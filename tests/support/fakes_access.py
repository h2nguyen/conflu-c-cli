"""The in-memory Confluence for what the user may do, restrictions on content, and the permissions and roles of a space: a mixin of `FakeGateway` (`_init_access` sets up its state).

What it holds when a test starts (the data is in data_access.py, which the mock Confluence uses as well):

    content of the kinds that no other fixture has: 7501 folder, 7511 blog post, 7521 whiteboard, 7531 database, 7541 smart link, 7551 custom content
    the restriction state of 2002 (VIEW_RESTRICTED, five direct permissions), 2003 (EDIT_RESTRICTED) and 7501; everything else is OPEN
    what may be done: the operations of its kind (2003: read and comment only); a test sets `operations[(kind, id)]`
    the permission model and the role model of ENG (1001), and the role mode ROLES_TRANSITION, so that both are read; `role_mode = None` is a site without space
    roles: it answers 404 to the mode, the role assignments and the roles

Pages and spaces are known as they are, and so are the attachments and the comments that the fake holds (2002 has three comments and two attachments); other content
is known to this area when a test registers it in `content_kinds` (`fake.content_kinds["7600"] = "folder"`), as `content_types` needs it as well. A comment is asked
for by `content_types` only when it is registered there too (`fake.content_kinds["4001"] = "footer-comment"`).
"""
from __future__ import annotations

from conflu_c_cli.domain.access import (
    OPERATIONS_COLLECTIONS,
    RESTRICTION_COLLECTIONS,
    ContentPermission,
    Operation,
    RestrictionState,
    RoleAssignment,
    SpacePermission,
    SpaceRole,
    normalized_type,
)
from conflu_c_cli.domain.errors import NotFoundError
from conflu_c_cli.domain.model import Chunk

from . import data_access as data

COMMENT_KINDS = {"footer-comment": "footer", "inline-comment": "inline"}  # what Confluence calls a comment, and what the model of a comment calls its kind


class FakeAccess:
    def _init_access(self) -> None:
        self.role_mode: str | None = data.ROLE_MODE
        self.operations: dict[tuple[str, str], list[Operation]] = {}  # what a test lists for one thing, by (kind, id)
        self.restriction_states: dict[str, RestrictionState] = {}
        self.content_permissions: dict[str, list[ContentPermission]] = {}
        self.space_permissions: dict[str, list[SpacePermission]] = {}  # by the id of the space
        self.role_assignments: dict[str, list[RoleAssignment]] = {}
        self.space_roles: list[SpaceRole] = [SpaceRole(*row) for row in data.SPACE_ROLES]
        for content_id, kind in data.KINDS.items():
            self.content_kinds[content_id] = kind
        for content_id, (state, created, by, grants) in data.RESTRICTIONS.items():
            self.restriction_states[content_id] = RestrictionState(state, created, by)
            self.content_permissions[content_id] = [ContentPermission(operation, kind, who, created, by) for operation, kind, who in grants]
        for space_id, rows in data.SPACE_PERMISSIONS.items():
            self.space_permissions[space_id] = [SpacePermission(*row) for row in rows]
        for space_id, rows in data.ROLE_ASSIGNMENTS.items():
            self.role_assignments[space_id] = [RoleAssignment(normalized_type(kind), who, role) for kind, who, role in rows]

    # -- helpers ----------------------------------------------------------------------------

    def _has(self, kind: str, target_id: str) -> bool:
        if kind == "page":
            return target_id in self.pages
        if kind == "space":
            return any(space.id == target_id for space in self.spaces.values())
        if kind == "attachment" and any(item.id == target_id for items in self.attachments.values() for item in items):
            return True
        if kind in COMMENT_KINDS and any(item.id == target_id and item.kind == COMMENT_KINDS[kind] for items in self.comments.values() for item in items):
            return True
        return self.content_kinds.get(target_id) == kind

    def _must_have(self, kind: str, target_id: str, collection: str, tail: str) -> None:
        if not self._has(kind, target_id):
            raise NotFoundError(f"Not found: GET /api/v2/{collection}/{target_id}/{tail}")

    def _space_id(self, space_id: str, tail: str) -> None:
        self._must_have("space", space_id, "spaces", tail)

    # -- the port ---------------------------------------------------------------------------

    def list_operations(self, kind: str, target_id: str) -> list[Operation]:
        self._enter("list_operations", kind, target_id)
        collection = OPERATIONS_COLLECTIONS.get(kind)
        if collection is None:
            raise ValueError(f"Not something that has operations: {kind}")
        self._must_have(kind, target_id, collection, "operations")
        if (kind, target_id) in self.operations:
            return list(self.operations[(kind, target_id)])
        return [Operation(*item) for item in data.OPERATIONS_BY_ID.get(target_id, data.OPERATIONS[kind])]

    def get_restriction_state(self, kind: str, content_id: str) -> RestrictionState:
        self._enter("get_restriction_state", kind, content_id)
        collection = RESTRICTION_COLLECTIONS.get(kind)
        if collection is None:
            raise ValueError(f"Not content that has restrictions of its own: {kind}")
        self._must_have(kind, content_id, collection, "restriction-state")
        return self.restriction_states.get(content_id, RestrictionState("OPEN"))

    def list_content_permissions(self, kind: str, content_id: str, *, limit: int = 250, cursor: str = "") -> Chunk[ContentPermission]:
        self._enter("list_content_permissions", kind, content_id, limit, cursor)
        collection = RESTRICTION_COLLECTIONS.get(kind)
        if collection is None:
            raise ValueError(f"Not content that has restrictions of its own: {kind}")
        self._must_have(kind, content_id, collection, "permissions")
        return self._chunk(list(self.content_permissions.get(content_id, [])), cursor, limit)

    def get_space_role_mode(self) -> str:
        self._enter("get_space_role_mode")
        if self.role_mode is None:
            raise NotFoundError("Not found: GET /api/v2/space-role-mode")
        return self.role_mode

    def list_space_permissions(self, space_id: str, *, limit: int = 250, cursor: str = "") -> Chunk[SpacePermission]:
        self._enter("list_space_permissions", space_id, limit, cursor)
        self._space_id(space_id, "permissions")
        return self._chunk(list(self.space_permissions.get(space_id, [])), cursor, limit)

    def list_space_role_assignments(self, space_id: str, *, limit: int = 250, cursor: str = "") -> Chunk[RoleAssignment]:
        self._enter("list_space_role_assignments", space_id, limit, cursor)
        self._space_id(space_id, "role-assignments")
        self._site_has_roles(f"spaces/{space_id}/role-assignments")
        return self._chunk(list(self.role_assignments.get(space_id, [])), cursor, limit)

    def list_space_roles(self, space_id: str = "", *, limit: int = 250, cursor: str = "") -> Chunk[SpaceRole]:
        self._enter("list_space_roles", space_id, limit, cursor)
        if space_id and not self._has("space", space_id):
            raise NotFoundError(f"Not found: GET /api/v2/space-roles?space-id={space_id}")
        self._site_has_roles("space-roles")
        return self._chunk(list(self.space_roles), cursor, limit)

    def _site_has_roles(self, tail: str) -> None:
        """A site without space roles (`role_mode = None`) answers 404 to everything about them, as the mock does."""
        if self.role_mode is None:
            raise NotFoundError(f"Not found: GET /api/v2/{tail}")
