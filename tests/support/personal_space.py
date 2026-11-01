"""The personal space that the sweeps share.

Confluence keys a personal space by `~` and the account id of its owner and names it after them, so a command that prints its key, its name, an
address with the key in it or a path made from either shows a person. The privacy sweep (tests/integration/test_privacy_sweep.py) looks for the account id
and for the name in everything the lines print; the modules that have lines about a personal space (`sweep_core`, `sweep_access`, `sweep_personal`) make it
with `add_personal_space`, and a mock of its own each (see `PREPARE` in sweep_runner.py), so that the other tests, which count the spaces of the default data,
do not see it.
"""
from __future__ import annotations

from typing import Any

PERSONAL = "~5b10ac8d82e05b22cc7d4ef5"  # `~` and the account id that the fixtures use
OWNER = "Alex Example"  # its name: the name of its owner
HOME_TITLE = "Start"


def add_personal_space(mock: Any) -> tuple[str, str]:
    """The personal space of a mock, made when it is not there yet: `(its id, the id of its home page)`. Its home page has a title of its own: Confluence
    titles the home page of a personal space with the name of its owner, which stays the documented limit of the rule that keeps people out (a title is free
    text and cannot be told from a name), and no line of a sweep could print that."""
    space = mock._space_by_key(PERSONAL)
    space_id = space["id"] if space else mock.add_space(PERSONAL, OWNER, "personal")
    mock.spaces[space_id]["description"] = "Notes of the owner"
    home = mock.spaces[space_id]["homepageId"]
    mock.pages[home]["title"] = HOME_TITLE
    return space_id, home
