"""Use cases around spaces."""
from __future__ import annotations

from dataclasses import dataclass

from ..domain.errors import UsageError
from ..domain.model import Space, parse_space_key
from ..domain.privacy import hide_space
from .paging import PAGE_SIZE, ensure_users_allowed, fetch_all
from .ports import ConfluenceGateway
from .settings import Settings

SPACE_TYPES = ("global", "collaboration", "knowledge_base", "personal")
SPACE_STATUSES = ("current", "archived")


@dataclass
class SpaceList:
    spaces: list[Space]
    next_cursor: str = ""
    truncated: bool = False


def _shown(space: Space, with_users: bool) -> Space:
    """A space as it is printed: as Confluence answers it when people are shown, else without the person that a personal space is named after
    (and with the e-mail addresses of any name redacted): see `privacy.hide_space`."""
    return space if with_users else hide_space(space)


class ListSpaces:
    def __init__(self, gateway: ConfluenceGateway, settings: Settings) -> None:
        self._gateway = gateway
        self._settings = settings

    def execute(
        self,
        *,
        space_type: str = "",
        status: str = "current",
        search: str = "",
        limit: int = 25,
        cursor: str = "",
        fetch_everything: bool = False,
        with_users: bool = False,
    ) -> SpaceList:
        ensure_users_allowed(with_users, self._settings)
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
            shown = [_shown(space, with_users) for space in spaces]  # before the filter: a search must not find what is not shown (`--search alex`)
            if wanted:
                shown = [space for space in shown if wanted in space.key.casefold() or wanted in space.name.casefold()]
            return SpaceList(shown, "", truncated)
        chunk = read(cursor)
        return SpaceList([_shown(space, with_users) for space in chunk.items], chunk.cursor)


class ShowSpace:
    def __init__(self, gateway: ConfluenceGateway, settings: Settings) -> None:
        self._gateway = gateway
        self._settings = settings

    def execute(self, key: str = "", *, with_users: bool = False) -> Space:
        ensure_users_allowed(with_users, self._settings)
        chosen = key or self._settings.space
        if not chosen:
            raise UsageError("No space selected.", hint="Pass a space key or run `conflu use KEY`.")
        return _shown(self._gateway.get_space(parse_space_key(chosen)), with_users)
