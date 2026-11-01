"""The routes of the mock Confluence for the comments of a page: reading one, editing one, resolving and filtering. `MockConfluence` asks them before its own routes (see mock_extensions.py)."""
from __future__ import annotations

from typing import Any

from .mock_base import RequestError, Routes

ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"  # the user of the token of the mock
OTHER = "5b10ac8d82e05b22cc7d4ef6"  # somebody else
KINDS = {"footer-comments": "footer", "inline-comments": "inline"}
READ_PARAMETERS = {"body-format", "version", "include-properties", "include-operations", "include-likes", "include-versions", "include-version"}


class CommentsRoutes(Routes):
    """`GET` and `PUT` of one comment, `/footer-comments/{comment-id}` and `/inline-comments/{comment-id}`: a comment is found in the collection of
    its own kind only (the other one answers 404, as it does for any id that is no comment of that kind). A change needs the next version number
    (HTTP 409 otherwise); the text of somebody else's comment cannot be changed (HTTP 403), and a dangling comment cannot be changed at all."""

    def handle(self, handler: Any, method: str, path: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]], body: Any) -> bool:
        found = self.match(r"/api/v2/(footer-comments|inline-comments)/([0-9]+)", path)
        if found is None or method not in ("GET", "PUT"):
            return False
        collection, comment_id = found.groups()
        if method == "GET":
            self._read(handler, collection, comment_id, query)
        else:
            self._change(handler, collection, comment_id, body)
        return True

    def add_fixtures(self) -> None:
        """The comments 4100 to 4107 on page 2004, which no other test reads comments of: somebody else's footer comment and an answer to it, inline
        comments in each state, one with a mention, an address and a macro, and an answer to an inline comment. Alex is the user of the token."""
        mention = f'<ac:link><ri:user ri:account-id="{ACCOUNT}" /></ac:link>'
        macro = '<ac:structured-macro ac:name="info" ac:schema-version="1"><ac:rich-text-body><p>Note</p></ac:rich-text-body></ac:structured-macro>'
        rows = (
            ("4100", "footer", None, OTHER, 1, "2026-10-12T09:00:00.000Z", "<p>Please review the decision.</p>", None),
            ("4101", "footer", "4100", ACCOUNT, 3, "2026-10-13T09:00:00.000Z", "<p>Will do.</p>", None),
            ("4102", "inline", None, ACCOUNT, 1, "2026-10-14T09:00:00.000Z", "<p>Is this still true?</p>", "open"),
            ("4103", "inline", None, ACCOUNT, 2, "2026-10-09T09:00:00.000Z", "<p>Fixed already.</p>", "resolved"),
            ("4104", "inline", None, ACCOUNT, 1, "2026-10-08T09:00:00.000Z", "<p>The text is gone.</p>", "dangling"),
            ("4105", "inline", None, ACCOUNT, 4, "2026-10-11T09:00:00.000Z", "<p>Again, please.</p>", "reopened"),
            ("4106", "footer", None, ACCOUNT, 1, "2026-10-10T09:00:00.000Z", f"<p>Ask {mention} or write to alex@example.com.</p>{macro}", None),
            ("4107", "inline", "4102", OTHER, 1, "2026-10-14T10:00:00.000Z", "<p>Yes, it is.</p>", "open"),
        )
        for comment_id, kind, parent, author, number, saved, text, resolution in rows:
            self.mock.comments[comment_id] = {
                "id": comment_id,
                "kind": kind,
                "pageId": "2004",
                "parentCommentId": parent,
                "authorId": author,
                "version": {"number": number, "createdAt": saved},
                "createdAt": saved,
                "body": text,
                "resolutionStatus": resolution,
            }

    def _comment(self, collection: str, comment_id: str) -> dict[str, Any]:
        comment = self.mock.comments.get(comment_id)
        if comment is None or comment["kind"] != KINDS[collection]:
            raise RequestError(404, "Not found", f"Comment not found: {comment_id}", code="NOT_FOUND")
        return comment

    def _read(self, handler: Any, collection: str, comment_id: str, query: dict[str, list[str]]) -> None:
        handler._require_known_query(query, READ_PARAMETERS)
        comment = self._comment(collection, comment_id)
        body_format = handler._single(query, "body-format")
        if body_format not in {None, "storage", "atlas_doc_format"}:
            raise RequestError(400, "Invalid request parameter", f"Unsupported value for body-format: {body_format}")
        handler._reply_json(200, handler._comment_model(comment, body_format=body_format))

    def _change(self, handler: Any, collection: str, comment_id: str, body: Any) -> None:
        kind = KINDS[collection]
        comment = self._comment(collection, comment_id)
        data = handler._require_object(body)
        for name in data:
            if name not in ("version", "body") + (("resolved",) if kind == "inline" else ()):
                raise RequestError(400, "Invalid request body", f"Unknown property: {name}")
        version = data.get("version")
        number = version.get("number") if isinstance(version, dict) else None
        if not isinstance(number, int) or isinstance(number, bool):
            raise RequestError(400, "Invalid request body", "version.number is required and must be an integer")
        if isinstance(version.get("message", ""), bool) or not isinstance(version.get("message", ""), str):
            raise RequestError(400, "Invalid request body", "version.message must be a string")
        current = comment["version"]["number"]
        if number != current + 1:
            raise RequestError(409, "Conflict", f"Version conflict: the comment is at version {current}, a change needs version {current + 1}, not {number}", code="CONFLICT")
        if "body" not in data and "resolved" not in data:
            raise RequestError(400, "Invalid request body", "body is required")
        if "body" in data and data["body"] is None:
            raise RequestError(400, "Invalid request body", "body must not be null")
        text = handler._parse_body_value(data["body"]) if "body" in data else comment["body"]
        if "resolved" in data and not isinstance(data["resolved"], bool):
            raise RequestError(400, "Invalid request body", "resolved must be true or false")
        if kind == "inline" and comment.get("resolutionStatus") == "dangling":
            raise RequestError(400, "Invalid request body", "A dangling comment cannot be updated")
        if text != comment["body"] and comment["authorId"] != ACCOUNT:
            raise RequestError(403, "Forbidden", "Only the author of a comment can change its text", code="FORBIDDEN")
        comment.setdefault("createdAt", comment["version"]["createdAt"])  # a comment keeps the date it was written on
        comment["body"] = text
        comment["version"] = {"number": number, "createdAt": self.mock._tick()}
        if data.get("resolved") is True:
            comment["resolutionStatus"] = "resolved"
        elif data.get("resolved") is False and comment.get("resolutionStatus") == "resolved":
            comment["resolutionStatus"] = "reopened"  # `false` for a comment that is open already changes nothing
        handler._reply_json(200, handler._comment_model(comment, body_format="storage"))
