from __future__ import annotations

import base64
import gzip
import html
import json
import re
import secrets
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, parse_qsl, quote, quote_plus, urlencode, urlparse, unquote

_ACCOUNT_ID = "5b10ac8d82e05b22cc7d4ef5"
_AUTHOR = {
    "accountId": _ACCOUNT_ID,
    "displayName": "Alex Example",
    "publicName": "Alex Example",
    "email": "alex@example.com",
}
_SPACE_TYPES = {"global", "collaboration", "knowledge_base", "personal", "system", "onboarding", "xflow_sample_space"}
_SPACE_STATUS = {"current", "archived", "trashed"}
_PAGE_STATUS = {"current", "archived", "deleted", "trashed"}
_PAGE_STATUS_SINGLE = {"current", "archived", "deleted", "trashed", "historical", "draft"}
_COMMENT_STATUS = {"current", "archived", "deleted", "trashed", "historical", "draft"}
_BODY_FORMATS = {"storage", "atlas_doc_format"}
_BODY_WRITE_FORMATS = {"storage", "atlas_doc_format", "wiki"}
_PAGE_SORTS = {"id", "-id", "created-date", "-created-date", "modified-date", "-modified-date", "title", "-title"}
_SPACE_SORTS = {"id", "-id", "key", "-key", "name", "-name"}
_VERSION_SORTS = {"modified-date", "-modified-date"}
_COMMENT_SORTS = {"created-date", "-created-date", "modified-date", "-modified-date"}
_DESCENDANT_DEPTH = set(str(value) for value in range(1, 11))
_LABEL_PREFIXES = {"my", "team", "global", "system"}
_MOVE_POSITIONS = {"append", "before", "after"}
_OLD_EXCERPTS = {"highlight", "indexed", "none", "highlight_unescaped", "indexed_unescaped"}
_OLD_SITE_PERMISSIONS = {"all", "externalCollaborator", "none"}
_FORBIDDEN_LABEL_CHARS = set(" &?/:;'\"<>()[],@^#$%*+=\\{}|`~!")
_SEARCH_EXPANDS = {"content.ancestors", "content.metadata.labels", "content.version", "content.space", "content.history"}
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _friendly_date(value: str) -> str:
    dt = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.000Z")
    return f"{_MONTHS[dt.month - 1]} {dt.day}, {dt.year}"


def _slug(text: str) -> str:
    return quote_plus(text)


def _plain_text(storage: str) -> str:
    text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", storage, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _text_terms(raw: str) -> list[str]:
    """The terms of a `text ~ "..."` clause: the words, or one phrase (kept with its quotes, so that it can be told from a word)."""
    value = re.sub(r"\\(.)", r"\1", raw)
    if len(value) > 2 and value.startswith('"') and value.endswith('"'):
        return [value]
    return value.split()


def _term_in(text: str, term: str) -> bool:
    """A word occurs as a part of the text, a phrase as its words in a row, and * and ? are wildcards. Case does not matter."""
    haystack, needle = text.lower(), term.lower()
    if len(needle) > 2 and needle.startswith('"') and needle.endswith('"'):
        return " ".join(needle[1:-1].split()) in " ".join(haystack.split())
    if "*" in needle or "?" in needle:
        pattern = "".join(".*" if char == "*" else "." if char == "?" else re.escape(char) for char in needle)
        return re.search(pattern, haystack) is not None
    return needle in haystack


def _highlight(text: str, words: list[str]) -> str:
    seen: set[str] = set()
    ordered = []
    for word in words:
        key = word.lower()
        if key and key not in seen:
            seen.add(key)
            ordered.append(word)
    ordered.sort(key=len, reverse=True)
    result = text
    for word in ordered:
        pattern = re.compile(re.escape(word), re.I)
        result = pattern.sub(lambda match: f"@@@hl@@@{match.group(0)}@@@endhl@@@", result)
    return result


def _excerpt(text: str, words: list[str]) -> str:
    if not text:
        return ""
    lowered = text.lower()
    found = len(text)
    chosen = ""
    for word in words:
        idx = lowered.find(word.lower())
        if idx != -1 and idx < found:
            found = idx
            chosen = word
    if found == len(text):
        snippet = text[:120]
    else:
        start = max(0, found - 30)
        end = min(len(text), found + max(len(chosen), 1) + 50)
        snippet = text[start:end]
        if start:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."
    return _highlight(snippet, words)


@dataclass
class Recorded:
    method: str
    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]
    body: Any = None
    raw: bytes = b""

    @property
    def target(self) -> str:
        return f"{self.method} {self.path}"


@dataclass
class _Failure:
    prefix: str
    status: int
    times: int
    body: Any = None
    method: str = ""
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class _RequestError(Exception):
    status: int
    title: str
    detail: str
    code: str = "INVALID_REQUEST_PARAMETER"
    old: bool = False
    old_key: str = "BAD_REQUEST"
    payload: Any = None


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.connections: set[Any] = set()

    def get_request(self) -> Any:
        connection, address = super().get_request()
        self.connections.add(connection)
        return connection, address

    def handle_error(self, request: Any, client_address: Any) -> None:
        if isinstance(sys.exc_info()[1], ConnectionError):
            return  # the client hung up on purpose (it refused an oversized answer, or a test closed the connection)
        super().handle_error(request, client_address)


