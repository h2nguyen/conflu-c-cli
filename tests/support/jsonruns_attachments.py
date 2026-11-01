"""What the JSON reference shows for the files attached to a page or a blog post: one attachment with its versions and labels, and the text of a document: one run per example, as `DocumentedJsonTest.runs` has them."""
from __future__ import annotations

from typing import Any, Callable


def runs(test: Any) -> dict[str, list[Callable[[], Any]]]:
    """Heading of docs/reference/json-output.md -> one function per example under it. `test.ran(...)` runs a command and returns its JSON."""
    ran = test.ran
    return {
        "conflu attachment ID --json": [lambda: ran("attachment", "att5101", "--versions", "--labels", "--json")],
        "conflu download ... --text --json": [lambda: ran("download", "att5102", "--text", "--json")],
    }
