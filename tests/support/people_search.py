"""A search index that lists people and spaces besides pages, with the raw answer of each result as the older API shapes it: what the tests of
`conflu search --cql 'type = user ...'` need, since the person and the personal space are named after their owner."""
from __future__ import annotations

from typing import Any

from conflu_c_cli.domain.model import SearchHit, SearchPage

from .fakes import ACCOUNT, BASE, FakeGateway

OWNER = "Alex Example"
PERSONAL_KEY = f"~{ACCOUNT}"
PERSON = SearchHit("", "user", OWNER, "", f"{BASE}/people/{ACCOUNT}", "", "2026-10-01T08:00:00.000Z")
PERSONAL_SPACE = SearchHit("", "space", OWNER, PERSONAL_KEY, f"{BASE}/spaces/{PERSONAL_KEY}/overview", "", "2026-09-01T08:00:00.000Z")
ENGINEERING = SearchHit("", "space", "Engineering", "ENG", f"{BASE}/spaces/ENG/overview", "", "2026-09-01T08:00:00.000Z")
PAGE = SearchHit("2002", "page", "Release notes", "ENG", f"{BASE}/spaces/ENG/pages/2002/Release+notes", "the october notes", "2026-10-10T09:00:00.000Z", "Engineering Home", ("release",), 3)
PAGE_OF_THE_OWNER = SearchHit("9001", "page", "My notes", PERSONAL_KEY, f"{BASE}/spaces/{PERSONAL_KEY}/pages/9001/My+notes", "", "2026-10-11T09:00:00.000Z", "", (), 1)


def raw_of(hit: SearchHit) -> dict[str, Any]:
    """The result as the search of the older API writes it."""
    relative = hit.url.removeprefix(BASE)
    common = {"title": hit.title, "excerpt": hit.excerpt, "url": relative, "lastModified": hit.last_modified, "breadcrumbs": [], "score": 1.0}
    if hit.type == "user":
        return {**common, "user": {"type": "known", "accountId": ACCOUNT, "displayName": hit.title, "publicName": hit.title}, "entityType": "user"}
    if hit.type == "space":
        space = {"id": 100, "key": hit.space_key, "name": hit.title, "type": "personal" if hit.space_key.startswith("~") else "global", "status": "current"}
        return {**common, "space": space, "resultGlobalContainer": {"title": hit.title, "displayUrl": f"/spaces/{hit.space_key}"}, "entityType": "space"}
    container = OWNER if hit.space_key.startswith("~") else "Engineering"
    content = {"id": hit.id, "type": hit.type, "title": hit.title, "_links": {"webui": relative}}
    return {
        **common,
        "content": content,
        "resultGlobalContainer": {"title": container, "displayUrl": f"/spaces/{hit.space_key}"},
        "entityType": "content",
    }


class PeopleGateway(FakeGateway):
    """The fixed hits `hits`, in this order, with their raw answers. The page size is the one asked for."""

    def __init__(self, *hits: SearchHit) -> None:
        super().__init__()
        self.search_hits = list(hits or (PERSON, PAGE, PERSONAL_SPACE, ENGINEERING, PAGE_OF_THE_OWNER))

    def search(self, cql: str, *, limit: int = 25, start: int = 0) -> SearchPage:
        self._enter("search", cql, limit, start)
        shown = self.search_hits[start : start + limit]
        return SearchPage(shown, len(self.search_hits), start, limit, [raw_of(hit) for hit in shown])
