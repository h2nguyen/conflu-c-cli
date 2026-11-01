"""What the JSON reference shows for blog posts: one run per example, as `DocumentedJsonTest.runs` has them."""
from __future__ import annotations

from typing import Any, Callable


def runs(test: Any) -> dict[str, list[Callable[[], Any]]]:
    """Heading of docs/reference/json-output.md -> one function per example under it. `test.ran(...)` runs a command and returns its JSON."""
    ran = test.ran
    return {
        "conflu blogposts --json": [lambda: ran("blogposts", "--space", "ENG", "--limit", "2", "--json")],
        "conflu blogpost ID --json": [lambda: ran("blogpost", "7101", "--comments", "--json")],
        "conflu blogpost ID --outline --json": [lambda: ran("blogpost", "7101", "--outline", "--json")],
        "conflu blogpost-create --json": [
            lambda: ran("blogpost-create", "--space", "ENG", "--title", "Release 2026.11 is out", "--body", "The November release is out.", "--labels", "release,news", "--json")
        ],
        "conflu blogpost-update --json": [lambda: ran("blogpost-update", "7101", "--title", "Release 2026.10 is out!", "--dry-run", "--json")],
        "conflu blogpost ID --body-only --out FILE --json": [lambda: ran("blogpost", "7101", "--body-only", "--out", str(test.root / "post.xml"), "--json")],
    }
