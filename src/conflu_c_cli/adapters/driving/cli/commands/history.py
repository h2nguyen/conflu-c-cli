"""Commands about earlier versions of a page, the difference between two of them, and restoring one: diff, restore."""
from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from .....domain.history import DEFAULT_CONTEXT, parse_target
from ..runtime import Context
from ..spec import Arg, Command, Example
from ._common import POWERSHELL_TEXT_NOTE, pretty
from .changes import DRY_RUN, SINCE

if TYPE_CHECKING:
    from .....application.history import RestoreResult, VersionDiff, VersionSide

GROUP = "Read"
WORK = "Work on a page"


# -- diff ----------------------------------------------------------------------------------------


def side_json(side: VersionSide | None) -> dict[str, Any] | None:
    if side is None:
        return None
    return {"number": side.number, "created": side.created, "message": side.message, "title": side.title, "current": side.current}


def diff_json(result: VersionDiff) -> dict[str, Any]:
    difference = result.difference
    return {
        "pageId": result.page_id,
        "title": result.title,
        "from": side_json(result.from_side),
        "to": side_json(result.to_side),
        "identical": result.identical,
        "added": difference.added,
        "removed": difference.removed,
        "truncated": difference.truncated,
        "totalChars": difference.total_chars or None,
        "dropped": list(result.dropped),
        "sourceIdentical": result.source_identical,
        "note": result.note or None,
        "diff": difference.text,
    }


def diff_text(result: VersionDiff) -> str:
    """The diff, or a sentence that says why there is none."""
    if result.difference.text:
        return result.difference.text
    if result.from_side is None or result.from_side.number == result.to_side.number:
        return result.note
    if result.source_identical:
        return f"Versions {result.from_side.number} and {result.to_side.number} are the same."
    shown = f" ({', '.join(result.dropped)})" if result.dropped else ""
    return f"{result.note} The versions differ in what the Markdown cannot say{shown}: that is not in a diff of the Markdown."


def run_diff(ctx: Context, args: argparse.Namespace) -> int:
    result = ctx.app.history.diff_versions.execute(
        args.ref,
        from_version=args.from_version,
        to_version=parse_target(args.to_version),
        context=args.context,
        max_chars=args.max_chars or 0,
    )
    if ctx.json_mode:
        ctx.print_json(diff_json(result))
        return 0
    ctx.print(diff_text(result))
    difference = result.difference
    if difference.truncated:
        ctx.diagnostics.info(f"The diff was cut: {len(difference.text)} of {difference.total_chars} characters are shown. A larger --max-chars shows more; a smaller --context makes it shorter.")
    if result.dropped and not difference.identical:
        ctx.diagnostics.info(f"The Markdown cannot show: {', '.join(result.dropped)}. A change in these is not in the diff.")
    return 0


# -- restore -------------------------------------------------------------------------------------


def restore_json(result: RestoreResult) -> dict[str, Any]:
    return {
        "action": "restored",
        "dryRun": result.dry_run,
        "pageId": result.page_id,
        "title": result.title,
        "url": result.url,
        "restoredVersion": result.restored_version,
        "versionFrom": result.version_from,
        "versionTo": result.version_to,
        "added": result.added,
        "removed": result.removed,
        "payload": result.payload,
    }


def _lines(count: int) -> str:
    return f"{count} line" + ("" if count == 1 else "s")


def restore_text(result: RestoreResult) -> str:
    changes = f"As Markdown shows them, the page gains {_lines(result.added)} and loses {_lines(result.removed)}."
    if result.dry_run:
        return (
            f"Dry run: version {result.restored_version} of page {result.page_id} '{result.title}' would come back as version {result.version_to}; nothing was sent\n"
            f"{changes}\n{pretty(result.payload)}"
        )
    where = f"\n{result.url}" if result.url else ""
    return f"Restored version {result.restored_version} of page {result.page_id}: {result.title} (version {result.version_from} -> {result.version_to}){where}\n{changes}"


def run_restore(ctx: Context, args: argparse.Namespace) -> int:
    result = ctx.app.history.restore_version.execute(
        args.ref,
        args.version,
        message=args.message or "",
        restore_title=args.restore_title,
        if_version=args.if_version,
        if_unchanged_since=args.if_unchanged_since,
        dry_run=args.dry_run,
    )
    ctx.print_json(restore_json(result)) if ctx.json_mode else ctx.print(restore_text(result))
    return 0


