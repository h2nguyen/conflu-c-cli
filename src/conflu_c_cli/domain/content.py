"""The kinds of content that sit in the tree of a space, and how a person names one.

A page, a blog post, a folder, a whiteboard, a database and a smart link all have an id, and the ids of the different kinds are numbers of
the same sequence: from the id alone nobody can tell which kind it is. Confluence says so when it is asked (`ConfluenceGateway.content_types`),
and the REST API v2 has one collection for each kind (`/pages/{id}`, `/folders/{id}` ...), so what the CLI asks for depends on the kind.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import ValidationError


@dataclass(frozen=True)
class Kind:
    name: str  # what Confluence calls it (`page`, `folder` ...)
    collection: str  # the collection of the v2 API: /api/v2/<collection>/{id}
    label: str  # for a sentence: "a folder"
    noun: str = ""  # without the article: "folder"
    command: str = ""  # the command that shows one: `conflu folder ID`


PAGE = Kind("page", "pages", "a page", "page", "page")
BLOGPOST = Kind("blogpost", "blogposts", "a blog post", "blog post", "blogpost")
FOLDER = Kind("folder", "folders", "a folder", "folder", "folder")
WHITEBOARD = Kind("whiteboard", "whiteboards", "a whiteboard", "whiteboard", "whiteboard")
DATABASE = Kind("database", "databases", "a database", "database", "database")
EMBED = Kind("embed", "embeds", "a smart link", "smart link", "smartlink")

KINDS = (PAGE, BLOGPOST, FOLDER, WHITEBOARD, DATABASE, EMBED)
# The kinds that can hold other content: the parent of a page, the start of a tree.
CONTAINERS = (PAGE, FOLDER, WHITEBOARD, DATABASE, EMBED)
# What is in the tree and is no page: each has its own read command and its own collection.
OTHER_CONTAINERS = tuple(kind for kind in CONTAINERS if kind is not PAGE)
CONTAINERS_SENTENCE = ", ".join(kind.label for kind in CONTAINERS[:-1]) + " or " + CONTAINERS[-1].label  # a page, a folder, ... or a smart link
CONTAINER_NOUNS = ", ".join(kind.noun for kind in CONTAINERS[:-1]) + " or " + CONTAINERS[-1].noun  # page, folder, ... or smart link

# What `POST /api/v2/content/convert-ids-to-types` says for content that is no kind of the tree.
OTHER_TYPES = {
    "footer-comment": "a footer comment",
    "inline-comment": "an inline comment",
    "attachment": "an attachment",
    "custom": "a piece of custom content of an app",
}

_ID = re.compile(r"^[0-9]{1,19}$")
_ATTACHMENT = re.compile(r"^att[0-9]+$")  # the id of an attachment, which is no content of the tree
_IN_URL = re.compile(
    r"/(?:pages/(?:[A-Za-z0-9-]+/)?|folder/|whiteboard/|database/|embed/|blog/[0-9]{4}/[0-9]{1,2}/[0-9]{1,2}/)([0-9]{1,19})(?:[/?#]|$)"
)
_ID_PARAMETER = re.compile(r"[?&](?:pageId|contentId)=([0-9]{1,19})(?:[&#]|$)")
_TINY = re.compile(r"/wiki/x/[A-Za-z0-9_-]+")


def kind_named(name: str) -> Kind | None:
    """The kind that Confluence calls `name` (`folder`), or None for one that is no kind of the tree (`footer-comment`)."""
    return next((kind for kind in KINDS if kind.name == name), None)


def describe(type_name: str | None) -> str:
    """`a folder`, `a footer comment`, or `nothing that this account can see` for what Confluence has no type for."""
    kind = kind_named(type_name or "")
    if kind is not None:
        return kind.label
    return OTHER_TYPES.get(type_name or "", f"content of the type {type_name}" if type_name else "nothing that this account can see")


def noun_of(type_name: str) -> str:
    """`folder`, `smart link`: the kind without its article, for a sentence that already has one."""
    kind = kind_named(type_name)
    return kind.noun if kind is not None else type_name


def point_at(type_name: str, content_id: str, title: str = "", *, width: int = 60) -> str:
    """`the folder 'Guides' [7001]`: how a message names one piece of content. The title is on one line and cut at `width` characters."""
    text = " ".join(str(title or "").split())
    shown = text if len(text) <= width else text[: width - 3].rstrip() + "..."
    return f"the {noun_of(type_name)} " + (f"'{shown}' " if shown else "") + f"[{content_id}]"


def parse_content_id(text: str) -> str:
    """The id of a page, a blog post, a folder, a whiteboard, a database or a smart link: the number itself, or the address of it as copied from
    the browser (`.../wiki/spaces/ENG/folder/123`, `.../pages/123/Title`, `.../blog/2026/10/15/123/Title`)."""
    value = (text or "").strip()
    if _ID.match(value):
        return value
    for pattern in (_IN_URL, _ID_PARAMETER):
        match = pattern.search(value)
        if match:
            return match.group(1)
    if _TINY.search(value):
        raise ValidationError(
            f"A short link cannot be resolved offline: {value}",
            hint="Open it in the browser and copy the full address, or use the numeric id.",
        )
    if _ATTACHMENT.match(value):
        raise ValidationError(
            f"{value} is an attachment, not a {CONTAINER_NOUNS}.",
            hint="An attachment belongs to a page: `conflu attachments PAGE` lists the attachments of a page.",
        )
    raise ValidationError(
        f"Invalid id: {value or '<missing>'}",
        hint="An id is a number such as 123456; the address of the page, folder or blog post, copied from the browser, works too.",
    )
