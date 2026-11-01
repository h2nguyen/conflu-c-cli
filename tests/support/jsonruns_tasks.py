"""What the JSON reference shows for the tasks that are written into pages: one run per example, as `DocumentedJsonTest.runs` has them."""
from __future__ import annotations

from typing import Any, Callable

from .mock_tasks import TasksRoutes


def runs(test: Any) -> dict[str, list[Callable[[], Any]]]:
    """Heading of docs/reference/json-output.md -> one function per example under it. `test.ran(...)` runs a command and returns its JSON."""
    ran = test.ran

    def accepted_and_not_made() -> Any:
        area = test.mock.area(TasksRoutes)
        area.ignores_changes = True  # a server that answers the change with success and does nothing
        try:
            return ran("task", "7206", "--complete", "--json")  # not 7203: the run before it completed that one
        finally:
            area.ignores_changes = False

    return {
        "conflu tasks --json": [
            lambda: ran("tasks", "--page", "2003", "--json"),
            lambda: ran("tasks", "--mine", "--status", "incomplete", "--limit", "1", "--with-users", "--json"),
            lambda: ran("tasks", "--task", "7205", "--json"),
        ],
        "conflu task ID --json": [
            lambda: ran("task", "7203", "--json"),
            lambda: ran("task", "7203", "--complete", "--dry-run", "--json"),
            lambda: ran("task", "7203", "--complete", "--json"),
            accepted_and_not_made,
        ],
    }
