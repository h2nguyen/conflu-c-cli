"""A page named by its id, by the address copied from the browser, or by a `page:` reference as the Markdown copy of a page writes it."""
from __future__ import annotations

from typing import Any

from ..domain.errors import NotFoundError, ValidationError
from ..domain.model import Space, parse_page_id, parse_space_key
from .ports import ConfluenceGateway
from .settings import Settings

PAGE_REFERENCE = "page:"


def _is_space_key(text: str) -> bool:
    try:
        parse_space_key(text)
    except ValidationError:
        return False
    return True


def _find(gateway: ConfluenceGateway, space: Space | None, title: str) -> list[Any]:
    return list(gateway.list_pages(space_id=space.id if space else "", title=title, status="current", limit=10).items)


def _default_space(gateway: ConfluenceGateway, settings: Settings, space: str) -> Space | None:
    key = space or settings.space
    return gateway.get_space(parse_space_key(key)) if key else None


def resolve_page_ref(gateway: ConfluenceGateway, settings: Settings, ref: str, *, space: str = "") -> str:
    """The id of the page. `page:KEY/Title` and `page:Title` (in `space`, else in the current space, else anywhere on the site)
    are the links that `conflu page` shows as `[text](page:...)`: this is how a reader follows one."""
    text = (ref or "").strip()
    if not text.casefold().startswith(PAGE_REFERENCE):
        return parse_page_id(text)
    title = text[len(PAGE_REFERENCE) :].strip()
    if not title:
        raise ValidationError("A `page:` reference needs a title.", hint="Write page:Title, or page:KEY/Title to name the space.")
    chosen: Space | None = None
    named = False  # the text began with the key of an existing space
    head, slash, tail = title.partition("/")
    if slash and tail.strip() and _is_space_key(head):
        try:
            chosen, named = gateway.get_space(head), True
        except NotFoundError:
            chosen = None  # `CI/CD pipeline` is a title, and CI is not a space
    whole = title
    if named:
        title = tail.strip()
    elif chosen is None:
        chosen = _default_space(gateway, settings, space)
    found = _find(gateway, chosen, title)
    if not found and named:
        # CI is a space but holds no page `CD pipeline`: the whole text may be the title of a page in the default scope. A page
        # of the named space wins when there is one, so a title that starts with a space key and a slash then needs the page id.
        other = _default_space(gateway, settings, space)
        elsewhere = _find(gateway, other, whole)
        if elsewhere:
            found, chosen, title = elsewhere, other, whole
    where = f" in the space {chosen.key}" if chosen else " on this site"
    if not found:
        raise NotFoundError(
            f"No current page is titled {title!r}{where}.",
            hint="Check the spelling, or find it with `conflu search`; name the space with page:KEY/Title or --space KEY.",
        )
    if len(found) > 1:
        raise ValidationError(
            f"{len(found)} pages are titled {title!r}{where}: " + ", ".join(f"{page.space_key} {page.id}" for page in found) + ".",
            hint="Name the space (page:KEY/Title or --space KEY), or use the page id.",
        )
    return found[0].id
