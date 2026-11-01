"""Use cases around comments: reading the conversations on a page (all of them or the recent ones), reading one, adding to them, changing one and resolving an inline one."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Sequence

from ..domain.comments import (
    RESOLUTIONS,
    CommentRecord,
    author_ref,
    check_expected_version,
    describe_change,
    edit_payload,
    ensure_comment_unchanged_since,
    ensure_comment_version,
    markers_added,
    parse_comment_id,
    parse_since,
    same_text,
    select_comments,
)
from ..domain.errors import AuthError, ConfluCliError, ConflictError, NotFoundError, UsageError, ValidationError
from ..domain.model import Chunk, Comment, parse_page_id
from ..domain.payloads import comment_payload
from ..domain.privacy import hide_comment_author
from ..domain.structure import hide_people_in_payload
from ..domain.timeutil import parse_timestamp
from .containers import not_a_page
from .paging import PAGE_SIZE, fetch_all, ensure_users_allowed, name_users, named
from .ports import Clock, ConfluenceGateway, Diagnostics
from .rendering import INPUT_FORMATS, BODY_FORMATS, Body, check_format, markdown_limits, markdown_round_trip, render_body, storage_from_input
from .services import Services
from .settings import Settings


@dataclass(frozen=True)
class CommentView:
    comment: Comment  # without the body, which is in `body`; without the author unless people are shown
    body: Body
    author_ref: str | None = None  # a pseudonym for the author, the same in every command that has the same token; None without a token or an author
    by_me: bool | None = None  # whether the user of the token wrote it; None when that is not known


def read_comments(gateway: ConfluenceGateway, page_id: str, *, inline: bool, resolution: str = "") -> list[Comment]:
    """The comments of a page, each conversation as its first comment followed by the replies. With a `resolution`: the inline conversations
    that are in that state."""

    def read_roots(cursor: str) -> Chunk[Comment]:
        if resolution:
            return gateway.list_inline_comments(page_id, resolution=resolution, limit=PAGE_SIZE, cursor=cursor)
        return gateway.list_comments(page_id, inline=inline, limit=PAGE_SIZE, cursor=cursor)

    try:
        roots, _ = fetch_all(read_roots)
    except NotFoundError as error:  # an id that is a folder or a blog post says what it is
        raise not_a_page(gateway, page_id, error) from error
    found: list[Comment] = []
    for root in roots:
        found.append(root)
        replies, _ = fetch_all(lambda cursor, root=root: gateway.list_replies(root.id, inline=inline or bool(resolution), limit=PAGE_SIZE, cursor=cursor))
        found.extend(replies)
    return found


def present_comments(comments: Sequence[Comment], fmt: str, *, with_users: bool) -> list[CommentView]:
    views = []
    for comment in comments:
        body = render_body(comment.body, fmt, with_users=with_users)
        shown = comment if with_users else hide_comment_author(comment)
        views.append(CommentView(replace(shown, body=""), body))
    return views


class ListComments:
    def __init__(self, gateway: ConfluenceGateway, settings: Settings, diagnostics: Diagnostics) -> None:
        self._gateway = gateway
        self._settings = settings
        self._diagnostics = diagnostics

    def execute(self, ref: str, *, inline: bool = False, body_format: str = "markdown", with_users: bool = False) -> list[CommentView]:
        page_id = parse_page_id(ref)
        ensure_users_allowed(with_users, self._settings)
        check_format(body_format, BODY_FORMATS)
        comments = read_comments(self._gateway, page_id, inline=False)
        if inline:
            comments += read_comments(self._gateway, page_id, inline=True)
        if with_users:
            known = name_users(self._gateway, self._diagnostics, [comment.author for comment in comments])
            comments = [replace(comment, author=named(comment.author, known)) for comment in comments]
        return present_comments(comments, body_format, with_users=with_users)


@dataclass
class CommentResult:
    page_id: str
    payload: dict[str, Any]
    dry_run: bool
    comment_id: str = ""


class AddComment:
    def __init__(self, gateway: ConfluenceGateway) -> None:
        self._gateway = gateway

    def execute(self, ref: str, body: str, *, body_format: str = "markdown", reply_to: str | None = None, dry_run: bool = False) -> CommentResult:
        page_id = parse_page_id(ref)
        check_format(body_format, INPUT_FORMATS)
        if not body.strip():
            raise ValidationError("The comment is empty.", hint="Pass text with --text or --file.")
        if reply_to is not None:
            reply_to = parse_comment_id(reply_to, "--reply-to")  # an empty value is an error: it must not turn into a comment of its own
        payload = comment_payload(page_id, storage_from_input(body, body_format), reply_to or "")
        try:
            if reply_to:
                _read(self._gateway, page_id, reply_to)  # the answer names its parent and not the page, so the parent proves both: it must be a comment of this page
            elif dry_run:
                self._gateway.get_page(page_id, with_body=False)  # proves that the page exists
            if dry_run:
                return CommentResult(page_id, payload, True)
            created = self._gateway.add_comment(payload)
        except NotFoundError as error:
            if reply_to:
                raise  # it is the parent that was not found, and `_read` says so
            raise not_a_page(self._gateway, page_id, error) from error  # an id that is a folder or a blog post says what it is
        return CommentResult(page_id, payload, False, created.id)


def _identity(gateway: ConfluenceGateway, diagnostics: Diagnostics) -> str:
    """The account id of the user of the token, or an empty text when that cannot be read (one request; a warning says that it failed)."""
    try:
        return gateway.current_user().account_id
    except ConfluCliError as error:
        diagnostics.warn(f"Could not tell which comments are yours: {error.message}")
        return ""


def _by_me(comment: Comment, me: str) -> bool | None:
    account = comment.author.account_id if comment.author else ""
    return account == me if account and me else None


def _present(
    gateway: ConfluenceGateway,
    settings: Settings,
    diagnostics: Diagnostics,
    comments: list[Comment],
    fmt: str,
    *,
    with_users: bool,
) -> list[CommentView]:
    """The comments as they may be printed. Each has `by_me` and `author_ref`, which say who wrote it without a name; the author and the people in
    the text stay out unless they may be shown. The user of the token is asked for once, and only when there are comments."""
    if not comments:
        return []
    me = _identity(gateway, diagnostics)
    shown = comments
    if with_users:
        known = name_users(gateway, diagnostics, [comment.author for comment in comments])
        shown = [replace(comment, author=named(comment.author, known)) for comment in comments]
    views = present_comments(shown, fmt, with_users=with_users)
    return [
        replace(view, author_ref=author_ref(settings.api_token, settings.wiki_url, comment.author.account_id if comment.author else ""), by_me=_by_me(comment, me))
        for view, comment in zip(views, comments)
    ]


@dataclass
class CommentList:
    page_id: str
    total: int  # the comments that the page has, of the kind that was asked for, before `since` and `last` chose among them
    comments: list[CommentView] = field(default_factory=list)
    since: str = ""  # the moment that `since` named, ISO 8601; empty without it


class FindComments:
    """The comments of a page, all of them or the recent ones, each with `by_me` and a pseudonym of its author."""

    def __init__(self, gateway: ConfluenceGateway, settings: Settings, diagnostics: Diagnostics, clock: Clock) -> None:
        self._gateway = gateway
        self._settings = settings
        self._diagnostics = diagnostics
        self._clock = clock

    def execute(
        self,
        ref: str,
        *,
        inline: bool = False,
        body_format: str = "markdown",
        with_users: bool = False,
        since: str | None = None,
        last: int = 0,
        resolution: str | None = None,
    ) -> CommentList:
        """`since` is a time ago, a date or an ISO time; `last` keeps the newest N of what `since` lets through. Both look at the time a comment was
        saved, which is when it was written unless somebody changed it. A `resolution` asks for the inline comments in that state, and only those:
        a footer comment has none. A `since` or a `resolution` that is given and empty is an error, never "not given"."""
        page_id = parse_page_id(ref)
        ensure_users_allowed(with_users, self._settings)
        check_format(body_format, BODY_FORMATS)
        if resolution is not None and resolution not in RESOLUTIONS:
            shown = resolution if len(resolution) <= 40 else resolution[:39] + "…"
            raise UsageError(f"Unknown value for --resolution: {shown or '<missing>'}", hint=f"Use one of: {', '.join(RESOLUTIONS)}.")
        if last < 0:
            raise UsageError("--last must be at least 1.", hint="--last 3 lists the three newest comments.")
        cutoff = parse_since(since, self._clock.now()) if since is not None else None  # an empty value is a mistake, not "no time"
        if resolution is not None:
            comments = read_comments(self._gateway, page_id, inline=True, resolution=resolution)
        else:
            comments = read_comments(self._gateway, page_id, inline=False)
            if inline:
                comments += read_comments(self._gateway, page_id, inline=True)
        chosen = select_comments(comments, since=cutoff, last=last)
        views = _present(self._gateway, self._settings, self._diagnostics, chosen, body_format, with_users=with_users)
        return CommentList(page_id, len(comments), views, cutoff.isoformat() if cutoff else "")


def _missing(page_id: str, comment_id: str, cause: NotFoundError | None) -> NotFoundError:
    return NotFoundError(
        f"No comment {comment_id} on page {page_id}.",
        hint=f"`conflu comments {page_id} --inline --json` lists the comments of the page with their ids.",
        details={**(cause.details if cause else {}), "pageId": page_id, "commentId": comment_id},
    )


def _read(gateway: ConfluenceGateway, page_id: str, comment_id: str) -> CommentRecord:
    """The comment, which must be on this page: a comment of another page is as good as none, and is not told apart from one."""
    try:
        record = gateway.get_comment(comment_id)
    except NotFoundError as error:
        raise _missing(page_id, comment_id, error) from error
    if record.page_id != page_id:
        raise _missing(page_id, comment_id, None)
    return record


class GetComment:
    """One comment of a page: its version and time, its text, whether it is yours and a pseudonym of its author."""

    def __init__(self, gateway: ConfluenceGateway, settings: Settings, diagnostics: Diagnostics) -> None:
        self._gateway = gateway
        self._settings = settings
        self._diagnostics = diagnostics

    def execute(self, ref: str, comment_id: str, *, body_format: str = "markdown", with_users: bool = False) -> CommentView:
        page_id, comment_id = parse_page_id(ref), parse_comment_id(comment_id, "--get")
        ensure_users_allowed(with_users, self._settings)
        check_format(body_format, BODY_FORMATS)
        comment = _read(self._gateway, page_id, comment_id).comment
        return _present(self._gateway, self._settings, self._diagnostics, [comment], body_format, with_users=with_users)[0]


@dataclass
class CommentChange:
    page_id: str
    comment_id: str
    kind: str  # footer | inline
    action: str  # updated | resolved | reopened | unchanged
    dry_run: bool
    payload: dict[str, Any] | None  # what is sent, or would be in a dry run; None when nothing is. When `redacted`: a copy without the people in the text
    version_from: int
    version_to: int
    updated: str  # when the comment was saved last: by this change, else as it is now
    resolution: str = ""  # an inline comment: its state after the change (what it would be in a dry run, what it is when nothing changes)
    by_me: bool | None = None  # a dry run of a change of the text: whether the user of the token wrote the comment
    diff: str = ""  # what a change of the text changes, as a unified diff of the two texts as Markdown without people
    lost: tuple[str, ...] = ()  # what a replacement from Markdown drops from the old text (only with --force)
    warnings: list[str] = field(default_factory=list)
    redacted: bool = False  # `payload` is the request without the people and addresses in the comment's text (resolving and reopening send that text back), not what is sent


def _state(comment: Comment) -> bool | None:
    """`resolved` as the update of a comment says it: for an inline comment whether it is resolved, for a footer comment nothing."""
    return comment.resolution == "resolved" if comment.kind == "inline" else None


def _refuse_dangling(comment: Comment, page_id: str) -> None:
    if comment.resolution == "dangling":
        raise ValidationError(
            f"Comment {comment.id} is dangling: the text on the page that it was made on is gone, and the API description says that a dangling comment cannot be updated.",
            hint=f"Add a new comment with `conflu comment {page_id} --text ...`.",
        )


_DENIED = (
    "Confluence lets a person change only their own comments, and the account needs the permission to add comments in the space. "
    "`conflu comment PAGE --get ID` says whether it is yours (byMe); add a new comment, or an answer with --reply-to, instead."
)
_DENIED_AS_MISSING = (
    "The comment was read a moment ago, so this is most likely how Confluence refuses a change that the account may not make: its API description "
    "answers 404 for a user who may view a comment but is forbidden from updating it. " + _DENIED
)


def _save(gateway: ConfluenceGateway, page_id: str, comment: Comment, payload: dict[str, Any]) -> Comment:
    """Sends the change. Confluence's own message of a refusal stays; what to do about it is added."""
    try:
        return gateway.update_comment(comment.id, comment.kind, payload)
    except AuthError as error:
        if error.details.get("status") != 403:
            raise
        raise AuthError(error.message, hint=f"{_DENIED} {error.hint}".strip(), details=error.details) from error
    except NotFoundError as error:
        raise NotFoundError(error.message, hint=_DENIED_AS_MISSING, details=error.details) from error
    except ConflictError as error:
        raise ConflictError(
            error.message,
            hint=f"The comment changed while you worked on it. Read it again with `conflu comment {page_id} --get {comment.id}` and decide again.",
            details={**error.details, "pageId": page_id, "commentId": comment.id},
        ) from error


