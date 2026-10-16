"""In-memory stand-ins for the ports: the use cases and the command line run without HTTP or files."""
from __future__ import annotations

import copy
import dataclasses
import fnmatch
import posixpath
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from conflu_c_cli.application.app import Application
from conflu_c_cli.application.ports import Clock, ConfigStore, ConfluenceGateway, Diagnostics, DocTopic, Docs, Files
from conflu_c_cli.application.settings import Settings
from conflu_c_cli.domain.errors import ConfluCliError, ConflictError, NotFoundError, ValidationError
from conflu_c_cli.domain.model import (
    Attachment,
    Chunk,
    Comment,
    Label,
    Page,
    PageRef,
    SearchHit,
    SearchPage,
    Space,
    TreeNode,
    User,
    VersionInfo,
)
from conflu_c_cli.version import __version__

BASE = "https://example.atlassian.net/wiki"
ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"
ALEX = User(ACCOUNT, "Alex Example", "alex@example.com")
CREATED = "2026-10-01T08:00:00.000Z"
UPDATED = "2026-10-10T09:00:00.000Z"

RELEASE_NOTES_BODY = (
    '<h1>Release notes</h1><p>Contact <ac:link><ri:user ri:account-id="5b10ac8d82e05b22cc7d4ef5" /></ac:link> '
    "or write to alex@example.com.</p><ul><li>First</li><li>Second</li></ul>"
    '<ac:structured-macro ac:name="toc" ac:schema-version="1" />'
)
ARCHITECTURE_BODY = (
    '<p>Overview</p><ac:structured-macro ac:name="code" ac:schema-version="1"><ac:parameter ac:name="language">python</ac:parameter>'
    '<ac:plain-text-body><![CDATA[print("hi")]]></ac:plain-text-body></ac:structured-macro>'
)


def sample_page(
    page_id: str,
    title: str,
    *,
    space_id: str = "1001",
    space_key: str = "ENG",
    parent_id: str = "",
    body: str = "<p>Text.</p>",
    version: int = 1,
    labels: tuple[str, ...] = (),
    message: str = "",
    status: str = "current",
) -> Page:
    slug = title.replace(" ", "+")
    url = f"{BASE}/spaces/{space_key}/pages/{page_id}/{slug}"
    return Page(
        id=page_id,
        title=title,
        status=status,
        space_id=space_id,
        space_key=space_key,
        parent_id=parent_id,
        created=CREATED,
        version=VersionInfo(version, UPDATED if version > 1 else CREATED, message, False, User(ACCOUNT)),
        author=User(ACCOUNT),
        owner=User(ACCOUNT),
        labels=[Label(name) for name in labels],
        body=body,
        url=url,
        raw={"id": page_id, "title": title, "authorId": ACCOUNT, "version": {"number": version, "authorId": ACCOUNT}},
    )


def default_spaces() -> dict[str, Space]:
    return {
        "ENG": Space("1001", "ENG", "Engineering", "global", "current", "Engineering documentation", "2001", "2026-09-01T08:00:00.000Z", f"{BASE}/spaces/ENG"),
        "DOCS": Space("1002", "DOCS", "Documentation", "global", "current", "", "3001", "2026-09-01T08:00:00.000Z", f"{BASE}/spaces/DOCS"),
    }


def default_pages() -> dict[str, Page]:
    pages = [
        sample_page("2001", "Engineering Home", body="<p>Welcome to engineering.</p>"),
        sample_page("2002", "Release notes", parent_id="2001", body=RELEASE_NOTES_BODY, version=3, labels=("release", "notes"), message="Added the October notes"),
        sample_page("2003", "Architecture", parent_id="2001", body=ARCHITECTURE_BODY),
        sample_page("2004", "ADR 0001", parent_id="2003", body="<p>Decision: use <strong>ports</strong> and adapters.</p>", version=2, labels=("adr",)),
        sample_page("2005", "Plain page", parent_id="2001", body="<p>Just a paragraph &amp; text.</p>"),
        sample_page("3001", "Docs Home", space_id="1002", space_key="DOCS", body="<p>Docs.</p>"),
    ]
    return {page.id: page for page in pages}


