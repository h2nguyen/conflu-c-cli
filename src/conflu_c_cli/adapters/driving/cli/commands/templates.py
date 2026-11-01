"""Commands about the templates of a space: templates, template."""
from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from .....application.formats import BODY_FORMATS
from ..listing import FORMAT, SELECT, print_list
from ..render import key_values, one_line, table
from ..runtime import Context
from ..spec import Arg, Command, Example
from ._common import LIMIT_HELP, body_json, check_limit
from ._outfile import FORCE, deliver, out_option, prepare_out

if TYPE_CHECKING:
    from .....application.templates import TemplateList, TemplateView
    from .....domain.templates import TemplateInfo

GROUP = "Spaces"
TEMPLATE_COLUMNS = [("ID", "id"), ("NAME", "name"), ("TYPE", "type"), ("SPACE", "spaceKey"), ("DESCRIPTION", "description")]


def template_json(info: TemplateInfo) -> dict[str, Any]:
    return {
        "id": info.id,
        "name": info.name,
        "type": info.type,
        "description": info.description,
        "spaceKey": info.space_key or None,
        "labels": list(info.labels),
        "blueprint": info.blueprint or None,
    }


def templates_text(result: TemplateList) -> str:
    if not result.templates:
        return "No templates."
    rows = [[item.id, item.name, item.type, item.space_key, item.description] for item in result.templates]
    return table([header for header, _ in TEMPLATE_COLUMNS], rows)


def run_templates(ctx: Context, args: argparse.Namespace) -> int:
    check_limit(args.limit)
    result = ctx.app.templates.list_templates.execute(
        space=args.space or "", blueprints=args.blueprints, limit=args.limit, start=args.start, fetch_everything=args.all
    )
    rows = [template_json(item) for item in result.templates]
    document = {
        "space": result.space or None,
        "blueprints": result.blueprints,
        "count": len(rows),
        "start": result.start,
        "nextStart": result.next_start,
        "truncated": result.truncated,
        "templates": rows,
    }
    if print_list(ctx, args, payload=document, rows=rows, list_key="templates", columns=TEMPLATE_COLUMNS, plain=lambda: templates_text(result)) or not result.templates:
        return 0
    if result.next_start is not None:
        ctx.diagnostics.info(f"More templates follow. Continue with --start {result.next_start}, or use --all.")
    if result.truncated:
        ctx.diagnostics.warn("The list was cut short at its limit; narrow it with --space.")
    return 0


def template_document(view: TemplateView) -> dict[str, Any]:
    return {**template_json(view.template), "variables": list(view.variables), "variablesComplete": view.variables_complete, "body": body_json(view.body)}


def template_text(view: TemplateView) -> str:
    info = view.template
    pairs = [
        ("Type", one_line(info.type)),
        ("Space", one_line(info.space_key) or "(global)"),
        ("Description", one_line(info.description)),
        ("Labels", one_line(", ".join(info.labels))),
        ("Blueprint", one_line(info.blueprint)),
        ("Variables", one_line(", ".join(view.variables)) + ("" if view.variables_complete or not view.variables else ", ...")),
    ]
    nothing = "(the template is empty)" if view.empty else "(nothing that this format can show: `--format storage` shows the body)"
    return f"{one_line(info.name)}  [{one_line(info.id)}]\n{key_values(pairs)}\n\n{view.body.text.rstrip() or nothing}"


def replaced_note(count: int) -> str:
    """One sentence for somebody who is about to make a page from the body: what stands in it where the template holds addresses and links."""
    what = "1 e-mail address or personal link was" if count == 1 else f"{count} e-mail addresses and personal links were"
    return (
        f"{what} replaced by [email] and [personal link] in this body: a page created from it would carry those words, not the addresses and links. "
        "`template` has no --with-users, so put the real ones into the file before you create the page, or take them out."
    )


def run_template(ctx: Context, args: argparse.Namespace) -> int:
    prepare_out(ctx, args, body_only=args.body_only, example="conflu template 7402 --format storage --body-only --out body.xml")
    view = ctx.app.templates.show_template.execute(args.id, body_format=args.format)
    if args.body_only:
        deliver(ctx, args, view.body.text)
        if view.body.dropped:
            ctx.diagnostics.info(f"The Markdown cannot show: {', '.join(view.body.dropped)}. `--format storage` shows the template as Confluence keeps it.")
        if view.replaced:
            ctx.diagnostics.warn(replaced_note(view.replaced))
        return 0
    if ctx.json_mode:
        ctx.print_json(template_document(view))
        if view.replaced:
            ctx.diagnostics.warn(replaced_note(view.replaced))
        return 0
    ctx.print(template_text(view))
    if view.body.dropped:
        ctx.diagnostics.info(f"The Markdown cannot show: {', '.join(view.body.dropped)}. `--format storage` shows the template as Confluence keeps it.")
    if view.replaced:
        ctx.diagnostics.warn(replaced_note(view.replaced))
    if not view.variables_complete:
        ctx.diagnostics.warn("The list of variables may be incomplete: the body holds more tags, or longer ones, than are read. `--format storage` shows the whole body.")
    return 0


