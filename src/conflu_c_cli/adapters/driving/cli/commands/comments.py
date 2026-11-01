"""Commands about the comments of a page: comments, comment."""
from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from .....application.formats import BODY_FORMATS
from .....domain.comments import RESOLUTIONS
from .....domain.errors import UsageError, ValidationError
from .....domain.model import parse_page_id
from ..listing import LIST_FORMAT, SELECT, print_list
from ..runtime import Context
from ..spec import READS_FILE, Arg, Command, Example
from ._common import POWERSHELL_TEXT_NOTE, body_json, pretty, shortened, text_option, user_json, user_name
from .changes import DRY_RUN

if TYPE_CHECKING:
    from .....application.comments import CommentChange, CommentResult, CommentView

GROUP = "Read"
WORK = "Work on a page"
FILE = Arg(("--file",), "Read the text from a file (`-` is standard input).", metavar="FILE", path=READS_FILE)
ID_NOT_A_PATH = "the id of a comment in Confluence, a number"


# -- comments ------------------------------------------------------------------------------------

COMMENT_COLUMNS = [("ID", "id"), ("KIND", "kind"), ("UPDATED", "updated"), ("PARENT", "parentId"), ("RESOLUTION", "resolution")]


def comment_row(view: CommentView, *, version: bool = False) -> dict[str, Any]:
    """A comment as JSON. The author is a person (null unless people are shown); `authorRef` and `byMe` say who wrote it without a name."""
    comment = view.comment
    row: dict[str, Any] = {"id": comment.id, "kind": comment.kind, "updated": comment.updated}
    if version:
        row["version"] = comment.version
    row.update(
        {
            "parentId": comment.parent_id or None,
            "resolution": comment.resolution or None,
            "author": user_json(comment.author),
            "authorRef": view.author_ref,
            "byMe": view.by_me,
            "body": body_json(view.body),
        }
    )
    return row


def comment_header(view: CommentView, *, users_shown: bool, version: bool = False) -> str:
    """The line above a comment: its number, kind, state and time, whom it answers, and who wrote it (the name when people are shown, else the
    pseudonym) with `(you)` for the comments of the user of the token."""
    comment = view.comment
    state = f" [{comment.resolution}]" if comment.resolution else ""
    line = f"--- #{comment.id} {comment.kind}{state} {comment.updated}"
    if comment.parent_id:
        line += f" (reply to #{comment.parent_id})"
    if version:
        line += f" (version {comment.version})"
    name = user_name(comment.author) if users_shown and comment.author else view.author_ref or ""
    who = " ".join(part for part in (name, "(you)" if view.by_me else "") if part)
    return f"{line}  {who}" if who else line


def comment_block(view: CommentView, *, users_shown: bool, version: bool = False) -> str:
    """A comment under its header; a reply is indented below the comment it answers."""
    indent = "    " if view.comment.parent_id else ""
    lines = [f"{indent}{comment_header(view, users_shown=users_shown, version=version)}"]
    lines.extend(f"{indent}{line}".rstrip() for line in view.body.text.strip().splitlines())
    return "\n".join(lines)


def comments_text(views: list[CommentView], *, users_shown: bool) -> str:
    return "\n".join(comment_block(view, users_shown=users_shown) for view in views)


def run_comments(ctx: Context, args: argparse.Namespace) -> int:
    if args.last is not None and args.last < 1:
        raise UsageError("--last must be at least 1.", hint="--last 3 lists the three newest comments.")
    found = ctx.app.comments.find.execute(
        args.ref,
        inline=args.inline,
        body_format=args.format,
        with_users=args.with_users,
        since=args.since,
        last=args.last or 0,
        resolution=args.resolution,
    )
    rows = [comment_row(view) for view in found.comments]
    document = {"pageId": found.page_id, "total": found.total, "count": len(rows), "since": found.since or None, "comments": rows}
    columns = COMMENT_COLUMNS + ([("AUTHOR", "author.displayName")] if args.with_users else []) + [("TEXT", "body.value")]

    def text() -> str:
        if found.comments:
            return comments_text(found.comments, users_shown=args.with_users)
        return "No comments." if not found.total else f"No comments match the options; the page has {found.total}."

    print_list(ctx, args, payload=document, rows=rows, list_key="comments", columns=columns, plain=text, format_dest="list_format")
    return 0


