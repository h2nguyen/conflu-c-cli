"""What Confluence's JSON means for the content properties of pages and other content: the answers as domain objects."""
from __future__ import annotations

from typing import Any

from ...domain.properties import ContentProperty


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def property_from(data: Any) -> ContentProperty:
    """A content property as the calls of API v2 describe it. The value is any JSON and stays as it came."""
    item = data if isinstance(data, dict) else {}
    version = item.get("version") if isinstance(item.get("version"), dict) else {}
    number = version.get("number")
    return ContentProperty(
        id=_text(item.get("id")),
        key=_text(item.get("key")),
        version=number if isinstance(number, int) and not isinstance(number, bool) else 1,
        value=item.get("value"),
        updated=_text(version.get("createdAt")),
    )
