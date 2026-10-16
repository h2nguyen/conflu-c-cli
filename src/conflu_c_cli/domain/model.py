"""The core concepts of the CLI as plain data. No I/O, no Confluence JSON."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from .errors import ValidationError

T = TypeVar("T")

_PAGE_ID = re.compile(r"^[0-9]{1,19}$")
_PAGE_IN_URL = re.compile(r"/pages/(?:[A-Za-z0-9-]+/)?([0-9]{1,19})(?:[/?#]|$)")
_PAGE_ID_PARAMETER = re.compile(r"[?&]pageId=([0-9]{1,19})(?:[&#]|$)")
_TINY_LINK = re.compile(r"/wiki/x/[A-Za-z0-9_-]+")
_SPACE_KEY = re.compile(r"^[~A-Za-z0-9][A-Za-z0-9~:_.-]{0,254}$")
_SPACE_IN_URL = re.compile(r"/spaces/([^/?#]+)")
_ATTACHMENT_ID = re.compile(r"^att[0-9]+$")


def parse_page_id(text: str) -> str:
    """A page id, or the address of a page as copied from the browser (`.../wiki/spaces/KEY/pages/123/Title`)."""
    value = (text or "").strip()
    if _PAGE_ID.match(value):
        return value
    for pattern in (_PAGE_IN_URL, _PAGE_ID_PARAMETER):
        match = pattern.search(value)
        if match:
            return match.group(1)
    if _TINY_LINK.search(value):
        raise ValidationError(
            f"A short link cannot be resolved offline: {value}",
            hint="Open it in the browser and copy the full address, or use the numeric page id.",
        )
    raise ValidationError(
        f"Invalid page id: {value or '<missing>'}",
        hint="A page id is a number such as 123456; a page address copied from the browser works too.",
    )


def parse_space_key(text: str) -> str:
    value = (text or "").strip()
    if not _SPACE_KEY.match(value):
        raise ValidationError(f"Invalid space key: {value or '<missing>'}", hint="A space key looks like ENG (letters and digits).")
    return value


def space_key_from_link(link: str) -> str:
    """The space key in a web address such as `/spaces/ENG/pages/123/Title`, or an empty text."""
    match = _SPACE_IN_URL.search(link or "")
    return match.group(1) if match else ""


def is_attachment_id(text: str) -> bool:
    return bool(_ATTACHMENT_ID.match((text or "").strip()))


@dataclass(frozen=True)
class User:
    account_id: str = ""
    display_name: str = ""
    email: str = ""


@dataclass(frozen=True)
class Label:
    name: str
    prefix: str = "global"


@dataclass(frozen=True)
class VersionInfo:
    number: int
    created: str = ""
    message: str = ""
    minor_edit: bool = False
    author: User | None = None


@dataclass(frozen=True)
class PageRef:
    id: str
    title: str = ""
    type: str = "page"
    status: str = ""


@dataclass(frozen=True)
class Comment:
    id: str
    kind: str = "footer"  # footer | inline
    updated: str = ""  # when the current version of the comment was saved; for a comment nobody edited, when it was written
    body: str = ""  # storage format
    version: int = 1
    author: User | None = None
    parent_id: str = ""
    resolution: str = ""  # inline comments: open, resolved, reopened, dangling


@dataclass
class Page:
    id: str
    title: str = ""
    status: str = ""
    space_id: str = ""
    space_key: str = ""
    parent_id: str = ""
    position: int | None = None
    created: str = ""
    version: VersionInfo | None = None
    author: User | None = None
    owner: User | None = None
    labels: list[Label] = field(default_factory=list)
    body: str | None = None  # storage format; None when it was not loaded
    url: str = ""
    ancestors: list[PageRef] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)
    raw: dict[str, Any] | None = field(default=None, repr=False, compare=False, metadata={"json": False})

    @property
    def updated(self) -> str:
        """When the current version was saved."""
        return self.version.created if self.version else self.created

    @property
    def version_number(self) -> int:
        return self.version.number if self.version else 0


@dataclass(frozen=True)
class Space:
    id: str
    key: str
    name: str = ""
    type: str = ""
    status: str = ""
    description: str = ""
    homepage_id: str = ""
    created: str = ""
    url: str = ""


@dataclass(frozen=True)
class Attachment:
    id: str
    title: str
    media_type: str = ""
    size: int = 0
    created: str = ""
    version: int = 1
    page_id: str = ""
    download_link: str = ""  # relative to the wiki root
    comment: str = ""


@dataclass(frozen=True)
class TreeNode:
    id: str
    title: str
    type: str = "page"
    parent_id: str = ""
    depth: int = 1
    status: str = ""
    position: int | None = None


@dataclass(frozen=True)
class SearchHit:
    id: str
    type: str
    title: str
    space_key: str = ""
    url: str = ""
    excerpt: str = ""
    last_modified: str = ""
    path: str = ""  # the titles of the parent pages from the top, joined by " > "
    labels: tuple[str, ...] = ()
    version: int | None = None
    snippet: str = ""  # the passage around the searched words, read from the page itself (see application.search)
    matched: tuple[str, ...] = ()  # which of the searched words the page holds, when a snippet was made


@dataclass
class SearchPage:
    hits: list[SearchHit]
    total: int
    start: int = 0
    limit: int = 0
    raw_results: list[dict[str, Any]] = field(default_factory=list, repr=False, metadata={"json": False})


@dataclass(frozen=True)
class Chunk(Generic[T]):
    """One page of a list that is read with a cursor. `cursor` is empty on the last one."""

    items: list[T]
    cursor: str = ""
