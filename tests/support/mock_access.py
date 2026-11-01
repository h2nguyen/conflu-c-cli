"""The routes of the mock Confluence for what the user may do, restrictions on content, and the permissions and roles of a space. `MockConfluence` asks them before its own routes (see mock_extensions.py).

What it holds (the data is in data_access.py, which the fake uses as well; `mock.area(AccessRoutes)` gives these routes to a test):

    `role_mode`, ROLES_TRANSITION from the start so that both models are read; None answers 404 to the mode, the role assignments and the roles, as a site without
    space roles does
    `restrictions[id]`: the state and the direct permissions of content (2002, 2003, 7501); all other content is OPEN with none
    `operations[id]`: what may be done with something, as `[(operation, target type), ...]`; the default is that of its kind
    `space_permissions[space id]`, `role_assignments[space id]` and `roles`: the two models of a space (ENG, 1001)
    content of the kinds that no other fixture has, registered in `mock.content_kinds`: 7501 folder, 7511 blog post, 7521 whiteboard, 7531 database,
    7541 smart link, 7551 custom content

Every answer is that of the REST API v2 document; a query parameter that the CLI has no reason to send is refused with HTTP 400, so that a test sees it.
"""
from __future__ import annotations

import re
from typing import Any

from . import data_access as data
from .mock_base import RequestError, Routes

CONTENT = {"pages": "page", "blogposts": "blogpost", "folders": "folder", "whiteboards": "whiteboard", "databases": "database", "embeds": "embed", "custom-content": "custom"}
COMMENTS = {"footer-comments": "footer", "inline-comments": "inline"}
RESTRICTABLE = ("pages", "blogposts", "folders", "whiteboards", "databases")
KIND_OF = {**CONTENT, "footer-comments": "footer-comment", "inline-comments": "inline-comment", "attachments": "attachment", "spaces": "space"}
_COLLECTIONS = "|".join(re.escape(name) for name in (*CONTENT, *COMMENTS, "attachments"))
_RESTRICTABLE = "|".join(RESTRICTABLE)


def _not_found(what: str) -> RequestError:
    return RequestError(404, "Not found", f"{what} does not exist, or this account may not see it", code="NOT_FOUND")


