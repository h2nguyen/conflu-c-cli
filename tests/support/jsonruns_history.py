"""What the JSON reference shows for earlier versions of a page, the difference between two of them, and restoring one: one run per example, as `DocumentedJsonTest.runs` has them."""
from __future__ import annotations

import json
from typing import Any, Callable


def runs(test: Any) -> dict[str, list[Callable[[], Any]]]:
    """Heading of docs/reference/json-output.md -> one function per example under it. `test.ran(...)` runs a command and returns its JSON."""
    ran = test.ran

    def several() -> Any:
        """Three pages of which one is not there: the pages that were found are printed and the exit code is that of the one that was not."""
        result = test.cli("page", "2002", "2003", "999", "--outline", "--json")
        assert result.code == 4, result.err
        return json.loads(result.out)

    return {
        "conflu page PAGE --version N --json": [lambda: ran("page", "2002", "--version", "2", "--json")],
        "conflu page PAGE... --json": [several],
        "conflu page PAGE --attachments --json": [lambda: ran("page", "2002", "--attachments", "--json")],
        "conflu diff PAGE --json": [lambda: ran("diff", "2002", "--json")],
        "conflu restore PAGE --json": [lambda: ran("restore", "2002", "--version", "1", "--dry-run", "--json")],
        "conflu page PAGE --body-only --out FILE --json": [lambda: ran("page", "2002", "--body-only", "--out", str(test.root / "page.xml"), "--json")],
    }
