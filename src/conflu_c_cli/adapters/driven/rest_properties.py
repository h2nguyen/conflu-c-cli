"""The content properties of pages and other content: the REST calls. A mixin of `RestConfluenceGateway`, which provides `_call`, `_finish`, `_transport`, `_settings`,
`_next_cursor` and `_base`."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...domain.model import Chunk
from .confluence_mapper import results_of
from .rest_support import V2, query, quote

# The models and the mapper of this area are imported where they are used, so that a command that never reads it does not load them (tests/test_startup.py).
if TYPE_CHECKING:
    from ...domain.properties import ContentProperty

# The calls of this area that use the v1 API, each with why v2 does not do (see docs/reference/compatibility.md). None: v2 lists, creates and
# changes the properties of every kind of content that has them. No call deletes a property: this CLI has no command that does.
V1_CALLS: dict[str, str] = {}


def _collection(kind: str) -> str:
    from ...domain.properties import collection_of

    found = collection_of(kind)
    if found is None:
        raise ValueError(f"Not a kind of content that has properties: {kind}")
    return found


class RestProperties:
    def list_properties(self, kind: str, content_id: str, *, key: str = "", limit: int = 25, cursor: str = "") -> Chunk[ContentProperty]:
        from .map_properties import property_from

        found = query(key=key, sort="key", limit=limit, cursor=cursor)
        data = self._call("GET", f"{V2}/{_collection(kind)}/{quote(content_id)}/properties?{found}")
        return Chunk([property_from(item) for item in results_of(data)], self._next_cursor(data))

    def create_property(self, kind: str, content_id: str, payload: dict[str, Any]) -> ContentProperty:
        from .map_properties import property_from

        return property_from(self._call("POST", f"{V2}/{_collection(kind)}/{quote(content_id)}/properties", payload))

    def update_property(self, kind: str, content_id: str, property_id: str, payload: dict[str, Any]) -> ContentProperty:
        from .map_properties import property_from

        return property_from(self._call("PUT", f"{V2}/{_collection(kind)}/{quote(content_id)}/properties/{quote(property_id)}", payload))
