"""How a command is described. One description feeds the parser, `conflu help`, `conflu commands --json`
and the generated reference, so they cannot drift apart."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .runtime import Context


@dataclass(frozen=True)
class Arg:
    names: tuple[str, ...]
    help: str
    kind: str = "str"  # str | int | float | flag | choice | list (an option given more than once, or several values)
    metavar: str = ""
    default: Any = None
    choices: tuple[str, ...] = ()
    required: bool = False

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

    def usage(self) -> str:
        parts = [f"conflu {self.name}"]
        for arg in self.args:
            if arg.positional:
                label = arg.label + ("..." if arg.kind == "list" else "")
                parts.append(label if arg.required else f"[{label}]")
            else:
                text = arg.names[0] if arg.kind == "flag" else f"{arg.names[0]} {arg.label}"
                parts.append(text if arg.required else f"[{text}]")
        if self.json_output:
            parts.append("[--json]")
        return " ".join(parts)


GROUP_ORDER = ("Read", "Work on a page", "Create and import", "Spaces", "Setup and information", "Tools")
