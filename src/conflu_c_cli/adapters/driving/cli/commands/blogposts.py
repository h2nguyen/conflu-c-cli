"""Commands about blog posts: blogposts, blogpost, blogpost-create, blogpost-update."""
from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from .....application.rendering import BODY_FORMATS, INPUT_FORMATS, storage_from_input
from .....domain.blogposts import BlogpostDraft
from .....domain.drafts import PageChanges
from .....domain.errors import UsageError
from .....domain.frontmatter import split_list
from .....domain.privacy import redact_text
from ..listing import FORMAT, SELECT, print_list
from ..render import key_values, table
from ..runtime import Context
from ..spec import READS_FILE, Arg, Command, Example
from ._common import LIMIT_HELP, POWERSHELL_TEXT_NOTE, check_limit, comment_json, page_body_json, pretty, replacing_text_option, shortened, text_option, user_json, user_name
from ._outfile import FORCE, deliver, out_option, prepare_out
from .pages import CURSOR, version_json, view_tail

if TYPE_CHECKING:
    from .....application.blogposts import BlogpostList, BlogpostWrite
    from .....application.pages import PageView
    from .....domain.model import Page

GROUP = "Blog posts"
STATUSES = ("current", "trashed", "deleted")  # what the REST API allows for blog posts; a page may also be archived, a blog post cannot
SORTS = ("id", "created-date", "modified-date")
BODY = Arg(
    ("--body",),
    "The text, in the --format. A longer text is easier in a file: --file.",
    metavar="TEXT",
    not_a_path="the text itself, written on the command line; the option that names a file is --file",
)
FILE = Arg(("--file",), "Read the text from a file (`-` is standard input).", metavar="FILE", path=READS_FILE)
TEXT_FORMAT = Arg(
    ("--format",),
    "Format of the text: markdown, which is converted, or storage, which is sent as it is.",
    kind="choice",
    choices=INPUT_FORMATS,
    default="markdown",
)
DRY_RUN = Arg(("--dry-run",), "Show what would be sent and check that the space (or the blog post) exists. Sends nothing.", kind="flag")
SINCE = Arg(
    ("--if-unchanged-since",),
    "Refuse (exit code 3) when the blog post changed in Confluence after this time (ISO 8601, for example the time you read it). "
    "It is a check just before the write, not a lock; the version number of an update is a second, atomic guard.",
    metavar="ISO",
)


# -- blogposts -----------------------------------------------------------------------------------


def blogpost_row_json(post: Page) -> dict[str, Any]:
    return {
        "id": post.id,
        "title": post.title,
        "status": post.status,
        "spaceId": post.space_id,
        "version": post.version_number or None,
        "created": post.created,
        "updated": post.updated,
        "url": post.url,
    }


BLOGPOST_COLUMNS = [("ID", "id"), ("TITLE", "title"), ("STATUS", "status"), ("VERSION", "version"), ("CREATED", "created")]


def blogposts_text(result: BlogpostList) -> str:
    if not result.blogposts:
        return "No blog posts."
    return table(["ID", "TITLE", "STATUS", "VERSION", "CREATED"], [(p.id, p.title, p.status, p.version_number or "", p.created) for p in result.blogposts])


def run_blogposts(ctx: Context, args: argparse.Namespace) -> int:
    check_limit(args.limit)
    if args.desc and not args.sort:
        raise UsageError("--desc needs --sort.", hint="For example --sort created-date --desc.")
    result = ctx.app.blogposts.list_blogposts.execute(
        space=args.space,
        title=args.title,
        status=args.status,
        sort=("-" if args.desc else "") + (args.sort or ""),
        limit=args.limit,
        cursor=args.cursor or "",
        fetch_everything=args.all,
    )
    rows = [blogpost_row_json(post) for post in result.blogposts]
    document = {
        "space": result.space.key if result.space else None,
        "count": len(result.blogposts),
        "nextCursor": result.next_cursor or None,
        "truncated": result.truncated,
        "blogposts": rows,
    }
    if print_list(ctx, args, payload=document, rows=rows, list_key="blogposts", columns=BLOGPOST_COLUMNS, plain=lambda: blogposts_text(result)) or not result.blogposts:
        return 0
    if result.next_cursor:
        ctx.diagnostics.info(f"More blog posts follow. Continue with --cursor {result.next_cursor}, or use --all.")
    if result.truncated:
        ctx.diagnostics.warn("The list was cut short at its limit; narrow it with --title or --space.")
    return 0


