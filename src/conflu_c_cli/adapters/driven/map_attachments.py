"""What Confluence's JSON means for the files attached to a page: versions, labels and the text of a document: the answers as domain objects."""
from __future__ import annotations

from typing import Any

from ...domain.model import Attachment, Label, VersionInfo
from . import confluence_mapper as mapper


def versions_of(data: Any) -> list[VersionInfo]:
    """The versions of an answer that lists them (`results`: number, createdAt, message, minorEdit, authorId); an entry without a number is left out."""
    return [version for version in map(mapper.version_from, mapper.results_of(data)) if version is not None and version.number]


def labels_of(data: Any) -> list[Label]:
    """The labels of an answer that lists them (`results`: id, name, prefix); a label without a name is left out."""
    return [label for label in map(mapper.label_from, mapper.results_of(data)) if label.name]


def attachments_of(data: Any) -> list[Attachment]:
    """The attachments of an answer that lists them (`results`), those of a page and those of a blog post alike."""
    return [mapper.attachment_from(item) for item in mapper.results_of(data)]
