"""The templates of a space, and the variables that a template declares.

Confluence has page templates (global ones, and those of a space) and the templates that blueprints provide. Only the older REST API (v1)
knows them. A template is read, never applied: the API has no call that makes a page from one.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

from .errors import ValidationError
from .privacy import redact_text

_TEMPLATE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_LISTS = ("page", "blueprint")  # the paths of the two lists, below the path that a template has: no template is called that

# A variable is `<at:var at:name="title" />`. The body of a template is written by whoever may edit templates, so the scan has limits that keep
# a body made of broken tags from costing more than a moment: a tag is looked at up to MAX_TAG characters, and a body for up to MAX_TAGS tags.
MAX_TAG = 1000
MAX_TAGS = 2000
MAX_NAMES = 200
# What the scan stops at: a variable, or the start of a part that is text and no markup: a comment, and a CDATA section (the code of a code macro stands in one).
_SCAN = re.compile(r"<at:var(?=[\s/>])|<!--|<!\[CDATA\[")
_ENDS = {"<!--": "-->", "<![CDATA[": "]]>"}
# the rest of the tag, read with its quotes in mind so that a `>` inside an attribute does not end it
_TAG_REST = re.compile(r"((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>")


@dataclass(frozen=True)
class TemplateInfo:
    id: str
    name: str = ""
    type: str = ""  # page | blueprint
    description: str = ""
    space_key: str = ""  # empty for a global template
    labels: tuple[str, ...] = ()
    blueprint: str = ""  # the blueprint that the template references, as Confluence names it (`referencingBlueprint`)


@dataclass(frozen=True)
class Template(TemplateInfo):
    body: str = ""  # storage format


@dataclass
class TemplatePage:
    """One piece of a list that is read with `start` and `limit`: what came, and where the next piece starts (None on the last one)."""

    templates: list[TemplateInfo] = field(default_factory=list)
    start: int = 0
    next_start: int | None = None


def parse_template_id(text: str) -> str:
    value = (text or "").strip()
    if not _TEMPLATE_ID.fullmatch(value) or value in _LISTS:
        shown = value if value and value.isprintable() and len(value) <= 60 else "<missing>" if not value else "<not a template id>"
        raise ValidationError(
            f"Invalid template id: {shown}",
            hint="`conflu templates` lists the page templates of a space with their ids, and `conflu templates --blueprints` those of the blueprints.",
        )
    return value


@dataclass(frozen=True)
class Variables:
    names: tuple[str, ...] = ()
    complete: bool = True  # False when the scan stopped at one of its limits, or met a tag that it could not read to its end


def variables_of(storage: str) -> Variables:
    """The names of the variables that a template declares (`<at:var at:name="title" />` in its storage format), each once, in the order in which
    they first appear. The Markdown copy of a body cannot show them. A comment and a CDATA section are text, so what looks like a variable in them (the code
    of a code macro, a note that was commented out) is none; one that never ends holds the rest of the body, and the list may be incomplete."""
    text = storage or ""
    found: dict[str, None] = {}
    position, looked, complete = 0, 0, True
    while True:
        opener = _SCAN.search(text, position)
        if opener is None:
            break
        ending = _ENDS.get(opener.group())
        if ending:
            end = text.find(ending, opener.end())
            if end < 0:
                complete = False
                break
            position = end + len(ending)
            continue
        looked += 1
        if looked > MAX_TAGS:
            complete = False
            break
        start = opener.end()
        tag = _TAG_REST.match(text, start, min(len(text), start + MAX_TAG))
        if tag is None:
            complete, position = False, start
            continue
        position = tag.end()
        name = _name_of(tag.group(1))
        if not name or name in found:
            continue
        if len(found) >= MAX_NAMES:
            complete = False
            break
        found[name] = None
    return Variables(tuple(found), complete)


_TOKEN = re.compile(r"\"([^\"]*)\"|'([^']*)'|([^\s\"'=/>]+)|(=)")


def _name_of(attributes: str) -> str:
    """The value of the attribute `at:name` among the attributes of a tag, read token by token (a quoted value is one token, so an attribute
    that merely mentions `at:name` in its value is not taken for it)."""
    word, equals = "", False
    for token in _TOKEN.finditer(attributes):
        double, single, bare, sign = token.groups()
        if bare is not None:
            word, equals = bare, False
        elif sign is not None:
            equals = bool(word)
        else:
            if equals and word == "at:name":
                return redact_text(html.unescape(double if double is not None else single)).strip()
            word, equals = "", False
    return ""
