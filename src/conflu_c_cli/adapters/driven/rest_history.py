"""Earlier versions of a page, the difference between two of them, and restoring one: the REST calls. A mixin of `RestConfluenceGateway`, which provides `_call`, `_finish`, `_transport`, `_settings`,
`_next_cursor` and `_base`."""
from __future__ import annotations

from typing import Any, Sequence

from ...domain.model import Chunk, Page
from . import confluence_mapper as mapper
from .rest_support import V1, V2, query, quote

# The models and the mapper of this area are imported where they are used, so that a command that never reads it does not load them (tests/test_startup.py).

# The calls of this area that use the v1 API, each with why v2 does not do (see docs/reference/compatibility.md).
V1_CALLS: dict[str, str] = {
    "POST /rest/api/content/{id}/version": "v2 reads the versions of a page and has no call that restores one.",
}


class RestHistory:
    def get_page_version(self, page_id: str, number: int, *, with_body: bool = True) -> Page:
        from . import map_history

        params = query(version=number, body_format="storage" if with_body else "")
        data = self._call("GET", f"{V2}/pages/{quote(page_id)}?{params}")
        return map_history.page_version_from(data, self._settings.wiki_url)

    def get_pages(self, ids: Sequence[str], *, with_body: bool = False, limit: int = 250, cursor: str = "") -> Chunk[Page]:
        params = query(id=list(ids), body_format="storage" if with_body else "", limit=limit, cursor=cursor)
        data = self._call("GET", f"{V2}/pages?{params}")
        base = self._base(data)
        return Chunk([mapper.page_from(item, base) for item in mapper.results_of(data)], self._next_cursor(data))

    def restore_page_version(self, page_id: str, payload: dict[str, Any]) -> int:
        from . import map_history

        return map_history.restored_number(self._call("POST", f"{V1}/content/{quote(page_id)}/version", payload))
