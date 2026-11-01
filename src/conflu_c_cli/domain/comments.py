"""Rules for comments: their ids, a pseudonym for an author, which comments are wanted, and what an edit sends, refuses and changes."""
from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from .durations import parse_duration
from .errors import ConflictError, UsageError, ValidationError
from .model import Comment
from .payloads import storage_body
from .privacy import EMAIL_MARKER, LINK_MARKER, normalize_newlines
from .timeutil import parse_timestamp

# What Confluence calls the states of an inline comment: `reopened` is a comment that was resolved and then opened again, `dangling` one whose
# text on the page is gone.
RESOLUTIONS = ("open", "resolved", "reopened", "dangling")
_COMMENT_ID = re.compile(r"[0-9]{1,19}")  # ASCII digits only: `\d` takes the digits of other scripts too
_AGO = re.compile(r"[0-9]+(?:\.[0-9]+)?[smhdw]", re.IGNORECASE)
_UNKNOWN = datetime.min.replace(tzinfo=timezone.utc)  # the moment of a comment whose time cannot be read: older than any


@dataclass(frozen=True)
class CommentRecord:
    """A comment as it is read by its id: the comment, and the page it is on (empty for a comment on a blog post or on an attachment)."""

    comment: Comment
    page_id: str = ""


def _shown(text: str, width: int = 60) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def parse_comment_id(text: str, option: str = "") -> str:
    """The id of a comment: digits only. `option` names the option that carried it (`--get`): an empty value, which a shell makes of an empty variable, is
    no id and never "not given", and the message says which option it was."""
    value = (text or "").strip()
    if not _COMMENT_ID.fullmatch(value):
        hint = "A comment id is a number; `conflu comments PAGE --json` lists them."
        if option and not value:
            raise ValidationError(f"{option} is empty: it needs the id of a comment.", hint=f"{hint} Leave {option} out if you mean none.")
        where = f" for {option}" if option else ""
        raise ValidationError(f"Invalid comment id{where}: {_shown(value) or '<missing>'}", hint=hint)
    return value


def author_ref(secret: str, base_url: str, account_id: str) -> str | None:
    """A stable pseudonym for the author of a comment, so that the comments of one person can be told from those of another while names are hidden.

    The start of an HMAC-SHA-256 over the address of the site and the account id, keyed with `secret` (the API token, which is never printed): the
    same author gives the same text in every command that has the same secret, and nobody without the secret can compute the text for an account id
    that they know, or find the account behind a text. Without a secret, or without an account, there is none: an unkeyed hash could be recomputed
    from an id."""
    key = (secret or "").encode("utf-8")
    account = (account_id or "").strip()
    if not key or not account:
        return None
    site = (base_url or "").strip().rstrip("/").casefold()
    message = f"conflu-c-cli authorRef 1\n{site}\n{account}".encode("utf-8")
    return "a-" + hmac.new(key, message, hashlib.sha256).hexdigest()[:8]


def parse_since(text: str, now: datetime) -> datetime:
    """The moment that `--since` names: a time ago (`2d`, `12h`, `1w`), a date (`2026-10-15`) or an ISO 8601 time. A date or a time without an
    offset counts as UTC."""
    value = (text or "").strip()
    try:
        if _AGO.fullmatch(value):
            return now - timedelta(seconds=parse_duration(value))
        return parse_timestamp(value)
    except (ValidationError, OverflowError, ValueError) as error:
        raise UsageError(
            f"Not a time for --since: {_shown(value) or '<missing>'}",
            hint="Write a time ago (2d, 12h, 1w), a date (2026-10-15) or an ISO 8601 time (2026-10-15T08:00:00Z).",
        ) from error


def _moment(comment: Comment) -> datetime | None:
    try:
        return parse_timestamp(comment.updated)
    except ValidationError:
        return None


