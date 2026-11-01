"""The in-memory Confluence for the comments of a page: reading one, editing one, resolving and filtering: a mixin of `FakeGateway` (`_init_comments` sets up its state)."""
from __future__ import annotations

import dataclasses
from typing import Any

from conflu_c_cli.domain.comments import CommentRecord
from conflu_c_cli.domain.errors import AuthError, ConflictError, NotFoundError, RejectedError
from conflu_c_cli.domain.model import Chunk, Comment, User

OTHER = "5b10ac8d82e05b22cc7d4ef6"  # an account that is not the one of the token: the author of somebody else's comment
SAVED = "2026-10-15T08:30:00.000Z"
MENTION = '<ac:link><ri:user ri:account-id="5b10ac8d82e05b22cc7d4ef5" /></ac:link>'


class FakeComments:
    def _init_comments(self) -> None:
        self.comment_saved = SAVED  # when the next change of a comment is saved; a test may set it

    def add_comment_fixtures(self) -> None:
        """The comments 4100 to 4107 on page 2004, which no other test reads comments of: somebody else's footer comment and an answer to it, inline
        comments in each state, one that holds a mention, an address and a macro, and an answer to an inline comment. Alex is the user of the token."""
        alex, other = self.user, User(OTHER)
        rows = (
            Comment("4100", "footer", "2026-10-12T09:00:00.000Z", "<p>Please review the decision.</p>", 1, other),
            Comment("4101", "footer", "2026-10-13T09:00:00.000Z", "<p>Will do.</p>", 3, alex, "4100"),
            Comment("4102", "inline", "2026-10-14T09:00:00.000Z", "<p>Is this still true?</p>", 1, alex, "", "open"),
            Comment("4103", "inline", "2026-10-09T09:00:00.000Z", "<p>Fixed already.</p>", 2, alex, "", "resolved"),
            Comment("4104", "inline", "2026-10-08T09:00:00.000Z", "<p>The text is gone.</p>", 1, alex, "", "dangling"),
            Comment("4105", "inline", "2026-10-11T09:00:00.000Z", "<p>Again, please.</p>", 4, alex, "", "reopened"),
            Comment(
                "4106",
                "footer",
                "2026-10-10T09:00:00.000Z",
                f"<p>Ask {MENTION} or write to alex@example.com.</p>"
                '<ac:structured-macro ac:name="info" ac:schema-version="1"><ac:rich-text-body><p>Note</p></ac:rich-text-body></ac:structured-macro>',
                1,
                alex,
            ),
            Comment("4107", "inline", "2026-10-14T10:00:00.000Z", "<p>Yes, it is.</p>", 1, other, "4102", "open"),
        )
        self.comments.setdefault("2004", []).extend(rows)

    def _find_comment(self, comment_id: str) -> tuple[str, int, Comment]:
        for page_id, items in self.comments.items():
            for index, comment in enumerate(items):
                if comment.id == comment_id:
                    return page_id, index, comment
        raise NotFoundError(
            f"No comment with the id {comment_id}.",
            hint="Confluence also answers 404 for what the account may not see.",
            details={"status": 404, "commentId": comment_id},
        )

    def get_comment(self, comment_id: str) -> CommentRecord:
        self._enter("get_comment", comment_id)
        page_id, _, comment = self._find_comment(comment_id)
        return CommentRecord(comment, page_id)

    def update_comment(self, comment_id: str, kind: str, payload: dict[str, Any]) -> Comment:
        self._enter("update_comment", comment_id, kind, payload)
        page_id, index, comment = self._find_comment(comment_id)
        request = f"PUT /api/v2/{kind}-comments/{comment_id}"
        if comment.kind != kind:
            raise NotFoundError(f"Not found: {request}", details={"status": 404, "request": request})
        if payload["version"]["number"] != comment.version + 1:
            raise ConflictError("Confluence reports a conflict (HTTP 409): Version conflict.", details={"status": 409, "request": request})
        body = payload.get("body", {}).get("value", comment.body)
        resolution = comment.resolution
        if "resolved" in payload:
            if kind != "inline":
                raise RejectedError("Confluence refused the request (HTTP 400): resolved is for inline comments.", details={"status": 400, "request": request})
            if resolution == "dangling":
                raise RejectedError("Confluence refused the request (HTTP 400): a dangling comment cannot be updated.", details={"status": 400, "request": request})
            resolution = "resolved" if payload["resolved"] else ("reopened" if resolution == "resolved" else resolution)
        if body != comment.body and (comment.author is None or comment.author.account_id != self.user.account_id):
            raise AuthError("Confluence refused this request (HTTP 403): only the author can change a comment.", details={"status": 403, "request": request})
        saved = dataclasses.replace(comment, body=body, version=comment.version + 1, updated=self.comment_saved, resolution=resolution)
        self.comments[page_id][index] = saved
        return saved

    def list_inline_comments(self, page_id: str, *, resolution: str = "", limit: int = 50, cursor: str = "") -> Chunk[Comment]:
        self._enter("list_inline_comments", page_id, resolution, limit, cursor)
        self._page(page_id)
        roots = [
            comment
            for comment in self.comments.get(page_id, [])
            if comment.kind == "inline" and not comment.parent_id and (not resolution or comment.resolution == resolution)
        ]
        return self._chunk(roots, cursor, limit)
