"""The Markdown file format the CLI imports and exports: a front matter of `key: value` lines, then the page."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from .errors import ValidationError

_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_HEADING_START = re.compile(r"[ \t\n]*#([ \t]+)")
_ALIASES = {
    "id": "page_id",
    "confluence_id": "page_id",
    "confluence_page_id": "page_id",
    "space_key": "space",
    "parent_id": "parent",
    "label": "labels",
}


@dataclass(frozen=True)
class MarkdownPage:
    meta: dict[str, str]
    body: str

    @property
    def title(self) -> str:
        return self.meta.get("title", "")


def split_list(value: str) -> list[str]:
    seen: dict[str, None] = {}
    for item in (value or "").split(","):
        if item.strip():
            seen.setdefault(item.strip(), None)
    return list(seen)


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_markdown_page(text: str) -> MarkdownPage:
    """Front matter is a `---` block of `key: value` lines; the rest is the page. A file without it is all page."""
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if not text.startswith("---\n"):
        return MarkdownPage({}, text)
    end = text.find("\n---\n", 3)
    if end >= 0:
        head, body = text[4:end], text[end + 5 :]
    elif text.endswith("\n---"):
        head, body = text[4:-4], ""
    else:
        raise ValidationError("missing closing --- in front matter", hint="End the front matter with a line that holds only ---.")
    meta: dict[str, str] = {}
    for raw in head.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        key, separator, value = raw.partition(":")
        if not separator or not _KEY.match(key.strip()):
            raise ValidationError(
                f"invalid front matter line: {raw.strip()}",
                hint="Every line is `key: value`; write a list on one line, for example `labels: a, b`.",
            )
        name = key.strip().lower().replace("-", "_")
        meta[_ALIASES.get(name, name)] = _unquote(value.strip())
    return MarkdownPage(meta, body.lstrip("\n"))


def take_title_heading(body: str) -> tuple[str, str]:
    """`(title, rest)` when the body starts with a level-1 heading, which is then the page title; else `("", body)`. The line is cut by hand: a
    pattern for the closing hashes and the blanks around them backtracks over every way to share a long run of blanks."""
    start = _HEADING_START.match(body)
    if start is None:
        return "", body
    newline = body.find("\n", start.end())
    end = len(body) if newline < 0 else newline
    rest = body[start.end() : end]
    if not rest:
        if len(start.group(1)) < 2:
            return "", body  # a title needs a character: the blanks after the `#` are all that there is to give, and one is needed to separate it
        title = ""
    else:
        title = rest.rstrip(" \t")
        bare = title.rstrip("#")
        if bare != title and bare[-1:] in (" ", "\t"):
            title = bare.rstrip(" \t")
    return title.strip(), body[end + 1 if newline >= 0 else end :].lstrip("\n")


def _one_line(value: str) -> str:
    """The value on one line. A line break or another control character becomes a space; runs of spaces stay, because a
    title with two spaces in it must come back with two, or importing the file again would rename the page."""
    return re.sub(r"[\x00-\x1f\x7f\x85\u2028\u2029]+", " ", str(value)).strip()


def _quoted_if_needed(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        other = "'" if value[0] == '"' else '"'
        return other + value + other
    return value


def render_front_matter(meta: Mapping[str, str]) -> str:
    """The front matter block for an exported page; empty values are left out."""
    lines = ["---"]
    for key, value in meta.items():
        text = _one_line(value)
        if text:
            lines.append(f"{key}: {_quoted_if_needed(text)}")
    lines.append("---")
    return "\n".join(lines) + "\n"
