"""The list of commands. To add a command, write a module in `commands/` and list it in
`commands/__init__.py`. The modules are imported when they are needed: `find_command` imports the one module of a command, `all_commands` all of them."""
from __future__ import annotations

from functools import lru_cache

from .commands import MODULE_NAMES, WHERE, load
from .spec import GROUP_ORDER, Command


@lru_cache(maxsize=1)
def all_commands() -> tuple[Command, ...]:
    found: list[Command] = []
    for name in MODULE_NAMES:
        found.extend(load(name).COMMANDS)
    order = {group: index for index, group in enumerate(GROUP_ORDER)}
    # The sort is stable: inside a group the commands stay in the order of their module.
    return tuple(sorted(found, key=lambda command: order.get(command.group, len(order))))


def find_command(name: str) -> Command | None:
    wanted = name.strip().lower()
    module = WHERE.get(wanted)
    if module is not None:  # the common case: one module is imported, not twenty
        for command in load(module).COMMANDS:
            if wanted == command.name or wanted in command.aliases:
                return command
    for command in all_commands():  # a name that the table does not list: found if a command has it (a test fails for the entry that is missing), else None
        if wanted == command.name or wanted in command.aliases:
            return command
    return None


def suggestions(name: str) -> list[str]:
    import difflib  # only a mistyped command needs it

    names = [command.name for command in all_commands()] + [alias for command in all_commands() for alias in command.aliases]
    return difflib.get_close_matches(name.lower(), names, n=3, cutoff=0.6)
