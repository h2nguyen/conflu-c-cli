"""Use cases around labels."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..domain.drafts import normalize_labels
from ..domain.errors import ValidationError
from ..domain.model import Label, parse_page_id
from ..domain.payloads import label_payload
from .ports import ConfluenceGateway


class ListLabels:
    def __init__(self, gateway: ConfluenceGateway) -> None:
        self._gateway = gateway

    def execute(self, ref: str) -> list[Label]:
        return self._gateway.list_labels(parse_page_id(ref))


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
        current = self._gateway.list_labels(page_id)  # also proves that the page exists
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