class FakeGateway(ConfluenceGateway):
    """A Confluence in memory. Every call is recorded in `calls`; `errors` makes a method fail."""

    def __init__(self) -> None:
        self.user = ALEX
        self.users = {ACCOUNT: ALEX}
        self.spaces = default_spaces()
        self.pages = default_pages()
        self.versions: dict[str, list[VersionInfo]] = {
            "2002": [
                VersionInfo(3, UPDATED, "Added the October notes", False, User(ACCOUNT)),
                VersionInfo(2, "2026-10-05T10:00:00.000Z", "", False, User(ACCOUNT)),
                VersionInfo(1, CREATED, "Created", False, User(ACCOUNT)),
            ]
        }
        self.comments: dict[str, list[Comment]] = {
            "2002": [
                Comment("4001", "footer", "2026-10-02T10:00:00.000Z", "<p>Looks good.</p>", 1, User(ACCOUNT)),
                Comment("4002", "footer", "2026-10-02T11:00:00.000Z", "<p>Thanks!</p>", 1, User(ACCOUNT), "4001"),
                Comment("4003", "inline", "2026-10-03T09:00:00.000Z", "<p>Check this phrase.</p>", 1, User(ACCOUNT), "", "open"),
            ]
        }
        self.attachments: dict[str, list[Attachment]] = {
            "2002": [
                Attachment("att5001", "diagram.png", "image/png", 10, "2026-10-04T08:00:00.000Z", 1, "2002", "/download/attachments/2002/diagram.png?version=1&api=v2"),
                Attachment("att5002", "notes.txt", "text/plain", 12, "2026-10-04T09:00:00.000Z", 1, "2002", "/download/attachments/2002/notes.txt?version=1&api=v2"),
            ]
        }
        self.attachment_data = {"att5001": b"PNGDATA123", "att5002": b"hello notes\n"}
        self.search_hits = [
            SearchHit("2002", "page", "Release notes", "ENG", f"{BASE}/spaces/ENG/pages/2002/Release+notes", "the october notes", UPDATED, "Engineering Home", ("release", "notes"), 3),
            SearchHit("2003", "page", "Architecture", "ENG", f"{BASE}/spaces/ENG/pages/2003/Architecture", "overview", CREATED, "Engineering Home", (), 1),
            SearchHit("2004", "page", "ADR 0001", "ENG", f"{BASE}/spaces/ENG/pages/2004/ADR+0001", "ports and adapters", CREATED, "Engineering Home > Architecture", ("adr",), 2),
        ]
        self.search_handler: Callable[[str], list[SearchHit]] | None = None  # answers a search by its CQL, instead of the fixed hits
        self.responses: dict[tuple[str, str], Any] = {}
        self.errors: dict[str, ConfluCliError] = {}
        self.calls: list[tuple[Any, ...]] = []
        self.page_cap = 2
        self.next_id = 20000

    # -- helpers -----------------------------------------------------------------------------

    def _enter(self, name: str, *args: Any) -> None:
        self.calls.append((name, *args))
        if name in self.errors:
            raise self.errors[name]

    def called(self, name: str) -> list[tuple[Any, ...]]:
        return [call for call in self.calls if call[0] == name]

    def _page(self, page_id: str) -> Page:
        if page_id not in self.pages:
            raise NotFoundError(f"Not found: GET /api/v2/pages/{page_id}")
        return self.pages[page_id]

    def _space_of(self, page: Page) -> Space:
        return next(space for space in self.spaces.values() if space.id == page.space_id)

    def _chunk(self, items: list[Any], cursor: str, limit: int) -> Chunk[Any]:
        start = int(cursor or 0)
        end = start + min(limit, self.page_cap)
        return Chunk(items[start:end], str(end) if end < len(items) else "")

    def _copy(self, page: Page, with_body: bool) -> Page:
        return dataclasses.replace(page, body=page.body if with_body else None, labels=list(page.labels), raw=copy.deepcopy(page.raw))

    def _new_id(self) -> str:
        self.next_id += 1
        return str(self.next_id)

    def _save_version(self, page: Page, number: int, message: str = "") -> None:
        minute = 10 + number
        page.version = VersionInfo(number, f"2026-10-15T08:{minute:02d}:00.000Z", message, False, User(ACCOUNT))

    # -- people ------------------------------------------------------------------------------

    def current_user(self) -> User:
        self._enter("current_user")
        return self.user

    def lookup_users(self, account_ids: Sequence[str]) -> dict[str, User]:
        self._enter("lookup_users", tuple(account_ids))
        return {account: self.users[account] for account in account_ids if account in self.users}

    # -- spaces ------------------------------------------------------------------------------

    def list_spaces(self, *, space_type: str = "", status: str = "current", limit: int = 25, cursor: str = "") -> Chunk[Space]:
        self._enter("list_spaces", space_type, status, limit, cursor)
        spaces = [space for space in self.spaces.values() if (not space_type or space.type == space_type) and space.status == status]
        return self._chunk(sorted(spaces, key=lambda space: space.key), cursor, limit)

    def get_space(self, key: str) -> Space:
        self._enter("get_space", key)
        for candidate in (key, key.upper()):
            if candidate in self.spaces:
                return self.spaces[candidate]
        raise NotFoundError(f"No space with the key {key}.")

    def get_space_by_id(self, space_id: str) -> Space:
        self._enter("get_space_by_id", space_id)
        for space in self.spaces.values():
            if space.id == space_id:
                return space
        raise NotFoundError(f"No space with the id {space_id}.")

    # -- pages -------------------------------------------------------------------------------

    def get_page(self, page_id: str, *, with_body: bool = True) -> Page:
        self._enter("get_page", page_id, with_body)
        return self._copy(self._page(page_id), with_body)

    def list_pages(
        self,
        *,
        space_id: str = "",
        ids: Sequence[str] = (),
        title: str = "",
        status: str = "current",
        sort: str = "",
        root_only: bool = False,
        with_body: bool = False,
        limit: int = 25,
        cursor: str = "",
    ) -> Chunk[Page]:
        self._enter("list_pages", space_id, tuple(ids), title, status, sort, root_only, with_body, limit, cursor)
        pages = [
            page
            for page in self.pages.values()
            if (not space_id or page.space_id == space_id)
            and (not ids or page.id in ids)
            and (not title or page.title.casefold() == title.casefold())
            and page.status == status
            and (not root_only or not page.parent_id)
        ]
        key = {"title": lambda p: p.title.casefold(), "id": lambda p: int(p.id), "modified-date": lambda p: p.updated}.get(sort.lstrip("-"), lambda p: int(p.id))
        pages.sort(key=key, reverse=sort.startswith("-"))
        chunk = self._chunk(pages, cursor, limit)
        return Chunk([self._copy(page, with_body) for page in chunk.items], chunk.cursor)

    def list_ancestors(self, page_id: str) -> list[PageRef]:
        self._enter("list_ancestors", page_id)
        chain: list[PageRef] = []
        page = self._page(page_id)
        while page.parent_id:
            page = self._page(page.parent_id)
            chain.append(PageRef(page.id, page.title))
        return list(reversed(chain))

    def list_descendants(self, page_id: str, *, depth: int = 3, limit: int = 250, cursor: str = "") -> Chunk[TreeNode]:
        self._enter("list_descendants", page_id, depth, limit, cursor)
        self._page(page_id)
        found: list[TreeNode] = []
        level = [page_id]
        for current in range(1, depth + 1):
            following: list[str] = []
            for parent in level:
                for position, page in enumerate(sorted((p for p in self.pages.values() if p.parent_id == parent), key=lambda p: p.title)):
                    found.append(TreeNode(page.id, page.title, "page", parent, current, "current", position))
                    following.append(page.id)
            level = following
        return self._chunk(found, cursor, limit)

    def list_versions(self, page_id: str, *, limit: int = 25, cursor: str = "") -> Chunk[VersionInfo]:
        self._enter("list_versions", page_id, limit, cursor)
        page = self._page(page_id)
        versions = self.versions.get(page_id) or ([page.version] if page.version else [])
        return self._chunk(list(versions), cursor, limit)

    def create_page(self, payload: dict[str, Any]) -> Page:
        self._enter("create_page", payload)
        space = next((space for space in self.spaces.values() if space.id == payload.get("spaceId")), None)
        if space is None:
            raise ValidationError("Unknown space")
        parent_id = payload.get("parentId") or space.homepage_id
        page = sample_page(self._new_id(), payload["title"], space_id=space.id, space_key=space.key, parent_id=parent_id, body=payload["body"]["value"], labels=())
        self._save_version(page, 1)
        self.pages[page.id] = page
        return self._copy(page, True)

    def update_page(self, page_id: str, payload: dict[str, Any]) -> Page:
        self._enter("update_page", page_id, payload)
        page = self._page(page_id)
        number = payload["version"]["number"]
        expected = 1 if payload.get("status") == "draft" else page.version_number + 1  # Atlassian: a draft is always version 1
        if number != expected:
            raise ConflictError("Confluence reports a conflict (HTTP 409): Version conflict.")
        page.title, page.body = payload["title"], payload["body"]["value"]
        self._save_version(page, number, payload["version"].get("message", ""))
        return self._copy(page, True)

    def update_title(self, page_id: str, payload: dict[str, Any]) -> Page:
        self._enter("update_title", page_id, payload)
        page = self._page(page_id)
        page.title = payload["title"]
        self._save_version(page, page.version_number + 1)
        return self._copy(page, False)

    def move_page(self, page_id: str, position: str, target_id: str) -> None:
        self._enter("move_page", page_id, position, target_id)
        page, target = self._page(page_id), self._page(target_id)
        page.parent_id = target.id if position == "append" else target.parent_id

    # -- comments ----------------------------------------------------------------------------

    def list_comments(self, page_id: str, *, inline: bool = False, limit: int = 50, cursor: str = "") -> Chunk[Comment]:
        self._enter("list_comments", page_id, inline, limit, cursor)
        self._page(page_id)
        kind = "inline" if inline else "footer"
        roots = [comment for comment in self.comments.get(page_id, []) if comment.kind == kind and not comment.parent_id]
        return self._chunk(roots, cursor, limit)

    def list_replies(self, comment_id: str, *, inline: bool = False, limit: int = 50, cursor: str = "") -> Chunk[Comment]:
        self._enter("list_replies", comment_id, inline, limit, cursor)
        replies = [comment for items in self.comments.values() for comment in items if comment.parent_id == comment_id]
        return self._chunk(replies, cursor, limit)

    def add_comment(self, payload: dict[str, Any]) -> Comment:
        self._enter("add_comment", payload)
        page_id = payload["pageId"]
        self._page(page_id)
        comment = Comment(self._new_id(), "footer", "2026-10-15T08:00:00.000Z", payload["body"]["value"], 1, ALEX, payload.get("parentCommentId", ""))
        self.comments.setdefault(page_id, []).append(comment)
        return comment

    # -- labels ------------------------------------------------------------------------------

    def list_labels(self, page_id: str) -> list[Label]:
        self._enter("list_labels", page_id)
        return list(self._page(page_id).labels)

    def add_labels(self, page_id: str, payload: list[dict[str, str]]) -> list[Label]:
        self._enter("add_labels", page_id, payload)
        page = self._page(page_id)
        for item in payload:
            if item["name"] not in {label.name for label in page.labels}:
                page.labels.append(Label(item["name"], item.get("prefix", "global")))
        return list(page.labels)

    def remove_label(self, page_id: str, name: str) -> None:
        self._enter("remove_label", page_id, name)
        page = self._page(page_id)
        if name not in {label.name for label in page.labels}:
            raise NotFoundError(f"No label {name}")
        page.labels = [label for label in page.labels if label.name != name]

    # -- attachments -------------------------------------------------------------------------

    def list_attachments(self, page_id: str, *, filename: str = "", limit: int = 50, cursor: str = "") -> Chunk[Attachment]:
        self._enter("list_attachments", page_id, filename, limit, cursor)
        self._page(page_id)
        items = [item for item in self.attachments.get(page_id, []) if not filename or item.title == filename]
        return self._chunk(items, cursor, limit)

    def get_attachment(self, attachment_id: str) -> Attachment:
        self._enter("get_attachment", attachment_id)
        for items in self.attachments.values():
            for item in items:
                if item.id == attachment_id:
                    return item
        raise NotFoundError(f"Not found: GET /api/v2/attachments/{attachment_id}")

    def upload_attachment(self, page_id: str, filename: str, data: bytes, *, comment: str = "", minor: bool = False) -> Attachment:
        self._enter("upload_attachment", page_id, filename, data, comment, minor)
        self._page(page_id)
        items = self.attachments.setdefault(page_id, [])
        existing = next((item for item in items if item.title == filename), None)
        if existing is not None:
            attachment = dataclasses.replace(existing, version=existing.version + 1, size=len(data), comment=comment)
            items[items.index(existing)] = attachment
        else:
            attachment = Attachment(f"att{self._new_id()}", filename, "application/octet-stream", len(data), "2026-10-15T08:00:00.000Z", 1, page_id, f"/download/attachments/{page_id}/{filename}", comment)
            items.append(attachment)
        self.attachment_data[attachment.id] = data
        return attachment

    def download_attachment(self, attachment: Attachment) -> bytes:
        self._enter("download_attachment", attachment.id)
        return self.attachment_data[attachment.id]

    # -- search and raw ----------------------------------------------------------------------

    def search(self, cql: str, *, limit: int = 25, start: int = 0) -> SearchPage:
        self._enter("search", cql, limit, start)
        size = min(limit, self.page_cap)
        source = self.search_handler(cql) if self.search_handler else self.search_hits
        hits = source[start : start + size]
        return SearchPage(hits, len(source), start, limit, [{"title": hit.title, "excerpt": hit.excerpt, "user": {"accountId": ACCOUNT, "displayName": "Alex Example"}} for hit in hits])

    def request(self, method: str, path: str, body: Any = None) -> Any:
        self._enter("request", method, path, body)
        return self.responses.get((method, path), {"ok": True, "user": {"accountId": ACCOUNT, "displayName": "Alex Example"}})


