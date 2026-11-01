"""The routes of the mock Confluence for the tasks that are written into pages. `MockConfluence` asks them before its own routes (see mock_extensions.py).

`GET /tasks` with every filter that the document lists, `GET /tasks/{id}` and `PUT /tasks/{id}`, which changes the status and nothing else. The ids 7200 to 7299
belong to this area. The mock starts with (the same as `fakes_tasks.py` holds):

    7201 incomplete  page 2002 (ENG)   "Check the numbers with <a mention of Alex>"   due 2026-10-20  assigned to Alex, created by Alex
    7202 complete    page 2002 (ENG)   "Publish the release notes"                       due 2026-10-10  assigned to Sam,  created by Alex, completed by Sam
    7203 incomplete  page 2003 (ENG)   "Write ADR 0002"                                  due 2026-11-05  assigned to Alex, created by Sam
    7204 incomplete  page 2005 (ENG)   "Mail alex@example.com about the plan"            no due date     assigned to Sam,  created by Alex
    7205 incomplete  blog post 7290     "Announce the release"                            due 2026-10-25  assigned to Alex, created by Alex
    7206 incomplete  page 3001 (DOCS)   "Update the docs home"                            due 2026-12-01  assigned to Sam,  created by Sam

Alex is the user of the token. Sam is a second person whom the mock does not describe (`POST /users-bulk` knows the one person of `mock.users`, and a
second one would change what the search for people finds). The blog post 7290 is registered in `mock.content_kinds`, so that `POST /content/convert-ids-to-types`
knows what it is. The tasks sit on pages that the other tests know, which is safe: nothing a page answers mentions its tasks. `read_back_fails` makes the read
of a task right after a change answer HTTP 500, once: a change that was made and cannot be confirmed. `read_back_refusal` is the same with a `RequestError` of the
caller's choice (an HTTP 403 whose explanation holds an address, say), and it is used up by the first read that follows a change. `ignores_changes` makes
`PUT /tasks/{id}` answer as if it had worked and change nothing: a server that says yes and does nothing (`ignored` lists what it was asked).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .mock_base import RequestError, Routes

ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"  # the user of the token of the mock
SAM = "5b10ac8d82e05b22cc7d4ea1"  # a second person
BLOG_POST = "7290"
STATUSES = ("complete", "incomplete")
BODY_FORMATS = ("storage", "atlas_doc_format")
MAX_VALUES = 250  # the `maxItems` of every array parameter of the list in the document
MAX_INT64 = 2**63 - 1
LIST_PARAMETERS = {
    "body-format", "include-blank-tasks", "status", "task-id", "space-id", "page-id", "blogpost-id", "created-by", "assigned-to", "completed-by",
    "created-at-from", "created-at-to", "due-at-from", "due-at-to", "completed-at-from", "completed-at-to", "cursor", "limit",
}
CHANGE_FIELDS = {
    "id", "localId", "spaceId", "pageId", "blogPostId", "status", "createdBy", "assignedTo", "completedBy", "createdAt", "updatedAt", "dueAt", "completedAt",
}
FIRST_NEW_ID = 7207
LAST_NEW_ID = 7289


def _millis(stamp: str) -> int:
    return int(datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.000Z").replace(tzinfo=timezone.utc).timestamp() * 1000)


class TasksRoutes(Routes):
    def __init__(self, mock: Any) -> None:
        super().__init__(mock)
        self.tasks: dict[str, dict[str, Any]] = {}
        self.changes: list[tuple[str, str]] = []  # (task id, status) of every change that was saved
        self.read_back_fails = False  # the read of a task right after a change answers HTTP 500, once: a change that was made and cannot be confirmed
        self.read_back_refusal: RequestError | None = None  # the same, with this refusal instead (HTTP 403 with its own explanation, say), and really once
        self.ignores_changes = False  # the change is accepted (HTTP 200, the task as it is) and not made: a server that says yes and does nothing
        self.ignored: list[tuple[str, str]] = []  # (task id, status) of every change that was accepted and not made
        self._unread = False  # a change was made and the task has not been read since
        self._next = FIRST_NEW_ID
        if mock.populated:
            self._seed()

    # -- the data --------------------------------------------------------------------------------

    def add_task(
        self,
        text: str,
        *,
        page_id: str = "2002",
        blogpost_id: str = "",
        status: str = "incomplete",
        due: str = "",
        assigned_to: str = "",
        created_by: str = ACCOUNT,
        completed_by: str = "",
        task_id: str = "",
        storage: str = "",
    ) -> str:
        """A task on a page (or on a blog post), for a test to set up. `text` is plain text, `storage` the body as storage format instead."""
        if status not in STATUSES:
            raise ValueError(status)
        if not task_id:
            if self._next > LAST_NEW_ID:
                raise RequestError(500, "The mock has no id left", f"This mock hands out the ids {FIRST_NEW_ID} to {LAST_NEW_ID} for new tasks")
            task_id = str(self._next)
            self._next += 1
        space_id = self.mock.pages[page_id]["spaceId"] if page_id and not blogpost_id else self.mock._space_by_key("ENG")["id"]
        created = self.mock._tick()
        self.tasks[task_id] = {
            "id": task_id,
            "localId": str(1 + sum(1 for item in self.tasks.values() if item.get("pageId") == page_id and item.get("blogPostId") == blogpost_id)),
            "spaceId": space_id,
            "pageId": "" if blogpost_id else page_id,
            "blogPostId": blogpost_id,
            "status": status,
            "body": storage or f"<span>{text}</span>",
            "createdBy": created_by,
            "assignedTo": assigned_to,
            "completedBy": completed_by,
            "createdAt": created,
            "updatedAt": created,
            "dueAt": due,
            "completedAt": created if status == "complete" else "",
        }
        return task_id

    def _seed(self) -> None:
        self.mock.content_kinds.setdefault(BLOG_POST, "blogpost")
        mention = f'<ac:link><ri:user ri:account-id="{ACCOUNT}" /></ac:link>'
        names = ("id", "status", "spaceId", "pageId", "blogPostId", "localId", "body", "createdBy", "assignedTo", "completedBy", "createdAt", "updatedAt", "dueAt", "completedAt")
        rows = (
            ("7201", "incomplete", "1001", "2002", "", "1", f"<span>Check the numbers with {mention}</span>", ACCOUNT, ACCOUNT, "", "2026-10-02T09:00:00.000Z", "2026-10-02T09:00:00.000Z", "2026-10-20T00:00:00.000Z", ""),
            ("7202", "complete", "1001", "2002", "", "2", "<span>Publish the release notes</span>", ACCOUNT, SAM, SAM, "2026-10-02T09:01:00.000Z", "2026-10-09T12:00:00.000Z", "2026-10-10T00:00:00.000Z", "2026-10-09T12:00:00.000Z"),
            ("7203", "incomplete", "1001", "2003", "", "1", "<span>Write ADR 0002</span>", SAM, ACCOUNT, "", "2026-10-03T10:00:00.000Z", "2026-10-03T10:00:00.000Z", "2026-11-05T00:00:00.000Z", ""),
            ("7204", "incomplete", "1001", "2005", "", "1", "<span>Mail alex@example.com about the plan</span>", ACCOUNT, SAM, "", "2026-10-04T11:00:00.000Z", "2026-10-04T11:00:00.000Z", "", ""),
            ("7205", "incomplete", "1001", "", BLOG_POST, "1", "<span>Announce the release</span>", ACCOUNT, ACCOUNT, "", "2026-10-05T08:00:00.000Z", "2026-10-05T08:00:00.000Z", "2026-10-25T00:00:00.000Z", ""),
            ("7206", "incomplete", "1002", "3001", "", "1", "<span>Update the docs home</span>", SAM, SAM, "", "2026-10-06T14:00:00.000Z", "2026-10-06T14:00:00.000Z", "2026-12-01T00:00:00.000Z", ""),
        )
        for row in rows:
            task = dict(zip(names, row))
            self.tasks[task["id"]] = task

    def _model(self, task: dict[str, Any], body_format: str | None) -> dict[str, Any]:
        """A task as the document describes it: what it has is there, what it has not is left out."""
        model: dict[str, Any] = {key: task[key] for key in ("id", "localId", "spaceId", "status", "createdAt", "updatedAt")}
        for key in ("pageId", "blogPostId", "createdBy", "assignedTo", "completedBy", "dueAt", "completedAt"):
            if task.get(key):
                model[key] = task[key]
        if body_format == "storage":
            model["body"] = {"storage": {"representation": "storage", "value": task["body"]}}
        elif body_format == "atlas_doc_format":
            model["body"] = {"atlas_doc_format": {"representation": "atlas_doc_format", "value": json.dumps({"type": "doc", "version": 1, "content": []})}}
        else:
            model["body"] = {}
        return model

    # -- the routes ------------------------------------------------------------------------------

    def handle(self, handler: Any, method: str, path: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]], body: Any) -> bool:
        if path == "/api/v2/tasks" and method == "GET":
            self._list(handler, query, query_pairs)
            return True
        found = self.match(r"/api/v2/tasks/([^/]+)", path)
        if found is None or method not in ("GET", "PUT"):
            return False
        task_id = found.group(1)
        handler._require_known_query(query, {"body-format"})
        body_format = self._body_format(handler, query)
        if not (len(task_id) <= 19 and task_id.isascii() and task_id.isdigit() and int(task_id) <= MAX_INT64):
            raise RequestError(400, "Invalid request parameter", "id must be an integer")
        task = self.tasks.get(task_id)
        if task is None:
            raise RequestError(404, "Not found", f"Task not found: {task_id}", code="NOT_FOUND")
        if method == "PUT":
            self._change(handler, task, body)
            self._unread = True
        elif self.read_back_refusal is not None and self._unread:
            self._unread = False
            refusal, self.read_back_refusal = self.read_back_refusal, None
            raise refusal
        elif self.read_back_fails and self._unread:
            self._unread = False
            raise RequestError(500, "Server error", "The task cannot be read", code="INTERNAL_ERROR")
        else:
            self._unread = False
        handler._reply_json(200, self._model(task, body_format))
        return True

    @staticmethod
    def _body_format(handler: Any, query: dict[str, list[str]]) -> str | None:
        found = handler._single(query, "body-format")
        if found not in {None, *BODY_FORMATS}:
            raise RequestError(400, "Invalid request parameter", f"Unsupported value for body-format: {found}")
        return found

    def _change(self, handler: Any, task: dict[str, Any], body: Any) -> None:
        data = handler._require_object(body)
        unknown = sorted(set(data) - CHANGE_FIELDS)
        if unknown:
            raise RequestError(400, "Invalid request body", f"Unknown property: {unknown[0]}")
        status = data.get("status")
        if not isinstance(status, str) or status not in STATUSES:
            raise RequestError(400, "Invalid request body", "status is required and must be complete or incomplete")
        if self.ignores_changes:
            self.ignored.append((task["id"], status))
            return
        if status != task["status"]:
            stamp = self.mock._tick()
            task["status"], task["updatedAt"] = status, stamp
            task["completedAt"], task["completedBy"] = (stamp, ACCOUNT) if status == "complete" else ("", "")
        self.changes.append((task["id"], status))

    def _list(self, handler: Any, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        handler._require_known_query(query, LIST_PARAMETERS)
        body_format = self._body_format(handler, query)
        status = handler._single(query, "status")
        if status is not None and status not in STATUSES:
            raise RequestError(400, "Invalid request parameter", f"Unsupported value for status: {status}")
        handler._parse_bool(handler._single(query, "include-blank-tasks"), "include-blank-tasks")
        numbers = {name: self._numbers(handler, query, name) for name in ("task-id", "space-id", "page-id", "blogpost-id")}
        people = {name: handler._parse_csv(handler._single(query, name), name) for name in ("created-by", "assigned-to", "completed-by")}
        for name, values in people.items():
            if len(values) > MAX_VALUES:
                raise RequestError(400, "Invalid request parameter", f"{name} takes at most {MAX_VALUES} values")
        names = ("created-at-from", "created-at-to", "due-at-from", "due-at-to", "completed-at-from", "completed-at-to")
        ranges = {name: handler._parse_int_query(handler._single(query, name), name) for name in names}
        limit = handler._parse_limit(query, default=25)
        offset = handler._parse_cursor(query)

        def person(task: dict[str, Any], key: str, name: str) -> bool:
            return not people[name] or task.get(key, "") in people[name]

        def within(task: dict[str, Any], key: str, low: int | None, high: int | None) -> bool:
            if low is None and high is None:
                return True
            if not task.get(key):  # a task without that date is in no range
                return False
            moment = _millis(task[key])
            return (low is None or moment >= low) and (high is None or moment <= high)

        found = [
            task
            for task in self.tasks.values()
            if (status is None or task["status"] == status)
            and (not numbers["task-id"] or task["id"] in numbers["task-id"])
            and (not numbers["space-id"] or task["spaceId"] in numbers["space-id"])
            # the filters of pages and of blog posts are used together: a task is in a page or in a blog post, so a task is kept by either
            and (not (numbers["page-id"] or numbers["blogpost-id"]) or task.get("pageId") in numbers["page-id"] or task.get("blogPostId") in numbers["blogpost-id"])
            and person(task, "createdBy", "created-by")
            and person(task, "assignedTo", "assigned-to")
            and person(task, "completedBy", "completed-by")
            and within(task, "createdAt", ranges["created-at-from"], ranges["created-at-to"])
            and within(task, "dueAt", ranges["due-at-from"], ranges["due-at-to"])
            and within(task, "completedAt", ranges["completed-at-from"], ranges["completed-at-to"])
        ]
        found.sort(key=lambda task: int(task["id"]))
        shown, links, headers = handler._apply_pagination(found, path="/api/v2/tasks", query_pairs=query_pairs, offset=offset, limit=limit)
        handler._reply_json(200, {"results": [self._model(task, body_format) for task in shown], "_links": links}, headers)

    @staticmethod
    def _numbers(handler: Any, query: dict[str, list[str]], name: str) -> list[str]:
        values = handler._parse_csv(handler._single(query, name), name)
        if len(values) > MAX_VALUES:
            raise RequestError(400, "Invalid request parameter", f"{name} takes at most {MAX_VALUES} values")
        if not all(len(value) <= 19 and value.isascii() and value.isdigit() and int(value) <= MAX_INT64 for value in values):
            raise RequestError(400, "Invalid request parameter", f"{name} must hold integers")
        return values
