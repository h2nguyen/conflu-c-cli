"""The part of the Confluence port that is about earlier versions of a page, the difference between two of them, and restoring one. `ConfluenceGateway` inherits it."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:
    from ..domain.model import Chunk, Page



class HistoryPort(ABC):
    @abstractmethod
    def get_page_version(self, page_id: str, number: int, *, with_body: bool = True) -> Page:
        """An earlier version of the page as it was saved: its title, its body in storage format when `with_body`, and that version (number, time,
        message). The page's own labels are not part of it. NotFoundError when the page has no such version."""

    @abstractmethod
    def get_pages(self, ids: Sequence[str], *, with_body: bool = False, limit: int = 250, cursor: str = "") -> Chunk[Page]:
        """Several pages with one request, at most 250 ids: those that exist, are current or archived and may be seen, without their labels,
        which this call does not give. An id that is not in the answer is not an error; a cursor continues an answer that did not fit."""

    @abstractmethod
    def restore_page_version(self, page_id: str, payload: dict[str, Any]) -> int:
        """Sends `payload` as it is (see `domain.history.restore_payload`): Confluence saves a new version of the page with the content of an
        earlier one. Returns the number of the new version when Confluence says it, else 0."""
