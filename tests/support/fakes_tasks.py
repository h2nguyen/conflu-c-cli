"""The in-memory Confluence for the tasks that are written into pages: a mixin of `FakeGateway` (`_init_tasks` sets up its state).

What it holds when a test starts (ids 7200 to 7299 belong to this area; the tasks sit on the pages that the other tests know, and in one blog post):

    7201 incomplete  page 2002 (ENG)   "Check the numbers with <a mention of Alex>"   due 2026-10-20  assigned to Alex, created by Alex
    7202 complete    page 2002 (ENG)   "Publish the release notes"                       due 2026-10-10  assigned to Sam,  created by Alex, completed by Sam
    7203 incomplete  page 2003 (ENG)   "Write ADR 0002"                                  due 2026-11-05  assigned to Alex, created by Sam
    7204 incomplete  page 2005 (ENG)   "Mail alex@example.com about the plan"            no due date     assigned to Sam,  created by Alex
    7205 incomplete  blog post 7290    "Announce the release"                            due 2026-10-25  assigned to Alex, created by Alex
    7206 incomplete  page 3001 (DOCS)  "Update the docs home"                            due 2026-12-01  assigned to Sam,  created by Sam

Alex is the user of the token; Sam is a second person (`SAM`) whom `lookup_users` does not describe, as in the mock (a test that wants a name for Sam
puts `SAM` into `users` itself: a second person known to every test would change what the other areas find).
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from typing import Any, Sequence

from conflu_c_cli.domain.errors import NotFoundError, RejectedError
from conflu_c_cli.domain.model import Chunk, User
from conflu_c_cli.domain.tasks import COMPLETE, INCOMPLETE, STATUSES, Task

SAM = User("5b10ac8d82e05b22cc7d4ea1", "Sam Example", "sam@example.com")  # a second person: the token belongs to Alex
BLOG_POST = "7290"  # the blog post that holds task 7205
MAX_IDS = 250  # how many ids a filter of the list takes: the `maxItems` of its parameter in the document


def _millis(stamp: str) -> int:
    return int(datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.000Z").replace(tzinfo=timezone.utc).timestamp() * 1000)


class FakeTasks:
    def _init_tasks(self) -> None:
        from .fakes import ACCOUNT

        alex = User(ACCOUNT)
        sam = User(SAM.account_id)
        self.content_kinds.setdefault(BLOG_POST, "blogpost")
        mention = f'<ri:user ri:account-id="{ACCOUNT}" />'
        tasks = [
            Task("7201", INCOMPLETE, "1001", "2002", "", "1", f"<span>Check the numbers with <ac:link>{mention}</ac:link></span>", alex, alex, None,
                 "2026-10-02T09:00:00.000Z", "2026-10-02T09:00:00.000Z", "2026-10-20T00:00:00.000Z", ""),
            Task("7202", COMPLETE, "1001", "2002", "", "2", "<span>Publish the release notes</span>", alex, sam, sam,
                 "2026-10-02T09:01:00.000Z", "2026-10-09T12:00:00.000Z", "2026-10-10T00:00:00.000Z", "2026-10-09T12:00:00.000Z"),
            Task("7203", INCOMPLETE, "1001", "2003", "", "1", "<span>Write ADR 0002</span>", sam, alex, None,
                 "2026-10-03T10:00:00.000Z", "2026-10-03T10:00:00.000Z", "2026-11-05T00:00:00.000Z", ""),
            Task("7204", INCOMPLETE, "1001", "2005", "", "1", "<span>Mail alex@example.com about the plan</span>", alex, sam, None,
                 "2026-10-04T11:00:00.000Z", "2026-10-04T11:00:00.000Z", "", ""),
            Task("7205", INCOMPLETE, "1001", "", BLOG_POST, "1", "<span>Announce the release</span>", alex, alex, None,
                 "2026-10-05T08:00:00.000Z", "2026-10-05T08:00:00.000Z", "2026-10-25T00:00:00.000Z", ""),
            Task("7206", INCOMPLETE, "1002", "3001", "", "1", "<span>Update the docs home</span>", sam, sam, None,
                 "2026-10-06T14:00:00.000Z", "2026-10-06T14:00:00.000Z", "2026-12-01T00:00:00.000Z", ""),
        ]
        self.tasks: dict[str, Task] = {task.id: task for task in tasks}
        self.task_clock = 0  # the minutes after 2026-10-15 08:00 at which the next change of a task is saved

    # -- the port ---------------------------------------------------------------------------

    def list_tasks(
        self,
        *,
        status: str = "",
        task_ids: Sequence[str] = (),
        space_ids: Sequence[str] = (),
        page_ids: Sequence[str] = (),
        blogpost_ids: Sequence[str] = (),
        assigned_to: Sequence[str] = (),
        created_by: Sequence[str] = (),
        due_from: int | None = None,
        due_to: int | None = None,
        limit: int = 25,
        cursor: str = "",
    ) -> Chunk[Task]:
        self._enter("list_tasks", status, tuple(task_ids), tuple(space_ids), tuple(page_ids), tuple(blogpost_ids), tuple(assigned_to), tuple(created_by), due_from, due_to, limit, cursor)
        if len(task_ids) > MAX_IDS:
            raise RejectedError(f"Confluence refused the request (HTTP 400): task-id takes at most {MAX_IDS} values")

        def person_in(user: User | None, wanted: Sequence[str]) -> bool:
            return not wanted or (user is not None and user.account_id in wanted)

        def due_in(task: Task) -> bool:
            if due_from is None and due_to is None:
                return True
            if not task.due:  # a task without a due date is in no range
                return False
            moment = _millis(task.due)
            return (due_from is None or moment >= due_from) and (due_to is None or moment <= due_to)

        found = [
            task
            for task in self.tasks.values()
            if (not status or task.status == status)
            and (not task_ids or task.id in task_ids)
            and (not space_ids or task.space_id in space_ids)
            and (not (page_ids or blogpost_ids) or task.page_id in page_ids or task.blogpost_id in blogpost_ids)  # the two filters are used in conjunction
            and person_in(task.assigned_to, assigned_to)
            and person_in(task.created_by, created_by)
            and due_in(task)
        ]
        return self._chunk(sorted(found, key=lambda task: int(task.id)), cursor, limit)

    def get_task(self, task_id: str) -> Task:
        self._enter("get_task", task_id)
        if task_id not in self.tasks:
            raise NotFoundError(f"Not found: GET /api/v2/tasks/{task_id}")
        return self.tasks[task_id]

    def update_task(self, task_id: str, payload: dict[str, Any]) -> Task:
        self._enter("update_task", task_id, payload)
        if task_id not in self.tasks:
            raise NotFoundError(f"Not found: PUT /api/v2/tasks/{task_id}")
        task = self.tasks[task_id]
        status = payload.get("status")
        if status not in STATUSES:
            raise RejectedError(f"Confluence refused the request (HTTP 400): status must be one of {', '.join(STATUSES)}")
        self.task_clock += 1
        stamp = f"2026-10-15T08:{self.task_clock:02d}:00.000Z"
        done = status == COMPLETE
        changed = dataclasses.replace(
            task, status=status, updated=stamp, completed=stamp if done else "", completed_by=User(self.user.account_id) if done else None
        )
        self.tasks[task_id] = changed
        return changed