@dataclass(frozen=True)
class Guards:
    """What a change of a comment checks before it sends anything: the version that the caller read, and the moment after which the comment must
    not have been saved. Either may be missing."""

    version: int | None = None
    since: datetime | None = None

    @classmethod
    def of(cls, if_version: int | None, if_unchanged_since: str | None) -> "Guards":
        """A guard that is given but empty is a mistake and is refused: silently going without it would write where the caller wanted to be stopped."""
        check_expected_version(if_version)
        if if_unchanged_since is not None and not if_unchanged_since.strip():
            raise ValidationError(
                "--if-unchanged-since is empty: it needs a time.",
                hint="Write it as ISO 8601, for example 2026-10-15T08:07:04Z, or leave the option out to go without the guard.",
            )
        return cls(if_version, parse_timestamp(if_unchanged_since) if if_unchanged_since is not None else None)

    @property
    def any(self) -> bool:
        return self.version is not None or self.since is not None

    def check(self, page_id: str, comment: Comment) -> None:
        if self.version is not None:
            ensure_comment_version(page_id, comment, self.version)
        if self.since is not None:
            ensure_comment_unchanged_since(page_id, comment, self.since)


class EditComment:
    """Replaces the text of a comment and keeps what else it is: an inline comment stays resolved or open. The old text stays in the versions of the
    comment, and a comment is never deleted."""

    def __init__(self, gateway: ConfluenceGateway, diagnostics: Diagnostics) -> None:
        self._gateway = gateway
        self._diagnostics = diagnostics

    def execute(
        self,
        ref: str,
        comment_id: str,
        text: str,
        *,
        body_format: str = "markdown",
        dry_run: bool = False,
        if_version: int | None = None,
        if_unchanged_since: str | None = None,
        force: bool = False,
    ) -> CommentChange:
        page_id, comment_id = parse_page_id(ref), parse_comment_id(comment_id, "--edit")
        check_format(body_format, INPUT_FORMATS)
        if not text.strip():
            raise ValidationError(
                "The new text of the comment is empty.",
                hint="Pass the text with --text or --file. This CLI neither deletes a comment nor empties one.",
            )
        guards = Guards.of(if_version, if_unchanged_since)
        current = _read(self._gateway, page_id, comment_id).comment
        _refuse_dangling(current, page_id)
        new_body = storage_from_input(text, body_format)
        added = markers_added(current.body, new_body)
        if added:
            raise ValidationError(
                f"The new text holds {' and '.join(added)}, which stands in place of an address or a profile link that the CLI hides when it shows "
                "a comment: sending it would overwrite the real one.",
                hint="Write the real address or link, or leave that part out. A comment that holds them is best changed in Confluence itself.",
                details={"markers": added},
            )
        guards.check(page_id, current)
        from_markdown = body_format == "markdown"
        if same_text(current.body, new_body) or (from_markdown and markdown_round_trip(current.body) == new_body):
            return CommentChange(page_id, comment_id, current.kind, "unchanged", dry_run, None, current.version, current.version, current.updated, current.resolution)
        lost = markdown_limits(current.body) if from_markdown else ()
        if lost and not force:
            raise ValidationError(
                f"Replacing the comment with Markdown would lose what Markdown cannot say: {', '.join(lost)}.",
                hint="Give the new text in storage format (--format storage), or replace it anyway with --force.",
                details={"lost": list(lost)},
            )
        number = current.version + 1
        payload = edit_payload(number, new_body, resolved=_state(current))
        diff = describe_change(render_body(current.body, "markdown", with_users=False).text, render_body(new_body, "markdown", with_users=False).text)
        if dry_run:
            mine = _by_me(current, _identity(self._gateway, self._diagnostics))
            warnings = ["Somebody else wrote this comment: Confluence refuses a change of its text (HTTP 403)."] if mine is False else []
            return CommentChange(page_id, comment_id, current.kind, "updated", True, payload, current.version, number, current.updated, current.resolution, mine, diff, lost, warnings)
        if guards.any:  # read again right before the write: the comment may have changed since the first read
            current = _read(self._gateway, page_id, comment_id).comment
            guards.check(page_id, current)
            number = current.version + 1
            payload = edit_payload(number, new_body, resolved=_state(current))
        saved = _save(self._gateway, page_id, current, payload)
        updated = saved.updated or current.updated
        return CommentChange(page_id, comment_id, current.kind, "updated", False, payload, current.version, max(saved.version, number), updated, saved.resolution or current.resolution, None, diff, lost)


