"""Keeping personal data out of what the CLI prints: account ids, e-mail addresses, personal links, mentions."""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from .model import Comment, Page, PageRef, SearchHit, Space, VersionInfo

HIDDEN = "[hidden]"
PERSONAL_SPACE = "[personal space]"

_PROFILE_PATH = r"/(?:wiki/)?(?:people/|spaces/~)[^\s\"'<>)]*"
# a profile address, absolute or as the page writes it (`/wiki/people/ID`); a path of any other kind (`docs/people/roles`) is not one. The scan from `http://`
# stops at the next `http://`, so that a text made of nothing but `http://http://...` is read in one pass, not once from every start.
_PERSONAL_LINK = re.compile(r"https?://(?:(?!https?://)[^\s\"'<>)])*?" + _PROFILE_PATH + r"|(?<![\w./~:-])" + _PROFILE_PATH)
# an address that ends in a number and then one more segment: the id of a page or a blog post, and the title that Confluence puts behind it
_ADDRESS_WITH_TITLE = re.compile(r"^(?P<head>[^?#]*/\d+)/(?P<slug>[^/?#]*)(?P<tail>[?#].*)?$")
_PERCENT = re.compile(r"%([0-9A-Fa-f]{2})")
_LABEL_LIMIT = 256  # how far back from a profile address the text of the Markdown link around it is looked for
# The look-behind lets a match start only at the beginning of a run of address characters: without it a page of one long word was scanned again from every
# letter (about 10 seconds for 40 000 characters).
_EMAIL = re.compile(r"(?<![\w.+'&!#$%*^`{|}~-])[\w.+'&!#$%*^`{|}~-]+@[\w-]+(?:\.[\w-]+)+")  # the characters of a local part that people really use (o'connor, a&b)
_ATTRIBUTE_VALUE = r"""\s*=\s*(?:"[^"]*"|'[^']*')"""  # `name="value"`, `name='value'` and blanks around the `=` are one thing to XML
_ACCOUNT_ATTRIBUTE = re.compile(r"\b((?:ri:|data-)(?:account-id|userkey|username))" + _ATTRIBUTE_VALUE, re.IGNORECASE)
# a link into a personal space names the owner by the account id in the key
_SPACE_KEY_ATTRIBUTE = re.compile(r"""\bri:space-key\s*=\s*(?:"~[^"]*"|'~[^']*')""", re.IGNORECASE)
_BLANKED_ATTRIBUTE = re.compile(
    r"""\b(?:ri:|data-)(?:account-id|userkey|username)\s*=\s*(?:"hidden"|'hidden')|\bri:space-key\s*=\s*(?:"%s"|'%s')""" % (re.escape(HIDDEN), re.escape(HIDDEN)),
    re.IGNORECASE,
)
_PERSONAL_KEY = re.compile(r"(?<![\w~])~[\w:.~-]*")  # `~` and the characters of a key; what cannot end a key is given back by `_hide_personal_key` (a pattern that must end in a letter backtracks: quadratic on `~-~-~-`)
# the head of a comparison that names spaces: `space = `, `space != `, `space in `, `space not in `, `space.key = ...` (any case). Only the VALUE after it can be a key:
# the operator `~` of a text search (`title ~ "~notes"`, `"a b"~10`, `word~`) is no key and is left alone.
_SPACE_HEAD = re.compile(r"\bspace(?:\.key)?\s*(?:!=|=|\bnot\s+in\b|\bin\b)\s*", re.IGNORECASE)
_VALUE_END = re.compile(r"[\s()]")
_PERSON_KEYS = frozenset({"authorId", "ownerId", "lastOwnerId", "spaceOwnerId", "creatorId", "accountId", "createdBy", "assignedTo", "completedBy"})
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


def _label_start(text: str, close: int, floor: int) -> int:
    """Where the `[` of a Markdown link is whose text ends just before index `close`, or -1: the nearest `[` that is not escaped, with no line break and no
    unescaped `]` in between, and not further back than `_LABEL_LIMIT` characters."""
    position, stop = close - 1, max(floor, close - _LABEL_LIMIT - 1)
    while position >= stop:
        char = text[position]
        if char == "\n":
            return -1
        if char in "[]":
            slashes = 0
            while position - slashes - 1 >= 0 and text[position - slashes - 1] == "\\":
                slashes += 1
            if slashes % 2 == 0:
                return position if char == "[" else -1
        position -= 1
    return -1


def _replace_profile_links(text: str) -> str:
    """Every address of a person's profile becomes `[personal link]`, and a Markdown link to one goes as a whole, because its text is the name of the
    person. One pass: each address is found once, and only the bounded text in front of it is read back, so that no text can make it take longer."""
    pieces: list[str] = []
    last = 0
    for found in _PERSONAL_LINK.finditer(text):
        start, end = found.span()
        if start < last:
            continue
        if start >= 2 and text[start - 2 : start] == "](" and text[end : end + 1] == ")":
            opening = _label_start(text, start - 2, last)
            if opening >= 0:
                start, end = opening, end + 1
        pieces.append(text[last:start])
        pieces.append(LINK_MARKER)
        last = end
    pieces.append(text[last:])
    return "".join(pieces)


