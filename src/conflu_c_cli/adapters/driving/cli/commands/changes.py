"""Commands that act on one page: update, move, comment, label, attach."""
from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from .....application.rendering import INPUT_FORMATS, storage_from_input
from .....domain.drafts import PageChanges
from .....domain.errors import UsageError
from .....domain.frontmatter import split_list
from ..render import table
from ..runtime import Context
from ..spec import Arg, Command, Example
from ._common import POWERSHELL_TEXT_NOTE, pretty, shortened, text_option

if TYPE_CHECKING:
    from .....application.attachments import UploadResult
    from .....application.comments import CommentResult
    from .....application.labels import LabelsResult
    from .....application.writing import PageWrite

GROUP = "Work on a page"

BODY = Arg(("--body",), "The text, in the --format. A longer text is easier in a file: --file.", metavar="TEXT")
FILE = Arg(("--file",), "Read the text from a file (`-` is standard input).", metavar="FILE")
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


def write_json(result: PageWrite) -> dict[str, Any]:
    page = result.page
    payload = result.payload
    title = page.title if page else (payload.get("title", "") if isinstance(payload, dict) else "")
    return {
        "action": result.action,
        "dryRun": result.dry_run,
        "pageId": page.id if page else None,
        "title": title,
        "url": page.url if page else None,
        "versionFrom": result.version_from or None,
        "versionTo": result.version_to or None,
        "lost": list(result.lost),
        "labels": result.labels,
        "payload": payload,
    }


def write_text(result: PageWrite) -> str:
    page = result.page
    title = page.title if page else ""
    where = f"\n{page.url}" if page and page.url else ""
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


# -- update --------------------------------------------------------------------------------------


def run_update(ctx: Context, args: argparse.Namespace) -> int:
    if args.append and args.prepend:
        raise UsageError("Use either --append or --prepend, not both.")
    text = text_option(ctx, args.body, args.file, "body")
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
    result = ctx.app.update_page.execute(
        args.ref, changes, dry_run=args.dry_run, if_version=args.if_version, if_unchanged_since=args.if_unchanged_since or "", force=args.force
    )
    ctx.print_json(write_json(result)) if ctx.json_mode else ctx.print(write_text(result))
    return 0


# -- move ----------------------------------------------------------------------------------------


def run_move(ctx: Context, args: argparse.Namespace) -> int:
    result = ctx.app.move_page.execute(args.ref, args.to, position=args.position, dry_run=args.dry_run)
    ctx.print_json(write_json(result)) if ctx.json_mode else ctx.print(write_text(result))
    return 0


# -- comment -------------------------------------------------------------------------------------


def comment_text(result: CommentResult) -> str:
    if result.dry_run:
        return f"Dry run: page {result.page_id} exists; nothing was sent\n{pretty(shortened(result.payload))}"
    return f"Commented on page {result.page_id}" + (f" (comment {result.comment_id})" if result.comment_id else "")


def run_comment(ctx: Context, args: argparse.Namespace) -> int:
    body = text_option(ctx, args.text, args.file, "comment")
    if body is None:
        raise UsageError("Nothing to do.", hint="Pass --text or --file. `conflu comments PAGE` lists the comments.")
    result = ctx.app.add_comment.execute(args.ref, body, body_format=args.format, reply_to=args.reply_to or "", dry_run=args.dry_run)
    if ctx.json_mode:
        ctx.print_json({"pageId": result.page_id, "dryRun": result.dry_run, "commentId": result.comment_id or None, "payload": result.payload})
    else:
        ctx.print(comment_text(result))
    return 0


# -- label ---------------------------------------------------------------------------------------


def labels_text(result: LabelsResult) -> str:
    changes = []
    if result.added:
        changes.append(f"{'would add' if result.dry_run else 'added'}: {', '.join(result.added)}")
    if result.removed:
        changes.append(f"{'would remove' if result.dry_run else 'removed'}: {', '.join(result.removed)}")
    head = "; ".join(changes) if changes else "nothing to change, the labels are as asked"
    now = ", ".join(label.name for label in result.labels) or "(none)"
    prefix = "Dry run (nothing was sent): " if result.dry_run else ""
    return f"{prefix}page {result.page_id}: {head}\nLabels{' now' if not result.dry_run else ''}: {now}"


def run_label(ctx: Context, args: argparse.Namespace) -> int:
    result = ctx.app.change_labels.execute(args.ref, add=split_list(args.add or ""), remove=split_list(args.remove or ""), dry_run=args.dry_run)
    if ctx.json_mode:
        ctx.print_json(
            {
                "pageId": result.page_id,
                "dryRun": result.dry_run,
                "added": result.added,
                "removed": result.removed,
                "labels": [label.name for label in result.labels],
            }
        )
    else:
        ctx.print(labels_text(result))
    return 0


# -- attach --------------------------------------------------------------------------------------


