"""The in-memory Confluence for the files attached to a page or a blog post: versions, labels and the file of one version: a mixin of `FakeGateway`
(`_init_attachments` sets up its state).

The attachments themselves are what `FakeGateway` keeps for the pages, `attachments` (a list for each page, and for each blog post: it is
the id of the holder) and `attachment_data` (the newest bytes of each). What a test starts with is in `attachment_data.py`."""
from __future__ import annotations

import dataclasses

from conflu_c_cli.domain.errors import NotFoundError
from conflu_c_cli.domain.model import Attachment, Chunk, Label, User, VersionInfo

from .attachment_data import ACCOUNT, FIXTURES, Fixture


class FakeAttachments:
    def _init_attachments(self) -> None:
        self.attachment_versions: dict[str, list[VersionInfo]] = {}  # what is known of the versions of an attachment: number, when, message
        self.attachment_version_data: dict[tuple[str, int], bytes] = {}  # the bytes of each version that is known, by the attachment and the number
        self.attachment_labels: dict[str, list[Label]] = {}
        self.limits_asked: list[tuple[str, int]] = []  # (attachment id, max_bytes) of every `fetch_attachment`
        for fixture in FIXTURES:
            if fixture.container in self.pages or self.content_kinds.get(fixture.container) == "blogpost":
                self.add_attachment_fixture(fixture)

    def add_attachment_fixture(self, fixture: Fixture) -> Attachment:
        """An attachment with the versions, the labels and the bytes that a `Fixture` says, on a page or on a blog post."""
        last = fixture.editions[-1]
        on_page = fixture.container in self.pages
        item = Attachment(
            fixture.id,
            fixture.name,
            fixture.media_type,
            len(last.data),
            fixture.editions[0].created,
            len(fixture.editions),
            fixture.container if on_page else "",
            f"/download/attachments/{fixture.container}/{fixture.name}?version={len(fixture.editions)}&api=v2",
            fixture.comment,
            "" if on_page else fixture.container,
            last.created,
        )
        self.attachments.setdefault(fixture.container, []).append(item)
        self.attachment_data[item.id] = last.data
        self.attachment_versions[item.id] = [
            VersionInfo(number, edition.created, edition.message, edition.minor, User(ACCOUNT)) for number, edition in enumerate(fixture.editions, 1)
        ]
        for number, edition in enumerate(fixture.editions, 1):
            self.attachment_version_data[(item.id, number)] = edition.data
        self.attachment_labels[item.id] = [Label(name) for name in fixture.labels]
        return item

    def _find_attachment(self, attachment_id: str) -> Attachment:
        for items in self.attachments.values():
            for item in items:
                if item.id == attachment_id:
                    return item
        raise NotFoundError(f"Not found: GET /api/v2/attachments/{attachment_id}")

    def _bytes_of(self, item: Attachment, version: int) -> bytes:
        if (item.id, version) in self.attachment_version_data:
            return self.attachment_version_data[(item.id, version)]
        if version == item.version and item.id in self.attachment_data:
            return self.attachment_data[item.id]
        raise NotFoundError(f"Not found: GET /api/v2/attachments/{item.id}?version={version}")

    def list_blogpost_attachments(self, blogpost_id: str, *, filename: str = "", limit: int = 50, cursor: str = "") -> Chunk[Attachment]:
        self._enter("list_blogpost_attachments", blogpost_id, filename, limit, cursor)
        if self.content_kinds.get(blogpost_id) != "blogpost":
            raise NotFoundError(f"Not found: GET /api/v2/blogposts/{blogpost_id}/attachments")
        items = [item for item in self.attachments.get(blogpost_id, []) if not filename or item.title == filename]
        return self._chunk(items, cursor, limit)

    def list_attachment_versions(self, attachment_id: str, *, limit: int = 25, cursor: str = "") -> Chunk[VersionInfo]:
        self._enter("list_attachment_versions", attachment_id, limit, cursor)
        item = self._find_attachment(attachment_id)
        known = {version.number: version for version in self.attachment_versions.get(item.id, [])}
        versions = [known.get(number) or VersionInfo(number, item.created, "", False, User(ACCOUNT)) for number in range(item.version, 0, -1)]
        return self._chunk(versions, cursor, limit)

    def get_attachment_version(self, attachment_id: str, version: int) -> Attachment:
        self._enter("get_attachment_version", attachment_id, version)
        item = self._find_attachment(attachment_id)
        data = self._bytes_of(item, version)
        holder = item.page_id or item.blog_post_id
        saved = next((entry.created for entry in self.attachment_versions.get(item.id, []) if entry.number == version), "") or item.updated
        link = f"/download/attachments/{holder}/{item.title}?version={version}&api=v2"
        return dataclasses.replace(item, version=version, size=len(data), download_link=link, updated=saved)

    def list_attachment_labels(self, attachment_id: str, *, limit: int = 50, cursor: str = "") -> Chunk[Label]:
        self._enter("list_attachment_labels", attachment_id, limit, cursor)
        self._find_attachment(attachment_id)
        return self._chunk(list(self.attachment_labels.get(attachment_id, [])), cursor, limit)

    def fetch_attachment(self, attachment: Attachment, version: int = 0, max_bytes: int = 0) -> bytes:
        self.limits_asked.append((attachment.id, max_bytes))  # what the use case wanted the file limited to; this fake, like a poor adapter, reads it whole
        if not version and not attachment.blog_post_id:
            return self.download_attachment(attachment)  # the newest file of a page: the call that every test of the download looks for
        self._enter("fetch_attachment", attachment.id, version)
        item = self._find_attachment(attachment.id)
        return self._bytes_of(item, version or item.version)
