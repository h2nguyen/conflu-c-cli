"""Commands about what the user may do, who may see or edit content, and who may use a space: permissions, restrictions, space-access.

All three only read. None changes a restriction, a permission or a role: who may read content is decided in the web interface (or with
`conflu api ... --write`, which can preview the request with `--dry-run`). People stay out of every answer until `--with-users`.
"""
from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from .....domain.access import CONTENT_PRINCIPALS, STATE_MEANING, ContentPermission, Principal, Subject
from .....domain.content import describe
from .....domain.errors import UsageError
from ..listing import FORMAT, SELECT, print_list, structured_text
from ..render import table
from ..runtime import Context
from ..spec import Arg, Command, Example
from ._common import check_limit

if TYPE_CHECKING:
    from .....application.access import Permissions, Restrictions, SpaceAccess

GROUP = "Access and people"
LIST_PAGE = 25  # principals in a piece of the list, when --limit says nothing
ID_NOT_A_PATH = "the id of content in Confluence, or its address in the browser"
NOT_CHANGED = (
    "Read only: nothing here changes who may see or edit content. That is done in the web interface, or with `conflu api ... --write`, which says what it sends "
    "and previews it with --dry-run."
)
WITH_USERS = Arg(
    ("--with-users",),
    "Show who: the account ids of users and the ids of groups, and who set the restriction. Refused when CONFLUENCE_HIDE_USERS=true. "
    "Without it only the counts are shown.",
    kind="flag",
)
WITH_USERS_OF_A_SPACE = Arg(
    ("--with-users",),
    "Show who: the account ids of users and the ids of groups (and the roles and access classes), with what each holds. Refused when CONFLUENCE_HIDE_USERS=true. "
    "Without it only the counts are shown.",
    kind="flag",
)
LIMIT = Arg(("--limit",), "With --with-users: principals in a piece of the list (1 to 250, default 25).", kind="int", metavar="N")
CURSOR = Arg(("--cursor",), "With --with-users: continue after the end of the previous answer: pass its nextCursor.", metavar="TOKEN")
ALL = Arg(("--all",), "With --with-users: show every principal instead of one piece (ignores --limit and --cursor).", kind="flag")
PERMISSION_COLUMNS = [("OPERATION", "operation"), ("TYPE", "principalType"), ("PRINCIPAL", "principalId")]
PRINCIPAL_COLUMNS = [
    ("MODEL", "model"),
    ("TYPE", "principalType"),
    ("PRINCIPAL", "principalId"),
    ("OPERATION", "operation"),
    ("ON", "targetType"),
    ("ROLE", "roleName"),
]


def the(kind: str) -> str:
    """`the folder`, `the footer comment`: what a kind is called in a sentence."""
    text = describe(kind)
    for article in ("an ", "a "):
        if text.startswith(article):
            return "the " + text[len(article) :]
    return text


def subject_json(subject: Subject) -> dict[str, Any]:
    return {"id": subject.id, "type": subject.type, "key": subject.key or None, "title": subject.title or None}


def where(subject: Subject) -> str:
    if subject.type == "space":
        return f"the space {subject.key}" + (f" ({subject.title})" if subject.title else "")
    return f"{the(subject.type)} [{subject.id}]"


def plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def _usable_only_with_users(args: argparse.Namespace, what: str) -> None:
    """A piece of the list, a cursor, a selection or a format shapes the list of principals, which there is none of until `--with-users`."""
    if args.with_users:
        return
    for flag, given in (
        ("--limit", args.limit is not None),
        ("--cursor", args.cursor is not None),
        ("--all", args.all),
        ("--select", bool(args.select)),
        ("--format", args.format != "table"),
    ):
        if given:
            raise UsageError(f"{flag} shapes the list of {what}, which is shown only with --with-users.", hint="Add --with-users to see who they are. The counts are always shown.")


def _more(ctx: Context, what: str, next_cursor: str) -> None:
    if next_cursor:
        ctx.diagnostics.info(f"More {what} follow. Continue with --cursor {next_cursor}, or use --all.")


# -- permissions ---------------------------------------------------------------------------------


def permissions_json(result: Permissions) -> dict[str, Any]:
    return {
        "target": subject_json(result.subject),
        "operations": [{"operation": item.operation, "targetType": item.target_type} for item in result.operations],
        "can": result.can,
    }


def permissions_text(result: Permissions) -> str:
    """Each operation with yes or no and what it is done to: `create` may be allowed for a comment and an attachment, and not for a page."""
    targets: dict[str, list[str]] = {}
    for item in result.operations:
        targets.setdefault(item.operation, []).append(item.target_type)
    rows = [(name, "yes" if allowed else "no", ", ".join(sorted(set(targets.get(name, []))))) for name, allowed in result.can.items()]
    inside = "in" if result.subject.type == "space" else "with"
    return f"What this account may do {inside} {where(result.subject)}:\n" + table(["OPERATION", "ALLOWED", "ON"], rows)