class ResolveComment:
    """Resolves an inline comment or opens it again. Its text stays as it is: the change sends the comment's own text back, which came from Confluence and
    may name people: the request that is shown leaves them out unless they are asked for, and what is sent is always the comment as it is."""

    def __init__(self, gateway: ConfluenceGateway, settings: Settings) -> None:
        self._gateway = gateway
        self._settings = settings

    def execute(
        self,
        ref: str,
        comment_id: str,
        *,
        resolved: bool,
        dry_run: bool = False,
        if_version: int | None = None,
        if_unchanged_since: str | None = None,
        with_users: bool = False,
    ) -> CommentChange:
        page_id, comment_id = parse_page_id(ref), parse_comment_id(comment_id, "--resolve" if resolved else "--reopen")
        ensure_users_allowed(with_users, self._settings)
        guards = Guards.of(if_version, if_unchanged_since)
        current = _read(self._gateway, page_id, comment_id).comment
        word = "resolved" if resolved else "reopened"
        if current.kind != "inline":
            raise UsageError(
                f"Comment {comment_id} is a footer comment: only an inline comment can be {word}.",
                hint=f"A footer comment is answered with a reply: `conflu comment {page_id} --text ... --reply-to {comment_id}`.",
            )
        _refuse_dangling(current, page_id)
        guards.check(page_id, current)
        if (current.resolution == "resolved") == resolved:
            return CommentChange(page_id, comment_id, "inline", "unchanged", dry_run, None, current.version, current.version, current.updated, current.resolution)
        number = current.version + 1
        payload = edit_payload(number, current.body, resolved=resolved)
        shown = payload if with_users else hide_people_in_payload(payload)  # what is sent is `payload`; what is printed does not name the people in the text
        if dry_run:
            return CommentChange(page_id, comment_id, "inline", word, True, shown, current.version, number, current.updated, word, redacted=shown != payload)
        if guards.any:  # read again right before the write: the comment may have changed since the first read
            current = _read(self._gateway, page_id, comment_id).comment
            guards.check(page_id, current)
            if (current.resolution == "resolved") == resolved:
                return CommentChange(page_id, comment_id, "inline", "unchanged", False, None, current.version, current.version, current.updated, current.resolution)
            number = current.version + 1
            payload = edit_payload(number, current.body, resolved=resolved)
            shown = payload if with_users else hide_people_in_payload(payload)
        saved = _save(self._gateway, page_id, current, payload)
        return CommentChange(
            page_id, comment_id, "inline", word, False, shown, current.version, max(saved.version, number), saved.updated or current.updated, saved.resolution or word, redacted=shown != payload
        )


@dataclass
class CommentsUseCases:
    """The use cases that are not fields of `Application` by themselves: the list with its filters, one comment, a change of its text and the
    resolution of an inline comment. Reached as `app.comments.<name>`."""

    find: FindComments
    get: GetComment
    edit: EditComment
    resolution: ResolveComment


def build(services: Services) -> CommentsUseCases:
    gateway, settings, diagnostics = services.gateway, services.settings, services.diagnostics
    return CommentsUseCases(
        find=FindComments(gateway, settings, diagnostics, services.clock),
        get=GetComment(gateway, settings, diagnostics),
        edit=EditComment(gateway, diagnostics),
        resolution=ResolveComment(gateway, settings),
    )
