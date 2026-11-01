"""What Confluence's JSON means for looking up people: the answers as domain objects."""
from __future__ import annotations

from typing import Any

from ...domain.users import Person


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def person_from(item: Any) -> Person | None:
    """A person as the bulk lookup describes one, and as the `user` of a search result does. None for what names nobody."""
    data = _object(item)
    account_id = _text(data.get("accountId"))
    if not account_id:
        return None
    return Person(account_id, _text(data.get("displayName") or data.get("publicName")), _text(data.get("email")), _text(data.get("accountType")))


def person_from_result(result: Any) -> Person | None:
    """One result of `GET /search/user`: the person is its `user`; the rest (a space, content) is what a search of any kind carries."""
    return person_from(_object(result).get("user"))
