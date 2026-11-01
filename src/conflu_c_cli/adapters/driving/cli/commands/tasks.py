"""Commands about the tasks that are written into pages: tasks, task."""
from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from .....domain.errors import UsageError
from .....domain.tasks import COMPLETE, INCOMPLETE, STATUSES
from ..listing import FORMAT, SELECT, print_list
from ..render import key_values, one_line, table
from ..runtime import Context
from ..spec import Arg, Command, Example
from ._common import LIMIT_HELP, check_limit, pretty, user_json, user_name

if TYPE_CHECKING:
    from .....application.tasks import TaskChange, TaskList, TaskView

GROUP = "Tasks and properties"

CURSOR = Arg(("--cursor",), "Continue after the end of the previous answer: pass its nextCursor.", metavar="TOKEN")
ALL = "Fetch every page of the list instead of one. --limit and --cursor are not used then, but a --limit out of range is still refused."


def task_json(view: TaskView) -> dict[str, Any]:
    """A task as a row. The three people are null unless the people are shown; `text` has no person in it either."""
    task = view.task
    return {
        "id": task.id,
        "localId": task.local_id or None,
        "status": task.status,
        "pageId": task.page_id or None,
        "blogPostId": task.blogpost_id or None,
        "spaceId": task.space_id or None,
        "text": view.text,
        "dueAt": task.due or None,
        "createdAt": task.created or None,
        "updatedAt": task.updated or None,
        "completedAt": task.completed or None,
        "assignedTo": user_json(task.assigned_to),
        "createdBy": user_json(task.created_by),
        "completedBy": user_json(task.completed_by),
    }


def task_columns(rows: list[dict[str, Any]], *, users_shown: bool) -> list[tuple[str, str]]:
    columns = [("ID", "id"), ("STATUS", "status"), ("DUE", "dueAt"), ("PAGE", "pageId")]
    if any(row["blogPostId"] for row in rows):
        columns.append(("BLOG POST", "blogPostId"))
    columns.append(("TEXT", "text"))
    if users_shown:
        columns.append(("ASSIGNED", "assignedTo.displayName"))
    return columns


def tasks_text(result: TaskList) -> str:
    if not result.tasks:
        return "No tasks."
    blog = any(view.task.blogpost_id for view in result.tasks)
    headers = ["ID", "STATUS", "DUE", "PAGE"] + (["BLOG POST"] if blog else []) + ["TEXT"] + (["ASSIGNED"] if result.users_shown else [])
    rows = [
        [view.task.id, view.task.status, view.task.due, view.task.page_id]
        + ([view.task.blogpost_id] if blog else [])
        + [view.text]
        + ([user_name(view.task.assigned_to)] if result.users_shown else [])
        for view in result.tasks
    ]
    return table(headers, rows)


def run_tasks(ctx: Context, args: argparse.Namespace) -> int:
    check_limit(args.limit)
    result = ctx.app.tasks.list_tasks.execute(
        space=args.space or "",
        page=args.page or "",
        task_ids=args.task or [],
        status=args.status or "",
        mine=args.mine,
        created_by_me=args.created_by_me,
        due_before=args.due_before or "",
        due_after=args.due_after or "",
        limit=args.limit,
        cursor=args.cursor or "",
        fetch_everything=args.all,
        with_users=args.with_users,
    )
    rows = [task_json(view) for view in result.tasks]
    document = {
        "space": result.space.key if result.space else None,
        "count": len(rows),
        "nextCursor": result.next_cursor or None,
        "truncated": result.truncated,
        "tasks": rows,
    }
    columns = task_columns(rows, users_shown=result.users_shown)
    if print_list(ctx, args, payload=document, rows=rows, list_key="tasks", columns=columns, plain=lambda: tasks_text(result)) or not result.tasks:
        return 0
    if result.next_cursor:
        ctx.diagnostics.info(f"More tasks follow. Continue with --cursor {result.next_cursor}, or use --all.")
    if result.truncated:
        ctx.diagnostics.warn("The list was cut short at its limit; narrow it with --space, --page, --status or --due-before.")
    return 0


