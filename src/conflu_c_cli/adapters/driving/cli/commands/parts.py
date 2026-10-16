"""Commands that read what belongs to a page: comments, labels, attachments, download."""
from __future__ import annotations

import argparse
from typing import Any

from .....application.rendering import BODY_FORMATS
from .....domain.model import parse_page_id
from ..render import table
from ..runtime import Context
from ..spec import Arg, Command, Example
from ._common import LIMIT_HELP, check_limit, comment_json, comments_text

GROUP = "Read"


def _size(count: int) -> str:
    if count < 1024:
        return f"{count} B"
    if count < 1024 * 1024:
        return f"{count / 1024:.1f} KB"
    return f"{count / (1024 * 1024):.1f} MB"


# -- comments ------------------------------------------------------------------------------------


def run_comments(ctx: Context, args: argparse.Namespace) -> int:
    views = ctx.app.list_comments.execute(args.ref, inline=args.inline, body_format=args.format, with_users=args.with_users)
    if ctx.json_mode:
        ctx.print_json({"pageId": parse_page_id(args.ref), "count": len(views), "comments": [comment_json(view) for view in views]})
        return 0
    ctx.print(comments_text(views, users_shown=args.with_users) if views else "No comments.")
    return 0


# -- labels --------------------------------------------------------------------------------------


def run_labels(ctx: Context, args: argparse.Namespace) -> int:
    labels = ctx.app.list_labels.execute(args.ref)
    if ctx.json_mode:
        ctx.print_json({"pageId": parse_page_id(args.ref), "labels": [{"name": label.name, "prefix": label.prefix} for label in labels]})
        return 0
    ctx.print(table(["NAME", "PREFIX"], [(label.name, label.prefix) for label in labels]) if labels else "No labels.")
    return 0


# -- attachments ---------------------------------------------------------------------------------


def attachment_json(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "mediaType": item.media_type,
        "size": item.size,
        "version": item.version,
        "created": item.created,
        "pageId": item.page_id or None,
        "downloadLink": item.download_link,
        "comment": item.comment or None,
    }


def run_attachments(ctx: Context, args: argparse.Namespace) -> int:
    check_limit(args.limit)
    result = ctx.app.list_attachments.execute(args.ref, name=args.name or "", limit=args.limit, cursor=args.cursor or "", fetch_everything=args.all)
    if ctx.json_mode:
        ctx.print_json(
            {
                "pageId": result.page_id,
                "count": len(result.attachments),
                "nextCursor": result.next_cursor or None,
                "attachments": [attachment_json(item) for item in result.attachments],
            }
        )
        return 0
    if not result.attachments:
        ctx.print("No attachments.")
        return 0
    rows = [(a.id, a.title, _size(a.size), a.media_type, a.version, a.created) for a in result.attachments]
    ctx.print(table(["ID", "NAME", "SIZE", "TYPE", "VERSION", "CREATED"], rows))
    if result.next_cursor:
        ctx.diagnostics.info(f"More attachments follow. Continue with --cursor {result.next_cursor}, or use --all.")
    return 0


def run_download(ctx: Context, args: argparse.Namespace) -> int:
    downloads = ctx.app.download_attachments.execute(
        args.target, names=args.name or (), everything=args.all, out_dir=args.out, force=args.force, dry_run=args.dry_run
    )
    if ctx.json_mode:
        ctx.print_json(
            {
                "dryRun": args.dry_run,
                "count": len(downloads),
                "files": [
                    {"attachmentId": d.attachment.id, "name": d.attachment.title, "path": d.path, "size": d.size, "action": d.action}
                    for d in downloads
                ],
            }
        )
        return 0
    for item in downloads:
        ctx.print(f"{item.action:<15}{item.path}  ({_size(item.size)})")
    return 0


