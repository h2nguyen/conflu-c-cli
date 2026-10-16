"""The Confluence port implemented over Confluence Cloud's REST APIs.

Pages, spaces, comments, versions and attachments are read and written through API v2 (`/api/v2`). A few things have no
v2 equivalent and use the older API (`/rest/api`): search with CQL, the current user, adding and removing labels,
uploading attachments and moving a page.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import re
import urllib.parse
import uuid
from typing import Any, Sequence

from ...application.paging import fetch_all
from ...application.ports import ConfluenceGateway
from ...application.settings import Settings, is_local_host
from ...domain.errors import (
    AuthError,
    ConfigError,
    ConflictError,
    NotFoundError,
    RejectedError,
    UnavailableError,
)
from ...domain.model import (
    Attachment,
    Chunk,
    Comment,
    Label,
    Page,
    PageRef,
    SearchPage,
    Space,
    TreeNode,
    User,
    VersionInfo,
)
from ...domain.privacy import strip_users
from . import confluence_mapper as mapper
from .http_transport import HttpResponse, HttpTransport

V2 = "/api/v2"
V1 = "/rest/api"
BULK_USERS = 250
SEARCH_EXPAND = "content.ancestors,content.metadata.labels,content.version"  # where a hit lives, how it is tagged, its version


def _quote(value: str) -> str:
    return urllib.parse.quote(str(value), safe="")


def _request_target(path: str) -> str:
    """A path and query as a person typed them, made fit for a request line: the fragment goes (no server ever sees one),
    a space, a quote or a non-ASCII character becomes %XX, and an escape that is there already stays as it is."""
    path = re.sub(r"%(?![0-9A-Fa-f]{2})", "%25", path.split("#", 1)[0])
    return urllib.parse.quote(path, safe="%!$&'()*+,/:;=?@[]~-._")


def _query(**params: Any) -> str:
    """A query string from the parameters that have a value (`True` becomes `true`)."""
    pairs = []
    for name, value in params.items():
        if value is None or value == "" or (isinstance(value, (list, tuple)) and not value):
            continue
        text = "true" if value is True else "false" if value is False else ",".join(map(str, value)) if isinstance(value, (list, tuple)) else str(value)
        pairs.append((name.replace("_", "-"), text))
    return urllib.parse.urlencode(pairs, quote_via=urllib.parse.quote)


def _messages(body: Any) -> str:
    """Confluence's own explanation of a refusal, in the shapes both APIs use."""
    if not isinstance(body, dict):
        return ""
    parts: list[str] = []
    errors = body.get("errors")
    if isinstance(errors, list):
        for item in errors:
            if isinstance(item, dict):
                text = item.get("detail") or item.get("title") or item.get("message")
                if isinstance(text, dict):
                    text = text.get("translation") or text.get("key")
                if text:
                    parts.append(str(text))
            elif item:
                parts.append(str(item))
    data = body.get("data")
    if isinstance(data, dict) and isinstance(data.get("errors"), list):
        for item in data["errors"]:
            text = item.get("message") if isinstance(item, dict) else item
            if isinstance(text, dict):
                text = text.get("translation") or text.get("key")
            if text:
                parts.append(str(text))
    for key in ("message", "reason"):
        if isinstance(body.get(key), str) and body[key] and body[key] not in parts:
            parts.append(body[key])
    return "; ".join(dict.fromkeys(parts))


def _without_secrets(value: Any, secrets: Sequence[str]) -> Any:
    """The value with every occurrence of a secret replaced, in strings at any depth."""
    usable = [secret for secret in secrets if len(secret) >= 6]  # too short to be a secret; replacing it would only damage the text
    if not usable:
        return value
    if isinstance(value, str):
        for secret in usable:
            value = value.replace(secret, "********")
        return value
    if isinstance(value, dict):
        return {key: _without_secrets(item, usable) for key, item in value.items()}
    if isinstance(value, list):
        return [_without_secrets(item, usable) for item in value]
    return value


