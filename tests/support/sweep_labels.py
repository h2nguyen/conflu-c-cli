"""The sweep lines of the labels used in a space, besides the labels of a page: see sweeps.py. Each module runs its lines in order against a mock of its own.

The mock starts with the labels `release` and `notes` on page 2002 and `adr` on page 2004, all in the space ENG; the space DOCS has none."""
from __future__ import annotations

from .sweeps import line

LINES = (
    # the labels that the content of a space carries: a piece, the next piece, all of them
    line("labels", "--space", "ENG"),
    line("labels", "--space", "ENG", "--limit", "1", "--cursor", "2"),
    line("labels", "--space", "ENG", "--all", "--select", "name", "--format", "tsv"),
    line("labels", "--space", "eng", "--all", "--json"),
    line("labels", "--space", "DOCS"),
    line("labels", "--space", "NOPE", code=4),
    line("labels", "--space", "E N G", code=1),
    line("labels", code=2),  # neither a page nor a space
    line("labels", "2002", "--space", "ENG", code=2),  # both
    # the labels of a page, and adding and removing them
    line("labels", "2002"),
    line("labels", "2002", "--select", "name", "--format", "md"),
    line("label", "2002", "--add", "swept", "--dry-run"),
    line("label", "2002", "--add", "swept", "--remove", "release"),
    line("labels", "--space", "ENG", "--all"),  # the new label is one of the space now
    line("label", "2002", "--remove", "swept"),
)