def select_comments(comments: Sequence[Comment], *, since: datetime | None = None, last: int = 0) -> list[Comment]:
    """The comments saved at or after `since` and, of those, the `last` newest (all when `last` is 0), in the order that they were given.

    The time of a comment is when its current version was saved: when it was written, unless somebody edited it."""
    chosen = list(enumerate(comments))
    if since is not None:
        chosen = [(index, comment) for index, comment in chosen if (_moment(comment) or _UNKNOWN) >= since]
    if last > 0:
        newest = sorted(chosen, key=lambda item: (_moment(item[1]) or _UNKNOWN, item[0]))[-last:]
        chosen = sorted(newest, key=lambda item: item[0])
    return [comment for _, comment in chosen]


def same_text(current: str, new: str) -> bool:
    """Whether two bodies in storage format are the same, apart from the line ends and the blanks around them."""
    return normalize_newlines(current).strip() == normalize_newlines(new).strip()


def markers_added(current: str, new: str) -> list[str]:
    """The stand-ins for personal data (`[email]`, `[personal link]`) that the new body holds and the current one does not. They come from a
    reading that hid a real address or profile link, and sending them back would overwrite the real one."""
    return [mark for mark in (EMAIL_MARKER, LINK_MARKER) if mark in new and mark not in current]


def describe_change(current: str, new: str) -> str:
    """The unified diff of two texts, or an empty text when they are the same. The texts are what a person reads (Markdown, people hidden)."""
    before, after = normalize_newlines(current).strip(), normalize_newlines(new).strip()
    if before == after:
        return ""
    import difflib  # a module of the standard library that only a change needs; it costs about 14 ms at start-up

    return "\n".join(difflib.unified_diff(before.splitlines(), after.splitlines(), "current", "new", lineterm="", n=2))


def ensure_comment_unchanged_since(page_id: str, comment: Comment, since: datetime) -> None:
    """Raise a conflict when the comment was saved after `since`. Confluence has no precondition on a time, so this is a check just before the
    write; the version number that the write carries is the atomic guard."""
    changed_at = _moment(comment)
    if changed_at is None:
        raise ValidationError(
            f"Confluence did not say when comment {comment.id} was last saved, so --if-unchanged-since cannot be checked.",
            hint=f"Read it again with `conflu comment {page_id} --get {comment.id}`, or edit it without the guard: the version number of the edit is still checked.",
        )
    if changed_at > since:
        raise ConflictError(
            f"Comment {comment.id} of page {page_id} changed in Confluence at {changed_at.isoformat()}, after {since.isoformat()}.",
            hint=f"Read it again with `conflu comment {page_id} --get {comment.id}` and review the current text before you change it.",
            details={"pageId": page_id, "commentId": comment.id, "updated": changed_at.isoformat(), "since": since.isoformat()},
        )


def check_expected_version(expected: int | None) -> None:
    """`--if-version` names a version that the comment has had: the first one is 1."""
    if expected is not None and expected < 1:
        raise UsageError("--if-version must be at least 1.", hint="A comment starts at version 1; `conflu comment PAGE --get ID` shows the version it is at.")


def ensure_comment_version(page_id: str, comment: Comment, expected: int) -> None:
    """Raise a conflict when the comment is not at the version that the caller read."""
    if comment.version != expected:
        raise ConflictError(
            f"Comment {comment.id} of page {page_id} is at version {comment.version}, not {expected}.",
            hint=f"Read it again with `conflu comment {page_id} --get {comment.id}` and review the current text before you change it.",
            details={"pageId": page_id, "commentId": comment.id, "version": comment.version, "expected": expected},
        )


def edit_payload(version_number: int, body: str, *, resolved: bool | None = None) -> dict[str, Any]:
    """What a change of a comment sends: the number of the new version (the current one plus one), the body in storage format and, for an inline
    comment, whether it is resolved. The state is always sent, so that a change of the text keeps it as it is."""
    payload: dict[str, Any] = {"version": {"number": version_number}, "body": storage_body(body)}
    if resolved is not None:
        payload["resolved"] = resolved
    return payload
