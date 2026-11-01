"""The part of the Confluence port that is about the labels used in a space, besides the labels of a page. `ConfluenceGateway` inherits it."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..domain.model import Chunk, Label



class LabelsPort(ABC):
    @abstractmethod
    def list_space_labels(self, space_id: str, *, limit: int = 25, cursor: str = "") -> Chunk[Label]:
        """The labels that the content of a space (pages, blog posts ...) carries, by name, a piece of the list at a time."""
