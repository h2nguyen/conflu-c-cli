"""What the user may do, restrictions on content, and the permissions and roles of a space: the REST calls. A mixin of `RestConfluenceGateway`, which provides `_call`, `_finish`, `_transport`, `_settings`,
`_next_cursor` and `_base`."""
from __future__ import annotations

from typing import TYPE_CHECKING

from ...domain.model import Chunk
from .confluence_mapper import results_of
from .rest_support import V2, query, quote

# The models and the mapper of this area are imported where they are used, so that a command that never reads it does not load them (tests/test_startup.py).
if TYPE_CHECKING:
    from ...domain.access import ContentPermission, Operation, RestrictionState, RoleAssignment, SpacePermission, SpaceRole

# The calls of this area that use the v1 API, each with why v2 does not do (see docs/reference/compatibility.md). None: v2 answers every question
# of this area, and none of the calls changes anything.
V1_CALLS: dict[str, str] = {}


def _operations_collection(kind: str) -> str:
    from ...domain.access import OPERATIONS_COLLECTIONS

    found = OPERATIONS_COLLECTIONS.get(kind)
    if found is None:
        raise ValueError(f"Not something that has operations: {kind}")
    return found


def _restriction_collection(kind: str) -> str:
    from ...domain.access import RESTRICTION_COLLECTIONS

    found = RESTRICTION_COLLECTIONS.get(kind)
    if found is None:
        raise ValueError(f"Not content that has restrictions of its own: {kind}")
    return found


class RestAccess:
    def list_operations(self, kind: str, target_id: str) -> list[Operation]:
        from . import map_access as access_mapper

        data = self._call("GET", f"{V2}/{_operations_collection(kind)}/{quote(target_id)}/operations")
        return access_mapper.operations_from(data)

    def get_restriction_state(self, kind: str, content_id: str) -> RestrictionState:
        from . import map_access as access_mapper

        data = self._call("GET", f"{V2}/{_restriction_collection(kind)}/{quote(content_id)}/restriction-state")
        return access_mapper.restriction_state_from(data)

    def list_content_permissions(self, kind: str, content_id: str, *, limit: int = 250, cursor: str = "") -> Chunk[ContentPermission]:
        from . import map_access as access_mapper

        data = self._call("GET", f"{V2}/{_restriction_collection(kind)}/{quote(content_id)}/permissions?{query(limit=limit, cursor=cursor)}")
        found = [item for item in map(access_mapper.content_permission_from, results_of(data)) if item is not None]
        return Chunk(found, self._next_cursor(data))

    def get_space_role_mode(self) -> str:
        from . import map_access as access_mapper

        return access_mapper.role_mode_from(self._call("GET", f"{V2}/space-role-mode"))

    def list_space_permissions(self, space_id: str, *, limit: int = 250, cursor: str = "") -> Chunk[SpacePermission]:
        from . import map_access as access_mapper

        data = self._call("GET", f"{V2}/spaces/{quote(space_id)}/permissions?{query(limit=limit, cursor=cursor)}")
        found = [item for item in map(access_mapper.space_permission_from, results_of(data)) if item is not None]
        return Chunk(found, self._next_cursor(data))

    def list_space_role_assignments(self, space_id: str, *, limit: int = 250, cursor: str = "") -> Chunk[RoleAssignment]:
        from . import map_access as access_mapper

        data = self._call("GET", f"{V2}/spaces/{quote(space_id)}/role-assignments?{query(limit=limit, cursor=cursor)}")
        found = [item for item in map(access_mapper.role_assignment_from, results_of(data)) if item is not None]
        return Chunk(found, self._next_cursor(data))

    def list_space_roles(self, space_id: str = "", *, limit: int = 250, cursor: str = "") -> Chunk[SpaceRole]:
        from . import map_access as access_mapper

        data = self._call("GET", f"{V2}/space-roles?{query(space_id=space_id, limit=limit, cursor=cursor)}")
        found = [item for item in map(access_mapper.role_from, results_of(data)) if item is not None]
        return Chunk(found, self._next_cursor(data))
