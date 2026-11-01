"""The routes of the mock Confluence for the labels used in a space, besides the labels of a page. `MockConfluence` asks them before its own routes (see mock_extensions.py)."""
from __future__ import annotations

from typing import Any

from .mock_base import RequestError, Routes

SORTS = {"created-date", "-created-date", "id", "-id", "name", "-name"}


class LabelsRoutes(Routes):
    """`GET /spaces/{id}/content/labels`: the labels of the pages and blog posts of a space, each once. The document lists the prefixes `my` and
    `team` for it (both by default); the labels of this mock are the ones anyone may use, `global` as the page endpoints answer them, so they
    are all there without a prefix and none is there for `my` or `team`. A label has no date here, so the sorts by date are by name too."""

    def handle(self, handler: Any, method: str, path: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]], body: Any) -> bool:
        found = self.match(r"/api/v2/spaces/([0-9]+)/content/labels", path)
        if found is None or method != "GET":
            return False
        self._read(handler, found.group(1), query, query_pairs)
        return True

    def _read(self, handler: Any, space_id: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        handler._require_known_query(query, {"prefix", "sort", "cursor", "limit"})
        if space_id not in self.mock.spaces:
            raise RequestError(404, "Not found", f"Space not found: {space_id}", code="NOT_FOUND")
        prefix = handler._single(query, "prefix")
        if prefix not in {None, "my", "team"}:
            raise RequestError(400, "Invalid request parameter", f"Unsupported value for prefix: {prefix}")
        sort = handler._single(query, "sort") or "id"
        if sort not in SORTS:
            raise RequestError(400, "Invalid request parameter", f"Unsupported value for sort: {sort}")
        offset = handler._parse_cursor(query)
        limit = handler._parse_limit(query, default=25)
        names = sorted({name for page in self.mock.pages.values() if page["spaceId"] == space_id for name in page["labels"]}, reverse=sort.startswith("-"))
        labels = [{"id": f"lbl-{space_id}-{name}", "name": name, "prefix": "global"} for name in names] if prefix is None else []
        shown, links, headers = handler._apply_pagination(labels, path=f"/api/v2/spaces/{space_id}/content/labels", query_pairs=query_pairs, offset=offset, limit=limit)
        handler._reply_json(200, {"results": shown, "_links": links}, headers)