def task_text(view: TaskView) -> str:
    task = view.task
    pairs = [
        ("Status", task.status),
        ("Page", task.page_id),
        ("Blog post", task.blogpost_id),
        ("Space id", task.space_id),
        ("Due", task.due),
        ("Created", task.created),
        ("Updated", task.updated),
        ("Completed", task.completed),
    ]
    return f"{one_line(view.text) or '(a task without text)'}  [{one_line(task.id)}]\n{key_values([(label, one_line(value)) for label, value in pairs])}"


def change_text(result: TaskChange) -> str:
    task = result.task.task
    steps = f"{result.status_from or 'unknown'} -> {result.status_to}"
    if result.action == "unchanged":
        return f"Nothing to change: task {task.id} is {result.status_to} already."
    if result.dry_run:
        return f"Dry run: task {task.id} would be {result.action} ({steps}); nothing was sent\n{pretty(result.payload)}"
    if result.confirmed is False:  # the read after the change shows the other state: whatever the call answered, it is not "completed" or "reopened"
        verb = "complete" if result.status_to == COMPLETE else "reopen"
        return f"Confluence accepted the request to {verb} task {task.id} ({steps}), but it still shows the task as {task.status or 'something else'}."
    shown = one_line(result.task.text)
    return f"{result.action.capitalize()} task {task.id}: {shown} ({steps})" if shown else f"{result.action.capitalize()} task {task.id} ({steps})"


def run_task(ctx: Context, args: argparse.Namespace) -> int:
    if args.complete and args.reopen:
        raise UsageError("Use either --complete or --reopen, not both.")
    if not (args.complete or args.reopen):
        if args.dry_run:
            raise UsageError("--dry-run previews --complete or --reopen; `conflu task ID` alone changes nothing.", hint="Add --complete or --reopen.")
        view = ctx.app.tasks.show_task.execute(args.id)
        ctx.print_json(task_json(view)) if ctx.json_mode else ctx.print(task_text(view))
        return 0
    result = ctx.app.tasks.change_task.execute(args.id, COMPLETE if args.complete else INCOMPLETE, dry_run=args.dry_run)
    for note in result.notes:
        ctx.diagnostics.warn(note)
    if ctx.json_mode:
        ctx.print_json(
            {
                "action": result.action,
                "dryRun": result.dry_run,
                "taskId": result.task.task.id,
                "statusFrom": result.status_from or None,
                "statusTo": result.status_to,
                "readBack": result.read_back,
                "notes": result.notes,
                "payload": result.payload,
                "task": task_json(result.task),
                "confirmed": result.confirmed,
                "message": result.message or None,
            }
        )
    else:
        ctx.print(change_text(result))
    return 0


