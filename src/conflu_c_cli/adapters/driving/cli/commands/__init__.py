"""The command modules. To add a command: write a module with a `COMMANDS` tuple and list it here."""
from __future__ import annotations

from . import changes, info, pages, parts, session, spaces, writing

# The order decides the order of the commands inside a group of `conflu help`.
MODULES = (pages, parts, changes, writing, spaces, session, info)
