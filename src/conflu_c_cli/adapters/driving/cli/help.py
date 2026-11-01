"""Help for people and for programs, and the generated reference. All from the command descriptions."""
from __future__ import annotations

import re
import textwrap
from typing import Any, Sequence

from ....domain.errors import EXIT_CODES, UsageError
from .apis import api_line, api_of
from .spec import GROUP_ORDER, Arg, Command

_COMMON_OPTIONS = (
    ("--json", "Print the result as JSON (stable keys for scripts and agents)."),
    ("-v, --verbose", "Log every request to stderr (never the credentials)."),
    (
        "--json-envelope",
        "Print exactly one JSON object on stdout, {\"ok\": true, \"data\": ...} or {\"ok\": false, \"error\": {...}}, whatever happens. "
        "The exit code and stderr stay as they are. Also CONFLUENCE_JSON_ENVELOPE=1.",
    ),
    ("-h, --help", "Show this help. Help never calls Confluence and never changes anything."),
)


def _wrap(text: str, indent: str = "") -> str:
    return "\n".join(
        textwrap.fill(paragraph, width=96, initial_indent=indent, subsequent_indent=indent)
        for paragraph in text.strip().split("\n\n")
    )


def _option_label(arg: Arg) -> str:
    if arg.positional:
        return arg.label
    names = ", ".join(arg.names)
    return names if arg.kind == "flag" else f"{names} {arg.label}"


def _arg_lines(command: Command) -> list[tuple[str, str]]:
    rows = [(_option_label(arg), arg.help + (f" Default: {arg.default}." if arg.default not in (None, "") else "")) for arg in command.args]
    if command.json_output:
        rows.append(_COMMON_OPTIONS[0])
    rows.extend(_COMMON_OPTIONS[1:])
    return rows


def render_overview(commands: Sequence[Command], version: str) -> str:
    lines = [
        f"Confluence Cloud command line helper (conflu-c-cli {version})",
        "",
        "Usage: conflu COMMAND [options]",
        "       conflu help COMMAND",
        "",
    ]
    width = max(len(command.name) for command in commands) + 2
    for group in GROUP_ORDER:
        members = [command for command in commands if command.group == group]
        if not members:
            continue
        lines.append(group)
        lines.extend(f"  {command.name.ljust(width)}{command.summary}" for command in members)
        lines.append("")
    lines += [
        "Every command answers `conflu COMMAND --help` (or `conflu help COMMAND`) with its options and examples.",
        "Help never calls Confluence and never changes anything.",
        "",
        "For scripts and AI agents: add --json (or set CONFLUENCE_OUTPUT=json). Errors then come as JSON on",
        "stderr. Exit codes and JSON shapes: `conflu how-to exit-codes`, `conflu how-to json-output`.",
        "Every command with its arguments in one short text: `conflu help --brief`.",
        "Settings: `conflu config show`. Guides: `conflu how-to`. Setup check: `conflu doctor`.",
    ]
    return "\n".join(lines)


BRIEF_BUDGET = 4096  # bytes: what an agent may spend to learn every command; the design below is for about 70 commands, at about 50 bytes each
BRIEF_OPTIONS = 4  # the options of a command that a line of the brief shows, besides those that must be given
_BRIEF_HEADER = (
    "conflu COMMAND ARGS [--options]  [x] optional, x... repeats, * changes data (use --dry-run first), ... more: conflu help COMMAND",
    "All commands take -v and --json-envelope; those that return data take --json.",
)
_BRIEF_LATE = ("--select", "--cursor", "--dry-run", "--json-envelope")  # plumbing that many commands share: it comes after what makes a command what it is


