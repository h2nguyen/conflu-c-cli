"""The part of the Confluence port that is about the content properties of pages and other content. `ConfluenceGateway` inherits it.

Every kind of content that has properties has them in its own collection of the v2 API, so an operation takes the kind that Confluence calls
the content (`page`, `blogpost`, `folder`, `whiteboard`, `database`, `embed`, `attachment`, `footer-comment`, `inline-comment`: what
`content_types` answers). No operation deletes a property.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..domain.model import Chunk
    from ..domain.properties import ContentProperty



class PropertiesPort(ABC):
    @abstractmethod
    def list_properties(self, kind: str, content_id: str, *, key: str = "", limit: int = 25, cursor: str = "") -> Chunk[ContentProperty]:
        """The properties of the content, by key; `key` keeps the one property with that key (case sensitive). NotFoundError when there is no such content."""

    @abstractmethod
    def create_property(self, kind: str, content_id: str, payload: dict[str, Any]) -> ContentProperty:
        """Sends `payload` as it is (see `domain.properties.create_payload`): what a dry run shows is what is sent."""

    @abstractmethod
    def update_property(self, kind: str, content_id: str, property_id: str, payload: dict[str, Any]) -> ContentProperty:
        """Sends `payload` as it is (see `domain.properties.update_payload`). A version that is not the next one is a ConflictError."""
