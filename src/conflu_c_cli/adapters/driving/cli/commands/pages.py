"""Commands that read pages: page, pages, tree, versions, search, export."""
from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from .....application.rendering import BODY_FORMATS, INPUT_FORMATS
from .....application.search import MATCH_MODES
from .....domain.cql import CONTENT_TYPES
from .....domain.errors import UsageError
from ..render import key_values, one_line, table
from ..runtime import Context
from ..spec import Arg, Command, Example
from ._common import LIMIT_HELP, check_limit, comment_json, comments_text, page_body_json, pretty, user_json, user_name

if TYPE_CHECKING:
    from .....application.pages import PageView
    from .....application.search import SearchResult
    from .....domain.model import Page

GROUP = "Read"
SORTS = ("id", "created-date", "modified-date", "title")

CURSOR = Arg(("--cursor",), "Continue after the end of the previous answer: pass its nextCursor.", metavar="TOKEN")
ALL = "Fetch every page of the list instead of one (ignores --limit and --cursor)."


# -- page ----------------------------------------------------------------------------------------


def _version_json(version: Any) -> dict[str, Any] | None:
    if version is None:
        return None
    return {
        "number": version.number,
        "created": version.created,
        "message": version.message,
        "minorEdit": version.minor_edit,
        "author": user_json(version.author),
    }


def page_json(view: PageView, *, with_ancestors: bool) -> dict[str, Any]:
    page = view.page
    data: dict[str, Any] = {
        "id": page.id,
        "title": page.title,
        "status": page.status,
        "spaceId": page.space_id,
        "spaceKey": page.space_key,
        "parentId": page.parent_id or None,
        "url": page.url,
        "version": _version_json(page.version),
        "created": page.created,
        "updated": page.updated,
        "labels": [label.name for label in page.labels],
        "author": user_json(page.author),
        "owner": user_json(page.owner),
    }
    if with_ancestors:
        data["ancestors"] = [{"id": ref.id, "title": ref.title} for ref in page.ancestors]
    data["body"] = page_body_json(view.body)
    if view.outline is not None:
        data["outline"] = [{"index": h.index, "level": h.level, "title": h.title, "chars": h.chars} for h in view.outline]
    if view.comments_shown:
        data["comments"] = [comment_json(item) for item in view.comments]
    return data


def page_text(view: PageView) -> str:
    page = view.page
    pairs: list[tuple[str, Any]] = [
        ("Space", page.space_key),
        ("Status", page.status),
        ("Version", page.version_number or ""),
        ("Parent", page.parent_id),
    ]
    if page.ancestors:
        pairs.append(("Path", " > ".join([ref.title or ref.id for ref in page.ancestors] + [page.title])))
    if view.body is not None and view.body.section:
        pairs.append(("Section", view.body.section))
    pairs += [("Labels", ", ".join(label.name for label in page.labels)), ("Created", page.created), ("Updated", page.updated)]
    if view.users_shown:
        pairs += [
            ("Author", user_name(page.author)),
            ("Owner", user_name(page.owner)),
            ("Saved by", user_name(page.version.author if page.version else None)),
        ]
    lines = [f"{page.title}  [{page.id}]", page.url, "", key_values(pairs)]
    if view.outline is not None:
        lines += ["", "Outline (read one part with --section TITLE or --section NUMBER):"]
        lines += [f"{h.index:>4}. {'  ' * (h.level - 1)}{one_line(h.title)}  ({h.chars} characters)" for h in view.outline]
        if not view.outline:
            lines.append("      (the page has no headings: read it whole, or cut it with --max-chars)")
    if view.body is not None:
        lines += ["", view.body.text.rstrip() or "(the page is empty)"]
    if view.comments_shown:
        lines += ["", f"Comments: {len(view.comments)}"]
        if view.comments:
            lines.append(comments_text(view.comments, users_shown=view.users_shown))
    else:
        lines += ["", "Comments: show them with --comments"]
    return "\n".join(line for line in lines if line is not None)


