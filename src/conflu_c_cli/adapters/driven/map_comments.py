"""What Confluence's JSON means for the comments of a page: reading one, editing one, resolving and filtering: the answers as domain objects."""
from __future__ import annotations

from typing import Any

from ...domain.comments import CommentRecord
from ...domain.model import Comment
from . import confluence_mapper as mapper


def comment_of(data: Any, kind: str) -> Comment:
    """A comment as the answers of the comment endpoints describe it (`kind` is the collection that was asked: footer or inline)."""
    return mapper.comment_from(data if isinstance(data, dict) else {}, kind)


def record_of(data: Any, kind: str) -> CommentRecord:
    """The comment and the page it is on (`pageId`; a comment on a blog post or on an attachment has none)."""
    page_id = data.get("pageId") if isinstance(data, dict) else None
    return CommentRecord(comment_of(data, kind), "" if page_id is None else str(page_id))
