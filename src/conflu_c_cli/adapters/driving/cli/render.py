"""Printing: tables, key/value blocks and JSON (stable camelCase keys for scripts and agents)."""
from __future__ import annotations

import json
import re
from dataclasses import fields, is_dataclass
from datetime import datetime
from typing import Any, Iterable, Sequence


def camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part.capitalize() for part in tail)


def to_jsonable(value: Any) -> Any:
    """Dataclasses become dicts with camelCase keys; fields marked `json: False` are left out."""
    if is_dataclass(value) and not isinstance(value, type):
        return {
            camel(item.name): to_jsonable(getattr(value, item.name))
            for item in fields(value)
            if item.metadata.get("json", True)
        }
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


_UNESCAPED_CONTROL = re.compile(r"[\x7f-\x9f]")


def dumps_json(value: Any, *, pretty: bool) -> str:
    """JSON with the characters of the text kept as they are, except DEL and the C1 controls, which JSON does not
    escape but a terminal obeys: they are written as \\u escapes, so nothing is lost and nothing is executed."""
    if pretty:
        text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    else:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    return _UNESCAPED_CONTROL.sub(lambda match: f"\\u{ord(match.group()):04x}", text)


_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def printable(text: str) -> str:
    """Text for a terminal. What a title, a page or a comment holds must not be able to move the cursor, clear the
    screen or retitle the window, which is what control characters such as ESC do; tabs and line breaks stay."""
    return _CONTROL.sub("", text.replace("\r\n", "\n"))


def one_line(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def table(headers: Sequence[str], rows: Iterable[Sequence[Any]], *, indent: str = "") -> str:
    """Left-aligned columns separated by two spaces; the last column is not padded."""
    body = [[one_line(cell) for cell in row] for row in rows]
    widths = [max([len(headers[i])] + [len(row[i]) for row in body]) for i in range(len(headers))]

    def line(cells: Sequence[str]) -> str:
        padded = [cell.ljust(widths[i]) for i, cell in enumerate(cells[:-1])] + [cells[-1]]
        return (indent + "  ".join(padded)).rstrip()

    return "\n".join([line(list(headers)), *(line(row) for row in body)])


def key_values(pairs: Iterable[tuple[str, Any]], *, indent: str = "") -> str:
    """`Label:  value` lines with aligned values; empty values are skipped."""
    shown = [(label, str(value)) for label, value in pairs if value not in ("", None)]
    if not shown:
        return ""
    width = max(len(label) for label, _ in shown) + 2
    return "\n".join(f"{indent}{(label + ':').ljust(width)}{value}" for label, value in shown)


def number(value: float) -> str:
    return f"{value:g}"
