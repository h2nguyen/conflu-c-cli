"""The routes of the mock Confluence for the files attached to a page or a blog post: the blog post's attachments, the versions and the labels of
an attachment, and what the core leaves out for an attachment that a blog post holds. `MockConfluence` asks them before its own routes (see mock_extensions.py).

The attachments themselves are `mock.attachments` (the core's own: `{id, pageId, title, mediaType, comment, versions: [{number, createdAt, data}]}`); an
attachment of a blog post has `pageId` empty and `blogPostId` set, which the core's routes for pages never match. What an edition of a file says
besides its bytes (the message, whether it was a minor edit) is `notes`, by the id and the number of the version; the labels are `labels`. The
attachments that a test starts with are the ones of `attachment_data.py` (ids `att5101` and up belong to this area; `att5001` and `att5002` are the core's).

Answered here: `GET /blogposts/{id}/attachments`, `GET /attachments/{id}/versions`, `GET /attachments/{id}/labels`, and for an attachment of a blog post
also `GET /attachments/{id}` and `GET /rest/api/content/{id}/child/attachment/{attachmentId}/download` (a redirect to the media service, as for a page).
"""
from __future__ import annotations

from typing import Any, Sequence
from urllib.parse import quote

from .attachment_data import ACCOUNT, FIXTURES, Edition, Fixture
from .mock_base import RequestError, Routes
from .mock_blogposts import BlogpostsRoutes

_LIST_SORTS = {"id", "-id", "created-date", "-created-date", "modified-date", "-modified-date"}
_LABEL_PREFIXES = {"my", "team", "global", "system"}
_INCLUDES = ("include-labels", "include-properties", "include-operations", "include-versions", "include-version", "include-collaborators")


