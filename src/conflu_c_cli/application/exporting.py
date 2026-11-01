"""Exporting pages to a folder of Markdown files, and an index, as a local mirror that people and tools can read."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..domain.content import describe
from ..domain.errors import UsageError, ValidationError
from ..domain.frontmatter import render_front_matter
from ..domain.model import Page, parse_space_key
from ..domain.naming import export_file_name
from ..domain.privacy import page_address, redact_text
from ..domain.structure import shown_key
from .blogposts import space_key as named_space_key
from .containers import ROOT, ContainerResolver, Located, named, with_titles
from .paging import fetch_all
from .ports import Clock, ConfluenceGateway, Files
from .rendering import INPUT_FORMATS, check_format, render_body
from .settings import Settings

INDEX_FILE = "index.json"
EXPORT_PAGE_SIZE = 50
MAX_TREE_DEPTH = 10


@dataclass
class ExportedPage:
    id: str
    title: str
    parent_id: str
    file: str
    version: int
    updated: str
    lossy: tuple[str, ...] = ()
    path: str = ""  # the parent pages from the top, within what was exported (and above the first page of a tree)


@dataclass
class ExportResult:
    directory: str
    space: str
    root: str
    format: str
    pages: list[ExportedPage]
    index_file: str
    dry_run: bool
    truncated: bool = False
    notes: list[str] = field(default_factory=list)


class ExportPages:
    """A whole space, or one page, or one folder (or whiteboard, database, smart link), with everything below it."""

    def __init__(self, gateway: ConfluenceGateway, files: Files, clock: Clock, settings: Settings) -> None:
        self._gateway = gateway
        self._files = files
        self._clock = clock
        self._settings = settings
        self._roots = ContainerResolver(gateway)

    def _space_pages(self, space_id: str) -> tuple[list[Page], bool]:
        return fetch_all(
            lambda cursor: self._gateway.list_pages(space_id=space_id, status="current", with_body=True, limit=EXPORT_PAGE_SIZE, cursor=cursor)
        )

    def _tree_pages(self, top: Located, notes: list[str]) -> tuple[list[Page], bool, dict[str, tuple[str, str]]]:
        """The pages below the root, the root itself when it is a page, and what is below it that is no page: `(title, parent id)` by id, so
        that the path of a page can name the folder it sits in."""
        if top.container is None:
            read = lambda cursor: self._gateway.list_descendants(top.id, depth=MAX_TREE_DEPTH, limit=250, cursor=cursor)  # noqa: E731
        else:
            read = lambda cursor: self._gateway.list_container_descendants(top.type, top.id, depth=MAX_TREE_DEPTH, limit=250, cursor=cursor)  # noqa: E731
            notes.append(f"{describe(top.type).capitalize()} is not a page: the pages below it are exported, and it is not.")
        nodes, truncated = fetch_all(read)
        if any(node.depth >= MAX_TREE_DEPTH for node in nodes):
            notes.append(f"The tree is {MAX_TREE_DEPTH} levels deep or more; pages below that level were not exported.")
        ids = ([top.id] if top.container is None else []) + [node.id for node in nodes if node.type == "page"]
        pages: list[Page] = []
        for start in range(0, len(ids), EXPORT_PAGE_SIZE):
            wanted = ids[start : start + EXPORT_PAGE_SIZE]
            found, _ = fetch_all(
                lambda cursor, wanted=wanted: self._gateway.list_pages(ids=wanted, status="current", with_body=True, limit=EXPORT_PAGE_SIZE, cursor=cursor)
            )
            pages.extend(found)
        missing = len(set(ids) - {page.id for page in pages})
        if missing:
            notes.append(f"{missing} pages could not be read (not current, or not visible to this account) and were left out.")
        return pages, truncated, {node.id: (redact_text(node.title), node.parent_id) for node in nodes if node.type != "page"}

    def _titles_above(self, top: Located) -> list[str]:
        """The titles from the top of the tree down to the parent of the root; for a root that is no page, down to the root itself, which no page of the export is."""
        if top.container is None:
            return [redact_text(ref.title) for ref in with_titles(self._gateway, self._gateway.list_ancestors(top.id))]
        above = with_titles(self._gateway, self._gateway.list_container_ancestors(top.type, top.id))
        return [redact_text(ref.title) for ref in above] + [redact_text(top.title)]

    def execute(
        self,
        *,
        out_dir: str,
        space: str | None = None,
        root: str | None = None,
        body_format: str = "markdown",
        dry_run: bool = False,
        force: bool = False,
    ) -> ExportResult:
        # An option that was given and is empty is a mistake, never "not given": an empty --page would export the whole current space, and an empty --out
        # would write into the folder that the command runs in. Nothing is asked and nothing is written, a dry run too.
        named(out_dir, "output folder", "Pass the folder to write into with --out DIR (`.` is the folder that you are in).")
        named_root = named(root, "page", "Pass the id or the address of a page, a folder, a whiteboard, a database or a smart link, or leave out --page to export a space.")
        if space is not None:
            named_space_key(space, self._settings)  # "The space is empty." for one that is
        check_format(body_format, INPUT_FORMATS)
        if space is not None and named_root is not None:
            raise UsageError("Use either --space or --page, not both.")
        notes: list[str] = []
        key, root_id, space_type = "", "", ""
        top: Located | None = None
        holders: dict[str, tuple[str, str]] = {}
        if named_root is not None:
            top = self._roots.resolve(named_root, ROOT)
            root_id = top.id
            key = self._roots.space_key(top)
            pages, truncated, holders = self._tree_pages(top, notes)
        else:
            chosen = space if space is not None else self._settings.space
            if not chosen:
                raise UsageError("Nothing to export.", hint="Pass --space KEY (or run `conflu use KEY`), or --page ID for a page and its descendants.")
            target = self._gateway.get_space(parse_space_key(chosen))
            key, space_type = target.key, target.type
            pages, truncated = self._space_pages(target.id)
        if not pages:
            raise ValidationError("There are no pages to export.")
        # The key of a personal space is the account id of its owner: the result, the files and the index have `[hidden]` for it, whoever typed it.
        # (`export` has no `--with-users`; a file with a `page_id` is imported by that id, and for one without it `import-md` takes `--space`.)
        space_label = shown_key(key, space_type)
        extension = ".md" if body_format == "markdown" else ".xml"
        above = self._titles_above(top) if top is not None else []
        by_id = {page.id: page for page in pages}

        def path_of(page: Page) -> str:
            titles: list[str] = []
            seen = {page.id}
            parent_id = page.parent_id
            while parent_id and parent_id not in seen:
                seen.add(parent_id)
                if parent_id in by_id:
                    titles.append(redact_text(by_id[parent_id].title))
                    parent_id = by_id[parent_id].parent_id
                elif parent_id in holders:
                    title, parent_id = holders[parent_id]
                    titles.append(title)
                else:
                    break
            if not titles and page.id == root_id:
                return " > ".join(above)
            return " > ".join([*(above if root_id else []), *reversed(titles)])

        planned: list[tuple[Page, str, str, tuple[str, ...]]] = []
        for page in sorted(pages, key=lambda item: (item.title.casefold(), item.id)):
            rendered = render_body(page.body or "", body_format, with_users=False)
            name = export_file_name(redact_text(page.title), page.id, extension)  # what the title says in the file, not more
            planned.append((page, self._files.join(out_dir, name), rendered.text, rendered.dropped))
        index_path = self._files.join(out_dir, INDEX_FILE)
        clashes = [path for _, path, _, _ in planned if self._files.exists(path)]
        if self._files.exists(index_path):
            clashes.append(index_path)
        if clashes and not force and not dry_run:
            raise ValidationError(f"{clashes[0]} exists already.", hint="Use --force to overwrite, or --out to choose another folder.")
        exported: list[ExportedPage] = []
        for page, path, text, dropped in planned:
            exported.append(
                ExportedPage(page.id, redact_text(page.title), page.parent_id, self._files.name(path), page.version_number, page.updated, dropped, path_of(page))
            )
            if dry_run:
                continue
            if body_format == "markdown":
                meta = {
                    "title": redact_text(page.title),
                    "page_id": page.id,
                    "space": space_label or shown_key(page.space_key),
                    "parent": page.parent_id,
                    "version": str(page.version_number or ""),
                    "updated": page.updated,
                    "url": page_address(page.url, page.id),  # the title is in the address too, and it is written redacted above
                    "path": path_of(page),
                    "lossy": ", ".join(dropped),
                }
                self._files.write_text(path, render_front_matter(meta) + "\n" + text + "\n")
            else:
                self._files.write_text(path, text + "\n")
        index: dict[str, Any] = {
            "exportedAt": self._clock.now().isoformat(timespec="seconds"),
            "space": space_label,
            "root": root_id,
            "format": body_format,
            "pages": [
                {"id": item.id, "title": item.title, "parentId": item.parent_id, "path": item.path, "file": item.file, "version": item.version, "updated": item.updated, "lossy": list(item.lossy)}
                for item in exported
            ],
        }
        if not dry_run:
            self._files.write_text(index_path, json.dumps(index, ensure_ascii=False, indent=1) + "\n")
        return ExportResult(out_dir, space_label, root_id, body_format, exported, index_path, dry_run, truncated, notes)
