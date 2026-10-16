"""Commands about the tool itself and a few helpers: help, commands, version, changelog, how-to, skill, convert, api."""
from __future__ import annotations

import argparse
import re
import sys
from typing import Mapping

from .....domain.errors import UsageError
from .....version import __version__
from ..help import catalog, mcp_tools, render_command_help, render_overview
from ..render import table
from ..runtime import Context
from ..spec import Arg, Command, Example
from ._common import POWERSHELL_JSON_NOTE, pretty

GROUP = "Setup and information"
TOOLS = "Tools"

# The registry imports this package, so it is imported only when a handler runs.


def _registry():
    from .. import registry

    return registry


def run_help(ctx: Context, args: argparse.Namespace) -> int:
    registry = _registry()
    if not args.command:
        ctx.print(render_overview(registry.all_commands(), __version__))
        return 0
    command = registry.find_command(args.command)
    if command is None:
        close = registry.suggestions(args.command)
        raise UsageError(
            f"Unknown command: {args.command}" + (f". Did you mean: {', '.join(close)}?" if close else "."),
            hint="Run `conflu help` for the list of commands.",
        )
    ctx.print(render_command_help(command))
    return 0


def run_commands(ctx: Context, args: argparse.Namespace) -> int:
    commands = _registry().all_commands()
    if args.format == "mcp":
        ctx.print_json(mcp_tools(commands, __version__, only=args.only))
    elif ctx.json_mode or args.format == "json":
        ctx.print_json(catalog(commands, __version__))
    else:
        ctx.print(table(["COMMAND", "GROUP", "SUMMARY"], [(command.name, command.group, command.summary) for command in commands]))
    return 0


def run_version(ctx: Context, args: argparse.Namespace) -> int:
    if ctx.json_mode:
        ctx.print_json({"name": "conflu-c-cli", "version": __version__, "python": sys.version.split()[0], "platform": sys.platform})
    else:
        ctx.print(f"conflu-c-cli {__version__}")
    return 0


def run_changelog(ctx: Context, args: argparse.Namespace) -> int:
    ctx.print(ctx.app.read_docs.changelog().rstrip())
    return 0


def run_how_to(ctx: Context, args: argparse.Namespace) -> int:
    docs = ctx.app.read_docs
    if args.topic:
        wanted = args.topic.strip().lower()
        text = (docs.readme() if wanted in ("readme", "overview") else docs.topic(wanted)).rstrip()
        ctx.print_json({"topic": wanted, "text": text}) if ctx.json_mode else ctx.print(text)
        return 0
    rows = [("readme", "Overview, install and the first commands")] + [(topic.name, topic.title) for topic in docs.topics()]
    if ctx.json_mode:
        ctx.print_json([{"topic": name, "title": title} for name, title in rows])
        return 0
    ctx.print(table(["TOPIC", "TITLE"], rows))
    ctx.print("\nShow one with `conflu how-to TOPIC`, for example `conflu how-to use-with-ai-agents`.")
    return 0


def run_skill(ctx: Context, args: argparse.Namespace) -> int:
    action = args.action or "show"
    if action == "show":
        text = ctx.app.read_docs.skill().rstrip()
        ctx.print_json({"name": "conflu-c-cli", "text": text}) if ctx.json_mode else ctx.print(text)
        return 0
    result = ctx.app.install_skill.execute(args.dir, dry_run=args.dry_run, force=args.force)
    if ctx.json_mode:
        ctx.print_json({"path": result.path, "action": result.action, "dryRun": result.dry_run})
    elif result.action == "unchanged":
        ctx.print(f"Skill already up to date: {result.path}")
    elif result.dry_run:
        ctx.print(f"Would write the skill to {result.path}")
    else:
        ctx.print(f"Skill {result.action}: {result.path}")
    return 0


def run_convert(ctx: Context, args: argparse.Namespace) -> int:
    if not args.file and ctx.stdin.isatty():
        raise UsageError("Pass a file, or pipe the text in.", hint="Example: conflu convert notes.md  or  cat notes.md | conflu convert -")
    result = ctx.app.convert_text.execute(ctx.read_input(args.file or "-"), args.source)
    ctx.print(result.text.rstrip("\n"))
    if result.dropped:
        ctx.diagnostics.info(f"The Markdown cannot show: {', '.join(result.dropped)}.")
    return 0