# -- blogpost ------------------------------------------------------------------------------------


def blogpost_json(view: PageView) -> dict[str, Any]:
    post = view.page
    data: dict[str, Any] = {
        "id": post.id,
        "title": post.title,
        "status": post.status,
        "spaceId": post.space_id,
        "spaceKey": post.space_key,
        "url": post.url,
        "version": version_json(post.version),
        "created": post.created,
        "updated": post.updated,
        "labels": [label.name for label in post.labels],
        "author": user_json(post.author),
    }
    data["body"] = page_body_json(view.body)
    if view.outline is not None:
        data["outline"] = [{"index": h.index, "level": h.level, "title": h.title, "chars": h.chars} for h in view.outline]
    if view.comments_shown:
        data["comments"] = [comment_json(item) for item in view.comments]
    return data


def blogpost_text(view: PageView) -> str:
    post = view.page
    pairs: list[tuple[str, Any]] = [
        ("Space", post.space_key),
        ("Status", post.status),
        ("Version", post.version_number or ""),
        ("Labels", ", ".join(label.name for label in post.labels)),
        ("Created", post.created),
        ("Updated", post.updated),
    ]
    if view.users_shown:
        pairs += [("Author", user_name(post.author)), ("Saved by", user_name(post.version.author if post.version else None))]
    return "\n".join([f"{post.title}  [{post.id}]", post.url, "", key_values(pairs), *view_tail(view, "blog post")])


def run_blogpost(ctx: Context, args: argparse.Namespace) -> int:
    if args.body_only and (args.no_body or args.raw or args.comments or args.outline):
        raise UsageError("--body-only prints the body and nothing else.", hint="Leave out --no-body, --raw, --comments and --outline.")
    if args.raw and (args.outline or args.section or args.max_chars):
        raise UsageError("--raw prints Confluence's own JSON, which has no parts.", hint="Leave out --outline, --section and --max-chars.")
    if args.raw and args.comments:
        raise UsageError("--raw prints Confluence's own JSON of the blog post, which has no comments.", hint="Leave out --comments, or leave out --raw.")
    prepare_out(ctx, args, body_only=args.body_only, example="conflu blogpost 123456 --format storage --body-only --out post.xml")
    view = ctx.app.blogposts.view_blogpost.execute(
        args.ref,
        body_format=args.format,
        with_body=not args.no_body,
        with_comments=args.comments,
        with_users=args.with_users,
        want_raw=args.raw,
        outline=args.outline,
        section=args.section or "",
        max_chars=args.max_chars or 0,
    )
    if args.body_only:
        deliver(ctx, args, view.body.text if view.body is not None else "")
        if view.body is not None and view.body.dropped:
            ctx.diagnostics.info(f"The Markdown cannot show: {', '.join(view.body.dropped)}.")
    elif args.raw:
        ctx.print_json(view.raw)
        return 0
    elif ctx.json_mode:
        ctx.print_json(blogpost_json(view))
        return 0
    else:
        ctx.print(blogpost_text(view))
        if view.body is not None and view.body.dropped:
            ctx.diagnostics.info(
                f"The Markdown cannot show: {', '.join(view.body.dropped)}. `--format storage` shows the blog post as Confluence keeps it."
            )
    body = view.body
    if body is not None and body.truncated:
        ctx.diagnostics.info(
            f"The text was cut: {len(body.text)} of {body.total_chars} characters are shown. Read a part with --section "
            f"(`--outline` lists the headings), or more with a larger --max-chars."
        )
    return 0


# -- blogpost-create and blogpost-update ---------------------------------------------------------


def write_json(result: BlogpostWrite) -> dict[str, Any]:
    post = result.blogpost
    payload = result.payload
    title = post.title if post else redact_text(payload.get("title", "") if isinstance(payload, dict) else "")
    return {
        "action": result.action,
        "dryRun": result.dry_run,
        "blogpostId": post.id if post else None,
        "title": title,
        "url": post.url if post else None,
        "versionFrom": result.version_from or None,
        "versionTo": result.version_to or None,
        "lost": list(result.lost),
        "labels": result.labels,
        "payload": payload,
    }


