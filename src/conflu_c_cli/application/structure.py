"""Use cases around folders, whiteboards, databases and smart links, and where content sits in the tree."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from ..domain.content import OTHER_CONTAINERS, describe, noun_of, parse_content_id
from ..domain.errors import NotFoundError, UsageError
from ..domain.model import PageRef, TreeNode, User, parse_space_key
from ..domain.privacy import hide_ref, redact_text
from ..domain.structure import (
    Container,
    DatabaseField,
    folder_payload,
    hide_people,
    shown_key,
    shown_value,
    smartlink_payload,
    validate_title,
    validate_url,
)
from ..domain.tree import arrange
from .blogposts import space_key as named_space_key
from .containers import PARENT, ROOT, ContainerResolver, ensure_same_space, not_the_kind, parent_named, space_key_of, with_titles
from .paging import PAGE_SIZE, ensure_users_allowed, fetch_all, name_users, named
from .ports import ConfluenceGateway, Diagnostics
from .refs import PAGE_REFERENCE, resolve_page_ref
from .services import Services
from .settings import Settings

LISTINGS = ("children", "fields", "views", "entries")  # the lists that `ShowContainer` can add; the last three are of a database
CONTAINER_KINDS = tuple(kind.name for kind in OTHER_CONTAINERS)


@dataclass
class TreeResult:
    root: PageRef
    space_key: str
    nodes: list[TreeNode]
    depth: int
    truncated: bool = False


class TreePages:
    """The tree below a page, or below a folder, a whiteboard, a database or a smart link."""

    def __init__(self, gateway: ConfluenceGateway, settings: Settings) -> None:
        self._gateway = gateway
        self._settings = settings
        self._roots = ContainerResolver(gateway)

    def execute(self, ref: str, *, depth: int = 3, space: str | None = None) -> TreeResult:
        if space is not None:
            named_space_key(space, self._settings)  # an empty --space is a mistake, also when the root is an id, which has no use for a space
        text = (ref or "").strip()
        root_id = resolve_page_ref(self._gateway, self._settings, text, space=space or "") if text.casefold().startswith(PAGE_REFERENCE) else parse_content_id(text)
        if not 1 <= depth <= 10:
            raise UsageError("--depth must be between 1 and 10.")
        root = self._roots.resolve(root_id, ROOT)
        space_key = shown_key(self._roots.space_key(root))  # `tree` has no --with-users: the key of a personal space is the account id of its owner
        if root.container is None:
            nodes, truncated = fetch_all(lambda cursor: self._gateway.list_descendants(root.id, depth=depth, limit=PAGE_SIZE, cursor=cursor))
        else:
            nodes, truncated = fetch_all(
                lambda cursor: self._gateway.list_container_descendants(root.type, root.id, depth=depth, limit=PAGE_SIZE, cursor=cursor)
            )
        clean = [replace(node, title=redact_text(node.title)) for node in nodes]
        return TreeResult(root.ref(), space_key, arrange(clean, root.id), depth, truncated)


@dataclass
class EntryRow:
    id: str
    values: dict[str, Any]  # what each cell shows (`domain.structure.shown_value`), by the id of the field


@dataclass
class ContainerView:
    container: Container  # without people unless they are shown
    users_shown: bool
    ancestors: list[PageRef] | None = None
    listing: str = ""  # which of LISTINGS was read; empty when none
    items: list[Any] = field(default_factory=list)  # of that list: TreeNode, DatabaseField, DatabaseView or EntryRow
    columns: list[DatabaseField] = field(default_factory=list)  # the fields that the values of the entries belong to
    next_cursor: str = ""
    truncated: bool = False


class ShowContainer:
    """One folder, whiteboard, database or smart link, and on request what is below it, the path to it and, for a database, its fields, views and entries."""

    def __init__(self, gateway: ConfluenceGateway, settings: Settings, diagnostics: Diagnostics) -> None:
        self._gateway = gateway
        self._settings = settings
        self._diagnostics = diagnostics

    def execute(
        self,
        kind: str,
        ref: str,
        *,
        listing: str = "",
        ancestors: bool = False,
        limit: int = 25,
        cursor: str = "",
        fetch_everything: bool = False,
        with_users: bool = False,
    ) -> ContainerView:
        if kind not in CONTAINER_KINDS:
            raise ValueError(f"Not a kind of content that this shows: {kind}")
        content_id = parse_content_id(ref)
        ensure_users_allowed(with_users, self._settings)
        if listing and listing not in LISTINGS:
            raise ValueError(f"Not a list: {listing}")
        if listing in ("fields", "views", "entries") and kind != "database":
            raise UsageError(f"{describe(kind).capitalize()} has no {listing}.", hint="Only a database has fields, views and entries.")
        container = self._read(kind, content_id)
        container = replace(container, space_key=space_key_of(self._gateway, container))
        container = self._with_names(container) if with_users else hide_people(container)
        view = ContainerView(container, with_users)
        if ancestors:
            refs = with_titles(self._gateway, self._gateway.list_container_ancestors(kind, content_id))
            view.ancestors = refs if with_users else [hide_ref(item) for item in refs]
        if listing:
            self._list(view, kind, content_id, listing, limit, cursor, fetch_everything)
        return view

    def _read(self, kind: str, content_id: str) -> Container:
        try:
            return self._gateway.get_container(kind, content_id)
        except NotFoundError as error:
            raise not_the_kind(self._gateway, content_id, kind, error) from error

    def _with_names(self, container: Container) -> Container:
        """The container with the names of the people who made it (best effort: a failed lookup leaves the account ids)."""
        saved_by = container.version.author if container.version else None
        known = name_users(self._gateway, self._diagnostics, [container.author, container.owner, saved_by])
        version = replace(container.version, author=named(saved_by, known)) if container.version else None
        return replace(container, author=named(container.author, known), owner=named(container.owner, known), version=version)

    def _list(self, view: ContainerView, kind: str, content_id: str, listing: str, limit: int, cursor: str, everything: bool) -> None:
        reads = {
            "children": lambda next_cursor, size: self._gateway.list_children(kind, content_id, limit=size, cursor=next_cursor),
            "fields": lambda next_cursor, size: self._gateway.list_database_fields(content_id, limit=size, cursor=next_cursor),
            "views": lambda next_cursor, size: self._gateway.list_database_views(content_id, limit=size, cursor=next_cursor),
            "entries": lambda next_cursor, size: self._gateway.list_database_entries(content_id, limit=size, cursor=next_cursor),
        }
        read = reads[listing]
        if everything:
            items, view.truncated = fetch_all(lambda next_cursor: read(next_cursor, PAGE_SIZE))
        else:
            chunk = read(cursor, limit)
            items, view.next_cursor = chunk.items, chunk.cursor
        view.listing = listing
        clean = (lambda text: text) if view.users_shown else redact_text
        if listing == "children":
            view.items = [replace(node, title=clean(node.title)) for node in items]
        elif listing == "fields":
            view.items = [self._field(item, clean) for item in items]
        elif listing == "views":
            view.items = [replace(item, name=clean(item.name)) for item in items]
        else:
            view.columns, view.items = self._entries(content_id, items, view.users_shown, clean)

    @staticmethod
    def _field(item: DatabaseField, clean: Any) -> DatabaseField:
        return replace(item, name=clean(item.name), description=clean(item.description), options=tuple(clean(option) for option in item.options))

    def _entries(self, database_id: str, entries: list[Any], users_shown: bool, clean: Any) -> tuple[list[DatabaseField], list[EntryRow]]:
        """The entries as rows of shown values, with the fields that name the cells (all of them, read once)."""
        fields, _ = fetch_all(lambda next_cursor: self._gateway.list_database_fields(database_id, limit=PAGE_SIZE, cursor=next_cursor))
        columns = [self._field(item, clean) for item in fields]
        names: dict[str, User] | None = None
        if users_shown:
            ids = [User(account_id=account) for entry in entries for value in entry.values.values() if value.type == "user" for account in value.value or []]
            names = name_users(self._gateway, self._diagnostics, ids)
        rows = []
        for entry in entries:
            order = [column.id for column in columns if column.id in entry.values] + [key for key in entry.values if key not in {column.id for column in columns}]
            rows.append(EntryRow(entry.id, {key: shown_value(entry.values[key], names) for key in order}))
        return columns, rows


@dataclass
class ContainerWrite:
    """What `folder-create` and `smartlink-create` did, or in a dry run would do."""

    action: str  # created
    type: str  # folder | embed
    title: str
    space_key: str
    payload: dict[str, Any]
    dry_run: bool
    container: Container | None = None  # what Confluence made; None in a dry run
    parent: PageRef | None = None  # where it goes, when a parent was named; the title is redacted


class CreateContainer:
    """A new folder or smart link: below a page, a folder or any other container of the space, or at the top of the space."""

    def __init__(self, gateway: ConfluenceGateway, settings: Settings, kind: str) -> None:
        self._gateway = gateway
        self._settings = settings
        self._kind = kind
        self._parents = ContainerResolver(gateway)

    def execute(self, title: str, *, url: str = "", space: str | None = None, parent: str | None = None, dry_run: bool = False) -> ContainerWrite:
        what = noun_of(self._kind)
        key = named_space_key(space, self._settings)  # None is "not named": the current space; one that is empty is a mistake
        parent = parent_named(parent)
        if not key:
            raise UsageError("No space selected.", hint="Pass --space KEY or run `conflu use KEY`.")
        title = validate_title(title, what)
        address = validate_url(url) if self._kind == "embed" else ""
        chosen = self._gateway.get_space(parse_space_key(key))
        parent_id, where = "", None
        if parent is not None:
            found = self._parents.resolve(parent, PARENT)
            ensure_same_space(found, chosen, f"A {what}")
            parent_id, where = found.id, found.ref()
        # Confluence does not forbid two folders of one title (nor two smart links), and no call lists the folders of a space: a dry run
        # cannot know whether the title is taken, and nothing here looks.
        payload = folder_payload(chosen.id, title, parent_id) if self._kind == "folder" else smartlink_payload(chosen.id, title, address, parent_id)
        shown = shown_key(chosen.key, chosen.type)  # what is printed of the space: the key of a personal space is the account id of its owner
        if dry_run:
            return ContainerWrite("created", self._kind, title, shown, payload, True, parent=where)
        made = self._gateway.create_folder(payload) if self._kind == "folder" else self._gateway.create_smartlink(payload)
        return ContainerWrite("created", self._kind, title, shown, payload, False, made, where)


@dataclass
class StructureUseCases:
    """The use cases of the area, reached as `app.structure.<name>`."""

    show: ShowContainer
    create_folder: CreateContainer
    create_smartlink: CreateContainer


def build(services: Services) -> StructureUseCases:
    return StructureUseCases(
        show=ShowContainer(services.gateway, services.settings, services.diagnostics),
        create_folder=CreateContainer(services.gateway, services.settings, "folder"),
        create_smartlink=CreateContainer(services.gateway, services.settings, "embed"),
    )
