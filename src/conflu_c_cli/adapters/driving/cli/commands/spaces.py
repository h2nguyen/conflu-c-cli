"""Commands about spaces: spaces, space."""
from __future__ import annotations

import argparse
from typing import Any

from .....application.spaces import SPACE_STATUSES, SPACE_TYPES
from .....domain.model import Space
from ..listing import FORMAT, SELECT, print_list
from ..render import key_values, table
from ..runtime import Context
from ..spec import Arg, Command, Example
from ._common import LIMIT_HELP, check_limit

GROUP = "Spaces"
SPACE_COLUMNS = [("KEY", "key"), ("NAME", "name"), ("TYPE", "type"), ("STATUS", "status"), ("HOMEPAGE", "homepageId")]
PERSONAL = (
    "A personal space is named after its owner and keyed by the owner's account id, so it comes out as an entry with the key [hidden], the name [personal space] "
    "and no description or address (its id, type, status, home page and date stay)"
)
WITH_USERS = Arg(
    ("--with-users",),
    "Show personal spaces as Confluence names them (the key is the account id of the owner, the name is the owner's), and the names and descriptions of "
    "other spaces as they are. Refused when CONFLUENCE_HIDE_USERS=true.",
    kind="flag",
)


def space_json(space: Space) -> dict[str, Any]:
    return {
        "id": space.id,
        "key": space.key,
        "name": space.name,
        "type": space.type,
        "status": space.status,
        "homepageId": space.homepage_id or None,
        "description": space.description,
        "created": space.created,
        "url": space.url,
    }


def run_spaces(ctx: Context, args: argparse.Namespace) -> int:
    check_limit(args.limit)
    result = ctx.app.list_spaces.execute(
        space_type=args.type or "",
        status=args.status,
        search=args.search or "",
        limit=args.limit,
        cursor=args.cursor or "",
        fetch_everything=args.all,
        with_users=args.with_users,
    )
    rows = [space_json(space) for space in result.spaces]
    document = {"count": len(result.spaces), "nextCursor": result.next_cursor or None, "truncated": result.truncated, "spaces": rows}

    def text() -> str:
        if not result.spaces:
            return "No spaces."
        return table(["KEY", "NAME", "TYPE", "STATUS", "HOMEPAGE"], [(s.key, s.name, s.type, s.status, s.homepage_id) for s in result.spaces])

    if print_list(ctx, args, payload=document, rows=rows, list_key="spaces", columns=SPACE_COLUMNS, plain=text) or not result.spaces:
        return 0
    if result.next_cursor:
        ctx.diagnostics.info(f"More spaces follow. Continue with --cursor {result.next_cursor}, or use --all.")
    return 0


def run_space(ctx: Context, args: argparse.Namespace) -> int:
    space = ctx.app.show_space.execute(args.key or "", with_users=args.with_users)
    if ctx.json_mode:
        ctx.print_json(space_json(space))
        return 0
    pairs = [("Name", space.name), ("Type", space.type), ("Status", space.status), ("Id", space.id), ("Home page", space.homepage_id), ("Created", space.created), ("Address", space.url)]
    lines = [f"{space.key}", key_values(pairs)]
    if space.description.strip():
        lines += ["", space.description.strip()]
    ctx.print("\n".join(lines))
    return 0


COMMANDS = (
    Command(
        name="spaces",
        group=GROUP,
        summary="List the spaces you can see",
        when="Use to find the key of a space. A personal space is listed without its owner (key [hidden], name [personal space]) unless you add --with-users.",
        description=f"Lists the spaces that this account can see, a page of the list at a time or all of it. {PERSONAL}; --with-users shows it as Confluence names it, "
        "and is refused when CONFLUENCE_HIDE_USERS=true. E-mail addresses and personal links in the name or the description of any other space are redacted. "
        "--search looks at what is printed, so it cannot find a person's space by the name of the person.",
        args=(
            Arg(("--type",), "Only spaces of this type.", kind="choice", choices=SPACE_TYPES),
            Arg(("--status",), "Only spaces with this status.", kind="choice", choices=SPACE_STATUSES, default="current"),
            Arg(("--search",), "Only spaces whose key or name, as printed, contains this text (reads the whole list).", metavar="TEXT"),
            Arg(("--limit",), LIMIT_HELP, kind="int", default=25, metavar="N"),
            Arg(("--cursor",), "Continue after the end of the previous answer: pass its nextCursor.", metavar="TOKEN"),
            Arg(("--all",), "Fetch every page of the list instead of one (ignores --limit and --cursor).", kind="flag"),
            WITH_USERS,
            SELECT,
            FORMAT,
        ),
        examples=(
            Example("conflu spaces"),
            Example("conflu spaces --search engineering --all --json"),
            Example("conflu spaces --all --select key,name --format md", "only these columns, as a Markdown table"),
            Example("conflu spaces --type personal --with-users", "personal spaces as Confluence names them (refused when people are hidden)"),
        ),
        json_output=True,
        output="count, nextCursor, truncated and spaces[]: id, key, name, type, status, homepageId, description, created, url "
        "(a personal space has the key [hidden], the name [personal space], an empty description and an empty url unless --with-users); "
        "with --select only those (dotted) keys of every space.",
        handler=run_spaces,
    ),
    Command(
        name="space",
        group=GROUP,
        summary="Show one space",
        when="Use to see the properties of one space and the id of its home page. A personal space is shown without its owner unless you add --with-users.",
        description=f"Shows a space with its home page and description. Without a key it shows the current space (`conflu use`). {PERSONAL}; --with-users shows it "
        "as Confluence names it, and is refused when CONFLUENCE_HIDE_USERS=true.",
        args=(Arg(("key",), "Space key.", metavar="KEY"), WITH_USERS),
        examples=(Example("conflu space ENG"), Example("conflu space --json"), Example("conflu space ENG --with-users", "a personal space as Confluence names it")),
        json_output=True,
        output="id, key, name, type, status, homepageId, description, created, url (a personal space has the key [hidden], the name [personal space], "
        "an empty description and an empty url unless --with-users).",
        handler=run_space,
    ),
)
