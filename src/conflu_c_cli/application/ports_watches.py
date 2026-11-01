"""The part of the Confluence port that is about the watches of the user on pages and spaces. `ConfluenceGateway` inherits it.

Only the watch of the token's own user: no operation takes the name of another person.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..domain.watches import WatchChange



class WatchesPort(ABC):
    @abstractmethod
    def watch_status(self, scope: str, target: str) -> bool:
        """Whether the token's user watches the content with this id (`scope` `content`) or the space with this key (`space`). NotFoundError when
        Confluence has no such thing for this account."""

    @abstractmethod
    def change_watch(self, change: WatchChange) -> None:
        """Sends `change` as it is (see `domain.watches.WatchChange`): what a dry run shows is what is sent. It adds or removes the watch of the token's own user."""
