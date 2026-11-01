"""The part of the Confluence port that is about the files attached to a page: blog posts, versions, labels and the file itself.
`ConfluenceGateway` inherits it.

The two protocols are what the `Files` of the real file system can do besides what `Files` says, and a file system in memory need not: the use
cases look for them (`isinstance`) and fall back to what every `Files` can do.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Iterator, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ..domain.model import Attachment, Chunk, Label, VersionInfo



@runtime_checkable
class ComparesPlaces(Protocol):
    """Whether two paths lead to the same file or folder, which no comparison of the spellings can say: a link, `..`, another case of a name
    on Windows, a short name and a hard link all lead to one place."""

    def same_place(self, first: str, second: str) -> bool:
        """True when both name the same existing file or folder, or when one of them does not exist yet and they come to the same path once
        links and `..` are followed. False when one of them cannot be looked at."""


@runtime_checkable
class ReadsPieces(Protocol):
    """Reading a file piece by piece, so that a large file can be searched without being held in memory."""

    def read_pieces(self, path: str, size: int) -> Iterator[bytes]:
        """The bytes of the file in pieces of at most `size` bytes, one after the other. ValidationError when the file cannot be read."""


class AttachmentsPort(ABC):
    """The attachments of blog posts, the versions and the labels of an attachment, and the file of one version."""

    @abstractmethod
    def list_blogpost_attachments(self, blogpost_id: str, *, filename: str = "", limit: int = 50, cursor: str = "") -> Chunk[Attachment]:
        """The attachments of a blog post, as `list_attachments` has those of a page; NotFoundError when there is no such blog post."""

    @abstractmethod
    def list_attachment_versions(self, attachment_id: str, *, limit: int = 25, cursor: str = "") -> Chunk[VersionInfo]:
        """The versions of an attachment, newest first: number, when, message, who (an account id). The answer has no size."""

    @abstractmethod
    def get_attachment_version(self, attachment_id: str, version: int) -> Attachment:
        """The attachment as it was in this version (its size, its number); NotFoundError when it has no such version."""

    @abstractmethod
    def list_attachment_labels(self, attachment_id: str, *, limit: int = 50, cursor: str = "") -> Chunk[Label]: ...

    @abstractmethod
    def fetch_attachment(self, attachment: Attachment, version: int = 0, max_bytes: int = 0) -> bytes:
        """The file of an attachment of a page or of a blog post. `version` 0 is the newest; another number asks for that version. The file is
        fetched from the configured Confluence only (the address is built from the ids, never taken from the metadata).

        `max_bytes` (0: none of its own) is the most that the caller will take, whatever Confluence says of the size of the file: a file that is
        longer is refused with a ValidationError as soon as that is seen, and what is left of it is not read. A caller still looks at what it got,
        for an adapter that cannot stop half way."""