# -- comment -------------------------------------------------------------------------------------


def comment_text(result: CommentResult) -> str:
    if result.dry_run:
        return f"Dry run: page {result.page_id} exists; nothing was sent\n{pretty(shortened(result.payload))}"
    return f"Commented on page {result.page_id}" + (f" (comment {result.comment_id})" if result.comment_id else "")


def change_json(result: CommentChange) -> dict[str, Any]:
    return {
        "action": result.action,
        "dryRun": result.dry_run,
        "pageId": result.page_id,
        "commentId": result.comment_id,
        "kind": result.kind,
        "versionFrom": result.version_from,
        "versionTo": result.version_to,
        "updated": result.updated or None,
        "resolution": result.resolution or None,
        "byMe": result.by_me,
        "diff": result.diff or None,
        "lost": list(result.lost),
        "warnings": result.warnings,
        "payload": result.payload,
        "payloadRedacted": result.redacted,
    }


def _subject(result: CommentChange) -> str:
    """`Comment 4001 of page 2002`, or `Dry run: comment 4001 of page 2002` at the start of a sentence."""
    where = f"comment {result.comment_id} of page {result.page_id}"
    return f"Dry run: {where}" if result.dry_run else where[0].upper() + where[1:]


def edit_text(result: CommentChange) -> str:
    if result.action == "unchanged":
        return f"{_subject(result)} has this text already; nothing was sent"
    versions = f"version {result.version_from} -> {result.version_to}"
    if not result.dry_run:
        note = f"\nWarning: dropped what Markdown cannot say: {', '.join(result.lost)}." if result.lost else ""
        return f"Edited comment {result.comment_id} of page {result.page_id} ({versions}){note}"
    lines = [f"{_subject(result)} would go from version {result.version_from} to {result.version_to}; nothing was sent", result.diff, "", "Would send:", pretty(result.payload)]
    if result.lost:
        lines.append(f"This replaces what Markdown cannot say and drops: {', '.join(result.lost)}.")
    return "\n".join(lines)


def resolution_text(result: CommentChange, *, resolved: bool) -> str:
    if result.action == "unchanged":
        return f"{_subject(result)} is {'resolved' if resolved else 'open'} already; nothing was sent"
    versions = f"version {result.version_from} -> {result.version_to}"
    if result.dry_run:
        text = f"{_subject(result)} would be {result.action} ({versions}); nothing was sent\n{pretty(result.payload)}"
        if result.redacted:
            text += "\nThe text of the comment is shown without the people and addresses in it (--with-users shows it as it is); what is sent is the comment as it is."
        return text
    return f"{result.action.capitalize()} comment {result.comment_id} of page {result.page_id} ({versions})"


MODES = (("get", "--get"), ("edit", "--edit"), ("resolve", "--resolve"), ("reopen", "--reopen"))
CHANGES = "--edit, --resolve and --reopen"
# The options that belong to some of the modes: (option, what it applies to, the modes it applies to). A mode is `add` when none of the four is given.
ONLY = (
    ("--reply-to", "adding a comment", ("add",)),
    ("--with-users", "--get, --resolve and --reopen", ("get", "resolve", "reopen")),
    ("--if-version", CHANGES, ("edit", "resolve", "reopen")),
    ("--if-unchanged-since", CHANGES, ("edit", "resolve", "reopen")),
    ("--force", "--edit", ("edit",)),
    ("--dry-run", f"adding a comment, {CHANGES}", ("add", "edit", "resolve", "reopen")),
    ("--format", "adding a comment, --edit and --get", ("add", "edit", "get")),
)
MODE_HINT = (
    "Pass --text or --file to add a comment, --get ID to read one, --edit ID with the new text to change one, --resolve ID or --reopen ID for an inline "
    "comment. `conflu comments PAGE` lists the comments."
)


