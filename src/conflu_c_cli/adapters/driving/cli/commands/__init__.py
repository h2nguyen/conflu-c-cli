"""The command modules. To add a command: write a module with a `COMMANDS` tuple, list the module in `MODULE_NAMES` and each name and alias of its commands in `WHERE`.

The modules are imported when they are needed: a command that runs imports its own module and what that uses, not the nineteen others, and `conflu version`
starts about a quarter of a second sooner on a computer where every file costs a virus scan. `help`, `commands`, `mcp` and a mistyped command need all of
them (`registry.all_commands`). `tests/cli/test_registry_lazy.py` holds `WHERE` to what the modules declare, so a command that is missing there fails a test
and is found all the same, slowly.
"""
from __future__ import annotations

import importlib
from types import ModuleType

# The order decides the order of the commands inside a group of `conflu help`.
MODULE_NAMES = (
    "pages",
    "structure",
    "history",
    "blogposts",
    "comments",
    "labels",
    "attachments",
    "changes",
    "writing",
    "access",
    "watches",
    "users",
    "tasks",
    "properties",
    "templates",
    "spaces",
    "session",
    "setup",
    "info",
    "mcp",
)

# Every command name and alias -> the module that declares it.
WHERE: dict[str, str] = {
    "page": "pages", "pages": "pages", "versions": "pages", "search": "pages", "export": "pages", "tree": "structure", "move": "structure",
    "folder": "structure", "whiteboard": "structure", "database": "structure", "smartlink": "structure", "folder-create": "structure",
    "smartlink-create": "structure", "diff": "history", "restore": "history", "blogposts": "blogposts", "blogpost": "blogposts",
    "blogpost-create": "blogposts", "blogpost-update": "blogposts", "comments": "comments", "comment": "comments", "labels": "labels", "label": "labels",
    "attachments": "attachments", "attachment": "attachments", "download": "attachments", "attach": "attachments", "update": "changes",
    "create": "writing", "import-md": "writing", "import-md-dir": "writing", "permissions": "access", "restrictions": "access", "space-access": "access",
    "watching": "watches", "watch": "watches", "users": "users", "tasks": "tasks", "task": "tasks", "properties": "properties",
    "property-set": "properties", "templates": "templates", "template": "templates", "spaces": "spaces", "space": "spaces", "setup-token": "session",
    "remove-token": "session", "use": "session", "current": "session", "clear-space": "session", "config": "session", "ping": "session",
    "doctor": "session", "setup": "setup", "help": "info", "commands": "info", "version": "info", "changelog": "info", "changes": "info",
    "history": "info", "how-to": "info", "howto": "info", "readme": "info", "docs": "info", "skill": "info", "convert": "info", "api": "info",
    "mcp": "mcp",
}


def load(name: str) -> ModuleType:
    """The command module of that name, imported on the first ask."""
    return importlib.import_module(f"{__name__}.{name}")


def __getattr__(name: str) -> tuple[ModuleType, ...]:
    """`MODULES`, the tuple of all the command modules in the order of `MODULE_NAMES`, imported when it is asked for (PEP 562)."""
    if name == "MODULES":
        return tuple(load(module) for module in MODULE_NAMES)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
