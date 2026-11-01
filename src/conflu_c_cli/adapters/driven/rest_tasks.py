"""The tasks that are written into pages: the REST calls. A mixin of `RestConfluenceGateway`, which provides `_call`, `_finish`, `_transport`, `_settings`,
`_next_cursor` and `_base`."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Sequence

from ...domain.errors import UnavailableError
from ...domain.model import Chunk
from .confluence_mapper import results_of
from .rest_support import V2, query, quote

# The models and the mapper of this area are imported where they are used, so that a command that never reads it does not load them (tests/test_startup.py).
if TYPE_CHECKING:
    from ...domain.tasks import Task

# The calls of this area that use the v1 API, each with why v2 does not do (see docs/reference/compatibility.md). None: v2 lists, reads and
# changes tasks, and `GET /tasks` has every filter that `conflu tasks` offers.
V1_CALLS: dict[str, str] = {}


class RestTasks:
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
        from .map_tasks import task_from

        found = query(
            body_format="storage",
            status=status,
            task_id=list(task_ids),
            space_id=list(space_ids),
            page_id=list(page_ids),
            blogpost_id=list(blogpost_ids),
            assigned_to=list(assigned_to),
            created_by=list(created_by),
            due_at_from=due_from,
            due_at_to=due_to,
            limit=limit,
            cursor=cursor,
        )
        data = self._call("GET", f"{V2}/tasks?{found}")
        return Chunk([task_from(item) for item in results_of(data)], self._next_cursor(data))

    def get_task(self, task_id: str) -> Task:
        from .map_tasks import task_from

        data = self._call("GET", f"{V2}/tasks/{quote(task_id)}?{query(body_format='storage')}")
        task = task_from(data)
        if not task.id:
            raise UnavailableError(f"Confluence answered, but not with task {task_id}.", hint="Try again; if it stays, check it with `conflu tasks`.")
        return task

    def update_task(self, task_id: str, payload: dict[str, Any]) -> Task:
        from .map_tasks import task_from

        return task_from(self._call("PUT", f"{V2}/tasks/{quote(task_id)}?{query(body_format='storage')}", payload))