def _brief_line(command: Command, options: int | None) -> str:
    """`name[*] ARGS --required [--option --option ...]`; a star after the name says that the command changes data. An option that must
    be given stands outside the brackets and is never cut. The options come in the order of the description, except those that many
    commands share (`--select`, `--cursor`) and the ones that only shape the text for a person (`--format` of a list), which come last."""
    positionals = [
        (arg.label + ("..." if arg.kind in ("list", "words") else "")) if arg.required else f"[{arg.label}{'...' if arg.kind in ('list', 'words') else ''}]"
        for arg in command.args
        if arg.positional
    ]
    flags = [arg for arg in command.args if not arg.positional and not (command.writes and "--dry-run" in arg.names)]  # the star says it
    required = [arg.names[0] for arg in flags if arg.required]
    optional = sorted((arg for arg in flags if not arg.required), key=lambda arg: arg.text_only or arg.names[0] in _BRIEF_LATE)
    names = [arg.names[0] for arg in optional]
    shown = names if options is None else names[:options]
    text = " ".join([command.name + ("*" if command.writes else ""), *positionals, *required])
    if shown:
        text += " [" + " ".join(shown) + (" ..." if len(shown) < len(names) else "") + "]"
    elif names:
        text += " [...]"
    return text


def render_brief(commands: Sequence[Command], *, options: int | None = BRIEF_OPTIONS, budget: int | None = BRIEF_BUDGET, names: Sequence[str] | None = None) -> str:
    """One line per command with its arguments and its main options: the compact reference for an agent (`conflu help --brief`).

    `options` is how many optional options a line shows (None: all of them). When the text is longer than `budget` bytes (a CLI that has
    grown beyond the design) the options of every command are cut further, step by step, until it fits; `names` keeps only those commands."""
    chosen = [command for command in commands if names is None or command.name in names]

    def build(count: int | None) -> str:
        lines = list(_BRIEF_HEADER)
        for group in GROUP_ORDER:
            members = [command for command in chosen if command.group == group]
            if members:
                lines.append(f"{group}:")
                lines.extend("  " + _brief_line(command, count) for command in members)
        return "\n".join(lines)

    levels = [None, 8, 6, 5, 4, 3, 2, 1, 0] if options is None else list(range(options, -1, -1))
    text = ""
    for count in levels:
        text = build(count)
        if budget is None or len(text.encode("utf-8")) <= budget:
            break
    return text


def render_compact_reference(commands: Sequence[Command], names: Sequence[str]) -> str:
    """For the skill: the arguments and all options of some commands, each with its first example."""
    by_name = {command.name: command for command in commands}
    lines: list[str] = []
    for name in names:
        command = by_name[name]
        lines.append(_brief_line(command, None))
        if command.examples:
            example = command.examples[0]
            lines.append("    " + example.command + (f"    # {example.note}" if example.note else ""))
    return "\n".join(lines)


def _changes(command: Command) -> str:
    """What the help says about writing: yes or no, and whether a preview exists."""
    if not command.writes:
        return "no"
    return "yes, preview with --dry-run" if any("--dry-run" in arg.names for arg in command.args) else "yes"


def render_command_help(command: Command) -> str:
    lines = [f"conflu {command.name} - {command.summary}", "", f"Usage: {command.usage()}", ""]
    if command.description:
        lines += [_wrap(command.description), ""]
    if command.when:
        lines += [_wrap(f"When to use: {command.when}"), ""]
    rows = _arg_lines(command)
    width = min(max(len(label) for label, _ in rows), 34) + 2
    positional = [(l, h) for (l, h), a in zip(rows, command.args) if a.positional]
    options = [row for row in rows if row not in positional]
    for title, block in (("Arguments", positional), ("Options", options)):
        if not block:
            continue
        lines.append(f"{title}:")
        for label, text in block:
            lead = f"  {label.ljust(width)}"
            wrapped = textwrap.wrap(text, width=96 - len(lead)) or [""]
            lines.append(lead + wrapped[0])
            lines.extend(" " * len(lead) + extra for extra in wrapped[1:])
        lines.append("")
    if command.examples:
        lines.append("Examples:")
        for example in command.examples:
            lines.append(f"  {example.command}")
            if example.note:
                lines.append(f"      {example.note}")
        lines.append("")
    if command.notes:
        lines.append("Notes:")
        lines.extend(_wrap("- " + note, "  ").replace("\n  ", "\n    ") for note in command.notes)
        lines.append("")
    facts = [f"Changes data: {_changes(command)}"]
    if api_line(command.name):
        facts.append(f"REST API: {api_line(command.name)}")
    if command.output:
        facts.append(f"JSON output: {command.output}")
    lines.extend(textwrap.fill(fact, width=96, subsequent_indent="  ") for fact in facts)
    return "\n".join(lines).rstrip()