COMMANDS = (
    Command(
        name="templates",
        group=GROUP,
        summary="List the page templates of a space",
        when="Use to see which templates a space offers, or the global ones, with their ids: read one with `template`. --blueprints lists the templates "
        "that blueprints provide instead.",
        description="Lists the page templates of one space (--space), or the global templates without it: the current space is not used. With --blueprints "
        "it lists the templates that blueprints provide instead. Templates are known to the older REST API only, which pages with --start and --limit. "
        "The API cannot make a page from a template: nothing in this CLI does.",
        args=(
            Arg(("--space",), "The key of the space. Without it the global templates.", metavar="KEY"),
            Arg(("--blueprints",), "List the templates that blueprints provide instead of the page templates.", kind="flag"),
            Arg(("--limit",), LIMIT_HELP, kind="int", default=25, metavar="N"),
            Arg(("--start",), "Where to start in the list: 0 is the first template. Continue with the nextStart of the last answer.", kind="int", default=0, metavar="N"),
            Arg(("--all",), "Fetch every template instead of one piece. --limit and --start are not used then, but a --limit out of range and a negative --start are still refused.", kind="flag"),
            SELECT,
            FORMAT,
        ),
        examples=(
            Example("conflu templates"),
            Example("conflu templates --space ENG --json"),
            Example("conflu templates --blueprints --space ENG --all"),
            Example("conflu templates --space ENG --all --select id,name,description --format tsv"),
        ),
        json_output=True,
        output="space (key, [hidden] for a personal space, or null: the global templates), blueprints (true for the templates of blueprints), count, start, nextStart (null on the last piece), "
        "truncated and templates[]: id, name, type (page or blueprint), description, spaceKey ([hidden] in a personal space, null for a global template), labels[], blueprint (what the "
        "template references, as Confluence says it, or null); with --select only those (dotted) keys of every template.",
        handler=run_templates,
    ),
    Command(
        name="template",
        group=GROUP,
        summary="Show a template with its body and its variables",
        when="Use to read a template: what it is, the variables it declares and its body. To start a page from it, save the body (with --format storage "
        "--body-only) and create the page from that file: the API cannot make a page from a template.",
        description="Shows the template's name, type, space, description and labels, the variables it declares (`<at:var>` elements, which the Markdown "
        "copy cannot show, so they are listed from the storage format) and its body, converted like the body of a page: people are hidden, and `dropped` "
        "names what the Markdown cannot say. Nothing in this CLI makes a page from a template.",
        args=(
            Arg(("id",), "The id of the template: `conflu templates` lists them, and `conflu templates --blueprints` those of the blueprints.", required=True, metavar="ID"),
            Arg(("--format",), "Format of the body.", kind="choice", choices=BODY_FORMATS, default="markdown"),
            Arg(("--body-only",), "Print the body and nothing else, for a file or a pipe. Wins over --json.", kind="flag"),
            out_option(),
            FORCE,
        ),
        examples=(
            Example("conflu template 7402"),
            Example("conflu template 7402 --format storage", "the source, as Confluence keeps it"),
            Example("conflu template 7402 --format storage --body-only --out body.xml", "only the source, into a file that the program writes as UTF-8, to start a page from it"),
            Example("conflu template 7402 --json"),
        ),
        notes=(
            "Mentions of people in the body come out blanked, so a template with a mention cannot be copied as it is: copy it in the browser.",
            "E-mail addresses and personal links come out as [email] and [personal link]; with --format storage a warning on standard error says how many, because a page "
            "created from that body would carry those words. `template` has no --with-users.",
            "Confluence answers HTTP 403 for a template that does not exist as well as for one that this account may not see.",
            "To save the body, use --body-only --out FILE and not `>`: the program then writes the file itself, as UTF-8 without a byte-order mark and with plain line ends, and says so "
            "in one line (`Wrote N bytes to FILE`; `file` and `bytes` with --json). Windows PowerShell 5.1 re-encodes what `>` saves and damages every character that is not ASCII. "
            "A file that exists is not replaced without --force, and never the settings file of the CLI. It writes a file on this computer and changes nothing in Confluence.",
        ),
        json_output=True,
        output="id, name, type, description, spaceKey ([hidden] in a personal space, null for a global template), labels[], blueprint, variables[] (the names that the template declares, in order, each once), "
        "variablesComplete (false when the body holds more tags than are read, or longer ones) and body{format,value,dropped[]}; with --body-only --out: file, bytes.",
        handler=run_template,
    ),
)
