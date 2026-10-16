"""Use cases around spaces."""
from __future__ import annotations

from dataclasses import dataclass, replace

from ..domain.errors import UsageError
from ..domain.model import Space, parse_space_key
from ..domain.privacy import redact_text
from .paging import PAGE_SIZE, fetch_all
from .ports import ConfluenceGateway
from .settings import Settings

SPACE_TYPES = ("global", "collaboration", "knowledge_base", "personal")
SPACE_STATUSES = ("current", "archived")


@dataclass
class SpaceList:
    spaces: list[Space]
    next_cursor: str = ""
    truncated: bool = False


def _clean(space: Space) -> Space:
    return replace(space, name=redact_text(space.name), description=redact_text(space.description))


class ListSpaces:
    def __init__(self, gateway: ConfluenceGateway) -> None:
        self._gateway = gateway

    def execute(
        self,
        *,
        space_type: str = "",
        status: str = "current",
        search: str = "",
        limit: int = 25,
        cursor: str = "",
        fetch_everything: bool = False,
    ) -> SpaceList:
        if space_type and space_type not in SPACE_TYPES:
            raise UsageError(f"Unknown space type: {space_type}", hint=f"Use one of: {', '.join(SPACE_TYPES)}.")
        wanted = search.strip().casefold()
        everything = fetch_everything or bool(wanted)  # a text filter can only be applied to the whole list

        def read(next_cursor: str):
            return self._gateway.list_spaces(
                space_type=space_type, status=status, limit=PAGE_SIZE if everything else limit, cursor=next_cursor
            )

        if everything:
            spaces, truncated = fetch_all(read)
            if wanted:
                spaces = [space for space in spaces if wanted in space.key.casefold() or wanted in space.name.casefold()]
            return SpaceList([_clean(space) for space in spaces], "", truncated)
        chunk = read(cursor)
        return SpaceList([_clean(space) for space in chunk.items], chunk.cursor)


class ShowSpace:
    def __init__(self, gateway: ConfluenceGateway, settings: Settings) -> None:
        self._gateway = gateway
        self._settings = settings

    def execute(self, key: str = "") -> Space:
        chosen = key or self._settings.space
        if not chosen:
            raise UsageError("No space selected.", hint="Pass a space key or run `conflu use KEY`.")
        return _clean(self._gateway.get_space(parse_space_key(chosen)))
