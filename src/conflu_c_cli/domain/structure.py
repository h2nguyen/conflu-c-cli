"""Folders, whiteboards, databases and smart links as plain data, and the rules for what is written to them or below them.

They are what the tree of a space holds besides pages (`domain.content` names the kinds). Confluence describes each of them with the
same few facts, so one class, `Container`, serves the four.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from .drafts import MAX_TITLE
from .errors import ValidationError
from .model import Page, User, VersionInfo
from .payloads import update_page_payload
from .privacy import HIDDEN, hide_version, is_personal_space, redact_address, redact_storage, redact_text

MAX_URL = 2048  # what a browser and most servers accept
MOVE_MESSAGE_TITLE = 60  # the part of a title that the message of a move repeats
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_ADDRESS = re.compile(r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://(?P<authority>[^/?#]*)")
_HOST = re.compile(r"^(?P<host>\[[0-9A-Fa-f:.]+\]|[^\s/?#@:\[\]\\]+)(?::(?P<port>[0-9]{1,5}))?$")
_NOT_SHOWN = ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp", "Zs")  # control, format (zero-width, right-to-left override), unassigned, separators


@dataclass
class Container:
    """A folder, a whiteboard, a database or a smart link."""

    id: str
    type: str  # folder | whiteboard | database | embed
    title: str = ""
    status: str = ""
    space_id: str = ""
    space_key: str = ""
    parent_id: str = ""
    parent_type: str = ""  # page, whiteboard, database, embed or folder; empty when it has no parent
    position: int | None = None
    created: str = ""
    version: VersionInfo | None = None
    author: User | None = None
    owner: User | None = None
    url: str = ""
    embed_url: str = ""  # a smart link: the address it shows
    raw: dict[str, Any] | None = field(default=None, repr=False, compare=False, metadata={"json": False})

    @property
    def updated(self) -> str:
        """When the current version was saved."""
        return self.version.created if self.version else self.created

    @property
    def version_number(self) -> int:
        return self.version.number if self.version else 0


@dataclass(frozen=True)
class DatabaseField:
    id: str
    name: str
    type: str  # text, number, checkbox, date, select, hyperlink, user, attachment, jiraIssue, pageLink, entryLink ...
    description: str = ""
    options: tuple[str, ...] = ()  # the choices of a select field


@dataclass(frozen=True)
class DatabaseView:
    id: str
    name: str
    type: str  # table, gallery, board, calendar or timeline


@dataclass(frozen=True)
class FieldValue:
    """One cell of an entry. `value` is None when nothing is set, else by type: a text (text, number, date), a bool (checkbox), a list of
    texts (select: the labels; user: account ids; attachment: media ids; jiraIssue: keys; pageLink: page ids; entryLink: entry ids) or a list
    of `{url, label}` (hyperlink). The fields that Confluence derives from other content have no value."""

    type: str
    value: Any = None


@dataclass(frozen=True)
class DatabaseEntry:
    id: str
    database_id: str
    values: dict[str, FieldValue] = field(default_factory=dict)  # by the id of the field


def validate_title(title: str, what: str) -> str:
    """The title of a new folder or smart link, by the rules of a page title: not empty, one line, at most 255 characters."""
    text = (title or "").strip()
    if not text:
        raise ValidationError(f"The {what} title is empty.", hint="Pass --title.")
    if _CONTROL.search(text):
        raise ValidationError(f"The {what} title contains a line break or another control character.")
    if len(text) > MAX_TITLE:
        raise ValidationError(f"The {what} title is longer than {MAX_TITLE} characters ({len(text)}).")
    return text


def validate_url(url: str) -> str:
    """The address of a smart link as it was given: http or https, a host, no credentials, at most 2048 characters, and no blank, control or
    invisible character in it. What a server would reject later is refused here, before anything is sent."""
    text = (url or "").strip()
    if not text:
        raise ValidationError("The address of the smart link is empty.", hint="Pass --url with an http or https address.")
    if len(text) > MAX_URL:
        raise ValidationError(f"The address of the smart link is longer than {MAX_URL} characters ({len(text)}).")
    if any(unicodedata.category(char) in _NOT_SHOWN or char == "\\" for char in text):
        raise ValidationError(
            "The address of the smart link holds a blank, a backslash, a control character or a character that shows nothing.",
            hint="Copy the address from the browser; a space in it is written %20.",
        )
    found = _ADDRESS.match(text)
    if found is None or found.group("scheme").lower() not in ("http", "https"):
        raise ValidationError("The address of the smart link is not an http or https address.", hint="It starts with https:// or http://.")
    authority = found.group("authority")
    if "@" in authority:
        raise ValidationError(
            "The address of the smart link holds a user name or a password.",
            hint="Leave the credentials out: an address is stored in the page tree, and everybody who can see it can read them.",
        )
    host = _HOST.match(authority)
    if host is None or (host.group("port") is not None and not 0 < int(host.group("port")) < 65536):
        raise ValidationError("The address of the smart link has no valid host name or port.", hint="For example https://example.com/page.")
    return text


def folder_payload(space_id: str, title: str, parent_id: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {"spaceId": space_id, "title": title}
    if parent_id:
        payload["parentId"] = parent_id
    return payload


def smartlink_payload(space_id: str, title: str, url: str, parent_id: str = "") -> dict[str, Any]:
    payload = folder_payload(space_id, title, parent_id)
    payload["embedUrl"] = url
    return payload


def move_message(title: str) -> str:
    """The message of the version that a move saves: `Moved below Guides`. The title is redacted, on one line and short."""
    text = " ".join(redact_text(title).split())
    shown = text if len(text) <= MOVE_MESSAGE_TITLE else text[: MOVE_MESSAGE_TITLE - 3].rstrip() + "..."
    return f"Moved below {shown}" if shown else "Moved"


def move_payload(page: Page, parent_id: str, message: str) -> dict[str, Any]:
    """What `PUT /pages/{id}` takes to put the page below another parent: the page as it is (title, status and body untouched) at the next
    version, with the new `parentId`. The version number is the guard: Confluence refuses it when somebody saved the page meanwhile.
    The page must have been read with its body: a page without one would be saved empty."""
    if page.body is None:
        raise ValueError(f"Page {page.id} was read without its body: moving it would save it empty")
    base = update_page_payload(page.id, page.title, page.body, page.version_number + 1, message, page.status)
    return {"id": base["id"], "status": base["status"], "title": base["title"], "parentId": parent_id, "body": base["body"], "version": base["version"]}


def shown_key(key: str, space_type: str = "") -> str:
    """The key of a space as it may be printed when people are not shown: a personal space is keyed by the account id of its owner, so it is `[hidden]`
    (`privacy.is_personal_space` says which; `space_type` is the type that Confluence gave, when it is known)."""
    return HIDDEN if is_personal_space(key, space_type) else key


def hide_people_in_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """The request as it may be shown when people are not shown: the title and the body redacted (the account ids of mentions blanked, e-mail
    addresses and personal links replaced). What is sent is the payload itself, never this copy."""
    shown = dict(payload)
    if isinstance(shown.get("title"), str):
        shown["title"] = redact_text(shown["title"])
    body = shown.get("body")
    if isinstance(body, dict) and isinstance(body.get("value"), str):
        shown["body"] = {**body, "value": redact_storage(body["value"])}
    return shown


def hide_people(container: Container) -> Container:
    """A copy without people and with redacted text. The key of a personal space and the address in it name the owner: they are `[hidden]` (the
    address keeps the rest of its path, see `privacy.redact_address`)."""
    return replace(
        container,
        title=redact_text(container.title),
        space_key=shown_key(container.space_key),
        url=redact_address(container.url),
        author=None,
        owner=None,
        version=hide_version(container.version),
        embed_url=redact_text(container.embed_url),
        raw=None,
    )


def shown_value(value: FieldValue, users: Mapping[str, User] | None) -> Any:
    """What a cell of an entry shows. Without `users` (account id -> user) the people in it are `[hidden]`, one marker each, and text and links are
    redacted; with them the people are named and the text stays as it is."""
    items = value.value
    if items is None:
        return None
    people = users is not None
    clean = (lambda text: text) if people else redact_text
    if value.type == "user":
        if users is None:
            return [HIDDEN for _ in items]
        return [
            {"accountId": item, "displayName": users[item].display_name if item in users else "", "email": users[item].email if item in users else ""}
            for item in items
        ]
    if value.type == "hyperlink":
        return [{"url": clean(item.get("url", "")), "label": clean(item.get("label", ""))} for item in items]
    if isinstance(items, str):
        return clean(items)
    if isinstance(items, list):
        return [clean(item) if isinstance(item, str) else item for item in items]
    return items
