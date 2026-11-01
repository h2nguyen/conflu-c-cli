"""Use cases around what the user may do, restrictions on content, and the permissions and roles of a space.

All of it is read only. No use case changes a restriction, a permission or a role: who may read content is decided in the web interface (or with
`conflu api ... --write`, which says what it sends).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Sequence, TypeVar

from ..domain.access import (
    OPERATIONS_COLLECTIONS,
    RESTRICTION_COLLECTIONS,
    SPACE,
    ContentPermission,
    Operation,
    PermissionCount,
    Principal,
    RestrictionState,
    RoleCount,
    SpaceRole,
    Subject,
    can,
    count_content_permissions,
    count_roles,
    count_space_permissions,
    only_names,
    operations_for,
)
from ..domain.content import describe, parse_content_id
from ..domain.errors import ConfluCliError, NotFoundError, RejectedError, UsageError, ValidationError
from ..domain.model import is_attachment_id, parse_space_key
from ..domain.privacy import hide_space, redact_text
from .paging import ensure_users_allowed, fetch_all
from .ports import ConfluenceGateway
from .services import Services
from .settings import Settings

READ_PAGE = 250  # the most that the calls of this area give in one answer
INHERITED = "Only what is set on the content itself is shown: a restriction that a parent page or folder sets is not in these calls, so OPEN does not mean that everybody may read it."
_CURSOR = re.compile(r"[0-9]{1,9}")
T = TypeVar("T")


def resolve_content(gateway: ConfluenceGateway, ref: str) -> tuple[str, str]:
    """What kind of content an id or an address names, and its id: `("folder", "7001")`. An attachment id (`att123`) says what it is, so nothing is asked."""
    text = (ref or "").strip()
    if is_attachment_id(text):
        return "attachment", text
    content_id = parse_content_id(text)
    kind = gateway.content_types([content_id]).get(content_id)
    if kind is None:
        raise NotFoundError(
            f"No content with the id {content_id} that this account can see.",
            hint="Check the id: the address of a page has it. Confluence says the same for content that does not exist and for content this account may not see.",
            details={"id": content_id},
        )
    return kind, content_id


def looks_like_a_space_key(text: str) -> bool:
    """Whether a text that is no id could be the key of a space (`ENG`): what a person types who means `--space`."""
    try:
        parse_space_key(text)
    except ValidationError:
        return False
    return not text.strip().isdigit()


def check_window(limit: int, cursor: str) -> None:
    if not 1 <= limit <= 250:
        raise UsageError("--limit must be between 1 and 250.")
    if cursor and not _CURSOR.fullmatch(cursor):
        raise UsageError(f"Not a cursor of this command: {cursor}", hint="Pass the nextCursor of the previous answer as it is.")


def window(items: Sequence[T], *, limit: int, cursor: str, everything: bool) -> tuple[list[T], str]:
    """The part of a list that `--limit`, `--cursor` and `--all` ask for, and the cursor of the next part (empty on the last). The whole list was read,
    so that the counts are of all of it: the cursor is a position in it, and nothing for the person to read."""
    if everything:
        return list(items), ""
    start = int(cursor or 0)
    end = start + limit
    return list(items[start:end]), (str(end) if end < len(items) else "")


# -- permissions --------------------------------------------------------------------------------


@dataclass
class Permissions:
    subject: Subject
    operations: list[Operation]  # in a fixed order, and only those named in `only` when something was
    can: dict[str, bool]  # whether each operation is allowed
    only: list[str]


class ShowPermissions:
    """What the token's user may do with a piece of content or in a space."""

    def __init__(self, gateway: ConfluenceGateway, settings: Settings) -> None:
        self._gateway = gateway
        self._settings = settings

    def execute(self, ref: str = "", *, space: str = "", only: str = "") -> Permissions:
        ref, space = (ref or "").strip(), (space or "").strip()
        if ref and space:
            raise UsageError("Give the id of content or --space, not both.", hint="`conflu permissions ID` is about content, `conflu permissions --space KEY` about a space.")
        names = only_names(only)  # a typo is refused before anything is asked
        if ref:
            try:
                kind, target_id = resolve_content(self._gateway, ref)
            except ValidationError as error:
                if not looks_like_a_space_key(ref):
                    raise
                raise ValidationError(error.message, hint=f"If {ref} is the key of a space, use --space {ref}.", details=error.details) from error
            if kind not in OPERATIONS_COLLECTIONS or kind == SPACE:
                raise ValidationError(f"{target_id} is {describe(kind)}: this CLI does not ask what may be done with that.", details={"id": target_id, "type": kind})
            operations = self._gateway.list_operations(kind, target_id)
            subject = Subject(kind, target_id)
        else:
            key = space or self._settings.space
            if not key:
                raise UsageError("Neither content nor a space is named.", hint="Give the id of content, or --space KEY, or run `conflu use KEY` to choose a current space.")
            found = self._gateway.get_space(parse_space_key(key))
            operations = self._gateway.list_operations(SPACE, found.id)
            shown = hide_space(found)  # a personal space is named by its owner, and this command cannot show people
            subject = Subject(SPACE, shown.id, shown.key, shown.name)
        return Permissions(subject, operations_for(operations, names), can(operations, names), names)


