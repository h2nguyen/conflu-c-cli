"""What the JSON reference shows for the watches of the user on pages and spaces: one run per example, as `DocumentedJsonTest.runs` has them."""
from __future__ import annotations

from typing import Any, Callable


def runs(test: Any) -> dict[str, list[Callable[[], Any]]]:
    """Heading of docs/reference/json-output.md -> one function per example under it. `test.ran(...)` runs a command and returns its JSON."""
    ran = test.ran
    return {
        "conflu watching --json": [lambda: ran("watching", "2002", "--json"), lambda: ran("watching", "--space", "ENG", "--json")],
        "conflu watch --json": [lambda: ran("watch", "2002", "--dry-run", "--json"), lambda: ran("watch", "--space", "ENG", "--json")],
    }