class AccessRoutes(Routes):
    def __init__(self, mock: Any) -> None:
        super().__init__(mock)
        self.role_mode: str | None = data.ROLE_MODE
        self.operations: dict[str, list[tuple[str, str]]] = {}  # what a test lists for one id
        self.restrictions: dict[str, dict[str, Any]] = {}
        self.space_permissions: dict[str, list[dict[str, Any]]] = {}
        self.role_assignments: dict[str, list[dict[str, Any]]] = {}
        self.roles: list[dict[str, Any]] = [
            {"id": role, "type": kind, "name": name, "description": f"The {name} role", "spacePermissions": ["read:space"]} for role, name, kind in data.SPACE_ROLES
        ]
        for content_id, kind in data.KINDS.items():
            mock.content_kinds[content_id] = kind
        for content_id, (state, created, by, grants) in data.RESTRICTIONS.items():
            entries = [{"operation": operation, "principal": {"principalType": kind, "principalId": who}, "createdAt": created, "createdBy": by} for operation, kind, who in grants]
            self.restrictions[content_id] = {"state": state, "createdAt": created, "createdBy": by, "permissions": entries}
        for space_id, rows in data.SPACE_PERMISSIONS.items():
            self.space_permissions[space_id] = [
                {"id": ident, "principal": {"type": kind, "id": who}, "operation": {"key": operation, "targetType": target}} for ident, kind, who, operation, target in rows
            ]
        for space_id, rows in data.ROLE_ASSIGNMENTS.items():
            self.role_assignments[space_id] = [{"principal": {"principalType": kind, "principalId": who}, "roleId": role} for kind, who, role in rows]

    # -- what exists --------------------------------------------------------------------------

    def _exists(self, collection: str, item: str) -> bool:
        if collection == "pages":
            return item in self.mock.pages
        if collection == "spaces":
            return item in self.mock.spaces
        if collection == "attachments":
            return item in self.mock.attachments
        if collection in COMMENTS:
            comment = self.mock.comments.get(item)
            return comment is not None and comment["kind"] == COMMENTS[collection]
        return self.mock.content_kinds.get(item) == CONTENT[collection]

    def _must_exist(self, collection: str, item: str, what: str) -> None:
        if not self._exists(collection, item):
            raise _not_found(f"The {what} {item}")

    # -- the routes ---------------------------------------------------------------------------

    def handle(self, handler: Any, method: str, path: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]], body: Any) -> bool:
        if method != "GET":
            return False
        found = self.match(rf"/api/v2/({_COLLECTIONS}|spaces)/([^/]+)/operations", path)
        if found:
            self._operations(handler, found.group(1), found.group(2), query)
            return True
        found = self.match(rf"/api/v2/({_RESTRICTABLE})/([^/]+)/restriction-state", path)
        if found:
            self._restriction_state(handler, found.group(1), found.group(2), query)
            return True
        found = self.match(rf"/api/v2/({_RESTRICTABLE})/([^/]+)/permissions", path)
        if found:
            self._content_permissions(handler, found.group(1), found.group(2), path, query, query_pairs)
            return True
        found = self.match(r"/api/v2/spaces/([^/]+)/(permissions|role-assignments)", path)
        if found:
            self._space_list(handler, found.group(1), found.group(2), path, query, query_pairs)
            return True
        if path == "/api/v2/space-role-mode":
            self._role_mode(handler, query)
            return True
        if path == "/api/v2/space-roles":
            self._space_roles(handler, path, query, query_pairs)
            return True
        return False

    def _operations(self, handler: Any, collection: str, item: str, query: dict[str, list[str]]) -> None:
        handler._require_known_query(query, set())
        self._must_exist(collection, item, KIND_OF[collection])
        listed = self.operations.get(item) or data.OPERATIONS_BY_ID.get(item) or data.OPERATIONS[KIND_OF[collection]]
        handler._reply_json(200, {"operations": [{"operation": operation, "targetType": target} for operation, target in listed]})

    def _restriction_state(self, handler: Any, collection: str, item: str, query: dict[str, list[str]]) -> None:
        handler._require_known_query(query, set())
        self._must_exist(collection, item, KIND_OF[collection])
        held = self.restrictions.get(item)
        if held is None:
            handler._reply_json(200, {"state": "OPEN"})
            return
        handler._reply_json(200, {key: held[key] for key in ("state", "createdAt", "createdBy")})

    def _paged(self, handler: Any, items: list[Any], path: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        limit = handler._parse_limit(query, default=25)
        offset = handler._parse_cursor(query)
        shown, links, headers = handler._apply_pagination(items, path=path, query_pairs=query_pairs, offset=offset, limit=limit)
        handler._reply_json(200, {"results": shown, "_links": links}, headers)

    def _content_permissions(self, handler: Any, collection: str, item: str, path: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        handler._require_known_query(query, {"limit", "cursor"})
        self._must_exist(collection, item, KIND_OF[collection])
        self._paged(handler, list(self.restrictions.get(item, {}).get("permissions", [])), path, query, query_pairs)

    def _space_list(self, handler: Any, space_id: str, what: str, path: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        handler._require_known_query(query, {"limit", "cursor"})
        self._must_exist("spaces", space_id, "space")
        if what == "role-assignments":
            self._site_has_roles()
        source = self.space_permissions if what == "permissions" else self.role_assignments
        self._paged(handler, list(source.get(space_id, [])), path, query, query_pairs)

    def _site_has_roles(self) -> None:
        """A site without space roles (`role_mode` is None) answers 404 to everything about them."""
        if self.role_mode is None:
            raise RequestError(404, "Not found", "Space roles are not available on this site", code="NOT_FOUND")

    def _role_mode(self, handler: Any, query: dict[str, list[str]]) -> None:
        handler._require_known_query(query, set())
        self._site_has_roles()
        handler._reply_json(200, {"mode": self.role_mode})

    def _space_roles(self, handler: Any, path: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        handler._require_known_query(query, {"space-id", "limit", "cursor"})
        self._site_has_roles()
        asked = handler._single(query, "space-id")
        if asked is not None:
            self._must_exist("spaces", asked, "space")
        self._paged(handler, list(self.roles), path, query, query_pairs)

    # -- what a test sets up ------------------------------------------------------------------

    def restrict(self, content_id: str, state: str, grants: tuple[tuple[str, str, str], ...] = (), *, by: str = data.ACCOUNT, when: str = "2026-10-06T09:00:00.000Z") -> None:
        """Content with a restriction state and direct permissions `(operation, principal type, principal id)`."""
        entries = [{"operation": operation, "principal": {"principalType": kind, "principalId": who}, "createdAt": when, "createdBy": by} for operation, kind, who in grants]
        self.restrictions[content_id] = {"state": state, "createdAt": when, "createdBy": by, "permissions": entries}