# -- restrictions -------------------------------------------------------------------------------


@dataclass
class Restrictions:
    subject: Subject
    state: RestrictionState  # without who set it, unless people are shown
    counts: dict[str, dict[str, int]]  # {read: {user, group}, update: {user, group}}, of all the direct permissions
    total: int  # how many direct permissions there are
    permissions: list[ContentPermission] | None  # the part that was asked for; None unless people are shown
    users_shown: bool
    next_cursor: str = ""
    truncated: bool = False
    notes: list[str] = field(default_factory=list)


class ShowRestrictions:
    """The restriction on content (open, or who may edit, or who may view) and the direct permissions that go with it. Who they are: only for people who ask."""

    def __init__(self, gateway: ConfluenceGateway, settings: Settings) -> None:
        self._gateway = gateway
        self._settings = settings

    def execute(self, ref: str, *, with_users: bool = False, limit: int = 25, cursor: str = "", fetch_everything: bool = False) -> Restrictions:
        ensure_users_allowed(with_users, self._settings)
        check_window(limit, cursor)
        kind, content_id = resolve_content(self._gateway, ref)
        if kind not in RESTRICTION_COLLECTIONS:
            raise ValidationError(
                f"{content_id} is {describe(kind)}, which has no restrictions of its own.",
                hint="Pages, blog posts, folders, whiteboards and databases have them; a comment or an attachment follows the content it belongs to: ask for that.",
                details={"id": content_id, "type": kind},
            )
        state = self._gateway.get_restriction_state(kind, content_id)
        everything, cut = fetch_all(lambda next_cursor: self._gateway.list_content_permissions(kind, content_id, limit=READ_PAGE, cursor=next_cursor))
        notes = [INHERITED]
        if cut:
            notes.append(f"Only the first {len(everything)} direct permissions were read: the counts are of those.")
        shown: list[ContentPermission] | None = None
        next_cursor = ""
        if with_users:
            ordered = sorted(everything, key=lambda item: (item.operation, item.principal_type, item.principal_id))
            shown, next_cursor = window(ordered, limit=limit, cursor=cursor, everything=fetch_everything)
        return Restrictions(
            Subject(kind, content_id),
            state if with_users else replace(state, created_by=""),
            count_content_permissions(everything),
            len(everything),
            shown,
            with_users,
            next_cursor,
            cut,
            notes,
        )


# -- who may use a space ------------------------------------------------------------------------

PERMISSIONS, ROLES = "permissions", "roles"  # the two ways that a space can give access


@dataclass
class SpaceAccess:
    subject: Subject
    mode: str | None  # PRE_ROLES, ROLES_TRANSITION or ROLES; None when the site does not say
    models: tuple[str, ...]  # which of PERMISSIONS and ROLES were read
    permission_counts: list[PermissionCount] | None  # None unless the permission model was read
    permission_total: int
    role_counts: list[RoleCount] | None  # None unless the role model was read
    role_total: int
    principals: list[Principal] | None  # the part that was asked for; None unless people are shown
    users_shown: bool
    total: int  # the assignments of all the models that were read
    next_cursor: str = ""
    truncated: bool = False
    notes: list[str] = field(default_factory=list)


