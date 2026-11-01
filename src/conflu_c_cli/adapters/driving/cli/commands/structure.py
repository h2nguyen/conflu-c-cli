"""Commands about where content sits and what is in the tree besides pages: tree, move; folder, whiteboard, database, smartlink; folder-create, smartlink-create."""
from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from .....application.paging import ensure_users_allowed
from .....application.structure import LISTINGS
from .....domain.content import noun_of, point_at
from .....domain.errors import UsageError
from .....domain.model import PageRef, VersionInfo
from .....domain.privacy import redact_address, redact_text
from ..listing import FORMAT, SELECT, print_list
from ..render import key_values, one_line, table
from ..runtime import Context
from ..spec import Arg, Command, Example, Handler
from ._common import LIMIT_HELP, check_limit, pretty, shortened, user_json, user_name
from .changes import DRY_RUN, SINCE, write_json, write_text

if TYPE_CHECKING:
    from .....application.structure import ContainerView, ContainerWrite
    from .....application.writing import PageWrite

GROUP = "Read"
WORK = "Work on a page"
STRUCTURE = "Structure"
NODE_COLUMNS = [("ID", "id"), ("TITLE", "title"), ("TYPE", "type"), ("PARENT", "parentId"), ("DEPTH", "depth"), ("STATUS", "status")]
CHILD_COLUMNS = [("ID", "id"), ("TYPE", "type"), ("TITLE", "title"), ("STATUS", "status")]
FIELD_COLUMNS = [("ID", "id"), ("NAME", "name"), ("TYPE", "type"), ("OPTIONS", "options")]
VIEW_COLUMNS = [("ID", "id"), ("NAME", "name"), ("TYPE", "type")]
EMPTY = {"children": "(nothing below this one)", "fields": "(no fields)", "views": "(no views)", "entries": "(no entries)"}

CURSOR = Arg(("--cursor",), "Continue after the end of the previous answer: pass its nextCursor (with the same --limit).", metavar="TOKEN")
ALL = Arg(("--all",), "Fetch every page of the list instead of one (ignores --limit and --cursor).", kind="flag")
LIMIT = Arg(("--limit",), LIMIT_HELP, kind="int", default=25, metavar="N")
WITH_USERS = Arg(
    ("--with-users",),
    "Show people: the author, the owner and who saved the version, and for a database the people in its cells. Refused when CONFLUENCE_HIDE_USERS=true.",
    kind="flag",
)
ANCESTORS = Arg(("--ancestors",), "Also show every ancestor, from the top of the space down to the parent.", kind="flag")
IF_VERSION = Arg(("--if-version",), "Refuse (exit code 3) unless the page is at this version now.", kind="int", metavar="N")
MOVE_WITH_USERS = Arg(
    ("--with-users",),
    "Show the request of a move that saves the page exactly as it is sent, with the people (mentions) and the addresses that the page body holds. Refused when CONFLUENCE_HIDE_USERS=true.",
    kind="flag",
)
PARENT_NOT_A_PATH = "a page, folder or other content of Confluence, named by its id or address"


# -- tree ----------------------------------------------------------------------------------------


def run_tree(ctx: Context, args: argparse.Namespace) -> int:
    result = ctx.app.tree_pages.execute(args.ref, depth=args.depth, space=args.space)
    rows = [{"id": n.id, "title": n.title, "type": n.type, "parentId": n.parent_id or None, "depth": n.depth, "status": n.status} for n in result.nodes]
    document = {
        "root": {"id": result.root.id, "title": result.root.title, "type": result.root.type, "spaceKey": result.space_key},
        "depth": result.depth,
        "count": len(result.nodes),
        "truncated": result.truncated,
        "nodes": rows,
    }

    def text() -> str:
        root = result.root
        lines = [f"{one_line(root.title)}  [{root.id}]" + ("" if root.type == "page" else f" ({root.type})")]
        for node in result.nodes:
            kind = "" if node.type == "page" else f" ({node.type})"
            lines.append(f"{'  ' * max(node.depth, 1)}{one_line(node.title)}  [{node.id}]{kind}")
        if not result.nodes:
            lines.append("  (no pages below this one)" if root.type == "page" else "  (nothing below this one)")
        return "\n".join(lines)

    if print_list(ctx, args, payload=document, rows=rows, list_key="nodes", columns=NODE_COLUMNS, plain=text):
        return 0
    if result.truncated:
        ctx.diagnostics.warn("The tree was cut short at its limit; start from a page or a folder further down.")
    return 0


