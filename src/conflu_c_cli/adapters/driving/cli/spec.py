"""How a command is described. One description feeds the parser, `conflu help`, `conflu commands --json`
and the generated reference, so they cannot drift apart."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .runtime import Context

# What an argument does with its value, for `conflu mcp`, which lets a model call a command: a value that names a path of this computer, a
# value that `@FILE` turns into the contents of a file, a flag that replaces what exists. A test over every command fails for an argument
# that looks like a path and says none of this (tests/cli/test_mcp_server.py).
READS_FILE = "reads a file"
READS_FILES = "reads files"  # several, as one argument each
READS_FOLDER = "reads a folder"
READS_FILE_OR_FOLDER = "reads a file or a folder"
WRITES_FILE = "writes a file"  # a new one
WRITES_FOLDER = "writes into a folder"
WRITES_BELOW_FOLDER = "writes into a folder below the working folder"  # files whose names a stranger chose: not into the folder itself
PATH_KINDS = (READS_FILE, READS_FILES, READS_FOLDER, READS_FILE_OR_FOLDER, WRITES_FILE, WRITES_FOLDER, WRITES_BELOW_FOLDER)


@dataclass(frozen=True)
class Arg:
    names: tuple[str, ...]
    help: str
    # str | int | float | flag | choice
    # list: an option given more than once, or a positional with several values (one argument each)
    # repeat: an option that may be given more than once; its value is a list (`--phrase 'a b' --phrase c`)
    # words: a positional that takes every word that stands there, joined by one blank, so that a text needs no quotes (the words as they came
    #        stay in `<dest>_words`, for a command that must tell `"a b"` from `a b`)
    kind: str = "str"
    metavar: str = ""
    default: Any = None
    choices: tuple[str, ...] = ()
    required: bool = False
    path: str = ""  # one of PATH_KINDS: the value names a file or a folder of this computer
    at_file: bool = False  # `@FILE` as the value reads a file of this computer (`-` reads standard input)
    overwrites: bool = False  # the flag replaces a file, or a change that somebody else made: the person decides that, not a model
    not_a_path: str = ""  # why an argument that looks like a path is none ("a file name to look for among the attachments of the page")
    text_only: bool = False  # it shapes the text for a person (`--format tsv`) and conflicts with `--json`: not offered to a model, whose call asks for JSON

    @property
    def positional(self) -> bool:
        return not self.names[0].startswith("-")

    @property
    def dest(self) -> str:
        long_names = [name for name in self.names if name.startswith("--")]
        return (long_names or self.names)[0].lstrip("-").replace("-", "_")

    @property
    def label(self) -> str:
        if self.metavar:
            return self.metavar
        if self.choices:
            return "|".join(self.choices)
        return "VALUE" if not self.positional else self.dest.upper()


@dataclass(frozen=True)
class Example:
    command: str
    note: str = ""


Handler = Callable[["Context", argparse.Namespace], "int | None"]


@dataclass(frozen=True)
class Command:
    name: str
    group: str
    summary: str
    handler: Handler
    description: str = ""
    when: str = ""  # when to use it, and when another command is the better one: the first thing a reader needs to choose
    args: tuple[Arg, ...] = ()
    examples: tuple[Example, ...] = ()
    notes: tuple[str, ...] = ()
    writes: bool = False
    json_output: bool = False
    output: str = ""
    aliases: tuple[str, ...] = ()
    needs_app: bool = True
    # What `conflu mcp` and `conflu commands --format mcp` need to know about the command (the person's commands are not offered to a model):
    streams: bool = False  # the command talks on standard input and output itself (a server): its output cannot be wrapped in an envelope
    for_person: bool = False  # not for an agent: it holds or changes credentials and settings, describes the CLI itself, or is the raw `api`
    local: bool = False  # it never asks Confluence (`openWorldHint: false`)
    destructive: bool = False  # it changes Confluence in a way that is not only additive: it replaces, moves or removes
    idempotent: bool = False  # the same call again changes nothing more
    writes_files: bool = False  # it writes files on this computer and changes nothing in Confluence (export, download)

    def usage(self) -> str:
        parts = [f"conflu {self.name}"]
        for arg in self.args:
            if arg.positional:
                label = arg.label + ("..." if arg.kind in ("list", "words") else "")
                parts.append(label if arg.required else f"[{label}]")
            else:
                text = arg.names[0] if arg.kind == "flag" else f"{arg.names[0]} {arg.label}"
                parts.append(text if arg.required else f"[{text}]")
        if self.json_output:
            parts.append("[--json]")
        return " ".join(parts)


GROUP_ORDER = (
    "Read",
    "Work on a page",
    "Create and import",
    "Structure",
    "Blog posts",
    "Access and people",
    "Tasks and properties",
    "Spaces",
    "Setup and information",
    "Tools",
)
