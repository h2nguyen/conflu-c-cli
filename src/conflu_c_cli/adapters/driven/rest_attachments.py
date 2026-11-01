"""The files attached to a page or a blog post: versions, labels and the file of one version: the REST calls. A mixin of `RestConfluenceGateway`,
which provides `_call`, `_finish`, `_transport`, `_settings`, `_next_cursor` and `_base`."""
from __future__ import annotations

from ...domain.errors import NotFoundError, UnavailableError, ValidationError
from ...domain.model import Attachment, Chunk, Label, VersionInfo
from ...domain.privacy import redact_text
from . import confluence_mapper as mapper
from . import http_transport
from .rest_support import V1, V2
from .rest_support import query as _query
from .rest_support import quote as _quote

# The models and the mapper of this area are imported where they are used, so that a command that never reads it does not load them (tests/test_startup.py).

# The calls of this area that use the v1 API, each with why v2 does not do (see docs/reference/compatibility.md).
# None of its own: v2 lists the versions, the labels and the attachments of a blog post, and reads one version (`GET /attachments/{id}?version=N`).
# The file of an attachment, of any version, is the one v1 call that the core names (`GET /rest/api/content/{id}/child/attachment/{attachmentId}/download`,
# which takes `?version=N`).
V1_CALLS: dict[str, str] = {}


def name_of(attachment: Attachment) -> str:
    """An attachment for an error message: its name can hold an e-mail address (it is data that somebody typed) and an error cannot know whether
    people are shown, so the name is redacted, and the id says which attachment it is."""
    from ...domain.attachmenttext import printable

    return f"{printable(redact_text(attachment.title))} ({attachment.id})"


class RestAttachments:
    def list_blogpost_attachments(self, blogpost_id: str, *, filename: str = "", limit: int = 50, cursor: str = "") -> Chunk[Attachment]:
        from . import map_attachments as attachment_map

        data = self._call("GET", f"{V2}/blogposts/{_quote(blogpost_id)}/attachments?{_query(filename=filename, limit=limit, cursor=cursor)}")
        return Chunk(attachment_map.attachments_of(data), self._next_cursor(data))

    def list_attachment_versions(self, attachment_id: str, *, limit: int = 25, cursor: str = "") -> Chunk[VersionInfo]:
        from . import map_attachments as attachment_map

        query = _query(sort="-modified-date", limit=limit, cursor=cursor)
        data = self._call("GET", f"{V2}/attachments/{_quote(attachment_id)}/versions?{query}")
        return Chunk(attachment_map.versions_of(data), self._next_cursor(data))

    def get_attachment_version(self, attachment_id: str, version: int) -> Attachment:
        return mapper.attachment_from(self._call("GET", f"{V2}/attachments/{_quote(attachment_id)}?{_query(version=version)}"))

    def list_attachment_labels(self, attachment_id: str, *, limit: int = 50, cursor: str = "") -> Chunk[Label]:
        from . import map_attachments as attachment_map

        number = attachment_id.removeprefix("att")  # the document types this one id as an integer; the other attachment calls take `(att)?[0-9]+`
        data = self._call("GET", f"{V2}/attachments/{_quote(number)}/labels?{_query(limit=limit, cursor=cursor)}")
        return Chunk(attachment_map.labels_of(data), self._next_cursor(data))

    def fetch_attachment(self, attachment: Attachment, version: int = 0, max_bytes: int = 0) -> bytes:
        from ...domain.attachmenttext import human_size

        container = attachment.page_id or attachment.blog_post_id
        if not version and not attachment.blog_post_id and not (max_bytes and container):
            return self.download_attachment(attachment)  # the newest file of a page, to be taken whole: what the core asks for
        if not container:
            raise NotFoundError(f"Confluence did not say which page or blog post holds {name_of(attachment)}, so its file cannot be asked for.")
        path = f"{V1}/content/{_quote(container)}/child/attachment/{_quote(attachment.id)}/download"
        if version:
            path += f"?{_query(version=version)}"
        try:
            # a redirect to a media service is followed there, without the credentials
            response = self._transport.download(path, limit=max_bytes) if max_bytes else self._transport.download(path)
        except http_transport.AnswerTooBig:
            if not max_bytes or max_bytes > http_transport.MAX_DOWNLOAD:
                raise  # the limit of the transport itself, which the caller cannot raise
            raise ValidationError(  # whatever Confluence said of the size, the file is longer than the caller takes: the rest of it was not read
                f"{name_of(attachment)} is larger than {human_size(max_bytes)}; it was not read to the end and nothing was kept.",
                hint="Raise --max-bytes, or choose the other files by id or --name.",
                details={"attachmentId": attachment.id, "maxBytes": max_bytes},
            ) from None
        if response.status != 200:  # a file is no JSON: only a refusal is decoded, to say what Confluence said
            if response.status >= 300:
                self._raise_for_status(response, self._decode(response), "GET", path.split("?")[0])
            raise UnavailableError(f"Confluence did not send {name_of(attachment)} (HTTP {response.status}).")
        return response.body
