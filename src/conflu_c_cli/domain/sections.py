"""The parts of a Markdown page: an outline of its headings, one section, and a cut that does not split a paragraph or a code block.

A page can be long and an answer short. These functions let a reader (a person, a program, an agent) look at the outline first
and then read only the part it needs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import ValidationError

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_FENCE_CLOSE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
_IMAGE_OR_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")
_STRONG = re.compile(r"(\*\*|__|~~)(.+?)\1")
_EMPHASIS = re.compile(r"(?<!\w)([*_])(\S(?:.*?\S)?)\1(?!\w)")


@dataclass(frozen=True)
class Heading:
    index: int  # 1-based position in the outline
    level: int  # 1 to 6
    title: str  # as plain text
    line: int  # 0-based line of the heading
    end: int  # 0-based line after the end of its section (the next heading of the same or a higher level)
    chars: int  # size of the section's text, with its sub-sections


def _fence_end(line: str, opened: tuple[str, int]) -> bool:
    """A line that closes the fence: up to three spaces, then only the fence's character, at least as often as it opened."""
    closing = _FENCE_CLOSE.match(line)
    return bool(closing) and closing.group(1)[0] == opened[0] and len(closing.group(1)) >= opened[1]


def plain_title(raw: str) -> str:
    """The text of a heading without its Markdown: links and images keep their text, escapes and emphasis go."""
    text = _IMAGE_OR_LINK.sub(r"\1", raw)
    text = _ESCAPE.sub(r"\1", text)
    text = text.replace("`", "")
    text = _STRONG.sub(r"\2", text)
    text = _EMPHASIS.sub(r"\2", text)
    return " ".join(text.split())


def outline(markdown: str) -> list[Heading]:
    """The headings of a Markdown text (the ATX kind, `# Title`, which is what the converter writes), outside code blocks,
    with the size of each section."""
    lines = (markdown or "").split("\n")
    found: list[tuple[int, int, str]] = []
    opened: tuple[str, int] | None = None
    for number, line in enumerate(lines):
        if opened is not None:
            if _fence_end(line, opened):
                opened = None
            continue
        fence = _FENCE.match(line)
        if fence:
            opened = (fence.group(1)[0], len(fence.group(1)))
            continue
        heading = _HEADING.match(line)
        if heading:
            found.append((number, len(heading.group(1)), plain_title(heading.group(2))))
    result = []
    for position, (number, level, title) in enumerate(found):
        end = len(lines)
        for later_number, later_level, _ in found[position + 1 :]:
            if later_level <= level:
                end = later_number
                break
        chars = len("\n".join(lines[number:end]).rstrip())
        result.append(Heading(position + 1, level, title, number, end, chars))
    return result


def _norm(text: str) -> str:
    return " ".join(plain_title(text).casefold().split()).rstrip(":").strip()


def extract_section(markdown: str, selector: str) -> tuple[str, Heading]:
    """The section with this heading, from the heading to the next one of the same or a higher level.

    `selector` is the text of the heading (any case; a part of it is enough when it is unique) or its number in the outline."""
    headings = outline(markdown)
    wanted = _norm(selector)
    if not headings:
        raise ValidationError("The page has no headings, so it has no sections.", hint="Read it whole, or cut it with --max-chars.")
    if not wanted:
        raise ValidationError("--section needs the text of a heading or its number.", hint="`--outline` lists the headings.")
    chosen: list[Heading]
    if wanted.isdigit() and 1 <= int(wanted) <= len(headings) and not any(_norm(h.title) == wanted for h in headings):
        chosen = [headings[int(wanted) - 1]]
    else:
        chosen = [h for h in headings if _norm(h.title) == wanted] or [h for h in headings if wanted in _norm(h.title)]
    if not chosen:
        raise ValidationError(
            f"The page has no heading like {selector!r}.",
            hint="Its headings: " + " | ".join(f"{h.index}. {h.title}" for h in headings[:30]) + ("" if len(headings) <= 30 else " ..."),
        )
    if len(chosen) > 1:
        raise ValidationError(
            f"{len(chosen)} headings match {selector!r}.",
            hint="Say which one by its number: " + " | ".join(f"{h.index}. {h.title}" for h in chosen[:12]) + ".",
        )
    heading = chosen[0]
    lines = markdown.split("\n")
    return "\n".join(lines[heading.line : heading.end]).rstrip() + "\n", heading


def _without_trailing_headings(lines: list[str]) -> list[str]:
    """The lines without a heading (and the blank lines) at the end: a cut must not leave a title with nothing below it."""
    kept = list(lines)
    while kept and (not kept[-1].strip() or _HEADING.match(kept[-1])):
        kept.pop()
    return kept


def truncate(markdown: str, max_chars: int) -> tuple[str, bool]:
    """The text cut to at most `max_chars` (not counting the line break at its end), at the end of a paragraph if it can be, and not
    inside a code block or below a heading that has nothing under it. The second value says whether something was cut off.

    The one exception is a first paragraph or code block that is longer than the limit itself: it is cut at a word, or in the line.
    Headings are the ATX kind (`#`), which is the only kind that `conflu page` writes."""
    if max_chars <= 0 or len(markdown) <= max_chars:
        return markdown, False
    lines = markdown.split("\n")
    opened: tuple[str, int] | None = None
    size = 0
    best_paragraph = best_line = 0
    for number, line in enumerate(lines):
        if opened is not None:
            if _fence_end(line, opened):
                opened = None
        else:
            fence = _FENCE.match(line)
            if fence:
                opened = (fence.group(1)[0], len(fence.group(1)))
        size += len(line) + 1
        if size - 1 > max_chars:
            break
        if opened is None:
            best_line = number + 1
            if not line.strip():
                best_paragraph = number + 1
    cut = best_paragraph or best_line
    kept = _without_trailing_headings(lines[:cut]) if cut else []
    if kept:
        return "\n".join(kept).rstrip() + "\n", True
    hard = markdown[:max_chars]
    space = hard.rfind(" ")
    return (hard[:space] if space > max_chars // 2 else hard).rstrip() + "\n", True