def run_permissions(ctx: Context, args: argparse.Namespace) -> int:
    result = ctx.app.access.permissions.execute(args.ref or "", space=args.space or "", only=args.only or "")
    ctx.print_json(permissions_json(result)) if ctx.json_mode else ctx.print(permissions_text(result))
    return 0


# -- restrictions --------------------------------------------------------------------------------


def permission_row(item: ContentPermission) -> dict[str, Any]:
    return {
        "operation": item.operation,
        "principalType": item.principal_type,
        "principalId": item.principal_id,
        "createdAt": item.created or None,
        "createdBy": item.created_by or None,
    }


def restrictions_json(result: Restrictions) -> dict[str, Any]:
    state = result.state
    rows = None if result.permissions is None else [permission_row(item) for item in result.permissions]
    return {
        "target": subject_json(result.subject),
        "state": state.state,
        "meaning": STATE_MEANING.get(state.state),
        "createdAt": state.created or None,
        "createdBy": state.created_by or None,
        "counts": result.counts,
        "total": result.total,
        "usersShown": result.users_shown,
        "count": None if rows is None else len(rows),
        "nextCursor": result.next_cursor or None,
        "truncated": result.truncated,
        "permissions": rows,
        "notes": result.notes,
    }


def restrictions_text(result: Restrictions) -> str:
    state = result.state
    name = f"{the(result.subject.type)} [{result.subject.id}]"
    lines = [f"{name[:1].upper() + name[1:]} is {state.state}." if state.state else f"Confluence names no restriction state for {name}."]
    if state.state in STATE_MEANING:
        lines.append(STATE_MEANING[state.state])
    if state.created:
        lines.append(f"Set on {state.created}" + (f" by {state.created_by}." if state.created_by else "."))
    if result.total:
        rows = [(operation, str(kinds.get("user", 0)), str(kinds.get("group", 0))) for operation, kinds in result.counts.items()]
        lines += ["", f"{plural(result.total, 'direct permission')}:", table(["OPERATION", *(f"{kind.upper()}S" for kind in CONTENT_PRINCIPALS)], rows)]
    else:
        lines += ["", "No direct permissions."]
    if result.permissions is not None and (result.permissions or result.total):
        rows = [permission_row(item) for item in result.permissions]
        lines += ["", structured_text(rows, PERMISSION_COLUMNS, None, "table") if rows else "(none in this piece of the list)"]
    lines += ["", *result.notes]
    return "\n".join(lines)


def run_restrictions(ctx: Context, args: argparse.Namespace) -> int:
    _usable_only_with_users(args, "the principals")
    limit = LIST_PAGE if args.limit is None else args.limit
    check_limit(limit)
    result = ctx.app.access.restrictions.execute(args.ref, with_users=args.with_users, limit=limit, cursor=args.cursor or "", fetch_everything=args.all)
    document = restrictions_json(result)
    if result.permissions is None:
        ctx.print_json(document) if ctx.json_mode else ctx.print(restrictions_text(result))
        if not ctx.json_mode and result.total:
            ctx.diagnostics.info("Who holds these is not shown. --with-users lists the users and groups; the counts above are always shown.")
        return 0
    rows = document["permissions"]
    if print_list(ctx, args, payload=document, rows=rows, list_key="permissions", columns=PERMISSION_COLUMNS, plain=lambda: restrictions_text(result)):
        return 0
    if args.format != "table" or args.select:  # the notes are not in the text of the list: that is rows only
        for note in result.notes:
            ctx.diagnostics.info(note)
    _more(ctx, "principals", result.next_cursor)
    return 0


# -- space-access --------------------------------------------------------------------------------


def principal_row(item: Principal) -> dict[str, Any]:
    return {
        "model": item.model,
        "principalType": item.principal_type,
        "principalId": item.principal_id,
        "operation": item.operation or None,
        "targetType": item.target_type or None,
        "roleId": item.role_id or None,
        "roleName": item.role_name or None,
    }


def space_access_json(result: SpaceAccess) -> dict[str, Any]:
    rows = None if result.principals is None else [principal_row(item) for item in result.principals]
    permissions, roles = result.permission_counts, result.role_counts
    return {
        "target": subject_json(result.subject),
        "mode": result.mode,
        "models": list(result.models),
        "permissionTotal": None if permissions is None else result.permission_total,
        "permissionCounts": None
        if permissions is None
        else [{"operation": item.operation, "targetType": item.target_type, "user": item.user, "group": item.group, "role": item.role} for item in permissions],
        "roleTotal": None if roles is None else result.role_total,
        "roleCounts": None
        if roles is None
        else [{"roleId": item.role_id, "name": item.name, "type": item.type or None, "user": item.user, "group": item.group, "accessClass": item.access_class} for item in roles],
        "usersShown": result.users_shown,
        "total": result.total,
        "count": None if rows is None else len(rows),
        "nextCursor": result.next_cursor or None,
        "truncated": result.truncated,
        "principals": rows,
        "notes": result.notes,
    }


