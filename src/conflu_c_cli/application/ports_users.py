"""The part of the Confluence port that is about looking up people. `ConfluenceGateway` inherits it.

`lookup_users` (in the port itself) names account ids for the commands that print people they came across; these two are for the command that is
about people: a search by name, and the full description of the people behind some account ids.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from ..domain.users import PeoplePage, Person



class UsersPort(ABC):
    @abstractmethod
    def search_people(self, cql: str, *, limit: int = 25, start: int = 0) -> PeoplePage:
        """The people that the CQL finds (`user.fullname ~ "alex"`: see `domain.users.search_query`), `limit` of them from the position `start`."""

    @abstractmethod
    def lookup_people(self, account_ids: Sequence[str]) -> list[Person]:
        """The people with these account ids, in the order asked; an id that Confluence does not know is left out. More than 250 go in several requests."""
