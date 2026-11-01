"""What the token's user may do, who may see or edit content, and who may use a space: as plain data, and the rules that read it.

Three questions, three kinds of answer. The operations are about the token's user alone (what *you* may do). The restriction state and the direct
permissions of a piece of content say who else may read or edit it, and the permissions or role assignments of a space say who may use the space.
Nothing here changes any of them: who may read content is decided in the web interface.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .content import BLOGPOST, DATABASE, FOLDER, KINDS, PAGE, WHITEBOARD
from .errors import UsageError

SPACE = "space"  # what the operations of a space are asked for: a space is no kind of content

# The collection of the REST API v2 that answers `/{collection}/{id}/operations`, for each kind of what has operations.
OPERATIONS_COLLECTIONS: dict[str, str] = {
    **{kind.name: kind.collection for kind in KINDS},
    "footer-comment": "footer-comments",
    "inline-comment": "inline-comments",
    "attachment": "attachments",
    "custom": "custom-content",
    SPACE: "spaces",
}
# The kinds that have a restriction state and direct permissions: a smart link, a comment and an attachment have none of their own.
RESTRICTION_COLLECTIONS: dict[str, str] = {kind.name: kind.collection for kind in (PAGE, BLOGPOST, FOLDER, WHITEBOARD, DATABASE)}

# What the document lists as the operation keys of a space permission: the operations that this CLI knows by name. A name that is not here is a typo
# in `--only`, and not an operation that is not allowed; the list of what is allowed shows whatever operation Confluence names.
KNOWN_OPERATIONS = (
    "use", "create", "read", "update", "delete", "copy", "move", "export", "purge", "purge_version", "administer", "restore", "create_space",
    "restrict_content", "archive",
)
HEADLINE_OPERATIONS = ("read", "update", "delete")  # always answered, yes or no

STATES = ("OPEN", "EDIT_RESTRICTED", "VIEW_RESTRICTED")  # what a restriction state is; STATES[0] is "no restriction on the content itself"
# What the document says each state means (the description of `state` in `getPageRestrictionState`), for the text that a person reads.
STATE_MEANING = {
    "OPEN": "No direct restriction on it. A parent may still restrict who can see or edit it.",
    "EDIT_RESTRICTED": "Viewing is open, but editing is restricted to the users and groups that are granted it.",
    "VIEW_RESTRICTED": "Viewing and editing are restricted to the users and groups that are granted it.",
}
CONTENT_OPERATIONS = ("read", "update")  # what a direct permission on content grants
CONTENT_PRINCIPALS = ("user", "group")


@dataclass(frozen=True)
class Subject:
    """What a command is about: a piece of content, or a space. `key` and `title` are those of a space as it is printed (`privacy.hide_space` says how:
    a personal space is `[hidden]` and `[personal space]`, unless people are shown); none is read for content (it would take a request of its own,
    and the person named the id)."""

    type: str  # what Confluence calls it: page, blogpost, folder, ... footer-comment, attachment, or space
    id: str
    key: str = ""  # of a space, as it is printed
    title: str = ""  # of a space, as it is printed


@dataclass(frozen=True)
class Operation:
    operation: str  # read, update, delete, create, ...
    target_type: str  # what it is done to: page, comment, attachment, space ...


@dataclass(frozen=True)
class RestrictionState:
    state: str  # OPEN, EDIT_RESTRICTED or VIEW_RESTRICTED: what is set on the content itself, not what a parent sets
    created: str = ""
    created_by: str = ""  # the account id of who set it: a person


@dataclass(frozen=True)
class ContentPermission:
    """One direct permission on content: this user or group may read, or may update."""

    operation: str  # read | update
    principal_type: str  # user | group
    principal_id: str  # an account id for a user, a group id for a group
    created: str = ""
    created_by: str = ""


@dataclass(frozen=True)
class SpacePermission:
    """One assignment of the permission model of a space: this user, group or role may do this to that."""

    id: str
    principal_type: str  # user | group | role
    principal_id: str
    operation: str
    target_type: str


@dataclass(frozen=True)
class SpaceRole:
    id: str
    name: str
    type: str = ""  # SYSTEM | CUSTOM


@dataclass(frozen=True)
class RoleAssignment:
    """One assignment of the role model of a space: this user, group or access class has that role."""

    principal_type: str  # user | group | access_class
    principal_id: str
    role_id: str


@dataclass(frozen=True)
class PermissionCount:
    """How many users, groups and roles hold one operation on one kind of thing in a space."""

    operation: str
    target_type: str
    user: int = 0
    group: int = 0
    role: int = 0


@dataclass(frozen=True)
class RoleCount:
    """How many users, groups and access classes have one role in a space."""

    role_id: str
    name: str
    type: str = ""
    user: int = 0
    group: int = 0
    access_class: int = 0


@dataclass(frozen=True)
class Principal:
    """A user, a group, a role or an access class with what it was given, for the lists that show who they are. A person: only with `--with-users`."""

    model: str  # permissions | roles
    principal_type: str
    principal_id: str
    operation: str = ""  # of the permission model
    target_type: str = ""
    role_id: str = ""  # of the role model
    role_name: str = ""


def normalized_type(text: str) -> str:
    """`USER` and `user` are the same: the document spells the types of a role assignment in capitals and those of a permission in lower case."""
    return (text or "").strip().lower()


def only_names(text: str | None) -> list[str]:
    """The operations that `--only` names: lower case, each once, in the order given; none when nothing was given.

    A name that is not an operation of the document is refused before anything is asked: `no` for a mistyped `updat` would read as a refusal by
    Confluence."""
    if not text:
        return []
    names = list(dict.fromkeys(part.strip().lower() for part in text.split(",") if part.strip()))
    if not names:
        raise UsageError("--only needs the names of operations.", hint=f"For example --only update,delete. Known: {', '.join(KNOWN_OPERATIONS)}.")
    unknown = [name for name in names if name not in KNOWN_OPERATIONS]
    if unknown:
        raise UsageError(f"Not an operation: {', '.join(unknown)}.", hint=f"Known operations: {', '.join(KNOWN_OPERATIONS)}.")
    return names


def can(operations: Sequence[Operation], only: Sequence[str] = ()) -> dict[str, bool]:
    """Whether each operation is allowed: the ones in `only`, else read, update and delete and every other operation that was listed."""
    allowed = {item.operation for item in operations}
    if only:
        return {name: name in allowed for name in only}
    rest = sorted(allowed - set(HEADLINE_OPERATIONS))
    return {name: name in allowed for name in (*HEADLINE_OPERATIONS, *rest)}


def operations_for(operations: Sequence[Operation], only: Sequence[str] = ()) -> list[Operation]:
    """The operations in a fixed order, and only those named in `only` when something was named."""
    kept = [item for item in operations if not only or item.operation in only]
    return sorted(set(kept), key=lambda item: (item.operation, item.target_type))


def count_content_permissions(permissions: Iterable[ContentPermission]) -> dict[str, dict[str, int]]:
    """`{read: {user: 1, group: 2}, update: {...}}`: all four counts are there, 0 when nobody. An operation or a kind of principal that the
    document does not know is counted under its own name."""
    counts: dict[str, dict[str, int]] = {operation: {kind: 0 for kind in CONTENT_PRINCIPALS} for operation in CONTENT_OPERATIONS}
    for item in permissions:
        row = counts.setdefault(item.operation, {kind: 0 for kind in CONTENT_PRINCIPALS})
        row[item.principal_type] = row.get(item.principal_type, 0) + 1
    return counts


def count_space_permissions(permissions: Iterable[SpacePermission]) -> list[PermissionCount]:
    tally: dict[tuple[str, str], dict[str, int]] = {}
    for item in permissions:
        row = tally.setdefault((item.operation, item.target_type), {"user": 0, "group": 0, "role": 0})
        if item.principal_type in row:
            row[item.principal_type] += 1
    return [PermissionCount(operation, target, **row) for (operation, target), row in sorted(tally.items())]


def count_roles(assignments: Iterable[RoleAssignment], roles: Iterable[SpaceRole]) -> list[RoleCount]:
    """The assignments per role, with the name of the role where it is known (else its id stands for it). Roles nobody has are left out."""
    known = {role.id: role for role in roles}
    tally: dict[str, dict[str, int]] = {}
    for item in assignments:
        row = tally.setdefault(item.role_id, {"user": 0, "group": 0, "access_class": 0})
        if item.principal_type in row:
            row[item.principal_type] += 1
    found = [
        RoleCount(role_id, known[role_id].name if role_id in known else role_id, known[role_id].type if role_id in known else "", **row)
        for role_id, row in tally.items()
    ]
    return sorted(found, key=lambda item: (item.name.casefold(), item.role_id))
