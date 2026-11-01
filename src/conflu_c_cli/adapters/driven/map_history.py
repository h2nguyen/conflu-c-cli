"""What Confluence's JSON means for earlier versions of a page, the difference between two of them, and restoring one: the answers as domain objects."""
from __future__ import annotations

from typing import Any

from ...domain.model import Page
from . import confluence_mapper as mapper


def page_version_from(data: dict[str, Any], fallback_base: str = "") -> Page:
    """An earlier version of a page: the answer has the shape of the page's own, with the title, the body and the version as they were then."""
    return mapper.page_from(data, fallback_base)


def restored_number(data: Any) -> int:
    """The number of the version that a restore made, as its answer says (the answer is a version of the older API); 0 when it does not say."""
    number = data.get("number") if isinstance(data, dict) else None
    return number if isinstance(number, int) and not isinstance(number, bool) and number > 0 else 0
