"""The routes of the mock Confluence for the content properties of pages and other content. `MockConfluence` asks them before its own routes (see mock_extensions.py).

Every kind of content that has properties has them in a collection of its own (`/pages/{id}/properties`, `/blogposts/...`, `/folders/...`, `/whiteboards/...`,
`/databases/...`, `/embeds/...`, `/attachments/...`, `/comments/...`): the list (`key`, `sort`, `cursor`, `limit`), the creation (HTTP 400 when the key is there
already) and the change of one property, which needs the next version number (HTTP 409 otherwise). A property is `{id, key, value, version{createdAt, message,
number, minorEdit, authorId}}` and its value is any JSON, at most 32 KiB. No call deletes one (the mock answers HTTP 405 to a DELETE, as for all of v2).

The ids 7300 to 7399 belong to this area; a property that is created gets the next id from 7313 on. The content that holds them is what the mock knows
(a page of `mock.pages`, an attachment, a comment) or what is registered in `mock.content_kinds` (the blog post 7390, the folder 7391, the whiteboard 7392, the
database 7393 and the smart link 7394 of this area). The mock starts with (the same as `fakes_properties.py` holds):

    page 2002        7301 editor = "v2"; 7302 content-appearance-published = "full-width" (version 2); 7303 team.review = an object with people in it (version 3)
    page 2003        7304 inventory = an object that is longer than 4000 characters as compact JSON
    page 2005        none
    blog post 7390   7305 audience        folder 7391   7306 owner-team        whiteboard 7392   7307 board-state
    database 7393    7308 schema          smart link 7394   7309 link-checked
    attachment att5001   7310 ocr         footer comment 4001   7311 bot.seen         inline comment 4003   7312 bot.seen

`raw_answers` holds bytes that the next lists answer with, as they are: a value that nests too deeply for the interpreter cannot be written by `json.dumps`.
"""
from __future__ import annotations

import json
from typing import Any

from .mock_base import RequestError, Routes

ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"  # the user of the token of the mock
KINDS = {"blogposts": "blogpost", "folders": "folder", "whiteboards": "whiteboard", "databases": "database", "embeds": "embed"}
COLLECTIONS = ("pages", "blogposts", "folders", "whiteboards", "databases", "embeds", "attachments", "comments")
HOLDERS = {"7390": "blogpost", "7391": "folder", "7392": "whiteboard", "7393": "database", "7394": "embed"}
MAX_VALUE_BYTES = 32 * 1024
FIRST_NEW_ID = 7313
LAST_NEW_ID = 7399
SORTS = {"key", "-key"}


