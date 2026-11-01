"""What the JSON reference shows for the comments of a page: reading one, editing one, resolving and filtering: one run per example, as `DocumentedJsonTest.runs` has them."""
from __future__ import annotations

from typing import Any, Callable


def runs(test: Any) -> dict[str, list[Callable[[], Any]]]:
    """Heading of docs/reference/json-output.md -> one function per example under it. `test.ran(...)` runs a command and returns its JSON.

    The headings of `conflu comments PAGE --json` and `conflu comment PAGE --json` were there before the modes and are run in test_json_reference.py. The
    runs here are previews (`--dry-run`) or reads, which change nothing, so that they can stand in any order next to the others."""
    ran = test.ran
    return {
        "conflu comment PAGE --get ID --json": [lambda: ran("comment", "2002", "--get", "4003", "--json")],
        "conflu comment PAGE --edit ID --json": [lambda: ran("comment", "2002", "--edit", "4001", "--text", "Looks good to me.", "--dry-run", "--json")],
        "conflu comment PAGE --resolve ID --json": [lambda: ran("comment", "2002", "--resolve", "4003", "--dry-run", "--json")],
    }
