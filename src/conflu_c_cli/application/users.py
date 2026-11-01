"""Use cases around looking up people.

This is the one place where people are the point, and so the one that does nothing without `--with-users`, and nothing at all under the privacy
policy (CONFLUENCE_HIDE_USERS=true). It is no way around that policy: it asks for the same permission as every other command.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain.errors import UsageError, ValidationError
from ..domain.users import Person, parse_account_ids, search_query
from .ports import ConfluenceGateway
from .services import Services
from .settings import Settings

SEARCH_PAGE = 50  # people per request when every result is wanted
MAX_PEOPLE = 5000  # a stop for a search that finds more than anybody can use; the caller is told when it was reached


def ensure_people_allowed(settings: Settings, with_users: bool, command: str) -> None:
    """Refuses the command that lists people, unless people may be shown (the policy) and were asked for (`--with-users`)."""
    if settings.hide_users:
        raise ValidationError(
            f"CONFLUENCE_HIDE_USERS=true: people are not printed, `{command}` is not available.",
            hint="Unset CONFLUENCE_HIDE_USERS if you need to see people.",
        )
    if not with_users:
        raise UsageError(
            f"`{command}` lists people.",
            hint="Add --with-users to show them. It is refused when CONFLUENCE_HIDE_USERS=true.",
        )


@dataclass
class UserSearch:
    query: str  # the words that were searched for
    cql: str  # the query that was sent: the text, quoted for CQL
    people: list[Person]
    total: int  # how many people Confluence says fit
    start: int  # the position of the first one that was asked for
    truncated: bool = False  # the search was cut short at MAX_PEOPLE
    next_start: int | None = None  # where the next request goes on; None on the last one, and when every result was asked for


class SearchUsers:
    """People whose name holds a text."""

    def __init__(self, gateway: ConfluenceGateway, settings: Settings) -> None:
        self._gateway = gateway
        self._settings = settings

    def execute(self, text: str, *, with_users: bool = False, limit: int = 25, start: int = 0, fetch_everything: bool = False) -> UserSearch:
        ensure_people_allowed(self._settings, with_users, "conflu users search")
        if not 1 <= limit <= 250:
            raise UsageError("--limit must be between 1 and 250.")
        if start < 0:
            raise UsageError("--start must not be negative.")
        cql = search_query(text)
        words = " ".join(text.split())
        if not fetch_everything:
            page = self._gateway.search_people(cql, limit=limit, start=start)
            end = start + page.size
            return UserSearch(words, cql, _distinct(page.people), page.total, start, next_start=end if page.size and end < page.total else None)
        found: list[Person] = []
        total, position, truncated = 0, 0, False
        while True:
            page = self._gateway.search_people(cql, limit=SEARCH_PAGE, start=position)
            total = page.total
            found.extend(page.people)
            position += page.size
            if not page.size or position >= total:
                break
            if position >= MAX_PEOPLE:
                truncated = True
                break
        return UserSearch(words, cql, _distinct(found), total, 0, truncated)


def _distinct(people: list[Person]) -> list[Person]:
    return list({person.account_id: person for person in people}.values())


@dataclass
class UserLookup:
    requested: int  # how many different account ids were asked for
    people: list[Person]  # in the order of the ids that were asked for
    not_found: list[str]  # the ids that Confluence did not describe: unknown, or not a person this account may look up


class LookupUsers:
    """The people behind some account ids."""

    def __init__(self, gateway: ConfluenceGateway, settings: Settings) -> None:
        self._gateway = gateway
        self._settings = settings

    def execute(self, text: str, *, with_users: bool = False) -> UserLookup:
        ensure_people_allowed(self._settings, with_users, "conflu users lookup")
        ids = parse_account_ids(text)
        known = {person.account_id: person for person in self._gateway.lookup_people(ids)}
        return UserLookup(len(ids), [known[item] for item in ids if item in known], [item for item in ids if item not in known])


@dataclass
class UsersUseCases:
    """The use cases of the area, reached as `app.users.<name>`."""

    search: SearchUsers
    lookup: LookupUsers


def build(services: Services) -> UsersUseCases:
    return UsersUseCases(
        search=SearchUsers(services.gateway, services.settings),
        lookup=LookupUsers(services.gateway, services.settings),
    )