def _arg_catalog(arg: Arg) -> dict[str, Any]:
    return {
        "names": list(arg.names),
        "positional": arg.positional,
        "kind": arg.kind,
        "required": arg.required,
        "default": arg.default,
        "choices": list(arg.choices),
        "help": arg.help,
    }


def catalog(commands: Sequence[Command], version: str) -> dict[str, Any]:
    """Everything a program needs to know about the CLI: `conflu commands --json`."""
    from ....application.settings import SETTING_DEFS

    return {
        "version": version,
        "commands": [
            {
                "name": command.name,
                "group": command.group,
                "summary": command.summary,
                "description": command.description,
                "whenToUse": command.when,
                "usage": command.usage(),
                "arguments": [_arg_catalog(arg) for arg in command.args],
                "supportsJson": command.json_output,
                "changesData": command.writes,
                "api": api_of(command.name),
                "jsonOutput": command.output,
                "examples": [{"command": item.command, "note": item.note} for item in command.examples],
                "notes": list(command.notes),
                "aliases": list(command.aliases),
            }
            for command in commands
        ],
        "exitCodes": [{"code": code, "names": names, "meaning": meaning} for code, names, meaning in EXIT_CODES],
        "settings": [
            {
                "name": item.name,
                "kind": item.kind,
                "default": item.default,
                "secret": item.secret,
                "personal": item.personal,
                "description": item.description,
            }
            for item in SETTING_DEFS
        ],
    }


# -- tool descriptions for agents (the shape of an MCP `tools/list` answer) ------------------------------------------

# Which commands an agent may call, and how far a change goes, is said by the flags of each command (`for_person`, `local`, `destructive`,
# `idempotent`, `writes_files`: see spec.Command): a command that is not for an agent holds or changes credentials and settings, describes the
# CLI itself, or is the raw `api`, whose writes no description can bound.
MCP_ONLY = ("read", "write", "all")
MCP_ALWAYS = {"ping": ("--quiet",)}  # what keeps the person that the token belongs to out of an answer that would show them
# What a tool that writes files says about itself: in the catalogue (`conflu commands --format mcp`, for a program that runs `conflu NAME` in a shell,
# where `--force` works) and as `conflu mcp` offers it (which refuses `force`, never writes over a file and keeps to the working folder).
MCP_FILES_NOTE = "Does not change Confluence. Writes files in a folder and can overwrite them: ask before you use it on a folder that holds work."
MCP_FILES_NOTE_OVER_MCP = (
    "Does not change Confluence. Writes files below the working folder of the server and never replaces one: `force` is refused over MCP, "
    "and a file that exists stops the command."
)
MCP_REFUSED_NOTE = "Refused over MCP: what it would override (a file, or content that would be lost) is for the user to decide, not for a call."
_TYPES = {"flag": "boolean", "int": "integer", "float": "number", "list": "array", "repeat": "array"}


def mcp_tool_name(command: Command) -> str:
    """The name of the tool of a command: `import-md` is `conflu_import_md`."""
    return "conflu_" + command.name.replace("-", "_")


def is_tool(command: Command) -> bool:
    """Whether a command can be a tool at all: it is not for the person, and it is no server that talks on standard input and output itself."""
    return not command.for_person and not command.streams


def tool_groups(commands: Sequence[Command]) -> list[str]:
    """The groups that hold a tool, in the order of `conflu help`."""
    present = {command.group for command in commands if is_tool(command)}
    return [group for group in GROUP_ORDER if group in present] + sorted(present - set(GROUP_ORDER))


