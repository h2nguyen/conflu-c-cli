"""What Confluence's JSON means for blog posts: the answers as domain objects."""
from __future__ import annotations

from typing import Any

from ...domain.model import Page
from . import confluence_mapper as mapper


def blogpost_from(data: dict[str, Any], fallback_base: str = "") -> Page:
    """A blog post as a `Page`: its answer has the fields of a page's answer, without a parent, a position and an owner."""
    return mapper.page_from(data, fallback_base)
