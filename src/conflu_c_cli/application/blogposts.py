"""Use cases around blog posts: list, read, create and change."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from ..domain.blogposts import (
    BlogpostDraft,
    create_blogpost_payload,
    ensure_blogpost_unchanged_since,
    ensure_blogpost_version,
    update_blogpost_payload,
    validate_blogpost_title,
)
from ..domain.content import describe, kind_named, parse_content_id
from ..domain.drafts import PageChanges, combine_body, normalize_labels
from ..domain.errors import ConfluCliError, NotFoundError, UsageError, ValidationError
from ..domain.model import Comment, Page, Space, parse_space_key
from ..domain.payloads import label_payload
from ..domain.privacy import hide_space, hide_users
from ..domain.structure import hide_people_in_payload
from ..domain.timeutil import parse_guard_time
from .pages import PageView, check_body_options, present_view, shape_body
from .paging import PAGE_SIZE, ensure_users_allowed, fetch_all
from .ports import ConfluenceGateway, Diagnostics
from .rendering import markdown_limits, markdown_round_trip
from .services import Services
from .settings import Settings


def space_key(space: str | None, settings: Settings) -> str:
    """The key of the space to work in: the one that was named, else the current one (which may be none). A name that is empty is a mistake, never "not named"."""
    if space is None:
        return settings.space
    if not space.strip():
        raise UsageError("The space is empty.", hint="Pass a space key such as ENG, or leave out --space to use the current space (`conflu use KEY`).")
    return space


def read_blogpost_comments(gateway: ConfluenceGateway, blogpost_id: str) -> list[Comment]:
    """The comments of a blog post, the footer comments and then the inline ones, each conversation as its first comment followed by the replies."""
    found: list[Comment] = []
    for inline in (False, True):
        roots, _ = fetch_all(lambda cursor, inline=inline: gateway.list_blogpost_comments(blogpost_id, inline=inline, limit=PAGE_SIZE, cursor=cursor))
        for root in roots:
            found.append(root)
            replies, _ = fetch_all(lambda cursor, root=root, inline=inline: gateway.list_replies(root.id, inline=inline, limit=PAGE_SIZE, cursor=cursor))
            found.extend(replies)
    return found


@dataclass
class BlogpostList:
    blogposts: list[Page]
    next_cursor: str
    space: Space | None  # as it may be printed (`privacy.hide_space`): the key of a personal space is `[hidden]`
    truncated: bool = False


class ListBlogposts:
    def __init__(self, gateway: ConfluenceGateway, settings: Settings) -> None:
        self._gateway = gateway
        self._settings = settings

    def execute(
        self,
        *,
        space: str | None = None,
        title: str | None = None,
        status: str = "current",
        sort: str = "",
        limit: int = 25,
        cursor: str = "",
        fetch_everything: bool = False,
    ) -> BlogpostList:
        key = space_key(space, self._settings)
        if title is not None and not title.strip():
            raise UsageError("The title is empty.", hint="Leave out --title to list every blog post.")
        chosen = self._gateway.get_space(parse_space_key(key)) if key else None

        def read(next_cursor: str):
            return self._gateway.list_blogposts(
                space_id=chosen.id if chosen else "", title=title or "", status=status, sort=sort, limit=PAGE_SIZE if fetch_everything else limit, cursor=next_cursor
            )

        shown = hide_space(chosen) if chosen else None
        if fetch_everything:
            posts, truncated = fetch_all(read)
            return BlogpostList([hide_users(post) for post in posts], "", shown, truncated)
        chunk = read(cursor)
        return BlogpostList([hide_users(post) for post in chunk.items], chunk.cursor, shown)


class ViewBlogpost:
    def __init__(self, gateway: ConfluenceGateway, settings: Settings, diagnostics: Diagnostics) -> None:
        self._gateway = gateway
        self._settings = settings
        self._diagnostics = diagnostics

    def execute(
        self,
        ref: str,
        *,
        body_format: str = "markdown",
        with_body: bool = True,
        with_comments: bool = False,
        with_users: bool = False,
        want_raw: bool = False,
        outline: bool = False,
        section: str = "",
        max_chars: int = 0,
    ) -> PageView:
        blogpost_id = parse_content_id(ref)
        ensure_users_allowed(with_users, self._settings)
        check_body_options(body_format, with_body, outline, section, max_chars)
        post = self._read(blogpost_id, with_body)
        post = replace(post, labels=self._gateway.list_blogpost_labels(blogpost_id))
        comments = read_blogpost_comments(self._gateway, blogpost_id) if with_comments else []
        body, headings = shape_body(post.body, body_format, with_users=with_users, outline=outline, section=section, max_chars=max_chars)
        return present_view(
            self._gateway,
            self._diagnostics,
            post,
            comments,
            body=body,
            headings=headings,
            raw=post.raw if want_raw else None,
            body_format=body_format,
            with_users=with_users,
            with_comments=with_comments,
        )

    def _read(self, blogpost_id: str, with_body: bool) -> Page:
        try:
            return self._gateway.get_blogpost(blogpost_id, with_body=with_body)
        except NotFoundError as error:
            raise explain_missing(self._gateway, blogpost_id, error) from error


def explain_missing(gateway: ConfluenceGateway, blogpost_id: str, error: NotFoundError) -> NotFoundError:
    """The error that says what the id is when it is no blog post (it is asked only after the blog post was not found), else the same error."""
    try:
        kind = gateway.content_types([blogpost_id]).get(blogpost_id)
    except ConfluCliError:
        return error
    if kind is None or kind == "blogpost":
        return error
    known = kind_named(kind)
    hint = f"Use `conflu {known.command} {blogpost_id}`." if known is not None and known.command else "`conflu blogposts --space KEY` lists the blog posts of a space."
    return NotFoundError(f"{blogpost_id} is {describe(kind)}, not a blog post.", hint=hint, details={**error.details, "blogpostId": blogpost_id, "type": kind})


@dataclass
class BlogpostWrite:
    action: str  # created | updated | unchanged
    blogpost: Page | None  # the blog post after the write, as it may be printed; None in a dry run of a creation
    payload: Any  # as it may be printed: for a change without --with-users a copy that does not name the people in the body
    dry_run: bool
    version_from: int = 0
    version_to: int = 0
    lost: tuple[str, ...] = ()  # what a replacement from Markdown dropped from the old body (only with --force)
    labels: list[str] = field(default_factory=list)
    redacted: bool = False  # `payload` is that copy and differs from what is sent


class CreateBlogpost:
    def __init__(self, gateway: ConfluenceGateway, settings: Settings) -> None:
        self._gateway = gateway
        self._settings = settings

    def execute(self, draft: BlogpostDraft, *, dry_run: bool = False) -> BlogpostWrite:
        key = space_key(draft.space, self._settings)
        if not key:
            raise UsageError("No space selected.", hint="Pass --space KEY or run `conflu use KEY`.")
        title = validate_blogpost_title(draft.title)
        labels = normalize_labels(draft.labels)
        space = self._gateway.get_space(parse_space_key(key))
        payload = create_blogpost_payload(space.id, title, draft.body)
        if dry_run:
            return BlogpostWrite("created", None, payload, True, 0, 1, labels=labels)
        post = self._gateway.create_blogpost(payload)
        if labels:
            try:
                self._gateway.add_blogpost_labels(post.id, label_payload(labels))
            except ConfluCliError as error:
                raise type(error)(
                    f"The blog post was created (id {post.id}), but its labels were not added: {error.message}",
                    hint="Add them in Confluence. `conflu label` works on pages only.",
                    details={**error.details, "blogpostId": post.id, "url": post.url},
                ) from error
        return BlogpostWrite("created", hide_users(post), payload, False, 0, post.version_number or 1, labels=labels)


class UpdateBlogpost:
    def __init__(self, gateway: ConfluenceGateway, settings: Settings) -> None:
        self._gateway = gateway
        self._settings = settings

    def execute(
        self,
        ref: str,
        changes: PageChanges,
        *,
        dry_run: bool = False,
        if_version: int | None = None,
        if_unchanged_since: str | None = None,
        force: bool = False,
        with_users: bool = False,
    ) -> BlogpostWrite:
        blogpost_id = parse_content_id(ref)
        ensure_users_allowed(with_users, self._settings)
        if if_unchanged_since is not None:
            parse_guard_time(if_unchanged_since)  # an empty value is an error naming the option, never "no guard": refused before anything is asked, in a dry run too
        if changes.is_empty():
            raise ValidationError("No changes given.", hint="Pass --title, or a body with --body or --file.")
        try:
            post = self._gateway.get_blogpost(blogpost_id, with_body=True)  # the body goes along even with a new title: the API has no call for the title alone
        except NotFoundError as error:
            raise explain_missing(self._gateway, blogpost_id, error) from error
        if post.status not in ("current", "draft"):
            raise ValidationError(f"Blog post {blogpost_id} is {post.status or 'not current'} and is not changed.", hint="Restore it in Confluence first.")
        current_version = post.version_number
        # As for pages: the new version number is the current one plus one, "unless you are updating the status to 'draft' which requires a version number of 1".
        next_version = 1 if post.status == "draft" else current_version + 1
        if if_version is not None:
            ensure_blogpost_version(blogpost_id, current_version, if_version)
        if if_unchanged_since is not None:
            ensure_blogpost_unchanged_since(blogpost_id, post.updated, if_unchanged_since)
        title = validate_blogpost_title(changes.title) if changes.title is not None else post.title
        current_body = post.body or ""
        new_body = current_body
        lost: tuple[str, ...] = ()
        if changes.body is not None:
            new_body = combine_body(current_body, changes.body, changes.body_mode)
            if changes.body_mode == "replace" and changes.from_markdown:
                if markdown_round_trip(current_body) == new_body:
                    new_body = current_body  # the blog post already says what this Markdown says
                else:
                    lost = markdown_limits(current_body)
                    if lost and not force:
                        raise ValidationError(
                            f"Replacing the body with Markdown would lose what Markdown cannot say: {', '.join(lost)}.",
                            hint="Add text with --append or --prepend, give the body in storage format (--format storage), "
                            "or replace it anyway with --force.",
                            details={"lost": list(lost)},
                        )
        if title == post.title and new_body == current_body:
            return BlogpostWrite("unchanged", self._printable(post, with_users), None, dry_run, current_version, current_version)
        payload = update_blogpost_payload(blogpost_id, title, new_body, next_version, changes.message, post.status)
        shown = payload if with_users else hide_people_in_payload(payload)  # what is sent is `payload`; what is printed does not name the people in the body
        redacted = shown != payload
        if dry_run:
            return BlogpostWrite("updated", self._printable(post, with_users), shown, True, current_version, next_version, lost, redacted=redacted)
        updated = self._gateway.update_blogpost(blogpost_id, payload)
        return BlogpostWrite(
            "updated", self._printable(updated, with_users), shown, False, current_version, updated.version_number or next_version, lost, redacted=redacted
        )

    @staticmethod
    def _printable(post: Page, with_users: bool) -> Page:
        return post if with_users else hide_users(post)


@dataclass
class BlogpostsUseCases:
    """The use cases of the area, reached as `app.blogposts.<name>`."""

    list_blogposts: ListBlogposts
    view_blogpost: ViewBlogpost
    create_blogpost: CreateBlogpost
    update_blogpost: UpdateBlogpost


def build(services: Services) -> BlogpostsUseCases:
    return BlogpostsUseCases(
        list_blogposts=ListBlogposts(services.gateway, services.settings),
        view_blogpost=ViewBlogpost(services.gateway, services.settings, services.diagnostics),
        create_blogpost=CreateBlogpost(services.gateway, services.settings),
        update_blogpost=UpdateBlogpost(services.gateway, services.settings),
    )