# -- move ----------------------------------------------------------------------------------------


def ref_json(ref: PageRef | None) -> dict[str, Any] | None:
    return None if ref is None else {"id": ref.id, "type": ref.type, "title": ref.title}


def move_json(result: PageWrite, with_users: bool = False) -> dict[str, Any]:
    return {
        **write_json(result, with_users),
        "payloadRedacted": result.redacted,
        "target": ref_json(result.where),
        "confirmed": result.confirmed,
        "message": result.message or None,
    }


def move_text(result: PageWrite, with_users: bool = False) -> str:
    where = result.where
    if where is None or where.type == "page":  # below, before or after a page: the text that it always was
        return write_text(result, with_users)
    page = result.page
    page_id = page.id if page else ""
    title = (page.title if with_users else redact_text(page.title)) if page else ""  # what Confluence answers can hold an e-mail address
    address = (page.url if with_users else redact_address(page.url)) if page else ""  # and so can the title in the address, or the key of a personal space
    below = point_at(where.type, where.id, where.title)
    if result.action == "unchanged":
        return f"Nothing to change: page {page_id} is already below {below}."
    if result.dry_run:
        text = (
            f"Dry run: page {page_id} '{one_line(title)}' would be moved below {below}. The move saves a new version of the page "
            f"(version {result.version_from} to {result.version_to}); nothing was sent\n"
            "If somebody has an unpublished draft of the page, Confluence merges this body into it and, when the two differ much, may replace the draft.\n"
            f"{pretty(shortened(result.payload))}"
        )
        if result.redacted:
            text += "\nThe body is shown without the people and addresses that it holds; the request has them. --with-users shows it as it is."
        return text
    return f"Moved page {page_id}: {title} below {below} (version {result.version_from} -> {result.version_to})" + (f"\n{address}" if address else "")


def run_move(ctx: Context, args: argparse.Namespace) -> int:
    ensure_users_allowed(args.with_users, ctx.app.settings)
    result = ctx.app.move_page.execute(
        args.ref,
        args.to,
        position=args.position,
        dry_run=args.dry_run,
        if_version=args.if_version,
        if_unchanged_since=args.if_unchanged_since,  # None when absent: one that is empty is a mistake, never "no guard"
        with_users=args.with_users,
    )
    ctx.print_json(move_json(result, args.with_users)) if ctx.json_mode else ctx.print(move_text(result, args.with_users))
    if result.message:  # the move is made; what could not be confirmed is said on stderr, and the exit code stays 0
        ctx.diagnostics.warn(result.message)
    return 0


# -- folder, whiteboard, database, smartlink ------------------------------------------------------


def _version_json(version: VersionInfo | None) -> dict[str, Any] | None:
    if version is None:
        return None
    return {"number": version.number, "created": version.created, "message": version.message, "minorEdit": version.minor_edit, "author": user_json(version.author)}


def _row_json(listing: str, item: Any) -> dict[str, Any]:
    if listing == "children":
        return {"id": item.id, "type": item.type, "title": item.title, "status": item.status, "position": item.position}
    if listing == "fields":
        return {"id": item.id, "name": item.name, "type": item.type, "description": item.description or None, "options": list(item.options)}
    if listing == "views":
        return {"id": item.id, "name": item.name, "type": item.type}
    return {"id": item.id, "values": item.values}


