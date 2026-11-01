"""The routes of the mock Confluence for looking up people. `MockConfluence` asks them before its own routes (see mock_extensions.py).

`GET /rest/api/search/user` answers a CQL of the form `user.fullname ~ "text"` with the people of `mock.users` whose display name holds the text, case
aside; any other query is HTTP 400 ("Could not parse cql"), as is a quote or a backslash that is not escaped. `POST /api/v2/users-bulk` is the mock's own
(mock_confluence.py). A person is `{"accountId", "displayName", "publicName", "email"}` and, for an account that is not an atlassian one, `"accountType"`.
"""
from __future__ import annotations

import re
from typing import Any

from .mock_base import RequestError, Routes

_FULLNAME = re.compile(r'user\.fullname\s*~\s*"((?:\\.|[^"\\])*)"')  # a quote and a backslash inside are escaped with a backslash


class UsersRoutes(Routes):
    def handle(self, handler: Any, method: str, path: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]], body: Any) -> bool:
        if method != "GET" or path != "/rest/api/search/user":
            return False
        handler._require_known_query(query, {"cql", "start", "limit", "expand", "sitePermissionTypeFilter"}, old=True)
        cql = handler._single(query, "cql")
        if cql is None:
            raise RequestError(400, "Bad Request", "Could not parse cql: missing cql", old=True, old_key="BAD_REQUEST")
        match = _FULLNAME.fullmatch(cql.strip())
        if match is None:
            raise RequestError(400, "Bad Request", f"Could not parse cql: {cql}", old=True, old_key="BAD_REQUEST")
        wanted = re.sub(r"\\(.)", r"\1", match.group(1)).casefold()
        limit = handler._parse_search_limit(query)
        start = handler._parse_start(query)
        found = [user for user in self.mock.users.values() if wanted in user["displayName"].casefold()]
        shown = found[start : start + min(limit, self.mock.page_cap)]
        results = [self._result(user) for user in shown]
        handler._reply_json(
            200,
            {
                "results": results,
                "start": start,
                "limit": limit,
                "size": len(results),
                "totalSize": len(found),
                "cqlQuery": cql,
                "searchDuration": 1,
                "_links": {"base": self.mock.base_url, "context": self.mock.context_path or "/"},
            },
        )
        return True

    @staticmethod
    def _result(user: dict[str, Any]) -> dict[str, Any]:
        """One result of a search for people: the person is its `user`; the rest is what a result of any search carries."""
        return {
            "user": {
                "type": "known",
                "accountId": user["accountId"],
                "accountType": user.get("accountType", "atlassian"),
                "email": user["email"],
                "publicName": user["publicName"],
                "displayName": user["displayName"],
                "profilePicture": {"path": "/avatar/default.png", "width": 48, "height": 48, "isDefault": True},
                "isGuest": False,
            },
            "title": user["displayName"],
            "excerpt": "",
            "url": f"/people/{user['accountId']}",
            "entityType": "user",
            "iconCssClass": "aui-icon content-type-profile",
            "lastModified": "2026-10-01T08:00:00.000Z",
            "breadcrumbs": [],
        }
