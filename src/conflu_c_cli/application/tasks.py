"""Use cases around the tasks that are written into pages: list them, show one, and complete or reopen one."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Sequence

from ..domain.content import describe, parse_content_id
from ..domain.errors import ConfluCliError, NotFoundError, UsageError, ValidationError
from ..domain.model import Space, User, parse_space_key
from ..domain.privacy import hide_space
from ..domain.tasks import COMPLETE, STATUSES, Task, due_range, parse_task_id, parse_task_ids, status_payload
from .paging import PAGE_SIZE, ensure_users_allowed, fetch_all, name_users, named
from .ports import ConfluenceGateway, Diagnostics
from .rendering import render_body
from .services import Services
from .settings import Settings


@dataclass(frozen=True)
class TaskView:
    """A task as it may be shown: its text is plain text (`task.body` is empty), and there is no person in it unless the people are shown."""

    task: Task
    text: str


UNREADABLE = "[the text of the task cannot be shown: it nests too deeply, or cannot be read]"


def present(task: Task, *, with_users: bool = False, known: dict[str, User] | None = None) -> TaskView:
    try:
        text = " ".join(render_body(task.body, "text", with_users=with_users).text.split())
    except Exception:  # noqa: BLE001 - the converter refuses a body with a ValidationError; whatever else one does to it must not stop the list of the others, nor follow a change as a crash
        text = UNREADABLE
    if with_users:
        names = known or {}
        shown = replace(task, body="", created_by=named(task.created_by, names), assigned_to=named(task.assigned_to, names), completed_by=named(task.completed_by, names))
    else:
        shown = replace(task, body="", created_by=None, assigned_to=None, completed_by=None)
    return TaskView(shown, text)


@dataclass
class TaskList:
    tasks: list[TaskView]
    next_cursor: str
    space: Space | None  # as it may be printed (`privacy.hide_space`) unless the people are shown: the key of a personal space is `[hidden]`
    truncated: bool = False
    users_shown: bool = False


class ListTasks:
    def __init__(self, gateway: ConfluenceGateway, settings: Settings, diagnostics: Diagnostics) -> None:
        self._gateway = gateway
        self._settings = settings
        self._diagnostics = diagnostics

    def execute(
        self,
        *,
        space: str = "",
        page: str = "",
        task_ids: Sequence[str] = (),
        status: str = "",
        mine: bool = False,
        created_by_me: bool = False,
        due_before: str = "",
        due_after: str = "",
        limit: int = 25,
        cursor: str = "",
        fetch_everything: bool = False,
        with_users: bool = False,
    ) -> TaskList:
        ensure_users_allowed(with_users, self._settings)
        if status and status not in STATUSES:
            raise UsageError(f"Unknown task status: {status}", hint=f"Use one of: {', '.join(STATUSES)}.")
        due_from, due_to = due_range(due_after, due_before)  # a day that is no day sends nothing
        wanted = parse_task_ids(task_ids)  # nor does an id that is no task id
        content_id = parse_content_id(page) if page else ""
        chosen = self._gateway.get_space(parse_space_key(space)) if space else None
        pages: list[str] = []
        posts: list[str] = []
        if content_id:
            (posts if self._holder(content_id) == "blogpost" else pages).append(content_id)
        me = self._token_user() if mine or created_by_me else ""

        def read(next_cursor: str):
            return self._gateway.list_tasks(
                status=status,
                task_ids=wanted,
                space_ids=[chosen.id] if chosen else [],
                page_ids=pages,
                blogpost_ids=posts,
                assigned_to=[me] if mine else [],  # the account id is the filter and is never printed
                created_by=[me] if created_by_me else [],
                due_from=due_from,
                due_to=due_to,
                limit=PAGE_SIZE if fetch_everything else limit,
                cursor=next_cursor,
            )

        if fetch_everything:
            tasks, truncated = fetch_all(read)
            following = ""
        else:
            chunk = read(cursor)
            tasks, following, truncated = chunk.items, chunk.cursor, False
        known: dict[str, User] = {}
        if with_users:
            known = name_users(self._gateway, self._diagnostics, [user for task in tasks for user in (task.created_by, task.assigned_to, task.completed_by)])
        shown = chosen if with_users or chosen is None else hide_space(chosen)  # the requests above named the space by its real key
        return TaskList([present(task, with_users=with_users, known=known) for task in tasks], following, shown, truncated, with_users)

    def _holder(self, content_id: str) -> str:
        """`page` or `blogpost`: what holds the tasks that are asked for. One request, because the ids of pages and of blog posts are one sequence."""
        kind = self._gateway.content_types([content_id]).get(content_id)
        if kind is None:
            raise NotFoundError(
                f"No page or blog post with the id {content_id} that this account can see.",
                hint="Check the id. Confluence says the same for content that does not exist and for content this account may not see.",
                details={"id": content_id},
            )
        if kind not in ("page", "blogpost"):
            raise ValidationError(
                f"{content_id} is {describe(kind)}, and tasks are written into pages and blog posts.",
                hint="Pass the id of the page or the blog post that holds the tasks.",
                details={"id": content_id, "type": kind},
            )
        return kind

    def _token_user(self) -> str:
        account = self._gateway.current_user().account_id
        if not account:
            raise ValidationError("Confluence did not say who the token belongs to, so --mine and --created-by-me have no person to look for.", hint="Check the token with `conflu ping`.")
        return account


class ShowTask:
    def __init__(self, gateway: ConfluenceGateway) -> None:
        self._gateway = gateway

    def execute(self, task_id: str) -> TaskView:
        return present(self._gateway.get_task(parse_task_id(task_id)))


@dataclass
class TaskChange:
    action: str  # completed | reopened | unchanged
    task: TaskView  # as Confluence holds it after the change (read back); as it is for a dry run and for `unchanged`
    status_from: str
    status_to: str
    payload: dict[str, str] | None  # what is sent; None when nothing is
    dry_run: bool
    read_back: bool = False  # the task was read again after the change
    notes: list[str] = field(default_factory=list)
    confirmed: bool | None = None  # the task, as read after the change, is in the state that was asked for; None for a dry run, `unchanged` and a read that failed
    message: str = ""  # what the person must know when the change was made and could not be confirmed (the exit code stays 0, and a warning says it)


class ChangeTask:
    """Completes or reopens a task. The task is read first; one that is in the state asked for is left alone; after the change it is read again, and what that
    read shows is what the answer says: a call that was accepted and changed nothing is not reported as a change that was made."""

    def __init__(self, gateway: ConfluenceGateway) -> None:
        self._gateway = gateway

    def execute(self, task_id: str, status: str, *, dry_run: bool = False) -> TaskChange:
        task_id = parse_task_id(task_id)
        payload = status_payload(status)
        current = self._gateway.get_task(task_id)
        if current.status == status:
            return TaskChange("unchanged", present(current), current.status, status, None, dry_run)
        action = "completed" if status == COMPLETE else "reopened"
        if dry_run:
            return TaskChange(action, present(current), current.status, status, payload, True)
        answered = self._gateway.update_task(task_id, payload)
        try:
            stored = self._gateway.get_task(task_id)
        except ConfluCliError as error:
            shown = answered if answered.id else replace(current, status=status)  # what Confluence answered to the change, else what was asked
            message = f"The task was {action}, but it could not be read back: {error.message.rstrip('.')}."
            return TaskChange(action, present(shown), current.status, status, payload, False, False, [message], None, message)
        if stored.status == status:
            return TaskChange(action, present(stored), current.status, status, payload, False, True, [], True, "")
        message = (
            f"Confluence accepted the change, but it holds task {task_id} as {stored.status or 'something else'}, not as {status}. "
            f"Somebody may have changed it again; check it with `conflu task {task_id} --json` (status)."
        )
        return TaskChange(action, present(stored), current.status, status, payload, False, True, [message], False, message)


@dataclass
class TasksUseCases:
    """The use cases of the area, reached as `app.tasks.<name>`."""

    list_tasks: ListTasks
    show_task: ShowTask
    change_task: ChangeTask


def build(services: Services) -> TasksUseCases:
    return TasksUseCases(
        ListTasks(services.gateway, services.settings, services.diagnostics),
        ShowTask(services.gateway),
        ChangeTask(services.gateway),
    )
