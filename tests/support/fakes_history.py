"""The in-memory Confluence for earlier versions of a page, the difference between two of them, and restoring one: a mixin of `FakeGateway` (`_init_history` sets up its state).

The page 2002 has three versions (`FakeGateway.versions` lists them): version 3 is the page as it is, versions 1 and 2 are kept here with a body of their own
(`version_bodies`) and, for version 1, a title of its own (`version_titles`). Any other page has its current version only, until a test adds more."""
from __future__ import annotations

import copy
import dataclasses
from typing import Any, Sequence

from conflu_c_cli.domain.errors import NotFoundError, RejectedError
from conflu_c_cli.domain.model import Chunk, Page, VersionInfo

FIRST_BODY = "<h1>Release notes</h1><p>Draft.</p>"
SECOND_BODY = (
    '<h1>Release notes</h1><p>Contact <ac:link><ri:user ri:account-id="5b10ac8d82e05b22cc7d4ef5" /></ac:link>.</p><ul><li>First</li></ul>'
)


class FakeHistory:
    def _init_history(self) -> None:
        self.version_bodies: dict[tuple[str, int], str] = {("2002", 1): FIRST_BODY, ("2002", 2): SECOND_BODY}
        self.version_titles: dict[tuple[str, int], str] = {("2002", 1): "Release notes (draft)"}

    def _version_of(self, page_id: str, number: int) -> tuple[str, str, VersionInfo]:
        """The title, the body and the version of an earlier version of the page, or NotFoundError."""
        page = self._page(page_id)
        if number == page.version_number:
            return page.title, page.body or "", page.version
        known = {version.number: version for version in self.versions.get(page_id, [])}
        body = self.version_bodies.get((page_id, number))
        if number not in known or body is None:
            raise NotFoundError(f"Not found: GET /api/v2/pages/{page_id} - Version not found: {number}")
        return self.version_titles.get((page_id, number), page.title), body, known[number]

    def get_page_version(self, page_id: str, number: int, *, with_body: bool = True) -> Page:
        self._enter("get_page_version", page_id, number, with_body)
        title, body, version = self._version_of(page_id, number)
        raw = copy.deepcopy(self._page(page_id).raw) or {}
        raw.update({"title": title, "version": {"number": version.number, "authorId": version.author.account_id if version.author else ""}})
        return dataclasses.replace(self._copy(self._page(page_id), with_body), title=title, version=version, body=body if with_body else None, raw=raw)

    def get_pages(self, ids: Sequence[str], *, with_body: bool = False, limit: int = 250, cursor: str = "") -> Chunk[Page]:
        self._enter("get_pages", tuple(ids), with_body, limit, cursor)
        found = sorted((page for page in self.pages.values() if page.id in ids and page.status in ("current", "archived")), key=lambda page: int(page.id))
        chunk = self._chunk(found, cursor, limit)
        return Chunk([dataclasses.replace(self._copy(page, with_body), labels=[]) for page in chunk.items], chunk.cursor)  # this call has no labels

    def restore_page_version(self, page_id: str, payload: dict[str, Any]) -> int:
        self._enter("restore_page_version", page_id, payload)
        page = self._page(page_id)
        params = payload.get("params") or {}
        number = params.get("versionNumber")
        if payload.get("operationKey") != "restore" or not isinstance(number, int) or not isinstance(params.get("message"), str):
            raise RejectedError("Confluence refused the request (HTTP 400): operationKey, params.versionNumber and params.message are required")
        title, body, _ = self._version_of(page_id, number)
        previous = page.version
        self.version_bodies.setdefault((page_id, previous.number), page.body or "")  # the version that the restore covers stays readable
        self.version_titles.setdefault((page_id, previous.number), page.title)
        page.body = body
        if params.get("restoreTitle"):
            page.title = title
        self._save_version(page, previous.number + 1, params["message"])
        self.versions[page_id] = [page.version, *self.versions.get(page_id, [previous])]
        return page.version.number
