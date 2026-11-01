"""From the tool call of an MCP client to a command line, and from what the command printed to a tool result.

A tool is one entry of `help.mcp_tools(...)`: its `inputSchema` says what a call may hold and `_meta.conflu` how the properties become a
command line. A call is untrusted: a model wrote it, perhaps after reading text that a stranger put into a page. So it is checked before
it runs and written so that a value stays a value. It cannot turn into an option of the command, cannot read a file of this computer
through `@FILE`, and cannot ask for people unless the server was started to allow that. Which properties name a path, accept `@FILE` or
override something is declared on the arguments of the commands (`spec.Arg`: `path`, `at_file`, `overwrites`), and a test over the real
commands fails for an argument that looks like a path and declares none of it: nothing is guessed from the English of a help text.

A path property that a call leaves out can still decide where a command works: `download` without `out` writes into the working folder
itself. Those places are written down here (`DEFAULT_PLACES`), so that they are judged like a path that the call gave, and the command is
given the place that was judged.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from ....domain.content import parse_content_id
from ....domain.errors import ConfluCliError
from ....domain.model import is_attachment_id
from .help import mcp_property_names
from .spec import Command

MAX_RESULT_CHARS = 100_000
WITH_USERS = "--with-users"
_TYPE_NAMES = {"string": "a string", "integer": "an integer", "number": "a number", "boolean": "true or false", "array": "an array of strings"}


@dataclass(frozen=True)
class DefaultPlace:
    """Where a command works when a call leaves a path property out, and how that place is worked out. A place that the policy did not judge
    would be an open door: a link at `tmp`, or a stray file under the name of a folder, takes the command anywhere (a download without `out`
    would write the files of a stranger into the working folder itself, among the files of the project). So the place is worked out here,
    judged as a path that the call gave is, and handed to the command as the value of the property."""

    made_of: tuple[str, ...]  # the arguments (first names) that the place is made of: one that the call lacks leaves nothing to work out
    build: Callable[[Mapping[str, Any]], str]  # from the values of those arguments, as the command works it out
    explain: str  # for the description of the tool: where the command then works, and that it differs from what a shell does
    short: str  # for the description of the property
    unused_with: str = ""  # a flag with which the command works at no such place and takes no value for it (`download --text` writes no file)
    below: tuple[str, ...] = ()  # a folder below the working folder that a value that the call gives must lie below too, not only this place


DOWNLOAD_FOLDER = ("tmp", "conflu-attachments")  # below the working folder; the command itself would use the working folder
DOWNLOAD_HERE = "/".join(DOWNLOAD_FOLDER)


def _download_folder(values: Mapping[str, Any]) -> str:
    target = str(values["target"]).strip()
    return os.path.join(*DOWNLOAD_FOLDER, target if is_attachment_id(target) else parse_content_id(target))


# The path properties that have a default place. A test over the real commands holds this table, `NO_DEFAULT_PLACE` and the declarations
# together: an optional property that names a path is in one of them, and the place is the one that the command uses.
DEFAULT_PLACES: dict[tuple[str, str], DefaultPlace] = {
    ("download", "--out"): DefaultPlace(
        ("target",),
        _download_folder,
        f"Over MCP `out` must lie below {DOWNLOAD_HERE}, a folder for what strangers wrote: the names and the bytes of the files come from the "
        f"authors of the attachments. Left out it is {DOWNLOAD_HERE}/ID, with ID the id of the attachment or of the page. In a shell the command "
        "takes any folder, and the current one when `out` is left out.",
        f"Over MCP: below {DOWNLOAD_HERE}; left out: {DOWNLOAD_HERE}/ID.",
        unused_with="--text",
        below=DOWNLOAD_FOLDER,
    ),
}
# The optional path properties that have none: what the command does without them, so that it touches no file of its own choosing.
NO_DEFAULT_PLACE: dict[tuple[str, str], str] = {
    ("update", "--file"): "the body is left as it is, or comes from `body`",
    ("create", "--file"): "the body comes from `body`, or the page has none",
    ("convert", "file"): "no file is read: the command converts standard input, which is empty over MCP",
    ("comment", "--file"): "the text comes from `text`",
    ("blogpost-create", "--file"): "the body comes from `body`, or the post has none",
    ("blogpost-update", "--file"): "the body is left as it is, or comes from `body`",
    ("property-set", "--file"): "the value comes from `value`",
    ("page", "--out"): "the body is printed, and no file is written",
    ("blogpost", "--out"): "the body is printed, and no file is written",
    ("template", "--out"): "the body is printed, and no file is written",
    ("convert", "--out"): "the result is printed, and no file is written",
}


@dataclass(frozen=True)
class Default:
    """A default place as the policy of the paths gets it: the place, and the property of the tool that holds each argument that it needs."""

    place: DefaultPlace
    properties: tuple[tuple[str, str], ...]  # (argument, property) for what the place is made of and for the flag that makes it unused


@dataclass(frozen=True)
class Access:
    """What a property does with its value."""

    path: str = ""  # one of spec.PATH_KINDS, or nothing
    at_file: bool = False
    overwrites: bool = False
    default: Default | None = None  # a path property: where the command works when the call leaves it out

    @property
    def below(self) -> tuple[str, ...]:
        """The folder below the working folder that a value of this property must lie below (where the files of strangers go), or nothing."""
        return () if self.default is None else self.default.place.below


def access_of(command: Command) -> dict[str, Access]:
    """The properties of the tool of `command` that name a path, accept `@FILE` or override, by property name: what the arguments declare."""
    names = mcp_property_names(command)
    found: dict[str, Access] = {}
    for arg in command.args:
        if arg.names[0] not in names:  # shapes text for a person: no property
            continue
        place = DEFAULT_PLACES.get((command.name, arg.names[0]))
        wanted = () if place is None else (*place.made_of, *((place.unused_with,) if place.unused_with else ()))
        default = None if place is None else Default(place, tuple((first, names[first]) for first in wanted))
        access = Access(arg.path, arg.at_file, arg.overwrites, default)
        if access != Access():
            found[names[arg.names[0]]] = access
    return found


@dataclass(frozen=True)
class CommandResult:
    """What a command did: its exit code and everything it printed."""

    code: int
    out: str
    err: str


def _describe(value: Any) -> str:
    """What a JSON value is, for a message."""
    if value is None:
        return "null"
    if isinstance(value, bool):  # a bool is an int in Python, and not a number in JSON
        return "a boolean"
    if isinstance(value, int):
        return "an integer"
    if isinstance(value, float):
        return "a number"
    if isinstance(value, str):
        return "a string"
    return "an array" if isinstance(value, list) else "an object"


def _fits(value: Any, kind: str) -> bool:
    if kind == "string":
        return isinstance(value, str)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "array":
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return kind == "number" or isinstance(value, int) or value.is_integer()  # JSON Schema counts 5.0 as an integer


def _text_problem(text: str) -> str:
    if "\x00" in text:
        return "must not contain a NUL character"
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return "must be valid text (it holds a lone surrogate)"
    return ""


def _value_problems(name: str, value: Any, spec: Mapping[str, Any]) -> list[str]:
    kind = spec["type"]
    if not _fits(value, kind):
        return [f"'{name}' must be {_TYPE_NAMES[kind]}, not {_describe(value)}"]
    found: list[str] = []
    for text in value if kind == "array" else [value] if kind == "string" else []:
        problem = _text_problem(text)
        if problem:
            found.append(f"'{name}' {problem}")
            break
    if kind == "string" and "enum" in spec and value not in spec["enum"]:
        found.append(f"'{name}' must be one of {', '.join(spec['enum'])}")
    return found


def _items(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _meaning_problems(tool: Mapping[str, Any], arguments: Mapping[str, Any], show_users: bool, access: Mapping[str, Access]) -> list[str]:
    """What a value would mean to the command, apart from its type: an option, a file, people, a positional argument out of order."""
    found: list[str] = []
    skipped = ""
    for item in tool["_meta"]["conflu"]["arguments"]:
        name, value = item["property"], arguments.get(item["property"])
        if value is None:
            skipped = skipped or (name if item["positional"] else "")
            continue
        if item["positional"]:
            if any(isinstance(text, str) and text.startswith("-") for text in _items(value)):
                found.append(f"'{name}' is a positional argument and must not start with '-' (the command would read it as an option)")
            if skipped:
                found.append(f"'{name}' cannot be given without '{skipped}': positional arguments come in order")
        if item["flag"] == WITH_USERS and value is True and not show_users:
            found.append(f"'{name}' is refused: people stay out unless the server is started with --show-users")
        if access.get(name, Access()).at_file:
            texts = [text for text in _items(value) if isinstance(text, str)]
            if any(text.startswith("@") for text in texts):
                found.append(f"'{name}' must not start with '@': the command would read a file of this computer. Give the text itself")
            elif "-" in texts:
                found.append(f"'{name}' must not be '-': the command would read standard input, which is empty here. Give the text itself")
    return found


def _quoted(names: Sequence[str], limit: int = 10) -> str:
    shown = ", ".join(f"'{name}'" for name in names[:limit])
    return shown + (f" and {len(names) - limit} more" if len(names) > limit else "")


def problems(tool: Mapping[str, Any], arguments: Mapping[str, Any], *, show_users: bool, access: Mapping[str, Access]) -> list[str]:
    """What is wrong with a call, a sentence each; nothing when it may run. `access` is what the properties of the tool do with a
    value (`access_of`), with no default so that a caller cannot forget it: a value that starts with `@` is refused where it would read
    a file."""
    schema = tool["inputSchema"]
    properties = schema["properties"]
    unknown = [name for name in arguments if name not in properties]
    found = []
    if unknown:
        noun = "property" if len(unknown) == 1 else "properties"
        found.append(f"unknown {noun} {_quoted(unknown)} (the properties are {', '.join(properties) or 'none'})")
    found += [f"'{name}' is required" for name in schema["required"] if name not in arguments]
    for name, value in arguments.items():
        if name in properties:
            found += _value_problems(name, value, properties[name])
    return found + _meaning_problems(tool, arguments, show_users, access)


def problem_summary(found: Sequence[str], limit: int = 8) -> str:
    """The problems as one message: a model that sent many wrong properties needs the first ones, not a page."""
    shown = "; ".join(found[:limit])
    return shown + (f"; and {len(found) - limit} more" if len(found) > limit else "")


def _text(value: Any, kind: str) -> str:
    return str(int(value)) if kind == "integer" else str(value)


def _texts(value: Any, kind: str) -> list[str]:
    """The arguments that a value becomes: one, or one for each item of an array (the files that the policy of the paths approved)."""
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [_text(value, kind)]


def command_line(tool: Mapping[str, Any], arguments: Mapping[str, Any], approved: Mapping[str, Any] | None = None) -> list[str]:
    """What `tests/cli/test_agent_tools.py::argv_from` builds, for a call that `problems` accepted: the positional arguments in order, then
    the flags (a boolean only when true), then what is always appended. Every option is written `--flag=value`, so that a value that
    starts with `-` stays the value of its option.

    `approved` holds, for each property that names a path, the value that the policy of the paths approved (`mcp_paths.PathPolicy.check`):
    the path in full, links followed. The command is given that value and never the text that the model wrote, because a command may take a
    text apart in its own way (take the blanks off its ends) and then use another path than the one that was checked. The files of `attach`
    are approved as an array and become one argument each, so that no command can split one at a blank."""
    meta = tool["_meta"]["conflu"]
    items = meta["arguments"]
    argv = list(meta["command"][1:])
    given = {**arguments, **(approved or {})}
    for item in items:
        value = given.get(item["property"])
        if item["positional"] and value is not None:
            argv.extend(_texts(value, item["type"]))
    for item in items:
        value = given.get(item["property"])
        if item["positional"] or value is None or value is False:
            continue
        if item["type"] == "boolean":
            argv.append(item["flag"])
        else:
            argv.extend(f"{item['flag']}={text}" for text in _texts(value, item["type"]))
    return argv + list(meta["alwaysAppend"])


def split_error(err: str) -> tuple[str, str]:
    """The error object that the command printed as the last line of standard error (JSON, compact), and the lines before it. Lines end
    at `\\n` only: `str.splitlines` would also cut a message at a character such as U+2028 that Confluence may have put into it."""
    lines = err.rstrip("\n").split("\n")
    try:
        printed = json.loads(lines[-1])
    except ValueError:
        printed = None
    if isinstance(printed, dict) and isinstance(printed.get("error"), dict):
        return lines[-1], "\n".join(lines[:-1])
    return "", err.rstrip("\n")


def _error_object(result: CommandResult) -> str:
    line, rest = split_error(result.err)
    if line:
        return line
    # a bug in a command: the CLI prints it as text, not as the error object
    message = next((text[len("ERROR: ") :] for text in rest.split("\n") if text.startswith("ERROR: ")), "")
    error = {
        "code": "ERROR" if message else "EXIT",
        "message": message or f"The command finished with exit code {result.code}.",
        "hint": "",
        "exitCode": result.code,
        "details": {},
    }
    return json.dumps({"error": error}, ensure_ascii=False, separators=(",", ":"))


def _cut(text: str) -> str:
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return (
        text[:MAX_RESULT_CHARS]
        + f"\n[Cut: the result has {len(text):,} characters and only the first {MAX_RESULT_CHARS:,} are shown. "
        "Ask for less: fewer keys (select), a smaller limit, a part of a page (outline, section, maxChars).]"
    )


def _block(text: str) -> dict[str, str]:
    return {"type": "text", "text": text}


def tool_result(result: CommandResult) -> dict[str, Any]:
    """The answer to `tools/call`: what the command printed or, when it failed, the error object that it printed on standard error, so that
    the caller sees the hint. A command that answered and still failed (`doctor`) adds what it printed. The rest of standard error is
    not part of the result."""
    if result.code == 0:
        return {"content": [_block(_cut(result.out))], "isError": False}
    content = [_block(_error_object(result))]
    if result.out.strip():
        content.append(_block(_cut(result.out)))
    return {"content": content, "isError": True}


def error_result(error: ConfluCliError) -> CommandResult:
    """What a command that failed with `error` leaves: the error object on standard error, as `main.run` prints it for `--json`. A call
    that the server refuses by its own policy (a path outside the working folder) is answered like a command that failed."""
    body = {"code": error.code, "message": error.message, "hint": error.hint, "exitCode": error.exit_code, "details": error.details}
    return CommandResult(error.exit_code, "", json.dumps({"error": body}, ensure_ascii=False, default=str, separators=(",", ":")) + "\n")


MIN_HOME = 4  # a home folder shorter than this is not looked for: it would be found in everything (`C:`, `/`)
MIN_NAME = 3  # nor a user name shorter than this; the name is only looked for as the folder of a user (`C:\Users\NAME`), not on its own
_NAME_CHARS = r"[\w$~-]|\.\w"  # what continues a name: a folder `alex.corp` is not the folder `alex`


def private_text_filter(homes: Sequence[str], names: Sequence[str] = ()) -> Callable[[str], str]:
    """A function that puts `~` in place of what a result would tell the model about the person at this computer: the home folder, in every
    spelling that a result can have (as it is, with `/` or `\\`, and as JSON writes a backslash, `\\\\`; capitals do not matter), and the folder
    of a user, `C:\\Users\\NAME` or `/home/NAME`, for each of `names` (the account name, which a path of another spelling can hold: the folder
    of the temporary files, the place of a launcher). A name or a folder that goes on (`alex.corp`, `alexander`) is another one and stays.

    It is the last filter over the text of a result, for every tool: `conflu_doctor` prints where the settings file is, an error shows the
    path of a file. It is no security boundary but a courtesy to the person: the path stays understandable (`~/.config/...`), the account
    name does not leave the computer in the context of a model. What a page or a comment says is changed only where it holds that exact
    folder. The returned function is the identity when there is nothing to look for."""
    spellings: set[str] = set()
    for home in homes:
        text = home.strip().rstrip("\\/")
        if len(text) < MIN_HOME:
            continue
        for form in (text, text.replace("\\", "/"), text.replace("/", "\\")):
            spellings.add(form)
            spellings.add(form.replace("\\", "\\\\"))
    parts = [re.escape(text) for text in sorted(spellings, key=lambda text: (-len(text), text))]
    named = sorted({name.strip() for name in names if len(name.strip()) >= MIN_NAME}, key=lambda name: (-len(name), name))
    if named:
        # the look-behind lets the folder of a user start only where a run of separators starts: from each separator of a run it was read to the end of the run,
        # which is the square of the length of a text of slashes
        parts.append(r"(?:[A-Za-z]:|(?<![\\/]))[\\/]+(?:users|home)[\\/]+(?:" + "|".join(re.escape(name) for name in named) + ")")
    if not parts:
        return lambda text: text
    pattern = re.compile("(?:" + "|".join(parts) + f")(?!{_NAME_CHARS})", re.IGNORECASE)
    return lambda text: pattern.sub("~", text)


def hidden(result: Mapping[str, Any], hide: Callable[[str], str]) -> dict[str, Any]:
    """The result of a tool with `hide` applied to the text of every block of it (what `tool_result` made)."""
    return {**result, "content": [{**block, "text": hide(block["text"])} for block in result["content"]]}