def _multipart(fields: dict[str, str], filename: str, data: bytes) -> tuple[bytes, str]:
    """A multipart/form-data body with the text fields and one file; its content type carries the boundary."""
    boundary = "----conflu" + uuid.uuid4().hex
    safe_name = re.sub(r'[\r\n"]', "_", filename)
    guessed = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8")
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{safe_name}"\r\nContent-Type: {guessed}\r\n\r\n'.encode("utf-8")
        + data
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class RestConfluenceGateway(ConfluenceGateway):
    def __init__(self, settings: Settings, transport: HttpTransport) -> None:
        self._settings = settings
        self._transport = transport

    # -- plumbing ---------------------------------------------------------------------------

    def _call(self, method: str, path: str, body: Any = None, *, timeout: float | None = None, retries: int | None = None) -> Any:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        response = self._transport.request(method, path, body=payload, timeout=timeout, retries=retries)
        return self._finish(response, method, path)

    def _finish(self, response: HttpResponse, method: str, path: str) -> Any:
        decoded = self._decode(response)
        self._raise_for_status(response, decoded, method, path)
        return decoded

    @staticmethod
    def _decode(response: HttpResponse) -> Any:
        if not response.body.strip():
            return {}
        try:
            return json.loads(response.body.decode("utf-8"))
        except ValueError:
            return {"_text": response.body.decode("utf-8", "replace")[:500]}

    def _scrub(self, value: Any) -> Any:
        """Confluence's explanation of a refusal ends up in our error output. Take the credentials out in case something
        in between echoed them, and under the privacy policy the people."""
        if self._settings.hide_users:
            value = strip_users(value)
        credentials = f"{self._settings.email}:{self._settings.api_token}".encode("utf-8")
        return _without_secrets(value, [self._settings.api_token, base64.b64encode(credentials).decode("ascii"), self._settings.email])

    def _custom_domain_hint(self) -> str:
        """API tokens are accepted on `SITE.atlassian.net` and on the gateway at api.atlassian.com, not on a company's own
        domain for the site: there the credentials are not read and Confluence answers as it does an anonymous caller."""
        host = (urllib.parse.urlsplit(self._settings.base_url).hostname or "").lower()
        if not host or host.endswith(".atlassian.net") or host == "api.atlassian.com" or is_local_host(host):
            return ""
        return (
            f"{host} is not an atlassian.net address. If it is a custom domain of your Confluence Cloud site, API tokens are not accepted on it: "
            f"open https://{host}/_edge/tenant_info in a browser, copy the cloudId it shows and run "
            "`conflu config set CONFLUENCE_BASE_URL https://api.atlassian.com/ex/confluence/CLOUD_ID`. "
        )

    def _raise_for_status(self, response: HttpResponse, body: Any, method: str, path: str) -> None:
        status = response.status
        if 200 <= status < 300:
            return
        body = self._scrub(body)
        reason = _messages(body)
        shown = path.split("?")[0]
        details = {"status": status, "request": f"{method} {shown}"}
        if 300 <= status < 400:
            target = urllib.parse.urlsplit(response.headers.get("location", ""))
            where = f" to {target.netloc}{target.path}" if target.netloc or target.path else ""
            raise ConfigError(
                f"Confluence answered with a redirect (HTTP {status}){where} instead of data.",
                hint="Check CONFLUENCE_BASE_URL: the address is probably wrong, or it lacks the /wiki (or is http instead of https).",
                details=details,
            )
        if status == 401:
            raise AuthError(
                "Confluence did not accept the credentials (HTTP 401).",
                hint=f"{self._custom_domain_hint()}Check CONFLUENCE_EMAIL and create a new API token at https://id.atlassian.com/manage-profile/security/api-tokens, "
                "then run `conflu setup-token`. A token with scopes needs the https://api.atlassian.com/ex/confluence/CLOUD_ID address.",
                details=details,
            )
        if status == 403:
            raise AuthError(
                f"Confluence refused this request (HTTP 403){': ' + reason if reason else ''}.",
                hint=f"{self._custom_domain_hint()}Your account lacks the permission, or the token's scopes do not cover it. Ask the space administrator.",
                details=details,
            )
        if status == 404:
            raise NotFoundError(
                f"Not found: {method} {shown}{' - ' + reason if reason else ''}",
                hint="Confluence also answers 404 for what the account may not see.",
                details=details,
            )
        if status == 409:
            raise ConflictError(
                f"Confluence reports a conflict (HTTP 409){': ' + reason if reason else ''}.",
                hint="The page changed meanwhile. Read it again and review the current state before writing.",
                details=details,
            )
        if status == 410:
            raise RejectedError(
                f"Confluence says this endpoint is gone (HTTP 410): {method} {shown}",
                hint="Atlassian retires old endpoints. Update conflu-c-cli, or use `conflu api` with the replacement.",
                details=details,
            )
        if status == 429:
            raise UnavailableError(
                "Confluence is limiting the rate of requests (HTTP 429).",
                hint="Wait a moment and try again; fewer requests (for example --limit instead of --all) help.",
                details=details,
            )
        if status >= 500:
            raise UnavailableError(
                f"Confluence answered with a server error (HTTP {status}){': ' + reason if reason else ''}.",
                hint="Try again in a moment; if it stays, check https://status.atlassian.com.",
                details=details,
            )
        raise RejectedError(f"Confluence refused the request (HTTP {status}): {reason or 'no explanation'}", details={**details, "confluence": body})

    @staticmethod
    def _next_cursor(data: Any) -> str:
        link = ((data or {}).get("_links") or {}).get("next") if isinstance(data, dict) else None
        if not isinstance(link, str) or not link:
            return ""
        values = urllib.parse.parse_qs(urllib.parse.urlsplit(link).query).get("cursor") or [""]
        return values[0]

    def _base(self, data: Any) -> str:
        return mapper.base_of(data, self._settings.wiki_url)

    # -- people -----------------------------------------------------------------------------

    def current_user(self) -> User:
        return mapper.user_from(self._call("GET", f"{V1}/user/current")) or User()

    def lookup_users(self, account_ids: Sequence[str]) -> dict[str, User]:
        found: dict[str, User] = {}
        ids = list(dict.fromkeys(account_ids))
        for start in range(0, len(ids), BULK_USERS):
            data = self._call("POST", f"{V2}/users-bulk", {"accountIds": ids[start : start + BULK_USERS]})
            for item in mapper.results_of(data):
                user = mapper.user_from(item)
                if user and user.account_id:
                    found[user.account_id] = user
        return found

    # -- spaces -----------------------------------------------------------------------------

    def list_spaces(self, *, space_type: str = "", status: str = "current", limit: int = 25, cursor: str = "") -> Chunk[Space]:
        query = _query(type=space_type, status=status, limit=limit, cursor=cursor, description_format="plain")
        data = self._call("GET", f"{V2}/spaces?{query}")
        base = self._base(data)
        return Chunk([mapper.space_from(item, base) for item in mapper.results_of(data)], self._next_cursor(data))

    def get_space(self, key: str) -> Space:
        for candidate in dict.fromkeys((key, key.upper())):
            data = self._call("GET", f"{V2}/spaces?{_query(keys=[candidate], description_format='plain')}")
            found = mapper.results_of(data)
            if found:
                return mapper.space_from(found[0], self._base(data))
        raise NotFoundError(f"No space with the key {key}.", hint="`conflu spaces` lists the spaces you can see.", details={"space": key})

    def get_space_by_id(self, space_id: str) -> Space:
        data = self._call("GET", f"{V2}/spaces/{_quote(space_id)}?{_query(description_format='plain')}")
        return mapper.space_from(data, self._base(data))

    # -- pages ------------------------------------------------------------------------------

    def get_page(self, page_id: str, *, with_body: bool = True) -> Page:
        query = _query(include_labels=True, body_format="storage" if with_body else "")
        data = self._call("GET", f"{V2}/pages/{_quote(page_id)}?{query}")
        return mapper.page_from(data, self._settings.wiki_url)

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
        common = dict(title=title, status=status, sort=sort, body_format="storage" if with_body else "", limit=limit, cursor=cursor)
        if space_id and not ids:
            query = _query(depth="root" if root_only else "", **common)
            path = f"{V2}/spaces/{_quote(space_id)}/pages?{query}"
        else:
            path = f"{V2}/pages?{_query(id=list(ids), space_id=space_id, **common)}"
        data = self._call("GET", path)
        base = self._base(data)
        return Chunk([mapper.page_from(item, base) for item in mapper.results_of(data)], self._next_cursor(data))

    def list_ancestors(self, page_id: str) -> list[PageRef]:
        data = self._call("GET", f"{V2}/pages/{_quote(page_id)}/ancestors?{_query(limit=250)}")
        ancestors = [item for item in mapper.results_of(data) if item.get("id")]
        if not ancestors:
            return []
        titles = {
            str(item.get("id")): str(item.get("title") or "")
            for item in mapper.results_of(self._call("GET", f"{V2}/pages?{_query(id=[str(item['id']) for item in ancestors], limit=250)}"))
        }
        return [PageRef(str(item["id"]), titles.get(str(item["id"]), ""), str(item.get("type") or "page")) for item in ancestors]

    def list_descendants(self, page_id: str, *, depth: int = 3, limit: int = 250, cursor: str = "") -> Chunk[TreeNode]:
        data = self._call("GET", f"{V2}/pages/{_quote(page_id)}/descendants?{_query(depth=depth, limit=limit, cursor=cursor)}")
        return Chunk([mapper.tree_node_from(item) for item in mapper.results_of(data)], self._next_cursor(data))

    def list_versions(self, page_id: str, *, limit: int = 25, cursor: str = "") -> Chunk[VersionInfo]:
        data = self._call("GET", f"{V2}/pages/{_quote(page_id)}/versions?{_query(sort='-modified-date', limit=limit, cursor=cursor)}")
        versions = [version for version in map(mapper.version_from, mapper.results_of(data)) if version]
        return Chunk(versions, self._next_cursor(data))

    def create_page(self, payload: dict[str, Any]) -> Page:
        data = self._call("POST", f"{V2}/pages", payload)
        return mapper.page_from(data, self._settings.wiki_url)

    def update_page(self, page_id: str, payload: dict[str, Any]) -> Page:
        data = self._call("PUT", f"{V2}/pages/{_quote(page_id)}", payload)
        return mapper.page_from(data, self._settings.wiki_url)

    def update_title(self, page_id: str, payload: dict[str, Any]) -> Page:
        data = self._call("PUT", f"{V2}/pages/{_quote(page_id)}/title", payload)
        return mapper.page_from(data, self._settings.wiki_url)

    def move_page(self, page_id: str, position: str, target_id: str) -> None:
        self._call("PUT", f"{V1}/content/{_quote(page_id)}/move/{_quote(position)}/{_quote(target_id)}")

    # -- comments ---------------------------------------------------------------------------

    def list_comments(self, page_id: str, *, inline: bool = False, limit: int = 50, cursor: str = "") -> Chunk[Comment]:
        kind = "inline" if inline else "footer"
        query = _query(body_format="storage", sort="created-date", limit=limit, cursor=cursor)
        data = self._call("GET", f"{V2}/pages/{_quote(page_id)}/{kind}-comments?{query}")
        return Chunk([mapper.comment_from(item, kind) for item in mapper.results_of(data)], self._next_cursor(data))

    def list_replies(self, comment_id: str, *, inline: bool = False, limit: int = 50, cursor: str = "") -> Chunk[Comment]:
        kind = "inline" if inline else "footer"
        query = _query(body_format="storage", sort="created-date", limit=limit, cursor=cursor)
        data = self._call("GET", f"{V2}/{kind}-comments/{_quote(comment_id)}/children?{query}")
        return Chunk([mapper.comment_from(item, kind) for item in mapper.results_of(data)], self._next_cursor(data))

    def add_comment(self, payload: dict[str, Any]) -> Comment:
        data = self._call("POST", f"{V2}/footer-comments", payload)
        return mapper.comment_from(data, "footer")

    # -- labels -----------------------------------------------------------------------------

    def list_labels(self, page_id: str) -> list[Label]:
        def read(cursor: str) -> Chunk[Label]:
            data = self._call("GET", f"{V2}/pages/{_quote(page_id)}/labels?{_query(limit=250, cursor=cursor)}")
            return Chunk([mapper.label_from(item) for item in mapper.results_of(data)], self._next_cursor(data))

        return fetch_all(read)[0]  # a removal must see every label, not the first 250

    def add_labels(self, page_id: str, payload: list[dict[str, str]]) -> list[Label]:
        data = self._call("POST", f"{V1}/content/{_quote(page_id)}/label", payload)
        return [mapper.label_from(item) for item in mapper.results_of(data)]

    def remove_label(self, page_id: str, name: str) -> None:
        self._call("DELETE", f"{V1}/content/{_quote(page_id)}/label/{_quote(name)}")

    # -- attachments ------------------------------------------------------------------------

    def list_attachments(self, page_id: str, *, filename: str = "", limit: int = 50, cursor: str = "") -> Chunk[Attachment]:
        query = _query(filename=filename, limit=limit, cursor=cursor)
        data = self._call("GET", f"{V2}/pages/{_quote(page_id)}/attachments?{query}")
        return Chunk([mapper.attachment_from(item) for item in mapper.results_of(data)], self._next_cursor(data))

    def get_attachment(self, attachment_id: str) -> Attachment:
        return mapper.attachment_from(self._call("GET", f"{V2}/attachments/{_quote(attachment_id)}"))

    def upload_attachment(self, page_id: str, filename: str, data: bytes, *, comment: str = "", minor: bool = False) -> Attachment:
        fields = {"minorEdit": "true" if minor else "false"}
        if comment:
            fields["comment"] = comment
        body, content_type = _multipart(fields, filename, data)
        path = f"{V1}/content/{_quote(page_id)}/child/attachment"
        response = self._transport.request(
            "PUT", path, body=body, content_type=content_type, headers={"X-Atlassian-Token": "nocheck"}
        )
        answer = self._finish(response, "PUT", path)
        results = mapper.results_of(answer)
        if not results and isinstance(answer, dict) and answer.get("id") and answer.get("type") == "attachment":
            results = [answer]  # an update may answer with the attachment itself
        if not results:
            raise UnavailableError(f"Confluence accepted {filename} but did not describe the attachment.", hint="Check it with `conflu attachments`.")
        return mapper.attachment_from_content(results[0])

    def download_attachment(self, attachment: Attachment) -> bytes:
        link = attachment.download_link
        if not link and attachment.page_id:
            link = f"{V1}/content/{_quote(attachment.page_id)}/child/attachment/{_quote(attachment.id)}/download"
        if not link:
            raise NotFoundError(f"Confluence gave no download address for {attachment.title}.")
        if link.startswith(self._settings.wiki_url):
            link = link[len(self._settings.wiki_url) :]
        path = link if link.startswith("/") else "/" + link
        response = self._transport.download(path)
        if response.status != 200:
            self._raise_for_status(response, self._decode(response), "GET", path.split("?")[0])
            raise UnavailableError(f"Confluence did not send {attachment.title} (HTTP {response.status}).")
        return response.body

    # -- search -----------------------------------------------------------------------------

    def search(self, cql: str, *, limit: int = 25, start: int = 0) -> SearchPage:
        data = self._call("GET", f"{V1}/search?{_query(cql=cql, limit=limit, start=start, expand=SEARCH_EXPAND)}")
        base = self._base(data)
        raw = mapper.results_of(data)
        hits = [mapper.search_hit_from(item, base) for item in raw]
        total = data.get("totalSize", data.get("size", len(hits))) if isinstance(data, dict) else len(hits)
        return SearchPage(hits, int(total), int(data.get("start", start)), int(data.get("limit", limit)), raw)

    # -- raw --------------------------------------------------------------------------------

    def request(self, method: str, path: str, body: Any = None) -> Any:
        return self._call(method, _request_target(path), body)
