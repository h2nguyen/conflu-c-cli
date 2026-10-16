"""Helpers shared by the command modules."""
from __future__ import annotations

import copy
import json
from typing import TYPE_CHECKING, Any, Sequence

from .....domain.errors import UsageError
from .....domain.model import User
from ..runtime import Context

if TYPE_CHECKING:
    from .....application.comments import CommentView
    from .....application.rendering import Body


def text_option(ctx: Context, text: str | None, file: str | None, what: str) -> str | None:
    """Text given inline or from a file (`-` is standard input). None when neither was given."""
    if text is not None and file is not None:
        raise UsageError(f"Use either the {what} text or its file, not both.")
    if file is not None:
        return ctx.read_input(file)
    return text


POWERSHELL_JSON_NOTE = (
    "In Windows PowerShell 5.1 pass the body with --data-file: PowerShell removes double quotes inside an argument."
)
POWERSHELL_TEXT_NOTE = (
    "Text with quotes or $ is easiest in a file: --file notes.md. In Windows PowerShell 5.1 double quotes inside an "
    "argument are removed."
)

LIMIT_HELP = "Items per page (1 to 250)."


def pretty(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def shortened(payload: Any, limit: int = 1500) -> Any:
    """A payload for a person to read: a page body longer than `limit` characters is cut. The JSON of a dry run
    is never cut; this is only for the text."""
    clone = copy.deepcopy(payload)
    body = clone.get("body") if isinstance(clone, dict) else None
    if isinstance(body, dict) and isinstance(body.get("value"), str) and len(body["value"]) > limit:
        body["value"] = f"{body['value'][:limit]}... ({len(body['value']) - limit} more characters)"
    return clone


def user_json(user: User | None) -> dict[str, str] | None:
    return None if user is None else {"accountId": user.account_id, "displayName": user.display_name, "email": user.email}


def check_limit(limit: int) -> None:
    if not 1 <= limit <= 250:
        raise UsageError("--limit must be between 1 and 250.")


def user_name(user: User | None) -> str:
    return "" if user is None else user.display_name or user.account_id


def body_json(body: Body | None) -> dict[str, Any] | None:
    return None if body is None else {"format": body.format, "value": body.text, "dropped": list(body.dropped)}


def page_body_json(body: Body | None) -> dict[str, Any] | None:
    """The body of a page: `section` names the part when one section was asked for, `truncated` says that the text was cut to
    --max-chars (then `totalChars` is the size of the whole text)."""
    if body is None:
        return None
    return {
        "format": body.format,
        "value": body.text,
        "dropped": list(body.dropped),
        "section": body.section or None,
        "truncated": body.truncated,
        "totalChars": body.total_chars or None,
    }


def comment_json(view: CommentView) -> dict[str, Any]:
    comment = view.comment
    return {
        "id": comment.id,
        "kind": comment.kind,
        "updated": comment.updated,
        "parentId": comment.parent_id or None,
        "resolution": comment.resolution or None,
        "author": user_json(comment.author),
        "body": body_json(view.body),
    }


def comments_text(views: Sequence[CommentView], *, users_shown: bool) -> str:
    """Each comment under a line with its id and date; a reply is indented below the comment it answers."""
    lines: list[str] = []
    for view in views:
        comment = view.comment
        indent = "    " if comment.parent_id else ""
        who = f"  {user_name(comment.author)}" if users_shown and comment.author else ""
        reply = f" (reply to #{comment.parent_id})" if comment.parent_id else ""
        state = f" [{comment.resolution}]" if comment.resolution else ""
        lines.append(f"{indent}--- #{comment.id} {comment.kind}{state} {comment.updated}{reply}{who}")
        lines.extend(f"{indent}{line}".rstrip() for line in view.body.text.strip().splitlines())
    return "\n".join(lines)
