"""What the route handlers of the mock Confluence have in common: the error that becomes a refusal, and the base of a feature area."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class RequestError(Exception):
    """A request that the mock refuses. `old` says that the answer has the shape of the v1 API's errors, else that of v2."""

    status: int
    title: str
    detail: str
    code: str = "INVALID_REQUEST_PARAMETER"
    old: bool = False
    old_key: str = "BAD_REQUEST"
    payload: Any = None


class Routes:
    """The routes of one feature area. `MockConfluence` creates one of each (see mock_extensions.py) and asks them before its own routes.

    `handle` answers a request that is this area's and returns True, or returns False for any other. The handler (`handler`) has the
    helpers of the mock: `_reply_json`, `_reply_bytes`, `_single`, `_parse_limit`, `_parse_cursor`, `_parse_csv`, `_apply_pagination`, `_require_object`, ...
    Raise `RequestError` for a refusal. The state of the area belongs to the instance; the rest of the data is `self.mock`."""

    def __init__(self, mock: Any) -> None:
        self.mock = mock

    def handle(self, handler: Any, method: str, path: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]], body: Any) -> bool:
        return False

    @staticmethod
    def match(pattern: str, path: str) -> "re.Match[str] | None":
        return re.fullmatch(pattern, path)
