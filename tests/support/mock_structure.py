"""The routes of the mock Confluence for folders, whiteboards, databases, smart links and where content sits in the tree. `MockConfluence` asks
them before its own routes (see mock_extensions.py).

What a mock starts with (ids 7000 to 7099 belong to this area; no page sits below any of it, so that the pages of the space stay as the
other tests know them: a test makes the pages it needs, `mock.add_page("ENG", "Title", parent_id="7001")`):

    7001 folder "Guides" at the root of ENG         7021 whiteboard "Architecture sketch"      (both below 7001)
    7011 folder "Runbooks"                          7041 database "Services", with fields, views and entries
    7061 smart link "Roadmap" (https://example.com/roadmap)

What a request creates gets the next of the ids 7090 to 7099. The content is kept like a page (`mock.pages`): a dict with `versions`, so that
the code of the mock that walks the tree (children, descendants, ancestors, positions) treats a folder as it treats a page.
"""
from __future__ import annotations

from typing import Any

from .mock_base import RequestError, Routes

ACCOUNT_ID = "5b10ac8d82e05b22cc7d4ef5"
COLLECTIONS = {"folders": "folder", "whiteboards": "whiteboard", "databases": "database", "embeds": "embed"}
LABELS = {"folder": "Folder", "whiteboard": "Whiteboard", "database": "Database", "embed": "Smart Link"}
FIRST_NEW_ID, LAST_ID = 7090, 7099
DEPTHS = {str(depth) for depth in range(1, 11)}
SEEDED = "2026-10-01T08:00:00.000Z"