class MemoryConfigStore(ConfigStore):
    def __init__(self, values: Mapping[str, str] | None = None, path: str = "memory://config") -> None:
        self.values = dict(values or {})
        self._path = path

    @property
    def path(self) -> str:
        return self._path

    def load(self) -> dict[str, str]:
        return dict(self.values)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def unset(self, key: str) -> bool:
        return self.values.pop(key, None) is not None


class MemoryFiles(Files):
    def __init__(self, files: Mapping[str, str | bytes] | None = None) -> None:
        self.files: dict[str, bytes] = {}
        for path, content in (files or {}).items():
            self.files[path] = content.encode("utf-8") if isinstance(content, str) else content
        self.writes: list[str] = []

    def text(self, path: str) -> str:
        return self.files[path].decode("utf-8")

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        if path not in self.files:
            raise ValidationError(f"Cannot read {path}: no such file")
        return self.files[path].decode(encoding)

    def read_bytes(self, path: str) -> bytes:
        if path not in self.files:
            raise ValidationError(f"Cannot read {path}: no such file")
        return self.files[path]

    def write_text(self, path: str, text: str) -> None:
        self.write_bytes(path, text.encode("utf-8"))

    def write_bytes(self, path: str, data: bytes) -> None:
        self.files[path] = data
        self.writes.append(path)

    def exists(self, path: str) -> bool:
        return path in self.files or self.is_dir(path)

    def is_dir(self, path: str) -> bool:
        prefix = path.rstrip("/") + "/"
        return any(name.startswith(prefix) for name in self.files)

    def size(self, path: str) -> int:
        return len(self.read_bytes(path))

    def list_matching(self, directory: str, pattern: str) -> list[str]:
        folder = directory.rstrip("/")
        return sorted(
            path for path in self.files if posixpath.dirname(path) == folder and fnmatch.fnmatch(posixpath.basename(path), pattern)
        )

    def join(self, *parts: str) -> str:
        return posixpath.join(*parts)

    def name(self, path: str) -> str:
        return posixpath.basename(path)


