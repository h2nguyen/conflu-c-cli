"""What Confluence's JSON means for the tasks that are written into pages: the answers as domain objects."""
from __future__ import annotations

from typing import Any

from ...domain.tasks import Task
from .confluence_mapper import storage_of, user_from_id


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _account(value: Any) -> str | None:
    """An account id as the answer gives it: a text. Anything else (a number, an object) is no account id, and names nobody."""
    return value if isinstance(value, str) else None


def task_from(data: Any) -> Task:
    """A task as `GET /tasks`, `GET /tasks/{id}` and `PUT /tasks/{id}` describe it. The people are account ids, and stay ids: a name is a lookup of its own."""
    item = data if isinstance(data, dict) else {}
    return Task(
        id=_text(item.get("id")),
        status=_text(item.get("status")),
        space_id=_text(item.get("spaceId")),
        page_id=_text(item.get("pageId")),
        blogpost_id=_text(item.get("blogPostId")),
        local_id=_text(item.get("localId")),
        body=storage_of(item) or "",
        created_by=user_from_id(_account(item.get("createdBy"))),
        assigned_to=user_from_id(_account(item.get("assignedTo"))),
        completed_by=user_from_id(_account(item.get("completedBy"))),
        created=_text(item.get("createdAt")),
        updated=_text(item.get("updatedAt")),
        due=_text(item.get("dueAt")),
        completed=_text(item.get("completedAt")),
    )