class StructureRoutes(Routes):
    def __init__(self, mock: Any) -> None:
        super().__init__(mock)
        self.items: dict[str, dict[str, Any]] = {}  # folders, whiteboards, databases and smart links, by id
        self.fields: dict[str, list[dict[str, Any]]] = {}
        self.views: dict[str, list[dict[str, Any]]] = {}
        self.entries: dict[str, list[dict[str, Any]]] = {}
        self._next = FIRST_NEW_ID
        if mock.populated:
            self._seed()

    # -- what the rest of the mock asks ----------------------------------------------------

    def item(self, content_id: str) -> dict[str, Any] | None:
        return self.items.get(content_id)

    def items_below(self, parent_id: str | None) -> list[dict[str, Any]]:
        return [item for item in self.items.values() if item["parentId"] == parent_id]

    def add(
        self, kind: str, content_id: str, title: str, parent_id: str | None, *, space_id: str = "1001", embed_url: str = "", created: str = SEEDED
    ) -> dict[str, Any]:
        """A folder, whiteboard, database or smart link; `mock.content_kinds` knows it as well."""
        item: dict[str, Any] = {
            "id": content_id,
            "type": kind,
            "spaceId": space_id,
            "title": title,
            "parentId": parent_id,
            "status": "current",
            "position": len([other for other in self.items.values() if other["parentId"] == parent_id]),
            "authorId": ACCOUNT_ID,
            "ownerId": ACCOUNT_ID,
            "createdAt": created,
            "versions": [{"number": 1, "createdAt": created, "message": "", "minorEdit": False, "authorId": ACCOUNT_ID}],
            "embedUrl": embed_url,
        }
        self.items[content_id] = item
        self.mock.content_kinds[content_id] = kind
        return item

    def _seed(self) -> None:
        self.add("folder", "7001", "Guides", None)
        self.add("folder", "7011", "Runbooks", "7001")
        self.add("whiteboard", "7021", "Architecture sketch", "7001")
        self.add("database", "7041", "Services", "7001")
        self.add("embed", "7061", "Roadmap", "7001", embed_url="https://example.com/roadmap")
        self.fields["7041"] = [
            {"id": "name", "name": "Name", "description": "What the service is called", "type": "text", "settings": {}},
            {"id": "tier", "name": "Tier", "description": None, "type": "select", "settings": {"options": [{"id": "o1", "label": "Gold"}, {"id": "o2", "label": "Silver"}, {"id": "o3", "label": "Bronze"}]}},
            {"id": "owner", "name": "Owner", "description": None, "type": "user", "settings": {}},
            {"id": "active", "name": "Active", "description": None, "type": "checkbox", "settings": {}},
            {"id": "docs", "name": "Docs", "description": None, "type": "hyperlink", "settings": {}},
        ]
        self.views["7041"] = [{"id": "view-all", "name": "All services", "type": "table"}, {"id": "view-tier", "name": "By tier", "type": "board"}]
        self.entries["7041"] = [
            {
                "id": "7051",
                "databaseId": "7041",
                "values": {
                    "name": {"type": "text", "plain": "Billing", "rich": None},
                    "tier": {"type": "select", "value": [{"id": "o1", "label": "Gold"}]},
                    "owner": {"type": "user", "value": [{"accountId": ACCOUNT_ID}]},
                    "active": {"type": "checkbox", "value": True},
                    "docs": {"type": "hyperlink", "value": [{"url": "https://example.com/billing", "label": "Billing docs"}]},
                },
            },
            {
                "id": "7052",
                "databaseId": "7041",
                "values": {
                    "name": {"type": "text", "plain": "Search", "rich": None},
                    "tier": {"type": "select", "value": [{"id": "o2", "label": "Silver"}]},
                    "owner": {"type": "user", "value": None},
                    "active": {"type": "checkbox", "value": False},
                    "docs": {"type": "hyperlink", "value": None},
                },
            },
            {
                "id": "7053",
                "databaseId": "7041",
                "values": {
                    "name": {"type": "text", "plain": "Contact alex@example.com", "rich": None},
                    "tier": {"type": "select", "value": [{"id": "o3", "label": "Bronze"}]},
                    "owner": {"type": "user", "value": []},
                    "active": {"type": "checkbox", "value": None},
                    "docs": {"type": "hyperlink", "value": None},
                },
            },
        ]

    # -- the routes ------------------------------------------------------------------------

    def handle(self, handler: Any, method: str, path: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]], body: Any) -> bool:
        if method == "POST" and path == "/api/v2/content/convert-ids-to-types":
            self._convert_ids_to_types(handler, body)
            return True
        created = self.match(r"/api/v2/(folders|whiteboards|databases|embeds)", path)
        if method == "POST" and created:
            self._create(handler, COLLECTIONS[created.group(1)], body)
            return True
        found = self.match(r"/api/v2/(folders|whiteboards|databases|embeds)/([^/]+)(?:/(ancestors|descendants|direct-children|fields|views|entries))?", path)
        if method != "GET" or not found:
            return False
        kind, part = COLLECTIONS[found.group(1)], found.group(3)
        if part in ("fields", "views", "entries") and kind != "database":
            return False
        item = self._lookup(kind, found.group(2))
        if part is None:
            handler._require_known_query(query, {"include-collaborators", "include-direct-children", "include-operations", "include-properties"})
            handler._reply_json(200, self._model(item))
        elif part == "ancestors":
            self._ancestors(handler, item, query)
        elif part == "descendants":
            self._descendants(handler, item, path, query, query_pairs)
        elif part == "direct-children":
            self._direct_children(handler, item, path, query, query_pairs)
        else:
            self._database_list(handler, item, part, path, query, query_pairs)
        return True

    def _lookup(self, kind: str, raw_id: str) -> dict[str, Any]:
        if not raw_id.isdigit():
            raise RequestError(400, "Invalid request parameter", f"The id of a {kind} must be numeric")
        item = self.items.get(raw_id)
        if item is None or item["type"] != kind:
            raise RequestError(404, "Not found", f"{LABELS[kind]} not found: {raw_id}", code="NOT_FOUND")
        return item

    def _model(self, item: dict[str, Any]) -> dict[str, Any]:
        version = item["versions"][-1]
        parent = item["parentId"]
        webui = f"/spaces/{self.mock.spaces[item['spaceId']]['key']}/{item['type']}/{item['id']}"
        model: dict[str, Any] = {
            "id": item["id"],
            "type": item["type"],
            "status": item["status"],
            "title": item["title"],
            "parentId": parent,
            "parentType": self.mock.content_kinds.get(parent, "page") if parent else None,
            "position": item["position"],
            "authorId": item["authorId"],
            "ownerId": item["ownerId"],
            "createdAt": item["createdAt"],
            "spaceId": item["spaceId"],
            "version": {key: version[key] for key in ("number", "createdAt", "message", "minorEdit", "authorId")},
            "_links": {"webui": webui, "base": self.mock.base_url},
        }
        if item["type"] == "whiteboard":
            model["_links"]["editui"] = f"{webui}?edit=true"
        if item["type"] == "embed" and item["embedUrl"]:
            model["embedUrl"] = item["embedUrl"]
        return model

    def _ancestors(self, handler: Any, item: dict[str, Any], query: dict[str, list[str]]) -> None:
        handler._require_known_query(query, {"limit"})
        limit = handler._parse_limit(query, default=25)
        chain = [{"id": ancestor["id"], "type": ancestor.get("type", "page")} for ancestor in self.mock._page_ancestors(item["id"])][-limit:]  # the nearest `limit`, from the top down (see the ancestors of a page)
        handler._reply_json(200, {"results": chain, "_links": {"base": self.mock.base_url}})

    def _descendants(self, handler: Any, item: dict[str, Any], path: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        handler._require_known_query(query, {"depth", "cursor", "limit"})
        depth = handler._single(query, "depth") or "2"
        if depth not in DEPTHS:
            raise RequestError(400, "Invalid request parameter", f"Unsupported value for depth: {depth}")
        offset, limit = handler._parse_cursor(query), handler._parse_limit(query, default=25)
        queue = [(child, 1) for child in self.mock._children(item["id"])]
        found: list[dict[str, Any]] = []
        while queue:
            current, level = queue.pop(0)
            found.append(handler._descendant_model(current, level))
            if level < int(depth):
                queue.extend((child, level + 1) for child in self.mock._children(current["id"]))
        shown, links, headers = handler._apply_pagination(found, path=path, query_pairs=query_pairs, offset=offset, limit=limit)
        handler._reply_json(200, {"results": shown, "_links": links}, headers)

    def _direct_children(self, handler: Any, item: dict[str, Any], path: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        handler._require_known_query(query, {"cursor", "limit", "sort"})
        offset, limit = handler._parse_cursor(query), handler._parse_limit(query, default=25)
        children = [
            {
                "id": child["id"],
                "status": child["status"],
                "title": child["title"],
                "type": child.get("type", "page"),
                "spaceId": child["spaceId"],
                "childPosition": child["position"],
            }
            for child in self.mock._children(item["id"])
        ]
        shown, links, headers = handler._apply_pagination(children, path=path, query_pairs=query_pairs, offset=offset, limit=limit)
        handler._reply_json(200, {"results": shown, "_links": links}, headers)

    def _database_list(self, handler: Any, item: dict[str, Any], part: str, path: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        """The fields, views and entries of a database: a page of them with the pagination of the Databases API (`meta`, `_links.next`)."""
        handler._require_known_query(query, {"limit", "cursor", "sort"} if part == "entries" else {"limit", "cursor"})
        offset, limit = handler._parse_cursor(query), handler._parse_limit(query, default=50)
        source = {"fields": self.fields, "views": self.views, "entries": self.entries}[part].get(item["id"], [])
        shown, links, headers = handler._apply_pagination(source, path=path, query_pairs=query_pairs, offset=offset, limit=limit)
        links["self"] = f"{self.mock.context_path}{path}"
        meta: dict[str, Any] = {"pageSize": min(limit, self.mock.page_cap), "hasMore": "next" in links}
        if offset:
            meta["cursor"] = str(offset)
        handler._reply_json(200, {"results": shown, "_links": links, "meta": meta}, headers)

    def _create(self, handler: Any, kind: str, body: Any) -> None:
        """`POST /folders` and its kin: the title need not be unique, and the parent may be a page or any other container of the same space."""
        data = handler._require_object(body)
        space_id = data.get("spaceId")
        if not isinstance(space_id, str):
            raise RequestError(400, "Invalid request body", "spaceId is required and must be a string")
        if space_id not in self.mock.spaces:
            raise RequestError(400, "Invalid request body", f"Unknown spaceId: {space_id}")
        title = data.get("title", "Untitled")
        if not isinstance(title, str) or not title.strip():
            raise RequestError(400, "Invalid request body", "title must be a non-empty string")
        parent_id = data.get("parentId")
        if parent_id is not None:
            holder = (self.mock.pages.get(parent_id) or self.items.get(parent_id)) if isinstance(parent_id, str) else None
            if holder is None:
                raise RequestError(400, "Invalid request body", f"Unknown parentId: {parent_id}")
            if holder["spaceId"] != space_id:
                raise RequestError(400, "Invalid request body", "parentId must refer to content in the same space")
        embed_url = data.get("embedUrl", "")
        if kind == "embed" and not (isinstance(embed_url, str) and embed_url.startswith(("http://", "https://"))):
            raise RequestError(400, "Invalid request body", "embedUrl must be an http or https address")
        if self._next > LAST_ID:
            raise RequestError(500, "The mock has no id left", "This mock hands out the ids 7090 to 7099 for new folders, whiteboards, databases and smart links")
        content_id = str(self._next)
        self._next += 1
        item = self.add(kind, content_id, title, parent_id, space_id=space_id, embed_url=embed_url if kind == "embed" else "", created=self.mock._tick())
        item["position"] = len(self.mock._children(parent_id)) - 1  # the last of the children, whatever the kind of the others
        handler._reply_json(200, self._model(item))

    def _convert_ids_to_types(self, handler: Any, body: Any) -> None:
        """`POST /content/convert-ids-to-types`: the type of each id, null for one that does not exist or may not be seen. The mock knows the
        pages, the comments and `mock.content_kinds`, where a feature area registers the ids of its own kind of content."""
        document = handler._require_object(body)
        ids = document.get("contentIds")
        if not isinstance(ids, list) or not ids or len(ids) > 100 or not all(isinstance(item, (str, int)) and not isinstance(item, bool) for item in ids):
            raise RequestError(400, "Invalid request body", "contentIds must be a list of one to 100 ids")
        results: dict[str, str | None] = {}
        for raw in ids:
            item = str(raw)
            if item in self.mock.pages:
                results[item] = "page"
            elif item in self.mock.comments:
                results[item] = "inline-comment" if self.mock.comments[item]["kind"] == "inline" else "footer-comment"
            else:
                results[item] = self.mock.content_kinds.get(item)
        handler._reply_json(200, {"results": results})
