"""The routes of the mock Confluence for earlier versions of a page, the difference between two of them, and restoring one. `MockConfluence` asks them before its own routes (see mock_extensions.py).

An earlier version is read by the core (`GET /pages/{id}?version=N`, `GET /pages?id=...`); what is here is the one call that v2 does not have: restoring a version
(`POST /rest/api/content/{id}/version`, the older API), which saves a new version with the body of the old one. Every version keeps its body in
`mock.pages[id]["versions"]`; a version may also carry the title it had (`title`), which the core shows when that version is read.

The page 2002 has three versions in the core, which all say the same: here its versions 1 and 2 get a body of their own (and version 1 a title), the same
as `FakeHistory` has them, so that a difference between versions can be read.
"""
from __future__ import annotations

from typing import Any

from .fakes_history import FIRST_BODY, SECOND_BODY
from .mock_base import RequestError, Routes


class HistoryRoutes(Routes):
    def __init__(self, mock: Any) -> None:
        super().__init__(mock)
        if mock.populated:
            versions = mock.pages["2002"]["versions"]
            versions[0].update({"body": FIRST_BODY, "title": "Release notes (draft)"})
            versions[1]["body"] = SECOND_BODY

    def handle(self, handler: Any, method: str, path: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]], body: Any) -> bool:
        match = self.match(r"/rest/api/content/(\d+)/version", path)
        if match and method == "POST":
            self._restore(handler, match.group(1), query, body)
            return True
        return False

    def _restore(self, handler: Any, page_id: str, query: dict[str, list[str]], body: Any) -> None:
        handler._require_known_query(query, {"expand"}, old=True)
        page = self.mock.pages.get(page_id)
        if page is None:
            raise RequestError(404, "Not found", f"Content not found: {page_id}", old=True, old_key="NOT_FOUND")
        if not isinstance(body, dict) or body.get("operationKey") != "restore" or not isinstance(body.get("params"), dict):
            raise RequestError(400, "Bad Request", "operationKey must be restore and params must be an object", old=True, old_key="BAD_REQUEST")
        params = body["params"]
        number = params.get("versionNumber")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise RequestError(400, "Bad Request", "params.versionNumber must be a version number", old=True, old_key="BAD_REQUEST")
        if not isinstance(params.get("message"), str):
            raise RequestError(400, "Bad Request", "params.message is required", old=True, old_key="BAD_REQUEST")
        if "restoreTitle" in params and not isinstance(params["restoreTitle"], bool):
            raise RequestError(400, "Bad Request", "params.restoreTitle must be true or false", old=True, old_key="BAD_REQUEST")
        if page["status"] != "current":
            raise RequestError(400, "Bad Request", f"Only current content can be restored, this one is {page['status']}", old=True, old_key="BAD_REQUEST")
        old = next((item for item in page["versions"] if item["number"] == number), None)
        if old is None:
            raise RequestError(404, "Not found", f"Version not found: {number}", old=True, old_key="NOT_FOUND")
        current = page["versions"][-1]
        current.setdefault("title", page["title"])  # the version that the restore covers keeps the title it had
        title = old.get("title", page["title"]) if params.get("restoreTitle") else page["title"]
        if title != page["title"] and any(
            other["id"] != page_id and other["spaceId"] == page["spaceId"] and other["status"] == "current" and other["title"] == title for other in self.mock.pages.values()
        ):
            raise RequestError(400, "Bad Request", "A page already exists with the same TITLE in this space", old=True, old_key="BAD_REQUEST")
        page["title"] = title
        created = self.mock._tick()
        page["versions"].append(
            {"number": current["number"] + 1, "createdAt": created, "message": params["message"], "minorEdit": False, "authorId": next(iter(self.mock.users)), "body": old["body"], "title": title}
        )
        author = self.mock.users[next(iter(self.mock.users))]
        handler._reply_json(
            200,
            {
                "by": {"type": "known", "accountId": author["accountId"], "accountType": "atlassian", "publicName": author["publicName"], "displayName": author["displayName"]},
                "when": created,
                "message": params["message"],
                "number": current["number"] + 1,
                "minorEdit": False,
                "content": {"id": page_id, "type": "page", "status": "current", "title": title},
                "contentTypeModified": False,
            },
        )
