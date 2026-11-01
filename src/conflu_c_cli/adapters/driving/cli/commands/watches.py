"""Commands about the watches of the user on pages and spaces: watching, watch."""
from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from .....domain.content import point_at
from .....domain.watches import SPACE, WatchTarget
from ..render import one_line
from ..runtime import Context
from ..spec import Arg, Command, Example

if TYPE_CHECKING:
    from .....application.watches import WatchResult, WatchState

GROUP = "Access and people"

PAGE = Arg(
    ("ref",),
    "Page id, or the address of the page; for a blog post or other content its id. Leave it out to name a space with --space.",
    metavar="PAGE",
)


def target_json(target: WatchTarget) -> dict[str, Any]:
    """What is watched: `key` and `title` are those of a space as `conflu spaces` prints them and null for content (the kind is `type`)."""
    return {"id": target.id, "type": target.type, "key": target.shown_key or None, "title": target.title or None}


def named(target: WatchTarget) -> str:
    """How a message names it: `the page [2002]`, `the space ENG (Engineering)`, `the space [hidden] ([personal space])`."""
    if target.scope == SPACE:
        title = one_line(target.title)
        return f"the space {target.shown_key}" + (f" ({title})" if title else "")
    return point_at(target.type, target.id)


# -- watching ------------------------------------------------------------------------------------


def watching_text(state: WatchState) -> str:
    return f"You {'watch' if state.watching else 'do not watch'} {named(state.target)}."


def run_watching(ctx: Context, args: argparse.Namespace) -> int:
    state = ctx.app.watches.watching.execute(args.ref or "", space=args.space or "")
    if ctx.json_mode:
        ctx.print_json({"target": target_json(state.target), "watching": state.watching})
    else:
        ctx.print(watching_text(state))
    return 0


# -- watch ---------------------------------------------------------------------------------------


def watch_json(result: WatchResult) -> dict[str, Any]:
    return {
        "action": result.action,
        "dryRun": result.dry_run,
        "target": target_json(result.target),
        "wasWatching": result.was_watching,
        "watching": result.watching,
        "confirmed": result.confirmed,
        "call": result.change.call if result.change else None,
        "message": result.message or None,
    }


def watch_text(result: WatchResult) -> str:
    what = named(result.target)
    if result.action == "unchanged":
        return f"Nothing to change: you watch {what} already." if result.was_watching else f"Nothing to change: you do not watch {what}."
    starting = result.action == "watched"
    if result.dry_run:
        call = result.change.call if result.change else ""
        return f"Dry run: you would {'start' if starting else 'stop'} watching {what}; nothing was sent\nCall: {call}"
    text = f"{'Now watching' if starting else 'Stopped watching'} {what}."
    if result.confirmed is None:
        return text + " The change was made, but reading the status back failed (see the warning)."
    if not result.confirmed:
        return text + " Confluence does not show the change yet (see the warning)."
    return text


def run_watch(ctx: Context, args: argparse.Namespace) -> int:
    result = ctx.app.watches.watch.execute(args.ref or "", space=args.space or "", remove=args.remove, dry_run=args.dry_run)
    ctx.print_json(watch_json(result)) if ctx.json_mode else ctx.print(watch_text(result))
    return 0


TARGET_JSON = (
    "target{id,type,key,title}: type is what Confluence calls the content (page, blogpost, folder ...) or space; key and title are set for a space "
    "only, as `conflu spaces` prints them: the title redacted like every title, and for a personal space (it is named after its owner) the key [hidden] "
    "and the title [personal space]"
)

COMMANDS = (
    Command(
        name="watching",
        group=GROUP,
        summary="Show whether you watch a page or a space",
        when="Use to see whether you get notifications for a page, a blog post or a space. It shows your own watch only. To start or stop watching use `watch`.",
        description="Says whether the account of the token watches a page (or a blog post or other content, by its id) or a space. Who else watches "
        "is not shown, and nothing is changed. Without a page and without --space the current space of `conflu use` is the one.",
        args=(
            PAGE,
            Arg(("--space",), "Show the watch of this space (its key) instead of a page's. Without a page and without it the current space is used.", metavar="KEY"),
        ),
        examples=(
            Example("conflu watching 123456"),
            Example("conflu watching --space ENG", "a space, by its key"),
            Example("conflu watching 123456 --json", "for a script or an agent"),
        ),
        notes=(
            "Only your own watch is read: no option names another person. Atlassian's API v2 has no call for watches, so the v1 calls are used (see `conflu how-to compatibility`).",
        ),
        json_output=True,
        output=f"{TARGET_JSON}; watching (true or false).",
        handler=run_watching,
    ),
    Command(
        name="watch",
        group=GROUP,
        summary="Start or stop watching a page or a space",
        when="Use to get notifications for a page, a blog post or a space (or with --remove to stop getting them). It changes your own watch only, "
        "never somebody else's. Preview with --dry-run. To see whether you watch it use `watching`.",
        description="Starts watching a page (or a blog post or other content, by its id) or a space, or with --remove stops, for the account of the token only: "
        "there is no option to name another person. The status is read first, so a watch that is as asked already is left alone (`unchanged`, "
        "nothing is sent), and it is read again after the change. If that second read fails, the change is still reported as made (exit code 0, "
        "`confirmed` is null) and a warning says how to check.",
        args=(
            PAGE,
            Arg(("--space",), "Watch this space (its key) instead of a page. A change names what it changes: the current space of `conflu use` is not assumed.", metavar="KEY"),
            Arg(("--remove",), "Stop watching instead of starting. It takes your own watch off and nothing else: no content, and nobody else's watch.", kind="flag"),
            Arg(("--dry-run",), "Show what would be sent and read the watch status. Sends nothing.", kind="flag"),
        ),
        examples=(
            Example("conflu watch 123456 --dry-run"),
            Example("conflu watch 123456"),
            Example("conflu watch --space ENG", "a space, by its key"),
            Example("conflu watch 123456 --remove", "stop watching"),
            Example("conflu watch 123456 --json"),
        ),
        notes=(
            "The watch is a notification setting of your account: `--remove` removes that and no content, and it cannot remove anybody else's watch. "
            "It is the only command, besides `conflu label --remove`, that sends a DELETE.",
            "Atlassian's API v2 has no call for watches, so the v1 calls are used (see `conflu how-to compatibility`).",
        ),
        writes=True,
        json_output=True,
        output=f"action (watched, unwatched or unchanged), dryRun, {TARGET_JSON}, wasWatching, watching (as Confluence says after the change; null when it "
        "could not be read back; in a dry run and when unchanged the state as it is), confirmed (the status read back is the one asked for; null when "
        "nothing was written or the read-back failed), call (the REST call that is sent, or in a dry run would be, as the compatibility page writes it; "
        "null when unchanged) and message (null unless the change could not be confirmed).",
        idempotent=True,
        handler=run_watch,
    ),
)
