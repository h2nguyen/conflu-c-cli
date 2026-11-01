"""Page bodies for people and programs: storage format shown as Markdown or text, or as it is."""
from __future__ import annotations

from dataclasses import dataclass

from ..domain.errors import UsageError, ValidationError
from ..domain.markdown import markdown_to_storage
from ..domain.privacy import has_blanked_mentions, redact_storage, redact_text
from ..domain.storage import storage_to_markdown, storage_to_text
from .formats import BODY_FORMATS, INPUT_FORMATS

REDACTED = "redacted-text"  # e-mail addresses and personal links that are hidden from the Markdown


@dataclass(frozen=True)
class Body:
    format: str
    text: str
    dropped: tuple[str, ...] = ()  # what the Markdown could not say (see domain.storage)
    section: str = ""  # the heading of the part that is shown, when only one section was asked for
    truncated: bool = False  # the text was cut to --max-chars
    total_chars: int = 0  # the size of the whole text, when it was cut


def check_format(fmt: str, allowed: tuple[str, ...] = BODY_FORMATS) -> str:
    if fmt not in allowed:
        raise UsageError(f"Unknown format: {fmt}", hint=f"Use one of: {', '.join(allowed)}.")
    return fmt


def render_body(storage: str, fmt: str, *, with_users: bool) -> Body:
    """The body in the format asked for. Without `with_users` the people are left out of it: mentions become `@user`
    and in storage format the account ids are blanked."""
    check_format(fmt)
    if fmt == "storage":
        return Body(fmt, storage if with_users else redact_storage(storage))
    if fmt == "text":
        text, dropped = storage_to_text(storage, show_mentions=with_users), ()
    else:
        converted = storage_to_markdown(storage, show_mentions=with_users)
        text, dropped = converted.text, converted.dropped
    cleaned = text if with_users else redact_text(text)
    if cleaned != text and fmt == "markdown":
        dropped = tuple(sorted({*dropped, REDACTED}))
    return Body(fmt, cleaned, dropped)


def markdown_limits(storage: str) -> tuple[str, ...]:
    """What the Markdown copy of a body (as `page` shows it) cannot say. A Markdown that replaces the body loses it."""
    return render_body(storage, "markdown", with_users=False).dropped


def markdown_round_trip(storage: str) -> str:
    """The storage format that the Markdown copy of a body (as `page` and `export` write it) becomes again."""
    return markdown_to_storage(render_body(storage, "markdown", with_users=False).text)


def storage_from_input(text: str, fmt: str) -> str:
    """The storage format for a body that was written as Markdown or already in storage format."""
    check_format(fmt, INPUT_FORMATS)
    if fmt == "markdown":
        return markdown_to_storage(text)
    if has_blanked_mentions(text):
        raise ValidationError(
            "The storage format has mentions whose account ids were hidden, or links into a personal space whose key was hidden, so it would break them.",
            hint="It was read without --with-users. Read the page again with --with-users before you edit and write it back.",
        )
    return text.strip()
