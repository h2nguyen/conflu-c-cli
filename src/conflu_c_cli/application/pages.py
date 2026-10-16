"""Use cases that read pages: view, list, tree and versions."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from ..domain.errors import UsageError
from ..domain.model import Page, PageRef, Space, TreeNode, VersionInfo, parse_page_id, parse_space_key
from ..domain.privacy import hide_users, hide_version, redact_text, strip_users
from ..domain.sections import Heading, extract_section, truncate
from ..domain.sections import outline as outline_of
from ..domain.tree import arrange
from .comments import CommentView, present_comments, read_comments
from .paging import PAGE_SIZE, ensure_users_allowed, fetch_all, name_users, named
from .ports import ConfluenceGateway, Diagnostics
from .refs import resolve_page_ref
from .rendering import BODY_FORMATS, Body, check_format, render_body
from .settings import Settings


@dataclass
class PageView:
    page: Page  # without the body, which is in `body`; without people unless they are shown
    body: Body | None
    comments: list[CommentView]
    users_shown: bool
    comments_shown: bool
    raw: dict[str, Any] | None = None
    outline: tuple[Heading, ...] | None = None  # the headings, when only the outline was asked for


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
    ) -> PageView:
        page_id = resolve_page_ref(self._gateway, self._settings, ref, space=space)
        ensure_users_allowed(with_users, self._settings)
        check_format(body_format, BODY_FORMATS)
        self._check_parts(body_format, with_body, outline, section, max_chars)
        page = self._gateway.get_page(page_id, with_body=with_body)
        if with_ancestors:
            page = replace(page, ancestors=self._gateway.list_ancestors(page_id))
        comments = read_comments(self._gateway, page_id, inline=False) if with_comments else []
        raw = page.raw if want_raw else None
        body = render_body(page.body, body_format, with_users=with_users) if page.body is not None else None
        headings: tuple[Heading, ...] | None = None
        if body is not None and outline:
            headings, body = tuple(outline_of(body.text)), None
        elif body is not None and (section or max_chars):
            if section:
                text, heading = extract_section(body.text, section)
                body = replace(body, text=text.rstrip("\n"), section=heading.title)  # as the text of a whole page ends
            if max_chars:
                before = len(body.text)  # of the whole page, or of the section when one was asked for
                text, cut = truncate(body.text, max_chars)
                if cut:
                    body = replace(body, text=text.rstrip("\n"), truncated=True, total_chars=before)
        if with_users:
            version_author = page.version.author if page.version else None
            known = name_users(self._gateway, self._diagnostics, [page.author, page.owner, version_author, *[c.author for c in comments]])
            version = replace(page.version, author=named(version_author, known)) if page.version else None
            page = replace(page, author=named(page.author, known), owner=named(page.owner, known), version=version)
            comments = [replace(comment, author=named(comment.author, known)) for comment in comments]
        else:
            page = hide_users(page)
            raw = strip_users(raw) if raw is not None else None
        views = present_comments(comments, body_format, with_users=with_users)
        return PageView(replace(page, body=None, comments=[]), body, views, with_users, with_comments, raw, headings)

    @staticmethod
    def _check_parts(body_format: str, with_body: bool, outline: bool, section: str, max_chars: int) -> None:
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


@dataclass
class PageList:
    pages: list[Page]
    next_cursor: str
    space: Space | None
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

        if fetch_everything:
            pages, truncated = fetch_all(read)
            return PageList([hide_users(page) for page in pages], "", chosen, truncated)
        chunk = read(cursor)
        return PageList([hide_users(page) for page in chunk.items], chunk.cursor, chosen)


@dataclass
class TreeResult:
    root: PageRef
    space_key: str
    nodes: list[TreeNode]
    depth: int
    truncated: bool = False


class TreePages:
    def __init__(self, gateway: ConfluenceGateway, settings: Settings) -> None:
        self._gateway = gateway
        self._settings = settings

    def execute(self, ref: str, *, depth: int = 3, space: str = "") -> TreeResult:
        page_id = resolve_page_ref(self._gateway, self._settings, ref, space=space)
        if not 1 <= depth <= 10:
            raise UsageError("--depth must be between 1 and 10.")
        root = self._gateway.get_page(page_id, with_body=False)
        nodes, truncated = fetch_all(lambda cursor: self._gateway.list_descendants(page_id, depth=depth, limit=PAGE_SIZE, cursor=cursor))
        clean = [replace(node, title=redact_text(node.title)) for node in nodes]
        return TreeResult(PageRef(root.id, redact_text(root.title), "page", root.status), root.space_key, arrange(clean, page_id), depth, truncated)


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
        page = self._gateway.get_page(page_id, with_body=False)

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
