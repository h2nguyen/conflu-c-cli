"""What Confluence's JSON means for the labels used in a space, besides the labels of a page: the answers as domain objects."""
from __future__ import annotations

from typing import Any

from ...domain.model import Label
from . import confluence_mapper as mapper


def labels_of(data: Any) -> list[Label]:
    """The labels of an answer that lists them (`results`: id, name, prefix); a label without a name is left out."""
    return [label for label in map(mapper.label_from, mapper.results_of(data)) if label.name]
