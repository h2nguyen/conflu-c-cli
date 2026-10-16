"""Use cases around comments: reading the conversations on a page and adding to them."""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Sequence

from ..domain.errors import ValidationError
from ..domain.model import Comment, parse_page_id
from ..domain.payloads import comment_payload
from ..domain.privacy import hide_comment_author
from .paging import PAGE_SIZE, fetch_all, ensure_users_allowed, name_users, named
from .ports import ConfluenceGateway, Diagnostics
from .rendering import INPUT_FORMATS, BODY_FORMATS, Body, check_format, render_body, storage_from_input
from .settings import Settings


@dataclass(frozen=True)
class CommentView:
    comment: Comment  # without the body, which is in `body`; without the author unless people are shown
    body: Body


def read_comments(gateway: ConfluenceGateway, page_id: str, *, inline: bool) -> list[Comment]:
    """The comments of a page, each conversation as its first comment followed by the replies."""
    roots, _ = fetch_all(lambda cursor: gateway.list_comments(page_id, inline=inline, limit=PAGE_SIZE, cursor=cursor))
    found: list[Comment] = []
    for root in roots:
        found.append(root)
        replies, _ = fetch_all(lambda cursor, root=root: gateway.list_replies(root.id, inline=inline, limit=PAGE_SIZE, cursor=cursor))
        found.extend(replies)
    return found


def present_comments(comments: Sequence[Comment], fmt: str, *, with_users: bool) -> list[CommentView]:
    views = []
    for comment in comments:
        body = render_body(comment.body, fmt, with_users=with_users)
        shown = comment if with_users else hide_comment_author(comment)
        views.append(CommentView(replace(shown, body=""), body))
    return views


class ListComments:
    def __init__(self, gateway: ConfluenceGateway, settings: Settings, diagnostics: Diagnostics) -> None:
        self._gateway = gateway
        self._settings = settings
        self._diagnostics = diagnostics

    def execute(self, ref: str, *, inline: bool = False, body_format: str = "markdown", with_users: bool = False) -> list[CommentView]:
        page_id = parse_page_id(ref)
        ensure_users_allowed(with_users, self._settings)
        check_format(body_format, BODY_FORMATS)
        comments = read_comments(self._gateway, page_id, inline=False)
        if inline:
            comments += read_comments(self._gateway, page_id, inline=True)
        if with_users:
            known = name_users(self._gateway, self._diagnostics, [comment.author for comment in comments])
            comments = [replace(comment, author=named(comment.author, known)) for comment in comments]
        return present_comments(comments, body_format, with_users=with_users)


@dataclass
class CommentResult:
    page_id: str
    payload: dict[str, Any]
    dry_run: bool
    comment_id: str = ""


class AddComment:
    def __init__(self, gateway: ConfluenceGateway) -> None:
        self._gateway = gateway

    def execute(self, ref: str, body: str, *, body_format: str = "markdown", reply_to: str = "", dry_run: bool = False) -> CommentResult:
        page_id = parse_page_id(ref)
        check_format(body_format, INPUT_FORMATS)
        if not body.strip():
            raise ValidationError("The comment is empty.", hint="Pass text with --text or --file.")
        if reply_to and not re.fullmatch(r"[0-9]+", reply_to):  # not str.isdigit(): it accepts digits of other scripts
            raise ValidationError(f"Not a comment id: {reply_to}", hint="A comment id is a number; `conflu comments PAGE --json` lists them.")
        payload = comment_payload(page_id, storage_from_input(body, body_format), reply_to)
        if dry_run:
            self._gateway.get_page(page_id, with_body=False)  # proves that the page exists
            return CommentResult(page_id, payload, True)
        created = self._gateway.add_comment(payload)
        return CommentResult(page_id, payload, False, created.id)
