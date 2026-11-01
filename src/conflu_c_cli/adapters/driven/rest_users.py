"""Looking up people: the REST calls. A mixin of `RestConfluenceGateway`, which provides `_call`, `_finish`, `_transport`, `_settings`,
`_next_cursor` and `_base`."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Sequence

from .confluence_mapper import results_of
from .rest_support import V1, V2, query

# The models and the mapper of this area are imported where they are used, so that a command that never reads it does not load them (tests/test_startup.py).
if TYPE_CHECKING:
    from ...domain.users import PeoplePage, Person

# The calls of this area that use the v1 API, each with why v2 does not do (see docs/reference/compatibility.md).
V1_CALLS: dict[str, str] = {
    "GET /rest/api/search/user": "v2 has no search for people: its bulk lookup only answers for account ids that are known already.",
}


class RestUsers:
    def search_people(self, cql: str, *, limit: int = 25, start: int = 0) -> PeoplePage:
        from ...domain.users import PeoplePage
        from . import map_users as users_mapper

        data: Any = self._call("GET", f"{V1}/search/user?{query(cql=cql, limit=limit, start=start)}")
        results = results_of(data)
        people = [person for person in map(users_mapper.person_from_result, results) if person is not None]
        listed = data if isinstance(data, dict) else {}
        total = listed.get("totalSize")
        known = total if isinstance(total, int) and not isinstance(total, bool) else start + len(results)  # what the answer shows to exist, when it does not say
        return PeoplePage(people, known, start, limit, len(results))

    def lookup_people(self, account_ids: Sequence[str]) -> list[Person]:
        from ...domain.users import MAX_ACCOUNT_IDS
        from . import map_users as users_mapper

        ids = list(dict.fromkeys(account_ids))
        found: list[Person] = []
        for start in range(0, len(ids), MAX_ACCOUNT_IDS):
            data = self._call("POST", f"{V2}/users-bulk", {"accountIds": ids[start : start + MAX_ACCOUNT_IDS]})
            found.extend(person for person in map(users_mapper.person_from, results_of(data)) if person is not None)
        return found
