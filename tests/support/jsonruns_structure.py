"""What the JSON reference shows for folders, whiteboards, databases and smart links, and where content sits in the tree: one run per example, as `DocumentedJsonTest.runs` has them."""
from __future__ import annotations

from typing import Any, Callable


def runs(test: Any) -> dict[str, list[Callable[[], Any]]]:
    """Heading of docs/reference/json-output.md -> one function per example under it. `test.ran(...)` runs a command and returns its JSON."""
    ran = test.ran
    return {
        "conflu folder ID --json": [lambda: ran("folder", "7001", "--children", "--ancestors", "--json")],
        "conflu whiteboard ID --json": [lambda: ran("whiteboard", "7021", "--ancestors", "--json")],
        "conflu database ID --json": [lambda: ran("database", "7041", "--entries", "--json"), lambda: ran("database", "7041", "--fields", "--json")],
        "conflu smartlink ID --json": [lambda: ran("smartlink", "7061", "--ancestors", "--json")],
        "conflu folder-create --json": [lambda: ran("folder-create", "--title", "Runbooks 2026", "--space", "ENG", "--parent", "7001", "--json")],
        "conflu smartlink-create --json": [
            lambda: ran("smartlink-create", "--url", "https://example.com/roadmap", "--title", "Roadmap 2026", "--space", "ENG", "--dry-run", "--json")
        ],
        "conflu move PAGE --to FOLDER --json": [lambda: ran("move", "2005", "--to", "7001", "--dry-run", "--json")],
    }
