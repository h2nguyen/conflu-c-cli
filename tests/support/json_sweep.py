"""The command lines of the sweep (tests/support/sweeps_all.py and sweep_local.py), run again with each way of asking for JSON.

tests/integration/test_json_sweep.py holds every command to its promise: a command that declares `json_output` prints one JSON value, and a failure is a JSON
error on standard error; with the envelope every command prints one JSON object on standard output. What each line printed is kept here, with the line as its
area wrote it, so that a violation can name the line.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from types import ModuleType

from conflu_c_cli.adapters.driving.cli.registry import find_command
from conflu_c_cli.adapters.driving.cli.spec import Command

from . import sweep_local, sweep_modes
from .sweep_runner import run_sweeps
from .sweeps import Line
from .sweeps_all import SWEEPS

MODULES = (*SWEEPS, sweep_local, sweep_modes)

ENVIRONMENT = "CONFLUENCE_OUTPUT=json"  # in the environment of the line
FLAG = "--json"  # appended to the arguments of a line whose command declares JSON
ENVELOPE = "CONFLUENCE_JSON_ENVELOPE=1"  # in the environment of the line
SWITCHES = (ENVIRONMENT, FLAG, ENVELOPE)

# Why a line prints text although JSON is on. Both are read from the specs of the commands, not from a list of names.
TEXT_ONLY = "the option shapes the text for a person (Arg.text_only): --json and --json-envelope refuse it, and CONFLUENCE_OUTPUT=json yields to it"
WINS_OVER_JSON = "the option says in its help that it wins over --json"


@dataclass(frozen=True)
class Run:
    """One line of the sweep, run with one switch."""

    area: str
    line: Line  # as its area wrote it
    command: Command
    switch: str
    applied: bool  # False: the line ran as it stands, because the switch does not fit it (a command without JSON for --json, a server, a text-only option)
    text_mode: str  # TEXT_ONLY, WINS_OVER_JSON, or "" when the line must print JSON
    code: int
    out: str
    err: str

    @property
    def label(self) -> str:
        return f"{self.area}: conflu {' '.join(self.line.argv)}"


def text_mode(command: Command, argv: tuple[str, ...]) -> str:
    """Why this line prints text although JSON is on, or "": it uses an option that is text on purpose, as its command's spec says."""
    for arg in command.args:
        if arg.positional:
            continue
        if any(token == name or token.startswith(f"{name}=") for token in argv[1:] for name in arg.names):
            if arg.text_only:
                return TEXT_ONLY
            if "wins over --json" in arg.help.lower():
                return WINS_OVER_JSON
    return ""


def _switched(line: Line, command: Command, switch: str, mode: str) -> tuple[Line, bool]:
    """The line as it runs with the switch, and whether the switch was added: not to a line that uses a text-only option (the usage error that follows
    is by design), and not `--json` to a command that declares no JSON (it takes none). A server gets the environment variables like every command."""
    if mode == TEXT_ONLY or (switch == FLAG and not command.json_output):
        return line, False
    if switch == FLAG:
        return replace(line, argv=(*line.argv, "--json")), True
    name, _, value = switch.partition("=")
    return replace(line, env=((name, value), *line.env)), True


def _variant(module: ModuleType, lines: tuple[Line, ...]) -> ModuleType:
    clone = ModuleType(module.__name__)
    clone.LINES = lines  # type: ignore[attr-defined]
    prepare = getattr(module, "PREPARE", None)
    if prepare is not None:
        clone.PREPARE = prepare  # type: ignore[attr-defined]
    return clone


@lru_cache(maxsize=None)
def runs(switch: str) -> tuple[Run, ...]:
    """Every line of every module, in the order of the sweep, run with the switch (each module against a mock of its own, as the other sweeps do)."""
    planned: list[tuple[str, Line, Command, bool, str]] = []
    modules = []
    for module in MODULES:
        lines = []
        for item in module.LINES:
            command = find_command(item.argv[0])
            assert command is not None, f"a sweep line names a command that does not exist: {item.argv[0]}"
            mode = text_mode(command, item.argv)
            ran, applied = _switched(item, command, switch, mode)
            planned.append((module.__name__.rpartition(".")[2], item, command, applied, mode))
            lines.append(ran)
        modules.append(_variant(module, tuple(lines)))
    result = run_sweeps(tuple(modules))
    assert len(result.outputs) == len(planned)
    return tuple(
        Run(area, item, command, switch, applied, mode, output.code, output.out, output.err)
        for (area, item, command, applied, mode), output in zip(planned, result.outputs)
    )
