"""People, as `conflu users` finds them: who they are, and how a text or an account id becomes a question that Confluence can answer.

A person is data about a person: nothing here may reach the output of the CLI unless the person at the terminal asked for people.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .cql import quote
from .errors import UsageError, ValidationError

MAX_QUERY = 256  # characters of a name to search for: a longer text is no name, and CQL has limits of its own
MAX_ACCOUNT_IDS = 250  # what one call of the bulk lookup takes
_ACCOUNT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9:_.-]{0,127}")
_SEPARATORS = re.compile(r"[\s,;]+")


@dataclass(frozen=True)
class Person:
    account_id: str
    display_name: str = ""
    email: str = ""  # empty when Confluence does not say: it depends on the privacy setting of the person
    account_type: str = ""  # atlassian, app, customer, unknown, or empty when Confluence does not say


@dataclass(frozen=True)
class PeoplePage:
    """One answer of a search for people: they come with an offset, as the answers of the older API do."""

    people: list[Person]
    total: int = 0
    start: int = 0
    limit: int = 0
    size: int = 0  # how many results the answer held, also those that name nobody and are not in `people`: the next page starts at start + size


def search_query(text: str) -> str:
    """The CQL of a search for people by name: `user.fullname ~ "alex"`.

    The text goes into a CQL string with its quote and backslash escaped, so that whatever it holds stays a text: `a" OR user = "b` finds
    nobody of that name and changes no other part of the query."""
    words = " ".join((text or "").split())
    if not words:
        raise UsageError("Nothing to search for.", hint="Give part of a name: `conflu users search alex --with-users`.")
    if len(words) > MAX_QUERY:
        raise ValidationError(f"'{words[:20]}...' is too long for a name to search for.", hint=f"At most {MAX_QUERY} characters.")
    return f"user.fullname ~ {quote(words)}"


def parse_account_ids(text: str) -> list[str]:
    """The account ids in a text: separated by blanks, commas or semicolons, each once, in the order given."""
    found = [part for part in _SEPARATORS.split((text or "").strip()) if part]
    if not found:
        raise UsageError("No account id given.", hint="For example `conflu users lookup 5b10ac8d82e05b22cc7d4ef5 --with-users`.")
    for part in found:
        if not _ACCOUNT_ID.fullmatch(part):
            raise ValidationError(
                f"Not an account id: {part[:60]}",
                hint="An account id is made of letters, digits, colons and dashes, such as 5b10ac8d82e05b22cc7d4ef5 or "
                "557058:00000000-0000-4000-8000-000000000001. `conflu users search NAME --with-users` finds one by name.",
            )
    unique = list(dict.fromkeys(found))
    if len(unique) > MAX_ACCOUNT_IDS:
        raise UsageError(f"{len(unique)} account ids: at most {MAX_ACCOUNT_IDS} can be looked up at a time.", hint="Split the list.")
    return unique