COMMANDS = (
    Command(
        name="tasks",
        group=GROUP,
        summary="List the tasks that are written into pages",
        when="Use to find the tasks (checkboxes) of pages and blog posts: your open ones with --mine --status incomplete, those of one page with --page, "
        "those of a space, those that are due soon, or those with ids that you have (--task). To complete or reopen one use `task`.",
        description="Lists the tasks of the whole site, or narrows them: to one space (--space), one page or blog post (--page), the tasks with some ids "
        "(--task, once for each: the way to read one task), a status, the tasks that are assigned to you (--mine) or that you created "
        "(--created-by-me), and a range of due days. Every filter that is given must hold. The text of a task is shown as plain text, without the "
        "people in it. Who created, was assigned and completed a task is shown only with --with-users. A task without a due date is in no range of "
        "due days. An id that no task has, or that the other filters do not let through, is not in the list: that is no error.",
        args=(
            Arg(("--space",), "Only the tasks of this space (its key). Without it the whole site: the current space is not used.", metavar="KEY"),
            Arg(("--page",), "Only the tasks of this page or blog post: its id, or the address as copied from the browser.", metavar="ID"),
            Arg(("--task",), "Only the task with this id, a positive whole number; repeat the option for more tasks, at most 250.", kind="repeat", metavar="ID"),
            Arg(("--status",), "Only the tasks that are incomplete, or only those that are complete. Without it both.", kind="choice", choices=STATUSES),
            Arg(("--mine",), "Only the tasks that are assigned to the user of the token. The account id is used for the search and is never printed.", kind="flag"),
            Arg(("--created-by-me",), "Only the tasks that the user of the token created.", kind="flag"),
            Arg(("--due-before",), "Only the tasks that are due at or before 00:00 UTC of this day (YYYY-MM-DD).", metavar="DATE"),
            Arg(("--due-after",), "Only the tasks that are due at or after 00:00 UTC of this day (YYYY-MM-DD).", metavar="DATE"),
            Arg(("--limit",), LIMIT_HELP, kind="int", default=25, metavar="N"),
            CURSOR,
            Arg(("--all",), ALL, kind="flag"),
            Arg(("--with-users",), "Show who created, was assigned and completed each task. Refused when CONFLUENCE_HIDE_USERS=true.", kind="flag"),
            SELECT,
            FORMAT,
        ),
        examples=(
            Example("conflu tasks --mine --status incomplete", "your open tasks"),
            Example("conflu tasks --page 123456 --json", "the tasks of one page, for a script or an agent"),
            Example("conflu tasks --task 7201 --task 7203 --json", "the tasks with these ids"),
            Example("conflu tasks --space ENG --due-after 2026-10-26 --due-before 2026-11-01", "what is due in a week"),
            Example("conflu tasks --created-by-me --status complete --all --select id,pageId,completedAt --format tsv"),
            Example("conflu tasks --mine --with-users"),
        ),
        notes=(
            "A date is a day, YYYY-MM-DD, counted from 00:00 UTC; a date that is no day, or that is before 1970, is a usage error.",
            "`--mine` needs one more request, to find out who the token belongs to; the account id never appears in the output.",
        ),
        json_output=True,
        output="space (key, [hidden] for a personal space unless --with-users, or null), count, nextCursor (null on the last page), truncated and tasks[]: id, localId, status (complete or incomplete), pageId and "
        "blogPostId (one of the two is null), spaceId, text (plain text), dueAt, createdAt, updatedAt, completedAt, assignedTo, createdBy and completedBy "
        "({accountId, displayName, email}: null unless --with-users); with --select only those (dotted) keys of every task.",
        handler=run_tasks,
    ),
    Command(
        name="task",
        group=GROUP,
        summary="Show a task, or complete or reopen it",
        when="Use to read one task, or to tick it off (--complete) or untick it (--reopen). Preview with --dry-run. To find the id of a task use `tasks`.",
        description="Without --complete or --reopen it shows the task and changes nothing. With one of them the task is read first; a task that is in "
        "the state asked for is left alone (`unchanged`, nothing is sent); otherwise its status is changed, which is all that Confluence lets a call "
        "change about a task, and it is read again, so that the answer says what Confluence holds now.",
        args=(
            Arg(("id",), "The task id: `conflu tasks` lists them.", required=True, metavar="ID"),
            Arg(("--complete",), "Mark the task as complete.", kind="flag"),
            Arg(("--reopen",), "Mark the task as incomplete again.", kind="flag"),
            Arg(("--dry-run",), "Show what would be sent and read the task. Sends nothing.", kind="flag"),
        ),
        examples=(
            Example("conflu task 7201"),
            Example("conflu task 7201 --complete --dry-run"),
            Example("conflu task 7201 --complete"),
            Example("conflu task 7201 --reopen --json"),
        ),
        notes=(
            "Without --complete or --reopen the command only reads; it is described as one that changes data because of those two flags, which is why --dry-run exists.",
            "If the change was made and the second read fails, the command still succeeds: `readBack` is false, `confirmed` is null, and `notes` and `message` say what happened.",
            "If the second read shows another state than the one that was asked for (the call was accepted and the task did not change), the command still ends with exit code 0, "
            "but the line does not say `Completed`: it says that Confluence still shows the old state, `confirmed` is false, and `message` and a warning say how to look.",
        ),
        writes=True,
        json_output=True,
        output="without --complete and --reopen: the task as `tasks` shows one (id, localId, status, pageId, blogPostId, spaceId, text, dueAt, createdAt, "
        "updatedAt, completedAt, assignedTo, createdBy, completedBy: the three people are always null here). With one of them: action (completed, "
        "reopened or unchanged), dryRun, taskId, statusFrom, statusTo, readBack (the task was read again after the change), notes[], payload "
        "(exactly what is sent; null when nothing is), task (as `tasks` shows it, as Confluence holds it after the change), confirmed (the task, as read "
        "after the change, is in the state that was asked for: false when it is not; null for a dry run, for unchanged and when the read failed) and "
        "message (null unless the change could not be confirmed).",
        destructive=False,
        idempotent=True,
        handler=run_task,
    ),
)
