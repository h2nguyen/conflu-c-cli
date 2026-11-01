"""The in-memory Confluence for the content properties of pages and other content: a mixin of `FakeGateway` (`_init_properties` sets up its state).

What it holds when a test starts (the ids 7300 to 7399 are the properties; what holds them is what the other tests know, and five pieces of content
of this area: 7390 is a blog post, 7391 a folder, 7392 a whiteboard, 7393 a database, 7394 a smart link; `content_types` knows them):

    page 2002        7301 editor = "v2"; 7302 content-appearance-published = "full-width" (version 2); 7303 team.review = an object with people in it (version 3)
    page 2003        7304 inventory = an object that is longer than 4000 characters as compact JSON
    page 2005        none
    blog post 7390   7305 audience        folder 7391   7306 owner-team        whiteboard 7392   7307 board-state
    database 7393    7308 schema          smart link 7394   7309 link-checked
    attachment att5001   7310 ocr         footer comment 4001   7311 bot.seen         inline comment 4003   7312 bot.seen

A property that a test creates gets the next of the ids from 7313 on.
"""
from __future__ import annotations

import dataclasses
from typing import Any

from conflu_c_cli.domain.errors import ConflictError, NotFoundError, RejectedError
from conflu_c_cli.domain.model import Chunk
from conflu_c_cli.domain.properties import ContentProperty, collection_of

HOLDERS = {"7390": "blogpost", "7391": "folder", "7392": "whiteboard", "7393": "database", "7394": "embed"}
FIRST_NEW_ID = 7313


class FakeProperties:
    def _init_properties(self) -> None:
        from .fakes import ACCOUNT

        self.content_kinds.update(HOLDERS)
        # The content that has no page-like record in the fake of its own area: the ids that hold properties, by what Confluence calls them.
        self.property_holders: dict[str, set[str]] = {"attachment": {"att5001", "att5002"}, "footer-comment": {"4001", "4002"}, "inline-comment": {"4003"}}
        self.property_store: dict[tuple[str, str], list[ContentProperty]] = {}
        self._next_property = FIRST_NEW_ID
        team_review = {
            "status": "open",
            "reviewer": {"accountId": ACCOUNT, "displayName": "Alex Example"},
            "owners": [ACCOUNT],
            "note": "Ask alex@example.com",
        }
        inventory = {"items": [f"item-{number:03d}" for number in range(400)]}
        seeds = [
            ("pages", "2002", ContentProperty("7301", "editor", 1, "v2", "2026-10-01T08:00:00.000Z")),
            ("pages", "2002", ContentProperty("7302", "content-appearance-published", 2, "full-width", "2026-10-05T08:00:00.000Z")),
            ("pages", "2002", ContentProperty("7303", "team.review", 3, team_review, "2026-10-10T09:00:00.000Z")),
            ("pages", "2003", ContentProperty("7304", "inventory", 1, inventory, "2026-10-01T08:00:00.000Z")),
            ("blogposts", "7390", ContentProperty("7305", "audience", 1, ["all"], "2026-10-01T08:00:00.000Z")),
            ("folders", "7391", ContentProperty("7306", "owner-team", 1, "docs", "2026-10-01T08:00:00.000Z")),
            ("whiteboards", "7392", ContentProperty("7307", "board-state", 1, {"zoom": 1.5}, "2026-10-01T08:00:00.000Z")),
            ("databases", "7393", ContentProperty("7308", "schema", 1, {"v": 2}, "2026-10-01T08:00:00.000Z")),
            ("embeds", "7394", ContentProperty("7309", "link-checked", 1, True, "2026-10-01T08:00:00.000Z")),
            ("attachments", "att5001", ContentProperty("7310", "ocr", 1, {"lang": "en"}, "2026-10-01T08:00:00.000Z")),
            ("comments", "4001", ContentProperty("7311", "bot.seen", 1, False, "2026-10-01T08:00:00.000Z")),
            ("comments", "4003", ContentProperty("7312", "bot.seen", 1, True, "2026-10-01T08:00:00.000Z")),
        ]
        for collection, holder, item in seeds:
            self.property_store.setdefault((collection, holder), []).append(item)

    # -- helpers ----------------------------------------------------------------------------

    def _property_holder(self, kind: str, content_id: str, verb: str) -> tuple[str, str]:
        """The collection and the id of the content that holds the properties; NotFoundError when there is no such content of that kind."""
        collection = collection_of(kind)
        if kind == "page":
            known = content_id in self.pages
        elif kind in self.property_holders:
            known = content_id in self.property_holders[kind]
        else:
            known = self.content_kinds.get(content_id) == kind
        if collection is None or not known:
            raise NotFoundError(f"Not found: {verb} /api/v2/{collection or kind}/{content_id}/properties")
        return collection, content_id

    # -- the port ---------------------------------------------------------------------------

    def list_properties(self, kind: str, content_id: str, *, key: str = "", limit: int = 25, cursor: str = "") -> Chunk[ContentProperty]:
        self._enter("list_properties", kind, content_id, key, limit, cursor)
        holder = self._property_holder(kind, content_id, "GET")
        found = [item for item in self.property_store.get(holder, []) if not key or item.key == key]
        return self._chunk(sorted(found, key=lambda item: item.key), cursor, limit)

    def create_property(self, kind: str, content_id: str, payload: dict[str, Any]) -> ContentProperty:
        self._enter("create_property", kind, content_id, payload)
        holder = self._property_holder(kind, content_id, "POST")
        key = payload.get("key")
        if not isinstance(key, str) or not key or "value" not in payload:
            raise RejectedError("Confluence refused the request (HTTP 400): a property needs a key and a value")
        if any(item.key == key for item in self.property_store.get(holder, [])):
            raise RejectedError(f"Confluence refused the request (HTTP 400): a property with the key {key} exists already")
        created = ContentProperty(str(self._next_property), key, 1, payload["value"], "2026-10-15T08:00:00.000Z")
        self._next_property += 1
        self.property_store.setdefault(holder, []).append(created)
        return created

    def update_property(self, kind: str, content_id: str, property_id: str, payload: dict[str, Any]) -> ContentProperty:
        self._enter("update_property", kind, content_id, property_id, payload)
        holder = self._property_holder(kind, content_id, "PUT")
        items = self.property_store.get(holder, [])
        current = next((item for item in items if item.id == property_id), None)
        if current is None:
            raise NotFoundError(f"Not found: PUT /api/v2/{holder[0]}/{content_id}/properties/{property_id}")
        number = (payload.get("version") or {}).get("number")
        if number != current.version + 1:
            raise ConflictError("Confluence reports a conflict (HTTP 409): the version number must be the current one plus one.")
        if payload.get("key") != current.key or "value" not in payload:
            raise RejectedError("Confluence refused the request (HTTP 400): the key must be the one of the property, and the value is needed")
        changed = dataclasses.replace(current, version=number, value=payload["value"], updated="2026-10-15T08:30:00.000Z")
        items[items.index(current)] = changed
        return changed