COMMANDS = (
    Command(
        name="diff",
        group=GROUP,
        summary="Show what changed between two versions of a page",
        when="Use to see what an edit changed, or what `restore` would bring back. It compares the Markdown of two versions; for the list of versions and their messages use `versions`.",
        description="A unified diff of the Markdown of two versions of the page: by default the current version against the one before it. "
        "--to names the later version (a number, or `current`), --from the earlier one; the two may be given in either order. "
        "People are hidden as in `page` (a mention is `@user`, an e-mail address `[email]`), so they are not in the diff. "
        "What Markdown cannot show (macros, layouts, mentions) is not compared: `dropped` names it. "
        "A page with one version, or two versions that read the same, says so; that is no failure. The first version of a page has nothing before it: `--to 1` says so, and `--from 1` compares it with the current one.",
        args=(
            Arg(("ref",), "Page id, or the address of the page.", required=True, metavar="PAGE"),
            Arg(("--from-version", "--from"), "The earlier version. Default: the version before --to.", kind="int", metavar="N"),
            Arg(("--to-version", "--to"), "The later version: a number or `current`. Default: current.", metavar="N|current"),
            Arg(("--context",), "Lines of unchanged text around each change.", kind="int", default=DEFAULT_CONTEXT, metavar="LINES"),
            Arg(("--max-chars",), "Cut the diff to about N characters, after the last whole line; the answer says that it was cut.", kind="int", metavar="N"),
        ),
        examples=(
            Example("conflu diff 123456", "the current version against the one before it"),
            Example("conflu diff 123456 --from 2 --to 5 --context 1", "version 2 against version 5, with one line of context"),
            Example("conflu diff 123456 --from 3 --json", "version 3 against the current one, as JSON: added, removed and diff"),
        ),
        notes=(
            "`conflu versions PAGE` lists the version numbers; a number that the page does not have is a not-found error that says where the page is now.",
            "The messages of the versions are redacted like any text from Confluence. The title of each version is named too: a change of the title is not in the diff of the body.",
        ),
        json_output=True,
        output="pageId, title, from and to ({number, created, message, title, current}; from is null for a page with one version, and for version 1 asked for as --to, which has nothing before it), "
        "identical (the Markdown of the two reads the same; false for version 1 asked for as --to, where nothing was compared), "
        "added and removed (lines), truncated and totalChars (when --max-chars cut the diff), dropped[], sourceIdentical (the storage format is the same too), note (null or what the text says instead of a diff) and diff.",
        handler=run_diff,
    ),
    Command(
        name="restore",
        group=WORK,
        summary="Bring an earlier version of a page back",
        when="Use to undo an edit: it saves a new version with the content of an earlier one, and nothing is lost, since the history keeps every version. Read the old version first (`page --version`, `diff`) and preview with --dry-run.",
        description="Saves a NEW version of the page with the body of version N (and with --restore-title also its title); the versions in between stay in the history. "
        "The version must exist and must not be the current one. The page must be current. The message of the new version is `Restored version N` unless you give one. "
        "--if-version and --if-unchanged-since refuse (exit code 3) when the page is not as you read it. Confluence has no version guard for a restore, "
        "so both are a check just before the write, not a lock; the answer names the version that the page reached, and says when it is not the next one. "
        "The content is restored by Confluence itself: nothing is converted, so macros and mentions come back as they were. The dry run reads the page and the version and sends nothing.",
        args=(
            Arg(("ref",), "Page id, or the address of the page.", required=True, metavar="PAGE"),
            Arg(("--version",), "The version to bring back (`conflu versions PAGE` lists them).", kind="int", required=True, metavar="N"),
            Arg(("--message",), "A message stored with the new version. Default: Restored version N.", metavar="TEXT"),
            Arg(("--restore-title",), "Also give the page the title that version had.", kind="flag"),
            Arg(("--if-version",), "Refuse (exit code 3) unless the page is at this version now.", kind="int", metavar="N"),
            SINCE,
            DRY_RUN,
        ),
        examples=(
            Example("conflu restore 123456 --version 2 --dry-run", "what would come back, and the payload"),
            Example("conflu restore 123456 --version 2 --message 'Back to the reviewed text' --if-version 5"),
            Example("conflu restore 123456 --version 1 --restore-title --json"),
        ),
        notes=(POWERSHELL_TEXT_NOTE, "A restore makes a new version; to undo it, restore the version that it covered (`conflu versions PAGE` names it)."),
        writes=True,
        destructive=True,
        json_output=True,
        output="action (restored), dryRun, pageId, title, url, restoredVersion, versionFrom, versionTo (in a dry run the version it would make), "
        "added and removed (lines that the restored Markdown adds to and takes from the current one) and payload (exactly what is sent: it names the version and holds no content).",
        handler=run_restore,
    ),
)
