"""What the JSON reference shows for the templates of a space: one run per example, as `DocumentedJsonTest.runs` has them."""
from __future__ import annotations

from typing import Any, Callable


def runs(test: Any) -> dict[str, list[Callable[[], Any]]]:
    """Heading of docs/reference/json-output.md -> one function per example under it. `test.ran(...)` runs a command and returns its JSON."""
    ran = test.ran
    return {
        "conflu templates --json": [
            lambda: ran("templates", "--space", "ENG", "--limit", "2", "--json"),
            lambda: ran("templates", "--blueprints", "--all", "--json"),
        ],
        "conflu template ID --json": [lambda: ran("template", "7402", "--json")],
        "conflu template ID --body-only --out FILE --json": [lambda: ran("template", "7402", "--format", "storage", "--body-only", "--out", str(test.root / "body.xml"), "--json")],
    }