def comment_mode(args: argparse.Namespace) -> str:
    """add, get, edit, resolve or reopen: what the command is asked to do. A usage error names the options that do not go together."""
    chosen = [(mode, flag) for mode, flag in MODES if getattr(args, mode) is not None]
    if len(chosen) > 1:
        raise UsageError(f"{' and '.join(flag for _, flag in chosen)} cannot be combined.", hint="Use one of them at a time.")
    mode = chosen[0][0] if chosen else "add"
    has_text = args.text is not None or args.file is not None
    if mode in ("get", "resolve", "reopen") and has_text:
        raise UsageError(f"--{mode} cannot be combined with --text or --file.", hint="The text is for adding a comment, or the new text of --edit.")
    if mode in ("add", "edit") and not has_text:
        raise UsageError("Nothing to do." if mode == "add" else "--edit needs the new text.", hint=MODE_HINT)
    if args.file is not None and not args.file.strip():
        raise ValidationError("--file is empty: it needs the name of a file.", hint="`--file -` reads standard input; --text takes a short text.")
    given = {
        "--reply-to": args.reply_to is not None,
        "--with-users": args.with_users,
        "--if-version": args.if_version is not None,
        "--if-unchanged-since": args.if_unchanged_since is not None,
        "--force": args.force,
        "--dry-run": args.dry_run,
        "--format": args.format != "markdown",
    }
    for flag, applies, modes in ONLY:
        if given[flag] and mode not in modes:
            raise UsageError(f"{flag} applies to {applies}.", hint=f"Leave {flag} out, or use {applies}.")
    if mode in ("add", "edit") and args.format == "text":
        raise UsageError("--format text shows a comment (--get): a comment is written in markdown or storage format.", hint="Use --format markdown or --format storage.")
    return mode


def show_comment(ctx: Context, args: argparse.Namespace) -> None:
    view = ctx.app.comments.get.execute(args.ref, args.get, body_format=args.format, with_users=args.with_users)
    page_id = parse_page_id(args.ref)
    if ctx.json_mode:
        ctx.print_json({"pageId": page_id, **comment_row(view, version=True)})
    else:
        ctx.print(comment_block(view, users_shown=args.with_users, version=True))


def edit_comment(ctx: Context, args: argparse.Namespace) -> None:
    text = text_option(ctx, args.text, args.file, "comment") or ""
    result = ctx.app.comments.edit.execute(
        args.ref,
        args.edit,
        text,
        body_format=args.format,
        dry_run=args.dry_run,
        if_version=args.if_version,
        if_unchanged_since=args.if_unchanged_since,
        force=args.force,
    )
    for warning in result.warnings:
        ctx.diagnostics.warn(warning)
    ctx.print_json(change_json(result)) if ctx.json_mode else ctx.print(edit_text(result))


def resolve_comment(ctx: Context, args: argparse.Namespace, mode: str) -> None:
    resolved = mode == "resolve"
    result = ctx.app.comments.resolution.execute(
        args.ref,
        args.resolve if resolved else args.reopen,
        resolved=resolved,
        dry_run=args.dry_run,
        if_version=args.if_version,
        if_unchanged_since=args.if_unchanged_since,
        with_users=args.with_users,
    )
    ctx.print_json(change_json(result)) if ctx.json_mode else ctx.print(resolution_text(result, resolved=resolved))


def add_comment(ctx: Context, args: argparse.Namespace) -> None:
    body = text_option(ctx, args.text, args.file, "comment") or ""
    result = ctx.app.add_comment.execute(args.ref, body, body_format=args.format, reply_to=args.reply_to, dry_run=args.dry_run)
    if ctx.json_mode:
        ctx.print_json({"pageId": result.page_id, "dryRun": result.dry_run, "commentId": result.comment_id or None, "payload": result.payload})
    else:
        ctx.print(comment_text(result))


def run_comment(ctx: Context, args: argparse.Namespace) -> int:
    mode = comment_mode(args)
    if mode == "get":
        show_comment(ctx, args)
    elif mode == "edit":
        edit_comment(ctx, args)
    elif mode in ("resolve", "reopen"):
        resolve_comment(ctx, args, mode)
    else:
        add_comment(ctx, args)
    return 0


