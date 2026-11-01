"""Use cases that create or change pages."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.content import OTHER_CONTAINERS, describe, noun_of, parse_content_id
from ..domain.drafts import PageChanges, PageDraft, combine_body, normalize_labels, validate_title
from ..domain.errors import ConfluCliError, ConflictError, NotFoundError, UnavailableError, UsageError, ValidationError
from ..domain.model import Page, PageRef, parse_page_id, parse_space_key
from ..domain.payloads import create_page_payload, label_payload, title_payload, update_page_payload
from ..domain.privacy import page_address, redact_text
from ..domain.structure import hide_people_in_payload, move_message, move_payload, shown_key
from ..domain.timeutil import ensure_unchanged_since, ensure_version, parse_guard_time
from .blogposts import space_key as named_space_key
from .containers import PARENT, TARGET, ContainerResolver, Located, ensure_same_space, parent_named
from .pages import read_page
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
    where: PageRef | None = None  # the parent of a new page, or the target of a move, when one was named; its title is redacted
    redacted: bool = False  # `payload` is a copy without the people in the page body (what a move below a folder shows by default), not what is sent
    confirmed: bool | None = None  # a move: the page, as Confluence answers after it, is below the new parent; None for a dry run, a page that did not move, or no answer
    message: str = ""  # a move: what the person must know when it was made and could not be confirmed (the exit code stays 0, and a warning says it)


class CreatePage:
    def __init__(self, gateway: ConfluenceGateway, settings: Settings) -> None:
        self._gateway = gateway
        self._settings = settings
        self._parents = ContainerResolver(gateway, remember=True)  # a batch of files below one parent looks it up once

    def execute(self, draft: PageDraft, *, dry_run: bool = False) -> PageWrite:
        key = named_space_key(draft.space, self._settings)  # None is "not named": the current space; one that is empty is a mistake, never the current space
        parent_ref = parent_named(draft.parent)  # the same: None puts the page below the home page, an empty parent is a mistake
        if not key:
            raise UsageError("No space selected.", hint="Pass --space KEY or run `conflu use KEY`.")
        title = validate_title(draft.title)
        labels = normalize_labels(draft.labels)
        space = self._gateway.get_space(parse_space_key(key))
        parent_id, where = "", None
        if parent_ref is not None:
            parent = self._parents.resolve(parent_ref, PARENT)  # a page, a folder, a whiteboard, a database or a smart link
            ensure_same_space(parent, space, "A page")
            parent_id, where = parent.id, parent.ref()
        taken = self._gateway.list_pages(space_id=space.id, title=title, status="current", limit=1).items
        if taken:
            shown = shown_key(space.key, space.type)  # `create` has no --with-users: the key of a personal space is the account id of its owner
            raise ConflictError(
                f"A page titled '{title}' exists already in space {shown} (id {taken[0].id}).",
                hint=f"Change it with `conflu update {taken[0].id}`, or choose another title.",
                details={"pageId": taken[0].id, "space": shown, "title": title},
            )
        payload = create_page_payload(space.id, title, draft.body, parent_id)
        if dry_run:
            return PageWrite("created", None, payload, True, 0, 1, labels=labels, where=where)
        page = self._gateway.create_page(payload)
        if labels:
            try:
                self._gateway.add_labels(page.id, label_payload(labels))
            except ConfluCliError as error:
                raise type(error)(
                    f"The page was created (id {page.id}), but its labels were not added: {error.message}",
                    hint=f"Add them with `conflu label {page.id} --add ...`.",
                    details={**error.details, "pageId": page.id, "url": page_address(page.url, page.id)},
                ) from error
        return PageWrite("created", page, payload, False, 0, page.version_number or 1, labels=labels, where=where)


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
        if_unchanged_since: str | None = None,
        force: bool = False,
        with_users: bool = False,
    ) -> PageWrite:
        page_id = parse_page_id(ref)
        if changes.is_empty():
            raise ValidationError("No changes given.", hint="Pass --title, or a body with --body or --file.")
        if if_unchanged_since is not None:
            parse_guard_time(if_unchanged_since)  # an empty or unreadable value is an error that names the option, refused before anything is asked, in a dry run too
        page = read_page(self._gateway, page_id, with_body=changes.body is not None)  # an id that is a folder or a blog post says what it is
        if page.status not in ("current", "draft"):
            raise ValidationError(f"Page {page_id} is {page.status or 'not current'} and is not changed.", hint="Restore it in Confluence first.")
        current_version = page.version_number
        # Atlassian: the new version number is the current one plus one, "unless you are updating the status to 'draft'
        # which requires a version number of 1".
        next_version = 1 if page.status == "draft" else current_version + 1
        if if_version is not None:
            ensure_version(page_id, current_version, if_version)
        if if_unchanged_since is not None:  # an empty value is an error (`parse_timestamp` refuses it), never "no guard"
            ensure_unchanged_since(page_id, page.updated, if_unchanged_since)
        title = validate_title(changes.title) if changes.title is not None else page.title
        lost: tuple[str, ...] = ()
        new_body: str | None = None
        if changes.body is not None:
            if page.body is None:  # the answer had no body: adding to it, or replacing it, would be done blind
                raise UnavailableError(
                    f"Confluence answered without the body of page {page_id}, so the body is not changed.",
                    hint="Read the page again with `conflu page --format storage`; if it keeps happening, tell Confluence's administrator.",
                )
            current_body = page.body
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
            shown = payload if with_users else hide_people_in_payload(payload)  # what is sent is `payload`; what is printed does not name the people in it
            if dry_run:
                return PageWrite("updated", page, shown, True, current_version, next_version, redacted=shown != payload)
            updated = self._gateway.update_title(page_id, payload)
            return PageWrite("updated", updated, shown, False, current_version, updated.version_number or next_version, redacted=shown != payload)
        payload = update_page_payload(page_id, title, new_body, next_version, changes.message, page.status)
        shown = payload if with_users else hide_people_in_payload(payload)  # an append or a prepend sends the whole body, mentions included
        if dry_run:
            return PageWrite("updated", page, shown, True, current_version, next_version, lost, redacted=shown != payload)
        updated = self._gateway.update_page(page_id, payload)
        return PageWrite("updated", updated, shown, False, current_version, updated.version_number or next_version, lost, redacted=shown != payload)


class MovePage:
    """Moves a page below, before or after another page (the v1 call, which saves no version), or below a folder, a whiteboard, a database or a
    smart link (the v2 call that saves the page again, as the next version, with a new parent)."""

    def __init__(self, gateway: ConfluenceGateway) -> None:
        self._gateway = gateway
        self._targets = ContainerResolver(gateway)

    def execute(
        self,
        ref: str,
        to: str,
        *,
        position: str = "append",
        dry_run: bool = False,
        if_version: int | None = None,
        if_unchanged_since: str | None = None,
        with_users: bool = False,
    ) -> PageWrite:
        page_id, target_id = parse_content_id(ref), parse_content_id(to)
        if if_unchanged_since is not None:
            parse_guard_time(if_unchanged_since)  # an empty value is an error naming the option, never "no guard": refused before anything is asked, in a dry run too
        if position not in POSITIONS:
            raise UsageError(f"Unknown position: {position}", hint=f"Use one of: {', '.join(POSITIONS)}.")
        if page_id == target_id:
            raise ValidationError("A page cannot be moved next to or below itself.")
        page = self._read_page(page_id)
        target = self._targets.resolve(target_id, TARGET)  # a page is asked for first: the request is the one that it always was
        if target.page is not None:
            return self._beside_or_below_page(page, target, position, dry_run, if_version, if_unchanged_since)
        return self._below_container(page, target, position, dry_run, if_version, if_unchanged_since, with_users)

    def _read_page(self, page_id: str) -> Page:
        try:
            return self._gateway.get_page(page_id, with_body=False)
        except NotFoundError as error:
            try:
                kind = self._gateway.content_types([page_id]).get(page_id)
            except ConfluCliError:
                raise error from None  # the second look only explains; when it cannot be made the first answer stands (exit code 4)
            if kind is None or kind == "page":
                raise
            if kind in {item.name for item in OTHER_CONTAINERS}:
                raise ValidationError(
                    f"{page_id} is {describe(kind)}, and the API has no call to move {describe(kind)}.",
                    hint="Only a page can be moved with this command. A folder, a whiteboard, a database or a smart link is moved in the browser.",
                    details={"id": page_id, "type": kind},
                ) from error
            raise ValidationError(
                f"{page_id} is {describe(kind)}, which cannot be moved: only a page can.", details={"id": page_id, "type": kind}
            ) from error

    @staticmethod
    def _guard(page: Page, if_version: int | None, if_unchanged_since: str | None) -> None:
        if if_version is not None:
            ensure_version(page.id, page.version_number, if_version)
        if if_unchanged_since is not None:
            ensure_unchanged_since(page.id, page.updated, if_unchanged_since)

    @staticmethod
    def _confirmation(moved: Page, expected_parent: str) -> tuple[bool, str]:
        """Whether the page, as Confluence answers after the move, is below the new parent; when it is not, what the person must know."""
        if moved.parent_id == expected_parent:
            return True, ""
        return False, (
            f"Confluence accepted the move, but page {moved.id} sits below {moved.parent_id or 'no page'}, not below {expected_parent}. "
            f"Check it with `conflu page {moved.id} --json` (parentId)."
        )

    def _beside_or_below_page(
        self, page: Page, target: Located, position: str, dry_run: bool, if_version: int | None, if_unchanged_since: str | None
    ) -> PageWrite:
        if position != "append" and target.page is not None and not target.page.parent_id:
            # The document of `PUT /content/{pageId}/move/{position}/{targetId}`: "This API can move pages to the top level of a space. Top-level
            # pages ... do not show up in the page tree display. To avoid this, never use `before` or `after` positions when the `targetId` is a
            # top-level page."
            raise ValidationError(
                f"Page {target.id} is at the top level of its space: moving page {page.id} {position} it would put it at the top level too.",
                hint="Pages at the top level do not show in the page tree, and Confluence says never to move a page before or after one. "
                "Use --position append to move the page below it, or name a page that has a parent.",
                details={"id": page.id, "targetId": target.id, "position": position},
            )
        self._guard(page, if_version, if_unchanged_since)
        payload = {"pageId": page.id, "position": position, "targetId": target.id}
        if dry_run:
            return PageWrite("moved", page, payload, True, page.version_number, page.version_number, where=target.ref())
        self._gateway.move_page(page.id, position, target.id)
        # From here the page is moved: whatever goes wrong now must not read as a failure of the move, or somebody repeats it.
        try:
            moved = self._gateway.get_page(page.id, with_body=False)
        except ConfluCliError as error:
            message = (
                f"The page was moved, but it could not be read back: {redact_text(error.message.rstrip('. '))}. "
                f"Check it with `conflu page {page.id} --json` (parentId)."
            )
            return PageWrite("moved", page, payload, False, page.version_number, page.version_number, where=target.ref(), message=message)
        confirmed, message = self._confirmation(moved, target.id if position == "append" else target.parent_id)
        return PageWrite("moved", moved, payload, False, page.version_number, moved.version_number, where=target.ref(), confirmed=confirmed, message=message)

    def _below_container(
        self, page: Page, target: Located, position: str, dry_run: bool, if_version: int | None, if_unchanged_since: str | None, with_users: bool
    ) -> PageWrite:
        if position != "append":
            raise UsageError(
                f"{describe(target.type).capitalize()} can only be a parent: the position among its children cannot be given.",
                hint="Leave out --position (append is the default), or move the page next to another page.",
            )
        if target.space_id and page.space_id and target.space_id != page.space_id:
            raise ValidationError(
                f"The target {noun_of(target.type)} {target.id} is not in the space of page {page.id}.", hint="A page moves within its space."
            )
        if page.status != "current":
            raise ValidationError(f"Page {page.id} is {page.status or 'not current'} and is not moved.", hint="Restore it in Confluence first.")
        if page.parent_id == target.id:
            return PageWrite("unchanged", page, None, dry_run, page.version_number, page.version_number, where=target.ref())
        if page.id in {ref.id for ref in self._gateway.list_container_ancestors(target.type, target.id)}:
            raise ValidationError(f"A page cannot be moved below one of its own descendants: {target.id} sits below page {page.id}.")
        current = self._gateway.get_page(page.id, with_body=True)  # the body goes back as it is; the version number of this read is the guard
        self._guard(current, if_version, if_unchanged_since)
        payload = move_payload(current, target.id, move_message(target.title))
        shown = payload if with_users else hide_people_in_payload(payload)  # what is sent is `payload`; what is printed does not name the people in the body
        version_from = current.version_number
        if dry_run:
            return PageWrite("moved", current, shown, True, version_from, version_from + 1, where=target.ref(), redacted=shown != payload)
        moved = self._gateway.update_page(current.id, payload)
        confirmed, message = self._confirmation(moved, target.id)
        return PageWrite(
            "moved", moved, shown, False, version_from, moved.version_number or version_from + 1, where=target.ref(), redacted=shown != payload, confirmed=confirmed, message=message
        )
