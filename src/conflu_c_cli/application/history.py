"""Use cases around earlier versions of a page: the difference between two of them, and restoring one."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..domain.errors import ConfluCliError, NotFoundError, UsageError, ValidationError
from ..domain.history import Difference, check_context, check_version_number, compare, restore_payload
from ..domain.model import Page, parse_page_id
from ..domain.privacy import page_address, redact_text
from ..domain.timeutil import ensure_unchanged_since, ensure_version, parse_guard_time
from .pages import read_page
from .ports import ConfluenceGateway, Diagnostics
from .rendering import Body, render_body
from .services import Services


def read_version(gateway: ConfluenceGateway, page_id: str, number: int, newest: int) -> Page:
    """An earlier version of the page with its body; NotFoundError, with where to look, when the page has no such version."""
    hint = f"The page is at version {newest}. `conflu versions {page_id}` lists the versions it has."
    details = {"pageId": page_id, "version": number, "currentVersion": newest}
    if newest and number > newest:
        raise NotFoundError(f"Page {page_id} has no version {number}.", hint=hint, details=details)
    try:
        return gateway.get_page_version(page_id, number, with_body=True)
    except NotFoundError as error:
        raise NotFoundError(f"Page {page_id} has no version {number}.", hint=hint, details={**error.details, **details}) from error


def as_markdown(page: Page) -> Body:
    """The body of a version as the Markdown that a reader without the right to see people gets: what is compared and counted is never a person."""
    return render_body(page.body or "", "markdown", with_users=False)


@dataclass(frozen=True)
class VersionSide:
    """One of the two versions that are compared; the message and the title are free text, so they are redacted."""

    number: int
    created: str
    message: str
    title: str
    current: bool


def _side(page: Page, newest: int) -> VersionSide:
    version = page.version
    number = version.number if version else 0
    return VersionSide(number, version.created if version else "", redact_text(version.message) if version else "", redact_text(page.title), number == newest)


@dataclass(frozen=True)
class VersionDiff:
    page_id: str
    title: str  # of the page now
    from_side: VersionSide | None  # None: nothing to compare with (the page has one version only, or the version asked for is its first)
    to_side: VersionSide
    difference: Difference
    dropped: tuple[str, ...]  # what the Markdown of either version cannot say, so that the diff does not show it
    source_identical: bool  # the storage format is the same too, not only its Markdown
    note: str = ""
    nothing_before: bool = False  # the version asked for is the first one of a page that has more: nothing came before it, and nothing was compared

    @property
    def identical(self) -> bool:
        """The Markdown of the two versions reads the same: never said when nothing came before the version asked for."""
        return self.difference.identical and not self.nothing_before


class DiffVersions:
    def __init__(self, gateway: ConfluenceGateway) -> None:
        self._gateway = gateway

    def execute(self, ref: str, *, from_version: int | None = None, to_version: int | None = None, context: int = 3, max_chars: int = 0) -> VersionDiff:
        """The difference between two versions as Markdown: `to_version` is the current version when it is None, `from_version` the one before it."""
        page_id = parse_page_id(ref)
        check_context(context)
        if max_chars < 0:
            raise UsageError("--max-chars must not be negative.")
        if from_version is not None:
            check_version_number(from_version, "--from")
        if to_version is not None:
            check_version_number(to_version, "--to")
        current = read_page(self._gateway, page_id, with_body=True)
        newest = current.version_number
        to_number = to_version if to_version is not None else newest
        later = current if to_number == newest else read_version(self._gateway, page_id, to_number, newest)
        title = redact_text(current.title)
        to_side = _side(later, newest)
        if from_version is None and to_number <= 1:
            if newest <= 1:
                return VersionDiff(page_id, title, None, to_side, Difference("", 0, 0), (), True, f"Page {page_id} has one version only: there is nothing to compare.")
            note = (
                f"Version {to_number} is the first version of page {page_id}: nothing came before it, so there is nothing to compare. "
                f"`--from {to_number}` compares it with the current version."
            )
            return VersionDiff(page_id, title, None, to_side, Difference("", 0, 0), (), False, note, nothing_before=True)
        from_number = from_version if from_version is not None else to_number - 1
        earlier = current if from_number == newest else read_version(self._gateway, page_id, from_number, newest)
        from_side = _side(earlier, newest)
        old, new = as_markdown(earlier), as_markdown(later)
        difference = compare(
            old.text,
            new.text,
            old_label=f"version {from_number}" + (" (current)" if from_side.current else ""),
            new_label=f"version {to_number}" + (" (current)" if to_side.current else ""),
            old_date=from_side.created,
            new_date=to_side.created,
            context=context,
            max_chars=max_chars,
        )
        note = ""
        if from_number == to_number:
            note = f"Version {from_number} is compared with itself."
        elif difference.identical:
            note = f"Versions {from_number} and {to_number} read the same as Markdown."
        return VersionDiff(
            page_id,
            title,
            from_side,
            to_side,
            difference,
            tuple(sorted({*old.dropped, *new.dropped})),
            (earlier.body or "") == (later.body or ""),
            note,
        )


@dataclass(frozen=True)
class RestoreResult:
    dry_run: bool
    page_id: str
    title: str  # the title the page has afterwards: the old one with `restore_title`
    url: str
    restored_version: int
    version_from: int  # the version the page was at
    version_to: int  # the version that the restore makes (in a dry run: the one it would make)
    payload: dict[str, Any]
    added: int  # lines the restored text adds to the Markdown of the current text
    removed: int


class RestoreVersion:
    def __init__(self, gateway: ConfluenceGateway, diagnostics: Diagnostics) -> None:
        self._gateway = gateway
        self._diagnostics = diagnostics

    def execute(
        self,
        ref: str,
        version: int,
        *,
        message: str = "",
        restore_title: bool = False,
        if_version: int | None = None,
        if_unchanged_since: str | None = None,
        dry_run: bool = False,
    ) -> RestoreResult:
        """Makes a new version of the page with the content of an earlier one; nothing is lost, the history keeps every version."""
        page_id = parse_page_id(ref)
        number = check_version_number(version)
        if if_unchanged_since is not None:
            parse_guard_time(if_unchanged_since)  # an empty value is an error naming the option, never "no guard": refused before anything is asked, in a dry run too
        text = (message or "").strip() or f"Restored version {number}"
        page = read_page(self._gateway, page_id, with_body=True)
        if page.status != "current":
            raise ValidationError(f"Page {page_id} is {page.status or 'not current'} and is not restored.", hint="Restore it in Confluence first.")
        newest = page.version_number
        if number == newest:
            raise UsageError(
                f"Version {number} is the current version of page {page_id}: there is nothing to restore.",
                hint=f"Name an earlier version: `conflu versions {page_id}` lists them.",
            )
        if if_version is not None:
            ensure_version(page_id, newest, if_version)
        if if_unchanged_since is not None:
            ensure_unchanged_since(page_id, page.updated, if_unchanged_since)
        earlier = read_version(self._gateway, page_id, number, newest)
        difference = compare(as_markdown(page).text, as_markdown(earlier).text, context=0)
        payload = restore_payload(number, text, restore_title)
        title = redact_text(earlier.title if restore_title else page.title)
        url = page_address(page.url, page_id)
        if dry_run:
            return RestoreResult(True, page_id, title, url, number, newest, newest + 1, payload, difference.added, difference.removed)
        made = self._gateway.restore_page_version(page_id, payload)
        reached = made or newest + 1
        try:
            reached = self._gateway.get_page(page_id, with_body=False).version_number or reached
        except ConfluCliError as error:  # the restore is done: say what is known instead of failing
            self._diagnostics.warn(f"The version was restored, but the page could not be read back: {error.message}")
        if reached != newest + 1:
            self._diagnostics.warn(f"The page is at version {reached} now, not {newest + 1}: somebody saved it while this version was restored.")
        return RestoreResult(False, page_id, title, url, number, newest, reached, payload, difference.added, difference.removed)


@dataclass
class HistoryUseCases:
    """The use cases of the area, reached as `app.history.<name>`."""

    diff_versions: DiffVersions
    restore_version: RestoreVersion


def build(services: Services) -> HistoryUseCases:
    return HistoryUseCases(
        diff_versions=DiffVersions(services.gateway),
        restore_version=RestoreVersion(services.gateway, services.diagnostics),
    )
