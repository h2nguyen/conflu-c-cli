"""The command that changes a page: update. It also holds what the commands that write share: the options, and the text of a write."""
from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from .....application.paging import ensure_users_allowed
from .....application.rendering import INPUT_FORMATS, storage_from_input
from .....domain.drafts import PageChanges
from .....domain.errors import UsageError
from .....domain.privacy import redact_address, redact_text
from ..runtime import Context
from ..spec import READS_FILE, Arg, Command, Example
from ._common import POWERSHELL_TEXT_NOTE, pretty, replacing_text_option, shortened

if TYPE_CHECKING:
    from .....application.writing import PageWrite

GROUP = "Work on a page"

BODY = Arg(
    ("--body",),
    "The text, in the --format. A longer text is easier in a file: --file.",
    metavar="TEXT",
    not_a_path="the text itself, written on the command line; the option that names a file is --file",
)
FILE = Arg(("--file",), "Read the text from a file (`-` is standard input).", metavar="FILE", path=READS_FILE)
FORMAT = Arg(
    ("--format",),
    "Format of the text: markdown, which is converted, or storage, which is sent as it is.",
    kind="choice",
    choices=INPUT_FORMATS,
    default="markdown",
)
DRY_RUN = Arg(("--dry-run",), "Show what would be sent and check that the page exists. Sends nothing.", kind="flag")
SINCE = Arg(
    ("--if-unchanged-since",),
    "Refuse (exit code 3) when the page changed in Confluence after this time (ISO 8601, for example the time you read it). "
    "It is a check just before the write, not a lock; the version number of an update is a second, atomic guard.",
    metavar="ISO",
)


def write_json(result: PageWrite, with_users: bool = False) -> dict[str, Any]:
    """The JSON of a write. The title and the address of the page come from Confluence and are redacted (an e-mail address in a title is in the
    address too) unless people are shown."""
    page = result.page
    payload = result.payload
    title = page.title if page else (payload.get("title", "") if isinstance(payload, dict) else "")
    return {
        "action": result.action,
        "dryRun": result.dry_run,
        "pageId": page.id if page else None,
        "title": title if with_users else redact_text(title),
        "url": (page.url if with_users else redact_address(page.url)) if page else None,
        "versionFrom": result.version_from or None,
        "versionTo": result.version_to or None,
        "lost": list(result.lost),
        "labels": result.labels,
        "payload": payload,
    }


def write_text(result: PageWrite, with_users: bool = False) -> str:
    page = result.page
    title = (page.title if with_users else redact_text(page.title)) if page else ""
    address = (page.url if with_users else redact_address(page.url)) if page else ""
    where = f"\n{address}" if address else ""
    if result.action == "unchanged":
        return f"Nothing to change: page {page.id if page else ''} is already as asked."
    if result.dry_run:
        if result.action == "created":
            lines = [f"Dry run: a page would be created; nothing was sent\n{pretty(shortened(result.payload))}"]
        elif result.action == "moved":
            lines = [f"Dry run: page {page.id if page else ''} would be moved; nothing was sent\n{pretty(result.payload)}"]
        else:
            lines = [
                f"Dry run: page {page.id if page else ''} '{title}' would go from version {result.version_from} to "
                f"{result.version_to}; nothing was sent\n{pretty(shortened(result.payload))}"
            ]
        if result.lost:
            lines.append(f"This replaces what Markdown cannot say and drops: {', '.join(result.lost)}.")
        return "\n".join(lines)
    if result.action == "created":
        labels = f" with the labels {', '.join(result.labels)}" if result.labels else ""
        return f"Created page {page.id if page else ''}: {title}{labels}{where}"
    if result.action == "moved":
        return f"Moved page {page.id if page else ''}: {title}{where}"
    note = f"\nWarning: dropped what Markdown cannot say: {', '.join(result.lost)}." if result.lost else ""
    return f"Updated page {page.id if page else ''}: {title} (version {result.version_from} -> {result.version_to}){where}{note}"