def update_json(result: BlogpostWrite) -> dict[str, Any]:
    return {**write_json(result), "payloadRedacted": result.redacted}


def write_text(result: BlogpostWrite) -> str:
    post = result.blogpost
    ident = post.id if post else ""
    title = post.title if post else ""
    where = f"\n{post.url}" if post and post.url else ""
    if result.action == "unchanged":
        return f"Nothing to change: blog post {ident} is already as asked."
    if result.dry_run:
        if result.action == "created":
            lines = [f"Dry run: a blog post would be created; nothing was sent\n{pretty(shortened(result.payload))}"]
            if result.labels:
                lines.append(f"Labels it would add: {', '.join(result.labels)}")
        else:
            lines = [
                f"Dry run: blog post {ident} '{title}' would go from version {result.version_from} to "
                f"{result.version_to}; nothing was sent\n{pretty(shortened(result.payload))}"
            ]
        if result.redacted:
            lines.append("The request is shown without the people and addresses that the body holds; --with-users shows it as it is.")
        if result.lost:
            lines.append(f"This replaces what Markdown cannot say and drops: {', '.join(result.lost)}.")
        return "\n".join(lines)
    if result.action == "created":
        labels = f" with the labels {', '.join(result.labels)}" if result.labels else ""
        return f"Created blog post {ident}: {title}{labels}{where}"
    note = f"\nWarning: dropped what Markdown cannot say: {', '.join(result.lost)}." if result.lost else ""
    return f"Updated blog post {ident}: {title} (version {result.version_from} -> {result.version_to}){where}{note}"


def run_blogpost_create(ctx: Context, args: argparse.Namespace) -> int:
    text = text_option(ctx, args.body, args.file, "body")
    draft = BlogpostDraft(
        space=args.space,
        title=args.title,
        body=storage_from_input(text, args.format) if text is not None else "",
        labels=split_list(args.labels or ""),
    )
    result = ctx.app.blogposts.create_blogpost.execute(draft, dry_run=args.dry_run)
    ctx.print_json(write_json(result)) if ctx.json_mode else ctx.print(write_text(result))
    return 0


def run_blogpost_update(ctx: Context, args: argparse.Namespace) -> int:
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
    result = ctx.app.blogposts.update_blogpost.execute(
        args.ref,
        changes,
        dry_run=args.dry_run,
        if_version=args.if_version,
        if_unchanged_since=args.if_unchanged_since,
        force=args.force,
        with_users=args.with_users,
    )
    ctx.print_json(update_json(result)) if ctx.json_mode else ctx.print(write_text(result))
    return 0