class ShowSpaceAccess:
    """Who may use a space: the way the site gives access (permissions or roles), and how many users, groups and roles hold what. Who they are: only for people who ask."""

    def __init__(self, gateway: ConfluenceGateway, settings: Settings) -> None:
        self._gateway = gateway
        self._settings = settings

    def execute(self, key: str = "", *, with_users: bool = False, limit: int = 25, cursor: str = "", fetch_everything: bool = False) -> SpaceAccess:
        ensure_users_allowed(with_users, self._settings)
        check_window(limit, cursor)
        chosen = (key or "").strip() or self._settings.space
        if not chosen:
            raise UsageError("No space selected.", hint="Pass a space key or run `conflu use KEY`.")
        space = self._gateway.get_space(parse_space_key(chosen))
        shown = space if with_users else hide_space(space)  # what is printed of the space; the calls below use its id, which names nobody
        notes: list[str] = []
        mode, models = self._models(notes)
        permissions, assignments, roles = [], [], []
        cut = False
        if PERMISSIONS in models:
            permissions, cut = fetch_all(lambda next_cursor: self._gateway.list_space_permissions(space.id, limit=READ_PAGE, cursor=next_cursor))
        if ROLES in models:
            try:
                assignments, cut_roles = fetch_all(lambda next_cursor: self._gateway.list_space_role_assignments(space.id, limit=READ_PAGE, cursor=next_cursor))
            except (NotFoundError, RejectedError) as error:
                if models == (ROLES,):
                    raise
                models = (PERMISSIONS,)
                notes.append(f"The role assignments of the space could not be read, so only its permission assignments are shown: {redact_text(error.message)}")
            else:
                cut = cut or cut_roles
                roles = self._roles(space.id, bool(assignments), notes)
        if cut:
            notes.append("The lists were cut short at their limit: the counts are of what was read.")
        names = {role.id: role.name if with_users else redact_text(role.name) for role in roles}
        role_counts = None
        if ROLES in models:
            kept = [replace(role, name=names[role.id]) for role in roles]
            role_counts = count_roles(assignments, kept)
        principals, next_cursor = None, ""
        if with_users:
            rows = [Principal(PERMISSIONS, item.principal_type, item.principal_id, operation=item.operation, target_type=item.target_type) for item in permissions]
            rows += [Principal(ROLES, item.principal_type, item.principal_id, role_id=item.role_id, role_name=names.get(item.role_id, item.role_id)) for item in assignments]
            rows.sort(key=lambda row: (row.model, row.operation, row.target_type, row.role_name.casefold(), row.principal_type, row.principal_id))
            principals, next_cursor = window(rows, limit=limit, cursor=cursor, everything=fetch_everything)
        return SpaceAccess(
            Subject(SPACE, shown.id, shown.key, shown.name),
            mode,
            models,
            count_space_permissions(permissions) if PERMISSIONS in models else None,
            len(permissions),
            role_counts,
            len(assignments),
            principals,
            with_users,
            len(permissions) + len(assignments),
            next_cursor,
            cut,
            notes,
        )

    def _models(self, notes: list[str]) -> tuple[str | None, tuple[str, ...]]:
        """The mode of the site and the models that follow from it. A site that cannot say is asked for both: one without space roles answers
        for the permissions, and the roles that fail to come are said so."""
        try:
            mode = self._gateway.get_space_role_mode()
        except (NotFoundError, RejectedError):
            notes.append("This site does not report a space role mode, so both the permission assignments and the role assignments are tried.")
            return None, (PERMISSIONS, ROLES)
        if mode == "PRE_ROLES":
            return mode, (PERMISSIONS,)
        if mode == "ROLES":
            return mode, (ROLES,)
        notes.append(
            "The site is moving from permissions to roles (ROLES_TRANSITION): both are shown."
            if mode == "ROLES_TRANSITION"
            else f"The space role mode {redact_text(mode) or '(none)'} is not one this CLI knows: both models are shown."
        )
        return redact_text(mode) or None, (PERMISSIONS, ROLES)

    def _roles(self, space_id: str, needed: bool, notes: list[str]) -> list[SpaceRole]:
        """The roles that name the assignments (best effort: without them a role is shown by its id)."""
        if not needed:
            return []
        try:
            return fetch_all(lambda next_cursor: self._gateway.list_space_roles(space_id, limit=READ_PAGE, cursor=next_cursor))[0]
        except ConfluCliError as error:
            notes.append(f"The names of the roles could not be read, so a role is shown by its id: {redact_text(error.message)}")
            return []


@dataclass
class AccessUseCases:
    """The use cases of the area, reached as `app.access.<name>`."""

    permissions: ShowPermissions
    restrictions: ShowRestrictions
    space_access: ShowSpaceAccess


def build(services: Services) -> AccessUseCases:
    return AccessUseCases(
        permissions=ShowPermissions(services.gateway, services.settings),
        restrictions=ShowRestrictions(services.gateway, services.settings),
        space_access=ShowSpaceAccess(services.gateway, services.settings),
    )
