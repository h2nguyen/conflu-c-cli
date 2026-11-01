"""The routes of the mock Confluence for the watches of the user on pages and spaces. `MockConfluence` asks them before its own routes (see mock_extensions.py).

The v1 calls `GET`, `POST` and `DELETE /rest/api/user/watch/content/{contentId}` and `.../space/{spaceKey}`. Nothing is watched at the start;
`watching` holds `("content", "2002")` and `("space", "ENG")` for what is. The two writes need the header `X-Atlassian-Token: no-check`, as the document says
(HTTP 403 without it). `read_back_fails` makes the status that is asked for right after a write answer HTTP 500, once: the case of a change that was made and
cannot be confirmed. An account id in the query is accepted, as the document allows; the CLI sends none, and a test looks at what it sent.
"""
from __future__ import annotations

from typing import Any

from .mock_base import RequestError, Routes


class WatchesRoutes(Routes):
    def __init__(self, mock: Any) -> None:
        super().__init__(mock)
        self.watching: set[tuple[str, str]] = set()
        self.read_back_fails = False
        self.written = 0  # the writes that were made
        self._unread = False  # a write was made and the status has not been asked for since

    def _exists(self, scope: str, target: str) -> bool:
        if scope == "space":
            return any(space["key"] == target for space in self.mock.spaces.values())
        return target in self.mock.pages or target in self.mock.content_kinds or target in self.mock.comments or target in self.mock.attachments

    def handle(self, handler: Any, method: str, path: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]], body: Any) -> bool:
        found = self.match(r"/rest/api/user/watch/(content|space)/([^/]+)", path)
        if not found or method not in ("GET", "POST", "DELETE"):
            return False
        scope, target = found.group(1), found.group(2)
        handler._require_known_query(query, {"accountId", "key", "username"}, old=True)
        if not self._exists(scope, target):
            raise RequestError(404, "Not found", f"No {scope} {target}", old=True, old_key="NOT_FOUND")
        if method == "GET":
            if self.read_back_fails and self._unread:
                self._unread = False
                raise RequestError(500, "Server error", "The watch status cannot be read", old=True, old_key="INTERNAL_ERROR")
            self._unread = False
            handler._reply_json(200, {"watching": (scope, target) in self.watching})
            return True
        if handler.headers.get("X-Atlassian-Token", "") != "no-check":
            raise RequestError(403, "Forbidden", "XSRF check failed", payload={"message": "XSRF check failed"})
        if method == "POST":
            self.watching.add((scope, target))
        else:
            self.watching.discard((scope, target))
        self.written += 1
        self._unread = True
        handler._reply_json(204, None)
        return True
