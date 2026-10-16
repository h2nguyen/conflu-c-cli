"""Reading a list that comes in pieces, and the names of the people that stay hidden by default."""
from __future__ import annotations

from typing import Callable, Iterable, TypeVar

from ..domain.errors import ConfluCliError, ValidationError
from ..domain.model import Chunk, User
from .ports import ConfluenceGateway, Diagnostics
from .settings import Settings

T = TypeVar("T")

PAGE_SIZE = 100
MAX_ITEMS = 20000  # a stop for a list that never ends; the caller is told when it was reached


def fetch_all(read: Callable[[str], Chunk[T]], *, max_items: int = MAX_ITEMS) -> tuple[list[T], bool]:
    """Every piece of a list: `(items, truncated)`. `read` gets the cursor of the piece it should return."""
    items: list[T] = []
    cursor, seen = "", set()
    while True:
        chunk = read(cursor)
        items.extend(chunk.items)
        if not chunk.cursor or not chunk.items or chunk.cursor in seen:
            return items, False
        if len(items) >= max_items:
            return items[:max_items], True
        seen.add(chunk.cursor)
        cursor = chunk.cursor


def ensure_users_allowed(with_users: bool, settings: Settings) -> None:
    if with_users and settings.hide_users:
        raise ValidationError(
            "CONFLUENCE_HIDE_USERS=true: people are not printed, --with-users is not available.",
            hint="Unset CONFLUENCE_HIDE_USERS if you need to see people.",
        )


def name_users(gateway: ConfluenceGateway, diagnostics: Diagnostics, users: Iterable[User | None]) -> dict[str, User]:
    """The names behind account ids, best effort: a failed lookup leaves the ids as they are."""
    ids = sorted({user.account_id for user in users if user is not None and user.account_id})
    if not ids:
        return {}
    try:
        return gateway.lookup_users(ids)
    except ConfluCliError as error:
        diagnostics.warn(f"Could not look up the names of the people: {error.message}")
        return {}


def named(user: User | None, known: dict[str, User]) -> User | None:
    return known.get(user.account_id, user) if user is not None else None