def _api_path(path: str, environ: Mapping[str, str]) -> str:
    """Git Bash rewrites an argument that starts with `/` into a Windows path (`/api/v2/pages` becomes
    `C:/Program Files/Git/api/v2/pages`) before Python sees it. Undo that, so both spellings work."""
    text = path.replace("\\", "/")
    root = (environ.get("EXEPATH") or "").replace("\\", "/").rstrip("/")
    if root and text.lower().startswith(root.lower() + "/"):
        return text[len(root) :]
    if re.match(r"^[A-Za-z]:/", text):
        raise UsageError(
            f"The path looks like a Windows path: {path}",
            hint="Git Bash rewrites a leading `/`. Write the path without it (api/v2/pages/123) or run with MSYS_NO_PATHCONV=1.",
        )
    return path


def run_api(ctx: Context, args: argparse.Namespace) -> int:
    body = ctx.read_input(args.data_file) if args.data_file else (args.data or "")
    result = ctx.app.raw_api.execute(args.method, _api_path(args.path, ctx.environ), body, write=args.write, dry_run=args.dry_run)
    if result.dry_run:
        ctx.print(f"Dry run: {result.method} {result.path}; nothing was sent")
        if result.body is not None:
            ctx.print(pretty(result.body))
    elif result.response is not None:
        ctx.print(pretty(result.response))
    return 0


