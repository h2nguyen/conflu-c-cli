"""What the JSON reference shows for what the user may do, restrictions on content, and the permissions and roles of a space: one run per example, as `DocumentedJsonTest.runs` has them."""
from __future__ import annotations

from typing import Any, Callable


def runs(test: Any) -> dict[str, list[Callable[[], Any]]]:
    """Heading of docs/reference/json-output.md -> one function per example under it. `test.ran(...)` runs a command and returns its JSON."""
    ran = test.ran
    return {
        "conflu permissions [ID] --json": [
            lambda: ran("permissions", "2002", "--json"),
            lambda: ran("permissions", "--space", "ENG", "--only", "read,update,create", "--json"),
        ],
        "conflu restrictions ID --json": [
            lambda: ran("restrictions", "2002", "--json"),
            lambda: ran("restrictions", "2002", "--with-users", "--limit", "2", "--json"),
        ],
        "conflu space-access [SPACE] --json": [
            lambda: ran("space-access", "ENG", "--json"),
            lambda: ran("space-access", "ENG", "--with-users", "--limit", "3", "--json"),
        ],
    }
