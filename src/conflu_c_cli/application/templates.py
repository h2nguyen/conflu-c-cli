"""Use cases around the templates of a space: list the page templates and the templates of blueprints, and read one with its variables."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import NoReturn

from ..domain.errors import AuthError, UsageError, ValidationError
from ..domain.model import parse_space_key
from ..domain.privacy import EMAIL_MARKER, LINK_MARKER, redact_text
from ..domain.structure import shown_key
from ..domain.templates import TemplateInfo, parse_template_id, variables_of
from .paging import MAX_ITEMS, PAGE_SIZE
from .ports import ConfluenceGateway
from .rendering import BODY_FORMATS, Body, check_format, render_body
from .services import Services


def hide_people(info: TemplateInfo) -> TemplateInfo:
    """The text of a template that a person wrote (its name, its description, its labels) goes through the same redaction as a title, and the key of
    the space of a template that lies in a personal space is `[hidden]`: it is the account id of the owner. The templates have no `--with-users`."""
    return replace(
        info,
        name=redact_text(info.name),
        description=redact_text(info.description),
        space_key=shown_key(info.space_key),
        labels=tuple(redact_text(label) for label in info.labels),
        blueprint=redact_text(info.blueprint),
    )


def refuse(error: AuthError, what: str, hint: str) -> NoReturn:
    """Raises HTTP 403 without Confluence's own words: the explanation that the older API gives is free text, which may name a person, and `what` says all
    that is known. Any other refusal (a 401 says that the credentials were not accepted, with no free text) goes on as it is: it is not a 403."""
    if error.details.get("status") != 403:
        raise error
    raise AuthError(f"Confluence refused this request (HTTP 403): {what}.", hint=hint, details=error.details) from error


@dataclass
class TemplateList:
    templates: list[TemplateInfo]
    start: int
    next_start: int | None  # where the next piece starts; None on the last one
    space: str  # the key as it is printed (`[hidden]` for a personal space); empty for the global templates
    blueprints: bool
    truncated: bool = False


class ListTemplates:
    def __init__(self, gateway: ConfluenceGateway) -> None:
        self._gateway = gateway

    def execute(self, *, space: str = "", blueprints: bool = False, limit: int = 25, start: int = 0, fetch_everything: bool = False) -> TemplateList:
        if start < 0:
            raise UsageError("--start must not be negative.")
        # The space is asked for first: the key is written as the space writes it (so `eng` does), and a space that is not there is "not found" here,
        # where the call for the templates would only say HTTP 403, which it says for a space that may not be seen as well.
        key = self._gateway.get_space(parse_space_key(space)).key if space else ""
        try:
            if fetch_everything:
                return self._all(key, blueprints)
            piece = self._gateway.list_templates(space_key=key, blueprints=blueprints, limit=limit, start=start)
        except AuthError as error:
            refuse(
                error,
                f"this account may not see the {'blueprint ' if blueprints else ''}templates of {'the space ' + shown_key(key) if key else 'the site'}",
                "Your account lacks the permission, or the token's scopes do not cover it. Ask the space administrator.",
            )
        return TemplateList([hide_people(item) for item in piece.templates], piece.start, piece.next_start, shown_key(key), blueprints)

    def _all(self, key: str, blueprints: bool) -> TemplateList:
        found: list[TemplateInfo] = []
        position, seen, truncated = 0, set(), False
        while True:
            piece = self._gateway.list_templates(space_key=key, blueprints=blueprints, limit=PAGE_SIZE, start=position)
            found.extend(piece.templates)
            seen.add(position)
            if piece.next_start is None or not piece.templates or piece.next_start in seen:
                break
            if len(found) >= MAX_ITEMS:
                found, truncated = found[:MAX_ITEMS], True
                break
            position = piece.next_start
        return TemplateList([hide_people(item) for item in found], 0, None, shown_key(key), blueprints, truncated)


@dataclass
class TemplateView:
    template: TemplateInfo  # without people in its text
    body: Body  # the body as `page` shows one: people hidden
    variables: tuple[str, ...]  # what the template declares, from the storage format: the Markdown cannot show them
    variables_complete: bool = True  # False when the scan of the body stopped at a limit (see domain.templates.variables_of)
    empty: bool = False  # the template has no body at all (a body that the format cannot show is not empty)
    replaced: int = 0  # the storage format of the body (asked for with `body_format` storage) holds this many `[email]` and `[personal link]` that were addresses and links


def replaced_in(original: str, shown: str) -> int:
    """How many e-mail addresses and personal links the redaction put `[email]` and `[personal link]` in the place of: the markers that `shown` holds more often
    than `original` does (a body that says `[email]` itself is not counted again)."""
    return sum(max(0, shown.count(marker) - original.count(marker)) for marker in (EMAIL_MARKER, LINK_MARKER))


class ShowTemplate:
    def __init__(self, gateway: ConfluenceGateway) -> None:
        self._gateway = gateway

    def execute(self, template_id: str, *, body_format: str = "markdown") -> TemplateView:
        template_id = parse_template_id(template_id)
        check_format(body_format, BODY_FORMATS)
        try:
            template = self._gateway.get_template(template_id)
        except AuthError as error:
            refuse(
                error,
                f"there is no template {template_id}, or this account may not see it (Confluence says the same for both)",
                "`conflu templates` and `conflu templates --blueprints` list the ids of the templates that this account can see.",
            )
        info = TemplateInfo(template.id, template.name, template.type, template.description, template.space_key, template.labels, template.blueprint)
        found = variables_of(template.body)
        try:
            body = render_body(template.body, body_format, with_users=False)
        except ValidationError as error:  # a body that the converter refuses (nested too deeply) can still be read as Confluence keeps it
            if body_format == "storage":
                raise
            raise ValidationError(error.message, hint="Read it as Confluence keeps it with --format storage.", details=error.details) from error
        replaced = replaced_in(template.body, body.text) if body_format == "storage" else 0
        return TemplateView(hide_people(info), body, found.names, found.complete, not template.body.strip(), replaced)


@dataclass
class TemplatesUseCases:
    """The use cases of the area, reached as `app.templates.<name>`."""

    list_templates: ListTemplates
    show_template: ShowTemplate


def build(services: Services) -> TemplatesUseCases:
    return TemplatesUseCases(ListTemplates(services.gateway), ShowTemplate(services.gateway))