def space_access_text(result: SpaceAccess) -> str:
    subject = result.subject
    lines = [f"Access to {where(subject)}", f"Role mode: {result.mode or 'not reported by this site'}"]
    if result.permission_counts is not None:
        rows = [(item.operation, item.target_type, str(item.user), str(item.group), str(item.role)) for item in result.permission_counts]
        lines += ["", f"{plural(result.permission_total, 'permission assignment')}:"]
        lines.append(table(["OPERATION", "ON", "USERS", "GROUPS", "ROLES"], rows) if rows else "(none)")
    if result.role_counts is not None:
        rows = [(item.name, item.type, str(item.user), str(item.group), str(item.access_class)) for item in result.role_counts]
        lines += ["", f"{plural(result.role_total, 'role assignment')}:"]
        lines.append(table(["ROLE", "TYPE", "USERS", "GROUPS", "ACCESS CLASSES"], rows) if rows else "(none)")
    if result.principals is not None and (result.principals or result.total):
        rows = [(item.model, item.principal_type, item.principal_id, item.role_name or f"{item.operation} {item.target_type}".strip()) for item in result.principals]
        lines += ["", table(["MODEL", "TYPE", "PRINCIPAL", "GRANTED"], rows) if rows else "(none in this piece of the list)"]
    lines += ["", *result.notes]
    return "\n".join(lines)


def run_space_access(ctx: Context, args: argparse.Namespace) -> int:
    _usable_only_with_users(args, "the principals")
    limit = LIST_PAGE if args.limit is None else args.limit
    check_limit(limit)
    result = ctx.app.access.space_access.execute(args.space or "", with_users=args.with_users, limit=limit, cursor=args.cursor or "", fetch_everything=args.all)
    document = space_access_json(result)
    if result.principals is None:
        ctx.print_json(document) if ctx.json_mode else ctx.print(space_access_text(result))
        if not ctx.json_mode and result.total:
            ctx.diagnostics.info("Who holds these is not shown. --with-users lists the users and groups; the counts above are always shown.")
        return 0
    rows = document["principals"]
    if print_list(ctx, args, payload=document, rows=rows, list_key="principals", columns=PRINCIPAL_COLUMNS, plain=lambda: space_access_text(result)):
        return 0
    if args.format != "table" or args.select:
        for note in result.notes:
            ctx.diagnostics.info(note)
    _more(ctx, "principals", result.next_cursor)
    return 0