class AttachmentsRoutes(Routes):
    def __init__(self, mock: Any) -> None:
        super().__init__(mock)
        self.notes: dict[tuple[str, int], dict[str, Any]] = {}  # (attachment id, version number) -> message and minorEdit of that version
        self.labels: dict[str, list[str]] = {}  # attachment id -> the names of its labels
        if mock.populated:
            for fixture in FIXTURES:
                self._seed(fixture)

    # -- the data --------------------------------------------------------------------------------

    def _seed(self, fixture: Fixture) -> None:
        if fixture.container in self.mock.pages or self.mock.content_kinds.get(fixture.container) == "blogpost":
            self.add_attachment(
                fixture.container, fixture.name, fixture.editions, fixture.media_type, attachment_id=fixture.id, comment=fixture.comment, labels=fixture.labels
            )

    def add_attachment(
        self,
        holder_id: str,
        name: str,
        editions: Sequence[Edition],
        media_type: str = "application/octet-stream",
        *,
        attachment_id: str = "",
        comment: str = "",
        labels: Sequence[str] = (),
    ) -> str:
        """A file on a page or on a blog post, with one version for each edition (the first is version 1), for a test to set up."""
        on_page = holder_id in self.mock.pages
        if not on_page and self.mock.content_kinds.get(holder_id) != "blogpost":
            raise KeyError(holder_id)
        if not attachment_id:
            attachment_id = f"att{self.mock._next_attachment}"
            self.mock._next_attachment += 1
        self.mock.attachments[attachment_id] = {
            "id": attachment_id,
            "pageId": holder_id if on_page else "",
            "blogPostId": "" if on_page else holder_id,
            "title": name,
            "mediaType": media_type,
            "comment": comment,
            "versions": [{"number": number, "createdAt": edition.created or self.mock._tick(), "data": bytes(edition.data)} for number, edition in enumerate(editions, 1)],
        }
        for number, edition in enumerate(editions, 1):
            self.notes[(attachment_id, number)] = {"message": edition.message, "minorEdit": edition.minor}
        self.labels[attachment_id] = list(labels)
        return attachment_id

    def add_version(self, attachment_id: str, data: bytes, message: str = "", minor: bool = False) -> int:
        """A new version of an attachment, saved now."""
        versions = self.mock.attachments[attachment_id]["versions"]
        number = len(versions) + 1
        versions.append({"number": number, "createdAt": self.mock._tick(), "data": bytes(data)})
        self.notes[(attachment_id, number)] = {"message": message, "minorEdit": minor}
        return number

    # -- the answers -----------------------------------------------------------------------------

    def _find(self, attachment_id: str) -> dict[str, Any]:
        attachment = self.mock.attachments.get(attachment_id)
        if attachment is None:
            raise RequestError(404, "Not found", f"Attachment not found: {attachment_id}", code="NOT_FOUND")
        return attachment

    def _link(self, attachment: dict[str, Any], number: int) -> str:
        holder = attachment.get("blogPostId") or attachment["pageId"]
        return f"/download/attachments/{holder}/{quote(attachment['title'])}?version={number}&modificationDate=0&api=v2"

    def _version_row(self, attachment: dict[str, Any], version: dict[str, Any]) -> dict[str, Any]:
        note = self.notes.get((attachment["id"], version["number"]), {})
        return {
            "number": version["number"],
            "createdAt": version["createdAt"],
            "message": note.get("message", ""),
            "minorEdit": note.get("minorEdit", False),
            "authorId": ACCOUNT,
        }

    def _model(self, attachment: dict[str, Any], number: int | None = None) -> dict[str, Any]:
        """What the v2 API says of an attachment of a blog post (the core's `_attachment_model` says it of one of a page)."""
        version = attachment["versions"][-1] if number is None else next(item for item in attachment["versions"] if item["number"] == number)
        post = self.mock.area(BlogpostsRoutes).blogposts[attachment["blogPostId"]]
        webui = f"/spaces/{self.mock.spaces[post['spaceId']]['key']}/blog/{post['id']}"
        download = self._link(attachment, version["number"])
        return {
            "id": attachment["id"],
            "status": "current",
            "title": attachment["title"],
            "createdAt": attachment["versions"][0]["createdAt"],
            "blogPostId": attachment["blogPostId"],
            "mediaType": attachment["mediaType"],
            "mediaTypeDescription": attachment["mediaType"],
            "comment": attachment["comment"],
            "fileId": attachment["id"],
            "fileSize": len(version["data"]),
            "webuiLink": webui,
            "downloadLink": download,
            "version": self._version_row(attachment, version),
            "_links": {"webui": webui, "download": download},
        }

    def handle(self, handler: Any, method: str, path: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]], body: Any) -> bool:
        if method != "GET":
            return False
        match = self.match(r"/api/v2/blogposts/(\d+)/attachments", path)
        if match:
            self._of_blogpost(handler, match.group(1), query, query_pairs)
            return True
        match = self.match(r"/api/v2/attachments/(att\d+)/versions", path)
        if match:
            self._versions(handler, match.group(1), query, query_pairs)
            return True
        match = self.match(r"/api/v2/attachments/(\d+)/labels", path)  # the document types this one id as an integer: `att5001` is no route of it
        if match:
            self._labels(handler, f"att{match.group(1)}", query, query_pairs)
            return True
        match = self.match(r"/api/v2/attachments/(att\d+)", path)
        if match and self.mock.attachments.get(match.group(1), {}).get("blogPostId"):
            self._one(handler, match.group(1), query)
            return True
        match = self.match(r"/rest/api/content/(\d+)/child/attachment/(att\d+)/download", path)
        if match and self.mock.attachments.get(match.group(2), {}).get("blogPostId") == match.group(1):
            handler._require_known_query(query, {"version", "status"}, old=True)
            handler._send_attachment_redirect(self.mock.attachments[match.group(2)], handler._parse_int_query(handler._single(query, "version"), "version", old=True))
            return True
        return False

    def _of_blogpost(self, handler: Any, blogpost_id: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        handler._require_known_query(query, {"sort", "cursor", "status", "mediaType", "filename", "limit"})
        if self.mock.content_kinds.get(blogpost_id) != "blogpost":
            raise RequestError(404, "Not found", f"Blog post not found: {blogpost_id}", code="NOT_FOUND")
        sort = handler._single(query, "sort") or "id"
        if sort not in _LIST_SORTS:
            raise RequestError(400, "Invalid request parameter", f"Unsupported value for sort: {sort}")
        if "status" in query:
            handler._parse_csv_enum(handler._single(query, "status"), "status", {"current", "archived", "trashed"})
        offset, limit = handler._parse_cursor(query), handler._parse_limit(query, default=50)
        items = [item for item in self.mock.attachments.values() if item.get("blogPostId") == blogpost_id]
        if (media_type := handler._single(query, "mediaType")) is not None:
            items = [item for item in items if item["mediaType"] == media_type]
        if (filename := handler._single(query, "filename")) is not None:
            items = [item for item in items if item["title"] == filename]
        key = sort.lstrip("-")
        if key == "id":
            items.sort(key=lambda item: int(item["id"].removeprefix("att")), reverse=sort.startswith("-"))
        elif key == "created-date":
            items.sort(key=lambda item: item["versions"][0]["createdAt"], reverse=sort.startswith("-"))
        else:
            items.sort(key=lambda item: item["versions"][-1]["createdAt"], reverse=sort.startswith("-"))
        models = [self._model(item) for item in items]
        shown, links, headers = handler._apply_pagination(models, path=f"/api/v2/blogposts/{blogpost_id}/attachments", query_pairs=query_pairs, offset=offset, limit=limit)
        handler._reply_json(200, {"results": shown, "_links": links}, headers)

    def _one(self, handler: Any, attachment_id: str, query: dict[str, list[str]]) -> None:
        handler._require_known_query(query, {"version", *_INCLUDES})
        for name in _INCLUDES:
            handler._parse_bool(handler._single(query, name), name)
        attachment = self._find(attachment_id)
        number = handler._parse_int_query(handler._single(query, "version"), "version")
        if number is not None and number not in {item["number"] for item in attachment["versions"]}:
            raise RequestError(404, "Not found", f"Attachment version not found: {number}", code="NOT_FOUND")
        handler._reply_json(200, self._model(attachment, number))

    def _versions(self, handler: Any, attachment_id: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        handler._require_known_query(query, {"cursor", "limit", "sort"})
        attachment = self._find(attachment_id)
        sort = handler._single(query, "sort") or "modified-date"
        if sort not in {"modified-date", "-modified-date"}:
            raise RequestError(400, "Invalid request parameter", f"Unsupported value for sort: {sort}")
        rows = [
            {**self._version_row(attachment, version), "attachment": {"title": attachment["title"], "id": attachment["id"]}}
            for version in sorted(attachment["versions"], key=lambda item: item["number"], reverse=sort.startswith("-"))
        ]
        offset, limit = handler._parse_cursor(query), handler._parse_limit(query, default=25)
        shown, links, headers = handler._apply_pagination(rows, path=f"/api/v2/attachments/{attachment_id}/versions", query_pairs=query_pairs, offset=offset, limit=limit)
        handler._reply_json(200, {"results": shown, "_links": links}, headers)

    def _labels(self, handler: Any, attachment_id: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        handler._require_known_query(query, {"prefix", "sort", "cursor", "limit"})
        self._find(attachment_id)
        prefix = handler._single(query, "prefix")
        if prefix is not None and prefix not in _LABEL_PREFIXES:
            raise RequestError(400, "Invalid request parameter", f"Unsupported value for prefix: {prefix}")
        names = self.labels.get(attachment_id, []) if prefix in (None, "global") else []  # every label here is a global one
        rows = [{"id": str(8000 + index), "name": name, "prefix": "global"} for index, name in enumerate(names, 1)]
        offset, limit = handler._parse_cursor(query), handler._parse_limit(query, default=50)
        shown, links, headers = handler._apply_pagination(rows, path=f"/api/v2/attachments/{attachment_id.removeprefix('att')}/labels", query_pairs=query_pairs, offset=offset, limit=limit)
        handler._reply_json(200, {"results": shown, "_links": links}, headers)
