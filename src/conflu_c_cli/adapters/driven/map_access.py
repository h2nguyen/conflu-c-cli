"""What Confluence's JSON means for what the user may do, restrictions on content, and the permissions and roles of a space: the answers as domain objects."""
from __future__ import annotations

from typing import Any

from ...domain.access import (
    ContentPermission,
    Operation,
    RestrictionState,
    RoleAssignment,
    SpacePermission,
    SpaceRole,
    normalized_type,
)


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def operations_from(data: Any) -> list[Operation]:
    """The `operations` of an answer to `GET /{collection}/{id}/operations`."""
    items = _object(data).get("operations")
    if not isinstance(items, list):
        return []
    return [Operation(_text(item.get("operation")), _text(item.get("targetType"))) for item in items if isinstance(item, dict) and item.get("operation")]


def restriction_state_from(data: Any) -> RestrictionState:
    body = _object(data)
    return RestrictionState(
        _text(body.get("state")),
        _text(body.get("createdAt")),
        _text(body.get("createdBy") or body.get("createdByAaid")),  # `createdByAaid` is the deprecated name of `createdBy`
    )


def content_permission_from(item: dict[str, Any]) -> ContentPermission | None:
    principal = _object(item.get("principal"))
    if not item.get("operation") or not principal.get("principalId"):
        return None
    return ContentPermission(
        _text(item.get("operation")).lower(),
        normalized_type(principal.get("principalType")),
        _text(principal.get("principalId")),
        _text(item.get("createdAt")),
        _text(item.get("createdBy") or item.get("createdByAaid")),
    )


def space_permission_from(item: dict[str, Any]) -> SpacePermission | None:
    principal = _object(item.get("principal"))
    operation = _object(item.get("operation"))
    if not principal.get("id") or not operation.get("key"):
        return None
    return SpacePermission(
        _text(item.get("id")),
        normalized_type(principal.get("type")),
        _text(principal.get("id")),
        _text(operation.get("key")),
        _text(operation.get("targetType")),
    )


def role_assignment_from(item: dict[str, Any]) -> RoleAssignment | None:
    principal = _object(item.get("principal"))
    if not principal.get("principalId") or not item.get("roleId"):
        return None
    return RoleAssignment(normalized_type(principal.get("principalType")), _text(principal.get("principalId")), _text(item.get("roleId")))


def role_from(item: dict[str, Any]) -> SpaceRole | None:
    if not item.get("id"):
        return None
    return SpaceRole(_text(item.get("id")), _text(item.get("name")), _text(item.get("type")))


def role_mode_from(data: Any) -> str:
    return _text(_object(data).get("mode"))
