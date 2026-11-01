"""The tasks that are written into pages and blog posts, and what a person types to find them.

A task is one checkbox of a page. Confluence lists them site wide, and the only thing a call can change about one is its status.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from .errors import UsageError, ValidationError
from .model import User

INCOMPLETE, COMPLETE = "incomplete", "complete"
STATUSES = (INCOMPLETE, COMPLETE)
MAX_TASK_ID = 2**63 - 1  # a task id is a 64 bit integer in the API
MAX_TASK_IDS = 250  # how many ids the filter `task-id` of `GET /tasks` takes, by its document

_TASK_ID = re.compile(r"[0-9]{1,19}")
_DAY = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MILLISECOND = timedelta(milliseconds=1)
FIRST_YEAR = 1970  # before it a day is a negative number of milliseconds, which no list of tasks has a use for


@dataclass(frozen=True)
class Task:
    id: str
    status: str = ""  # complete | incomplete
    space_id: str = ""
    page_id: str = ""  # the page that holds the task; empty for a task in a blog post
    blogpost_id: str = ""  # the blog post that holds it, else empty
    local_id: str = ""  # its number inside that page or blog post
    body: str = ""  # the text of the task, in storage format
    created_by: User | None = None
    assigned_to: User | None = None
    completed_by: User | None = None
    created: str = ""
    updated: str = ""
    due: str = ""
    completed: str = ""


def _task_number(text: str) -> str | None:
    """The task id that `text` is, as the API writes it (a positive whole number without leading zeros), or None."""
    value = (text or "").strip()
    if not _TASK_ID.fullmatch(value) or not 0 < int(value) <= MAX_TASK_ID:
        return None
    return str(int(value))


def parse_task_id(text: str) -> str:
    number = _task_number(text)
    if number is None:
        raise ValidationError(f"Invalid task id: {(text or '').strip()[:40] or '<missing>'}", hint="A task id is a positive number such as 123456; `conflu tasks` lists them.")
    return number


def parse_task_ids(values: Sequence[str]) -> list[str]:
    """The ids that `--task` was given, as the list of tasks takes them: each a task id, once, in the order they came, and no more than `MAX_TASK_IDS`."""
    found: dict[str, None] = {}
    for text in [values] if isinstance(values, str) else values or ():  # a text is one id, not a row of characters
        number = _task_number(text)
        if number is None:
            raise UsageError(
                f"--task needs a task id, a positive whole number such as 7201, not '{(text or '').strip()[:40]}'.",
                hint="`conflu tasks` lists the ids. Give --task once for each task.",
            )
        found[number] = None
        if len(found) > MAX_TASK_IDS:
            raise UsageError(f"--task takes at most {MAX_TASK_IDS} ids at once.", hint="Ask for fewer, or narrow the list with --page, --space or --status.")
    return list(found)


def day_start(text: str, flag: str) -> int:
    """The start of a day (00:00 UTC) as epoch milliseconds, which is how the list of tasks takes a date. `text` is `YYYY-MM-DD`."""
    value = (text or "").strip()
    found = _DAY.fullmatch(value)
    try:
        if found is None or int(found.group(1)) < FIRST_YEAR:
            raise ValueError(value)
        moment = datetime(int(found.group(1)), int(found.group(2)), int(found.group(3)), tzinfo=timezone.utc)
    except ValueError:
        raise UsageError(
            f"{flag} needs a day written as YYYY-MM-DD, not '{value}'.",
            hint=f"For example {flag} 2026-10-31. A day counts from 00:00 UTC; a year before {FIRST_YEAR} is not accepted.",
        ) from None
    return (moment - _EPOCH) // _MILLISECOND


def due_range(after: str = "", before: str = "") -> tuple[int | None, int | None]:
    """`(from, to)` in epoch milliseconds for `--due-after` and `--due-before`, both ends included as the list of tasks includes them."""
    start = day_start(after, "--due-after") if after else None
    end = day_start(before, "--due-before") if before else None
    if start is not None and end is not None and start > end:
        raise UsageError(f"--due-after {after} is later than --due-before {before}: no task can be due in between.", hint="Swap the two days, or leave one out.")
    return start, end


def status_payload(status: str) -> dict[str, Any]:
    """What `PUT /tasks/{id}` takes: the call changes the status and nothing else, so nothing else is sent (and no person is named)."""
    if status not in STATUSES:
        raise UsageError(f"Unknown task status: {status}", hint=f"Use one of: {', '.join(STATUSES)}.")
    return {"status": status}
