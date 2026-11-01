"""The in-memory Confluence for folders, whiteboards, databases, smart links and where content sits in the tree: a mixin of `FakeGateway`
(`_init_structure` sets up its state).

What it holds when a test starts (ids 7000 to 7099 belong to this area; no page sits below any of it, so that the pages of the space stay as
the other tests know them: a test makes the pages it needs with `add_page_below`):

    7001 folder "Guides" at the root of ENG         7021 whiteboard "Architecture sketch"      (both below 7001)
    7011 folder "Runbooks"                          7041 database "Services", with fields, views and entries
    7061 smart link "Roadmap" (https://example.com/roadmap)
"""
from __future__ import annotations

import dataclasses
from typing import Any, Sequence

from conflu_c_cli.domain.content import OTHER_CONTAINERS, kind_named
from conflu_c_cli.domain.errors import NotFoundError, ValidationError
from conflu_c_cli.domain.model import Chunk, Page, PageRef, TreeNode, User, VersionInfo
from conflu_c_cli.domain.structure import Container, DatabaseEntry, DatabaseField, DatabaseView, FieldValue

CONTAINER_KINDS = {kind.name for kind in OTHER_CONTAINERS}


class FakeStructure:
    def _init_structure(self) -> None:
        # The ids of content that is no page, with what Confluence calls it (`folder`, `blogpost` ...). A feature area that adds
        # such content to the fake registers its ids here, so that `content_types` knows them.
        self.content_kinds: dict[str, str] = {}
        self.containers: dict[str, Container] = {}
        self.database_fields: dict[str, list[DatabaseField]] = {}
        self.database_views: dict[str, list[DatabaseView]] = {}
        self.database_entries: dict[str, list[DatabaseEntry]] = {}
        self.add_container("folder", "7001", "Guides")
        self.add_container("folder", "7011", "Runbooks", parent_id="7001")
        self.add_container("whiteboard", "7021", "Architecture sketch", parent_id="7001")
        self.add_container("database", "7041", "Services", parent_id="7001")
        self.add_container("embed", "7061", "Roadmap", parent_id="7001", embed_url="https://example.com/roadmap")
        self.database_fields["7041"] = [
            DatabaseField("name", "Name", "text", "What the service is called"),
            DatabaseField("tier", "Tier", "select", "", ("Gold", "Silver", "Bronze")),
            DatabaseField("owner", "Owner", "user"),
            DatabaseField("active", "Active", "checkbox"),
            DatabaseField("docs", "Docs", "hyperlink"),
        ]
        self.database_views["7041"] = [DatabaseView("view-all", "All services", "table"), DatabaseView("view-tier", "By tier", "board")]
        self.database_entries["7041"] = [
            DatabaseEntry("7051", "7041", {
                "name": FieldValue("text", "Billing"),
                "tier": FieldValue("select", ["Gold"]),
                "owner": FieldValue("user", ["5b10ac8d82e05b22cc7d4ef5"]),
                "active": FieldValue("checkbox", True),
                "docs": FieldValue("hyperlink", [{"url": "https://example.com/billing", "label": "Billing docs"}]),
            }),
            DatabaseEntry("7052", "7041", {
                "name": FieldValue("text", "Search"),
                "tier": FieldValue("select", ["Silver"]),
                "owner": FieldValue("user"),
                "active": FieldValue("checkbox", False),
                "docs": FieldValue("hyperlink"),
            }),
            DatabaseEntry("7053", "7041", {
                "name": FieldValue("text", "Contact alex@example.com"),
                "tier": FieldValue("select", ["Bronze"]),
                "owner": FieldValue("user", []),
                "active": FieldValue("checkbox"),
                "docs": FieldValue("hyperlink"),
            }),
        ]

    # -- what a test sets up ----------------------------------------------------------------

    def add_container(
        self, kind: str, container_id: str, title: str, *, parent_id: str = "", space_key: str = "ENG", embed_url: str = ""
    ) -> Container:
        """A folder, whiteboard, database or smart link, known to `content_types` as well."""
        from .fakes import ACCOUNT, BASE, CREATED

        space = self.spaces[space_key]
        item = Container(
            id=container_id,
            type=kind,
            title=title,
            status="current",
            space_id=space.id,
            space_key=space_key,
            parent_id=parent_id,
            parent_type=self._parent_type(parent_id) if parent_id else "",
            position=len(self._tree_children(parent_id)) if parent_id else 0,
            created=CREATED,
            version=VersionInfo(1, CREATED, "", False, User(ACCOUNT)),
            author=User(ACCOUNT),
            owner=User(ACCOUNT),
            url=f"{BASE}/spaces/{space_key}/{kind}/{container_id}",
            embed_url=embed_url,
            raw={"id": container_id, "title": title, "authorId": ACCOUNT, "ownerId": ACCOUNT, "version": {"number": 1, "authorId": ACCOUNT}},
        )
        self.containers[container_id] = item
        self.content_kinds[container_id] = kind
        return item

    def add_page_below(self, parent_id: str, page_id: str, title: str, *, body: str = "<p>Text.</p>", space_key: str = "ENG") -> Page:
        """A page below a page, a folder or any other container."""
        from .fakes import sample_page

        space = self.spaces[space_key]
        page = sample_page(page_id, title, space_id=space.id, space_key=space_key, parent_id=parent_id, body=body)
        page.parent_type = self._parent_type(parent_id)
        self.pages[page_id] = page
        return page

    # -- helpers shared with the page calls of the fake ------------------------------------

    def _parent_type(self, parent_id: str) -> str:
        """What a page below this id has as `parent_type`: the kind of the container, else a page."""
        return self.containers[parent_id].type if parent_id in self.containers else "page"

    def _tree_children(self, parent_id: str) -> list[tuple[str, str, str]]:
        """`(id, title, type)` of what sits directly below the id, pages and containers alike, in the order of their titles."""
        found = [(page.id, page.title, "page") for page in self.pages.values() if page.parent_id == parent_id]
        found += [(item.id, item.title, item.type) for item in self.containers.values() if item.parent_id == parent_id]
        return sorted(found, key=lambda entry: (entry[1], entry[0]))

    def _ancestor_refs(self, parent_id: str) -> list[PageRef]:
        """From the top of the tree down to this id, pages and containers alike."""
        chain: list[PageRef] = []
        seen: set[str] = set()
        while parent_id and parent_id not in seen:
            seen.add(parent_id)
            if parent_id in self.containers:
                holder = self.containers[parent_id]
                chain.append(PageRef(holder.id, holder.title, holder.type))
                parent_id = holder.parent_id
            else:
                page = self._page(parent_id)
                chain.append(PageRef(page.id, page.title, "page"))
                parent_id = page.parent_id
        return list(reversed(chain))

    def _container(self, kind: str, container_id: str) -> Container:
        item = self.containers.get(container_id)
        if kind not in CONTAINER_KINDS or item is None or item.type != kind:
            known = kind_named(kind)
            raise NotFoundError(f"Not found: GET /api/v2/{known.collection if known else kind}/{container_id}")
        return item

    def _holder_exists(self, kind: str, container_id: str) -> None:
        if kind == "page":
            self._page(container_id)
        else:
            self._container(kind, container_id)

    # -- the port ---------------------------------------------------------------------------

    def content_types(self, ids: Sequence[str]) -> dict[str, str | None]:
        self._enter("content_types", tuple(ids))
        found: dict[str, str | None] = {}
        for item in dict.fromkeys(str(value) for value in ids):
            found[item] = "page" if item in self.pages else self.content_kinds.get(item)
        return found

    def get_container(self, kind: str, container_id: str) -> Container:
        self._enter("get_container", kind, container_id)
        return dataclasses.replace(self._container(kind, container_id))

    def list_children(self, kind: str, container_id: str, *, limit: int = 25, cursor: str = "") -> Chunk[TreeNode]:
        self._enter("list_children", kind, container_id, limit, cursor)
        self._holder_exists(kind, container_id)
        nodes = [TreeNode(item_id, title, type_, container_id, 1, "current", position) for position, (item_id, title, type_) in enumerate(self._tree_children(container_id))]
        return self._chunk(nodes, cursor, limit)

    def list_container_descendants(self, kind: str, container_id: str, *, depth: int = 3, limit: int = 250, cursor: str = "") -> Chunk[TreeNode]:
        self._enter("list_container_descendants", kind, container_id, depth, limit, cursor)
        self._holder_exists(kind, container_id)
        found: list[TreeNode] = []
        level = [container_id]
        for current in range(1, depth + 1):
            following: list[str] = []
            for parent in level:
                for position, (item_id, title, type_) in enumerate(self._tree_children(parent)):
                    found.append(TreeNode(item_id, title, type_, parent, current, "current", position))
                    following.append(item_id)
            level = following
        return self._chunk(found, cursor, limit)

    def list_container_ancestors(self, kind: str, container_id: str) -> list[PageRef]:
        self._enter("list_container_ancestors", kind, container_id)
        self._holder_exists(kind, container_id)
        holder = self.pages[container_id].parent_id if kind == "page" else self.containers[container_id].parent_id
        return self._ancestor_refs(holder)

    def _create_container(self, kind: str, payload: dict[str, Any]) -> Container:
        space = next((space for space in self.spaces.values() if space.id == payload.get("spaceId")), None)
        if space is None:
            raise ValidationError("Unknown space")
        parent_id = payload.get("parentId") or ""
        if parent_id and parent_id not in self.pages and parent_id not in self.containers:
            raise ValidationError(f"Unknown parentId: {parent_id}")
        item = self.add_container(kind, self._new_id(), payload.get("title") or "Untitled", parent_id=parent_id, space_key=space.key, embed_url=payload.get("embedUrl", ""))
        return dataclasses.replace(item)

    def create_folder(self, payload: dict[str, Any]) -> Container:
        self._enter("create_folder", payload)
        return self._create_container("folder", payload)

    def create_smartlink(self, payload: dict[str, Any]) -> Container:
        self._enter("create_smartlink", payload)
        return self._create_container("embed", payload)

    def list_database_fields(self, database_id: str, *, limit: int = 25, cursor: str = "") -> Chunk[DatabaseField]:
        self._enter("list_database_fields", database_id, limit, cursor)
        self._container("database", database_id)
        return self._chunk(list(self.database_fields.get(database_id, [])), cursor, limit)

    def list_database_views(self, database_id: str, *, limit: int = 25, cursor: str = "") -> Chunk[DatabaseView]:
        self._enter("list_database_views", database_id, limit, cursor)
        self._container("database", database_id)
        return self._chunk(list(self.database_views.get(database_id, [])), cursor, limit)

    def list_database_entries(self, database_id: str, *, limit: int = 25, cursor: str = "") -> Chunk[DatabaseEntry]:
        self._enter("list_database_entries", database_id, limit, cursor)
        self._container("database", database_id)
        return self._chunk(list(self.database_entries.get(database_id, [])), cursor, limit)
