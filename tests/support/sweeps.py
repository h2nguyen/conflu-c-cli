"""The command lines that the conformance sweep runs (tests/integration/test_conformance.py), one module per feature area.

A line is run in the order it stands, against one mock Confluence that the area has to itself, through the real adapters. The sweep
asserts that no line made a call that the matching OpenAPI document does not list, or lists as deprecated, that every call to the v1
API is one that `V1_CALLS` explains, and that `docs/reference/compatibility.md` names the calls of every command. An area adds its own
lines to its own module; a command that is in no module and not in `LOCAL` fails the sweep.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Line:
    """One run of the command line. `{work}` in the arguments, and in the names of `files`, stands for a folder of its own."""

    argv: tuple[str, ...]
    stdin: str = ""
    files: tuple[tuple[str, str | bytes], ...] = ()  # (path, content) written below `{work}` before the run
    code: int = 0  # the exit code that the run must end with
    env: tuple[tuple[str, str], ...] = ()  # extra environment variables

    @property
    def command(self) -> str:
        return self.argv[0]


def line(*argv: str, stdin: str = "", files: tuple[tuple[str, str | bytes], ...] = (), code: int = 0, env: tuple[tuple[str, str], ...] = ()) -> Line:
    return Line(tuple(argv), stdin, files, code, env)


# Commands that never ask Confluence for anything (they read the documents that ship with the CLI, the settings, or convert text).
# `setup` is swept in sweep_core (it makes the one call that is in neither document), and `mcp` runs the other commands.
LOCAL = frozenset(
    {
        "help", "commands", "version", "changelog", "how-to", "skill", "convert", "config", "current", "clear-space",
        "remove-token", "setup-token", "mcp",
    }
)
