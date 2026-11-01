"""What the JSON reference shows for the content properties of pages and other content: one run per example, as `DocumentedJsonTest.runs` has them."""
from __future__ import annotations

from typing import Any, Callable


def runs(test: Any) -> dict[str, list[Callable[[], Any]]]:
    """Heading of docs/reference/json-output.md -> one function per example under it. `test.ran(...)` runs a command and returns its JSON."""
    ran = test.ran
    return {
        "conflu properties ID --json": [
            lambda: ran("properties", "2002", "--key", "team.review", "--json"),
            lambda: ran("properties", "2003", "--max-chars", "60", "--json"),
        ],
        "conflu property-set ID --json": [
            lambda: ran("property-set", "2002", "--key", "team.review", "--value", '{"status":"closed"}', "--dry-run", "--json"),
            lambda: ran("property-set", "2002", "--key", "reviewed.by", "--value", '"the team"', "--json"),
        ],
    }