def wanted_groups(commands: Sequence[Command], groups: Sequence[str]) -> frozenset[str]:
    """The groups that were asked for, in lower case. A name that is no group of a tool is a usage error that lists the groups."""
    known = {group.lower(): group for group in tool_groups(commands)}
    unknown = [name for name in groups if name.strip().lower() not in known]
    if unknown:
        raise UsageError(
            f"Unknown group: {', '.join(repr(name) for name in unknown)}.",
            hint=f"The groups are: {', '.join(known.values())}. Case does not matter; repeat --group for several.",
        )
    return frozenset(name.strip().lower() for name in groups)


def _camel(text: str) -> str:
    head, *tail = [part for part in re.split(r"[^A-Za-z0-9]+", text) if part]
    return head.lower() + "".join(part[:1].upper() + part[1:].lower() for part in tail)


def _offered(command: Command) -> list[Arg]:
    """The arguments a model is told about: those that shape text for a person (`--format tsv`) cannot go with the JSON that its call asks for."""
    return [arg for arg in command.args if not arg.text_only]


def mcp_property_names(command: Command) -> dict[str, str]:
    """The property of the input schema for each argument (by its first name): `--if-version` is `ifVersion`, PAGE is `page`."""
    names: dict[str, str] = {}
    taken: set[str] = set()
    for arg in _offered(command):
        base = _camel(re.sub(r"\.\w+$", "", arg.metavar)) if arg.positional and arg.metavar else _camel(arg.dest)
        name = base if base not in taken else base + "Option"
        taken.add(name)
        names[arg.names[0]] = name
    return names


def _schema(arg: Arg) -> dict[str, Any]:
    kind = _TYPES.get(arg.kind, "string")
    several = kind == "array"
    schema: dict[str, Any] = {"type": kind}
    if several:
        schema["items"] = {"type": "string"}
    if arg.choices:
        schema["enum"] = list(arg.choices)
    text = arg.help.strip()
    if several:
        text += " Several values: one array item each."
    schema["description"] = text
    if arg.default not in (None, "", False):
        schema["default"] = arg.default
    return schema


def _in_tool_terms(text: str, command: Command, names: dict[str, str], tool_names: dict[str, str]) -> str:
    """The text as a reader of the tool description needs it: `--dry-run` is the property `dryRun`, `page` is the tool `conflu_page`."""
    for cli_name, tool_name in tool_names.items():  # first: afterwards `space` could be a property or a command
        text = text.replace(f"`{cli_name}`", f"`{tool_name}`")
    for arg in _offered(command):
        if arg.positional:
            continue
        name = names[arg.names[0]]
        for flag in sorted(arg.names, key=len, reverse=True):
            text = text.replace(f"`{flag}`", f"`{name}`")
            text = re.sub(r"(?<=`)" + re.escape(flag) + r"(?![\w-])", name, text)  # in a longer span: `--format storage`
            text = re.sub(r"(?<![\w`-])" + re.escape(flag) + r"(?![\w-])", f"`{name}`", text)
    return text


def _mentions_a_flag(text: str, flags: Sequence[str]) -> bool:
    return any(re.search(r"(?<![\w-])" + re.escape(flag) + r"(?![\w-])", text) for flag in flags)


