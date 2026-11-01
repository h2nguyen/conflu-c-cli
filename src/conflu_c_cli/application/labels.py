"""Use cases around labels."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..domain.drafts import normalize_labels
from ..domain.errors import NotFoundError, ValidationError
from ..domain.model import Chunk, Label, Space, parse_page_id, parse_space_key
from ..domain.payloads import label_payload
from ..domain.privacy import hide_space
from .containers import not_a_page
from .paging import PAGE_SIZE, fetch_all
from .ports import ConfluenceGateway
from .services import Services


def read_labels(gateway: ConfluenceGateway, page_id: str) -> list[Label]:
    """The labels of the page. An id that is a folder, a blog post or another kind of content is a not-found error whose hint says what it is."""
    try:
        return gateway.list_labels(page_id)
    except NotFoundError as error:
        raise not_a_page(gateway, page_id, error) from error


class ListLabels:
    def __init__(self, gateway: ConfluenceGateway) -> None:
        self._gateway = gateway

    def execute(self, ref: str) -> list[Label]:
        return read_labels(self._gateway, parse_page_id(ref))


@dataclass
class LabelsResult:
    page_id: str
    added: list[str]
    removed: list[str]
    labels: list[Label]  # after the change; the current ones in a dry run
    dry_run: bool
    payload: dict[str, Any]


class ChangeLabels:
    def __init__(self, gateway: ConfluenceGateway) -> None:
        self._gateway = gateway

    def execute(self, ref: str, *, add: list[str], remove: list[str], dry_run: bool = False) -> LabelsResult:
        page_id = parse_page_id(ref)
        to_add, to_remove = normalize_labels(add), normalize_labels(remove)
        if not to_add and not to_remove:
            raise ValidationError("No labels given.", hint="Pass --add a,b and/or --remove c.")
        clash = sorted(set(to_add) & set(to_remove))
        if clash:
            raise ValidationError(f"{', '.join(clash)} is in --add and in --remove.")
        current = read_labels(self._gateway, page_id)  # also proves that the page exists
        present = {label.name for label in current}
        will_add = [name for name in to_add if name not in present]
        will_remove = [name for name in to_remove if name in present]
        payload = {"add": label_payload(will_add), "remove": will_remove}
        if dry_run:
            return LabelsResult(page_id, will_add, will_remove, current, True, payload)
        if will_add:
            self._gateway.add_labels(page_id, payload["add"])
        for name in will_remove:
            self._gateway.remove_label(page_id, name)
        labels = self._gateway.list_labels(page_id) if will_add or will_remove else current
        return LabelsResult(page_id, will_add, will_remove, labels, False, payload)


@dataclass
class SpaceLabels:
    space: Space  # as it may be printed (`privacy.hide_space`): the key of a personal space is `[hidden]`
    labels: list[Label]
    next_cursor: str = ""
    truncated: bool = False


class ListSpaceLabels:
    """The labels that the content of a space carries (not the labels of the space itself): a piece of the list, or all of it."""

    def __init__(self, gateway: ConfluenceGateway) -> None:
        self._gateway = gateway

    def execute(self, key: str, *, limit: int = 25, cursor: str = "", fetch_everything: bool = False) -> SpaceLabels:
        space = self._gateway.get_space(parse_space_key(key))

        def read(next_cursor: str) -> Chunk[Label]:
            return self._gateway.list_space_labels(space.id, limit=PAGE_SIZE if fetch_everything else limit, cursor=next_cursor)

        shown = hide_space(space)
        if fetch_everything:
            labels, truncated = fetch_all(read)
            return SpaceLabels(shown, labels, "", truncated)
        chunk = read(cursor)
        return SpaceLabels(shown, chunk.items, chunk.cursor)


@dataclass
class LabelsUseCases:
    """The use cases that are not fields of `Application` by themselves: the labels used in a space. Reached as `app.labels.<name>`."""

    in_space: ListSpaceLabels


def build(services: Services) -> LabelsUseCases:
    return LabelsUseCases(in_space=ListSpaceLabels(services.gateway))
