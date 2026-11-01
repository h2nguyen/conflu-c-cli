"""The part of the Confluence port that is about the tasks that are written into pages. `ConfluenceGateway` inherits it.

A task is one checkbox of a page or a blog post. `GET /tasks` lists them across the site with the filters below; the only change that a call
can make to one is its status.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:
    from ..domain.model import Chunk
    from ..domain.tasks import Task



class TasksPort(ABC):
    @abstractmethod
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
        """The tasks that every filter that is given lets through, by id; the text of each in storage format. `status` is `complete` or `incomplete`
        (empty: both); `task_ids` are the ids of the tasks that are wanted (at most 250, see `domain.tasks.parse_task_ids`); the people are account ids;
        `due_from` and `due_to` are epoch milliseconds and both ends are included, so a task that has no due date is in no range. The ids of pages and
        blog posts are used in conjunction, as Confluence does."""

    @abstractmethod
    def get_task(self, task_id: str) -> Task:
        """The task with its text; NotFoundError when there is none, or when this account may not see it."""

    @abstractmethod
    def update_task(self, task_id: str, payload: dict[str, Any]) -> Task:
        """Sends `payload` as it is (see `domain.tasks.status_payload`): what a dry run shows is what is sent. Answers with the task as it is now."""