def run_page(ctx: Context, args: argparse.Namespace) -> int:
    if args.body_only and (args.no_body or args.raw or args.comments or args.ancestors or args.outline):
        raise UsageError("--body-only prints the body and nothing else.", hint="Leave out --no-body, --raw, --comments, --ancestors and --outline.")
    if args.raw and (args.outline or args.section or args.max_chars):
        raise UsageError("--raw prints Confluence's own JSON, which has no parts.", hint="Leave out --outline, --section and --max-chars.")
    view = ctx.app.view_page.execute(
        args.ref,
        body_format=args.format,
        with_body=not args.no_body,
        with_comments=args.comments,
        with_users=args.with_users,
        with_ancestors=args.ancestors,
        want_raw=args.raw,
        outline=args.outline,
        section=args.section or "",
        max_chars=args.max_chars or 0,
        space=args.space or "",
    )
    if args.body_only:
        ctx.print(view.body.text if view.body is not None else "")
        if view.body is not None and view.body.dropped:
            ctx.diagnostics.info(f"The Markdown cannot show: {', '.join(view.body.dropped)}.")
        _say_if_cut(ctx, view)
        return 0
    if args.raw:
        ctx.print(pretty(view.raw))
        return 0
    if ctx.json_mode:
        ctx.print_json(page_json(view, with_ancestors=args.ancestors))
        return 0
    ctx.print(page_text(view))
    if view.body is not None and view.body.dropped:
        ctx.diagnostics.info(
            f"The Markdown cannot show: {', '.join(view.body.dropped)}. `--format storage` shows the page as Confluence keeps it."
        )
    _say_if_cut(ctx, view)
    return 0


def _say_if_cut(ctx: Context, view: PageView) -> None:
    body = view.body
    if body is not None and body.truncated:
        ctx.diagnostics.info(
            f"The text was cut: {len(body.text)} of {body.total_chars} characters are shown. Read a part with --section "
            f"(`--outline` lists the headings), or more with a larger --max-chars."
        )


# -- pages ---------------------------------------------------------------------------------------


def page_row_json(page: Page) -> dict[str, Any]:
    return {
        "id": page.id,
        "title": page.title,
        "status": page.status,
        "spaceId": page.space_id,
        "parentId": page.parent_id or None,
        "version": page.version_number or None,
        "updated": page.updated,
        "url": page.url,
    }


def run_pages(ctx: Context, args: argparse.Namespace) -> int:
    check_limit(args.limit)
    if args.desc and not args.sort:
        raise UsageError("--desc needs --sort.", hint="For example --sort modified-date --desc.")
    result = ctx.app.list_pages.execute(
        space=args.space or "",
        title=args.title or "",
        status=args.status,
        sort=("-" if args.desc else "") + (args.sort or ""),
        root_only=args.root,
        limit=args.limit,
        cursor=args.cursor or "",
        fetch_everything=args.all,
    )
    if ctx.json_mode:
        ctx.print_json(
            {
                "space": result.space.key if result.space else None,
                "count": len(result.pages),
                "nextCursor": result.next_cursor or None,
                "truncated": result.truncated,
                "pages": [page_row_json(page) for page in result.pages],
            }
        )
        return 0
    if not result.pages:
        ctx.print("No pages.")
        return 0
    ctx.print(table(["ID", "TITLE", "STATUS", "VERSION", "UPDATED"], [(p.id, p.title, p.status, p.version_number or "", p.updated) for p in result.pages]))
    if result.next_cursor:
        ctx.diagnostics.info(f"More pages follow. Continue with --cursor {result.next_cursor}, or use --all.")
    if result.truncated:
        ctx.diagnostics.warn("The list was cut short at its limit; narrow it with --title or --root.")
    return 0


# -- tree ----------------------------------------------------------------------------------------