COMMANDS = (
    Command(
        name="help",
        group=GROUP,
        summary="Show the commands, or the help of one command",
        when="Use to read the help of one command.",
        args=(Arg(("command",), "Command name.", metavar="COMMAND"),),
        examples=(Example("conflu help"), Example("conflu help update")),
        needs_app=False,
        handler=run_help,
    ),
    Command(
        name="commands",
        group=GROUP,
        summary="List every command, for programs",
        when="Use to learn the whole CLI in one call. `--format mcp` gives the commands as tool descriptions for an agent.",
        description="With --json it prints the complete description of the CLI: every command with its arguments, examples, JSON output, "
        "whether it changes data, when to use it, plus the exit codes and the settings. An AI agent can read it once instead of parsing help text. "
        "With --format mcp it prints the commands an agent may use as tool descriptions in the shape of an MCP `tools/list` answer: a name, a "
        "description, a JSON Schema for the input, annotations (read-only, destructive, idempotent) and, under `_meta.conflu`, how the "
        "properties become a command line. Commands for the person (the token, the settings, the default space) and the raw `api` are not in it.",
        args=(
            Arg(("--format",), "table (the default), json (the catalog, as with --json) or mcp (tool descriptions for an agent).", kind="choice", choices=("table", "json", "mcp"), default="table"),
            Arg(("--only",), "With --format mcp: read (the default: nothing that changes Confluence), write or all.", kind="choice", choices=("read", "write", "all"), default="read"),
        ),
        examples=(
            Example("conflu commands --json"),
            Example("conflu commands --format mcp", "the read-only tools, as tool descriptions"),
            Example("conflu commands --format mcp --only all", "with the tools that change Confluence"),
        ),
        json_output=True,
        output="version, commands[], exitCodes[], settings[]; with --format mcp: tools[] (name, title, description, inputSchema, annotations, _meta) and _meta.",
        needs_app=False,
        handler=run_commands,
    ),
    Command(
        name="version",
        group=GROUP,
        summary="Show the version",
        when="Use to see which version of the tool runs.",
        description="Aliases: -V and --version.",
        examples=(Example("conflu version"), Example("conflu version --json")),
        json_output=True,
        output="name, version, python, platform.",
        needs_app=False,
        handler=run_version,
    ),
    Command(
        name="changelog",
        group=GROUP,
        summary="Show the release history",
        when="Use to see what changed between versions.",
        description="Aliases: changes, history.",
        examples=(Example("conflu changelog"),),
        aliases=("changes", "history"),
        handler=run_changelog,
    ),
    Command(
        name="how-to",
        group=GROUP,
        summary="Read the guides that ship with the CLI",
        when="Use to read the guides that ship with the tool, offline: for example `find-information`, which says how to search well.",
        description="Without a topic it lists the guides; with one it prints the guide (with --json: topic and text). Everything works offline. Aliases: howto, readme, docs.",
        args=(Arg(("topic",), "Guide name; `readme` is the overview.", metavar="TOPIC"),),
        examples=(Example("conflu how-to"), Example("conflu how-to daily-workflow"), Example("conflu how-to use-with-ai-agents")),
        aliases=("howto", "readme", "docs"),
        json_output=True,
        output="without a topic: a list of {topic, title}; with a topic: {topic, text}.",
        handler=run_how_to,
    ),
    Command(
        name="skill",
        group=GROUP,
        summary="Show or install the AI agent skill",
        when="Use to read or install the skill that teaches an AI agent to use this tool.",
        description="The skill tells an AI agent (GitHub Copilot, for example) how to use this CLI. `show` prints it; `install` copies "
        "it to DIR/conflu-c-cli/SKILL.md, by default into .github/skills of the current folder. A skill that is already there and "
        "differs from this version (an older one, or one you edited) is replaced only with --force.",
        args=(
            Arg(("action",), "show (default) or install.", kind="choice", choices=("show", "install")),
            Arg(("--dir",), "Folder that holds the skills.", default=".github/skills", metavar="DIR"),
            Arg(("--force",), "Replace a skill that differs from this version.", kind="flag"),
            Arg(("--dry-run",), "Only say where the skill would be written.", kind="flag"),
        ),
        examples=(Example("conflu skill"), Example("conflu skill install"), Example("conflu skill install --dir ~/.copilot/skills --force")),
        json_output=True,
        output="with show: name, text; with install: path, action (installed, replaced or unchanged), dryRun.",
        handler=run_skill,
    ),
    Command(
        name="convert",
        group=TOOLS,
        summary="Convert Markdown to storage format, or back",
        when="Use to see what the converter makes of a text before it is sent to Confluence, or to read storage format as Markdown.",
        description="Prints the storage format (Confluence's XHTML) that `create`, `update` and `comment` would send for a Markdown file or for "
        "standard input; front matter is dropped. With --source storage it goes the other way and prints the Markdown that `page` shows, "
        "naming on stderr what Markdown cannot say. The same converters run behind every command that takes Markdown.",
        args=(
            Arg(("file",), "The file; `-` or nothing reads standard input.", metavar="FILE"),
            Arg(("--source",), "What the input is: markdown (the default) or storage format.", kind="choice", choices=("markdown", "storage"), default="markdown"),
        ),
        examples=(Example("conflu convert notes.md"), Example("cat page.xml | conflu convert --source storage")),
        handler=run_convert,
    ),
    Command(
        name="api",
        group=TOOLS,
        summary="Call any Confluence REST endpoint",
        when="Use only when no named command covers a call. GET is free; POST and PUT change Confluence.",
        description="An escape hatch for what no command covers yet. PATH is below the wiki address and starts with api/ (API v2, "
        "for example api/v2/pages/123456) or rest/ (the older API, for example rest/api/search). GET is free. POST and PUT change "
        "Confluence and need --write; preview them with --dry-run. DELETE is deliberately not offered. The answer is Confluence's JSON.",
        args=(
            Arg(("method",), "GET, POST or PUT.", required=True, metavar="METHOD"),
            Arg(("path",), "Path such as api/v2/pages/123456. A leading / is accepted too.", required=True, metavar="PATH"),
            Arg(("--data",), "Request body as JSON.", metavar="JSON"),
            Arg(("--data-file",), "Request body from a file (`-` is standard input).", metavar="FILE"),
            Arg(("--write",), "Confirm that a POST or PUT may change Confluence.", kind="flag"),
            Arg(("--dry-run",), "Show the request and send nothing.", kind="flag"),
        ),
        examples=(
            Example("conflu api GET api/v2/pages/123456"),
            Example("conflu api GET 'rest/api/search?cql=type=page&limit=5'"),
            Example("conflu api PUT api/v2/pages/123456/title --data-file payload.json --write --dry-run"),
        ),
        notes=(
            "Git Bash turns an argument that starts with / into a Windows path. The CLI undoes that, but writing the path without the leading / avoids the problem.",
            POWERSHELL_JSON_NOTE,
        ),
        writes=True,
        json_output=True,
        output="Confluence's response, unchanged (people removed when CONFLUENCE_HIDE_USERS=true).",
        handler=run_api,
    ),
)
