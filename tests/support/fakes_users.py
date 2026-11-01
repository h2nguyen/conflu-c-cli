"""The in-memory Confluence for looking up people: a mixin of `FakeGateway` (`_init_users` sets up its state).

The people are the `users` of the fake (Alex Example to begin with): a test adds `fake.users["id"] = User(...)`, and `account_types["id"]` for one that is
not an `atlassian` account. A search by name finds those whose display name holds the text, as the `~` of CQL does, case aside.
"""
from __future__ import annotations

import re
from typing import Sequence

from conflu_c_cli.domain.errors import RejectedError
from conflu_c_cli.domain.model import User
from conflu_c_cli.domain.users import PeoplePage, Person

_FULLNAME = re.compile(r'user\.fullname\s*~\s*"((?:\\.|[^"\\])*)"')  # a quote and a backslash inside are escaped with a backslash


class FakeUsers:
    def _init_users(self) -> None:
        self.account_types: dict[str, str] = {}  # by account id; `atlassian` when a test says nothing

    def _person(self, user: User) -> Person:
        return Person(user.account_id, user.display_name, user.email, self.account_types.get(user.account_id, "atlassian"))

    def search_people(self, cql: str, *, limit: int = 25, start: int = 0) -> PeoplePage:
        self._enter("search_people", cql, limit, start)
        match = _FULLNAME.fullmatch(cql.strip())
        if match is None:
            raise RejectedError(f"Confluence refused the request (HTTP 400): Could not parse cql: {cql}")
        wanted = re.sub(r"\\(.)", r"\1", match.group(1)).casefold()
        found = [self._person(user) for user in self.users.values() if wanted in user.display_name.casefold()]
        shown = found[start : start + min(limit, self.page_cap)]
        return PeoplePage(shown, len(found), start, limit, len(shown))

    def lookup_people(self, account_ids: Sequence[str]) -> list[Person]:
        self._enter("lookup_people", tuple(account_ids))
        return [self._person(self.users[account]) for account in dict.fromkeys(account_ids) if account in self.users]
