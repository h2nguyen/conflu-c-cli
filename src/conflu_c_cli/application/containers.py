"""What an id is, when it may be more than a page: the parent of a new page, the target of a move, the start of a tree.

A page is asked for first, as it was before folders: one request, and nothing else for the common case. Only when Confluence says that there
is no such page does the id get a second look: `content_types` says what it is, and the collection of that kind says the rest.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from ..domain.content import CONTAINER_NOUNS, CONTAINERS_SENTENCE, OTHER_CONTAINERS, describe, kind_named, noun_of, parse_content_id
from ..domain.errors import ConfluCliError, NotFoundError, UsageError, ValidationError
from ..domain.model import Page, PageRef, Space
from ..domain.privacy import redact_text
from ..domain.structure import Container, shown_key
from .paging import fetch_all
from .ports import ConfluenceGateway

PARENT = "a parent"
TARGET = "the target of a move"
ROOT = "the start of a tree"

TITLES_AT_A_TIME = 100  # the ids of pages that one request names
_CONTAINER_NAMES = {kind.name for kind in OTHER_CONTAINERS}


@dataclass(frozen=True)
class Located:
    """A page, a folder, a whiteboard, a database or a smart link that was found."""

    id: str
    type: str  # page | folder | whiteboard | database | embed
    title: str
    space_id: str
    parent_id: str = ""
    status: str = ""
    page: Page | None = None  # what was read, for a page (without its body)
    container: Container | None = None  # and for the others

    def ref(self) -> PageRef:
        """For a message or a result: the title is redacted."""
        return PageRef(self.id, redact_text(self.title), self.type, self.status)


def not_found(content_id: str) -> NotFoundError:
    return NotFoundError(
        f"No {CONTAINER_NOUNS} with the id {content_id} that this account can see.",
        hint="Check the id: the address of the content has it, and `conflu tree` and `conflu folder ID --children` list the ids below a page or a folder. "
        "Confluence says the same for content that does not exist and for content this account may not see.",
        details={"id": content_id},
    )


def not_the_kind(gateway: ConfluenceGateway, content_id: str, wanted: str, error: NotFoundError) -> ConfluCliError:
    """The error for an id that was asked for as one kind of content (`wanted`: `page`, `folder` ...) and is none: the same NotFoundError, with a hint
    that says what the id is and which command shows it (`123 is a folder, not a page: use `conflu folder 123``). It costs one more request, only on
    this path; when that cannot be answered, or the id is nothing known, the error stays as it was."""
    try:
        kind = gateway.content_types([content_id]).get(content_id)
    except ConfluCliError:
        return error
    if kind is None or kind == wanted:
        return error
    known = kind_named(kind)
    use = f": use `conflu {known.command} {content_id}`" if known is not None and known.command else ""
    return NotFoundError(error.message, hint=f"{content_id} is {describe(kind)}, not {describe(wanted)}{use}.", details={**error.details, "type": kind})


def not_a_page(gateway: ConfluenceGateway, content_id: str, error: NotFoundError) -> ConfluCliError:
    """What a command that reads a page raises when `GET /pages/{id}` found none: `raise not_a_page(gateway, page_id, error) from error`."""
    return not_the_kind(gateway, content_id, "page", error)


def space_key_of(gateway: ConfluenceGateway, container: Container) -> str:
    """The key of the space of a folder and the like: the address of the answer has it; when it does not, one more request, best effort."""
    if container.space_key or not container.space_id:
        return container.space_key
    try:
        return gateway.get_space_by_id(container.space_id).key
    except ConfluCliError:
        return ""


def with_titles(gateway: ConfluenceGateway, refs: Sequence[PageRef]) -> list[PageRef]:
    """The path with the titles that Confluence leaves out of an answer of ancestors (it names an id and a type): the pages in as few requests as
    possible, each folder, whiteboard, database or smart link with its own. What this account may not see has no title to show."""
    bare = [ref for ref in refs if not ref.title]
    if not bare:
        return list(refs)
    titles: dict[str, str] = {}
    pages = [ref.id for ref in bare if ref.type == "page"]
    for start in range(0, len(pages), TITLES_AT_A_TIME):
        wanted = pages[start : start + TITLES_AT_A_TIME]
        found, _ = fetch_all(lambda cursor, wanted=wanted: gateway.list_pages(ids=wanted, status="current", limit=TITLES_AT_A_TIME, cursor=cursor))
        titles.update({page.id: page.title for page in found})
    for ref in bare:
        if ref.type in _CONTAINER_NAMES:
            try:
                titles[ref.id] = gateway.get_container(ref.type, ref.id).title
            except NotFoundError:
                continue
    return [replace(ref, title=titles.get(ref.id, ref.title)) for ref in refs]


def named(value: str | None, what: str, hint: str) -> str | None:
    """An option as it was given: None when it was left out, the value as it is otherwise. One that was given and is empty is a mistake, never "left
    out": a writer would put its work at a place that nobody asked for, and `export --page ''` would export a whole space."""
    if value is not None and not value.strip():
        raise UsageError(f"The {what} is empty.", hint=hint)
    return value


