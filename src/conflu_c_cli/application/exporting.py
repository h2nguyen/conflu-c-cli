"""Exporting pages to a folder of Markdown files, and an index, as a local mirror that people and tools can read."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..domain.errors import UsageError, ValidationError
from ..domain.frontmatter import render_front_matter
from ..domain.model import Page, parse_page_id, parse_space_key
from ..domain.naming import export_file_name
from ..domain.privacy import redact_text
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
    """A whole space, or one page with everything below it."""

    def __init__(self, gateway: ConfluenceGateway, files: Files, clock: Clock, settings: Settings) -> None:
        self._gateway = gateway
        self._files = files
        self._clock = clock
        self._settings = settings

    def _space_pages(self, space_id: str) -> tuple[list[Page], bool]:
        return fetch_all(
            lambda cursor: self._gateway.list_pages(space_id=space_id, status="current", with_body=True, limit=EXPORT_PAGE_SIZE, cursor=cursor)
        )

    def _tree_pages(self, root_id: str, notes: list[str]) -> tuple[list[Page], bool]:
        nodes, truncated = fetch_all(lambda cursor: self._gateway.list_descendants(root_id, depth=MAX_TREE_DEPTH, limit=250, cursor=cursor))
        if any(node.depth >= MAX_TREE_DEPTH for node in nodes):
            notes.append(f"The tree is {MAX_TREE_DEPTH} levels deep or more; pages below that level were not exported.")
        ids = [root_id] + [node.id for node in nodes if node.type == "page"]
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
        return pages, truncated

    def execute(
        self,
        *,
        out_dir: str,
        space: str = "",
        root: str = "",
        body_format: str = "markdown",
        dry_run: bool = False,
        force: bool = False,
    ) -> ExportResult:
        check_format(body_format, INPUT_FORMATS)
        if space and root:
            raise UsageError("Use either --space or --page, not both.")
        notes: list[str] = []
        key, root_id = "", ""
        if root:
            root_id = parse_page_id(root)
            top = self._gateway.get_page(root_id, with_body=False)
            key = top.space_key
            pages, truncated = self._tree_pages(root_id, notes)
        else:
            chosen = space or self._settings.space
            if not chosen:
                raise UsageError("Nothing to export.", hint="Pass --space KEY (or run `conflu use KEY`), or --page ID for a page and its descendants.")
            target = self._gateway.get_space(parse_space_key(chosen))
            key = target.key
            pages, truncated = self._space_pages(target.id)
        if not pages:
            raise ValidationError("There are no pages to export.")
        extension = ".md" if body_format == "markdown" else ".xml"
        above = [redact_text(ref.title) for ref in self._gateway.list_ancestors(root_id)] if root_id else []
        by_id = {page.id: page for page in pages}

        def path_of(page: Page) -> str:
            titles: list[str] = []
            seen = {page.id}
            parent = by_id.get(page.parent_id)
            while parent is not None and parent.id not in seen:
                titles.append(redact_text(parent.title))
                seen.add(parent.id)
                parent = by_id.get(parent.parent_id)
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
                    "space": key or page.space_key,
                    "parent": page.parent_id,
                    "version": str(page.version_number or ""),
                    "updated": page.updated,
                    "url": page.url,
                    "path": path_of(page),
                    "lossy": ", ".join(dropped),
                }
                self._files.write_text(path, render_front_matter(meta) + "\n" + text + "\n")
            else:
                self._files.write_text(path, text + "\n")
        index: dict[str, Any] = {
            "exportedAt": self._clock.now().isoformat(timespec="seconds"),
            "space": key,
            "root": root_id,
            "format": body_format,
            "pages": [
                {"id": item.id, "title": item.title, "parentId": item.parent_id, "path": item.path, "file": item.file, "version": item.version, "updated": item.updated, "lossy": list(item.lossy)}
                for item in exported
            ],
        }
        if not dry_run:
            self._files.write_text(index_path, json.dumps(index, ensure_ascii=False, indent=1) + "\n")
        return ExportResult(out_dir, key, root_id, body_format, exported, index_path, dry_run, truncated, notes)