COMMANDS = (
    Command(
        name="permissions",
        group=GROUP,
        summary="Show what your account may do with content or in a space",
        when="Use before a change to see whether this account may do it (update, delete, create ...), instead of reading the refusal. "
        "It answers for the account of the token only; who else may see or edit content is `restrictions`, and who may use a space is `space-access`.",
        description="Asks Confluence which operations the account of the token is allowed on a page, blog post, folder, whiteboard, database, smart link, comment or "
        "attachment (give its id or address; what it is gets looked up), or with --space (or the current space) in a space, and what each operation is done to. "
        "`can` answers read, update and delete with yes or no, and every other operation that is allowed; --only names the operations you ask about and "
        "keeps those (an operation that is not allowed is `no`). Not about other people.",
        args=(
            Arg(
                ("ref",),
                "Id of a page, blog post, folder, whiteboard, database, smart link, comment or attachment, or its address as copied from the browser. Leave it out to ask about a space.",
                metavar="ID",
                not_a_path=ID_NOT_A_PATH,
            ),
            Arg(("--space",), "Ask about this space instead of content. Without an ID and without --space the current space (`conflu use`) is used.", metavar="KEY"),
            Arg(("--only",), "Only these operations, comma separated, for example update,delete: the answer says yes or no for each.", metavar="NAME,NAME"),
        ),
        examples=(
            Example("conflu permissions 123456", "everything this account may do with a page"),
            Example("conflu permissions 123456 --only update,delete", "yes or no for each"),
            Example("conflu permissions --space ENG --json", "what this account may do in a space, as JSON"),
        ),
        notes=(
            NOT_CHANGED,
            "`create` may be allowed for a comment or an attachment and not for a page: `operations` and the column ON say what each operation is done to.",
        ),
        json_output=True,
        output="target ({id, type, key, title}: key and title only for a space; the title of content is not read), operations[] ({operation, targetType}, in a fixed order; "
        "only those named by --only when it is given) and can (one yes or no, as true or false, for each of read, update and delete and the other operations that "
        "are allowed; those named by --only when it is given).",
        handler=run_permissions,
    ),
    Command(
        name="restrictions",
        group=GROUP,
        summary="Show the restriction on content and who is granted access",
        when="Use to see whether a page, blog post, folder, whiteboard or database is restricted (OPEN, EDIT_RESTRICTED or VIEW_RESTRICTED) and how many users and "
        "groups may read or update it. Who they are is shown only with --with-users. Not for what this account may do: that is `permissions`.",
        description="Shows the restriction that is set on the content itself and its direct permissions. The counts of users and groups per operation (read, update) "
        "are always shown; the account ids of the users, the ids of the groups and who set the restriction only with --with-users, one piece at a time (--limit, "
        "--cursor) or all of it (--all). A restriction that a parent page or folder sets is not in these calls, so OPEN does not mean that everybody may read it. "
        "A smart link, comment or attachment has no restriction of its own: the command says so.",
        args=(
            Arg(
                ("ref",),
                "Id of a page, blog post, folder, whiteboard or database, or its address as copied from the browser.",
                required=True,
                metavar="ID",
                not_a_path=ID_NOT_A_PATH,
            ),
            WITH_USERS,
            LIMIT,
            CURSOR,
            ALL,
            SELECT,
            FORMAT,
        ),
        examples=(
            Example("conflu restrictions 123456", "the state and how many users and groups hold read and update"),
            Example("conflu restrictions 123456 --with-users --json", "and who they are"),
            Example("conflu restrictions 123456 --with-users --all --select operation,principalType,principalId --format tsv", "the principals as rows"),
        ),
        notes=(
            NOT_CHANGED,
            "`conflu users lookup ACCOUNT_ID --with-users` says who an account id is. A group is shown by its id: naming it would need a call that v2 does not have.",
        ),
        json_output=True,
        output="target ({id, type, key, title}), state (OPEN, EDIT_RESTRICTED or VIEW_RESTRICTED), meaning, createdAt and createdBy (null for OPEN; createdBy only with "
        "--with-users), counts ({read: {user, group}, update: {user, group}}, of all the direct permissions), total, usersShown, count (principals in this answer; null "
        "without --with-users), nextCursor, truncated (the lists were cut and the counts are of what was read), permissions[] ({operation, principalType, "
        "principalId, createdAt, createdBy}; null without --with-users; with --select only those keys) and notes[].",
        handler=run_restrictions,
    ),
    Command(
        name="space-access",
        group=GROUP,
        summary="Show who may use a space",
        when="Use to see how a space gives access (permissions or roles) and how many users, groups and roles hold what. Who they are is shown only with --with-users. "
        "Not for what this account may do: that is `permissions`.",
        description="Reads the role mode of the site (PRE_ROLES: permission assignments, ROLES: role assignments, ROLES_TRANSITION: both), then what that mode "
        "needs: who may do what in the space, or who has which role (by the name of the role). The counts of users, groups and roles or access classes are always "
        "shown; the account ids, the ids of groups and the roles they hold only with --with-users, one piece at a time (--limit, --cursor) or all of it (--all). "
        "A site without space roles has permission assignments only.",
        args=(
            Arg(("space",), "Key of the space. Default: the current space (`conflu use`).", metavar="SPACE"),
            WITH_USERS_OF_A_SPACE,
            LIMIT,
            CURSOR,
            ALL,
            SELECT,
            FORMAT,
        ),
        examples=(
            Example("conflu space-access ENG", "the role mode and how many users, groups and roles hold what"),
            Example("conflu space-access ENG --with-users --all --json", "and who they are"),
            Example("conflu space-access ENG --with-users --select principalType,principalId,roleName --format md", "the principals as a Markdown table"),
        ),
        notes=(
            NOT_CHANGED,
            "An access class is a kind of audience that is no single person (for example everybody who has an account); it is listed with the principals, so that one switch decides.",
        ),
        json_output=True,
        output="target ({id, type: space, key, title}), mode (null when the site does not report one), models (permissions, roles: what was read), permissionTotal and "
        "permissionCounts[] ({operation, targetType, user, group, role}), roleTotal and roleCounts[] ({roleId, name, type, user, group, accessClass}) (each null when its "
        "model was not read), usersShown, total, count (principals in this answer; null without --with-users), nextCursor, truncated, principals[] ({model, "
        "principalType, principalId, operation, targetType, roleId, roleName}; null without --with-users; with --select only those keys) and notes[].",
        handler=run_space_access,
    ),
)