def redact_text(text: Any) -> str:
    """Remove personal profile links (a Markdown link to a profile as a whole: its text is a name) and e-mail addresses from free text."""
    cleaned = str(text or "")
    if "people/" in cleaned or "spaces/~" in cleaned:  # only such a text can hold a profile link: the other pattern need not look
        cleaned = _replace_profile_links(cleaned)
    return _EMAIL.sub(EMAIL_MARKER, cleaned)


def _title_of(slug: str) -> str:
    """`Contact+alex%40example.com` as the title it was made from: a blank is written `+`, other characters `%XX`. Only the ASCII characters that a
    redaction looks for (`@`, `/`, `:`) matter here, so a byte of a longer character may come out wrong; the result is only compared, never shown."""
    return _PERCENT.sub(lambda found: chr(int(found.group(1), 16)), slug.replace("+", " "))


_PERSONAL_SPACE_ADDRESS = re.compile(r"/spaces/~[^/?#]*")
_CONTENT_ID_IN_ADDRESS = re.compile(r"/(?:pages|blog/\d{4}/\d{2}/\d{2})/(\d+)")


def redact_address(url: Any) -> str:
    """The address of a page or a blog post as Confluence builds it ends in the title (`/pages/123/Title+of+it`), and a title can hold an e-mail
    address or the link to a person. Then the address ends at the id, which opens the page just the same; any other address stays as it is.
    An address inside a personal space (`/spaces/~ACCOUNT/...`, which names its owner by the account id) becomes the one that names the page by its id
    alone (`/pages/viewpage.action?pageId=123`); for other content it keeps the path and has `[hidden]` in the place of the key."""
    text = str(url or "")
    personal = _PERSONAL_SPACE_ADDRESS.search(text)
    if personal:
        content = _CONTENT_ID_IN_ADDRESS.search(text, personal.end())
        if content:
            return f"{text[: personal.start()]}/pages/viewpage.action?pageId={content.group(1)}"
        return f"{text[: personal.start()]}/spaces/{HIDDEN}{text[personal.end():]}"
    found = _ADDRESS_WITH_TITLE.match(text)
    if not found:
        return text
    slug = _title_of(found.group("slug"))
    if redact_text(slug) == slug:
        return text
    return found.group("head") + (found.group("tail") or "")


def page_address(url: Any, content_id: Any = "") -> str:
    """The address of a page or a blog post as it may be printed when people are not shown (see `redact_address`). `content_id` is the id of the
    content: with it an address in a personal space is the one that names the page by its id even when the address has no `/pages/ID` in it."""
    text = str(url or "")
    personal = _PERSONAL_SPACE_ADDRESS.search(text)
    if personal and content_id and not _CONTENT_ID_IN_ADDRESS.search(text, personal.end()):
        return f"{text[: personal.start()]}/pages/viewpage.action?pageId={content_id}"
    return redact_address(text)


def has_redaction_marker(text: Any) -> bool:
    """True when the text holds what `redact_text` puts in the place of an e-mail address or a personal link."""
    return LINK_MARKER in str(text or "") or EMAIL_MARKER in str(text or "")


def redact_storage(storage: Any) -> str:
    """Storage format without the account ids of mentions and the keys of personal spaces in links (a key is the account id of the owner), and with the
    text redacted. A page body that was cleaned this way must not be written back: its mentions and links no longer point at anybody."""
    cleaned = _SPACE_KEY_ATTRIBUTE.sub(f'ri:space-key="{HIDDEN}"', _ACCOUNT_ATTRIBUTE.sub(r'\1="hidden"', str(storage or "")))
    return redact_text(cleaned)


def _hide_personal_key(found: re.Match[str]) -> str:
    """`~` and an account id (what a query writes for the space of a person) becomes `[hidden]`; the characters after the last letter, digit or `_`
    are not part of a key and stay (`~alex-` is `[hidden]-`), and a `~` with none is no key."""
    text = found.group(0)
    key = text.rstrip(":.~-")
    return text if len(key) <= 1 else HIDDEN + text[len(key) :]


def redact_query(query: Any) -> str:
    """A query as it may be printed when people are not shown: the key of a personal space in the value of a `space` comparison (`space = "~ACCOUNT"`,
    `space in ("ENG", "~ACCOUNT")`, `space.key = ~ACCOUNT`) is `[hidden]`. What is run is the query itself, never this copy. Nothing else is touched: the
    operator `~` of a text search, proximity (`"a b"~10`), fuzziness (`word~`) and quoted texts stay as they were written.

    Each comparison is read once, up to the end of its value (a list ends at its `)`, a single value at a blank or a parenthesis), and a comparison that
    begins inside what was read is not read again: the work grows with the length of the query, not with its square."""
    text = str(query or "")
    parts: list[str] = []
    done = 0
    for head in _SPACE_HEAD.finditer(text):
        start = head.end()
        if start < done:
            continue
        if text.startswith("(", start):
            close = text.find(")", start)
            end = len(text) if close < 0 else close + 1
        else:
            stop = _VALUE_END.search(text, start)
            end = len(text) if stop is None else stop.start()
        parts.append(text[done:start])
        parts.append(_PERSONAL_KEY.sub(_hide_personal_key, text[start:end]))
        done = end
    parts.append(text[done:])
    return "".join(parts)


