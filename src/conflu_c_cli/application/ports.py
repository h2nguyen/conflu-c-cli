"""Ports: what the application needs from the outside world.

The use cases depend on these interfaces only. Adapters implement them (Confluence over HTTP, a config
file, the file system) and tests replace them with fakes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from ..domain.model import (
    Attachment,
    Chunk,
    Comment,
    Label,
    Page,
    PageRef,
    SearchPage,
    Space,
    TreeNode,
    User,
    VersionInfo,
)


class ConfluenceGateway(ABC):
    """Everything the CLI asks of Confluence. Lists that are read with a cursor return a `Chunk`; the use cases
    ask for the next one with `chunk.cursor`, so the gateway never loops."""

    @abstractmethod
    def current_user(self) -> User: ...

    @abstractmethod
    def lookup_users(self, account_ids: Sequence[str]) -> dict[str, User]:
        """Names for account ids, as far as Confluence tells them; an id it does not know is left out."""

    @abstractmethod
    def list_spaces(self, *, space_type: str = "", status: str = "current", limit: int = 25, cursor: str = "") -> Chunk[Space]: ...

    @abstractmethod
    def get_space(self, key: str) -> Space:
        """The space with this key; NotFoundError when there is none or it cannot be seen."""

    @abstractmethod
    def get_space_by_id(self, space_id: str) -> Space: ...

    @abstractmethod
    def get_page(self, page_id: str, *, with_body: bool = True) -> Page:
        """The page with its labels and current version; the body in storage format when `with_body`."""

    @abstractmethod
    def list_pages(
        self,
        *,
        space_id: str = "",
        ids: Sequence[str] = (),
        title: str = "",
        status: str = "current",
        sort: str = "",
        root_only: bool = False,
        with_body: bool = False,
        limit: int = 25,
        cursor: str = "",
    ) -> Chunk[Page]: ...

    @abstractmethod
    def list_ancestors(self, page_id: str) -> list[PageRef]:
        """From the top of the tree down to the parent, with titles."""

    @abstractmethod
    def list_descendants(self, page_id: str, *, depth: int = 3, limit: int = 250, cursor: str = "") -> Chunk[TreeNode]: ...

    @abstractmethod
    def list_versions(self, page_id: str, *, limit: int = 25, cursor: str = "") -> Chunk[VersionInfo]:
        """Newest first."""

    @abstractmethod
    def create_page(self, payload: dict[str, Any]) -> Page:
        """Sends `payload` as it is (see `domain.payloads.create_page_payload`): what a dry run shows is what is sent."""

    @abstractmethod
    def update_page(self, page_id: str, payload: dict[str, Any]) -> Page:
        """Sends `payload` as it is (see `domain.payloads.update_page_payload`). A version that is not the next one
        is a ConflictError."""

    @abstractmethod
    def update_title(self, page_id: str, payload: dict[str, Any]) -> Page:
        """Changes only the title (see `domain.payloads.title_payload`)."""

    @abstractmethod
    def move_page(self, page_id: str, position: str, target_id: str) -> None:
        """`position` is append (below the target), before or after (next to it)."""

    @abstractmethod
    def list_comments(self, page_id: str, *, inline: bool = False, limit: int = 50, cursor: str = "") -> Chunk[Comment]:
        """The comments at the top of the conversations; the replies come from `list_replies`."""

    @abstractmethod
    def list_replies(self, comment_id: str, *, inline: bool = False, limit: int = 50, cursor: str = "") -> Chunk[Comment]: ...

    @abstractmethod
    def add_comment(self, payload: dict[str, Any]) -> Comment:
        """Sends `payload` as it is (see `domain.payloads.comment_payload`)."""

    @abstractmethod
    def list_labels(self, page_id: str) -> list[Label]: ...

    @abstractmethod
    def add_labels(self, page_id: str, payload: list[dict[str, str]]) -> list[Label]: ...

    @abstractmethod
    def remove_label(self, page_id: str, name: str) -> None: ...

    @abstractmethod
    def list_attachments(self, page_id: str, *, filename: str = "", limit: int = 50, cursor: str = "") -> Chunk[Attachment]: ...

    @abstractmethod
    def get_attachment(self, attachment_id: str) -> Attachment: ...

    @abstractmethod
    def upload_attachment(self, page_id: str, filename: str, data: bytes, *, comment: str = "", minor: bool = False) -> Attachment:
        """Adds the file, or a new version of it when the page has a file of that name."""

    @abstractmethod
    def download_attachment(self, attachment: Attachment) -> bytes: ...

    @abstractmethod
    def search(self, cql: str, *, limit: int = 25, start: int = 0) -> SearchPage: ...

    @abstractmethod
    def request(self, method: str, path: str, body: Any = None) -> Any:
        """A raw call below the wiki root, for example `api/v2/pages/123` or `rest/api/search?cql=...`."""


class ConfigStore(ABC):
    """Persistent settings: `KEY=value` pairs."""

    @property
    @abstractmethod
    def path(self) -> str: ...

    @abstractmethod
    def load(self) -> dict[str, str]: ...

    @abstractmethod
    def set(self, key: str, value: str) -> None: ...

    @abstractmethod
    def unset(self, key: str) -> bool:
        """True when the key was there."""


class Files(ABC):
    @abstractmethod
    def read_text(self, path: str, encoding: str = "utf-8") -> str: ...

    @abstractmethod
    def read_bytes(self, path: str) -> bytes: ...

    @abstractmethod
    def write_text(self, path: str, text: str) -> None:
        """Creates missing parent folders."""

    @abstractmethod
    def write_bytes(self, path: str, data: bytes) -> None:
        """Creates missing parent folders."""

    @abstractmethod
    def exists(self, path: str) -> bool: ...

    @abstractmethod
    def is_dir(self, path: str) -> bool: ...

    @abstractmethod
    def size(self, path: str) -> int: ...

    @abstractmethod
    def list_matching(self, directory: str, pattern: str) -> list[str]:
        """Full paths of the files in `directory` that match the glob `pattern`, sorted by name."""

    @abstractmethod
    def join(self, *parts: str) -> str: ...

    @abstractmethod
    def name(self, path: str) -> str: ...


class Clock(ABC):
    @abstractmethod
    def now(self) -> datetime:
        """The current time, timezone aware (UTC)."""


class Diagnostics(ABC):
    """Messages for the person at the terminal (or the agent), apart from the result."""

    @abstractmethod
    def info(self, message: str) -> None: ...

    @abstractmethod
    def warn(self, message: str) -> None: ...

    @abstractmethod
    def debug(self, message: str) -> None: ...


@dataclass(frozen=True)
class DocTopic:
    name: str
    title: str


class Docs(ABC):
    """The documentation that ships with the CLI."""

    @abstractmethod
    def topics(self) -> list[DocTopic]: ...

    @abstractmethod
    def topic(self, name: str) -> str: ...

    @abstractmethod
    def readme(self) -> str: ...

    @abstractmethod
    def changelog(self) -> str: ...

    @abstractmethod
    def skill(self) -> str: ...
