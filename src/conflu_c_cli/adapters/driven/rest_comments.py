"""The comments of a page: reading one, editing one, resolving and filtering: the REST calls. A mixin of `RestConfluenceGateway`, which provides `_call`, `_finish`, `_transport`, `_settings`,
`_next_cursor` and `_base`."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...domain.errors import NotFoundError
from ...domain.model import Chunk, Comment
from . import confluence_mapper as mapper
from .rest_support import V2
from .rest_support import query as _query
from .rest_support import quote as _quote

# The models and the mapper of this area are imported where they are used, so that a command that never reads it does not load them (tests/test_startup.py).
if TYPE_CHECKING:
    from ...domain.comments import CommentRecord

# The calls of this area that use the v1 API, each with why v2 does not do (see docs/reference/compatibility.md).
# None: v2 reads, changes and filters comments (`GET` and `PUT` of `/footer-comments/{comment-id}` and `/inline-comments/{comment-id}`, the
# `resolution-status` filter of `/pages/{id}/inline-comments`). Whether a comment is yours is the one v1 call of the core, `GET /rest/api/user/current`.
V1_CALLS: dict[str, str] = {}

KINDS = ("footer", "inline")


class RestComments:
    def get_comment(self, comment_id: str) -> CommentRecord:
        # Footer and inline comments have a collection each and share their ids with every other kind of content. The footer comments are asked
        # first, they are the common ones; a 404 sends the question on to the inline comments, and a 404 there is the answer.
        from . import map_comments as comment_map

        for kind in KINDS:
            try:
                data = self._call("GET", f"{V2}/{kind}-comments/{_quote(comment_id)}?{_query(body_format='storage')}")
            except NotFoundError:
                continue
            return comment_map.record_of(data, kind)
        raise NotFoundError(
            f"No comment with the id {comment_id}.",
            hint="Confluence also answers 404 for what the account may not see.",
            details={"status": 404, "commentId": comment_id},
        )

    def update_comment(self, comment_id: str, kind: str, payload: dict[str, Any]) -> Comment:
        from . import map_comments as comment_map

        if kind not in KINDS:
            raise ValueError(f"A comment is a footer or an inline comment, not {kind!r}")
        data = self._call("PUT", f"{V2}/{kind}-comments/{_quote(comment_id)}", payload)
        return comment_map.comment_of(data, kind)

    def list_inline_comments(self, page_id: str, *, resolution: str = "", limit: int = 50, cursor: str = "") -> Chunk[Comment]:
        from . import map_comments as comment_map

        query = _query(body_format="storage", resolution_status=resolution, sort="created-date", limit=limit, cursor=cursor)
        data = self._call("GET", f"{V2}/pages/{_quote(page_id)}/inline-comments?{query}")
        return Chunk([comment_map.comment_of(item, "inline") for item in mapper.results_of(data)], self._next_cursor(data))