def mentions_people(storage: Any) -> bool:
    return bool(_ACCOUNT_ATTRIBUTE.search(str(storage or "")))


def has_blanked_mentions(storage: Any) -> bool:
    """True when storage format carries mentions or links into a personal space that `redact_storage` blanked: it must not be written to a page."""
    return bool(_BLANKED_ATTRIBUTE.search(str(storage or "")))


def blanked_attributes(storage: Any) -> list[str]:
    """The attributes that `redact_storage` blanked in a text, one entry for each, as `name="value"` with the name in lower case and double quotes
    (`ri:account-id="hidden"`, `data-userkey="hidden"`, `ri:space-key="[hidden]"`). It reads them with the pattern that `has_blanked_mentions` asks, so
    that what is blanked and what is counted as blanked are the one list of this module."""
    found = []
    for match in _BLANKED_ATTRIBUTE.finditer(str(storage or "")):
        name, _, value = match.group(0).partition("=")
        found.append(f'{name.strip().lower()}="{value.strip()[1:-1]}"')
    return found


def looks_like_user(value: Any) -> bool:
    """A user object, also a partial one that holds only a name (`ownedBy: {displayName: ...}`)."""
    if not isinstance(value, dict):
        return False
    return ("accountId" in value and any(key in value for key in _PERSON_NAME_KEYS)) or any(isinstance(value.get(key), str) for key in ("displayName", "publicName"))


def strip_users(value: Any) -> Any:
    """Replace every user object and person id in raw JSON with a marker and redact all text: the people of an answer (also a task's `assignedTo`, a
    `principal`), the mention of a page in the other body formats (an ADF `mention` node, `data-account-id`), and the key and the name of a personal space."""
    if looks_like_user(value):
        return {"hidden": True}
    if isinstance(value, dict):
        if value.get("type") == "mention" and isinstance(value.get("attrs"), dict):
            value = {**value, "attrs": {"hidden": True}}
        elif isinstance(value.get("key"), str) and "name" in value and is_personal_space(value["key"], value.get("type")):
            value = {**value, "key": HIDDEN, "name": PERSONAL_SPACE, "description": "", "_links": {}}
        return {key: _stripped(key, child) for key, child in value.items()}
    if isinstance(value, list):
        return [strip_users(child) for child in value]
    if isinstance(value, str):
        text = redact_storage(value)
        return redact_address(text) if text.startswith(("/", "http://", "https://")) else text
    return value


def _stripped(key: str, child: Any) -> Any:
    if key in _PERSON_KEYS and isinstance(child, str):
        return HIDDEN
    if key == "principal" and isinstance(child, dict):
        return {**{name: strip_users(part) for name, part in child.items() if name != "id"}, "id": HIDDEN}
    return strip_users(child)


def hide_version(version: VersionInfo | None) -> VersionInfo | None:
    return None if version is None else replace(version, author=None, message=redact_text(version.message))


def hide_users(page: Page) -> Page:
    """A copy of the page without people and with redacted text."""
    return replace(
        page,
        title=redact_text(page.title),
        url=page_address(page.url, page.id),
        space_key=HIDDEN if is_personal_space(page.space_key) else page.space_key,
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
    return replace(
        hit,
        title=redact_text(hit.title),
        url=page_address(hit.url, hit.id),
        space_key=HIDDEN if is_personal_space(hit.space_key) else hit.space_key,
        excerpt="",
        path=redact_text(hit.path),
    )


def is_personal_space(key: Any, space_type: Any = "") -> bool:
    """A personal space is the space of one person: Confluence types it `personal` and keys it by `~` and the account id of its owner."""
    return str(space_type or "") == "personal" or str(key or "").startswith("~")


def hide_space(space: Space) -> Space:
    """A space as it may be printed when people are not shown, for every command that prints one (`spaces`, `space`, `use`, `permissions`, `space-access`).

    A personal space is named after its owner and keyed by the owner's account id, and its description and address say who that is: it comes out
    as an entry with the key `[hidden]` and the name `[personal space]`, so that it still counts and can be told by its id, type, status, home page
    and date, which name nobody. Any other space keeps its key and has the e-mail addresses and personal links of its name and description redacted."""
    if is_personal_space(space.key, space.type):
        return replace(space, key=HIDDEN, name=PERSONAL_SPACE, description="", url="")
    return replace(space, name=redact_text(space.name), description=redact_text(space.description))


__all__ = [
    "HIDDEN",
    "PERSONAL_SPACE",
    "blanked_attributes",
    "hide_comment_author",
    "hide_hit",
    "hide_ref",
    "hide_space",
    "hide_users",
    "has_blanked_mentions",
    "hide_version",
    "has_redaction_marker",
    "is_personal_space",
    "looks_like_user",
    "mentions_people",
    "normalize_newlines",
    "page_address",
    "redact_address",
    "redact_query",
    "redact_storage",
    "redact_text",
    "strip_users",
]
