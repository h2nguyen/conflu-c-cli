"""Use cases around the watches of the user on pages and spaces.

Only the watch of the token's own user is read or changed. There is nothing to name another person with, in the use cases or below them.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain.content import parse_content_id
from ..domain.errors import ConfluCliError, NotFoundError, UsageError, ValidationError
from ..domain.model import parse_space_key
from ..domain.privacy import hide_space, redact_text
from ..domain.watches import SPACE, WatchChange, WatchTarget
from .ports import ConfluenceGateway, Diagnostics
from .services import Services
from .settings import Settings


def check_command(target: WatchTarget) -> str:
    """The command that says whether the watch is there: what a message sends a person to when a change could not be confirmed. A personal space is
    named as everywhere it is printed (`[hidden]`): the person has the key that they typed."""
    return f"conflu watching --space {target.shown_key}" if target.scope == SPACE else f"conflu watching {target.id}"


def resolve_watch_target(gateway: ConfluenceGateway, settings: Settings, ref: str, space: str, *, current_space: bool) -> WatchTarget:
    """What `[PAGE] [--space KEY]` names: content (any content id: Confluence says what it is), or a space. With `current_space` the space of
    `conflu use` is what neither names: a read may assume it, a change does not (it names what it changes)."""
    ref, space = (ref or "").strip(), (space or "").strip()
    if ref and space:
        raise UsageError("Give the id of a page or --space, not both.", hint="`conflu watching ID` is about content, `conflu watching --space KEY` about a space.")
    if ref:
        try:
            content_id = parse_content_id(ref)
        except ValidationError as error:
            raise ValidationError(error.message, hint=f"{error.hint} A space is named with --space KEY.".strip()) from error
        kind = gateway.content_types([content_id]).get(content_id)
        if kind is None:
            raise NotFoundError(
                f"No content with the id {content_id} that this account can see.",
                hint="Check the id: the address of a page has it. Confluence says the same for content that does not exist and for content this account may not see.",
                details={"id": content_id},
            )
        return WatchTarget(kind, content_id)
    key = space or (settings.space if current_space else "")
    if not key:
        raise UsageError(
            "Neither a page nor a space is named.",
            hint="Give the id of a page, or --space KEY, or run `conflu use KEY` to choose a current space."
            if current_space
            else "Give the id of a page, or --space KEY. A change never assumes the current space of `conflu use`.",
        )
    found = gateway.get_space(parse_space_key(key))
    shown = hide_space(found)  # these commands have no --with-users: a personal space is printed as it is everywhere; the call below still names it by its key
    return WatchTarget(SPACE, found.id, found.key, shown.name, shown.key)


@dataclass(frozen=True)
class WatchState:
    target: WatchTarget
    watching: bool


class ShowWatching:
    def __init__(self, gateway: ConfluenceGateway, settings: Settings) -> None:
        self._gateway = gateway
        self._settings = settings

    def execute(self, ref: str = "", *, space: str = "") -> WatchState:
        found = resolve_watch_target(self._gateway, self._settings, ref, space, current_space=True)
        return WatchState(found, self._gateway.watch_status(found.scope, found.name))


@dataclass
class WatchResult:
    target: WatchTarget
    action: str  # watched | unwatched | unchanged
    dry_run: bool
    was_watching: bool  # before the change
    watching: bool | None  # after it, as Confluence says; None when that could not be read. In a dry run: the state as it is
    confirmed: bool | None  # the status read back after the write shows what was asked; None when nothing was written, or when it could not be read
    change: WatchChange | None  # what is sent, or in a dry run would be; None when the watch is as asked already
    message: str = ""  # what the person must know when the change was made and is not confirmed


class ChangeWatch:
    """Starts watching a page or a space, or with `remove` stops: the token's own watch. It reads the status first and sends nothing when it is as
    asked, and reads it back after a write."""

    def __init__(self, gateway: ConfluenceGateway, settings: Settings, diagnostics: Diagnostics) -> None:
        self._gateway = gateway
        self._settings = settings
        self._diagnostics = diagnostics

    def execute(self, ref: str = "", *, space: str = "", remove: bool = False, dry_run: bool = False) -> WatchResult:
        found = resolve_watch_target(self._gateway, self._settings, ref, space, current_space=False)
        wanted = not remove
        before = self._gateway.watch_status(found.scope, found.name)
        if before == wanted:
            return WatchResult(found, "unchanged", dry_run, before, before, None, None)
        change = found.change(wanted)
        action = "watched" if wanted else "unwatched"
        if dry_run:
            return WatchResult(found, action, True, before, before, None, change)
        self._gateway.change_watch(change)
        # From here the change is made: whatever goes wrong now must not read as a failure, or somebody repeats it.
        try:
            after = self._gateway.watch_status(found.scope, found.name)
        except ConfluCliError as error:
            message = (
                f"The watch was {'added' if wanted else 'taken off'}, but reading the watch status afterwards failed: "
                f"{redact_text(error.message.rstrip('. '))}. Check it with `{check_command(found)}`."
            )
            self._diagnostics.warn(message)
            return WatchResult(found, action, False, before, None, None, change, message)
        confirmed = after == wanted
        message = ""
        if not confirmed:
            message = f"Confluence accepted the change, but still says that you {'do not ' if wanted else ''}watch it. Check it with `{check_command(found)}`."
            self._diagnostics.warn(message)
        return WatchResult(found, action, False, before, after, confirmed, change, message)


@dataclass
class WatchesUseCases:
    """The use cases of the area, reached as `app.watches.<name>`."""

    watching: ShowWatching
    watch: ChangeWatch


def build(services: Services) -> WatchesUseCases:
    return WatchesUseCases(
        watching=ShowWatching(services.gateway, services.settings),
        watch=ChangeWatch(services.gateway, services.settings, services.diagnostics),
    )
