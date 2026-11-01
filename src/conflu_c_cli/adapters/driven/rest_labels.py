"""The labels used in a space, besides the labels of a page: the REST calls. A mixin of `RestConfluenceGateway`, which provides `_call`, `_finish`, `_transport`, `_settings`,
`_next_cursor` and `_base`."""
from __future__ import annotations

from ...domain.model import Chunk, Label
from .rest_support import V2
from .rest_support import query as _query
from .rest_support import quote as _quote

# The models and the mapper of this area are imported where they are used, so that a command that never reads it does not load them (tests/test_startup.py).

# The calls of this area that use the v1 API, each with why v2 does not do (see docs/reference/compatibility.md).
# None: v2 lists the labels of a space (`GET /spaces/{id}/content/labels`, which is the labels of its content: `GET /spaces/{id}/labels` is the
# labels of the space itself). Adding and removing a label is `conflu label`, whose v1 calls are in the core.
V1_CALLS: dict[str, str] = {}


class RestLabels:
    def list_space_labels(self, space_id: str, *, limit: int = 25, cursor: str = "") -> Chunk[Label]:
        # By name, so that every piece of a long list continues where the one before it stopped, and a person reads it in order.
        from . import map_labels as label_map

        query = _query(sort="name", limit=limit, cursor=cursor)
        data = self._call("GET", f"{V2}/spaces/{_quote(space_id)}/content/labels?{query}")
        return Chunk(label_map.labels_of(data), self._next_cursor(data))
