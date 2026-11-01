"""What Confluence's JSON means for the watches of the user on pages and spaces: the answers as domain objects."""
from __future__ import annotations

from typing import Any


def watching_from(data: Any) -> bool | None:
    """The `watching` of an answer to a watch status, or None when the answer does not say."""
    value = data.get("watching") if isinstance(data, dict) else None
    return value if isinstance(value, bool) else None
