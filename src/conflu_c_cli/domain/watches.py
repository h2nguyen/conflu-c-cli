"""Watching a page or a space: what a change of your own watch is, in the words of the rules.

Only the token's own watch is ever read or changed. There is no way to name another person: no call here has a place for one.
"""
from __future__ import annotations

from dataclasses import dataclass

CONTENT = "content"  # a page, a blog post, ... anything with a content id
SPACE = "space"  # a space is watched by its key
SCOPES = (CONTENT, SPACE)

# The REST API v1 path of the watch calls, as `docs/reference/compatibility.md` writes them; v2 has no watches.
PATHS = {CONTENT: "/rest/api/user/watch/content/{contentId}", SPACE: "/rest/api/user/watch/space/{spaceKey}"}


@dataclass(frozen=True)
class WatchChange:
    """What `conflu watch` sends, or in a dry run would send: start watching, or stop. Built once, shown by the dry run and sent as it is."""

    scope: str  # content | space
    target: str  # the id of the content, or the key of the space
    watch: bool  # True: start watching; False: stop

    @property
    def method(self) -> str:
        """POST adds your watch, DELETE takes it off again. The DELETE removes a watch, not content: a watch is a notification setting of your own."""
        return "POST" if self.watch else "DELETE"

    @property
    def call(self) -> str:
        """The REST call that sends it, as the compatibility page and `V1_CALLS` write it: `POST /rest/api/user/watch/content/{contentId}`."""
        return f"{self.method} {PATHS[self.scope]}"


@dataclass(frozen=True)
class WatchTarget:
    """What is watched: a piece of content, named by its id, or a space, named by its key.

    A space is printed as `privacy.hide_space` says, like every command that names one: `title` and `shown_key` are what is printed. They differ from
    the key for a personal space, which is named after its owner and keyed by the owner's account id; `key` stays what the call names."""

    type: str  # what Confluence calls it: page, blogpost, folder ... or space
    id: str
    key: str = ""  # of a space: what the call names
    title: str = ""  # the name of a space as it is printed; for content none is read: it would take a request of its own, and the person named the id
    shown_key: str = ""  # the key of a space as it is printed: `[hidden]` for a personal space

    @property
    def scope(self) -> str:
        return SPACE if self.type == SPACE else CONTENT

    @property
    def name(self) -> str:
        """What the call names: the key of a space, the id of content."""
        return self.key if self.scope == SPACE else self.id

    def change(self, watch: bool) -> WatchChange:
        return WatchChange(self.scope, self.name, watch)