def run_tree(ctx: Context, args: argparse.Namespace) -> int:
    result = ctx.app.tree_pages.execute(args.ref, depth=args.depth, space=args.space or "")
    if ctx.json_mode:
        ctx.print_json(
            {
                "root": {"id": result.root.id, "title": result.root.title, "spaceKey": result.space_key},
                "depth": result.depth,
                "count": len(result.nodes),
                "truncated": result.truncated,
                "nodes": [
                    {"id": n.id, "title": n.title, "type": n.type, "parentId": n.parent_id or None, "depth": n.depth, "status": n.status}
                    for n in result.nodes
                ],
            }
        )
        return 0
    lines = [f"{one_line(result.root.title)}  [{result.root.id}]"]
    for node in result.nodes:
        kind = "" if node.type == "page" else f" ({node.type})"
        lines.append(f"{'  ' * max(node.depth, 1)}{one_line(node.title)}  [{node.id}]{kind}")
    if not result.nodes:
        lines.append("  (no pages below this one)")
    ctx.print("\n".join(lines))
    if result.truncated:
        ctx.diagnostics.warn("The tree was cut short at its limit; start from a page further down.")
    return 0


# -- versions ------------------------------------------------------------------------------------


def run_versions(ctx: Context, args: argparse.Namespace) -> int:
    check_limit(args.limit)
    result = ctx.app.list_versions.execute(
        args.ref, limit=args.limit, cursor=args.cursor or "", fetch_everything=args.all, with_users=args.with_users
    )
    if ctx.json_mode:
        ctx.print_json(
            {
                "pageId": result.page_id,
                "title": result.title,
                "count": len(result.versions),
                "nextCursor": result.next_cursor or None,
                "versions": [_version_json(version) for version in result.versions],
            }
        )
        return 0
    headers = ["NUMBER", "SAVED", "MESSAGE"] + (["AUTHOR"] if result.users_shown else [])
    rows = [[v.number, v.created, v.message] + ([user_name(v.author)] if result.users_shown else []) for v in result.versions]
    ctx.print(table(headers, rows))
    if result.next_cursor:
        ctx.diagnostics.info(f"Older versions follow. Continue with --cursor {result.next_cursor}, or use --all.")
    return 0


# -- search --------------------------------------------------------------------------------------


def run_search(ctx: Context, args: argparse.Namespace) -> int:
    check_limit(args.limit)
    if args.start < 0:
        raise UsageError("--start must not be negative.")
    result: SearchResult = ctx.app.search_content.execute(
        text=args.text or "",
        space=args.space or "",
        content_type=args.type,
        label=args.label or "",
        title=args.title or "",
        under=args.under or "",
        since=args.since or "",
        cql=args.cql or "",
        limit=args.limit,
        start=args.start,
        fetch_everything=args.all,
        with_users=args.with_users,
        match=args.match,
        snippets=args.snippets,
    )
    if args.raw:
        ctx.print(pretty({"total": result.total, "cql": result.cql, "results": result.raw_results}))
        return 0
    for note in result.notes:
        ctx.diagnostics.info(note)
    if ctx.json_mode:
        ctx.print_json(
            {
                "total": result.total,
                "count": len(result.hits),
                "start": result.start,
                "cql": result.cql,
                "match": result.match,
                "relaxed": result.relaxed,
                "terms": list(result.terms),
                "ignored": list(result.ignored),
                "notes": list(result.notes),
                "truncated": result.truncated,
                "hits": [
                    {
                        "id": hit.id,
                        "type": hit.type,
                        "title": hit.title,
                        "spaceKey": hit.space_key,
                        "path": hit.path or None,
                        "labels": list(hit.labels),
                        "version": hit.version,
                        "url": hit.url,
                        "excerpt": hit.excerpt if result.excerpts_shown else None,
                        "snippet": hit.snippet or None,
                        "matched": list(hit.matched),
                        "lastModified": hit.last_modified,
                    }
                    for hit in result.hits
                ],
            }
        )
        return 0
    if not result.hits:
        ctx.print("Nothing found.")
        return 0
    if args.excerpts and not result.excerpts_shown:
        ctx.diagnostics.info("Excerpts can name people (a mention is plain text in the search index), so they are left out. Add --with-users to see them.")
    if args.excerpts and result.excerpts_shown:
        lines = []
        for hit in result.hits:
            lines.append(f"{hit.id}  {hit.type}  {hit.space_key}  {one_line(hit.title)}")
            if hit.excerpt:
                lines.append(f"    {hit.excerpt}")
        ctx.print("\n".join(lines))
    elif args.snippets:
        lines = []
        for hit in result.hits:
            lines.append(f"{hit.id}  {hit.type}  {hit.space_key}  {one_line(hit.title)}")
            if hit.path:
                lines.append(f"    in: {one_line(hit.path)}")
            if hit.labels:
                lines.append(f"    labels: {', '.join(hit.labels)}")
            if hit.snippet:
                lines.append(f"    {hit.snippet}")
        ctx.print("\n".join(lines))
    else:
        with_paths = any(hit.path for hit in result.hits)
        headers = ["ID", "TYPE", "SPACE", "TITLE", "MODIFIED"] + (["PATH"] if with_paths else [])
        rows = [[h.id, h.type, h.space_key, h.title, h.last_modified] + ([h.path] if with_paths else []) for h in result.hits]
        ctx.print(table(headers, rows))
    if len(result.hits) < result.total and not args.all:
        ctx.diagnostics.info(f"Showing {len(result.hits)} of {result.total}. Use --all, or --start to page.")
    if result.truncated:
        ctx.diagnostics.warn("The list was cut short at its limit; narrow the search.")
    return 0


