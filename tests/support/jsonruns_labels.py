"""What the JSON reference shows for the labels used in a space, besides the labels of a page: one run per example, as `DocumentedJsonTest.runs` has them."""
from __future__ import annotations

from typing import Any, Callable


def runs(test: Any) -> dict[str, list[Callable[[], Any]]]:
    """Heading of docs/reference/json-output.md -> one function per example under it. `test.ran(...)` runs a command and returns its JSON.

    The heading of `conflu labels PAGE --json` was there before the labels of a space and is run in test_json_reference.py."""
    ran = test.ran
    return {
        "conflu labels --space KEY --json": [lambda: ran("labels", "--space", "ENG", "--limit", "2", "--json")],
    }