COMMANDS = (
    Command(
        name="blogposts",
        group=GROUP,
        summary="List the blog posts of a space",
        when="Use to list the blog posts of a space with their ids, versions and dates, or to look one up by its exact title (--title). Read one with `blogpost`; to look for words inside blog posts use `search --type blogpost`.",
        description="Lists the blog posts of the current space (`conflu use`) or of the space given with --space; without either, those of the whole site. "
        "A blog post is not a page: it has no parent, and it is not in `pages`. Blog posts can share a title. The ids are what `blogpost` takes.",
        args=(
            Arg(("--space",), "Space key. Default: the current space.", metavar="KEY"),
            Arg(("--title",), "Only the blog posts with exactly this title.", metavar="TEXT"),
            Arg(("--status",), "Status of the blog posts (a blog post is never archived).", kind="choice", choices=STATUSES, default="current"),
            Arg(("--sort",), "Order of the list.", kind="choice", choices=SORTS),
            Arg(("--desc",), "Sort downwards (needs --sort).", kind="flag"),
            Arg(("--limit",), LIMIT_HELP, kind="int", default=25, metavar="N"),
            CURSOR,
            Arg(("--all",), "Fetch every blog post of the list instead of one part of it (ignores --limit and --cursor).", kind="flag"),
            SELECT,
            FORMAT,
        ),
        examples=(
            Example("conflu blogposts --space ENG --sort created-date --desc --limit 10", "the latest ones"),
            Example("conflu blogposts --space ENG --title 'Release 2026.10 is out' --json"),
            Example("conflu blogposts --space ENG --all --select id,title,created --format tsv", "only these columns, as TSV for a script or a spreadsheet"),
        ),
        json_output=True,
        output="space (key, [hidden] for a personal space, or null), count, nextCursor (null on the last page), truncated and blogposts[]: id, title, status, spaceId, version, created, updated, url; "
        "with --select only those (dotted) keys of every blog post.",
        handler=run_blogposts,
    ),
    Command(
        name="blogpost",
        group=GROUP,
        summary="Show one blog post",
        when="Use to read a blog post whose id or address you know (`blogposts` finds it). Start with --outline and read only the --section you need. For a page use `page`.",
        description="Shows the title, space, version, labels and the body, as `page` does. The body is converted from Confluence's storage format to Markdown "
        "(or plain text; with --format storage it is shown as Confluence keeps it). People and mentions are hidden unless you add --with-users. "
        "The blog post can be given by its id or by the address as copied from the browser (.../blog/2026/10/15/123456/Title). "
        "--comments adds the footer and the inline comments with their replies.",
        args=(
            Arg(("ref",), "Blog post id, or the address of the blog post as copied from the browser.", required=True, metavar="BLOGPOST"),
            Arg(("--format",), "Format of the body.", kind="choice", choices=BODY_FORMATS, default="markdown"),
            Arg(("--outline",), "Show the headings with the size of each section, and not the body. Then read one part with --section.", kind="flag"),
            Arg(("--section",), "Show only this section: the text of its heading (a part of it is enough when it is unique) or its number from --outline.", metavar="TITLE|N"),
            Arg(("--max-chars",), "Cut the body to about N characters, at the end of a paragraph; the answer says that it was cut.", kind="int", metavar="N"),
            Arg(("--no-body",), "Leave the body out and show only the properties of the blog post.", kind="flag"),
            Arg(("--body-only",), "Print the body and nothing else, for a file or a pipe. Wins over --json.", kind="flag"),
            Arg(("--comments",), "Also show the comments (footer and inline) with their replies.", kind="flag"),
            Arg(("--with-users",), "Show people (author, who saved the version, comment authors) and the account ids of mentions. Refused when CONFLUENCE_HIDE_USERS=true.", kind="flag"),
            Arg(("--raw",), "Print Confluence's own JSON for the blog post (people removed unless --with-users). Not with --comments, --outline, --section or --max-chars, which are not in it.", kind="flag"),
            out_option(),
            FORCE,
        ),
        examples=(
            Example("conflu blogpost 123456", "the blog post as Markdown"),
            Example("conflu blogpost https://example.atlassian.net/wiki/spaces/ENG/blog/2026/10/15/123456/Release+2026.10 --outline"),
            Example("conflu blogpost 123456 --comments --json", "with its comments, as JSON for a script or an agent"),
            Example("conflu blogpost 123456 --section 'Known issues' --max-chars 3000", "only that section, cut if it is longer"),
            Example("conflu blogpost 123456 --format storage --body-only --out post.xml", "only the source, into a file that the program writes as UTF-8"),
        ),
        notes=(
            "The Markdown is a reading copy: macros, layouts, mentions and the like cannot be shown in it. Both the text and the JSON name what is missing (`dropped`).",
            "Storage format read without --with-users has the account ids of mentions blanked. `blogpost-update` refuses such a body.",
            "To save the body, use --body-only --out FILE and not `>`: the program then writes the file itself, as UTF-8 without a byte-order mark and with plain line ends, and says so "
            "in one line (`Wrote N bytes to FILE`; `file` and `bytes` with --json). Windows PowerShell 5.1 re-encodes what `>` saves and damages every character that is not ASCII. "
            "A file that exists is not replaced without --force, and never the settings file of the CLI. It writes a file on this computer and changes nothing in Confluence.",
        ),
        json_output=True,
        output="id, title, status, spaceId, spaceKey, url, version{number,created,message,minorEdit,author}, created, updated, labels[], author (null unless --with-users), "
        "body{format,value,dropped[],section,truncated,totalChars} (null with --no-body or --outline), outline[{index,level,title,chars}] (with --outline), comments[] (with --comments); "
        "with --body-only --out: file, bytes.",
        handler=run_blogpost,
    ),
    Command(
        name="blogpost-create",
        group=GROUP,
        summary="Create one blog post",
        when="Use to publish a new blog post in a space. Preview with --dry-run. Blog posts can share a title, so the CLI does not look for one that is there already.",
        description="Creates a blog post in a space. The body is Markdown (converted to storage format) unless --format says storage; a blog post without a body is fine. "
        "The dry run proves that the space exists and shows the payload. Unlike a page, a blog post may have the same title as another one: nothing is checked, and "
        "when Confluence refuses a title all the same its message is shown (exit code 6). The labels are added with a second request; when that fails the blog post is there and the error says so.",
        args=(
            Arg(("--space",), "Space key. Default: the current space.", metavar="KEY"),
            Arg(("--title",), "The title of the blog post.", required=True, metavar="TEXT"),
            BODY,
            FILE,
            TEXT_FORMAT,
            Arg(("--labels",), "Labels to put on the blog post, comma separated.", metavar="a,b"),
            DRY_RUN,
        ),
        examples=(
            Example("conflu blogpost-create --space ENG --title 'Release 2026.10 is out' --file post.md --dry-run"),
            Example("conflu blogpost-create --title 'Weekly update' --body 'Nothing to report.' --labels news,weekly"),
        ),
        notes=(POWERSHELL_TEXT_NOTE, "Read the id of the new blog post from `--json` (`blogpostId`); never guess it."),
        writes=True,
        json_output=True,
        output="action (created), dryRun, blogpostId (null in a dry run), title, url, versionFrom (null), versionTo, lost[], labels[] and payload (exactly what is sent).",
        handler=run_blogpost_create,
    ),
    Command(
        name="blogpost-update",
        group=GROUP,
        summary="Change the title or the body of a blog post",
        when="Use to change the title or the body of one existing blog post. Preview with --dry-run, guard with --if-version, and prefer --append to replacing the body.",
        description="Changes the title, the body, or both, as `update` does for a page. The text replaces the body, or is put behind it (--append) or in front of it "
        "(--prepend); the two keep everything that is there. Markdown (the default format) is converted to storage format. Replacing a body with Markdown is refused "
        "when the blog post holds what Markdown cannot say (macros, mentions, layouts ...) unless you add --force; `conflu blogpost ID --json` shows it under `dropped`. "
        "The new version number is the current one plus one, so Confluence itself refuses (exit code 3) when somebody saved in between. "
        "A change of the title alone sends the body along unchanged: the API has no call for the title only.",
        args=(
            Arg(("ref",), "Blog post id, or the address of the blog post.", required=True, metavar="BLOGPOST"),
            Arg(("--title",), "The new title.", metavar="TEXT"),
            BODY,
            FILE,
            TEXT_FORMAT,
            Arg(("--append",), "Put the text behind the current body instead of replacing it.", kind="flag"),
            Arg(("--prepend",), "Put the text in front of the current body instead of replacing it.", kind="flag"),
            Arg(("--message",), "A message stored with the new version.", metavar="TEXT"),
            Arg(("--if-version",), "Refuse (exit code 3) unless the blog post is at this version now.", kind="int", metavar="N"),
            SINCE,
            Arg(("--force",), "Replace a body with Markdown even though what Markdown cannot say is lost.", kind="flag", overwrites=True),
            Arg(
                ("--with-users",),
                "Show the payload exactly as it is sent, with the people and addresses that the body holds, and the title as it is. Refused when CONFLUENCE_HIDE_USERS=true.",
                kind="flag",
            ),
            DRY_RUN,
        ),
        examples=(
            Example("conflu blogpost-update 123456 --title 'Release 2026.10 is out!' --dry-run"),
            Example("conflu blogpost-update 123456 --file addendum.md --append --message 'Added the known issues' --if-version 3"),
            Example("conflu blogpost-update 123456 --file post.xml --format storage --dry-run"),
        ),
        notes=(
            POWERSHELL_TEXT_NOTE,
            "The `payload` holds the whole body, also for a change of the title, because the API has no call for the title only. Without --with-users it is a copy "
            "without the people and addresses that the body holds (`payloadRedacted` is then true); the request that is sent has them, so mentions survive.",
        ),
        writes=True,
        destructive=True,
        json_output=True,
        output="action (updated or unchanged), dryRun, blogpostId, title, url, versionFrom, versionTo, lost[], labels[], payload (what is sent; without --with-users a copy that "
        "does not name the people in the body) and payloadRedacted (true when the payload shown differs from the request).",
        handler=run_blogpost_update,
    ),
)