COMMANDS = (
    Command(
        name="comments",
        group=GROUP,
        summary="Show the comments of a page",
        when="Use to read the discussion on a page. --inline adds the comments made on a piece of text, --since and --last pick the recent ones, "
        "--resolution the open or resolved inline ones.",
        description="Shows the footer comments, each conversation as its first comment followed by the replies. Authors and mentions are hidden "
        "unless you add --with-users; every comment has byMe and authorRef instead (a pseudonym of its author, the same for the same token).",
        args=(
            Arg(("ref",), "Page id, or the address of the page.", required=True, metavar="PAGE"),
            Arg(("--inline",), "Also show the inline comments.", kind="flag"),
            Arg(
                ("--since",),
                "Only comments saved in the last 2d, 12h or 1w, or since a date (2026-10-15) or an ISO time; without an offset it is UTC. A comment is saved when it is "
                "written, and again when somebody changes it.",
                metavar="WHEN",
            ),
            Arg(("--last",), "Only the N newest comments (of those that --since lets through).", kind="int", metavar="N"),
            Arg(
                ("--resolution",),
                "Only the inline comments in this state: open, resolved, reopened or dangling (the text on the page is gone). The footer comments have none "
                "and are left out; open and reopened are two states.",
                kind="choice",
                choices=RESOLUTIONS,
                metavar="STATE",
            ),
            Arg(("--format",), "Format of the comment text.", kind="choice", choices=BODY_FORMATS, default="markdown"),
            Arg(("--with-users",), "Show who wrote each comment. Refused when CONFLUENCE_HIDE_USERS=true.", kind="flag"),
            SELECT,
            LIST_FORMAT,
        ),
        examples=(
            Example("conflu comments 123456"),
            Example("conflu comments 123456 --inline --json"),
            Example("conflu comments 123456 --inline --select id,kind,updated --list-format tsv", "one line per comment, without the text"),
            Example("conflu comments 123456 --since 2d --last 3", "the newest three of the last two days"),
            Example("conflu comments 123456 --resolution open --json", "the inline comments that nobody has resolved"),
        ),
        notes=(
            "`--format` is the format of the comment text; `--list-format` is how the list is printed (the other list commands call that `--format`).",
            "`--since` and `--last` look at the time a comment was last saved: when it was written, unless somebody changed it.",
            "`byMe` and the `(you)` mark need to know whom the token belongs to: one more request, and only when there are comments. `authorRef` is a stable "
            "pseudonym (`a-` and eight hexadecimal digits) of the author, keyed with the API token, so the comments of one person can be told apart while names stay hidden.",
        ),
        json_output=True,
        output="pageId, total (before --since and --last), count, since (the moment --since named, or null) and comments[]: id, kind (footer or inline), "
        "updated, parentId (null for the first comment of a conversation), resolution (inline comments), author (null unless --with-users), authorRef "
        "(null without a token), byMe (null when not known), body{format,value,dropped[]}; with --select only those (dotted) keys of every comment.",
        handler=run_comments,
    ),
    Command(
        name="comment",
        group=WORK,
        summary="Add, read or change a comment",
        when="Use to add a comment to a page or answer one (--reply-to), read one (--get), correct one you wrote (--edit), or resolve an inline comment "
        "(--resolve) and open it again (--reopen). Everyone who sees the page sees a comment: write or change one only when asked, preview with --dry-run.",
        description="Adds a footer comment, or with --reply-to an answer to a comment of that page. --get ID shows one comment; --edit ID replaces its text "
        "(--text or --file is the new text); --resolve ID and --reopen ID resolve an inline comment or open it again. They exclude each other. "
        "The text is Markdown unless --format says storage. A change reads the comment first, and its dry run shows a diff. It is refused when the "
        "new text holds [email] or [personal link] (what a reading puts in place of an address or a profile link), and when replacing with Markdown "
        "would lose a mention or a macro (--force allows that). --if-version and --if-unchanged-since refuse a change of a comment that has moved on "
        "(exit code 3). When nothing changes, nothing is sent. A comment is never deleted.",
        args=(
            Arg(("ref",), "Page id, or the address of the page.", required=True, metavar="PAGE"),
            Arg(
                ("--text",),
                "The comment, or with --edit its new text. A longer text is easier in a file: --file.",
                metavar="TEXT",
                not_a_path="the text of the comment itself, not the name of a file",
            ),
            FILE,
            Arg(("--get",), "Show this comment (`comments` lists the ids).", metavar="ID", not_a_path=ID_NOT_A_PATH),
            Arg(
                ("--edit",),
                "Replace the text of this comment with --text or --file. An inline comment stays as resolved or open as it is.",
                metavar="ID",
                not_a_path=ID_NOT_A_PATH,
            ),
            Arg(("--resolve",), "Resolve this inline comment.", metavar="ID", not_a_path=ID_NOT_A_PATH),
            Arg(("--reopen",), "Open this inline comment again.", metavar="ID", not_a_path=ID_NOT_A_PATH),
            Arg(
                ("--reply-to",),
                "When adding: the id of the comment to answer (`comments` lists them). It is read first and must be on this page (exit code 4 otherwise, "
                "also with --dry-run); the request names it in place of the page.",
                metavar="COMMENT",
                not_a_path=ID_NOT_A_PATH,
            ),
            Arg(
                ("--format",),
                "Format of the text: markdown, which is converted, or storage, which is sent as it is; with --get also text.",
                kind="choice",
                choices=BODY_FORMATS,
                default="markdown",
            ),
            Arg(
                ("--with-users",),
                "With --get: show who wrote the comment. With --resolve and --reopen: show the request as it is, with the people in the text of the comment. "
                "Refused when CONFLUENCE_HIDE_USERS=true.",
                kind="flag",
            ),
            Arg(
                ("--if-version",),
                "With --edit, --resolve and --reopen: refuse (exit code 3) unless the comment is at this version now (--get shows it).",
                kind="int",
                metavar="N",
            ),
            Arg(
                ("--if-unchanged-since",),
                "With --edit, --resolve and --reopen: refuse (exit code 3) when the comment was saved after this time (ISO 8601, for example when you read it). "
                "Checked again just before the write; the version number of the change is a second, atomic guard.",
                metavar="ISO",
            ),
            Arg(("--force",), "With --edit: replace a comment with Markdown even though what Markdown cannot say is lost.", kind="flag", overwrites=True),
            DRY_RUN,
        ),
        examples=(
            Example("conflu comment 123456 --text 'Reviewed, no findings.' --dry-run"),
            Example("conflu comment 123456 --file review.md"),
            Example("conflu comment 123456 --get 4001 --json"),
            Example("conflu comment 123456 --edit 4001 --file new.md --dry-run", "shows the diff, sends nothing"),
            Example("conflu comment 123456 --edit 4001 --text 'Fixed in 2.1.' --if-version 1"),
            Example("conflu comment 123456 --edit 4001 --text 'Fixed in 2.1.' --if-unchanged-since 2026-10-15T08:00:00Z"),
            Example("conflu comment 123456 --resolve 4003 --dry-run"),
            Example("conflu comment 123456 --reopen 4003"),
        ),
        notes=(
            POWERSHELL_TEXT_NOTE,
            "A change makes a new version of the comment; the earlier versions stay in Confluence. Confluence lets only the author change the text of a comment "
            "(exit code 5). A comment that somebody else changed meanwhile is exit code 3.",
            "--resolve and --reopen send the comment's own text back. The request that is printed leaves out the people and addresses in it (`payloadRedacted`) unless "
            "you add --with-users; what is sent is always the comment as it is.",
        ),
        writes=True,
        json_output=True,
        output="adding: pageId, dryRun, commentId (null in a dry run) and payload (exactly what is sent). --get: pageId, id, kind, updated, version, parentId, "
        "resolution, author (null unless --with-users), authorRef, byMe, body{format,value,dropped[]}. --edit, --resolve and --reopen: action (updated, "
        "resolved, reopened or unchanged), dryRun, pageId, commentId, kind, versionFrom, versionTo, updated, resolution, byMe, diff, lost[], warnings[], "
        "payload (what is sent, null when nothing is) and payloadRedacted (true when the printed payload leaves out the people and addresses in the "
        "text that --resolve and --reopen send back; --with-users shows it as it is).",
        destructive=True,
        handler=run_comment,
    ),
)
