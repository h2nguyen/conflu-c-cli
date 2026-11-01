"""Earlier versions of a page: which version a person means, the difference between two of them, and the request that restores one."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import UsageError

CURRENT = "current"
DEFAULT_CONTEXT = 3
MAX_CONTEXT = 1000


def check_version_number(number: int, option: str = "--version") -> int:
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise UsageError(f"{option} must be a version number: 1 or more.", hint="`conflu versions PAGE` lists the versions of a page.")
    return number


def parse_target(value: str | None) -> int | None:
    """The version that `--to` names: None for `current` (and when it is not given), else a version number. An empty value is a mistake, not "not given"."""
    text = (CURRENT if value is None else value).strip().lower()
    if text == CURRENT:
        return None
    if not text.isascii() or not text.isdigit() or len(text) > 9:  # a version has at most nine digits; `int()` refuses thousands
        raise UsageError(f"--to must be a version number or `current`, not {value!r}.", hint="`conflu versions PAGE` lists the versions of a page.")
    return check_version_number(int(text), "--to")


def check_context(context: int) -> int:
    if not 0 <= context <= MAX_CONTEXT:
        raise UsageError(f"--context must be between 0 and {MAX_CONTEXT}.")
    return context


def restore_payload(version_number: int, message: str, restore_title: bool = False) -> dict[str, Any]:
    """What `POST /rest/api/content/{id}/version` takes. It names the version and holds no content: Confluence makes the new version itself."""
    return {"operationKey": "restore", "params": {"versionNumber": version_number, "message": message, "restoreTitle": restore_title}}


@dataclass(frozen=True)
class Difference:
    """What differs between two texts, as a unified diff and as the number of lines on each side."""

    text: str  # the unified diff; empty when nothing differs
    added: int
    removed: int
    truncated: bool = False
    total_chars: int = 0  # the size of the whole diff, when it was cut

    @property
    def identical(self) -> bool:
        return not (self.added or self.removed)


def cut_lines(text: str, max_chars: int) -> tuple[str, bool]:
    """The text cut after the last whole line that fits into `max_chars`; a first line that is longer is cut in the line."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    kept: list[str] = []
    size = 0
    for line in text.split("\n"):
        if kept and size + len(line) > max_chars:
            break
        kept.append(line)
        size += len(line) + 1
    return "\n".join(kept)[:max_chars], True


def compare(
    old: str,
    new: str,
    *,
    old_label: str = "old",
    new_label: str = "new",
    old_date: str = "",
    new_date: str = "",
    context: int = DEFAULT_CONTEXT,
    max_chars: int = 0,
) -> Difference:
    """The unified diff from `old` to `new`, `context` lines around each change, cut to `max_chars` when that is given."""
    import difflib  # a module of the standard library that only a difference needs; it costs about 14 ms at start-up

    lines = list(
        difflib.unified_diff(
            old.splitlines(), new.splitlines(), fromfile=old_label, tofile=new_label, fromfiledate=old_date, tofiledate=new_date, n=context, lineterm=""
        )
    )
    body = lines[2:]  # the first two lines name the two sides
    added = sum(1 for line in body if line.startswith("+"))
    removed = sum(1 for line in body if line.startswith("-"))
    text = "\n".join(lines)
    shown, cut = cut_lines(text, max_chars)
    return Difference(shown, added, removed, cut, len(text) if cut else 0)