def parent_named(parent: str | None) -> str | None:
    """The parent that a writer was given: None when none was named (the new content goes to the default place), the value as it is otherwise (see `named`)."""
    return named(parent, "parent", "Pass the id or the address of a page, a folder, a whiteboard, a database or a smart link, or leave out --parent.")


def ensure_same_space(parent: Located, space: Space, what: str) -> None:
    """New content goes into the space of its parent. `what` is what is created (`A page`, `A folder`)."""
    if parent.space_id and space.id and parent.space_id != space.id:
        raise ValidationError(
            f"The parent {noun_of(parent.type)} {parent.id} is not in space {shown_key(space.key, space.type)}.",
            hint=f"{what} is created in the space of its parent: pass that space, or another parent.",
        )


class ContainerResolver:
    """Finds what an id or an address names. With `remember`, what was found stays known for the life of the object: a folder of Markdown files
    that are published below one folder looks that folder up once, not once per file. Without it every call asks again."""

    def __init__(self, gateway: ConfluenceGateway, *, remember: bool = False) -> None:
        self._gateway = gateway
        self._remember = remember
        self._found: dict[str, Located] = {}

    def resolve(self, ref: str, purpose: str) -> Located:
        """`purpose` completes "... which cannot be <purpose>" when the id is a blog post, a comment or an attachment."""
        content_id = parse_content_id(ref)
        if not self._remember:
            return self._look_up(content_id, purpose)
        if content_id not in self._found:
            self._found[content_id] = self._look_up(content_id, purpose)
        return self._found[content_id]

    def _look_up(self, content_id: str, purpose: str) -> Located:
        try:
            page = self._gateway.get_page(content_id, with_body=False)
        except NotFoundError as error:
            return self._beyond_pages(content_id, purpose, error)
        return Located(page.id, "page", page.title, page.space_id, page.parent_id, page.status, page=page)

    def _beyond_pages(self, content_id: str, purpose: str, error: NotFoundError) -> Located:
        try:
            kind = self._gateway.content_types([content_id]).get(content_id)
        except ConfluCliError:
            # The second look is only there to say what else the id could be. When it cannot be made, the first answer stands, with its exit code
            # (4): the error of a helper call must not replace "not found" (`not_the_kind` does the same).
            raise error from None
        if kind is None:
            raise not_found(content_id) from error
        if kind == "page":
            raise error  # it is a page after all (it changed meanwhile, or this account cannot read it): the first answer stands
        if kind not in _CONTAINER_NAMES:
            raise ValidationError(
                f"{content_id} is {describe(kind)}, which cannot be {purpose}.",
                hint=f"Use {CONTAINERS_SENTENCE} instead: `conflu tree` and `conflu folder ID --children` show the ids.",
                details={"id": content_id, "type": kind},
            ) from error
        container = self._gateway.get_container(kind, content_id)
        return Located(container.id, kind, container.title, container.space_id, container.parent_id, container.status, container=container)

    def space_key(self, found: Located) -> str:
        """The key of the space of what was found; for a page, the one its address names (as `page` shows it), for the others the address or one more request."""
        if found.container is not None:
            return space_key_of(self._gateway, found.container)
        return found.page.space_key if found.page is not None else ""