class PropertiesRoutes(Routes):
    def __init__(self, mock: Any) -> None:
        super().__init__(mock)
        self.store: dict[tuple[str, str], list[dict[str, Any]]] = {}  # (collection, id of the content) -> its properties
        self.saved: list[tuple[str, str, str, int]] = []  # (collection, id of the content, key, version) of every creation and change that was saved
        self.raw_answers: list[bytes] = []
        self._next = FIRST_NEW_ID
        if mock.populated:
            self._seed()

    # -- the data --------------------------------------------------------------------------------

    def add_property(self, collection: str, holder_id: str, key: str, value: Any, *, version: int = 1, created: str = "") -> str:
        """A property on content, for a test to set up (and its id)."""
        if collection not in COLLECTIONS or not self._exists(collection, holder_id):
            raise KeyError((collection, holder_id))
        property_id = self._new_id()
        self.store.setdefault((collection, holder_id), []).append(
            {"id": property_id, "key": key, "value": value, "version": self._version(version, created or self.mock._tick())}
        )
        return property_id

    def _new_id(self) -> str:
        if self._next > LAST_NEW_ID:
            raise RequestError(500, "The mock has no id left", f"This mock hands out the ids {FIRST_NEW_ID} to {LAST_NEW_ID} for new properties")
        self._next += 1
        return str(self._next - 1)

    @staticmethod
    def _version(number: int, created: str, message: str = "") -> dict[str, Any]:
        return {"createdAt": created, "message": message, "number": number, "minorEdit": False, "authorId": ACCOUNT}

    def _seed(self) -> None:
        self.mock.content_kinds.update({holder: kind for holder, kind in HOLDERS.items() if holder not in self.mock.content_kinds})
        review = {"status": "open", "reviewer": {"accountId": ACCOUNT, "displayName": "Alex Example"}, "owners": [ACCOUNT], "note": "Ask alex@example.com"}
        inventory = {"items": [f"item-{number:03d}" for number in range(400)]}
        rows = (
            ("pages", "2002", "7301", "editor", "v2", 1, "2026-10-01T08:00:00.000Z"),
            ("pages", "2002", "7302", "content-appearance-published", "full-width", 2, "2026-10-05T08:00:00.000Z"),
            ("pages", "2002", "7303", "team.review", review, 3, "2026-10-10T09:00:00.000Z"),
            ("pages", "2003", "7304", "inventory", inventory, 1, "2026-10-01T08:00:00.000Z"),
            ("blogposts", "7390", "7305", "audience", ["all"], 1, "2026-10-01T08:00:00.000Z"),
            ("folders", "7391", "7306", "owner-team", "docs", 1, "2026-10-01T08:00:00.000Z"),
            ("whiteboards", "7392", "7307", "board-state", {"zoom": 1.5}, 1, "2026-10-01T08:00:00.000Z"),
            ("databases", "7393", "7308", "schema", {"v": 2}, 1, "2026-10-01T08:00:00.000Z"),
            ("embeds", "7394", "7309", "link-checked", True, 1, "2026-10-01T08:00:00.000Z"),
            ("attachments", "att5001", "7310", "ocr", {"lang": "en"}, 1, "2026-10-01T08:00:00.000Z"),
            ("comments", "4001", "7311", "bot.seen", False, 1, "2026-10-01T08:00:00.000Z"),
            ("comments", "4003", "7312", "bot.seen", True, 1, "2026-10-01T08:00:00.000Z"),
        )
        for collection, holder, property_id, key, value, version, created in rows:
            self.store.setdefault((collection, holder), []).append({"id": property_id, "key": key, "value": value, "version": self._version(version, created)})

    def _exists(self, collection: str, holder_id: str) -> bool:
        if collection == "pages":
            return holder_id in self.mock.pages
        if collection == "attachments":
            return holder_id in self.mock.attachments
        if collection == "comments":
            return holder_id in self.mock.comments
        return self.mock.content_kinds.get(holder_id) == KINDS[collection]

    # -- the routes ------------------------------------------------------------------------------

    def handle(self, handler: Any, method: str, path: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]], body: Any) -> bool:
        found = self.match(r"/api/v2/(" + "|".join(COLLECTIONS) + r")/([^/]+)/properties(?:/([^/]+))?", path)
        if found is None:
            return False
        collection, holder_id, property_id = found.groups()
        if (method, property_id is None) not in {("GET", True), ("POST", True), ("GET", False), ("PUT", False)}:
            return False
        if collection != "attachments" and not holder_id.isdigit():
            raise RequestError(400, "Invalid request parameter", f"{holder_id} is not an id: it must be an integer")
        if not self._exists(collection, holder_id):
            raise RequestError(404, "Not found", f"Content not found: {holder_id}", code="NOT_FOUND")
        items = self.store.setdefault((collection, holder_id), [])
        if property_id is None:
            if method == "GET":
                self._list(handler, collection, holder_id, items, query, query_pairs)
            else:
                self._create(handler, collection, holder_id, items, body)
            return True
        if not property_id.isdigit():
            raise RequestError(400, "Invalid request parameter", "property-id must be an integer")
        current = next((item for item in items if item["id"] == property_id), None)
        if current is None:
            raise RequestError(404, "Not found", f"Property not found: {property_id}", code="NOT_FOUND")
        if method == "PUT":
            self._change(handler, collection, holder_id, current, body)
        handler._reply_json(200, current)
        return True

    def _list(self, handler: Any, collection: str, holder_id: str, items: list[dict[str, Any]], query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        handler._require_known_query(query, {"key", "sort", "cursor", "limit"})
        sort = handler._single(query, "sort")
        if sort is not None and sort not in SORTS:
            raise RequestError(400, "Invalid request parameter", f"Unsupported value for sort: {sort}")
        limit = handler._parse_limit(query, default=25)
        offset = handler._parse_cursor(query)
        if self.raw_answers:
            handler._reply_bytes(200, self.raw_answers.pop(0), content_type="application/json")
            return
        key = handler._single(query, "key")
        found = sorted((item for item in items if key is None or item["key"] == key), key=lambda item: item["key"], reverse=sort == "-key")
        shown, links, headers = handler._apply_pagination(found, path=f"/api/v2/{collection}/{holder_id}/properties", query_pairs=query_pairs, offset=offset, limit=limit)
        handler._reply_json(200, {"results": shown, "_links": links}, headers)

    @staticmethod
    def _checked(data: dict[str, Any], allowed: set[str]) -> None:
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise RequestError(400, "Invalid request body", f"Unknown property: {unknown[0]}")
        if "value" not in data:
            raise RequestError(400, "Invalid request body", "value is required")
        if len(json.dumps(data["value"], separators=(",", ":"), ensure_ascii=False).encode("utf-8")) > MAX_VALUE_BYTES:
            raise RequestError(400, "Invalid request body", f"The value of a property holds at most {MAX_VALUE_BYTES // 1024} KiB")

    def _create(self, handler: Any, collection: str, holder_id: str, items: list[dict[str, Any]], body: Any) -> None:
        data = handler._require_object(body)
        self._checked(data, {"key", "value"})
        key = data.get("key")
        if not isinstance(key, str) or not 1 <= len(key) <= 255:
            raise RequestError(400, "Invalid request body", "key is required: a text of 1 to 255 characters")
        if any(item["key"] == key for item in items):
            raise RequestError(400, "Invalid request body", f"A property with the key {key} exists already")
        created = {"id": self._new_id(), "key": key, "value": data["value"], "version": self._version(1, self.mock._tick())}
        items.append(created)
        self.saved.append((collection, holder_id, key, 1))
        handler._reply_json(200, created)

    def _change(self, handler: Any, collection: str, holder_id: str, current: dict[str, Any], body: Any) -> None:
        data = handler._require_object(body)
        self._checked(data, {"key", "value", "version"})
        if data.get("key") != current["key"]:
            raise RequestError(400, "Invalid request body", "key must be the key of the property: it cannot be changed")
        version = data.get("version")
        number = version.get("number") if isinstance(version, dict) else None
        if not isinstance(number, int) or isinstance(number, bool):
            raise RequestError(400, "Invalid request body", "version.number is required and must be an integer")
        message = version.get("message", "")
        if not isinstance(message, str):
            raise RequestError(400, "Invalid request body", "version.message must be a text")
        held = current["version"]["number"]
        if number != held + 1:
            raise RequestError(409, "Conflict", f"Version conflict: the property is at version {held}, a change needs version {held + 1}, not {number}", code="CONFLICT")
        current["value"] = data["value"]
        current["version"] = self._version(number, self.mock._tick(), message)
        self.saved.append((collection, holder_id, current["key"], number))
