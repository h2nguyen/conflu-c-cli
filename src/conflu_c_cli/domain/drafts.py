"""What to send to Confluence when a page is created or changed: the rules for titles, labels and bodies."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .errors import ValidationError

MAX_TITLE = 255
MAX_LABEL = 255
BODY_MODES = ("replace", "append", "prepend")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_BAD_LABEL = re.compile(r"[\s&?/:;'\"<>()\[\],@^#$%*+=\\{}|`~!]")


def parse_json_object(text: str, what: str = "JSON", *, hint: str = "") -> dict[str, Any]:
    try:
        value = json.loads(text)
    except ValueError as error:
        raise ValidationError(f"{what} is not valid JSON: {error}", hint=hint) from error
    if not isinstance(value, dict):
        raise ValidationError(f"{what} must be a JSON object")
    return value


def validate_title(title: str) -> str:
    text = (title or "").strip()
    if not text:
        raise ValidationError(
            "The page title is empty.",
            hint="Pass --title, or write `title:` in the front matter, or start the Markdown with a # heading.",
        )
    if _CONTROL.search(text):
        raise ValidationError("The page title contains a line break or another control character.")
    if len(text) > MAX_TITLE:
        raise ValidationError(f"The page title is longer than {MAX_TITLE} characters ({len(text)}).")
    return text


def normalize_labels(names: list[str]) -> list[str]:
    """Labels as Confluence stores them: lower case, each once; refuses what Confluence would refuse."""
    seen: dict[str, None] = {}
    for name in names:
        label = (name or "").strip().lower()
        if not label:
            continue
        if _BAD_LABEL.search(label) or len(label) > MAX_LABEL or not label.strip("."):
            raise ValidationError(
                f"Not a valid label: {name!r}",
                hint="A label has no spaces, is not only dots, and has none of & ? / : ; ' \" < > ( ) [ ] , @ ^ # $ % * + = \\ { } | ` ~ !",
            )
        seen.setdefault(label, None)
    return list(seen)


def combine_body(current: str, new: str, mode: str) -> str:
    """The body after a change: `new` replaces the current one, or is put behind or before it."""
    if mode == "replace":
        return new
    if mode not in BODY_MODES:
        raise ValidationError(f"Unknown body mode: {mode}", hint=f"Use one of: {', '.join(BODY_MODES)}.")
    if not current.strip():
        return new
    return f"{current}\n{new}" if mode == "append" else f"{new}\n{current}"


@dataclass
class PageDraft:
    """A page to create. The body is in storage format already. `space` and `parent` are None when none was named (the current space, the home page of
    the space); one that is empty was named and is a mistake, which `CreatePage` refuses."""

    space: str | None = None
    title: str = ""
    body: str = ""
    parent: str | None = None
    labels: list[str] = field(default_factory=list)


@dataclass
class PageChanges:
    """What to change on a page. `None` means "leave as it is". A body in storage format that came from
    Markdown (`from_markdown`) replaces the page only when nothing the Markdown cannot say would be lost."""

    title: str | None = None
    body: str | None = None
    body_mode: str = "replace"
    from_markdown: bool = False
    message: str = ""

    def is_empty(self) -> bool:
        return self.title is None and self.body is None
