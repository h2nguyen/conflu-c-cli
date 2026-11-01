"""The sweep lines of the tasks that are written into pages: see sweeps.py. Each module runs its lines in order against a mock of its own.

The mock starts with the tasks 7201 to 7206 (see mock_tasks.py): on the pages 2002 (two: one with a mention of Alex), 2003, 2005 and 3001 (the space DOCS) and in
the blog post 7290, assigned to Alex, to a second person or to nobody. Alex is the user of the token, so the lines that name people have a person to hide.

`PREPARE` makes the mock refuse three requests with HTTP 403, each once, and the explanation of each holds the address of a person, as Confluence's can: the
first read of the list, the read of the task 7298 and the change of the task 7205. It makes a fourth refusal, of the same kind, for the read that follows the
first change that is made, so that a change can be made and not be confirmed. The four lines that meet them stand first, in this order, and the lines below
are not refused: a refusal is made for the first request of its kind, so a line that is put before them would take one."""
from __future__ import annotations

from typing import Any

from .mock_base import RequestError
from .mock_tasks import TasksRoutes
from .sweeps import line

REFUSAL = {"errors": [{"status": 403, "code": "FORBIDDEN", "title": "Forbidden", "detail": "alex@example.com may not see or change this task"}]}


def prepare(mock: Any) -> None:
    mock.fail_next("/api/v2/tasks/7298", 403, method="GET", body=REFUSAL)  # a task that this account may not see
    mock.fail_next("/api/v2/tasks/7205", 403, method="PUT", body=REFUSAL)  # a task that it may read and not change
    mock.fail_next("/api/v2/tasks", 403, method="GET", body=REFUSAL)  # the list; queued last, because the paths of the two above begin with this one
    mock.area(TasksRoutes).read_back_refusal = RequestError(403, "Forbidden", REFUSAL["errors"][0]["detail"], code="FORBIDDEN")  # a change that cannot be confirmed


PREPARE = prepare

LINES = (
    # what Confluence refuses with HTTP 403, and says an address in its explanation: the list, one task, a change, and the read after a change (see PREPARE; they stand first)
    line("tasks", "--status", "incomplete", code=5),
    line("task", "7298", code=5),
    line("task", "7205", "--complete", code=5),
    line("task", "7206", "--complete"),
    # the list: a piece, the next piece, all of it, shaped for a script
    line("tasks"),
    line("tasks", "--limit", "1", "--cursor", "2"),
    line("tasks", "--all", "--select", "id,status,dueAt", "--format", "tsv"),
    line("tasks", "--all", "--json"),
    # every filter of the call: a space, a page, a blog post, a status, the person of the token, a range of due days
    line("tasks", "--space", "ENG", "--status", "incomplete", "--all"),
    line("tasks", "--space", "eng", "--status", "complete"),
    line("tasks", "--space", "DOCS", "--json"),
    line("tasks", "--page", "2002", "--status", "complete"),
    line("tasks", "--page", "7290"),
    line("tasks", "--mine", "--status", "incomplete", "--all"),
    line("tasks", "--created-by-me", "--all", "--json"),
    line("tasks", "--due-after", "2026-10-15", "--due-before", "2026-11-30", "--all"),
    line("tasks", "--all", "--with-users"),
    line("tasks", "--page", "2002", "--with-users", "--json"),
    # tasks by id: one, several, one whose text has an address and one with a mention, one that no task has, with the other filters and with the people
    line("tasks", "--task", "7201"),
    line("tasks", "--task", "7203", "--task", "7205", "--json"),
    line("tasks", "--task", "7204"),
    line("tasks", "--task", "7201", "--task", "7204", "--json"),
    line("tasks", "--task", "7288"),
    line("tasks", "--task", "7201", "--task", "7202", "--task", "7203", "--status", "complete", "--page", "2002", "--all"),
    line("tasks", "--task", "7202", "--with-users"),
    line("tasks", "--task", "7204", "--with-users", "--json"),
    # what is refused
    line("tasks", "--due-before", "2026-02-30", code=2),
    line("tasks", "--task", "abc", code=2),
    line("tasks", "--task", "0", code=2),
    line("tasks", "--space", "NOPE", code=4),
    line("tasks", "--page", "99999", code=4),
    line("tasks", "--page", "7001", code=1),  # a folder holds no tasks
    # one task, and its change: the dry run, the change, the same change again, and back
    line("task", "7201"),
    line("task", "7203", "--json"),
    line("task", "7201", "--complete", "--dry-run"),
    line("task", "7201", "--complete", "--dry-run", "--json"),
    line("task", "7201", "--complete"),
    line("task", "7201", "--complete"),
    line("task", "7201", "--reopen", "--dry-run"),
    line("task", "7201", "--reopen", "--json"),
    line("task", "7202", "--reopen"),
    line("task", "99999", code=4),
    line("task", "7201", "--complete", "--reopen", code=2),
)
