"""Blog posts as the CLI writes them: the request bodies, the title rule and the guards of a change.

A blog post is not a page. Its title need not be unique, it has no parent, and the REST API v2 has no call that changes only the title,
so every change of one sends the body as well.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .drafts import MAX_TITLE
from .errors import ConflictError, ValidationError
from .payloads import storage_body, update_page_payload
from .timeutil import parse_guard_time, parse_timestamp

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass
class BlogpostDraft:
    """A blog post to create. The body is in storage format already. `space` is None when none was named: an empty name is a mistake, not "none"."""

    space: str | None = None
    title: str = ""
    body: str = ""
    labels: list[str] = field(default_factory=list)


def validate_blogpost_title(title: str) -> str:
    text = (title or "").strip()
    if not text:
        raise ValidationError("The blog post title is empty.", hint="Pass --title.")
    if _CONTROL.search(text):
        raise ValidationError("The blog post title contains a line break or another control character.")
    if len(text) > MAX_TITLE:
        raise ValidationError(f"The blog post title is longer than {MAX_TITLE} characters ({len(text)}).")
    return text


def create_blogpost_payload(space_id: str, title: str, body: str) -> dict[str, Any]:
    return {"spaceId": space_id, "status": "current", "title": title, "body": storage_body(body)}


def update_blogpost_payload(blogpost_id: str, title: str, body: str, version_number: int, message: str = "", status: str = "current") -> dict[str, Any]:
    """`PUT /blogposts/{id}` takes what `PUT /pages/{id}` takes: the id, the status, the title, the whole body and the version it becomes."""
    return update_page_payload(blogpost_id, title, body, version_number, message, status)


def ensure_blogpost_version(blogpost_id: str, current: int, expected: int) -> None:
    """Raise a conflict when the blog post is not at the version the caller read."""
    if current != expected:
        raise ConflictError(
            f"Blog post {blogpost_id} is at version {current}, not {expected}.",
            hint="Read it again and review the current state before writing.",
            details={"blogpostId": blogpost_id, "version": current, "expected": expected},
        )


def ensure_blogpost_unchanged_since(blogpost_id: str, updated: str, since: str) -> None:
    """Raise a conflict when the blog post was changed after `since`."""
    changed_at = parse_timestamp(updated)
    limit = parse_guard_time(since)
    if changed_at > limit:
        raise ConflictError(
            f"Blog post {blogpost_id} changed in Confluence at {changed_at.isoformat()}, after {limit.isoformat()}.",
            hint="Read it again and review the current state before writing.",
            details={"blogpostId": blogpost_id, "updated": changed_at.isoformat(), "since": limit.isoformat()},
        )
