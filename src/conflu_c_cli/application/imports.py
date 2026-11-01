"""Importing pages from Markdown files: one file, or a folder of them."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.drafts import PageChanges, PageDraft, normalize_labels
from ..domain.errors import ConfluCliError, ValidationError
from ..domain.frontmatter import parse_markdown_page, split_list, take_title_heading
from ..domain.model import PageRef, parse_page_id, parse_space_key
from ..domain.privacy import HIDDEN, has_redaction_marker
from .blogposts import space_key as named_space_key
from .containers import parent_named
from .labels import ChangeLabels
from .ports import ConfluenceGateway, Files
from .rendering import storage_from_input
from .settings import Settings
from .writing import CreatePage, UpdatePage

MARKDOWN_PATTERN = "*.md"


@dataclass
class ImportOutcome:
    file: str
    action: str  # created | updated | unchanged | failed
    page_id: str = ""
    title: str = ""
    url: str = ""
    dry_run: bool = False
    message: str = ""
    payload: Any = None
    lost: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()  # the labels the import added; in a dry run, the ones it would add
    parent: PageRef | None = None  # a page that is created: what it goes below (a page, a folder ...), when a parent was named; the title is redacted


@dataclass
class BatchImport:
    outcomes: list[ImportOutcome] = field(default_factory=list)
    first_error: ConfluCliError | None = None

    def count(self, action: str) -> int:
        return sum(1 for outcome in self.outcomes if outcome.action == action)


class ImportMarkdown:
    """One Markdown file. With `page_id` in the front matter it updates that page; otherwise it looks for a page with
    the same title in the space and updates it, or creates the page."""

    def __init__(
        self,
        files: Files,
        gateway: ConfluenceGateway,
        settings: Settings,
        create: CreatePage,
        update: UpdatePage,
        labels: ChangeLabels,
    ) -> None:
        self._files = files
        self._gateway = gateway
        self._settings = settings
        self._create = create
        self._update = update
        self._labels = labels

    def named(self, space: str | None, parent: str | None) -> tuple[str, str | None]:
        """The space to import into when a file names none (the option, else the current space) and the parent, as they were given: None is "not named",
        and one that is empty is a mistake, also for a file that would be updated: a value that is no value is never a reason to go on."""
        return named_space_key(space, self._settings), parent_named(parent)

    def execute(self, path: str, *, space: str | None = None, parent: str | None = None, dry_run: bool = False, force: bool = False) -> ImportOutcome:
        current, parent = self.named(space, parent)
        if not self._files.exists(path) or self._files.is_dir(path):
            raise ValidationError(f"File not found: {path}")
        parsed = parse_markdown_page(self._files.read_text(path))
        meta, body = parsed.meta, parsed.body
        title = meta.get("title", "").strip()
        if not title:
            heading, rest = take_title_heading(body)
            if heading:
                title, body = heading, rest
        if title and has_redaction_marker(title):
            raise ValidationError(
                f"The title in {path} holds a placeholder that `export` writes in place of an e-mail address or a personal link: {title}",
                hint="Write the real title, or take the `title:` line out: a file with a `page_id` keeps the title that the page has.",
            )
        page_id = meta.get("page_id", "").strip()
        if not title and not page_id:
            raise ValidationError(
                f"{path} has no title.",
                hint="Write `title:` in the front matter, or start the Markdown with a # heading.",
            )
        storage = storage_from_input(body, "markdown")
        labels = split_list(meta.get("labels", ""))
        message = meta.get("message", "").strip() or f"Imported from {self._files.name(path)}"
        if page_id:
            return self._update_page(path, parse_page_id(page_id), title, storage, labels, message, dry_run, force)
        declared = meta.get("space") or ""
        # `export` writes [hidden] for the key of a personal space (it is the account id of its owner): a file that says so names no space, and --space applies
        key = (declared if declared != HIDDEN else "") or current
        if not key:
            raise ValidationError(
                f"{path} has no space and no current space is selected.",
                hint="Write `space:` in the front matter, pass --space KEY, or run `conflu use KEY`.",
            )
        target = self._gateway.get_space(parse_space_key(key))
        existing = self._gateway.list_pages(space_id=target.id, title=title, status="current", limit=1).items
        if existing:
            return self._update_page(path, existing[0].id, title, storage, labels, message, dry_run, force)
        draft = PageDraft(space=target.key, title=title, body=storage, parent=meta.get("parent") or parent, labels=labels)
        result = self._create.execute(draft, dry_run=dry_run)
        page = result.page
        return ImportOutcome(
            path, "created", page.id if page else "", title, page.url if page else "", dry_run, payload=result.payload, labels=tuple(result.labels), parent=result.where
        )

    def _update_page(
        self, path: str, page_id: str, title: str, storage: str, labels: list[str], message: str, dry_run: bool, force: bool
    ) -> ImportOutcome:
        wanted = normalize_labels(labels)  # a label Confluence would refuse is refused before anything is written
        changes = PageChanges(title=title or None, body=storage, from_markdown=True, message=message)
        result = self._update.execute(page_id, changes, dry_run=dry_run, force=force)
        added: tuple[str, ...] = ()
        if wanted:
            try:
                plan = self._labels.execute(page_id, add=wanted, remove=[], dry_run=dry_run)
            except ConfluCliError as error:
                if dry_run or result.action == "unchanged":
                    raise
                raise type(error)(
                    f"The page was updated (id {page_id}), but its labels were not added: {error.message}",
                    hint=f"Add them with `conflu label {page_id} --add ...`.",
                    details={**error.details, "pageId": page_id},
                ) from error
            added = tuple(plan.added)
        action = "updated" if result.action == "unchanged" and added else result.action  # a new label is a change too
        page = result.page
        return ImportOutcome(
            path,
            action,
            page_id,
            page.title if page else title,
            page.url if page else "",
            dry_run,
            payload=result.payload,
            lost=result.lost,
            labels=added,
        )


class ImportMarkdownDirectory:
    """Every `*.md` file of a folder (not its subfolders), in the order of their names."""

    def __init__(self, files: Files, importer: ImportMarkdown) -> None:
        self._files = files
        self._importer = importer

    def execute(
        self,
        directory: str,
        *,
        space: str | None = None,
        parent: str | None = None,
        dry_run: bool = False,
        force: bool = False,
        continue_on_error: bool = False,
    ) -> BatchImport:
        self._importer.named(space, parent)  # an empty --space or --parent is refused before any file is read, not file by file
        if not self._files.is_dir(directory):
            raise ValidationError(f"Not a folder: {directory}")
        paths = self._files.list_matching(directory, MARKDOWN_PATTERN)
        if not paths:
            raise ValidationError(f"No {MARKDOWN_PATTERN} files in {directory}.")
        batch = BatchImport()
        for path in paths:
            try:
                batch.outcomes.append(self._importer.execute(path, space=space, parent=parent, dry_run=dry_run, force=force))
            except ConfluCliError as error:
                batch.outcomes.append(ImportOutcome(path, "failed", dry_run=dry_run, message=error.message))
                if batch.first_error is None:
                    batch.first_error = error
                if not continue_on_error:
                    break
        return batch
