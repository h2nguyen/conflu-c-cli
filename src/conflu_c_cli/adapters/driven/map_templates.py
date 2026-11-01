"""What Confluence's JSON means for the templates of a space: the answers as domain objects."""
from __future__ import annotations

import urllib.parse
from typing import Any

from ...domain.errors import UnavailableError
from ...domain.templates import Template, TemplateInfo, TemplatePage
from .confluence_mapper import results_of


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _fields(data: Any) -> dict[str, Any]:
    item = _object(data)
    labels = item.get("labels")
    names = [_text(_object(label).get("name") or _object(label).get("label")) for label in labels] if isinstance(labels, list) else []
    return dict(
        id=_text(item.get("templateId")),
        name=_text(item.get("name")),
        type=_text(item.get("templateType")),
        description=_text(item.get("description")),
        space_key=_text(_object(item.get("space")).get("key")),
        labels=tuple(name for name in names if name),
        blueprint=_text(item.get("referencingBlueprint")),
    )


def info_from(data: Any) -> TemplateInfo:
    """A template as the lists of the older API describe it: without its body."""
    return TemplateInfo(**_fields(data))


def template_from(data: Any) -> Template:
    """A template with its body in storage format, as `GET /template/{id}` answers with `expand=body.storage`."""
    storage = _object(_object(_object(data).get("body")).get("storage"))
    return Template(**_fields(data), body=_text(storage.get("value")))


def page_from(data: Any, start: int) -> TemplatePage:
    """A piece of a list of templates, and where the next one starts: the `start` of `_links.next`, which is how the older API says that there is more."""
    answer = _object(data)
    templates = [info_from(item) for item in results_of(answer)]
    begun = answer.get("start") if isinstance(answer.get("start"), int) and not isinstance(answer.get("start"), bool) else start
    link = _object(answer.get("_links")).get("next")
    following: int | None = None
    if isinstance(link, str) and link:
        try:
            wanted = urllib.parse.parse_qs(urllib.parse.urlsplit(link).query).get("start") or [""]
        except ValueError:  # a list that cannot go on must not be taken for a list that ended
            raise UnavailableError(
                "Confluence answered with a link to the next piece of the list that cannot be read.",
                hint="Try again. If it stays, something between you and Confluence is changing its answers.",
            ) from None
        digits = wanted[0].isascii() and wanted[0].isdigit() and len(wanted[0]) <= 18  # `int` of 5000 digits is a ValueError
        following = int(wanted[0]) if digits else begun + len(templates)
        if following <= begun:
            following = None  # a link that does not go on would be read for ever
    return TemplatePage(templates, begun, following)
