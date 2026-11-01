"""The watches of the user on pages and spaces: the REST calls. A mixin of `RestConfluenceGateway`, which provides `_call`, `_finish`, `_transport`, `_settings`,
`_next_cursor` and `_base`.

Only the watch of the token's own user is read or changed: no call here sends an account id, so Confluence answers for the user who owns the token.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ...domain.errors import UnavailableError
from .rest_support import V1, quote

# The models and the mapper of this area are imported where they are used, so that a command that never reads it does not load them (tests/test_startup.py).
if TYPE_CHECKING:
    from ...domain.watches import WatchChange

# The calls of this area that use the v1 API, each with why v2 does not do (see docs/reference/compatibility.md).
V1_CALLS: dict[str, str] = {
    "GET /rest/api/user/watch/content/{contentId}": "v2 has no watches: it cannot say whether you watch a page or other content.",
    "POST /rest/api/user/watch/content/{contentId}": "v2 has no watches: it cannot make you watch a page or other content.",
    "DELETE /rest/api/user/watch/content/{contentId}": "v2 has no watches: it cannot make you stop watching a page or other content.",
    "GET /rest/api/user/watch/space/{spaceKey}": "v2 has no watches: it cannot say whether you watch a space.",
    "POST /rest/api/user/watch/space/{spaceKey}": "v2 has no watches: it cannot make you watch a space.",
    "DELETE /rest/api/user/watch/space/{spaceKey}": "v2 has no watches: it cannot make you stop watching a space.",
}
XSRF = {"X-Atlassian-Token": "no-check"}  # the two writes have XSRF protection: Confluence refuses them without this header


def _path(scope: str, target: str) -> str:
    from ...domain.watches import SCOPES

    if scope not in SCOPES:
        raise ValueError(f"Not something that can be watched: {scope}")
    return f"{V1}/user/watch/{scope}/{quote(target)}"


class RestWatches:
    def watch_status(self, scope: str, target: str) -> bool:
        from . import map_watches as watches_mapper

        path = _path(scope, target)
        watching = watches_mapper.watching_from(self._call("GET", path))
        if watching is None:
            raise UnavailableError(
                f"Confluence did not say whether you watch {scope} {target}.",
                hint="Try again in a moment; `conflu doctor` checks that the v1 API answers.",
            )
        return watching

    def change_watch(self, change: WatchChange) -> None:
        path = _path(change.scope, change.target)
        response = self._transport.request(change.method, path, headers=XSRF)
        self._finish(response, change.method, path, "nothing")  # HTTP 204: there is no body to read