# -- export --------------------------------------------------------------------------------------


def run_export(ctx: Context, args: argparse.Namespace) -> int:
    result = ctx.app.export_pages.execute(
        out_dir=args.out,
        space=args.space or "",
        root=args.page or "",
        body_format=args.format,
        dry_run=args.dry_run,
        force=args.force,
    )
    lossy = sum(1 for item in result.pages if item.lossy)
    if ctx.json_mode:
        ctx.print_json(
            {
                "directory": result.directory,
                "space": result.space or None,
                "root": result.root or None,
                "format": result.format,
                "dryRun": result.dry_run,
                "count": len(result.pages),
                "indexFile": result.index_file,
                "truncated": result.truncated,
                "notes": result.notes,
                "pages": [
                    {"id": i.id, "title": i.title, "parentId": i.parent_id or None, "path": i.path or None, "file": i.file, "version": i.version, "updated": i.updated, "lossy": list(i.lossy)}
                    for i in result.pages
                ],
            }
        )
        return 0
    verb = "Would write" if result.dry_run else "Wrote"
    ctx.print(f"{verb} {len(result.pages)} pages to {result.directory}" + ("" if result.dry_run else f" (index: {result.index_file})"))
    if lossy and result.format == "markdown":
        ctx.diagnostics.info(f"{lossy} pages hold constructs that Markdown cannot show (macros, mentions, layouts ...); `lossy` in the files and in the index lists them.")
    for note in result.notes:
        ctx.diagnostics.warn(note)
    if result.truncated:
        ctx.diagnostics.warn("The export was cut short at its limit; export a smaller part with --page.")
    return 0


