"""Commands about spaces: spaces, space."""
from __future__ import annotations

import argparse
from typing import Any

from .....application.spaces import SPACE_STATUSES, SPACE_TYPES
from .....domain.model import Space
from ..render import key_values, table
from ..runtime import Context
from ..spec import Arg, Command, Example
from ._common import LIMIT_HELP, check_limit

GROUP = "Spaces"


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
    )
    if ctx.json_mode:
        ctx.print_json(
            {
                "count": len(result.spaces),
                "nextCursor": result.next_cursor or None,
                "truncated": result.truncated,
                "spaces": [space_json(space) for space in result.spaces],
            }
        )
        return 0
    if not result.spaces:
        ctx.print("No spaces.")
        return 0
    ctx.print(table(["KEY", "NAME", "TYPE", "STATUS", "HOMEPAGE"], [(s.key, s.name, s.type, s.status, s.homepage_id) for s in result.spaces]))
    if result.next_cursor:
        ctx.diagnostics.info(f"More spaces follow. Continue with --cursor {result.next_cursor}, or use --all.")
    return 0


def run_space(ctx: Context, args: argparse.Namespace) -> int:
    space = ctx.app.show_space.execute(args.key or "")
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
        when="Use to find the key of a space.",
        args=(
            Arg(("--type",), "Only spaces of this type.", kind="choice", choices=SPACE_TYPES),
            Arg(("--status",), "Only spaces with this status.", kind="choice", choices=SPACE_STATUSES, default="current"),
            Arg(("--search",), "Only spaces whose key or name contains this text (reads the whole list).", metavar="TEXT"),
            Arg(("--limit",), LIMIT_HELP, kind="int", default=25, metavar="N"),
            Arg(("--cursor",), "Continue after the end of the previous answer: pass its nextCursor.", metavar="TOKEN"),
            Arg(("--all",), "Fetch every page of the list instead of one (ignores --limit and --cursor).", kind="flag"),
        ),
        examples=(Example("conflu spaces"), Example("conflu spaces --search engineering --all --json")),
        json_output=True,
        output="count, nextCursor, truncated and spaces[]: id, key, name, type, status, homepageId, description, created, url.",
        handler=run_spaces,
    ),
    Command(
        name="space",
        group=GROUP,
        summary="Show one space",
        when="Use to see the properties of one space and the id of its home page.",
        description="Shows a space with its home page and description. Without a key it shows the current space (`conflu use`).",
        args=(Arg(("key",), "Space key.", metavar="KEY"),),
        examples=(Example("conflu space ENG"), Example("conflu space --json")),
        json_output=True,
        output="id, key, name, type, status, homepageId, description, created, url.",
        handler=run_space,
    ),
)
