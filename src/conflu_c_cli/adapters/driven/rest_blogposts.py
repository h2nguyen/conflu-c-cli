"""Blog posts: the REST calls. A mixin of `RestConfluenceGateway`, which provides `_call`, `_finish`, `_transport`, `_settings`,
`_next_cursor` and `_base`."""
from __future__ import annotations

from typing import Any

from ...application.paging import fetch_all
from ...domain.model import Chunk, Comment, Label, Page
from . import confluence_mapper as mapper
from .rest_support import V1, V2, query, quote

# The models and the mapper of this area are imported where they are used, so that a command that never reads it does not load them (tests/test_startup.py).

# The calls of this area that use the v1 API, each with why v2 does not do (see docs/reference/compatibility.md).
V1_CALLS: dict[str, str] = {
    "POST /rest/api/content/{id}/label": "v2 reads the labels of content and has no call that adds one.",
}


def _with_query(path: str, **params: Any) -> str:
    text = query(**params)
    return f"{path}?{text}" if text else path


class RestBlogposts:
    def get_blogpost(self, blogpost_id: str, *, with_body: bool = True) -> Page:
        from . import map_blogposts

        data = self._call("GET", _with_query(f"{V2}/blogposts/{quote(blogpost_id)}", body_format="storage" if with_body else ""))
        return map_blogposts.blogpost_from(data, self._settings.wiki_url)

    def list_blogposts(
        self, *, space_id: str = "", title: str = "", status: str = "current", sort: str = "", limit: int = 25, cursor: str = ""
    ) -> Chunk[Page]:
        from . import map_blogposts

        path = f"{V2}/spaces/{quote(space_id)}/blogposts" if space_id else f"{V2}/blogposts"
        data = self._call("GET", _with_query(path, title=title, status=status, sort=sort, limit=limit, cursor=cursor))
        base = self._base(data)
        return Chunk([map_blogposts.blogpost_from(item, base) for item in mapper.results_of(data)], self._next_cursor(data))

    def create_blogpost(self, payload: dict[str, Any]) -> Page:
        from . import map_blogposts

        data = self._call("POST", f"{V2}/blogposts", payload)
        return map_blogposts.blogpost_from(data, self._settings.wiki_url)

    def update_blogpost(self, blogpost_id: str, payload: dict[str, Any]) -> Page:
        from . import map_blogposts

        data = self._call("PUT", f"{V2}/blogposts/{quote(blogpost_id)}", payload)
        return map_blogposts.blogpost_from(data, self._settings.wiki_url)

    def list_blogpost_labels(self, blogpost_id: str) -> list[Label]:
        def read(cursor: str) -> Chunk[Label]:
            data = self._call("GET", f"{V2}/blogposts/{quote(blogpost_id)}/labels?{query(limit=250, cursor=cursor)}")
            return Chunk([mapper.label_from(item) for item in mapper.results_of(data)], self._next_cursor(data))

        return fetch_all(read)[0]

    def add_blogpost_labels(self, blogpost_id: str, payload: list[dict[str, str]]) -> list[Label]:
        data = self._call("POST", f"{V1}/content/{quote(blogpost_id)}/label", payload)  # the call is keyed by the id of any content
        return [mapper.label_from(item) for item in mapper.results_of(data)]

    def list_blogpost_comments(self, blogpost_id: str, *, inline: bool = False, limit: int = 50, cursor: str = "") -> Chunk[Comment]:
        kind = "inline" if inline else "footer"
        params = query(body_format="storage", sort="created-date", limit=limit, cursor=cursor)
        data = self._call("GET", f"{V2}/blogposts/{quote(blogpost_id)}/{kind}-comments?{params}")
        return Chunk([mapper.comment_from(item, kind) for item in mapper.results_of(data)], self._next_cursor(data))
