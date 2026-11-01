"""The sweep lines of the watches of the user on pages and spaces: see sweeps.py. Each module runs its lines in order against a mock of its own.

Nothing is watched at the start. The lines reach every call of `V1_CALLS`: the status, the watch and the stop, for content and for a space."""
from __future__ import annotations

from .sweeps import line

LINES = (
    line("watching", "2002"),
    line("watching", "--space", "ENG"),
    line("watch", "2002", "--dry-run"),
    line("watch", "2002"),
    line("watch", "2002"),  # as asked already: nothing is sent
    line("watching", "2002", "--json"),
    line("watch", "2002", "--remove", "--dry-run"),
    line("watch", "2002", "--remove"),
    line("watch", "--space", "ENG", "--dry-run"),
    line("watch", "--space", "ENG"),
    line("watching", "--space", "ENG"),
    line("watch", "--space", "ENG", "--remove"),
    line("watching", "999999", code=4),  # no such content
    line("watch", "--space", "NOSUCH", code=4),  # no such space
    line("watch", "2002", "--space", "ENG", code=2),  # a page or a space, not both
    line("watch", code=2),  # a change names what it changes
)