COMMANDS = (
    Command(
        name="comments",
        group=GROUP,
        summary="Show the comments of a page",
        when="Use to read the discussion on a page; with --inline also the comments made on a piece of text.",
        description="Shows the footer comments, each conversation as its first comment followed by the replies. --inline adds the comments "
        "that were made on a piece of text. Authors and mentions are hidden unless you add --with-users.",
        args=(
            Arg(("ref",), "Page id, or the address of the page.", required=True, metavar="PAGE"),
            Arg(("--inline",), "Also show the inline comments.", kind="flag"),
            Arg(("--format",), "Format of the comment text.", kind="choice", choices=BODY_FORMATS, default="markdown"),
            Arg(("--with-users",), "Show who wrote each comment. Refused when CONFLUENCE_HIDE_USERS=true.", kind="flag"),
        ),
        examples=(Example("conflu comments 123456"), Example("conflu comments 123456 --inline --json")),
        json_output=True,
        output="pageId, count and comments[]: id, kind (footer or inline), updated, parentId (null for the first comment of a conversation), "
        "resolution (inline comments), author (null unless --with-users), body{format,value,dropped[]}.",
        handler=run_comments,
    ),
    Command(
        name="labels",
        group=GROUP,
        summary="List the labels of a page",
        when="Use to see how a page is tagged.",
        args=(Arg(("ref",), "Page id, or the address of the page.", required=True, metavar="PAGE"),),
        examples=(Example("conflu labels 123456"), Example("conflu labels 123456 --json")),
        json_output=True,
        output="pageId and labels[]: name, prefix.",
        handler=run_labels,
    ),
    Command(
        name="attachments",
        group=GROUP,
        summary="List the files attached to a page",
        when="Use to list the files attached to a page before you `download` one.",
        args=(
            Arg(("ref",), "Page id, or the address of the page.", required=True, metavar="PAGE"),
            Arg(("--name",), "Only the attachment with this file name.", metavar="FILE"),
            Arg(("--limit",), LIMIT_HELP, kind="int", default=50, metavar="N"),
            Arg(("--cursor",), "Continue after the end of the previous answer: pass its nextCursor.", metavar="TOKEN"),
            Arg(("--all",), "Fetch every page of the list instead of one (ignores --limit and --cursor).", kind="flag"),
        ),
        examples=(Example("conflu attachments 123456"), Example("conflu attachments 123456 --json")),
        json_output=True,
        output="pageId, count, nextCursor and attachments[]: id, title, mediaType, size, version, created, pageId, downloadLink, comment.",
        handler=run_attachments,
    ),
    Command(
        name="download",
        group=GROUP,
        summary="Download attachments of a page",
        when="Use to save attachments of a page into a folder. It never overwrites a file without --force.",
        description="Downloads one attachment by its id (att123456, from `conflu attachments`), or files of a page by name (--name, as often as "
        "you like) or all of them (--all). Files go into --out (the current folder by default) under their own names. A file that exists "
        "is replaced only with --force. The credentials are sent to Confluence only, never to the media service that serves the file.",
        args=(
            Arg(("target",), "An attachment id such as att123456, or a page (id or address) together with --name or --all.", required=True, metavar="ATTACHMENT_OR_PAGE"),
            Arg(("--name",), "File name to download from the page. Give it again for more files.", kind="list", metavar="FILE"),
            Arg(("--all",), "Download every attachment of the page.", kind="flag"),
            Arg(("--out",), "Folder to write into; it is created when it is missing.", default=".", metavar="DIR"),
            Arg(("--force",), "Overwrite files that exist.", kind="flag"),
            Arg(("--dry-run",), "Say what would be downloaded. Writes nothing.", kind="flag"),
        ),
        examples=(
            Example("conflu download att98765 --out tmp"),
            Example("conflu download 123456 --name diagram.png --name notes.pdf --out tmp"),
            Example("conflu download 123456 --all --out tmp --dry-run"),
        ),
        json_output=True,
        output="dryRun, count and files[]: attachmentId, name, path, size, action (downloaded or would download).",
        handler=run_download,
    ),
)
