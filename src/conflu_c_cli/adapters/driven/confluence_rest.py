"""The Confluence port implemented over Confluence Cloud's REST APIs.

API v2 (`/api/v2`) is the default: pages, spaces, comments, versions, attachment reads and most of the rest. The older API v1
(`/rest/api`) is used only where v2 has no equivalent, and every such call is named in `V1_CALLS` with its reason: search with CQL, the
current user, adding and removing labels, uploading and downloading the file of an attachment, and moving a page before or after another.
The feature areas are mixins (`rest_*.py`) of `RestConfluenceGateway`; what they share is in `rest_support.py`.
"""
from __future__ import annotations

import base64
import json
import re
import urllib.parse
from dataclasses import replace
from typing import Any, Sequence

from ...application.paging import fetch_all
from ...application.ports import ConfluenceGateway
from ...application.settings import Settings, is_local_host
from ...domain.errors import (
    AuthError,
    ConfigError,
    ConfluCliError,
    ConflictError,
    NotFoundError,
    RejectedError,
    UnavailableError,
)
from ...domain.errortext import redact_error_text, redact_error_value
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
from ...domain.structure import shown_key
from . import confluence_mapper as mapper
from .http_transport import HttpResponse, HttpTransport
from .rest_access import RestAccess
from .rest_attachments import RestAttachments, name_of
from .rest_blogposts import RestBlogposts
from .rest_comments import RestComments
from .rest_history import RestHistory
from .rest_labels import RestLabels
from .rest_properties import RestProperties
from .rest_setup import RestSetup
from .rest_structure import RestStructure
from .rest_support import V1, V2
from .rest_support import messages as _messages
from .rest_support import multipart as _multipart
from .rest_support import next_cursor
from .rest_support import query as _query
from .rest_support import quote as _quote
from .rest_support import request_target as _request_target
from .rest_support import without_secrets as _without_secrets
from .rest_tasks import RestTasks
from .rest_templates import RestTemplates
from .rest_users import RestUsers
from .rest_watches import RestWatches

BULK_USERS = 250
BULK_PAGES = 250  # what `id` and `limit` of the list of pages take at most
SEARCH_EXPAND = "content.ancestors,content.metadata.labels,content.version"  # where a hit lives, how it is tagged, its version

# The calls of this module that use the v1 API, each with why: v2 is the API to use, and v1 only where v2 has nothing for it. The
# keys are the calls as `tests/support/confluence_cloud_v1_endpoints.txt` writes them; a test sweeps every command, holds this table
# against the calls that were really made and against the v1 document, and `docs/reference/compatibility.md` repeats it.
V1_CALLS: dict[str, str] = {
    "GET /rest/api/user/current": "v2 has no call for the user who owns the token.",
    "GET /rest/api/search": "v2 has no CQL search.",
    "POST /rest/api/content/{id}/label": "v2 reads the labels of content and has no call that adds one.",
    "DELETE /rest/api/content/{id}/label/{label}": "v2 reads the labels of content and has no call that removes one.",
    "PUT /rest/api/content/{id}/child/attachment": "v2 reads attachments and has no upload.",
    "GET /rest/api/content/{id}/child/attachment/{attachmentId}/download": "v2 describes an attachment but has no call that serves its file.",
    "PUT /rest/api/content/{pageId}/move/{position}/{targetId}": "v2 can only put a page below another parent, by saving a new version of it: before and after another page need this call.",
}


def _whole(value: Any, what: str) -> int:
    """A count or a position that an answer holds. What is not a whole number (`"many"`, `null`, `1e999`) is a damaged answer, not a mistake of the person."""
    try:
        number = int(value)
        if not -(2**63) <= number < 2**63:
            raise OverflowError("not a number of the API")
        return number
    except (ValueError, TypeError, OverflowError):
        raise UnavailableError(
            f"Confluence answered with {what} that is not a number.",
            hint="Try again. If it stays, something between you and Confluence is changing its answers.",
        ) from None


