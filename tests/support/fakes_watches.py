"""The in-memory Confluence for the watches of the user on pages and spaces: a mixin of `FakeGateway` (`_init_watches` sets up its state).

Nothing is watched when a test starts. `watching` holds `("content", "2002")` and `("space", "ENG")` for what is; content is known when it is a
page or when a test registered it in `content_kinds`, a space by its key.
"""
from __future__ import annotations

from conflu_c_cli.domain.errors import NotFoundError
from conflu_c_cli.domain.watches import CONTENT, SPACE, WatchChange


class FakeWatches:
    def _init_watches(self) -> None:
        self.watching: set[tuple[str, str]] = set()

    def _watchable(self, scope: str, target: str) -> None:
        if scope not in (CONTENT, SPACE):
            raise ValueError(f"Not something that can be watched: {scope}")
        known = (target in self.pages or target in self.content_kinds) if scope == CONTENT else target in self.spaces
        if not known:
            raise NotFoundError(f"Not found: GET /rest/api/user/watch/{scope}/{target}")

    def watch_status(self, scope: str, target: str) -> bool:
        self._enter("watch_status", scope, target)
        self._watchable(scope, target)
        return (scope, target) in self.watching

    def change_watch(self, change: WatchChange) -> None:
        self._enter("change_watch", change)
        self._watchable(change.scope, change.target)
        if change.watch:
            self.watching.add((change.scope, change.target))
        else:
            self.watching.discard((change.scope, change.target))
