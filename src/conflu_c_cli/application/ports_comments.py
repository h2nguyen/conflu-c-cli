"""The part of the Confluence port that is about the comments of a page: reading one, editing one, resolving and filtering. `ConfluenceGateway` inherits it."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..domain.comments import CommentRecord
    from ..domain.model import Chunk, Comment



class CommentsPort(ABC):
    @abstractmethod
    def get_comment(self, comment_id: str) -> CommentRecord:
        """The comment with this id, footer or inline, and the page it is on. NotFoundError when there is none, or when it cannot be seen."""

    @abstractmethod
    def update_comment(self, comment_id: str, kind: str, payload: dict[str, Any]) -> Comment:
        """Sends `payload` as it is (see `domain.comments.edit_payload`) to the footer or inline comment (`kind`) with this id. A version that is not
        the next one is a ConflictError; somebody else's comment is an AuthError."""

    @abstractmethod
    def list_inline_comments(self, page_id: str, *, resolution: str = "", limit: int = 50, cursor: str = "") -> Chunk[Comment]:
        """The inline comments at the top of the conversations, only those in this resolution state when `resolution` is given."""
