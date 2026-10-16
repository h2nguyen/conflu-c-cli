"""Use cases that create or change pages."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.drafts import PageChanges, PageDraft, combine_body, normalize_labels, validate_title
from ..domain.errors import ConfluCliError, ConflictError, UsageError, ValidationError
from ..domain.model import Page, parse_page_id, parse_space_key
from ..domain.payloads import create_page_payload, label_payload, title_payload, update_page_payload
from ..domain.timeutil import ensure_unchanged_since, ensure_version
from .ports import ConfluenceGateway
from .rendering import markdown_limits, markdown_round_trip
from .settings import Settings

POSITIONS = ("append", "before", "after")


@dataclass
class PageWrite:
    action: str  # created | updated | moved | unchanged
    page: Page | None  # the page after the write; None in a dry run of a creation
    payload: Any
    dry_run: bool
    version_from: int = 0
    version_to: int = 0
    lost: tuple[str, ...] = ()  # what a replacement from Markdown dropped from the old body (only with --force)
    labels: list[str] = field(default_factory=list)


class CreatePage:
    def __init__(self, gateway: ConfluenceGateway, settings: Settings) -> None:
        self._gateway = gateway
        self._settings = settings

    def execute(self, draft: PageDraft, *, dry_run: bool = False) -> PageWrite:
        key = draft.space or self._settings.space
        if not key:
            raise UsageError("No space selected.", hint="Pass --space KEY or run `conflu use KEY`.")
        title = validate_title(draft.title)
        labels = normalize_labels(draft.labels)
        space = self._gateway.get_space(parse_space_key(key))
        parent_id = ""
        if draft.parent:
            parent_id = parse_page_id(draft.parent)
            parent = self._gateway.get_page(parent_id, with_body=False)
            if parent.space_id and space.id and parent.space_id != space.id:
                raise ValidationError(
                    f"The parent page {parent_id} is not in space {space.key}.",
                    hint="A page is created in the space of its parent: pass that space, or another parent.",
                )
        taken = self._gateway.list_pages(space_id=space.id, title=title, status="current", limit=1).items
        if taken:
            raise ConflictError(
                f"A page titled '{title}' exists already in space {space.key} (id {taken[0].id}).",
                hint=f"Change it with `conflu update {taken[0].id}`, or choose another title.",
                details={"pageId": taken[0].id, "space": space.key, "title": title},
            )
        payload = create_page_payload(space.id, title, draft.body, parent_id)
        if dry_run:
            return PageWrite("created", None, payload, True, 0, 1, labels=labels)
        page = self._gateway.create_page(payload)
        if labels:
            try:
                self._gateway.add_labels(page.id, label_payload(labels))
            except ConfluCliError as error:
                raise type(error)(
                    f"The page was created (id {page.id}), but its labels were not added: {error.message}",
                    hint=f"Add them with `conflu label {page.id} --add ...`.",
                    details={**error.details, "pageId": page.id, "url": page.url},
                ) from error
        return PageWrite("created", page, payload, False, 0, page.version_number or 1, labels=labels)


class UpdatePage:
    def __init__(self, gateway: ConfluenceGateway) -> None:
        self._gateway = gateway

    def execute(
        self,
        ref: str,
        changes: PageChanges,
        *,
        dry_run: bool = False,
        if_version: int | None = None,
        if_unchanged_since: str = "",
        force: bool = False,
    ) -> PageWrite:
        page_id = parse_page_id(ref)
        if changes.is_empty():
            raise ValidationError("No changes given.", hint="Pass --title, or a body with --body or --file.")
        page = self._gateway.get_page(page_id, with_body=changes.body is not None)
        if page.status not in ("current", "draft"):
            raise ValidationError(f"Page {page_id} is {page.status or 'not current'} and is not changed.", hint="Restore it in Confluence first.")
        current_version = page.version_number
        # Atlassian: the new version number is the current one plus one, "unless you are updating the status to 'draft'
        # which requires a version number of 1".
        next_version = 1 if page.status == "draft" else current_version + 1
        if if_version is not None:
            ensure_version(page_id, current_version, if_version)
        if if_unchanged_since:
            ensure_unchanged_since(page_id, page.updated, if_unchanged_since)
        title = validate_title(changes.title) if changes.title is not None else page.title
        lost: tuple[str, ...] = ()
        new_body: str | None = None
        if changes.body is not None:
            current_body = page.body or ""
            new_body = combine_body(current_body, changes.body, changes.body_mode)
            if changes.body_mode == "replace" and changes.from_markdown:
                if markdown_round_trip(current_body) == new_body:
                    new_body = current_body  # the page already says what this Markdown says
                else:
                    lost = markdown_limits(current_body)
                    if lost and not force:
                        raise ValidationError(
                            f"Replacing the body with Markdown would lose what Markdown cannot say: {', '.join(lost)}.",
                            hint="Add text with --append or --prepend, give the body in storage format (--format storage), "
                            "or replace it anyway with --force.",
                            details={"lost": list(lost)},
                        )
            if new_body == current_body:
                new_body = None
        if title == page.title and new_body is None:
            return PageWrite("unchanged", page, None, dry_run, current_version, current_version)
        if new_body is None:
            payload: Any = title_payload(title, page.status)
            if dry_run:
                return PageWrite("updated", page, payload, True, current_version, next_version)
            updated = self._gateway.update_title(page_id, payload)
            return PageWrite("updated", updated, payload, False, current_version, updated.version_number or next_version)
        payload = update_page_payload(page_id, title, new_body, next_version, changes.message, page.status)
        if dry_run:
            return PageWrite("updated", page, payload, True, current_version, next_version, lost)
        updated = self._gateway.update_page(page_id, payload)
        return PageWrite("updated", updated, payload, False, current_version, updated.version_number or next_version, lost)


class MovePage:
    def __init__(self, gateway: ConfluenceGateway) -> None:
        self._gateway = gateway

    def execute(self, ref: str, to: str, *, position: str = "append", dry_run: bool = False) -> PageWrite:
        page_id, target_id = parse_page_id(ref), parse_page_id(to)
        if position not in POSITIONS:
            raise UsageError(f"Unknown position: {position}", hint=f"Use one of: {', '.join(POSITIONS)}.")
        if page_id == target_id:
            raise ValidationError("A page cannot be moved next to or below itself.")
        page = self._gateway.get_page(page_id, with_body=False)
        self._gateway.get_page(target_id, with_body=False)  # proves that the target exists
        payload = {"pageId": page_id, "position": position, "targetId": target_id}
        if dry_run:
            return PageWrite("moved", page, payload, True, page.version_number, page.version_number)
        self._gateway.move_page(page_id, position, target_id)
        moved = self._gateway.get_page(page_id, with_body=False)
        return PageWrite("moved", moved, payload, False, page.version_number, moved.version_number)