COMMANDS = (
    Command(
        name="page",
        group=GROUP,
        summary="Show one page",
        when="Use to read one page whose id, address or title you know. Start with --outline and read only the --section you need: pages can be long. To find the page first use `search`; to follow a link that is shown as page:KEY/Title, pass it as the page.",
        description="Shows the title, space, version, labels and the body. The body is converted from Confluence's storage format "
        "to Markdown (or plain text; with --format storage it is shown as Confluence keeps it). People and mentions are hidden "
        "unless you add --with-users. The page can be given by its id or by the address as copied from the browser.",
        args=(
            Arg(
                ("ref",),
                "Page id, the address of the page as copied from the browser, or a `page:KEY/Title` reference, which is how `conflu page` shows a link to another page.",
                required=True,
                metavar="PAGE",
            ),
            Arg(("--format",), "Format of the body.", kind="choice", choices=BODY_FORMATS, default="markdown"),
            Arg(("--outline",), "Show the headings with the size of each section, and not the body. Then read one part with --section.", kind="flag"),
            Arg(("--section",), "Show only this section: the text of its heading (a part of it is enough when it is unique) or its number from --outline.", metavar="TITLE|N"),
            Arg(("--max-chars",), "Cut the body to about N characters, at the end of a paragraph; the answer says that it was cut.", kind="int", metavar="N"),
            Arg(("--space",), "The space of a `page:Title` reference. Default: the current space, else the whole site.", metavar="KEY"),
            Arg(("--no-body",), "Leave the body out and show only the properties of the page.", kind="flag"),
            Arg(("--body-only",), "Print the body and nothing else, for a file or a pipe. Wins over --json.", kind="flag"),
            Arg(("--comments",), "Also show the comments.", kind="flag"),
            Arg(("--ancestors",), "Also show the path of parent pages.", kind="flag"),
            Arg(("--with-users",), "Show people (author, owner, who saved the version, comment authors) and the account ids of mentions. Refused when CONFLUENCE_HIDE_USERS=true.", kind="flag"),
            Arg(("--raw",), "Print Confluence's own JSON for the page (people removed unless --with-users).", kind="flag"),
        ),
        examples=(
            Example("conflu page 123456", "the page as Markdown"),
            Example("conflu page 123456 --comments --ancestors --json", "everything as JSON, for a script or an agent"),
            Example("conflu page 123456 --outline", "the headings and the size of each section: find the part worth reading"),
            Example("conflu page 123456 --section Steps --max-chars 3000", "only that section, cut if it is longer"),
            Example("conflu page 'page:ENG/Our Products' --outline", "follow a link: a page by its title"),
            Example("conflu page 123456 --format storage", "the source, as Confluence keeps it"),
            Example("conflu page 123456 --format storage --with-users --body-only > page.xml", "only the source, into a file"),
            Example("conflu page https://example.atlassian.net/wiki/spaces/ENG/pages/123456/Title --no-body"),
        ),
        notes=(
            "The Markdown is a reading copy: macros, layouts, mentions, links between pages and the like cannot be shown in it. "
            "Both the text and the JSON name what is missing (`dropped`).",
            "Storage format read without --with-users has the account ids of mentions blanked. `update` and `create` refuse such a body.",
            "A long page costs a lot to read whole. `--outline` first, then `--section`, spends only what the question needs; `dropped` always names the whole page, "
            "not only the section.",
        ),
        json_output=True,
        output="id, title, status, spaceId, spaceKey, parentId, url, version{number,created,message,minorEdit,author}, created, updated, labels[], "
        "author and owner (null unless --with-users), ancestors[{id,title}] (with --ancestors), "
        "body{format,value,dropped[],section,truncated,totalChars} (null with --no-body or --outline; section names the part shown, truncated says that "
        "--max-chars cut the text, totalChars is the size of the whole text then), outline[{index,level,title,chars}] (with --outline), comments[] (with --comments).",
        handler=run_page,
    ),
    Command(
        name="pages",
        group=GROUP,
        summary="List the pages of a space",
        when="Use to list the pages of a space with their ids, versions and dates, or to look a page up by its exact title (--title). To look for words inside pages use `search`.",
        description="Lists the pages of the current space (`conflu use`) or of the space given with --space; without either, the pages of the whole site. "
        "Page ids are what the other commands take.",
        args=(
            Arg(("--space",), "Space key. Default: the current space.", metavar="KEY"),
            Arg(("--title",), "Only the pages with exactly this title.", metavar="TEXT"),
            Arg(("--status",), "Status of the pages.", kind="choice", choices=("current", "archived", "trashed"), default="current"),
            Arg(("--sort",), "Order of the list.", kind="choice", choices=SORTS),
            Arg(("--desc",), "Sort downwards (needs --sort).", kind="flag"),
            Arg(("--root",), "Only the pages at the root level of the space (needs a space).", kind="flag"),
            Arg(("--limit",), LIMIT_HELP, kind="int", default=25, metavar="N"),
            CURSOR,
            Arg(("--all",), ALL, kind="flag"),
        ),
        examples=(
            Example("conflu pages --space ENG --limit 50"),
            Example("conflu pages --space ENG --title 'Release notes' --json"),
            Example("conflu pages --space ENG --all --sort modified-date --desc --json"),
        ),
        json_output=True,
        output="space (key or null), count, nextCursor (null on the last page), truncated and pages[]: id, title, status, spaceId, parentId, version, updated, url.",
        handler=run_pages,
    ),
    Command(
        name="tree",
        group=GROUP,
        summary="Show the pages below a page",
        when="Use to see how a topic is organised: the pages below a page. Also a way to find related pages after `search` has found one.",
        description="Shows the descendants of a page as a tree, down to --depth levels (1 to 10). Folders and other content below the page "
        "are listed with their type.",
        args=(
            Arg(("ref",), "Page id, the address of the page, or a `page:KEY/Title` reference.", required=True, metavar="PAGE"),
            Arg(("--depth",), "Levels to show (1 to 10).", kind="int", default=3, metavar="N"),
            Arg(("--space",), "The space of a `page:Title` reference. Default: the current space, else the whole site.", metavar="KEY"),
        ),
        examples=(Example("conflu tree 123456"), Example("conflu tree 123456 --depth 10 --json"), Example("conflu tree 'page:ENG/Our Products' --depth 2")),
        json_output=True,
        output="root{id,title,spaceKey}, depth, count, truncated and nodes[] in reading order: id, title, type, parentId, depth, status.",
        handler=run_tree,
    ),
    Command(
        name="versions",
        group=GROUP,
        summary="List the saved versions of a page",
        when="Use to see when and why a page changed, or to learn the version number that `update --if-version` needs.",
        description="Newest first, with the date and the message of each version.",
        args=(
            Arg(("ref",), "Page id, or the address of the page.", required=True, metavar="PAGE"),
            Arg(("--limit",), LIMIT_HELP, kind="int", default=25, metavar="N"),
            CURSOR,
            Arg(("--all",), ALL, kind="flag"),
            Arg(("--with-users",), "Show who saved each version. Refused when CONFLUENCE_HIDE_USERS=true.", kind="flag"),
        ),
        examples=(Example("conflu versions 123456"), Example("conflu versions 123456 --all --json")),
        json_output=True,
        output="pageId, title, count, nextCursor and versions[]: number, created, message, minorEdit, author (null unless --with-users).",
        handler=run_versions,
    ),
    Command(
        name="search",
        group=GROUP,
        summary="Search pages with text or CQL",
        when="Use first when you do not know where information is. It finds pages by words, label, place or date and returns for each hit its path, labels and version, and with --snippets the passage around your words, so that you need not read a page to judge it. Read a hit with `page`.",
        description="Searches the whole site, or one space with --space, in titles and bodies; the other options narrow the result. The text "
        "becomes words and \"quoted phrases\": punctuation and filler words in English and German (how, do, the, wie, ich ...) are left out, "
        "and the answer says which. Case does not matter, stems match (groups finds group) and * is a wildcard. By default every word must "
        "occur; when no page holds all of them the search is repeated for the pages that hold some, and the answer says so (--match any asks "
        "for that directly, --match all never relaxes). Each hit has its path, labels and version. --snippets N reads the first N pages with "
        "one request and shows the passage around your words, so that you need not open a page to judge it. --cql takes a query written in "
        "Confluence's query language and replaces the other options.",
        args=(
            Arg(("text",), "Words to search for, or a question; \"quote a phrase\" to keep its words together.", metavar="TEXT"),
            Arg(("--space",), "Only this space.", metavar="KEY"),
            Arg(("--type",), "Kind of content.", kind="choice", choices=CONTENT_TYPES, default="page"),
            Arg(("--label",), "Only content with this label.", metavar="LABEL"),
            Arg(("--title",), "Only content whose title contains this text.", metavar="TEXT"),
            Arg(("--under",), "Only the descendants of this page (id or address).", metavar="PAGE"),
            Arg(("--since",), "Only content changed on or after this date (YYYY-MM-DD).", metavar="DATE"),
            Arg(("--cql",), "A CQL query. Replaces TEXT and the options above.", metavar="CQL"),
            Arg(("--limit",), "Results per request (1 to 250; Confluence may allow fewer).", kind="int", default=25, metavar="N"),
            Arg(("--start",), "Index of the first result.", kind="int", default=0, metavar="N"),
            Arg(("--all",), "Fetch every result instead of one request (ignores --limit and --start).", kind="flag"),
            Arg(("--match",), "all: every word must occur. any: one is enough. auto: all, and any when no page holds all of them.", kind="choice", choices=MATCH_MODES, default="auto"),
            Arg(("--snippets",), "Read the first N hits (up to 25) and show the passage around the searched words, with people hidden. One extra request.", kind="int", default=0, metavar="N"),
            Arg(("--excerpts",), "Show the excerpt of the search index for each result. Needs --with-users: it can name people.", kind="flag"),
            Arg(("--with-users",), "Show the excerpts, which can name people. Refused when CONFLUENCE_HIDE_USERS=true.", kind="flag"),
            Arg(("--raw",), "Print Confluence's own JSON (people and excerpts removed unless --with-users).", kind="flag"),
        ),
        examples=(
            Example("conflu search 'retention policy'"),
            Example("conflu search 'how do I request an SSO group for QA?' --space ENG --snippets 5 --json", "a question works: filler words are dropped"),
            Example("conflu search '\"SSO group\" roles' --space ENG --match any", "an exact phrase, plus a word"),
            Example("conflu search 'data quality' --space ENG --label adr --json"),
            Example("conflu search --cql 'type = page AND space = \"ENG\" AND lastmodified >= \"2026-10-01\"' --all --json"),
        ),
        json_output=True,
        output="total, count, start, cql, match (all, any or cql), relaxed (true when no page held all words), terms[] and ignored[] (what was searched for and what was left out), "
        "notes[] (what the person at the terminal is told: filler left out, the search relaxed, nothing found and what to try), truncated and hits[]: id, type, title, spaceKey, path (the parent pages, or null), labels[], version, url, excerpt (null unless --with-users: it can name people), "
        "snippet and matched[] (with --snippets: the passage around the words, from the page itself, and which words the page holds), lastModified.",
        handler=run_search,
    ),
    Command(
        name="export",
        group=GROUP,
        summary="Export a space or a page tree to Markdown files",
        when="Use to keep a Markdown copy of a space or a page tree in a folder next to the code, so that grep and file search cover Confluence as well. It is a copy to read, not a sync.",
        description="Writes every page of a space (--space), or a page with everything below it (--page), as one file per page in a folder, "
        "with an index.json. A Markdown file starts with a front matter (title, page_id, space, parent, version, updated, url, path), which "
        "`import-md` understands. What Markdown cannot show is listed under `lossy`. No personal data is written. "
        "Existing files are overwritten only with --force. It is a copy to read and to edit with care, not a sync: "
        "`import-md-dir` is the way back, and it is one-way as well.",
        args=(
            Arg(("--out",), "Folder to write into; it is created when it is missing.", required=True, metavar="DIR"),
            Arg(("--space",), "Export the pages of this space. Default: the current space, unless --page is given.", metavar="KEY"),
            Arg(("--page",), "Export this page and its descendants (up to 10 levels).", metavar="PAGE"),
            Arg(("--format",), "markdown, or storage for the pages as Confluence keeps them (.xml).", kind="choice", choices=INPUT_FORMATS, default="markdown"),
            Arg(("--force",), "Overwrite files that exist.", kind="flag"),
            Arg(("--dry-run",), "Read the pages and say what would be written. Writes nothing.", kind="flag"),
        ),
        examples=(
            Example("conflu export --space ENG --out tmp/eng"),
            Example("conflu export --page 123456 --out tmp/guide --dry-run"),
        ),
        notes=(
            "A title is written exactly as the page has it. An e-mail address or a personal link in it becomes `[email]` or `[personal link]`, as in the text.",
            "`import-md-dir` does not check whether a page changed in Confluence after this export: export again (into a folder under Git, with --force) and read the diff first. "
            "`conflu how-to export-and-sync` says what the pair does and does not do.",
        ),
        json_output=True,
        output="directory, space, root, format, dryRun, count, indexFile, truncated, notes[] and pages[]: id, title, parentId, path (the parent pages within the export, or null), file, version, updated, lossy[].",
        handler=run_export,
    ),
)
