"""Keeping personal data out of what the CLI prints: account ids, e-mail addresses, personal links, mentions."""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from .model import Comment, Page, PageRef, SearchHit, VersionInfo

HIDDEN = "[hidden]"

_PROFILE_PATH = r"/(?:wiki/)?(?:people/|spaces/~)[^\s\"'<>)]*"
# a profile address, absolute or as the page writes it (`/wiki/people/ID`); a path of any other kind (`docs/people/roles`) is not one
_PERSONAL_LINK = re.compile(r"https?://[^\s\"'<>)]*" + _PROFILE_PATH + r"|(?<![\w./~:-])" + _PROFILE_PATH)
# a Markdown link to a profile: its text is the name of the person, so the whole link goes
_PERSONAL_MARKDOWN_LINK = re.compile(r"\[(?:[^\[\]\\\n]|\\.)*\]\((?:" + _PERSONAL_LINK.pattern + r")\)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_ACCOUNT_ATTRIBUTE = re.compile(r'\b(ri:(?:account-id|userkey|username))="[^"]*"')
_BLANKED_ATTRIBUTE = re.compile(r'\bri:(?:account-id|userkey|username)="hidden"')
_PERSON_KEYS = frozenset({"authorId", "ownerId", "lastOwnerId", "spaceOwnerId", "creatorId", "accountId"})
_PERSON_NAME_KEYS = ("displayName", "publicName", "email")


def normalize_newlines(text: Any) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n")


LINK_MARKER = "[personal link]"
EMAIL_MARKER = "[email]"


def is_profile_link(href: Any) -> bool:
    """True when the address is that of a person's profile (or personal space): a link to one is as good as a mention of the person."""
    text = str(href or "").strip()
    found = _PERSONAL_LINK.match(text)
    return bool(found) and found.end() == len(text)


def redact_text(text: Any) -> str:
    """Remove personal profile links (a Markdown link to a profile as a whole: its text is a name) and e-mail addresses from free text."""
    cleaned = _PERSONAL_MARKDOWN_LINK.sub(LINK_MARKER, str(text or ""))
    cleaned = _PERSONAL_LINK.sub(LINK_MARKER, cleaned)
    return _EMAIL.sub(EMAIL_MARKER, cleaned)


def has_redaction_marker(text: Any) -> bool:
    """True when the text holds what `redact_text` puts in the place of an e-mail address or a personal link."""
    return LINK_MARKER in str(text or "") or EMAIL_MARKER in str(text or "")


def redact_storage(storage: Any) -> str:
    """Storage format without the account ids of mentions, and with the text redacted. A page body that was cleaned
    this way must not be written back: its mentions no longer point at anybody."""
    return redact_text(_ACCOUNT_ATTRIBUTE.sub(r'\1="hidden"', str(storage or "")))


def mentions_people(storage: Any) -> bool:
    return bool(_ACCOUNT_ATTRIBUTE.search(str(storage or "")))


def has_blanked_mentions(storage: Any) -> bool:
    """True when storage format carries mentions that `redact_storage` blanked: it must not be written to a page."""
    return bool(_BLANKED_ATTRIBUTE.search(str(storage or "")))


def looks_like_user(value: Any) -> bool:
    return isinstance(value, dict) and "accountId" in value and any(key in value for key in _PERSON_NAME_KEYS)


def strip_users(value: Any) -> Any:
    """Replace every user object and person id in raw JSON with a marker and redact all text."""
    if looks_like_user(value):
        return {"hidden": True}
    if isinstance(value, dict):
        return {key: HIDDEN if key in _PERSON_KEYS and isinstance(child, str) else strip_users(child) for key, child in value.items()}
    if isinstance(value, list):
        return [strip_users(child) for child in value]
    if isinstance(value, str):
        return redact_storage(value)
    return value


def hide_version(version: VersionInfo | None) -> VersionInfo | None:
    return None if version is None else replace(version, author=None, message=redact_text(version.message))


def hide_users(page: Page) -> Page:
    """A copy of the page without people and with redacted text."""
    return replace(
        page,
        title=redact_text(page.title),
        author=None,
        owner=None,
        version=hide_version(page.version),
        body=None if page.body is None else redact_storage(page.body),
        ancestors=[hide_ref(ref) for ref in page.ancestors],
        comments=[hide_comment_author(comment) for comment in page.comments],
        raw=None,
    )


def hide_comment_author(comment: Comment) -> Comment:
    return replace(comment, author=None, body=redact_storage(comment.body))


def hide_ref(ref: PageRef) -> PageRef:
    return replace(ref, title=redact_text(ref.title))


def hide_hit(hit: SearchHit) -> SearchHit:
    """The search index writes the name of a mentioned person into the excerpt as plain text, which cannot be told from
    any other word: the excerpt is left out altogether."""
    return replace(hit, title=redact_text(hit.title), excerpt="", path=redact_text(hit.path))


__all__ = [
    "HIDDEN",
    "hide_comment_author",
    "hide_hit",
    "hide_ref",
    "hide_users",
    "has_blanked_mentions",
    "hide_version",
    "has_redaction_marker",
    "looks_like_user",
    "mentions_people",
    "normalize_newlines",
    "redact_storage",
    "redact_text",
    "strip_users",
]