def mcp_tool(command: Command, tool_names: dict[str, str] | None = None, *, over_mcp: bool = False) -> dict[str, Any]:
    """The description of one command as a tool. `over_mcp` describes it as `conflu mcp` offers it: the server refuses what overrides (`force`)
    and never writes over a file, which the catalogue (for a shell, where the flag works) does not say."""
    names = mcp_property_names(command)
    tool_names = tool_names or {}
    offered = _offered(command)
    text_flags = [flag for arg in command.args if arg.text_only for flag in arg.names]

    def say(text: str) -> str:
        return _in_tool_terms(text, command, names, tool_names)

    properties = {names[arg.names[0]]: {**_schema(arg), "description": say(_schema(arg)["description"])} for arg in offered}
    forcing = [names[arg.names[0]] for arg in offered if arg.overwrites]
    if over_mcp:
        for name in forcing:
            properties[name]["description"] = f"{MCP_REFUSED_NOTE} {properties[name]['description']}"
    required = [names[arg.names[0]] for arg in offered if arg.required]
    parts = [command.summary + "."]
    if command.when:
        parts.append(say(f"When to use: {command.when}"))
    if command.description:
        parts.append(say(" ".join(command.description.split())))
    if command.output:
        parts.append(say(f"Returns JSON: {command.output}"))
    if command.writes:
        parts.append("Changes Confluence." + (" Run it with dryRun first and show the result." if any("--dry-run" in a.names for a in command.args) else ""))
    elif command.writes_files:
        parts.append(MCP_FILES_NOTE_OVER_MCP if over_mcp else MCP_FILES_NOTE)
    if over_mcp and forcing:
        parts.append(f"Over MCP `{forcing[0]}` is refused: do not set it.")
    annotations: dict[str, Any] = {"title": command.summary, "readOnlyHint": not command.writes and not command.writes_files, "openWorldHint": not command.local}
    if command.writes:
        annotations["destructiveHint"] = command.destructive
        annotations["idempotentHint"] = command.idempotent
    elif command.writes_files:  # it changes no page, but it can replace a file: the same call again leaves what the first one wrote
        annotations["destructiveHint"] = True
        annotations["idempotentHint"] = True
    return {
        "name": mcp_tool_name(command),
        "title": command.summary,
        "description": "\n\n".join(parts),
        "inputSchema": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
        "annotations": annotations,
        "_meta": {
            "conflu": {
                "command": ["conflu", command.name],
                "arguments": [
                    {
                        "property": names[arg.names[0]],
                        "positional": arg.positional,
                        "flag": None if arg.positional else arg.names[0],
                        "type": _TYPES.get(arg.kind, "string"),
                    }
                    for arg in offered
                ],
                "alwaysAppend": (["--json"] if command.json_output else []) + list(MCP_ALWAYS.get(command.name, ())),
                "examples": [item.command for item in command.examples if not _mentions_a_flag(item.command, text_flags)],
            }
        },
    }


def mcp_tools(commands: Sequence[Command], version: str, *, only: str = "read", groups: Sequence[str] = (), over_mcp: bool = False) -> dict[str, Any]:
    """The commands an agent may use, as MCP tool descriptions: name, description, JSON Schema for the input, annotations
    (read-only, destructive, idempotent), and under `_meta.conflu` how the properties become a command line.

    `only` is `read` (the default: nothing that changes Confluence and nothing that writes files), `write` (the commands that change Confluence,
    and those that write files, which are not read-only) or `all`. `groups` keeps the tools of some groups of `conflu help` (a name that is none
    is a usage error); it changes no text of a tool. `over_mcp` is how `conflu mcp` offers them: the same tools, and the texts that differ say what
    the server does (it refuses `force`, and never writes over a file); the catalogue describes the commands as a shell runs them."""
    if only not in MCP_ONLY:
        raise ValueError(f"only must be one of {MCP_ONLY}")
    wanted = wanted_groups(commands, groups)
    in_set = [command for command in commands if is_tool(command) and (only == "all" or (command.writes or command.writes_files) == (only == "write"))]
    tool_names = {command.name: mcp_tool_name(command) for command in in_set}  # a tool names the other tools of its set, not those of a group that is left out
    chosen = [command for command in in_set if not wanted or command.group.lower() in wanted]
    meta: dict[str, Any] = {
        "version": version,
        "only": only,
        "invoke": (
            "Run the command: `conflu NAME`, then the positional arguments in the order of `arguments`, then each other property as its flag "
            "(a boolean only when true, an array as the flag repeated; the array of a positional argument is passed item by item, in order), "
            "then the always-appended flags. A result is JSON on standard output; "
            "a failure is a non-zero exit code and JSON on standard error: {\"error\": {\"code\", \"message\", \"hint\", \"exitCode\"}}."
        ),
        "exitCodes": [{"code": code, "names": names, "meaning": meaning} for code, names, meaning in EXIT_CODES],
    }
    if wanted:
        meta["groups"] = [group for group in tool_groups(commands) if group.lower() in wanted]
    return {"tools": [mcp_tool(command, tool_names, over_mcp=over_mcp) for command in chosen], "_meta": {"conflu": meta}}


