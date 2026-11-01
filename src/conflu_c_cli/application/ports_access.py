"""The part of the Confluence port that is about what the user may do, restrictions on content, and the permissions and roles of a space. `ConfluenceGateway` inherits it.

Everything in it is read only. The kinds are what Confluence calls them (`page`, `blogpost`, `folder`, `whiteboard`, `database`, `embed`, `footer-comment`,
`inline-comment`, `attachment`, `custom`), and `space` for the operations of a space, which is no kind of content.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..domain.access import ContentPermission, Operation, RestrictionState, RoleAssignment, SpacePermission, SpaceRole
    from ..domain.model import Chunk



class AccessPort(ABC):
    @abstractmethod
    def list_operations(self, kind: str, target_id: str) -> list[Operation]:
        """What the token's user may do with the content of this kind and id, or in the space with this id (kind `space`). NotFoundError when
        Confluence has no such thing for this account."""

    @abstractmethod
    def get_restriction_state(self, kind: str, content_id: str) -> RestrictionState:
        """The restriction that is set on the content itself (`OPEN`, `EDIT_RESTRICTED`, `VIEW_RESTRICTED`); one a parent sets is not in it. Kinds: page, blogpost,
        folder, whiteboard, database."""

    @abstractmethod
    def list_content_permissions(self, kind: str, content_id: str, *, limit: int = 250, cursor: str = "") -> Chunk[ContentPermission]:
        """The direct permissions on the content: who may read, and who may update. At most 250 to a piece."""

    @abstractmethod
    def get_space_role_mode(self) -> str:
        """`PRE_ROLES`, `ROLES_TRANSITION` or `ROLES`: how the site gives access to its spaces. NotFoundError on a site without space roles."""

    @abstractmethod
    def list_space_permissions(self, space_id: str, *, limit: int = 250, cursor: str = "") -> Chunk[SpacePermission]:
        """The permission assignments of the space (the permission model): who may do what."""

    @abstractmethod
    def list_space_role_assignments(self, space_id: str, *, limit: int = 250, cursor: str = "") -> Chunk[RoleAssignment]:
        """The role assignments of the space (the role model): who has which role."""

    @abstractmethod
    def list_space_roles(self, space_id: str = "", *, limit: int = 250, cursor: str = "") -> Chunk[SpaceRole]:
        """The roles of the site, or those available for one space; the names that the role assignments need."""
