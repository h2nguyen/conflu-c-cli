"""Folders, whiteboards, databases, smart links and where content sits in the tree: the REST calls. A mixin of `RestConfluenceGateway`, which
provides `_call`, `_finish`, `_transport`, `_settings`, `_next_cursor` and `_base`."""
from __future__ import annotations

from typing import Any, Sequence

from ...domain.content import CONTAINERS
from ...domain.model import Chunk, PageRef, TreeNode
from ...domain.structure import Container, DatabaseEntry, DatabaseField, DatabaseView
from .confluence_mapper import results_of, tree_node_from
from .rest_support import V2, next_cursor, query, quote

# The models and the mapper of this area are imported where they are used, so that a command that never reads it does not load them (tests/test_startup.py).

# The calls of this area that use the v1 API, each with why v2 does not do (see docs/reference/compatibility.md). None: v2 reads, creates
# and lists all of it. A page is moved below a folder, or any other container, with the v2 call that saves the page (`PUT /pages/{id}`), and
# before or after another page with the v1 call that `confluence_rest.py` names.
V1_CALLS: dict[str, str] = {}

TYPES_AT_A_TIME = 100  # what `convert-ids-to-types` takes in one call
ANCESTORS_AT_A_TIME = 250  # what the list of the ancestors of an item takes in one call
MAX_ANCESTOR_CALLS = 20  # a tree that is deeper than 20 of these calls has an ancestor that is its own: the bound ends the loop that it would make


def _collection(kind: str) -> str:
    found = next((item for item in CONTAINERS if item.name == kind), None)
    if found is None:
        raise ValueError(f"Not a kind of content that holds other content: {kind}")
    return found.collection


def _more(data: Any) -> str:
    """The cursor of the next piece of a list of a database, which also says in `meta` whether there is one."""
    meta = data.get("meta") if isinstance(data, dict) else None
    if isinstance(meta, dict) and meta.get("hasMore") is False:
        return ""
    return next_cursor(data)


class RestStructure:
    def content_types(self, ids: Sequence[str]) -> dict[str, str | None]:
        wanted = list(dict.fromkeys(str(item) for item in ids))
        found: dict[str, str | None] = {}
        for start in range(0, len(wanted), TYPES_AT_A_TIME):
            data = self._call("POST", f"{V2}/content/convert-ids-to-types", {"contentIds": wanted[start : start + TYPES_AT_A_TIME]})
            results = data.get("results") if isinstance(data, dict) else None
            for key, value in (results if isinstance(results, dict) else {}).items():
                found[str(key)] = value if isinstance(value, str) and value else None
        return {item: found.get(item) for item in wanted}

    def get_container(self, kind: str, container_id: str) -> Container:
        from . import map_structure as structure_mapper

        data = self._call("GET", f"{V2}/{_collection(kind)}/{quote(container_id)}")
        return structure_mapper.container_from(data, kind, self._settings.wiki_url)

    def list_children(self, kind: str, container_id: str, *, limit: int = 25, cursor: str = "") -> Chunk[TreeNode]:
        from . import map_structure as structure_mapper

        data = self._call("GET", f"{V2}/{_collection(kind)}/{quote(container_id)}/direct-children?{query(limit=limit, cursor=cursor)}")
        return Chunk([structure_mapper.child_from(item, container_id) for item in results_of(data)], self._next_cursor(data))

    def list_container_descendants(self, kind: str, container_id: str, *, depth: int = 3, limit: int = 250, cursor: str = "") -> Chunk[TreeNode]:
        data = self._call("GET", f"{V2}/{_collection(kind)}/{quote(container_id)}/descendants?{query(depth=depth, limit=limit, cursor=cursor)}")
        return Chunk([tree_node_from(item) for item in results_of(data)], self._next_cursor(data))

    def _ancestors(self, kind: str, item_id: str) -> list[dict[str, Any]]:
        """The ancestors of an item from the top down, as the answers give them (an id and a type). A call answers with at most `limit` of them, the
        nearest ones, and for more the documents say to "call this endpoint with the ID of first ancestor in the response payload": that gives the
        ancestors above it."""
        found: list[dict[str, Any]] = []
        for _ in range(MAX_ANCESTOR_CALLS):
            data = self._call("GET", f"{V2}/{_collection(kind)}/{quote(item_id)}/ancestors?{query(limit=ANCESTORS_AT_A_TIME)}")
            answer = [item for item in results_of(data) if item.get("id")]
            found = answer + found
            if len(answer) < ANCESTORS_AT_A_TIME:
                break
            item_id, kind = str(answer[0]["id"]), str(answer[0].get("type") or "page")
        return found

    def list_container_ancestors(self, kind: str, container_id: str) -> list[PageRef]:
        from . import map_structure as structure_mapper

        return [structure_mapper.ancestor_from(item) for item in self._ancestors(kind, container_id)]  # an ancestor has an id and a type, no title

    def create_folder(self, payload: dict[str, Any]) -> Container:
        from . import map_structure as structure_mapper

        data = self._call("POST", f"{V2}/folders", payload)
        return structure_mapper.container_from(data, "folder", self._settings.wiki_url)

    def create_smartlink(self, payload: dict[str, Any]) -> Container:
        from . import map_structure as structure_mapper

        data = self._call("POST", f"{V2}/embeds", payload)
        return structure_mapper.container_from(data, "embed", self._settings.wiki_url)

    def list_database_fields(self, database_id: str, *, limit: int = 25, cursor: str = "") -> Chunk[DatabaseField]:
        from . import map_structure as structure_mapper

        data = self._call("GET", f"{V2}/databases/{quote(database_id)}/fields?{query(limit=limit, cursor=cursor)}")
        return Chunk([structure_mapper.field_from(item) for item in results_of(data)], _more(data))

    def list_database_views(self, database_id: str, *, limit: int = 25, cursor: str = "") -> Chunk[DatabaseView]:
        from . import map_structure as structure_mapper

        data = self._call("GET", f"{V2}/databases/{quote(database_id)}/views?{query(limit=limit, cursor=cursor)}")
        return Chunk([structure_mapper.view_from(item) for item in results_of(data)], _more(data))

    def list_database_entries(self, database_id: str, *, limit: int = 25, cursor: str = "") -> Chunk[DatabaseEntry]:
        from . import map_structure as structure_mapper

        data = self._call("GET", f"{V2}/databases/{quote(database_id)}/entries?{query(limit=limit, cursor=cursor)}")
        return Chunk([structure_mapper.entry_from(item) for item in results_of(data)], _more(data))
