"""Use cases that read pages: view, list and versions."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Sequence

from ..domain.errors import NotFoundError, UsageError, ValidationError
from ..domain.history import check_version_number
from ..domain.model import Attachment, Comment, Page, Space, User, VersionInfo, parse_page_id, parse_space_key
from ..domain.privacy import hide_space, hide_users, hide_version, redact_text, strip_users
from ..domain.sections import Heading, extract_section, truncate
from ..domain.sections import outline as outline_of
from .containers import not_a_page, with_titles
from .paging import PAGE_SIZE, ensure_users_allowed, fetch_all, name_users, named
from .ports import ConfluenceGateway, Diagnostics
from .refs import PAGE_REFERENCE, resolve_page_ref
from .rendering import BODY_FORMATS, Body, check_format, render_body
from .settings import Settings

# The comments are read for `--comments` only: their code is imported where it is used, so that a page without them does not load it (tests/test_startup.py).
if TYPE_CHECKING:
    from .comments import CommentView

BULK_PAGES = 250  # what one request for several pages takes (the REST API v2 limit of `limit`)


def read_page(gateway: ConfluenceGateway, page_id: str, *, with_body: bool) -> Page:
    """The page as it is now. An id that is a folder, a whiteboard, a database or a smart link is a not-found error whose hint says what it is."""
    try:
        return gateway.get_page(page_id, with_body=with_body)
    except NotFoundError as error:
        raise not_a_page(gateway, page_id, error) from error


@dataclass
class PageView:
    page: Page  # without the body, which is in `body`; without people unless they are shown
    body: Body | None
    comments: list[CommentView]
    users_shown: bool
    comments_shown: bool
    raw: dict[str, Any] | None = None
    outline: tuple[Heading, ...] | None = None  # the headings, when only the outline was asked for
    current_version: int = 0  # set when an earlier version was asked for: the number of the current one
    attachments: tuple[Attachment, ...] | None = None  # the files of the page, when they were asked for; their names and types without e-mail addresses unless people are shown
    labels_shown: bool = True  # False: the labels were not read (the request for several pages does not give them)


def check_body_options(body_format: str, with_body: bool, outline: bool, section: str, max_chars: int) -> None:
    """Refuse a combination of the options that shape a body that makes no sense, before anything is asked of Confluence."""
    check_format(body_format, BODY_FORMATS)
    if not (outline or section or max_chars):
        return
    if max_chars < 0:
        raise UsageError("--max-chars must not be negative.")
    if not with_body:
        raise UsageError("--outline, --section and --max-chars read the body.", hint="Leave out --no-body.")
    if outline and (section or max_chars):
        raise UsageError("--outline lists the headings and shows no body.", hint="Read a part with --section (and --max-chars) without --outline.")
    if (outline or section) and body_format != "markdown":
        raise UsageError("--outline and --section need the Markdown format, which has the headings.", hint="Leave out --format, or use --format markdown.")
    if max_chars and body_format == "storage":
        raise UsageError("--max-chars would cut the storage format in the middle of an element.", hint="Use --format markdown or text.")


def shape_body(storage: str | None, body_format: str, *, with_users: bool, outline: bool, section: str, max_chars: int) -> tuple[Body | None, tuple[Heading, ...] | None]:
    """The body as it is shown: in the format asked for, and with only the headings, one section or the start of it when that was asked for.
    The second value is the outline, when that is what was asked for (then there is no body)."""
    if storage is None:
        return None, None
    body = render_body(storage, body_format, with_users=with_users)
    if outline:
        return None, tuple(outline_of(body.text))
    if section:
        text, heading = extract_section(body.text, section)
        body = replace(body, text=text.rstrip("\n"), section=heading.title)  # as the text of a whole page ends
    if max_chars:
        before = len(body.text)  # of the whole page, or of the section when one was asked for
        text, cut = truncate(body.text, max_chars)
        if cut:
            body = replace(body, text=text.rstrip("\n"), truncated=True, total_chars=before)
    return body, None


def present_view(
    gateway: ConfluenceGateway,
    diagnostics: Diagnostics,
    page: Page,
    comments: list[Comment],
    *,
    body: Body | None,
    headings: tuple[Heading, ...] | None,
    raw: dict[str, Any] | None,
    body_format: str,
    with_users: bool,
    with_comments: bool,
    known: dict[str, User] | None = None,
) -> PageView:
    """What is read of a page or a blog post, as a reader may see it: people named only when they are shown, and hidden, with free text redacted,
    otherwise. `known` holds the names that were looked up already, for a command that reads several pages and asks for each person once."""
    if with_users:
        names = known if known is not None else {}
        version_author = page.version.author if page.version else None
        wanted = [page.author, page.owner, version_author, *[comment.author for comment in comments]]
        names.update(name_users(gateway, diagnostics, [user for user in wanted if user is not None and user.account_id not in names]))
        version = replace(page.version, author=named(version_author, names)) if page.version else None
        page = replace(page, author=named(page.author, names), owner=named(page.owner, names), version=version)
        comments = [replace(comment, author=named(comment.author, names)) for comment in comments]
    else:
        page = hide_users(page)
        raw = strip_users(raw) if raw is not None else None
    views = []
    if comments:
        from .comments import present_comments

        views = present_comments(comments, body_format, with_users=with_users)
    return PageView(replace(page, body=None, comments=[]), body, views, with_users, with_comments, raw, headings)


@dataclass(frozen=True)
class MissingPage:
    """A page of a call for several pages that could not be shown: what Confluence or the options said about it."""

    ref: str
    code: str
    message: str
    exit_code: int = 4
    hint: str = ""


@dataclass
class PagesView:
    """Several pages: one entry for each page asked for, in the order it was asked for, each page once."""

    entries: list[PageView | MissingPage]

    @property
    def pages(self) -> list[PageView]:
        return [item for item in self.entries if isinstance(item, PageView)]

    @property
    def errors(self) -> list[MissingPage]:
        return [item for item in self.entries if isinstance(item, MissingPage)]


@dataclass(frozen=True)
class _Options:
    body_format: str
    with_body: bool
    with_comments: bool
    with_users: bool
    with_ancestors: bool
    want_raw: bool
    outline: bool
    section: str
    max_chars: int
    with_attachments: bool


class ViewPage:
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
        with_ancestors: bool = False,
        want_raw: bool = False,
        outline: bool = False,
        section: str = "",
        max_chars: int = 0,
        space: str = "",
        version: int | None = None,
        with_attachments: bool = False,
    ) -> PageView:
        """One page: the current version, or an earlier one with `version`, which is read without comments and ancestors (they are the page's now)."""
        options = _Options(body_format, with_body, with_comments, with_users, with_ancestors, want_raw, outline, section, max_chars, with_attachments)
        self._check(options, version=version, several=False)
        page_id = resolve_page_ref(self._gateway, self._settings, ref, space=space)
        page, current = self._read(page_id, options, version)
        return self._present(page_id, page, current, options, {}, labels_shown=True)

    def execute_many(
        self,
        refs: Sequence[str],
        *,
        body_format: str = "markdown",
        with_body: bool = True,
        with_comments: bool = False,
        with_users: bool = False,
        with_ancestors: bool = False,
        outline: bool = False,
        section: str = "",
        max_chars: int = 0,
        space: str = "",
        version: int | None = None,
        with_attachments: bool = False,
        want_raw: bool = False,
    ) -> PagesView:
        """Several pages, with one request for the pages themselves (at most 250 ids at a time). A page that Confluence does not return is asked for
        on its own, so that "not found" is Confluence's answer to that page and not a filter of the list; a page that is not there, or whose
        section was asked for and is not in it, is an entry of the answer and no failure of the call. The labels are not read: the request
        for several pages does not give them."""
        if not refs:
            raise UsageError("No page given.", hint="Give a page id, the address of a page or a `page:KEY/Title` reference.")
        options = _Options(body_format, with_body, with_comments, with_users, with_ancestors, want_raw, outline, section, max_chars, with_attachments)
        self._check(options, version=version, several=True)  # this reads the pages as they are now, and has no raw form
        ids = self._resolve(refs, space)
        wanted = list(dict.fromkeys(item for item in ids if isinstance(item, str)))
        found = self._bulk(wanted, with_body)
        known: dict[str, User] = {}
        entries: list[PageView | MissingPage] = []
        shown: set[str] = set()
        for ref, item in zip(refs, ids):
            if isinstance(item, MissingPage):
                entries.append(item)
                continue
            if item in shown:
                continue
            shown.add(item)
            try:
                page = found[item] if item in found else read_page(self._gateway, item, with_body=with_body)
            except NotFoundError as error:
                entries.append(MissingPage(ref, error.code, error.message, error.exit_code, error.hint))
                continue
            try:
                entries.append(self._present(item, page, 0, options, known, labels_shown=False))
            except ValidationError as error:  # the section that was asked for is not in this page
                entries.append(MissingPage(ref, error.code, error.message, error.exit_code, error.hint))
        return PagesView(entries)

    # -- steps -----------------------------------------------------------------------------------

    def _check(self, options: _Options, *, version: int | None, several: bool) -> None:
        ensure_users_allowed(options.with_users, self._settings)
        check_body_options(options.body_format, options.with_body, options.outline, options.section, options.max_chars)
        if version is not None:
            check_version_number(version)
            if several:
                raise UsageError("--version reads one version of one page.", hint="Give one page, or leave out --version.")
            if options.with_comments or options.with_ancestors:
                raise UsageError(
                    "--version reads the page as it was saved: its comments and its place in the tree are those of now.",
                    hint="Leave out --comments and --ancestors (`conflu comments PAGE` shows the comments of the page now), or leave out --version.",
                )
        if several and options.want_raw:
            raise UsageError("--raw prints Confluence's own JSON of one page.", hint="Give one page, or leave out --raw.")

    def _resolve(self, refs: Sequence[str], space: str) -> list[str | MissingPage]:
        """The id of every page asked for, or what is wrong with it. An id that is not one is refused for the whole call, before anything is
        asked; a `page:` reference that names no page is an entry."""
        parsed = [None if ref.strip().casefold().startswith(PAGE_REFERENCE) else parse_page_id(ref) for ref in refs]
        found: list[str | MissingPage] = []
        for ref, page_id in zip(refs, parsed):
            if page_id is not None:
                found.append(page_id)
                continue
            try:
                found.append(resolve_page_ref(self._gateway, self._settings, ref, space=space))
            except NotFoundError as error:
                found.append(MissingPage(ref, error.code, error.message, error.exit_code, error.hint))
        return found

    def _bulk(self, ids: list[str], with_body: bool) -> dict[str, Page]:
        found: dict[str, Page] = {}
        for start in range(0, len(ids), BULK_PAGES):
            chunk = ids[start : start + BULK_PAGES]
            pages, _ = fetch_all(lambda cursor: self._gateway.get_pages(chunk, with_body=with_body, limit=BULK_PAGES, cursor=cursor))
            found.update({page.id: page for page in pages if page.id in chunk})
        return found

    def _read(self, page_id: str, options: _Options, version: int | None) -> tuple[Page, int]:
        """The page and, for an earlier version, the number of the current one (0 for the current version itself)."""
        if version is None:
            return read_page(self._gateway, page_id, with_body=options.with_body), 0
        current = read_page(self._gateway, page_id, with_body=False)
        newest = current.version_number
        hint = f"The page is at version {newest}. `conflu versions {page_id}` lists the versions it has."
        details = {"pageId": page_id, "version": version, "currentVersion": newest}
        if newest and version > newest:
            raise NotFoundError(f"Page {page_id} has no version {version}.", hint=hint, details=details)
        try:
            page = self._gateway.get_page_version(page_id, version, with_body=options.with_body)
        except NotFoundError as error:
            raise NotFoundError(f"Page {page_id} has no version {version}.", hint=hint, details={**error.details, **details}) from error
        # what belongs to the page and not to one of its versions is the page's now
        return replace(
            page, labels=current.labels, labels_incomplete=current.labels_incomplete, status=current.status, parent_id=current.parent_id, parent_type=current.parent_type
        ), newest

    def _attachments(self, page_id: str, *, with_users: bool) -> tuple[Attachment, ...]:
        found, _ = fetch_all(lambda cursor: self._gateway.list_attachments(page_id, limit=PAGE_SIZE, cursor=cursor))
        return tuple(found if with_users else [replace(item, title=redact_text(item.title), media_type=redact_text(item.media_type)) for item in found])  # a file name and a type can hold an e-mail address

    def _present(self, page_id: str, page: Page, current: int, options: _Options, known: dict[str, User], *, labels_shown: bool) -> PageView:
        if options.with_ancestors:
            page = replace(page, ancestors=with_titles(self._gateway, self._gateway.list_ancestors(page_id)))  # a folder in the path has no title in the answer
        comments = []
        if options.with_comments:
            from .comments import read_comments

            comments = read_comments(self._gateway, page_id, inline=False)
        body, headings = shape_body(
            page.body, options.body_format, with_users=options.with_users, outline=options.outline, section=options.section, max_chars=options.max_chars
        )
        view = present_view(
            self._gateway,
            self._diagnostics,
            page if labels_shown else replace(page, labels=[]),
            comments,
            body=body,
            headings=headings,
            raw=page.raw if options.want_raw else None,
            body_format=options.body_format,
            with_users=options.with_users,
            with_comments=options.with_comments,
            known=known,
        )
        attachments = self._attachments(page_id, with_users=options.with_users) if options.with_attachments else None
        if page.labels_incomplete and labels_shown:
            self._diagnostics.warn(f"Only the first {len(page.labels)} labels of the page are shown: the rest could not be read. `conflu labels {page_id}` lists them.")
        return replace(view, current_version=current, attachments=attachments, labels_shown=labels_shown)


@dataclass
class PageList:
    pages: list[Page]
    next_cursor: str
    space: Space | None  # as it may be printed (`privacy.hide_space`): the key of a personal space is `[hidden]`
    truncated: bool = False


class ListPages:
    def __init__(self, gateway: ConfluenceGateway, settings: Settings) -> None:
        self._gateway = gateway
        self._settings = settings

    def execute(
        self,
        *,
        space: str = "",
        title: str = "",
        status: str = "current",
        sort: str = "",
        root_only: bool = False,
        limit: int = 25,
        cursor: str = "",
        fetch_everything: bool = False,
    ) -> PageList:
        key = space or self._settings.space
        chosen = self._gateway.get_space(parse_space_key(key)) if key else None
        if root_only and chosen is None:
            raise UsageError("--root needs a space.", hint="Pass --space KEY or run `conflu use KEY`.")

        def read(next_cursor: str):
            return self._gateway.list_pages(
                space_id=chosen.id if chosen else "",
                title=title,
                status=status,
                sort=sort,
                root_only=root_only,
                limit=PAGE_SIZE if fetch_everything else limit,
                cursor=next_cursor,
            )

        shown = hide_space(chosen) if chosen else None
        if fetch_everything:
            pages, truncated = fetch_all(read)
            return PageList([hide_users(page) for page in pages], "", shown, truncated)
        chunk = read(cursor)
        return PageList([hide_users(page) for page in chunk.items], chunk.cursor, shown)


@dataclass
class VersionList:
    page_id: str
    title: str
    versions: list[VersionInfo]
    next_cursor: str = ""
    users_shown: bool = False


class ListVersions:
    def __init__(self, gateway: ConfluenceGateway, settings: Settings, diagnostics: Diagnostics) -> None:
        self._gateway = gateway
        self._settings = settings
        self._diagnostics = diagnostics

    def execute(self, ref: str, *, limit: int = 25, cursor: str = "", fetch_everything: bool = False, with_users: bool = False) -> VersionList:
        page_id = parse_page_id(ref)
        ensure_users_allowed(with_users, self._settings)
        page = read_page(self._gateway, page_id, with_body=False)

        def read(next_cursor: str):
            return self._gateway.list_versions(page_id, limit=PAGE_SIZE if fetch_everything else limit, cursor=next_cursor)

        if fetch_everything:
            versions, _ = fetch_all(read)
            next_cursor = ""
        else:
            chunk = read(cursor)
            versions, next_cursor = chunk.items, chunk.cursor
        if with_users:
            known = name_users(self._gateway, self._diagnostics, [version.author for version in versions])
            versions = [replace(version, author=named(version.author, known)) for version in versions]
        else:
            versions = [hide_version(version) for version in versions]  # type: ignore[misc]
        return VersionList(page_id, redact_text(page.title), versions, next_cursor, with_users)