def run_update(ctx: Context, args: argparse.Namespace) -> int:
    if args.append and args.prepend:
        raise UsageError("Use either --append or --prepend, not both.")
    text = replacing_text_option(ctx, args.body, args.file, "body")
    mode = "append" if args.append else "prepend" if args.prepend else "replace"
    if text is None and mode != "replace":
        raise UsageError(f"--{mode} needs a text.", hint="Pass --body or --file.")
    changes = PageChanges(
        title=args.title,
        body=None if text is None else storage_from_input(text, args.format),
        body_mode=mode,
        from_markdown=args.format == "markdown",
        message=args.message or "",
    )
    ensure_users_allowed(args.with_users, ctx.app.settings)
    result = ctx.app.update_page.execute(
        args.ref,
        changes,
        dry_run=args.dry_run,
        if_version=args.if_version,
        if_unchanged_since=args.if_unchanged_since,
        force=args.force,
        with_users=args.with_users,
    )
    ctx.print_json({**write_json(result, args.with_users), "payloadRedacted": result.redacted}) if ctx.json_mode else ctx.print(
        write_text(result, args.with_users) + ("\nThe request is shown without the people and addresses that the body holds; --with-users shows it as it is." if result.redacted else "")
    )
    return 0


COMMANDS = (
    Command(
        name="update",
        group=GROUP,
        summary="Change the title or the body of a page",
        when="Use to change the title or the body of one existing page. Preview with --dry-run, guard with --if-version, and prefer --append to replacing the body.",
        description="Changes the title, the body, or both. The text replaces the body, or is put behind it (--append) or in front of it "
        "(--prepend); the two keep everything that is on the page. Markdown (the default format) is converted to storage format. "
        "Replacing a body with Markdown is refused when the page holds what Markdown cannot say (macros, mentions, layouts, links "
        "between pages ...) unless you add --force; `conflu page PAGE --json` shows it under `dropped`. The new version number is "
        "the current one plus one, so Confluence itself refuses (exit code 3) when somebody saved in between.",
        args=(
            Arg(("ref",), "Page id, or the address of the page.", required=True, metavar="PAGE"),
            Arg(("--title",), "The new title.", metavar="TEXT"),
            BODY,
            FILE,
            FORMAT,
            Arg(("--append",), "Put the text behind the current body instead of replacing it.", kind="flag"),
            Arg(("--prepend",), "Put the text in front of the current body instead of replacing it.", kind="flag"),
            Arg(("--message",), "A message stored with the new version.", metavar="TEXT"),
            Arg(("--if-version",), "Refuse (exit code 3) unless the page is at this version now.", kind="int", metavar="N"),
            SINCE,
            Arg(("--force",), "Replace a body with Markdown even though what Markdown cannot say is lost.", kind="flag", overwrites=True),
            Arg(
                ("--with-users",),
                "Show the request exactly as it is sent, with the people (mentions), e-mail addresses and personal links that the body holds. "
                "Refused when CONFLUENCE_HIDE_USERS=true.",
                kind="flag",
            ),
            DRY_RUN,
        ),
        examples=(
            Example("conflu update 123456 --title 'Release notes 2026.10' --dry-run"),
            Example("conflu update 123456 --file notes.md --append --message 'Added the October notes' --if-version 7"),
            Example("conflu update 123456 --file page.xml --format storage --dry-run"),
        ),
        notes=(POWERSHELL_TEXT_NOTE, "A change of the title alone does not touch the body."),
        writes=True,
        json_output=True,
        output="action (updated or unchanged), dryRun, pageId, title and url (redacted unless --with-users; the address ends at the id of the page when "
        "the title holds an e-mail address), versionFrom, versionTo, lost[], labels[], payload (what is sent, but without the people and addresses that "
        "the body holds unless --with-users) and payloadRedacted (true when the printed payload differs from the request).",
        destructive=True,
        handler=run_update,
    ),
)