class MockConfluence:
    gzip = False

    def __init__(
        self,
        *,
        context_path: str = "/wiki",
        page_cap: int = 2,
        email: str = "user@example.com",
        token: str = "test-token",
        populate: bool = True,
    ) -> None:
        self.context_path = "/" + context_path.strip("/") if context_path not in {"", "/"} else ""
        self.page_cap = page_cap
        self.email = email
        self.token = token
        self.requests: list[Recorded] = []
        self.media_requests: list[Recorded] = []
        self.spaces: dict[str, dict[str, Any]] = {}
        self.pages: dict[str, dict[str, Any]] = {}
        self.comments: dict[str, dict[str, Any]] = {}
        self.attachments: dict[str, dict[str, Any]] = {}
        self.users: dict[str, dict[str, Any]] = {_ACCOUNT_ID: dict(_AUTHOR)}
        self._failures: list[_Failure] = []
        self._lock = threading.Lock()
        self._server: _Server | None = None
        self._media_server: _Server | None = None
        self._thread: threading.Thread | None = None
        self._media_thread: threading.Thread | None = None
        self._next_space = 10000
        self._next_page = 20000
        self._next_comment = 40010
        self._next_attachment = 50000
        self._clock = datetime(2026, 10, 15, 8, 0, 0, tzinfo=timezone.utc)
        self._media_secret = secrets.token_urlsafe(18)
        if populate:
            self._populate_defaults()

    def __enter__(self) -> "MockConfluence":
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def start(self) -> None:
        if self._server is not None:
            return
        mock = self

        class ApiHandler(_ApiHandler):
            confluence = mock

        class MediaHandler(_MediaHandler):
            confluence = mock

        self._server = _Server(("127.0.0.1", 0), ApiHandler)
        self._media_server = _Server(("127.0.0.1", 0), MediaHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self._media_thread = threading.Thread(target=self._media_server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self._thread.start()
        self._media_thread.start()

    def stop(self) -> None:
        for server, thread in ((self._server, self._thread), (self._media_server, self._media_thread)):
            if server is None:
                continue
            server.shutdown()
            server.server_close()
            for connection in list(server.connections):
                try:
                    connection.close()
                except OSError:
                    pass
            if thread is not None:
                thread.join(timeout=1)
        self._server = None
        self._media_server = None
        self._thread = None
        self._media_thread = None

    @property
    def base_url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_address[1]}{self.context_path}"

    @property
    def media_url(self) -> str:
        assert self._media_server is not None
        return f"http://127.0.0.1:{self._media_server.server_address[1]}"

    def fail_next(
        self,
        prefix: str,
        status: int,
        times: int = 1,
        *,
        method: str = "",
        body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._failures.append(_Failure(prefix, status, times, body, method, headers or {}))

    def add_space(self, key: str, name: str, space_type: str = "global") -> str:
        if space_type not in _SPACE_TYPES:
            raise ValueError(space_type)
        space_id = str(self._next_space)
        self._next_space += 1
        created = self._tick()
        home_id = str(self._next_page)
        self._next_page += 1
        self.spaces[space_id] = {
            "id": space_id,
            "key": key,
            "name": name,
            "type": space_type,
            "status": "current",
            "homepageId": home_id,
            "description": "",
            "createdAt": created,
        }
        self.pages[home_id] = {
            "id": home_id,
            "spaceId": space_id,
            "title": f"{name} Home",
            "parentId": None,
            "status": "current",
            "position": 0,
            "authorId": _ACCOUNT_ID,
            "ownerId": _ACCOUNT_ID,
            "createdAt": created,
            "versions": [{"number": 1, "createdAt": created, "message": "Created", "minorEdit": False, "authorId": _ACCOUNT_ID, "body": ""}],
            "labels": [],
        }
        return space_id

    def add_page(
        self,
        space_key: str,
        title: str,
        body: str = "",
        *,
        parent_id: str | None = None,
        labels: tuple[str, ...] = (),
        versions: int = 1,
    ) -> str:
        space = self._space_by_key(space_key)
        if space is None:
            raise KeyError(space_key)
        parent_id = space["homepageId"] if parent_id is None else parent_id
        if parent_id is not None and parent_id not in self.pages:
            raise KeyError(parent_id)
        page_id = str(self._next_page)
        self._next_page += 1
        created = self._tick()
        version_items: list[dict[str, Any]] = []
        for number in range(1, max(versions, 1) + 1):
            version_items.append(
                {
                    "number": number,
                    "createdAt": created if number == 1 else self._tick(),
                    "message": "Created" if number == 1 else "",
                    "minorEdit": False,
                    "authorId": _ACCOUNT_ID,
                    "body": body,
                }
            )
        self.pages[page_id] = {
            "id": page_id,
            "spaceId": space["id"],
            "title": title,
            "parentId": parent_id,
            "status": "current",
            "position": self._next_position(parent_id),
            "authorId": _ACCOUNT_ID,
            "ownerId": _ACCOUNT_ID,
            "createdAt": created,
            "versions": version_items,
            "labels": [name.lower() for name in labels],
        }
        return page_id

    def add_comment(self, page_id: str, body: str, *, kind: str = "footer", parent_id: str | None = None) -> str:
        if page_id not in self.pages:
            raise KeyError(page_id)
        if kind not in {"footer", "inline"}:
            raise ValueError(kind)
        comment_id = str(self._next_comment)
        self._next_comment += 1
        created = self._tick()
        self.comments[comment_id] = {
            "id": comment_id,
            "kind": kind,
            "pageId": page_id,
            "parentCommentId": parent_id,
            "authorId": _ACCOUNT_ID,
            "version": {"number": 1, "createdAt": created},
            "body": body,
            "resolutionStatus": "open" if kind == "inline" else None,
        }
        return comment_id

    def add_attachment(self, page_id: str, name: str, data: bytes, media_type: str = "application/octet-stream") -> str:
        if page_id not in self.pages:
            raise KeyError(page_id)
        attachment_id = f"att{self._next_attachment}"
        self._next_attachment += 1
        created = self._tick()
        self.attachments[attachment_id] = {
            "id": attachment_id,
            "pageId": page_id,
            "title": name,
            "mediaType": media_type,
            "comment": "",
            "versions": [{"number": 1, "createdAt": created, "data": bytes(data)}],
        }
        return attachment_id

    def take_failure(self, method: str, path: str) -> _Failure | None:
        with self._lock:
            for failure in list(self._failures):
                if path.startswith(failure.prefix) and (not failure.method or failure.method == method):
                    failure.times -= 1
                    if failure.times <= 0:
                        self._failures.remove(failure)
                    return failure
        return None

    def _populate_defaults(self) -> None:
        self.spaces["1001"] = {
            "id": "1001",
            "key": "ENG",
            "name": "Engineering",
            "type": "global",
            "status": "current",
            "homepageId": "2001",
            "description": "Engineering documentation",
            "createdAt": "2026-09-01T08:00:00.000Z",
        }
        self.spaces["1002"] = {
            "id": "1002",
            "key": "DOCS",
            "name": "Documentation",
            "type": "global",
            "status": "current",
            "homepageId": "3001",
            "description": "",
            "createdAt": "2026-09-01T08:00:00.000Z",
        }
        self.pages.update(
            {
                "2001": self._page_template("2001", "1001", "Engineering Home", None, 0, "<p>Welcome to engineering.</p>", [(1, "2026-10-01T08:00:00.000Z", "Created")]),
                "2002": self._page_template(
                    "2002",
                    "1001",
                    "Release notes",
                    "2001",
                    0,
                    '<h1>Release notes</h1><p>Contact <ac:link><ri:user ri:account-id="5b10ac8d82e05b22cc7d4ef5" /></ac:link> or write to alex@example.com.</p><ul><li>First</li><li>Second</li></ul><ac:structured-macro ac:name="toc" ac:schema-version="1" />',
                    [(1, "2026-10-01T08:00:00.000Z", "Created"), (2, "2026-10-05T10:00:00.000Z", ""), (3, "2026-10-10T09:00:00.000Z", "Added the October notes")],
                    labels=["release", "notes"],
                ),
                "2003": self._page_template(
                    "2003",
                    "1001",
                    "Architecture",
                    "2001",
                    1,
                    '<p>Overview</p><ac:structured-macro ac:name="code" ac:schema-version="1"><ac:parameter ac:name="language">python</ac:parameter><ac:plain-text-body><![CDATA[print("hi")]]></ac:plain-text-body></ac:structured-macro>',
                    [(1, "2026-10-01T08:00:00.000Z", "Created")],
                ),
                "2004": self._page_template("2004", "1001", "ADR 0001", "2003", 0, "<p>Decision: use <strong>ports</strong> and adapters.</p>", [(1, "2026-10-01T08:00:00.000Z", "Created"), (2, "2026-10-06T09:00:00.000Z", "")], labels=["adr"]),
                "2005": self._page_template("2005", "1001", "Plain page", "2001", 2, "<p>Just a paragraph &amp; text.</p>", [(1, "2026-10-01T08:00:00.000Z", "Created")]),
                "3001": self._page_template("3001", "1002", "Docs Home", None, 0, "<p>Docs.</p>", [(1, "2026-10-01T08:00:00.000Z", "Created")]),
            }
        )
        self.comments["4001"] = {"id": "4001", "kind": "footer", "pageId": "2002", "parentCommentId": None, "authorId": _ACCOUNT_ID, "version": {"number": 1, "createdAt": "2026-10-02T10:00:00.000Z"}, "body": "<p>Looks good.</p>", "resolutionStatus": None}
        self.comments["4002"] = {"id": "4002", "kind": "footer", "pageId": "2002", "parentCommentId": "4001", "authorId": _ACCOUNT_ID, "version": {"number": 1, "createdAt": "2026-10-02T11:00:00.000Z"}, "body": "<p>Thanks!</p>", "resolutionStatus": None}
        self.comments["4003"] = {"id": "4003", "kind": "inline", "pageId": "2002", "parentCommentId": None, "authorId": _ACCOUNT_ID, "version": {"number": 1, "createdAt": "2026-10-03T09:00:00.000Z"}, "body": "<p>Check this phrase.</p>", "resolutionStatus": "open"}
        self.attachments["att5001"] = {"id": "att5001", "pageId": "2002", "title": "diagram.png", "mediaType": "image/png", "comment": "", "versions": [{"number": 1, "createdAt": "2026-10-04T08:00:00.000Z", "data": b"PNGDATA123"}]}
        self.attachments["att5002"] = {"id": "att5002", "pageId": "2002", "title": "notes.txt", "mediaType": "text/plain", "comment": "", "versions": [{"number": 1, "createdAt": "2026-10-04T08:01:00.000Z", "data": b"hello notes\n"}]}

    def _page_template(
        self,
        page_id: str,
        space_id: str,
        title: str,
        parent_id: str | None,
        position: int,
        body: str,
        versions: list[tuple[int, str, str]],
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "id": page_id,
            "spaceId": space_id,
            "title": title,
            "parentId": parent_id,
            "status": "current",
            "position": position,
            "authorId": _ACCOUNT_ID,
            "ownerId": _ACCOUNT_ID,
            "createdAt": "2026-10-01T08:00:00.000Z",
            "versions": [
                {"number": number, "createdAt": created_at, "message": message, "minorEdit": False, "authorId": _ACCOUNT_ID, "body": body}
                for number, created_at, message in versions
            ],
            "labels": list(labels or []),
        }

    def _tick(self) -> str:
        value = _iso(self._clock)
        self._clock += timedelta(minutes=1)
        return value

    def _space_by_key(self, key: str) -> dict[str, Any] | None:
        for space in self.spaces.values():
            if space["key"] == key:
                return space
        return None

    def _page_space_key(self, page: dict[str, Any]) -> str:
        return self.spaces[page["spaceId"]]["key"]

    def _page_webui(self, page: dict[str, Any]) -> str:
        return f"/spaces/{self._page_space_key(page)}/pages/{page['id']}/{_slug(page['title'])}"

    def _page_links(self, page: dict[str, Any]) -> dict[str, str]:
        webui = self._page_webui(page)
        return {"webui": webui, "editui": f"{webui}?edit=true", "tinyui": f"/x/{page['id']}"}

    def _attachment_download_path(self, attachment: dict[str, Any], version_number: int | None = None) -> str:
        version_number = attachment["versions"][-1]["number"] if version_number is None else version_number
        return f"/download/attachments/{attachment['pageId']}/{quote(attachment['title'])}?version={version_number}&modificationDate=0&api=v2"

    def _next_position(self, parent_id: str | None) -> int:
        positions = [page["position"] for page in self.pages.values() if page.get("parentId") == parent_id]
        return max(positions) + 1 if positions else 0

    def _children(self, parent_id: str | None) -> list[dict[str, Any]]:
        children = [page for page in self.pages.values() if page.get("parentId") == parent_id]
        return sorted(children, key=lambda item: (item["position"], int(item["id"])))

    def _resequence(self, parent_id: str | None) -> None:
        for index, page in enumerate(self._children(parent_id)):
            page["position"] = index

    def _page_ancestors(self, page_id: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        current = self.pages[page_id].get("parentId")
        while current is not None:
            page = self.pages[current]
            items.append(page)
            current = page.get("parentId")
        items.reverse()
        return items

    def _is_descendant(self, page_id: str, candidate_parent: str) -> bool:
        current = self.pages[candidate_parent].get("parentId")
        while current is not None:
            if current == page_id:
                return True
            current = self.pages[current].get("parentId")
        return False


class _BaseHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    confluence: MockConfluence

    def log_message(self, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        self.route("GET")

    def do_POST(self) -> None:
        self.route("POST")

    def do_PUT(self) -> None:
        self.route("PUT")

    def do_DELETE(self) -> None:
        self.route("DELETE")

    def route(self, method: str) -> None:
        raise NotImplementedError

    def _json_bytes(self, payload: Any) -> bytes:
        return json.dumps(payload).encode("utf-8")

    def _reply_json(self, status: int, payload: Any = None, headers: dict[str, str] | None = None) -> None:
        body = b"" if payload is None else self._json_bytes(payload)
        compress = self.confluence.gzip and len(body) > 200 and "gzip" in self.headers.get("Accept-Encoding", "")
        if compress:
            body = gzip.compress(body)
        self.send_response(status)
        self.send_header("Content-Type", "application/json;charset=UTF-8")
        if compress:
            self.send_header("Content-Encoding", "gzip")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _reply_bytes(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None, content_type: str = "application/octet-stream") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _read_body(self) -> tuple[Any, bytes, str | None]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return None, raw, None
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("application/json"):
            try:
                return json.loads(raw.decode("utf-8")), raw, None
            except (UnicodeDecodeError, json.JSONDecodeError):
                return raw, raw, "Invalid JSON body"
        if content_type.startswith("multipart/form-data"):
            try:
                return self._parse_multipart(raw, content_type), raw, None
            except ValueError as exc:
                return raw, raw, str(exc)
        return raw, raw, None

    def _parse_multipart(self, raw: bytes, content_type: str) -> dict[str, Any]:
        match = re.search(r'boundary="?([^";]+)"?', content_type)
        if not match:
            raise ValueError("Missing multipart boundary")
        boundary = b"--" + match.group(1).encode("utf-8")
        parts = raw.split(boundary)
        if len(parts) < 3:
            raise ValueError("Malformed multipart body")
        fields: dict[str, str] = {}
        file_info: dict[str, Any] | None = None
        for chunk in parts[1:]:
            if chunk.startswith(b"--"):
                break
            if chunk.startswith(b"\r\n"):
                chunk = chunk[2:]
            if chunk.endswith(b"\r\n"):
                chunk = chunk[:-2]
            header_block, separator, data = chunk.partition(b"\r\n\r\n")
            if not separator:
                raise ValueError("Malformed multipart section")
            header_map: dict[str, str] = {}
            for line in header_block.split(b"\r\n"):
                if b":" not in line:
                    raise ValueError("Malformed multipart header")
                name, value = line.decode("utf-8").split(":", 1)
                header_map[name.lower()] = value.strip()
            disposition = header_map.get("content-disposition", "")
            name_match = re.search(r'name="([^"]+)"', disposition)
            if not name_match:
                raise ValueError("Missing multipart field name")
            field_name = name_match.group(1)
            file_match = re.search(r'filename="([^"]*)"', disposition)
            if file_match:
                file_info = {
                    "name": file_match.group(1),
                    "type": header_map.get("content-type", "application/octet-stream"),
                    "data": data,
                }
            else:
                fields[field_name] = data.decode("utf-8")
        return {"fields": fields, "file": file_info}

    def _expected_auth(self) -> str:
        encoded = base64.b64encode(f"{self.confluence.email}:{self.confluence.token}".encode("utf-8")).decode("ascii")
        return f"Basic {encoded}"

    def _is_authorized(self) -> bool:
        return self.headers.get("Authorization", "") == self._expected_auth()

    def _v2_error(self, status: int, code: str, title: str, detail: str) -> dict[str, Any]:
        return {"errors": [{"status": status, "code": code, "title": title, "detail": detail}]}

    def _old_error(self, status: int, key: str, translation: str) -> dict[str, Any]:
        return {
            "statusCode": status,
            "data": {
                "authorized": status != 401,
                "valid": False,
                "errors": [{"message": {"key": key, "translation": translation}}],
                "successful": False,
            },
            "message": translation,
            "reason": HTTPStatus(status).phrase,
        }

    def _send_error_payload(self, error: _RequestError) -> None:
        if error.payload is not None:
            if isinstance(error.payload, bytes):
                self._reply_bytes(error.status, error.payload)
                return
            self._reply_json(error.status, error.payload)
            return
        if error.old:
            self._reply_json(error.status, self._old_error(error.status, error.old_key, error.detail))
            return
        self._reply_json(error.status, self._v2_error(error.status, error.code, error.title, error.detail))

    def _require_known_query(self, query: dict[str, list[str]], allowed: set[str], *, old: bool = False) -> None:
        unknown = sorted(set(query) - allowed)
        if unknown:
            raise _RequestError(400, "Invalid request parameter", f"Unknown query parameter: {unknown[0]}", old=old, old_key="BAD_REQUEST")

    def _single(self, query: dict[str, list[str]], name: str) -> str | None:
        values = query.get(name)
        if not values:
            return None
        return ",".join(values)

    def _parse_bool(self, raw: str | None, name: str, *, old: bool = False) -> bool | None:
        if raw is None:
            return None
        lowered = raw.lower()
        if lowered not in {"true", "false"}:
            raise _RequestError(400, "Invalid request parameter", f"{name} must be true or false", old=old, old_key="BAD_REQUEST")
        return lowered == "true"

    def _parse_limit(self, query: dict[str, list[str]], *, default: int, old: bool = False) -> int:
        raw = self._single(query, "limit")
        if raw is None:
            return default
        if not raw.isdigit():
            raise _RequestError(400, "Invalid request parameter", "limit must be an integer", old=old, old_key="BAD_REQUEST")
        limit = int(raw)
        if limit < 1 or limit > 250:
            raise _RequestError(400, "Invalid request parameter", "limit must be between 1 and 250", old=old, old_key="BAD_REQUEST")
        return limit

    def _parse_search_limit(self, query: dict[str, list[str]]) -> int:
        raw = self._single(query, "limit")
        if raw is None:
            return 25
        if not raw.isdigit():
            raise _RequestError(400, "Bad Request", "Could not parse cql: invalid limit", old=True, old_key="BAD_REQUEST")
        return int(raw)

    def _parse_start(self, query: dict[str, list[str]]) -> int:
        raw = self._single(query, "start")
        if raw is None:
            return 0
        if not raw.isdigit():
            raise _RequestError(400, "Bad Request", "Could not parse cql: invalid start", old=True, old_key="BAD_REQUEST")
        return int(raw)

    def _parse_cursor(self, query: dict[str, list[str]], *, old: bool = False) -> int:
        raw = self._single(query, "cursor")
        if raw is None:
            return 0
        if not raw.isdigit():
            raise _RequestError(400, "Invalid request parameter", "cursor must be a numeric offset", old=old, old_key="BAD_REQUEST")
        return int(raw)

    def _parse_csv(self, raw: str | None, name: str, *, old: bool = False) -> list[str]:
        if raw is None:
            return []
        values = [item.strip() for item in raw.split(",")]
        if any(value == "" for value in values):
            raise _RequestError(400, "Invalid request parameter", f"{name} contains an empty item", old=old, old_key="BAD_REQUEST")
        return values

    def _parse_csv_enum(self, raw: str | None, name: str, allowed: set[str], *, old: bool = False) -> list[str]:
        values = self._parse_csv(raw, name, old=old)
        for value in values:
            if value not in allowed:
                raise _RequestError(400, "Invalid request parameter", f"Unsupported value for {name}: {value}", old=old, old_key="BAD_REQUEST")
        return values

    def _parse_int_query(self, raw: str | None, name: str, *, old: bool = False) -> int | None:
        if raw is None:
            return None
        if not raw.isdigit():
            raise _RequestError(400, "Invalid request parameter", f"{name} must be numeric", old=old, old_key="BAD_REQUEST")
        return int(raw)

    def _require_object(self, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise _RequestError(400, "Invalid request body", "Request body must be a JSON object")
        return body

    def _parse_body_value(self, body: Any) -> str | None:
        if body is None:
            return None
        if not isinstance(body, dict):
            raise _RequestError(400, "Invalid request body", "body must be an object")
        if "representation" in body or "value" in body:
            representation = body.get("representation")
            value = body.get("value")
        else:
            if len(body) != 1:
                raise _RequestError(400, "Invalid request body", "Nested body must contain exactly one representation")
            representation, nested = next(iter(body.items()))
            if representation not in _BODY_WRITE_FORMATS or not isinstance(nested, dict):
                raise _RequestError(400, "Invalid request body", "Unsupported body representation")
            value = nested.get("value")
            representation = nested.get("representation", representation)
        if representation not in _BODY_WRITE_FORMATS:
            raise _RequestError(400, "Invalid request body", f"Unsupported body representation: {representation}")
        if not isinstance(value, str):
            raise _RequestError(400, "Invalid request body", "body value must be a string")
        return value

    def _response_body(self, storage: str) -> dict[str, Any]:
        return {"storage": {"representation": "storage", "value": storage}}

    def _space_model(self, space: dict[str, Any], description_format: str | None = None, include_base: bool = False) -> dict[str, Any]:
        model = {
            "id": space["id"],
            "key": space["key"],
            "name": space["name"],
            "type": space["type"],
            "status": space["status"],
            "authorId": _ACCOUNT_ID,
            "createdAt": space["createdAt"],
            "homepageId": space["homepageId"],
            "_links": {"webui": f"/spaces/{space['key']}"},
        }
        if description_format == "plain":
            model["description"] = {"plain": {"representation": "plain", "value": space["description"]}}
        if include_base:
            model["_links"]["base"] = self.confluence.base_url
        return model

    def _page_model(
        self,
        page: dict[str, Any],
        *,
        body_format: str | None = None,
        version_number: int | None = None,
        include_base: bool = False,
        include_labels: bool = False,
        include_current_version: bool = True,
    ) -> dict[str, Any]:
        version = page["versions"][-1] if version_number is None else next(item for item in page["versions"] if item["number"] == version_number)
        model = {
            "id": page["id"],
            "status": page["status"],
            "title": page["title"],
            "spaceId": page["spaceId"],
            "position": page["position"],
            "authorId": page["authorId"],
            "ownerId": page["ownerId"],
            "lastOwnerId": page["ownerId"],
            "createdAt": page["createdAt"],
            "parentType": "page",
            "_links": self.confluence._page_links(page),
        }
        model["parentId"] = page.get("parentId")
        if include_current_version:
            model["version"] = {
                "number": version["number"],
                "createdAt": version["createdAt"],
                "message": version["message"],
                "minorEdit": version["minorEdit"],
                "authorId": version["authorId"],
            }
        if body_format == "storage":
            model["body"] = self._response_body(version["body"])
        elif body_format == "atlas_doc_format":
            raise _RequestError(400, "Invalid request parameter", "body-format atlas_doc_format is not implemented by this mock")
        if include_labels:
            model["labels"] = {"results": [self._label_model(page["id"], label) for label in page["labels"]]}
        if include_base:
            model["_links"]["base"] = self.confluence.base_url
        return model

    def _descendant_model(self, page: dict[str, Any], depth: int) -> dict[str, Any]:
        return {
            "id": page["id"],
            "status": page["status"],
            "title": page["title"],
            "type": "page",
            "parentId": page["parentId"],
            "depth": depth,
            "childPosition": page["position"],
        }

    def _label_model(self, page_id: str, name: str) -> dict[str, Any]:
        return {"id": f"lbl-{page_id}-{name}", "name": name, "prefix": "global"}

    def _comment_model(self, comment: dict[str, Any], *, body_format: str | None = None) -> dict[str, Any]:
        page = self.confluence.pages[comment["pageId"]]
        model = {
            "id": comment["id"],
            "status": "current",
            "title": f"Re: {page['title']}",
            "pageId": comment["pageId"],
            "version": {
                "number": comment["version"]["number"],
                "createdAt": comment["version"]["createdAt"],
                "message": "",
                "minorEdit": False,
                "authorId": comment["authorId"],
            },
            "_links": {"webui": f"{self.confluence._page_webui(page)}#comment-{comment['id']}"},
        }
        if comment["kind"] == "footer":
            model["parentCommentId"] = comment.get("parentCommentId")
        if comment["kind"] == "inline":
            model["resolutionStatus"] = comment.get("resolutionStatus") or "open"
        if body_format == "storage":
            model["body"] = self._response_body(comment["body"])
        elif body_format == "atlas_doc_format":
            raise _RequestError(400, "Invalid request parameter", "body-format atlas_doc_format is not implemented by this mock")
        return model

    def _attachment_model(self, attachment: dict[str, Any], *, version_number: int | None = None) -> dict[str, Any]:
        version = attachment["versions"][-1] if version_number is None else next(item for item in attachment["versions"] if item["number"] == version_number)
        page = self.confluence.pages[attachment["pageId"]]
        download = self.confluence._attachment_download_path(attachment, version["number"])
        return {
            "id": attachment["id"],
            "status": "current",
            "title": attachment["title"],
            "createdAt": attachment["versions"][0]["createdAt"],
            "pageId": attachment["pageId"],
            "mediaType": attachment["mediaType"],
            "mediaTypeDescription": attachment["mediaType"],
            "comment": attachment["comment"],
            "fileId": attachment["id"],
            "fileSize": len(version["data"]),
            "webuiLink": self.confluence._page_webui(page),
            "downloadLink": download,
            "version": {"number": version["number"], "createdAt": version["createdAt"], "message": "", "minorEdit": False, "authorId": _ACCOUNT_ID},
            "_links": {"webui": self.confluence._page_webui(page), "download": download},
        }

    def _apply_pagination(
        self,
        items: list[Any],
        *,
        path: str,
        query_pairs: list[tuple[str, str]],
        offset: int,
        limit: int,
        base_links: bool = True,
    ) -> tuple[list[Any], dict[str, Any], dict[str, str]]:
        page_size = min(limit, self.confluence.page_cap)
        sliced = items[offset:offset + page_size]
        links: dict[str, Any] = {"base": self.confluence.base_url} if base_links else {}
        headers: dict[str, str] = {}
        if offset + page_size < len(items):
            pairs = [(key, value) for key, value in query_pairs if key != "cursor"]
            pairs.append(("cursor", str(offset + page_size)))
            next_path = f"{self.confluence.context_path}{path}?{urlencode(pairs, doseq=True)}"
            links["next"] = next_path
            headers["Link"] = f"<{next_path}>; rel=\"next\""
        return sliced, links, headers


class _ApiHandler(_BaseHandler):
    def route(self, method: str) -> None:
        body, raw, parse_error = self._read_body()
        url = urlparse(self.path)
        full_path = unquote(url.path)
        path = full_path[len(self.confluence.context_path):] if self.confluence.context_path and full_path.startswith(self.confluence.context_path) else full_path
        query = parse_qs(url.query, keep_blank_values=True)
        headers = {key.lower(): value for key, value in self.headers.items()}
        self.confluence.requests.append(Recorded(method, path, query, headers, body, raw))
        if not self._is_authorized():
            self._reply_json(401, self._old_error(401, "UNAUTHORIZED", "Unauthorized"))
            return
        failure = self.confluence.take_failure(method, path)
        if failure is not None:
            payload = failure.body if failure.body is not None else {"message": "injected"}
            self._reply_json(failure.status, payload, failure.headers)
            return
        if parse_error and path.startswith(("/api/v2/", "/rest/api/")):
            if path.startswith("/api/v2/"):
                self._reply_json(400, self._v2_error(400, "INVALID_REQUEST_PARAMETER", "Invalid request body", parse_error))
            else:
                self._reply_json(400, self._old_error(400, "BAD_REQUEST", parse_error))
            return
        try:
            if path.startswith("/api/v2"):
                if method == "DELETE":
                    raise _RequestError(405, "Method not allowed", "DELETE is not supported by this mock", code="INVALID_REQUEST_PARAMETER")
                self._route_v2(method, path, query, parse_qsl(url.query, keep_blank_values=True), body)
                return
            if path.startswith("/rest/api"):
                self._route_old(method, path, query, parse_qsl(url.query, keep_blank_values=True), body)
                return
            if path.startswith("/download/"):
                self._route_download(path, query)
                return
            raise _RequestError(404, "Not found", f"Unknown path: {path}", old=True, old_key="NOT_FOUND")
        except _RequestError as error:
            self._send_error_payload(error)
        except KeyError:
            self._send_error_payload(_RequestError(404, "Not found", f"Unknown path: {path}", old=path.startswith("/rest/"), old_key="NOT_FOUND", code="NOT_FOUND"))

    def _route_v2(self, method: str, path: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]], body: Any) -> None:
        if method == "GET" and path == "/api/v2/spaces":
            return self._get_spaces(query, query_pairs)
        match = re.fullmatch(r"/api/v2/spaces/(\d+)", path)
        if method == "GET" and match:
            return self._get_space(match.group(1), query)
        match = re.fullmatch(r"/api/v2/spaces/(\d+)/pages", path)
        if method == "GET" and match:
            return self._get_space_pages(match.group(1), query, query_pairs)
        if method == "GET" and path == "/api/v2/pages":
            return self._get_pages(query, query_pairs)
        if method == "POST" and path == "/api/v2/pages":
            return self._post_page(query, body)
        match = re.fullmatch(r"/api/v2/pages/([^/]+)", path)
        if match:
            if method == "GET":
                return self._get_page(match.group(1), query)
            if method == "PUT":
                return self._put_page(match.group(1), body)
        match = re.fullmatch(r"/api/v2/pages/(\d+)/title", path)
        if method == "PUT" and match:
            return self._put_page_title(match.group(1), body)
        match = re.fullmatch(r"/api/v2/pages/(\d+)/ancestors", path)
        if method == "GET" and match:
            return self._get_page_ancestors(match.group(1), query)
        match = re.fullmatch(r"/api/v2/pages/(\d+)/descendants", path)
        if method == "GET" and match:
            return self._get_page_descendants(match.group(1), query, query_pairs)
        match = re.fullmatch(r"/api/v2/pages/(\d+)/direct-children", path)
        if method == "GET" and match:
            return self._get_page_children(match.group(1), query, query_pairs)
        match = re.fullmatch(r"/api/v2/pages/(\d+)/versions", path)
        if method == "GET" and match:
            return self._get_page_versions(match.group(1), query, query_pairs)
        match = re.fullmatch(r"/api/v2/pages/(\d+)/labels", path)
        if method == "GET" and match:
            return self._get_page_labels(match.group(1), query, query_pairs)
        match = re.fullmatch(r"/api/v2/pages/(\d+)/(footer-comments|inline-comments)", path)
        if method == "GET" and match:
            return self._get_page_comments(match.group(1), match.group(2), query, query_pairs)
        match = re.fullmatch(r"/api/v2/(footer-comments|inline-comments)/(\d+)/children", path)
        if method == "GET" and match:
            return self._get_comment_children(match.group(1), match.group(2), query, query_pairs)
        if method == "POST" and path == "/api/v2/footer-comments":
            return self._post_footer_comment(body)
        match = re.fullmatch(r"/api/v2/pages/(\d+)/attachments", path)
        if method == "GET" and match:
            return self._get_page_attachments(match.group(1), query, query_pairs)
        match = re.fullmatch(r"/api/v2/attachments/(att\d+)", path)
        if method == "GET" and match:
            return self._get_attachment(match.group(1), query)
        if method == "POST" and path == "/api/v2/users-bulk":
            return self._post_users_bulk(body)
        raise _RequestError(404, "Not found", f"Unknown path: {path}", code="NOT_FOUND")

    def _route_old(self, method: str, path: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]], body: Any) -> None:
        if method == "GET" and path == "/rest/api/user/current":
            self._require_known_query(query, {"expand"}, old=True)
            expand = self._single(query, "expand")
            if expand:
                values = self._parse_csv(expand, "expand", old=True)
                for value in values:
                    if value not in {"operations", "personalSpace", "isExternalCollaborator"}:
                        raise _RequestError(400, "Bad Request", f"Unsupported value for expand: {value}", old=True, old_key="BAD_REQUEST")
            return self._reply_json(200, {"type": "known", "accountId": _ACCOUNT_ID, "accountType": "atlassian", "email": _AUTHOR["email"], "publicName": _AUTHOR["publicName"], "displayName": _AUTHOR["displayName"], "profilePicture": {}, "_links": {}})
        if method == "GET" and path == "/rest/api/search":
            return self._search(query, query_pairs)
        match = re.fullmatch(r"/rest/api/content/(\d+)/label", path)
        if match and method == "POST":
            return self._add_labels(match.group(1), body)
        match = re.fullmatch(r"/rest/api/content/(\d+)/label/([^/]+)", path)
        if match and method == "DELETE":
            return self._delete_label(match.group(1), unquote(match.group(2)))
        match = re.fullmatch(r"/rest/api/content/(\d+)/child/attachment", path)
        if match and method in {"POST", "PUT"}:
            return self._upload_attachment(method, match.group(1), query, body)
        match = re.fullmatch(r"/rest/api/content/(\d+)/move/([^/]+)/([0-9]+)", path)
        if match and method == "PUT":
            return self._move_page(match.group(1), match.group(2), match.group(3))
        match = re.fullmatch(r"/rest/api/content/(\d+)/child/attachment/(att\d+)/download", path)
        if match and method == "GET":
            return self._attachment_redirect_by_id(match.group(1), match.group(2), query)
        raise _RequestError(404, "Not found", f"Unknown path: {path}", old=True, old_key="NOT_FOUND", code="NOT_FOUND")

    def _route_download(self, path: str, query: dict[str, list[str]]) -> None:
        match = re.fullmatch(r"/download/attachments/(\d+)/([^/]+)", path)
        if not match:
            raise _RequestError(404, "Not found", f"Unknown path: {path}", old=True, old_key="NOT_FOUND")
        page_id = match.group(1)
        filename = unquote(match.group(2))
        version = self._parse_int_query(self._single(query, "version"), "version", old=True)
        for attachment in self.confluence.attachments.values():
            if attachment["pageId"] == page_id and attachment["title"] == filename:
                return self._send_attachment_redirect(attachment, version)
        raise _RequestError(404, "Not found", f"Attachment not found: {filename}", old=True, old_key="NOT_FOUND")

    def _get_spaces(self, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        self._require_known_query(query, {"ids", "keys", "type", "status", "labels", "favorited-by", "not-favorited-by", "sort", "description-format", "include-icon", "cursor", "limit"})
        description_format = self._single(query, "description-format")
        if description_format not in {None, "plain", "view"}:
            raise _RequestError(400, "Invalid request parameter", f"Unsupported value for description-format: {description_format}")
        self._parse_bool(self._single(query, "include-icon"), "include-icon")
        sort = self._single(query, "sort") or "id"
        if sort not in _SPACE_SORTS:
            raise _RequestError(400, "Invalid request parameter", f"Unsupported value for sort: {sort}")
        status = self._single(query, "status") or "current"
        if status not in _SPACE_STATUS:
            raise _RequestError(400, "Invalid request parameter", f"Unsupported value for status: {status}")
        limit = self._parse_limit(query, default=25)
        offset = self._parse_cursor(query)
        items = [space for space in self.confluence.spaces.values() if space["status"] == status]
        ids = set(self._parse_csv(self._single(query, "ids"), "ids")) or None
        keys = set(self._parse_csv(self._single(query, "keys"), "keys")) or None
        labels = self._parse_csv(self._single(query, "labels"), "labels")
        favorited = self._single(query, "favorited-by")
        not_favorited = self._single(query, "not-favorited-by")
        if ids is not None:
            items = [space for space in items if space["id"] in ids]
        if keys is not None:
            items = [space for space in items if space["key"] in keys]
        wanted_type = self._single(query, "type")
        if wanted_type is not None:
            if wanted_type not in _SPACE_TYPES:
                raise _RequestError(400, "Invalid request parameter", f"Unsupported value for type: {wanted_type}")
            items = [space for space in items if space["type"] == wanted_type]
        if labels:
            items = []
        if favorited:
            items = []
        if not_favorited:
            items = list(items)
        items = self._sort_spaces(items, sort)
        page_items, links, headers = self._apply_pagination(items, path="/api/v2/spaces", query_pairs=query_pairs, offset=offset, limit=limit)
        self._reply_json(200, {"results": [self._space_model(space, description_format) for space in page_items], "_links": links}, headers)

    def _sort_spaces(self, spaces: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
        reverse = sort.startswith("-")
        key = sort.lstrip("-")
        return sorted(spaces, key=lambda item: (item[key], int(item["id"])) if key != "id" else int(item["id"]), reverse=reverse)

    def _get_space(self, space_id: str, query: dict[str, list[str]]) -> None:
        self._require_known_query(query, {"description-format", "include-icon", "include-labels", "include-properties", "include-operations", "include-permissions", "include-role-assignments"})
        if space_id not in self.confluence.spaces:
            raise _RequestError(404, "Not found", f"Space not found: {space_id}", code="NOT_FOUND")
        for name in {"include-icon", "include-labels", "include-properties", "include-operations", "include-permissions", "include-role-assignments"}:
            self._parse_bool(self._single(query, name), name)
        description_format = self._single(query, "description-format")
        if description_format not in {None, "plain", "view"}:
            raise _RequestError(400, "Invalid request parameter", f"Unsupported value for description-format: {description_format}")
        self._reply_json(200, self._space_model(self.confluence.spaces[space_id], description_format, include_base=True))

    def _get_space_pages(self, space_id: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        self._require_known_query(query, {"depth", "sort", "status", "title", "body-format", "cursor", "limit"})
        if space_id not in self.confluence.spaces:
            raise _RequestError(404, "Not found", f"Space not found: {space_id}", code="NOT_FOUND")
        depth = self._single(query, "depth") or "all"
        if depth not in {"all", "root"}:
            raise _RequestError(400, "Invalid request parameter", f"Unsupported value for depth: {depth}")
        sort = self._single(query, "sort") or "id"
        if sort not in _PAGE_SORTS:
            raise _RequestError(400, "Invalid request parameter", f"Unsupported value for sort: {sort}")
        statuses = self._parse_csv_enum(self._single(query, "status") or "current,archived", "status", _PAGE_STATUS)
        body_format = self._single(query, "body-format")
        if body_format not in {None, "storage", "atlas_doc_format"}:
            raise _RequestError(400, "Invalid request parameter", f"Unsupported value for body-format: {body_format}")
        limit = self._parse_limit(query, default=25)
        offset = self._parse_cursor(query)
        title = self._single(query, "title")
        items = [page for page in self.confluence.pages.values() if page["spaceId"] == space_id and page["status"] in statuses]
        if depth == "root":
            items = [page for page in items if page.get("parentId") is None]
        if title is not None:
            items = [page for page in items if page["title"] == title]
        items = self._sort_pages(items, sort)
        page_items, links, headers = self._apply_pagination(items, path=f"/api/v2/spaces/{space_id}/pages", query_pairs=query_pairs, offset=offset, limit=limit)
        self._reply_json(200, {"results": [self._page_model(page, body_format=body_format) for page in page_items], "_links": links}, headers)

    def _sort_pages(self, pages: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
        reverse = sort.startswith("-")
        key = sort.lstrip("-")
        if key == "id":
            return sorted(pages, key=lambda page: int(page["id"]), reverse=reverse)
        if key == "created-date":
            return sorted(pages, key=lambda page: page["createdAt"], reverse=reverse)
        if key == "modified-date":
            return sorted(pages, key=lambda page: page["versions"][-1]["createdAt"], reverse=reverse)
        if key == "title":
            return sorted(pages, key=lambda page: (page["title"].lower(), int(page["id"])), reverse=reverse)
        return list(pages)

    def _get_pages(self, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        self._require_known_query(query, {"id", "space-id", "sort", "status", "title", "body-format", "subtype", "cursor", "limit"})
        sort = self._single(query, "sort") or "id"
        if sort not in _PAGE_SORTS:
            raise _RequestError(400, "Invalid request parameter", f"Unsupported value for sort: {sort}")
        statuses = self._parse_csv_enum(self._single(query, "status") or "current,archived", "status", _PAGE_STATUS)
        body_format = self._single(query, "body-format")
        if body_format not in {None, "storage", "atlas_doc_format"}:
            raise _RequestError(400, "Invalid request parameter", f"Unsupported value for body-format: {body_format}")
        subtype = self._single(query, "subtype")
        if subtype not in {None, "live", "page"}:
            raise _RequestError(400, "Invalid request parameter", f"Unsupported value for subtype: {subtype}")
        ids = set(self._parse_csv(self._single(query, "id"), "id")) or None
        space_ids = set(self._parse_csv(self._single(query, "space-id"), "space-id")) or None
        title = self._single(query, "title")
        limit = self._parse_limit(query, default=25)
        offset = self._parse_cursor(query)
        items = [page for page in self.confluence.pages.values() if page["status"] in statuses]
        if ids is not None:
            items = [page for page in items if page["id"] in ids]
        if space_ids is not None:
            items = [page for page in items if page["spaceId"] in space_ids]
        if title is not None:
            title_lower = title.lower()
            items = [page for page in items if page["title"].lower() == title_lower]
        if subtype == "live":
            items = []
        items = self._sort_pages(items, sort)
        page_items, links, headers = self._apply_pagination(items, path="/api/v2/pages", query_pairs=query_pairs, offset=offset, limit=limit)
        self._reply_json(200, {"results": [self._page_model(page, body_format=body_format) for page in page_items], "_links": links}, headers)

    def _get_page(self, page_id: str, query: dict[str, list[str]]) -> None:
        self._require_known_query(query, {"body-format", "get-draft", "status", "version", "include-labels", "include-properties", "include-operations", "include-likes", "include-versions", "include-version", "include-favorited-by-current-user-status", "include-webresources", "include-collaborators", "include-direct-children"})
        if not page_id.isdigit():
            raise _RequestError(400, "Invalid request parameter", "Page id must be numeric")
        if page_id not in self.confluence.pages:
            raise _RequestError(404, "Not found", f"Page not found: {page_id}", code="NOT_FOUND")
        body_format = self._single(query, "body-format")
        if body_format not in {None, "storage", "atlas_doc_format", "view", "export_view", "anonymous_export_view", "styled_view", "editor"}:
            raise _RequestError(400, "Invalid request parameter", f"Unsupported value for body-format: {body_format}")
        if body_format not in {None, "storage"}:
            raise _RequestError(400, "Invalid request parameter", f"body-format {body_format} is not implemented by this mock")
        self._parse_bool(self._single(query, "get-draft"), "get-draft")
        statuses = self._parse_csv_enum(self._single(query, "status"), "status", _PAGE_STATUS_SINGLE) if "status" in query else []
        page = self.confluence.pages[page_id]
        if statuses and page["status"] not in statuses:
            raise _RequestError(404, "Not found", f"Page not found: {page_id}", code="NOT_FOUND")
        include_labels = self._parse_bool(self._single(query, "include-labels"), "include-labels") or False
        self._parse_bool(self._single(query, "include-properties"), "include-properties")
        self._parse_bool(self._single(query, "include-operations"), "include-operations")
        self._parse_bool(self._single(query, "include-likes"), "include-likes")
        include_versions = self._parse_bool(self._single(query, "include-versions"), "include-versions") or False
        include_version = self._parse_bool(self._single(query, "include-version"), "include-version")
        self._parse_bool(self._single(query, "include-favorited-by-current-user-status"), "include-favorited-by-current-user-status")
        self._parse_bool(self._single(query, "include-webresources"), "include-webresources")
        self._parse_bool(self._single(query, "include-collaborators"), "include-collaborators")
        include_direct_children = self._parse_bool(self._single(query, "include-direct-children"), "include-direct-children") or False
        version_number = self._parse_int_query(self._single(query, "version"), "version")
        if version_number is not None and version_number not in {item["number"] for item in page["versions"]}:
            raise _RequestError(404, "Not found", f"Version not found: {version_number}", code="NOT_FOUND")
        model = self._page_model(page, body_format=body_format, version_number=version_number, include_base=True, include_labels=include_labels, include_current_version=include_version is not False)
        if include_versions:
            model["versions"] = {"results": [{"number": item["number"], "createdAt": item["createdAt"], "message": item["message"], "minorEdit": item["minorEdit"], "authorId": item["authorId"]} for item in page["versions"]]}
        if include_direct_children:
            model["directChildren"] = {"results": [self._descendant_model(child, 1) for child in self.confluence._children(page_id)]}
        self._reply_json(200, model)

    def _post_page(self, query: dict[str, list[str]], body: Any) -> None:
        self._require_known_query(query, {"embedded", "private", "root-level"})
        root_level = self._parse_bool(self._single(query, "root-level"), "root-level") or False
        for name in {"embedded", "private"}:
            self._parse_bool(self._single(query, name), name)
        data = self._require_object(body)
        if "spaceId" not in data:
            raise _RequestError(400, "Invalid request body", "spaceId is required")
        space_id = data["spaceId"]
        if not isinstance(space_id, str):
            raise _RequestError(400, "Invalid request body", "spaceId must be a string")
        if space_id not in self.confluence.spaces:
            raise _RequestError(400, "Invalid request body", f"Unknown spaceId: {space_id}")
        status = data.get("status", "current")
        if status not in {"current", "draft"}:
            raise _RequestError(400, "Invalid request body", f"Unsupported status: {status}")
        title = data.get("title")
        if status != "draft" and not isinstance(title, str):
            raise _RequestError(400, "Invalid request body", "title is required unless status is draft")
        if title is None:
            title = "Untitled draft"
        if not isinstance(title, str):
            raise _RequestError(400, "Invalid request body", "title must be a string")
        subtype = data.get("subtype")
        if subtype not in {None, "live"}:
            raise _RequestError(400, "Invalid request body", f"Unsupported subtype: {subtype}")
        parent_id = data.get("parentId")
        if parent_id is not None and not isinstance(parent_id, str):
            raise _RequestError(400, "Invalid request body", "parentId must be a string")
        if parent_id is None and not root_level:
            parent_id = self.confluence.spaces[space_id]["homepageId"]
        if parent_id is not None:
            parent = self.confluence.pages.get(parent_id)
            if parent is None:
                raise _RequestError(400, "Invalid request body", f"Unknown parentId: {parent_id}")
            if parent["spaceId"] != space_id:
                raise _RequestError(400, "Invalid request body", "parentId must refer to a page in the same space")
        if any(page["spaceId"] == space_id and page["status"] == "current" and page["title"] == title for page in self.confluence.pages.values()):
            raise _RequestError(400, "A page with this title already exists", "A page already exists with the same TITLE in this space")
        body_value = self._parse_body_value(data.get("body")) or ""
        created = self.confluence._tick()
        page_id = str(self.confluence._next_page)
        self.confluence._next_page += 1
        page = {
            "id": page_id,
            "spaceId": space_id,
            "title": title,
            "parentId": parent_id,
            "status": status,
            "position": self.confluence._next_position(parent_id),
            "authorId": _ACCOUNT_ID,
            "ownerId": _ACCOUNT_ID,
            "createdAt": created,
            "versions": [{"number": 1, "createdAt": created, "message": "Created", "minorEdit": False, "authorId": _ACCOUNT_ID, "body": body_value}],
            "labels": [],
        }
        self.confluence.pages[page_id] = page
        self._reply_json(200, self._page_model(page, body_format="storage" if data.get("body") is not None else None, include_base=True))

    def _put_page(self, page_id: str, body: Any) -> None:
        if page_id not in self.confluence.pages:
            raise _RequestError(404, "Not found", f"Page not found: {page_id}", code="NOT_FOUND")
        data = self._require_object(body)
        for required in ("id", "status", "title", "body", "version"):
            if required not in data:
                raise _RequestError(400, "Invalid request body", f"{required} is required")
        if data["id"] != page_id:
            raise _RequestError(400, "Invalid request body", "Body id must match the path id")
        if data["status"] not in {"current", "draft"}:
            raise _RequestError(400, "Invalid request body", f"Unsupported status: {data['status']}")
        if not isinstance(data["title"], str):
            raise _RequestError(400, "Invalid request body", "title must be a string")
        version = data["version"]
        if not isinstance(version, dict) or not isinstance(version.get("number"), int):
            raise _RequestError(400, "Invalid request body", "version.number is required")
        page = self.confluence.pages[page_id]
        current_version = page["versions"][-1]["number"]
        if version["number"] != current_version + 1:
            raise _RequestError(409, "Version conflict", f"Expected version.number {current_version + 1} but got {version['number']}", code="CONFLICT")
        new_title = data["title"]
        if any(other["id"] != page_id and other["spaceId"] == page["spaceId"] and other["status"] == "current" and other["title"] == new_title for other in self.confluence.pages.values()):
            raise _RequestError(400, "A page with this title already exists", "A page already exists with the same TITLE in this space")
        if "spaceId" in data and data["spaceId"] != page["spaceId"]:
            raise _RequestError(400, "Invalid request body", "spaceId cannot change")
        if "parentId" in data and data["parentId"] is not None:
            parent = self.confluence.pages.get(data["parentId"])
            if parent is None or parent["spaceId"] != page["spaceId"]:
                raise _RequestError(400, "Invalid request body", "parentId must refer to a page in the same space")
            if data["parentId"] != page["parentId"]:
                old_parent = page["parentId"]
                page["parentId"] = data["parentId"]
                page["position"] = self.confluence._next_position(data["parentId"])
                self.confluence._resequence(old_parent)
        page["title"] = new_title
        page["status"] = data["status"]
        body_value = self._parse_body_value(data["body"]) or ""
        created = self.confluence._tick()
        page["versions"].append({"number": version["number"], "createdAt": created, "message": version.get("message", ""), "minorEdit": False, "authorId": _ACCOUNT_ID, "body": body_value})
        self._reply_json(200, self._page_model(page, body_format="storage", include_base=True))

    def _put_page_title(self, page_id: str, body: Any) -> None:
        if page_id not in self.confluence.pages:
            raise _RequestError(404, "Not found", f"Page not found: {page_id}", code="NOT_FOUND")
        data = self._require_object(body)
        for required in ("status", "title"):
            if required not in data:
                raise _RequestError(400, "Invalid request body", f"{required} is required")
        if data["status"] not in {"current", "draft"}:
            raise _RequestError(400, "Invalid request body", f"Unsupported status: {data['status']}")
        if not isinstance(data["title"], str):
            raise _RequestError(400, "Invalid request body", "title must be a string")
        page = self.confluence.pages[page_id]
        if any(other["id"] != page_id and other["spaceId"] == page["spaceId"] and other["status"] == "current" and other["title"] == data["title"] for other in self.confluence.pages.values()):
            raise _RequestError(400, "A page with this title already exists", "A page already exists with the same TITLE in this space")
        page["title"] = data["title"]
        page["status"] = data["status"]
        created = self.confluence._tick()
        current = page["versions"][-1]
        page["versions"].append({"number": current["number"] + 1, "createdAt": created, "message": "", "minorEdit": False, "authorId": _ACCOUNT_ID, "body": current["body"]})
        self._reply_json(200, self._page_model(page, include_base=True))

    def _get_page_ancestors(self, page_id: str, query: dict[str, list[str]]) -> None:
        self._require_known_query(query, {"limit"})
        if page_id not in self.confluence.pages:
            raise _RequestError(404, "Not found", f"Page not found: {page_id}", code="NOT_FOUND")
        limit = self._parse_limit(query, default=25)
        items = [{"id": page["id"], "type": "page"} for page in self.confluence._page_ancestors(page_id)][:limit]
        self._reply_json(200, {"results": items, "_links": {"base": self.confluence.base_url}})

    def _get_page_descendants(self, page_id: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        self._require_known_query(query, {"depth", "cursor", "limit"})
        if page_id not in self.confluence.pages:
            raise _RequestError(404, "Not found", f"Page not found: {page_id}", code="NOT_FOUND")
        depth = self._single(query, "depth") or "2"
        if depth not in _DESCENDANT_DEPTH:
            raise _RequestError(400, "Invalid request parameter", f"Unsupported value for depth: {depth}")
        offset = self._parse_cursor(query)
        limit = self._parse_limit(query, default=25)
        max_depth = int(depth)
        queue = [(child, 1) for child in self.confluence._children(page_id)]
        items: list[dict[str, Any]] = []
        while queue:
            current, current_depth = queue.pop(0)
            items.append(self._descendant_model(current, current_depth))
            if current_depth < max_depth:
                for child in self.confluence._children(current["id"]):
                    queue.append((child, current_depth + 1))
        page_items, links, headers = self._apply_pagination(items, path=f"/api/v2/pages/{page_id}/descendants", query_pairs=query_pairs, offset=offset, limit=limit)
        self._reply_json(200, {"results": page_items, "_links": links}, headers)

    def _get_page_children(self, page_id: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        self._require_known_query(query, {"cursor", "limit", "sort"})
        if page_id not in self.confluence.pages:
            raise _RequestError(404, "Not found", f"Page not found: {page_id}", code="NOT_FOUND")
        sort = self._single(query, "sort") or "id"
        if sort not in _PAGE_SORTS:
            raise _RequestError(400, "Invalid request parameter", f"Unsupported value for sort: {sort}")
        offset = self._parse_cursor(query)
        limit = self._parse_limit(query, default=25)
        children = self._sort_pages(self.confluence._children(page_id), sort)
        items = [self._descendant_model(child, 1) for child in children]
        page_items, links, headers = self._apply_pagination(items, path=f"/api/v2/pages/{page_id}/direct-children", query_pairs=query_pairs, offset=offset, limit=limit)
        self._reply_json(200, {"results": page_items, "_links": links}, headers)

    def _get_page_versions(self, page_id: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        self._require_known_query(query, {"body-format", "cursor", "limit", "sort"})
        if page_id not in self.confluence.pages:
            raise _RequestError(404, "Not found", f"Page not found: {page_id}", code="NOT_FOUND")
        body_format = self._single(query, "body-format")
        if body_format not in {None, "storage", "atlas_doc_format"}:
            raise _RequestError(400, "Invalid request parameter", f"Unsupported value for body-format: {body_format}")
        if body_format == "atlas_doc_format":
            raise _RequestError(400, "Invalid request parameter", "body-format atlas_doc_format is not implemented by this mock")
        sort = self._single(query, "sort") or "-modified-date"
        if sort not in _VERSION_SORTS:
            raise _RequestError(400, "Invalid request parameter", f"Unsupported value for sort: {sort}")
        offset = self._parse_cursor(query)
        limit = self._parse_limit(query, default=25)
        page = self.confluence.pages[page_id]
        versions = list(page["versions"])
        versions.sort(key=lambda item: item["createdAt"], reverse=sort.startswith("-"))
        items = []
        for version in versions:
            entry = {
                "number": version["number"],
                "createdAt": version["createdAt"],
                "message": version["message"],
                "minorEdit": version["minorEdit"],
                "authorId": version["authorId"],
                "page": {"id": page["id"], "title": page["title"], "version": version["number"]},
            }
            if body_format == "storage":
                entry["page"]["body"] = self._response_body(version["body"])
            items.append(entry)
        page_items, links, headers = self._apply_pagination(items, path=f"/api/v2/pages/{page_id}/versions", query_pairs=query_pairs, offset=offset, limit=limit)
        self._reply_json(200, {"results": page_items, "_links": links}, headers)

    def _get_page_labels(self, page_id: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        self._require_known_query(query, {"prefix", "sort", "cursor", "limit"})
        if page_id not in self.confluence.pages:
            raise _RequestError(404, "Not found", f"Page not found: {page_id}", code="NOT_FOUND")
        prefix = self._single(query, "prefix")
        if prefix not in {None, *sorted(_LABEL_PREFIXES)}:
            raise _RequestError(400, "Invalid request parameter", f"Unsupported value for prefix: {prefix}")
        sort = self._single(query, "sort") or "name"
        if sort not in {"name", "-name"}:
            raise _RequestError(400, "Invalid request parameter", f"Unsupported value for sort: {sort}")
        offset = self._parse_cursor(query)
        limit = self._parse_limit(query, default=25)
        labels = sorted(self.confluence.pages[page_id]["labels"], reverse=sort.startswith("-"))
        items = [self._label_model(page_id, label) for label in labels if prefix in {None, "global"}]
        page_items, links, headers = self._apply_pagination(items, path=f"/api/v2/pages/{page_id}/labels", query_pairs=query_pairs, offset=offset, limit=limit)
        self._reply_json(200, {"results": page_items, "_links": links}, headers)

    def _get_page_comments(self, page_id: str, collection: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        allowed = {"body-format", "status", "sort", "cursor", "limit"}
        if collection == "inline-comments":
            allowed.add("resolution-status")
        self._require_known_query(query, allowed)
        if page_id not in self.confluence.pages:
            raise _RequestError(404, "Not found", f"Page not found: {page_id}", code="NOT_FOUND")
        body_format = self._single(query, "body-format")
        if body_format not in {None, "storage", "atlas_doc_format"}:
            raise _RequestError(400, "Invalid request parameter", f"Unsupported value for body-format: {body_format}")
        if body_format == "atlas_doc_format":
            raise _RequestError(400, "Invalid request parameter", "body-format atlas_doc_format is not implemented by this mock")
        self._parse_csv_enum(self._single(query, "status") or "current", "status", _COMMENT_STATUS)
        if collection == "inline-comments" and "resolution-status" in query:
            self._parse_csv_enum(self._single(query, "resolution-status"), "resolution-status", {"resolved", "open", "dangling", "reopened"})
        sort = self._single(query, "sort") or "created-date"
        if sort not in _COMMENT_SORTS:
            raise _RequestError(400, "Invalid request parameter", f"Unsupported value for sort: {sort}")
        offset = self._parse_cursor(query)
        limit = self._parse_limit(query, default=25)
        kind = "footer" if collection == "footer-comments" else "inline"
        items = [comment for comment in self.confluence.comments.values() if comment["pageId"] == page_id and comment["kind"] == kind and not comment.get("parentCommentId")]
        items.sort(key=lambda item: item["version"]["createdAt"], reverse=sort.startswith("-"))
        models = [self._comment_model(comment, body_format=body_format) for comment in items]
        page_items, links, headers = self._apply_pagination(models, path=f"/api/v2/pages/{page_id}/{collection}", query_pairs=query_pairs, offset=offset, limit=limit)
        self._reply_json(200, {"results": page_items, "_links": links}, headers)

    def _get_comment_children(self, collection: str, comment_id: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        self._require_known_query(query, {"body-format", "sort", "cursor", "limit"})
        if comment_id not in self.confluence.comments:
            raise _RequestError(404, "Not found", f"Comment not found: {comment_id}", code="NOT_FOUND")
        parent = self.confluence.comments[comment_id]
        kind = "footer" if collection == "footer-comments" else "inline"
        if parent["kind"] != kind:
            raise _RequestError(404, "Not found", f"Comment not found: {comment_id}", code="NOT_FOUND")
        body_format = self._single(query, "body-format")
        if body_format not in {None, "storage", "atlas_doc_format"}:
            raise _RequestError(400, "Invalid request parameter", f"Unsupported value for body-format: {body_format}")
        if body_format == "atlas_doc_format":
            raise _RequestError(400, "Invalid request parameter", "body-format atlas_doc_format is not implemented by this mock")
        sort = self._single(query, "sort") or "created-date"
        if sort not in _COMMENT_SORTS:
            raise _RequestError(400, "Invalid request parameter", f"Unsupported value for sort: {sort}")
        offset = self._parse_cursor(query)
        limit = self._parse_limit(query, default=25)
        items = [comment for comment in self.confluence.comments.values() if comment.get("parentCommentId") == comment_id and comment["kind"] == kind]
        items.sort(key=lambda item: item["version"]["createdAt"], reverse=sort.startswith("-"))
        models = [self._comment_model(comment, body_format=body_format) for comment in items]
        page_items, links, headers = self._apply_pagination(models, path=f"/api/v2/{collection}/{comment_id}/children", query_pairs=query_pairs, offset=offset, limit=limit)
        self._reply_json(200, {"results": page_items, "_links": links}, headers)

    def _post_footer_comment(self, body: Any) -> None:
        data = self._require_object(body)
        if "body" not in data:
            raise _RequestError(400, "Invalid request body", "body is required")
        page_id = data.get("pageId")
        if not isinstance(page_id, str):
            raise _RequestError(400, "Invalid request body", "pageId is required in this mock")
        if page_id not in self.confluence.pages:
            raise _RequestError(404, "Not found", f"Page not found: {page_id}", code="NOT_FOUND")
        parent_id = data.get("parentCommentId")
        if parent_id is not None:
            if not isinstance(parent_id, str) or parent_id not in self.confluence.comments:
                raise _RequestError(400, "Invalid request body", "parentCommentId must refer to an existing comment")
        body_value = self._parse_body_value(data["body"]) or ""
        comment_id = str(self.confluence._next_comment)
        self.confluence._next_comment += 1
        created = self.confluence._tick()
        self.confluence.comments[comment_id] = {"id": comment_id, "kind": "footer", "pageId": page_id, "parentCommentId": parent_id, "authorId": _ACCOUNT_ID, "version": {"number": 1, "createdAt": created}, "body": body_value, "resolutionStatus": None}
        self._reply_json(201, self._comment_model(self.confluence.comments[comment_id], body_format="storage"), {"Location": f"{self.confluence.context_path}/api/v2/footer-comments/{comment_id}"})

    def _get_page_attachments(self, page_id: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        self._require_known_query(query, {"sort", "cursor", "status", "mediaType", "filename", "limit"})
        if page_id not in self.confluence.pages:
            raise _RequestError(404, "Not found", f"Page not found: {page_id}", code="NOT_FOUND")
        sort = self._single(query, "sort") or "id"
        if sort not in {"id", "-id", "created-date", "-created-date", "title", "-title"}:
            raise _RequestError(400, "Invalid request parameter", f"Unsupported value for sort: {sort}")
        if "status" in query:
            self._parse_csv_enum(self._single(query, "status"), "status", {"current", "archived", "trashed"})
        offset = self._parse_cursor(query)
        limit = self._parse_limit(query, default=50)
        media_type = self._single(query, "mediaType")
        filename = self._single(query, "filename")
        items = [attachment for attachment in self.confluence.attachments.values() if attachment["pageId"] == page_id]
        if media_type is not None:
            items = [attachment for attachment in items if attachment["mediaType"] == media_type]
        if filename is not None:
            items = [attachment for attachment in items if attachment["title"] == filename]
        reverse = sort.startswith("-")
        key = sort.lstrip("-")
        if key == "id":
            items.sort(key=lambda attachment: int(attachment["id"].removeprefix("att")), reverse=reverse)
        elif key == "created-date":
            items.sort(key=lambda attachment: attachment["versions"][0]["createdAt"], reverse=reverse)
        else:
            items.sort(key=lambda attachment: attachment["title"].lower(), reverse=reverse)
        models = [self._attachment_model(attachment) for attachment in items]
        page_items, links, headers = self._apply_pagination(models, path=f"/api/v2/pages/{page_id}/attachments", query_pairs=query_pairs, offset=offset, limit=limit)
        self._reply_json(200, {"results": page_items, "_links": links}, headers)

    def _get_attachment(self, attachment_id: str, query: dict[str, list[str]]) -> None:
        self._require_known_query(query, {"version", "include-labels", "include-properties", "include-operations", "include-versions", "include-version", "include-collaborators"})
        if attachment_id not in self.confluence.attachments:
            raise _RequestError(404, "Not found", f"Attachment not found: {attachment_id}", code="NOT_FOUND")
        for name in {"include-labels", "include-properties", "include-operations", "include-versions", "include-version", "include-collaborators"}:
            self._parse_bool(self._single(query, name), name)
        version_number = self._parse_int_query(self._single(query, "version"), "version")
        attachment = self.confluence.attachments[attachment_id]
        if version_number is not None and version_number not in {item["number"] for item in attachment["versions"]}:
            raise _RequestError(404, "Not found", f"Attachment version not found: {version_number}", code="NOT_FOUND")
        self._reply_json(200, self._attachment_model(attachment, version_number=version_number))

    def _post_users_bulk(self, body: Any) -> None:
        data = self._require_object(body)
        account_ids = data.get("accountIds")
        if not isinstance(account_ids, list) or not account_ids:
            raise _RequestError(400, "Invalid request body", "accountIds must be a non-empty list")
        if len(account_ids) > 250 or any(not isinstance(item, str) for item in account_ids):
            raise _RequestError(400, "Invalid request body", "accountIds must contain 1 to 250 strings")
        results = []
        for account_id in account_ids:
            user = self.confluence.users.get(account_id)
            if user is not None:
                results.append({"accountId": user["accountId"], "accountType": "atlassian", "email": user["email"], "publicName": user["publicName"], "displayName": user["displayName"]})
        self._reply_json(200, {"results": results, "_links": {"base": self.confluence.base_url}})

    def _parse_cql(self, raw: str) -> tuple[list[tuple[str, Any]], str | None]:
        text = raw.strip()
        order = None
        order_match = re.search(r"\s+ORDER\s+BY\s+lastmodified\s+(ASC|DESC)\s*$", text, re.I)
        if order_match:
            order = order_match.group(1).upper()
            text = text[: order_match.start()].strip()
        parts: list[str] = []
        current: list[str] = []
        in_quotes = False
        escape = False
        index = 0
        while index < len(text):
            char = text[index]
            if escape:
                current.append(char)
                escape = False
            elif char == "\\":
                current.append(char)
                escape = True
            elif char == '"':
                current.append(char)
                in_quotes = not in_quotes
            elif not in_quotes and text[index:index + 4].upper() == " AND":
                parts.append("".join(current).strip())
                current = []
                index += 3
            else:
                current.append(char)
            index += 1
        if in_quotes:
            raise _RequestError(400, "Bad Request", f"Could not parse cql: {raw}", old=True, old_key="BAD_REQUEST")
        if current or text:
            parts.append("".join(current).strip())
        clauses: list[tuple[str, Any]] = []
        for part in parts:
            if not part:
                continue
            match = re.fullmatch(r"type\s*=\s*(page|blogpost|attachment|comment)", part, re.I)
            if match:
                clauses.append(("type", {match.group(1).lower()}))
                continue
            match = re.fullmatch(r"type\s+in\s*\((.+)\)", part, re.I)
            if match:
                values = []
                for token in match.group(1).split(","):
                    token = token.strip().strip('"').lower()
                    if token not in {"page", "blogpost", "attachment", "comment"}:
                        raise _RequestError(400, "Bad Request", f"Could not parse cql: {raw}", old=True, old_key="BAD_REQUEST")
                    values.append(token)
                clauses.append(("type", set(values)))
                continue
            match = re.fullmatch(r'space\s*=\s*"((?:\\.|[^"])*)"', part, re.I)
            if match:
                clauses.append(("space", bytes(match.group(1), "utf-8").decode("unicode_escape")))
                continue
            match = re.fullmatch(r'text\s*~\s*"((?:\\.|[^"])*)"', part, re.I)
            if match:
                clauses.append(("text", _text_terms(match.group(1))))
                continue
            match = re.fullmatch(r'\(\s*(text\s*~\s*"(?:\\.|[^"])*"(?:\s+OR\s+text\s*~\s*"(?:\\.|[^"])*")+)\s*\)', part, re.I)
            if match:
                values = re.findall(r'text\s*~\s*"((?:\\.|[^"])*)"', match.group(1))
                clauses.append(("textany", [term for value in values for term in _text_terms(value)]))
                continue
            match = re.fullmatch(r'title\s*~\s*"((?:\\.|[^"])*)"', part, re.I)
            if match:
                clauses.append(("title", bytes(match.group(1), "utf-8").decode("unicode_escape")))
                continue
            match = re.fullmatch(r'label\s*=\s*"((?:\\.|[^"])*)"', part, re.I)
            if match:
                clauses.append(("label", bytes(match.group(1), "utf-8").decode("unicode_escape").lower()))
                continue
            match = re.fullmatch(r'ancestor\s*=\s*(\d+)', part, re.I)
            if match:
                clauses.append(("ancestor", match.group(1)))
                continue
            match = re.fullmatch(r'lastmodified\s*>=\s*"(\d{4}-\d{2}-\d{2})"', part, re.I)
            if match:
                clauses.append(("lastmodified", match.group(1)))
                continue
            raise _RequestError(400, "Bad Request", f"Could not parse cql: {raw}", old=True, old_key="BAD_REQUEST")
        return clauses, order

    def _search(self, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        self._require_known_query(query, {"cql", "limit", "start", "excerpt", "cursor", "next", "prev", "cqlcontext", "includeArchivedSpaces", "excludeCurrentSpaces", "sitePermissionTypeFilter", "_", "expand"}, old=True)
        cql = self._single(query, "cql")
        if cql is None:
            raise _RequestError(400, "Bad Request", "Could not parse cql: missing cql", old=True, old_key="BAD_REQUEST")
        excerpt = self._single(query, "excerpt") or "highlight"
        if excerpt not in _OLD_EXCERPTS:
            raise _RequestError(400, "Bad Request", f"Unsupported value for excerpt: {excerpt}", old=True, old_key="BAD_REQUEST")
        limit = self._parse_search_limit(query)
        start = self._parse_start(query)
        self._parse_bool(self._single(query, "next"), "next", old=True)
        self._parse_bool(self._single(query, "prev"), "prev", old=True)
        self._parse_bool(self._single(query, "includeArchivedSpaces"), "includeArchivedSpaces", old=True)
        self._parse_bool(self._single(query, "excludeCurrentSpaces"), "excludeCurrentSpaces", old=True)
        permission = self._single(query, "sitePermissionTypeFilter") or "none"
        if permission not in _OLD_SITE_PERMISSIONS:
            raise _RequestError(400, "Bad Request", f"Unsupported value for sitePermissionTypeFilter: {permission}", old=True, old_key="BAD_REQUEST")
        if "_" in query:
            self._parse_int_query(self._single(query, "_"), "_", old=True)
        expand: list[str] = []
        if "expand" in query:
            expand = self._parse_csv(self._single(query, "expand"), "expand", old=True)
            unknown = [value for value in expand if value not in _SEARCH_EXPANDS]
            if unknown:
                raise _RequestError(400, "Bad Request", f"Unsupported value for expand: {unknown[0]}", old=True, old_key="BAD_REQUEST")
        clauses, order = self._parse_cql(cql)
        pages = [page for page in self.confluence.pages.values() if page["status"] == "current"]
        words: list[str] = []
        for kind, value in clauses:
            if kind == "type":
                if "page" not in value:
                    pages = []
            elif kind == "space":
                pages = [page for page in pages if self.confluence.spaces[page["spaceId"]]["key"] == value]
            elif kind == "text":
                words = words + [term.strip('"') for term in value]
                pages = [page for page in pages if all(_term_in(f"{page['title']} {_plain_text(page['versions'][-1]['body'])}", term) for term in value)]
            elif kind == "textany":
                words = words + [term.strip('"') for term in value]
                pages = [page for page in pages if any(_term_in(f"{page['title']} {_plain_text(page['versions'][-1]['body'])}", term) for term in value)]
            elif kind == "title":
                words = value.split()
                pages = [page for page in pages if value.lower() in page["title"].lower()]
            elif kind == "label":
                pages = [page for page in pages if value in page["labels"]]
            elif kind == "ancestor":
                pages = [page for page in pages if value in {ancestor["id"] for ancestor in self.confluence._page_ancestors(page["id"])}]
            elif kind == "lastmodified":
                pages = [page for page in pages if page["versions"][-1]["createdAt"][:10] >= value]
        pages.sort(key=lambda item: item["versions"][-1]["createdAt"], reverse=(order or "DESC") == "DESC")
        total = len(pages)
        size = min(limit, self.confluence.page_cap)
        shown = pages[start:start + size]
        results = []
        for page in shown:
            plain = html.escape(_plain_text(page["versions"][-1]["body"]), quote=False)  # the real search escapes what it returns
            highlight_words = [html.escape(word, quote=False) for word in (words or [page["title"]])]
            content: dict[str, Any] = {"id": page["id"], "type": "page", "status": "current", "title": page["title"], "_links": {"webui": self.confluence._page_webui(page)}}
            if "content.ancestors" in expand:
                content["ancestors"] = [{"id": ancestor["id"], "type": "page", "status": "current", "title": ancestor["title"]} for ancestor in self.confluence._page_ancestors(page["id"])]
            if "content.metadata.labels" in expand:
                names = page["labels"]
                content["metadata"] = {"labels": {"results": [{"prefix": "global", "name": name, "id": str(index), "label": name} for index, name in enumerate(names, 1)], "start": 0, "limit": 200, "size": len(names)}}
            if "content.version" in expand:
                content["version"] = {"number": page["versions"][-1]["number"], "when": page["versions"][-1]["createdAt"]}
            results.append(
                {
                    "content": content,
                    "title": _highlight(html.escape(page["title"], quote=False), highlight_words),
                    "excerpt": _excerpt(plain, highlight_words),
                    "url": self.confluence._page_webui(page),
                    "resultGlobalContainer": {"title": self.confluence.spaces[page["spaceId"]]["name"], "displayUrl": f"/spaces/{self.confluence.spaces[page['spaceId']]['key']}"},
                    "entityType": "content",
                    "lastModified": page["versions"][-1]["createdAt"],
                    "friendlyLastModified": _friendly_date(page["versions"][-1]["createdAt"]),
                    "score": 1.0,
                }
            )
        self._reply_json(200, {"results": results, "start": start, "limit": limit, "size": len(results), "totalSize": total, "cqlQuery": cql, "searchDuration": 1, "_links": {"base": self.confluence.base_url, "context": self.confluence.context_path or "/"}})

    def _add_labels(self, page_id: str, body: Any) -> None:
        if page_id not in self.confluence.pages:
            raise _RequestError(404, "Not found", f"Page not found: {page_id}", old=True, old_key="NOT_FOUND")
        entries = body if isinstance(body, list) else [body]
        if not entries or any(not isinstance(item, dict) for item in entries):
            raise _RequestError(400, "Bad Request", "Invalid label payload", old=True, old_key="BAD_REQUEST")
        labels = self.confluence.pages[page_id]["labels"]
        for entry in entries:
            if entry.get("prefix") != "global" or not isinstance(entry.get("name"), str):
                raise _RequestError(400, "Bad Request", "prefix and name are required", old=True, old_key="BAD_REQUEST")
            name = entry["name"].lower()
            if any(char in _FORBIDDEN_LABEL_CHARS for char in name):
                raise _RequestError(400, "Bad Request", f"Invalid label name: {entry['name']}", old=True, old_key="BAD_REQUEST")
            if name not in labels:
                labels.append(name)
        labels.sort()
        self._reply_json(200, {"results": [self._label_model(page_id, label) for label in labels], "start": 0, "limit": 200, "size": len(labels)})

    def _delete_label(self, page_id: str, name: str) -> None:
        page = self.confluence.pages.get(page_id)
        if page is None:
            raise _RequestError(404, "Not found", f"Page not found: {page_id}", old=True, old_key="NOT_FOUND")
        lowered = name.lower()
        if lowered not in page["labels"]:
            raise _RequestError(404, "Not found", f"Label not found: {name}", old=True, old_key="NOT_FOUND")
        page["labels"].remove(lowered)
        self._reply_json(204, None)

    def _upload_attachment(self, method: str, page_id: str, query: dict[str, list[str]], body: Any) -> None:
        self._require_known_query(query, {"status"}, old=True)
        if page_id not in self.confluence.pages:
            raise _RequestError(404, "Not found", f"Page not found: {page_id}", old=True, old_key="NOT_FOUND")
        status = self._single(query, "status") or "current"
        if status not in {"current", "draft"}:
            raise _RequestError(400, "Bad Request", f"Unsupported value for status: {status}", old=True, old_key="BAD_REQUEST")
        if self.headers.get("X-Atlassian-Token", "") != "nocheck":
            raise _RequestError(403, "Forbidden", "XSRF check failed", payload={"message": "XSRF check failed"})
        if not isinstance(body, dict) or not isinstance(body.get("file"), dict):
            raise _RequestError(400, "Bad Request", "file part is required", old=True, old_key="BAD_REQUEST")
        file_part = body["file"]
        fields = body.get("fields") or {}
        name = file_part.get("name")
        if not isinstance(name, str) or not name:
            raise _RequestError(400, "Bad Request", "file part must have a filename", old=True, old_key="BAD_REQUEST")
        data = file_part.get("data")
        if not isinstance(data, (bytes, bytearray)):
            raise _RequestError(400, "Bad Request", "file part must contain bytes", old=True, old_key="BAD_REQUEST")
        media_type = file_part.get("type") or "application/octet-stream"
        existing = next((attachment for attachment in self.confluence.attachments.values() if attachment["pageId"] == page_id and attachment["title"] == name), None)
        if method == "POST" and existing is not None:
            raise _RequestError(400, "Bad Request", "Cannot add a new attachment with same file name as an existing attachment", old=True, old_key="BAD_REQUEST")
        if existing is None:
            attachment_id = f"att{self.confluence._next_attachment}"
            self.confluence._next_attachment += 1
            existing = {"id": attachment_id, "pageId": page_id, "title": name, "mediaType": media_type, "comment": fields.get("comment", ""), "versions": []}
            self.confluence.attachments[attachment_id] = existing
        created = self.confluence._tick()
        existing["mediaType"] = media_type
        existing["comment"] = fields.get("comment", existing.get("comment", ""))
        existing["versions"].append({"number": len(existing["versions"]) + 1, "createdAt": created, "data": bytes(data)})
        page = self.confluence.pages[page_id]
        result = {
            "id": existing["id"],
            "type": "attachment",
            "status": "current",
            "title": existing["title"],
            "version": {"number": existing["versions"][-1]["number"], "when": created},
            "extensions": {"mediaType": existing["mediaType"], "fileSize": len(existing["versions"][-1]["data"]), "comment": existing["comment"]},
            "container": {"id": page_id, "type": "page", "title": page["title"]},
            "_links": {"download": self.confluence._attachment_download_path(existing)},
        }
        self._reply_json(200, {"results": [result], "size": 1})

    def _send_attachment_redirect(self, attachment: dict[str, Any], version_number: int | None = None) -> None:
        version_number = attachment["versions"][-1]["number"] if version_number is None else version_number
        if version_number not in {item["number"] for item in attachment["versions"]}:
            raise _RequestError(404, "Not found", f"Attachment version not found: {version_number}", old=True, old_key="NOT_FOUND")
        location = f"{self.confluence.media_url}/file/{attachment['id']}/binary?token={self.confluence._media_secret}&name={quote(attachment['title'])}&version={version_number}"
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _attachment_redirect_by_id(self, page_id: str, attachment_id: str, query: dict[str, list[str]]) -> None:
        attachment = self.confluence.attachments.get(attachment_id)
        if attachment is None or attachment["pageId"] != page_id:
            raise _RequestError(404, "Not found", f"Attachment not found: {attachment_id}", old=True, old_key="NOT_FOUND")
        version = self._parse_int_query(self._single(query, "version"), "version", old=True)
        if "status" in query:
            self._parse_csv(self._single(query, "status"), "status", old=True)
        self._send_attachment_redirect(attachment, version)

    def _move_page(self, page_id: str, position: str, target_id: str) -> None:
        if position not in _MOVE_POSITIONS:
            raise _RequestError(400, "Bad Request", f"Unsupported value for position: {position}", old=True, old_key="BAD_REQUEST")
        if page_id not in self.confluence.pages or target_id not in self.confluence.pages:
            raise _RequestError(404, "Not found", "Page not found", old=True, old_key="NOT_FOUND")
        if page_id == target_id or self.confluence._is_descendant(page_id, target_id):
            raise _RequestError(400, "Bad Request", "Cannot move a page below itself or one of its descendants", old=True, old_key="BAD_REQUEST")
        page = self.confluence.pages[page_id]
        target = self.confluence.pages[target_id]
        old_parent = page["parentId"]
        old_siblings = [item for item in self.confluence._children(old_parent) if item["id"] != page_id]
        for index, sibling in enumerate(old_siblings):
            sibling["position"] = index
        if position == "append":
            new_parent = target_id
            siblings = self.confluence._children(new_parent)
            page["parentId"] = new_parent
            page["position"] = len(siblings)
        else:
            new_parent = target["parentId"]
            siblings = [item for item in self.confluence._children(new_parent) if item["id"] != page_id]
            insert_at = next(index for index, item in enumerate(siblings) if item["id"] == target_id)
            if position == "after":
                insert_at += 1
            siblings.insert(insert_at, page)
            page["parentId"] = new_parent
            for index, sibling in enumerate(siblings):
                sibling["position"] = index
        self.confluence._resequence(old_parent)
        if position == "append":
            self.confluence._resequence(target_id)
        else:
            self.confluence._resequence(new_parent)
        self._reply_json(200, {"id": page_id})


class _MediaHandler(_BaseHandler):
    def route(self, method: str) -> None:
        body, raw, _ = self._read_body()
        url = urlparse(self.path)
        path = unquote(url.path)
        query = parse_qs(url.query, keep_blank_values=True)
        headers = {key.lower(): value for key, value in self.headers.items()}
        self.confluence.media_requests.append(Recorded(method, path, query, headers, body, raw))
        match = re.fullmatch(r"/file/(att\d+)/binary", path)
        if method != "GET" or not match:
            self._reply_bytes(404, b"not found", content_type="text/plain;charset=UTF-8")
            return
        attachment = self.confluence.attachments.get(match.group(1))
        if attachment is None:
            self._reply_bytes(404, b"not found", content_type="text/plain;charset=UTF-8")
            return
        token = (query.get("token") or [""])[0]
        if token != self.confluence._media_secret:
            self._reply_bytes(403, b"forbidden", content_type="text/plain;charset=UTF-8")
            return
        version_raw = (query.get("version") or [str(attachment["versions"][-1]["number"])])[0]
        if not version_raw.isdigit():
            self._reply_bytes(404, b"not found", content_type="text/plain;charset=UTF-8")
            return
        version = next((item for item in attachment["versions"] if item["number"] == int(version_raw)), None)
        if version is None:
            self._reply_bytes(404, b"not found", content_type="text/plain;charset=UTF-8")
            return
        self._reply_bytes(200, version["data"], {"Content-Length": str(len(version["data"]))}, attachment["mediaType"])