class FixedClock(Clock):
    def __init__(self, moment: datetime | None = None) -> None:
        self.moment = moment or datetime(2026, 10, 15, 8, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.moment


class FakeDocs(Docs):
    def __init__(self) -> None:
        self.skill_text = "---\nname: conflu-c-cli\ndescription: A fake skill for the tests of the command line.\n---\n# Skill\n"

    def topics(self) -> list[DocTopic]:
        return [DocTopic("daily-workflow", "Daily workflow"), DocTopic("exit-codes", "Exit codes")]

    def topic(self, name: str) -> str:
        if name not in ("daily-workflow", "exit-codes"):
            raise NotFoundError(f"No guide named '{name}'.")
        return f"# {name}\n\nText of {name}.\n"

    def readme(self) -> str:
        return "# conflu-c-cli\n\nOverview.\n"

    def changelog(self) -> str:
        return f"# Changelog\n\n## [{__version__}] - 2026-10-17\n"

    def skill(self) -> str:
        return self.skill_text


class RecordingDiagnostics(Diagnostics):
    def __init__(self) -> None:
        self.infos: list[str] = []
        self.warnings: list[str] = []
        self.debugs: list[str] = []

    def info(self, message: str) -> None:
        self.infos.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def debug(self, message: str) -> None:
        self.debugs.append(message)


def default_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = dict(base_url=BASE, email="user@example.com", api_token="secret-token")
    values.update(overrides)
    return Settings(**values)


def build_app(
    *,
    gateway: FakeGateway | None = None,
    files: MemoryFiles | None = None,
    store: MemoryConfigStore | None = None,
    settings: Settings | None = None,
    docs: Docs | None = None,
    diagnostics: Diagnostics | None = None,
    environ: Mapping[str, str] | None = None,
) -> Application:
    return Application.create(
        settings=settings or default_settings(),
        gateway=gateway or FakeGateway(),
        store=store or MemoryConfigStore(),
        files=files or MemoryFiles(),
        clock=FixedClock(),
        docs=docs or FakeDocs(),
        diagnostics=diagnostics or RecordingDiagnostics(),
        environ=environ or {},
        runtime={"version": "1.0.0", "python": "3.13"},
    )