def run_attach(ctx: Context, args: argparse.Namespace) -> int:
    result: UploadResult = ctx.app.upload_attachments.execute(args.ref, args.files, comment=args.comment or "", minor=args.minor, dry_run=args.dry_run)
    if ctx.json_mode:
        ctx.print_json(
            {
                "pageId": result.page_id,
                "dryRun": result.dry_run,
                "files": [
                    {
                        "path": item.path,
                        "name": item.name,
                        "size": item.size,
                        "action": item.action,
                        "attachmentId": item.attachment.id if item.attachment else None,
                        "version": item.attachment.version if item.attachment else None,
                    }
                    for item in result.uploads
                ],
            }
        )
        return 0
    rows = [(item.action, item.name, f"{item.size} B", item.attachment.id if item.attachment else "", item.attachment.version if item.attachment else "") for item in result.uploads]
    ctx.print(table(["ACTION", "NAME", "SIZE", "ATTACHMENT", "VERSION"], rows))
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
            Arg(("--force",), "Replace a body with Markdown even though what Markdown cannot say is lost.", kind="flag"),
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
        output="action (updated or unchanged), dryRun, pageId, title, url, versionFrom, versionTo, lost[], labels[] and payload (exactly what is sent).",
        handler=run_update,
    ),
    Command(
        name="move",
        group=GROUP,
        summary="Move a page below, before or after another page",
        when="Use to move one page below, before or after another page. Preview with --dry-run.",
        description="With the default position `append` the page becomes the last child of the target; `before` and `after` put it next to "
        "the target, under the target's parent.",
        args=(
            Arg(("ref",), "Page id, or the address of the page to move.", required=True, metavar="PAGE"),
            Arg(("--to",), "The page to move it to (id or address).", required=True, metavar="TARGET"),
            Arg(("--position",), "Where, relative to the target.", kind="choice", choices=("append", "before", "after"), default="append"),
            DRY_RUN,
        ),
        examples=(Example("conflu move 123456 --to 654321 --dry-run"), Example("conflu move 123456 --to 654321 --position before")),
        writes=True,
        json_output=True,
        output="action (moved), dryRun, pageId, title, url and payload{pageId,position,targetId}.",
        handler=run_move,
    ),
    Command(
        name="comment",
        group=GROUP,
        summary="Add a comment to a page",
        when="Use to add a footer comment to a page, or to answer a comment with --reply-to. Preview with --dry-run.",
        description="Adds a footer comment, or with --reply-to an answer to a comment. The text is Markdown unless --format says storage.",
        args=(
            Arg(("ref",), "Page id, or the address of the page.", required=True, metavar="PAGE"),
            Arg(("--text",), "The comment. A longer text is easier in a file: --file.", metavar="TEXT"),
            FILE,
            FORMAT,
            Arg(("--reply-to",), "Id of the comment to answer (`conflu comments PAGE --json` lists them).", metavar="COMMENT"),
            DRY_RUN,
        ),
        examples=(Example("conflu comment 123456 --text 'Reviewed, no findings.' --dry-run"), Example("conflu comment 123456 --file review.md")),
        notes=(POWERSHELL_TEXT_NOTE,),
        writes=True,
        json_output=True,
        output="pageId, dryRun, commentId (null in a dry run) and payload (exactly what is sent).",
        handler=run_comment,
    ),
    Command(
        name="label",
        group=GROUP,
        summary="Add or remove labels of a page",
        when="Use to add or remove labels of one page. Preview with --dry-run.",
        description="Adds the labels of --add and removes those of --remove (comma separated). A label that is on the page already, or "
        "not on it, is skipped. Labels are written in lower case.",
        args=(
            Arg(("ref",), "Page id, or the address of the page.", required=True, metavar="PAGE"),
            Arg(("--add",), "Labels to add, comma separated.", metavar="a,b"),
            Arg(("--remove",), "Labels to remove, comma separated.", metavar="a,b"),
            DRY_RUN,
        ),
        examples=(Example("conflu label 123456 --add reviewed,adr --dry-run"), Example("conflu label 123456 --remove draft")),
        writes=True,
        json_output=True,
        output="pageId, dryRun, added[], removed[] and labels[] (the names after the change; the current ones in a dry run).",
        handler=run_label,
    ),
    Command(
        name="attach",
        group=GROUP,
        summary="Attach files to a page",
        when="Use to upload files to a page. Preview with --dry-run.",
        description="Uploads the files. A file whose name the page has already becomes a new version of that attachment. In the text of a "
        "page an image is referred to by its file name: attach it first, then write the file name where Markdown wants the address of an image.",
        args=(
            Arg(("ref",), "Page id, or the address of the page.", required=True, metavar="PAGE"),
            Arg(("files",), "The files to upload.", kind="list", required=True, metavar="FILE"),
            Arg(("--comment",), "A comment stored with the attachments.", metavar="TEXT"),
            Arg(("--minor",), "A minor edit: nobody is notified.", kind="flag"),
            DRY_RUN,
        ),
        examples=(Example("conflu attach 123456 diagram.png --dry-run"), Example("conflu attach 123456 diagram.png notes.pdf --comment 'October version'")),
        writes=True,
        json_output=True,
        output="pageId, dryRun and files[]: path, name, size, action (uploaded or would upload), attachmentId, version.",
        handler=run_attach,
    ),
)