def _text_of(value: Any) -> str:
    """One cell of an entry as a person reads it in a table."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(_text_of(item) for item in value)
    if isinstance(value, dict):
        if "url" in value:
            return f"{value['label']} <{value['url']}>" if value.get("label") else str(value["url"])
        return str(value.get("displayName") or value.get("accountId") or "")
    return str(value)


def container_json(view: ContainerView) -> dict[str, Any]:
    c = view.container
    data: dict[str, Any] = {
        "id": c.id,
        "type": c.type,
        "title": c.title,
        "status": c.status,
        "spaceId": c.space_id,
        "spaceKey": c.space_key or None,
        "parentId": c.parent_id or None,
        "parentType": c.parent_type or None,
        "position": c.position,
        "url": c.url,
        "version": _version_json(c.version),
        "created": c.created,
        "updated": c.updated,
        "author": user_json(c.author),
        "owner": user_json(c.owner),
    }
    if c.type == "embed":
        data["embedUrl"] = c.embed_url or None
    if view.ancestors is not None:
        data["ancestors"] = [ref_json(ref) for ref in view.ancestors]
    if view.listing:
        data["count"] = len(view.items)
        data["nextCursor"] = view.next_cursor or None
        data["truncated"] = view.truncated
        if view.listing == "entries":
            data["columns"] = [{"id": item.id, "name": item.name, "type": item.type} for item in view.columns]
        data[view.listing] = [_row_json(view.listing, item) for item in view.items]
    return data


def _list_text(view: ContainerView) -> str:
    if not view.items:
        return EMPTY[view.listing]
    if view.listing == "children":
        return table(["ID", "TYPE", "TITLE", "STATUS"], [(n.id, n.type, n.title, n.status) for n in view.items])
    if view.listing == "fields":
        return table(["ID", "NAME", "TYPE", "OPTIONS"], [(f.id, f.name, f.type, ", ".join(f.options)) for f in view.items])
    if view.listing == "views":
        return table(["ID", "NAME", "TYPE"], [(v.id, v.name, v.type) for v in view.items])
    headers = ["ID", *[column.name for column in view.columns]]
    return table(headers, [[row.id, *[_text_of(row.values.get(column.id)) for column in view.columns]] for row in view.items])


def container_text(view: ContainerView) -> str:
    c = view.container
    pairs: list[tuple[str, Any]] = [
        ("Type", noun_of(c.type)),
        ("Space", c.space_key),
        ("Status", c.status),
        ("Version", c.version_number or ""),
        ("Parent", f"{c.parent_id} ({c.parent_type})" if c.parent_id and c.parent_type else c.parent_id),
        ("Address", c.embed_url),
    ]
    if view.ancestors:
        pairs.append(("Path", " > ".join([item.title or item.id for item in view.ancestors] + [c.title])))
    elif view.ancestors is not None:
        pairs.append(("Path", "(at the top of the space)"))
    if c.type == "whiteboard":
        pairs.append(("Content", "the REST API has no call that returns what a whiteboard shows"))
    pairs += [("Created", c.created), ("Updated", c.updated)]
    if view.users_shown:
        pairs += [("Author", user_name(c.author)), ("Owner", user_name(c.owner)), ("Saved by", user_name(c.version.author if c.version else None))]
    lines = [f"{c.title}  [{c.id}]", c.url, "", key_values(pairs), ""]
    if view.listing:
        lines.append(_list_text(view))
    elif c.type == "database":
        lines.append("Below it, its fields, its views and its entries: --children, --fields, --views, --entries (one at a time).")
    else:
        lines.append("Below it: show what is there with --children.")
    return "\n".join(lines)


def _columns(view: ContainerView) -> list[tuple[str, str]]:
    if view.listing == "children":
        return CHILD_COLUMNS
    if view.listing == "fields":
        return FIELD_COLUMNS
    if view.listing == "views":
        return VIEW_COLUMNS
    return [("ID", "id"), *[(column.name, f"values.{column.id}") for column in view.columns]]


def run_container(ctx: Context, args: argparse.Namespace, kind: str) -> int:
    chosen = [name for name in LISTINGS if getattr(args, name, False)]
    if len(chosen) > 1:
        raise UsageError(
            f"Ask for one list at a time: {', '.join('--' + name for name in chosen)} are too many together.",
            hint="Run the command once for each list; --ancestors can go with any of them.",
        )
    listing = chosen[0] if chosen else ""
    if listing:
        check_limit(args.limit)
    elif args.cursor or args.all or args.select or args.format != "table":
        raise UsageError(
            "--cursor, --all, --select and --format work on a list, and none was asked for.",
            hint="Add --children (a database also has --fields, --views and --entries).",
        )
    view = ctx.app.structure.show.execute(
        kind,
        args.ref,
        listing=listing,
        ancestors=args.ancestors,
        limit=args.limit,
        cursor=args.cursor or "",
        fetch_everything=args.all,
        with_users=args.with_users,
    )
    document = container_json(view)
    if not listing:
        ctx.print_json(document) if ctx.json_mode else ctx.print(container_text(view))
        return 0
    rows = document[listing]
    if print_list(ctx, args, payload=document, rows=rows, list_key=listing, columns=_columns(view), plain=lambda: container_text(view)):
        return 0
    if view.next_cursor:
        ctx.diagnostics.info(f"More {listing} follow. Continue with --cursor {view.next_cursor} (and the same --limit), or use --all.")
    if view.truncated:
        ctx.diagnostics.warn(f"The list of {listing} was cut short at its limit.")
    return 0


def _runner(kind: str) -> Handler:
    def run(ctx: Context, args: argparse.Namespace) -> int:
        return run_container(ctx, args, kind)

    return run


def _show_args(kind: str, what: str, *lists: Arg) -> tuple[Arg, ...]:
    return (
        Arg(("ref",), f"Id of the {what}, or its address as copied from the browser.", required=True, metavar=kind.upper(), not_a_path=f"the id of {what} in Confluence"),
        *lists,
        ANCESTORS,
        WITH_USERS,
        LIMIT,
        CURSOR,
        ALL,
        SELECT,
        FORMAT,
    )


CHILDREN = Arg(("--children",), "List what sits directly below it, in the order of the tree.", kind="flag")


# -- folder-create and smartlink-create ----------------------------------------------------------


def writer_json(result: ContainerWrite, id_key: str) -> dict[str, Any]:
    made = result.container
    data: dict[str, Any] = {
        "action": result.action,
        "dryRun": result.dry_run,
        id_key: made.id if made else None,
        "title": redact_text(made.title if made else result.title),
        "spaceKey": result.space_key,
        "url": (redact_address(made.url) or None) if made else None,
    }
    if "embedUrl" in result.payload:
        data["embedUrl"] = result.payload["embedUrl"]
    data["parentId"] = result.parent.id if result.parent else None
    data["parentType"] = result.parent.type if result.parent else None
    data["parent"] = ref_json(result.parent)
    data["payload"] = result.payload
    return data


def writer_text(result: ContainerWrite) -> str:
    what = noun_of(result.type)
    below = f" below {point_at(result.parent.type, result.parent.id, result.parent.title)}" if result.parent else ""
    if result.dry_run:
        return f"Dry run: a {what} would be created{below}; nothing was sent\n{pretty(result.payload)}"
    made = result.container
    title = redact_text(made.title if made else result.title)  # what Confluence answers can hold an e-mail address
    return f"Created {what} {made.id if made else ''}: {title}{below}" + (f"\n{redact_address(made.url)}" if made and made.url else "")


def run_folder_create(ctx: Context, args: argparse.Namespace) -> int:
    result = ctx.app.structure.create_folder.execute(args.title, space=args.space, parent=args.parent, dry_run=args.dry_run)
    ctx.print_json(writer_json(result, "folderId")) if ctx.json_mode else ctx.print(writer_text(result))
    return 0


def run_smartlink_create(ctx: Context, args: argparse.Namespace) -> int:
    result = ctx.app.structure.create_smartlink.execute(args.title, url=args.url, space=args.space, parent=args.parent, dry_run=args.dry_run)
    ctx.print_json(writer_json(result, "smartlinkId")) if ctx.json_mode else ctx.print(writer_text(result))
    return 0


SPACE = Arg(("--space",), "Space key. Default: the current space.", metavar="KEY")
PARENT = Arg(
    ("--parent",),
    "The page, folder, whiteboard, database or smart link of the space to create it below (id or address). Default: none is named.",
    metavar="ID",
    not_a_path=PARENT_NOT_A_PATH,
)

CONTAINER_OUTPUT = (
    "id, type, title, status, spaceId, spaceKey, parentId, parentType, position, url, version{number,created,message,minorEdit,author}, created, updated, "
    "author and owner (null unless --with-users), ancestors[]: id, type, title (with --ancestors); in a personal space spaceKey and the key in url are [hidden] unless --with-users"
)
LIST_OUTPUT = "; with a list also count, nextCursor (null on the last page), truncated and the list, of which --select keeps some keys"


COMMANDS = (
    Command(
        name="tree",
        group=GROUP,
        summary="Show what is below a page or a folder",
        when="Use to see how a topic is organised: the pages, folders, whiteboards, databases and smart links below a page or a folder. Also a way to find related pages after `search` has found one.",
        description="Shows the descendants of a page, or of a folder, a whiteboard, a database or a smart link, as a tree, down to --depth levels (1 to 10). "
        "Anything that is no page is listed with its type.",
        args=(
            Arg(
                ("ref",),
                "Page id, the address of the page, a `page:KEY/Title` reference, or the id or address of a folder, whiteboard, database or smart link.",
                required=True,
                metavar="PAGE",
                not_a_path=PARENT_NOT_A_PATH,
            ),
            Arg(("--depth",), "Levels to show (1 to 10).", kind="int", default=3, metavar="N"),
            Arg(("--space",), "The space of a `page:Title` reference. Default: the current space, else the whole site.", metavar="KEY"),
            SELECT,
            FORMAT,
        ),
        examples=(
            Example("conflu tree 123456"),
            Example("conflu tree 123456 --depth 10 --json"),
            Example("conflu tree 7001 --depth 2", "everything below a folder"),
            Example("conflu tree 'page:ENG/Our Products' --depth 2"),
            Example("conflu tree 123456 --depth 5 --select id,title,depth --format tsv", "the tree as flat rows"),
        ),
        json_output=True,
        output="root{id,title,type,spaceKey ([hidden] in a personal space)}, depth, count, truncated and nodes[] in reading order: id, title, type, parentId, depth, status; "
        "with --select only those (dotted) keys of every node.",
        handler=run_tree,
    ),
    Command(
        name="move",
        group=WORK,
        summary="Move a page below, before or after another page, or below a folder",
        when="Use to move one page below, before or after another page, or below a folder. Preview with --dry-run.",
        description="With the default position `append` the page becomes the last child of the target; `before` and `after` put it next to "
        "the target, under the target's parent. The target may also be a folder, a whiteboard, a database or a smart link: then only `append` is "
        "possible, and the page is saved again with its body untouched, as the next version, below the new parent (a version message says "
        "`Moved below ...`; Confluence merges a save into an unpublished draft of the page, if somebody has one); a page that is below it already "
        "is left as it is. A folder, a whiteboard, a database or a smart link cannot be moved: "
        "the API has no call for it.",
        args=(
            Arg(("ref",), "Page id, or the address of the page to move.", required=True, metavar="PAGE"),
            Arg(
                ("--to",),
                "The page, folder, whiteboard, database or smart link to move it to (id or address).",
                required=True,
                metavar="TARGET",
                not_a_path=PARENT_NOT_A_PATH,
            ),
            Arg(
                ("--position",),
                "Where, relative to the target. Only append is possible when the target is no page; before and after are refused for a page at the top level of its space (the home page, for one).",
                kind="choice",
                choices=("append", "before", "after"),
                default="append",
            ),
            IF_VERSION,
            SINCE,
            MOVE_WITH_USERS,
            DRY_RUN,
        ),
        examples=(
            Example("conflu move 123456 --to 654321 --dry-run"),
            Example("conflu move 123456 --to 654321 --position before"),
            Example("conflu move 123456 --to 7001 --dry-run", "below a folder: it saves a new version of the page"),
        ),
        writes=True,
        json_output=True,
        output="action (moved, or unchanged for a page that is below the folder already), dryRun, pageId, title, url (redacted like every address unless --with-users: cut at the id when the title in it holds an address, and the address by id alone in a personal space), versionFrom, versionTo, lost[], labels[], "
        "payload (what is sent: pageId, position and targetId for a page as the target; the whole request, with the body, below a folder), "
        "payloadRedacted (true when that body is shown without the people and addresses in it; --with-users shows it as it is), target{id,type,title}, "
        "confirmed (the page, as Confluence answers after the move, is below the new parent; false when it is not; null for a dry run, a page that did not move, "
        "and a move that could not be read back, which is no failure) and message (null unless the move could not be confirmed).",
        destructive=True,
        idempotent=True,
        handler=run_move,
    ),
    Command(
        name="folder",
        group=STRUCTURE,
        summary="Show one folder",
        when="Use to see a folder, what sits directly below it (--children) and the path to it (--ancestors). A folder id is in its address; no call lists the folders of a space.",
        description="Shows the title, space, status, version, position and parent of a folder; a folder has no text of its own. People are hidden unless you add "
        "--with-users. Pages go below a folder with `create --parent`; `tree` shows everything below it.",
        args=_show_args("FOLDER", "folder", CHILDREN),
        examples=(
            Example("conflu folder 7001"),
            Example("conflu folder 7001 --children --json"),
            Example("conflu folder 7001 --children --select id,type,title --format tsv", "the children as flat rows"),
            Example("conflu folder 7001 --ancestors"),
        ),
        json_output=True,
        output=CONTAINER_OUTPUT + ", children[]: id, type, title, status, position (with --children)" + LIST_OUTPUT + ".",
        handler=_runner("folder"),
    ),
    Command(
        name="whiteboard",
        group=STRUCTURE,
        summary="Show one whiteboard",
        when="Use to see where a whiteboard sits and what is below it. Its drawing cannot be read: the REST API has no call that returns the content of a whiteboard.",
        description="Shows the title, space, status, version, position and parent of a whiteboard. People are hidden unless you add --with-users.",
        args=_show_args("WHITEBOARD", "whiteboard", CHILDREN),
        examples=(Example("conflu whiteboard 7021"), Example("conflu whiteboard 7021 --ancestors --json")),
        json_output=True,
        output=CONTAINER_OUTPUT + ", children[]: id, type, title, status, position (with --children)" + LIST_OUTPUT + ".",
        handler=_runner("whiteboard"),
    ),
    Command(
        name="database",
        group=STRUCTURE,
        summary="Show one database",
        when="Use to see a database and, one list at a time, its --fields, --views or --entries. Atlassian marks the API for the entries as experimental.",
        description="Shows the title, space, status, version, position and parent of a database. --entries gives every entry with the value of each field, keyed by "
        "the id of the field, and `columns` that name the fields. Text in a cell has e-mail addresses and personal links redacted, and the people in a cell "
        "are `[hidden]` unless you add --with-users.",
        args=_show_args(
            "DATABASE",
            "database",
            CHILDREN,
            Arg(("--fields",), "List the fields of the database.", kind="flag"),
            Arg(("--views",), "List the views of the database.", kind="flag"),
            Arg(("--entries",), "List the entries of the database, with the value of every field.", kind="flag"),
        ),
        examples=(
            Example("conflu database 7041"),
            Example("conflu database 7041 --fields"),
            Example("conflu database 7041 --entries --limit 50 --json"),
            Example("conflu database 7041 --entries --all --select id,values --format tsv", "all entries as flat rows"),
        ),
        notes=("The cursor of a list belongs to the --limit that made it: continue with the same one, or use --all.",),
        json_output=True,
        output=CONTAINER_OUTPUT + ", children[]: id, type, title, status, position (with --children), fields[]: id, name, type, description, options[] (with --fields), "
        "views[]: id, name, type (with --views), columns[]: id, name, type and entries[]: id, values{field id: value} (with --entries)" + LIST_OUTPUT + ".",
        handler=_runner("database"),
    ),
    Command(
        name="smartlink",
        group=STRUCTURE,
        summary="Show one smart link",
        when="Use to see where a smart link sits and the address it shows.",
        description="Shows the title, space, status, version, position and parent of a smart link, and its address (`embedUrl`). People and personal links are hidden "
        "unless you add --with-users.",
        args=_show_args("SMARTLINK", "smart link", CHILDREN),
        examples=(Example("conflu smartlink 7061"), Example("conflu smartlink 7061 --json")),
        json_output=True,
        output=CONTAINER_OUTPUT + ", embedUrl (null when it shows no address), children[]: id, type, title, status, position (with --children)" + LIST_OUTPUT + ".",
        handler=_runner("embed"),
    ),
    Command(
        name="folder-create",
        group=STRUCTURE,
        summary="Create a folder",
        when="Use to make a folder to publish pages below (`create --parent FOLDER`). Preview with --dry-run; a title need not be unique.",
        description="Creates a folder in a space: below --parent (a page, folder, whiteboard, database or smart link of that space), or with no parent named. "
        "Confluence does not forbid two folders with one title, and no call lists the folders of a space, so the dry run cannot say whether the title is taken. "
        "The new id is printed; it is what `create --parent` and `import-md --parent` take. A folder is never renamed, moved or deleted by this command.",
        args=(
            Arg(("--title",), "The title: one line, at most 255 characters.", required=True, metavar="TEXT"),
            SPACE,
            PARENT,
            DRY_RUN,
        ),
        examples=(
            Example("conflu folder-create --title Guides --space ENG --dry-run"),
            Example("conflu folder-create --space ENG --title Runbooks --parent 7001 --json"),
        ),
        notes=("Read the id of the new folder from `--json` (`folderId`); never guess it.",),
        writes=True,
        json_output=True,
        output="action (created), dryRun, folderId (null in a dry run), title, spaceKey, url (null in a dry run), parentId, parentType, parent{id,type,title} "
        "(null without --parent) and payload (exactly what is sent).",
        handler=run_folder_create,
    ),
    Command(
        name="smartlink-create",
        group=STRUCTURE,
        summary="Create a smart link",
        when="Use to put a smart link, a link to an address, into the tree of a space. Preview with --dry-run.",
        description="Creates a smart link in a space: below --parent (a page, folder, whiteboard, database or smart link of that space), or with no parent named. "
        "The address must be http or https without a user name or password, at most 2048 characters, and without a blank or a control character; it is shown "
        "as it was given. Confluence does not forbid two smart links with one title. The new id is printed. A smart link is never renamed, moved or deleted by "
        "this command.",
        args=(
            Arg(("--url",), "The address that the smart link shows: http or https, at most 2048 characters.", required=True, metavar="URL"),
            Arg(("--title",), "The title: one line, at most 255 characters.", required=True, metavar="TEXT"),
            SPACE,
            PARENT,
            DRY_RUN,
        ),
        examples=(
            Example("conflu smartlink-create --url https://example.com/roadmap --title Roadmap --space ENG --dry-run"),
            Example("conflu smartlink-create --url https://example.com/roadmap --title Roadmap --space ENG --parent 7001 --json"),
        ),
        notes=("Read the id of the new smart link from `--json` (`smartlinkId`); never guess it.",),
        writes=True,
        json_output=True,
        output="action (created), dryRun, smartlinkId (null in a dry run), title, spaceKey, url (null in a dry run), embedUrl, parentId, parentType, "
        "parent{id,type,title} (null without --parent) and payload (exactly what is sent).",
        handler=run_smartlink_create,
    ),
)
