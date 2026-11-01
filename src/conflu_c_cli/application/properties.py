"""Use cases around the content properties of pages and other content: read the properties of any content, and set one."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.content import describe, parse_content_id
from ..domain.errors import ConflictError, NotFoundError, UsageError, ValidationError
from ..domain.model import is_attachment_id
from ..domain.properties import (
    CUT_MARKER,
    HOLDERS_SENTENCE,
    ContentProperty,
    collection_of,
    copies_written_back,
    create_payload,
    named,
    same_value,
    shown_key,
    shown_text,
    shown_value,
    update_payload,
    validate_key,
)
from .paging import PAGE_SIZE, ensure_users_allowed, fetch_all
from .ports import ConfluenceGateway
from .services import Services
from .settings import Settings

MAX_CHARS = 2000  # of a value that is shown, unless the person says another number


@dataclass(frozen=True)
class Target:
    """The content that holds properties: its id, and what Confluence calls it (`page`, `blogpost`, `folder`, `whiteboard`, `database`, `embed`,
    `attachment`, `footer-comment`, `inline-comment`)."""

    id: str
    type: str


def resolve_target(gateway: ConfluenceGateway, ref: str) -> Target:
    """What an id names. The ids of pages, blog posts, folders and the rest are one sequence, so Confluence is asked (one request); an attachment is
    known by its id, which starts with `att`."""
    text = (ref or "").strip()
    if is_attachment_id(text):
        return Target(text, "attachment")
    content_id = parse_content_id(text)
    kind = gateway.content_types([content_id]).get(content_id)
    if kind is None:
        raise NotFoundError(
            f"No content with the id {content_id} that this account can see.",
            hint="Check the id. Confluence says the same for content that does not exist and for content this account may not see.",
            details={"id": content_id},
        )
    if kind == "attachment":
        return Target(f"att{content_id}", "attachment")  # the v2 API writes the id of an attachment with the prefix
    if collection_of(kind) is None:
        raise ValidationError(
            f"{content_id} is {describe(kind)}, and this command works with {HOLDERS_SENTENCE}.",
            hint="Pass the id of the content that holds the properties.",
            details={"id": content_id, "type": kind},
        )
    return Target(content_id, kind)


@dataclass(frozen=True)
class PropertyView:
    id: str
    key: str  # free text: without the people it is hidden like any other
    version: int
    updated: str
    value: Any  # the JSON value; when `truncated`, the beginning of its compact text instead, ending in the mark that `property-set` refuses (`CUT_MARKER`)
    text: str  # the compact JSON text of the value, cut to the number of characters that was asked for, and then ending in that mark
    truncated: bool = False
    total_chars: int = 0  # the size of the whole text


@dataclass
class PropertyList:
    target: Target
    properties: list[PropertyView]
    next_cursor: str = ""
    truncated: bool = False  # the list was cut short at its limit


def present(item: ContentProperty, *, max_chars: int, with_users: bool) -> PropertyView:
    value = shown_value(item.value, with_users=with_users)
    text, cut, total = shown_text(value, max_chars)
    return PropertyView(item.id, shown_key(item.key, with_users=with_users), item.version, item.updated, text if cut else value, text, cut, total)


class ListProperties:
    def __init__(self, gateway: ConfluenceGateway, settings: Settings) -> None:
        self._gateway = gateway
        self._settings = settings

    def execute(
        self,
        ref: str,
        *,
        key: str = "",
        max_chars: int = MAX_CHARS,
        with_users: bool = False,
        limit: int = 25,
        cursor: str = "",
        fetch_everything: bool = False,
    ) -> PropertyList:
        ensure_users_allowed(with_users, self._settings)
        if max_chars < 0:
            raise UsageError("--max-chars must not be negative.", hint="0 shows every value whole.")
        target = resolve_target(self._gateway, ref)

        def read(next_cursor: str):
            return self._gateway.list_properties(target.type, target.id, key=key, limit=PAGE_SIZE if fetch_everything else limit, cursor=next_cursor)

        if fetch_everything:
            items, truncated = fetch_all(read)
            following = ""
        else:
            chunk = read(cursor)
            items, following, truncated = chunk.items, chunk.cursor, False
        return PropertyList(target, [present(item, max_chars=max_chars, with_users=with_users) for item in items], following, truncated)


@dataclass
class PropertyChange:
    action: str  # created | updated | unchanged
    target: Target
    key: str
    property_id: str  # empty in a dry run of a creation
    version_from: int  # 0 for a creation
    version_to: int
    value: Any  # the value as it was given
    current: Any  # what Confluence held (without people); None for a creation
    payload: dict[str, Any] | None  # what is sent; None when nothing is
    dry_run: bool
    notes: list[str] = field(default_factory=list)


class SetProperty:
    """Sets the value of the property with a key: creates it when the key is new, else saves the next version of it. The property is read first, so
    that a value that is there already is left alone and a guard (`if_version`) can say no before anything is sent. Nothing deletes a property."""

    def __init__(self, gateway: ConfluenceGateway) -> None:
        self._gateway = gateway

    def execute(self, ref: str, key: str, value: Any, *, message: str = "", if_version: int | None = None, dry_run: bool = False) -> PropertyChange:
        key = validate_key(key)
        if if_version is not None and if_version < 0:
            raise UsageError("--if-version must not be negative.", hint="0 means that the property must not exist yet.")
        target = resolve_target(self._gateway, ref)
        existing = self._find(target, key)
        current = None if existing is None else shown_value(existing.value, with_users=False)
        self._refuse_copies(target, key, value, existing, current)
        if if_version is not None:
            self._guard(target, key, existing, if_version)
        if existing is None:
            notes = ["--message was not sent: a new property has no version message."] if message else []
            payload = create_payload(key, value)
            if dry_run:
                return PropertyChange("created", target, key, "", 0, 1, value, None, payload, True, notes)
            try:
                created = self._gateway.create_property(target.type, target.id, payload)
            except ConflictError as error:
                raise self._moved_on(target, key, error) from error
            return PropertyChange("created", target, key, created.id, 0, created.version or 1, value, None, payload, False, notes)
        if same_value(existing.value, value):
            notes = ["--message was not sent: the value is the one that is there, so nothing was saved."] if message else []
            return PropertyChange("unchanged", target, key, existing.id, existing.version, existing.version, value, current, None, dry_run, notes)
        payload = update_payload(key, value, existing.version + 1, message)
        if dry_run:
            return PropertyChange("updated", target, key, existing.id, existing.version, existing.version + 1, value, current, payload, True)
        try:
            saved = self._gateway.update_property(target.type, target.id, existing.id, payload)
        except ConflictError as error:
            raise self._moved_on(target, key, error) from error
        return PropertyChange("updated", target, key, saved.id or existing.id, existing.version, saved.version or existing.version + 1, value, current, payload, False)

    @staticmethod
    def _refuse_copies(target: Target, key: str, value: Any, existing: ContentProperty | None, shown: Any) -> None:
        """A value that is a copy of what `conflu properties` showed, not the value of the property, is refused: saving it would overwrite what Confluence holds
        (nothing may redact it) with what the reading put in its place. That is a part of a value that was cut (`[value cut]`, refused for a new property too),
        the stand-ins of the people in it (`[hidden]`, `{"hidden": true}` ...) and a text that the reading changed (an address without its title), wherever
        it stands. The way to a value that may be written is one reading of the whole real one: `--with-users --max-chars 0`."""
        where = named(target.type, target.id)
        found, altered = copies_written_back(value, None if existing is None else existing.value, shown)
        read_whole = f"conflu properties {target.id} --key {key} --max-chars 0 --json"
        if CUT_MARKER in found:
            saved = f"replace the whole property {key} of {where} with the beginning of it" if existing is not None else "store the beginning of a value as the value of a new property"
            raise ValidationError(
                f"The new value holds `{CUT_MARKER}`, which ends a value that `conflu properties` cut at --max-chars: it is the beginning of a value, not the value. "
                f"Saving it would {saved}.",
                hint=f"Read the whole value with `{read_whole}` (add --with-users when it holds people), change only what you need, and write that.",
                details={"id": target.id, "key": key, "markers": found},
            )
        read_real = f"conflu properties {target.id} --key {key} --with-users --max-chars 0 --json"
        hint = f"Read the real value with `{read_real}` (refused when CONFLUENCE_HIDE_USERS=true), change only what you need, and write that."
        if found:
            marks = [f"`{mark}`" for mark in found]
            named_markers = marks[0] if len(marks) == 1 else f"{', '.join(marks[:-1])} and {marks[-1]}"
            raise ValidationError(
                f"The new value holds {named_markers}, what `conflu properties` shows in the place of the people and addresses that the property {key} "
                f"of {where} holds. Saving it would overwrite them.",
                hint=hint,
                details={"id": target.id, "key": key, "markers": found},
            )
        if altered:
            samples = [text if len(text) <= 80 else text[:77] + "..." for text in altered[:3]]
            many = f"{len(altered)} texts" if len(altered) > 1 else "a text"
            raise ValidationError(
                f"The new value holds {many} that `conflu properties` shows instead of what the property {key} of {where} holds, for example `{samples[0]}` "
                "(an address is shown without its title when the title holds an e-mail address). Saving it would overwrite the original.",
                hint=hint,
                details={"id": target.id, "key": key, "texts": samples},
            )

    @staticmethod
    def _moved_on(target: Target, key: str, error: ConflictError) -> ConflictError:
        """Confluence's own answer to a save that lost against somebody else's; its hint speaks of a page, and this was a property."""
        return ConflictError(
            error.message,
            hint=f"The property was saved by somebody else while this ran. Read it again with `conflu properties {target.id} --key {key}`, review its value, and set it again.",
            details={**error.details, "id": target.id, "key": key},
        )

    def _find(self, target: Target, key: str) -> ContentProperty | None:
        """The property with exactly this key. Asked for with the key, so one piece is enough; every piece is read when the answer is longer."""
        items, _ = fetch_all(lambda cursor: self._gateway.list_properties(target.type, target.id, key=key, limit=PAGE_SIZE, cursor=cursor))
        return next((item for item in items if item.key == key), None)

    @staticmethod
    def _guard(target: Target, key: str, existing: ContentProperty | None, expected: int) -> None:
        held = existing.version if existing is not None else 0
        if held == expected:
            return
        where = named(target.type, target.id)
        if existing is None:
            what = f"The property {key} of {where} does not exist."
        elif expected == 0:
            what = f"The property {key} of {where} exists already (version {held})."
        else:
            what = f"The property {key} of {where} is at version {held}, not {expected}."
        raise ConflictError(
            what,
            hint=f"Read it again with `conflu properties {target.id} --key {key}` and review its value before you write.",
            details={"id": target.id, "key": key, "version": held, "expected": expected},
        )


@dataclass
class PropertiesUseCases:
    """The use cases of the area, reached as `app.properties.<name>`."""

    list_properties: ListProperties
    set_property: SetProperty


def build(services: Services) -> PropertiesUseCases:
    return PropertiesUseCases(ListProperties(services.gateway, services.settings), SetProperty(services.gateway))
