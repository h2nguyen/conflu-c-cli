"""The part of the Confluence port that is about folders, whiteboards, databases and smart links, and where content sits in the tree.
`ConfluenceGateway` inherits it.

The first operation is the one that every kind of content needs: what kind an id is. The REST API v2 has a collection for each kind, so a
command that takes the id of "a page or a folder" has to ask before it can ask for the thing itself. The others take the kind (`folder`,
`whiteboard`, `database`, `embed`, and for what the tree has in common also `page`) and ask that collection.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:
    from ..domain.model import Chunk, PageRef, TreeNode
    from ..domain.structure import Container, DatabaseEntry, DatabaseField, DatabaseView



class StructurePort(ABC):
    @abstractmethod
    def content_types(self, ids: Sequence[str]) -> dict[str, str | None]:
        """What Confluence calls the content with each id (`page`, `blogpost`, `folder`, `whiteboard`, `database`, `embed`, `footer-comment`,
        `inline-comment`, `attachment`, `custom`), or None for an id that does not exist or that this account may not see. At most 100 ids."""

    @abstractmethod
    def get_container(self, kind: str, container_id: str) -> Container:
        """The folder, whiteboard, database or smart link with this id; NotFoundError when the id is another kind of content, or unknown."""

    @abstractmethod
    def list_children(self, kind: str, container_id: str, *, limit: int = 25, cursor: str = "") -> Chunk[TreeNode]:
        """What sits directly below it, in the order of the tree: pages, folders, whiteboards, databases and smart links."""

    @abstractmethod
    def list_container_descendants(self, kind: str, container_id: str, *, depth: int = 3, limit: int = 250, cursor: str = "") -> Chunk[TreeNode]:
        """Everything below it down to `depth` levels, as `list_descendants` has it for a page: nodes with their type, parent and depth."""

    @abstractmethod
    def list_container_ancestors(self, kind: str, container_id: str) -> list[PageRef]:
        """From the top of the tree down to the parent: the id and the type of each. Confluence names no title there (`application.containers.with_titles`
        asks for them); an adapter or a fake may fill them in."""

    @abstractmethod
    def create_folder(self, payload: dict[str, Any]) -> Container:
        """Sends `payload` as it is (see `domain.structure.folder_payload`): what a dry run shows is what is sent."""

    @abstractmethod
    def create_smartlink(self, payload: dict[str, Any]) -> Container:
        """Sends `payload` as it is (see `domain.structure.smartlink_payload`)."""

    @abstractmethod
    def list_database_fields(self, database_id: str, *, limit: int = 25, cursor: str = "") -> Chunk[DatabaseField]: ...

    @abstractmethod
    def list_database_views(self, database_id: str, *, limit: int = 25, cursor: str = "") -> Chunk[DatabaseView]: ...

    @abstractmethod
    def list_database_entries(self, database_id: str, *, limit: int = 25, cursor: str = "") -> Chunk[DatabaseEntry]: ...
