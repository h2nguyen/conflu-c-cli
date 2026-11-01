"""What the JSON reference shows for looking up people: one run per example, as `DocumentedJsonTest.runs` has them."""
from __future__ import annotations

from typing import Any, Callable


def runs(test: Any) -> dict[str, list[Callable[[], Any]]]:
    """Heading of docs/reference/json-output.md -> one function per example under it. `test.ran(...)` runs a command and returns its JSON."""
    ran = test.ran
    return {
        "conflu users search TEXT --json": [lambda: ran("users", "search", "alex", "--with-users", "--json")],
        "conflu users lookup ACCOUNT_ID --json": [lambda: ran("users", "lookup", "5b10ac8d82e05b22cc7d4ef5", "0000000000000000000000ff", "--with-users", "--json")],
    }