_MEDIA_TYPE = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]{0,60}/[a-z0-9][a-z0-9!#$&^_.+-]{0,60}")
_IN_THE_WAY = "A proxy, a captive portal or a login page between you and Confluence may have answered in its place: check the VPN and CONFLUENCE_BASE_URL (`conflu doctor` checks the connection), then try again."
_IN_THE_WAY_OF_A_WRITE = (
    "A proxy, a captive portal or a login page between you and Confluence may have answered in its place, and the change may have been made all the same: "
    "look at the result (`conflu page ID`, `conflu comments PAGE`, `conflu attachments PAGE`, `conflu properties ID`) before you repeat it, and check the VPN and "
    "CONFLUENCE_BASE_URL (`conflu doctor` checks the connection)."
)


def _media_type(response: HttpResponse) -> str:
    """The media type that an answer says it has (`text/html`), when what it says looks like one: it is the server's text, and a message shows it."""
    found = response.headers.get("content-type", "").partition(";")[0].strip().lower()
    return found if _MEDIA_TYPE.fullmatch(found) else ""


def _kind_of(value: Any) -> str:
    """What a JSON value is, in words, for the message about an answer of the wrong kind."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true or false"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, str):
        return "a text"
    return "a list" if isinstance(value, list) else "something else"


_NOTHING = object()  # "no value was read", where `None` is the JSON `null`
MAX_RESULTS = 1000  # the most that a list answer holds: the documents allow 250 (v2) and 100 (v1) to a request, so more is not an answer of Confluence
MAX_OBJECTS = 250_000  # the JSON objects in all of one answer: a page, its labels and versions, 250 of them, make a few thousand


class _TooManyObjects(Exception):
    """Raised while an answer is decoded, as soon as it holds more objects (or arrays) than `MAX_OBJECTS` allows: the memory that a list of objects takes
    is not bounded by the size of the text (400,000 empty objects are 1.2 MB, and cost half a gigabyte once they are mapped)."""


class _ObjectCount:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self, item: dict[str, Any]) -> dict[str, Any]:
        self.count += 1
        if self.count > MAX_OBJECTS:
            raise _TooManyObjects()
        return item


def _unreadable(response: HttpResponse, details: dict[str, Any], error: ValueError | None = None, *, found: Any = _NOTHING) -> UnavailableError:
    """The error for a success that holds nothing that can be read. `{}` in its place would be an empty result, and a list that looks empty, a page
    that is blank or a connection that is `OK` is what a damaged answer must never be taken for. No text of the answer is in the message. `found` is
    the JSON that was read when it is of another kind than the call needs (an object): a list, `null`, a number."""
    status = response.status
    # What a proxy answered to a write may have been done by Confluence all the same: the hint of a read says "try again", that of a write says to look first.
    in_the_way = _IN_THE_WAY if str(details.get("request", "GET")).startswith("GET") else _IN_THE_WAY_OF_A_WRITE
    if error is None and found is not _NOTHING:
        return UnavailableError(f"Confluence answered HTTP {status} with {_kind_of(found)}, where a JSON object was expected.", hint=in_the_way, details=details)
    if error is None:
        return UnavailableError(f"Confluence answered HTTP {status} with an empty body, where an answer with data was expected.", hint=in_the_way, details=details)
    if isinstance(error, (json.JSONDecodeError, UnicodeDecodeError)):
        media = _media_type(response)
        named = f" ({media})" if media else ""
        return UnavailableError(f"Confluence answered HTTP {status} with something that is not JSON{named}.", hint=in_the_way, details=details)
    return UnavailableError(  # what else the decoder refuses is a number of more than 4,300 digits, which it will not turn into an integer
        f"Confluence answered HTTP {status} with a number that is too long to be read (more than 4,300 digits).",
        hint="A value that somebody stored (a content property, for example) is the usual cause: it cannot be shown by this program.",
        details=details,
    )


class RestConfluenceGateway(
    RestStructure,
    RestBlogposts,
    RestHistory,
    RestComments,
    RestLabels,
    RestAttachments,
    RestAccess,
    RestWatches,
    RestUsers,
    RestTasks,
    RestProperties,
    RestTemplates,
    RestSetup,
    ConfluenceGateway,
):
    def __init__(self, settings: Settings, transport: HttpTransport) -> None:
        self._settings = settings
        self._transport = transport

    # -- plumbing ---------------------------------------------------------------------------

    def _call(self, method: str, path: str, body: Any = None, *, timeout: float | None = None, retries: int | None = None, expect: str = "object") -> Any:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        response = self._transport.request(method, path, body=payload, timeout=timeout, retries=retries)
        return self._finish(response, method, path, expect)

    def _finish(self, response: HttpResponse, method: str, path: str, expect: str = "object") -> Any:
        decoded = self._decode(response, method, path.split("?")[0], expect)
        self._raise_for_status(response, decoded, method, path)
        return decoded

    @staticmethod
    def _decode(response: HttpResponse, method: str = "", shown: str = "", expect: str = "any") -> Any:
        """The JSON of an answer, of the kind that the call needs: `expect` is "object" (what every call needs that reads something or makes it: a list is
        an object with `results`), "nothing" (a call whose success has no body to read: a label that is removed, a watch, a move; what comes is ignored, but it
        must be JSON if there is any) or "any" (the raw API, which prints what the endpoint answers). A success that is not of that kind is an
        `UnavailableError`, never `{}`: what is no JSON (a login page that a proxy answers with HTTP 200), JSON of another kind (`[]`, `null`), a number of
        more than 4,300 digits (a content property can hold one), an empty body where there should be data. An empty answer would be a list that looks
        empty, a page that is blank, a connection that is `OK`, a property that was "created". A refusal is the other way round: its status says what it was,
        so a body of it that is no JSON is only an explanation that is not there."""
        status = response.status
        success = 200 <= status < 300
        details = {"status": status, "request": f"{method} {shown}"} if method else {"status": status}
        if not response.body.strip():
            if success and (expect == "object" or (expect == "any" and method == "GET" and status == 200)):
                raise _unreadable(response, details)
            return {}
        try:
            text = response.body.decode("utf-8")
            if text.count("[") > 8 * MAX_OBJECTS:  # arrays have no hook: a text made of `[]` is 2 bytes for 56 bytes of memory (an object counts as one of 8 here)
                raise _TooManyObjects()
            value = json.loads(text, object_hook=_ObjectCount())
        except RecursionError:  # what somebody stored in a property can nest arrays far deeper than the decoder reads
            raise UnavailableError(
                "Confluence answered with JSON that nests arrays or objects too deeply to be read.",
                hint="A value that somebody stored (a content property, for example) is the usual cause: it cannot be shown by this program.",
                details={"status": response.status},
            ) from None
        except _TooManyObjects:
            raise UnavailableError(
                f"Confluence answered with more than {MAX_OBJECTS:,} JSON objects in one answer, which is not read.",
                hint="Try again. If it stays, something between you and Confluence is changing its answers.",
                details=details,
            ) from None
        except ValueError as error:
            if success:
                raise _unreadable(response, details, error) from None
            return {"_text": response.body.decode("utf-8", "replace")[:500]}
        results = value.get("results") if isinstance(value, dict) else None
        if isinstance(results, list) and len(results) > MAX_RESULTS:
            raise UnavailableError(
                f"Confluence answered with {len(results):,} results in one answer, where a request returns {MAX_RESULTS:,} at most.",
                hint="Try again. If it stays, something between you and Confluence is changing its answers.",
                details=details,
            )
        if success and expect == "object" and not isinstance(value, dict):
            raise _unreadable(response, details, found=value)
        return value

    def _scrub(self, value: Any) -> Any:
        """Confluence's explanation of a refusal ends up in our error output. Take the credentials out in case something
        in between echoed them, and under the privacy policy the people."""
        if self._settings.hide_users:
            value = strip_users(value)
        credentials = f"{self._settings.email}:{self._settings.api_token}".encode("utf-8")
        return _without_secrets(value, [self._settings.api_token, base64.b64encode(credentials).decode("ascii"), self._settings.email])

    def _explanation(self, body: Any, status: int, method: str, shown: str) -> tuple[Any, str]:
        """What Confluence said about a refusal, as it may be printed: the answer without credentials (and, under the policy that never prints people,
        without the keys that name them) and the explanation that goes into the message of the error, without e-mail addresses, links to people and
        account ids, which a sentence of the server may hold whatever the policy. An answer nested deeper than the scrubbing reads is a damaged answer."""
        try:
            body = self._scrub(body)
            return body, redact_error_text(_messages(body))
        except RecursionError:
            raise UnavailableError(
                f"Confluence answered with HTTP {status} and a body that nests arrays or objects too deeply to be read.",
                hint="Try again. If it stays, something between you and Confluence is changing its answers.",
                details={"status": status, "request": f"{method} {shown}"},
            ) from None

    def _answer_details(self, body: Any) -> dict[str, Any]:
        """The answer of a refusal for the `details` of its error, for the one error that carries it. Not under the policy that never prints people: a
        whole answer cannot be searched for every way that a person is written in it. Otherwise it is kept without the people that it names (a user object,
        a person id: a name is not a pattern that a text redaction finds) and with its text redacted as the message is: nobody asked for the people in it."""
        if self._settings.hide_users:
            return {}
        try:
            return {"confluence": redact_error_value(strip_users(body))}
        except RecursionError:  # too deep to copy: the message of the error stands without it
            return {}

    def _custom_domain_hint(self) -> str:
        """API tokens are accepted on `SITE.atlassian.net` and on the gateway at api.atlassian.com, not on a company's own
        domain for the site: there the credentials are not read and Confluence answers as it does an anonymous caller."""
        host = (urllib.parse.urlsplit(self._settings.base_url).hostname or "").lower()
        if not host or host.endswith(".atlassian.net") or host == "api.atlassian.com" or is_local_host(host):
            return ""
        return (
            f"{host} is not an atlassian.net address. If it is a custom domain of your Confluence Cloud site, API tokens are not accepted on it: "
            "run `conflu setup --discover`, which reads the public tenant information of the site (https://" + host + "/_edge/tenant_info) and proposes "
            "the gateway address, or set it yourself with "
            "`conflu config set CONFLUENCE_BASE_URL https://api.atlassian.com/ex/confluence/CLOUD_ID`. "
        )

    def _raise_for_status(self, response: HttpResponse, body: Any, method: str, path: str) -> None:
        status = response.status
        if 200 <= status < 300:
            return
        shown = path.split("?")[0]
        body, reason = self._explanation(body, status, method, shown)
        details = {"status": status, "request": f"{method} {shown}"}
        if 300 <= status < 400:
            try:
                target = urllib.parse.urlsplit(response.headers.get("location", ""))
            except ValueError:  # `Location: http://[`: an address that no parser takes is a damaged answer, not a mistake in CONFLUENCE_BASE_URL
                raise UnavailableError(
                    f"Confluence answered with a redirect (HTTP {status}) to an address that cannot be read.",
                    hint="Try again. If it stays, something between you and Confluence (a proxy, a captive portal) is changing its answers.",
                    details=details,
                ) from None
            where = redact_error_text(f" to {target.netloc}{target.path}") if target.netloc or target.path else ""
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
        raise RejectedError(
            f"Confluence refused the request (HTTP {status}): {reason or 'no explanation'}",
            details={**details, **self._answer_details(body)},
        )

    @staticmethod
    def _next_cursor(data: Any) -> str:
        return next_cursor(data)

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
        raise NotFoundError(f"No space with the key {shown_key(key)}.", hint="`conflu spaces` lists the spaces you can see.", details={"space": shown_key(key)})

    def get_space_by_id(self, space_id: str) -> Space:
        data = self._call("GET", f"{V2}/spaces/{_quote(space_id)}?{_query(description_format='plain')}")
        return mapper.space_from(data, self._base(data))

    # -- pages ------------------------------------------------------------------------------

    def get_page(self, page_id: str, *, with_body: bool = True) -> Page:
        query = _query(include_labels=True, body_format="storage" if with_body else "")
        data = self._call("GET", f"{V2}/pages/{_quote(page_id)}?{query}")
        page = mapper.page_from(data, self._settings.wiki_url)
        if mapper.labels_cut(data):  # the answer holds the first 50 labels only: the call that lists the labels reads them all
            try:
                page = replace(page, labels=self.list_labels(page_id))
            except ConfluCliError:
                # The page itself was read. The rest of its labels is a second call that can be refused or fail on its own: the page keeps the
                # 50 labels it has and says so (`labels_incomplete`), as 1.0.0 showed the page (it asked for no more), instead of failing as a whole.
                page = replace(page, labels_incomplete=True)
        return page

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
        ancestors = self._ancestors("page", page_id)
        titles: dict[str, str] = {}
        for start in range(0, len(ancestors), BULK_PAGES):  # `id` of the list of pages takes at most 250
            wanted = [str(item["id"]) for item in ancestors[start : start + BULK_PAGES]]
            for item in mapper.results_of(self._call("GET", f"{V2}/pages?{_query(id=wanted, limit=BULK_PAGES)}")):
                titles[str(item.get("id"))] = str(item.get("title") or "")
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
        self._call("PUT", f"{V1}/content/{_quote(page_id)}/move/{_quote(position)}/{_quote(target_id)}", expect="nothing")  # what comes back is not read

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
        self._call("DELETE", f"{V1}/content/{_quote(page_id)}/label/{_quote(name)}", expect="nothing")  # HTTP 204: there is no body

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
        # The file is asked for with the documented v1 call, built from the ids. The `downloadLink` of an answer is a web address, not
        # a call of either document, and an address that came out of an answer is not what the credentials should be sent to: it
        # is the last resort, for an attachment whose page is not known.
        link = ""
        if attachment.page_id:
            link = f"{V1}/content/{_quote(attachment.page_id)}/child/attachment/{_quote(attachment.id)}/download"
        elif attachment.download_link:
            link = attachment.download_link
        if not link:
            raise NotFoundError(f"Confluence gave no download address for {name_of(attachment)}.")
        if link.startswith(self._settings.wiki_url):
            link = link[len(self._settings.wiki_url) :]
        path = link if link.startswith("/") else "/" + link
        response = self._transport.download(path)
        if response.status != 200:  # a file is no JSON: only a refusal is decoded, to say what Confluence said
            if response.status >= 300:
                self._raise_for_status(response, self._decode(response), "GET", path.split("?")[0])
            raise UnavailableError(f"Confluence did not send {name_of(attachment)} (HTTP {response.status}).")
        return response.body

    # -- search -----------------------------------------------------------------------------

    def search(self, cql: str, *, limit: int = 25, start: int = 0) -> SearchPage:
        data = self._call("GET", f"{V1}/search?{_query(cql=cql, limit=limit, start=start, expand=SEARCH_EXPAND)}")
        base = self._base(data)
        raw = mapper.results_of(data)
        hits = [mapper.search_hit_from(item, base) for item in raw]
        total = data.get("totalSize", data.get("size", len(hits)))
        return SearchPage(hits, _whole(total, "a total"), _whole(data.get("start", start), "a start"), _whole(data.get("limit", limit), "a limit"), raw)

    # -- raw --------------------------------------------------------------------------------

    def request(self, method: str, path: str, body: Any = None) -> Any:
        return self._call(method, _request_target(path), body, expect="any")  # the raw API prints what the endpoint answers: any JSON