# -- generated reference (docs/reference/*.md) ----------------------------------------------------

_GENERATED = "<!-- Generated by scripts/generate_docs.py from the command descriptions. Do not edit by hand. -->"


def commands_markdown(commands: Sequence[Command], version: str) -> str:
    out = [_GENERATED, "", "# Command reference", "", f"conflu-c-cli {version}. The same text is available offline with `conflu help COMMAND`.", ""]
    for group in GROUP_ORDER:
        members = [command for command in commands if command.group == group]
        if not members:
            continue
        out += [f"## {group}", ""]
        for command in members:
            out += [f"### `conflu {command.name}`", "", command.summary + ".", "", "```text", command.usage(), "```", ""]
            if command.description:
                out += [command.description.strip(), ""]
            if command.when:
                out += [f"**When to use:** {command.when}", ""]
            rows = _arg_lines(command)
            out += ["| Argument or option | Meaning |", "| --- | --- |"]
            out += [f"| `{label}` | {text.replace('|', chr(92) + '|')} |" for label, text in rows]
            out.append("")
            if command.examples:
                out += ["```bash"]
                for example in command.examples:
                    out.append(f"{example.command}" + (f"    # {example.note}" if example.note else ""))
                out += ["```", ""]
            for note in command.notes:
                out.append(f"- {note}")
            if command.notes:
                out.append("")
            out.append(f"Changes data: **{_changes(command)}**." if command.writes else "Changes data: no.")
            if api_line(command.name):
                out += ["", f"REST API: {api_line(command.name)}"]
            if command.output:
                out.append("")
                out.append(f"JSON output: {command.output}")
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def _default_text(item: Any) -> str:
    if item.secret:
        return "secret"
    if item.kind == "bool":
        return f"`{str(item.default).lower()}`"
    if item.kind == "float":
        return f"`{item.default:g}`"
    return f"`{item.default}`" if item.default not in ("", None) else "(empty)"


def settings_markdown() -> str:
    from ....application.settings import SETTING_DEFS

    out = [_GENERATED, "", "# Configuration reference", "",
           "Settings come from the environment, then from the config file (`conflu config path`), then from the defaults.", "",
           "| Setting | Default | Meaning |", "| --- | --- | --- |"]
    for item in SETTING_DEFS:
        example = f" Example: `{item.example}`." if item.example else ""
        out.append(f"| `{item.name}` | {_default_text(item)} | {item.description}{example} |")
    return "\n".join(out) + "\n"


def exit_codes_markdown() -> str:
    out = [_GENERATED, "", "# Exit codes", "",
           "A script or an agent can decide what to do from the exit code alone.", "",
           "| Code | Error codes | Meaning |", "| --- | --- | --- |"]
    out += [f"| {code} | {names} | {meaning} |" for code, names, meaning in EXIT_CODES]
    out += ["", "Two more codes come from the shell and not from Confluence: **130** when the command was interrupted (Ctrl+C) and **141** when the reader of its output "
            "went away (`conflu pages | head`); treat 141 as expected when you piped the output on purpose.",
            "", "With `--json` (or `CONFLUENCE_OUTPUT=json`) an error is printed to **stderr** as one JSON object:", "",
            "```json", '{"error": {"code": "NOT_FOUND", "message": "...", "hint": "...", "exitCode": 4, "details": {}}}', "```", ""]
    return "\n".join(out)
