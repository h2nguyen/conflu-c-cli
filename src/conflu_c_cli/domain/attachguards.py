"""The guards of `attach`: what is never published, and what a new version of a file must not replace unseen.

An attachment can be opened by everyone who can see the page, and the CLI cannot take one back. So a file that holds the secrets of the CLI
itself is never sent: not its settings file, not a copy of it, not a log with a dump of the headers of a request. A file that is given a new
version replaces the one that a person saw, so what is read before is checked against what that person expects (`--if-version`,
`--if-unchanged-since`). All pure: the bytes, the file system and Confluence are the business of the ports.
"""
from __future__ import annotations

import base64
from typing import Iterable, Sequence

from .attachmenttext import printable
from .errors import ConflictError, ValidationError
from .model import Attachment
from .textio import TEXT_ENCODINGS
from .timeutil import parse_guard_time, parse_timestamp

MIN_SECRET = 6  # a shorter token is no secret, and looking for it would refuse every file (the same rule as the one that scrubs an error message)
SCAN_PIECE = 1 << 20  # bytes of a file that are looked at at once
SCAN_LIMIT = 256 << 20  # a file larger than this is not searched for the token, and so not read: it is refused


def _encoded(text: str) -> list[bytes]:
    found = []
    for encoding in TEXT_ENCODINGS:  # what `decode_text` reads, so that the search cannot know fewer encodings than the reader of a file does
        try:
            found.append(text.encode(encoding))
        except UnicodeEncodeError:  # a character that the encoding (ANSI) has no byte for: the file cannot hold the text in it
            continue
    return found


def secret_needles(token: str, email: str = "") -> tuple[bytes, ...]:
    """The bytes under which a token can stand in a file: as it is, and as the value of the header that carries it (`Authorization: Basic ...` is
    the encoded `email:token`), each in every encoding that `domain.textio.decode_text` reads (UTF-8, UTF-16 and UTF-32 with either byte order,
    ANSI): a copy that an editor or Windows PowerShell saved in another encoding holds it too. Empty for a token that is too short to be one."""
    if len(token) < MIN_SECRET:
        return ()
    header = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
    return tuple(dict.fromkeys(needle for text in (token, header) for needle in _encoded(text)))


def holds_secret(pieces: Iterable[bytes], needles: Sequence[bytes]) -> bool:
    """Whether the bytes, which come in pieces, hold one of the needles, also where it stands across the end of one piece and the start of the
    next. The needles are never shown."""
    if not needles:
        return False
    keep = max(len(needle) for needle in needles) - 1
    carry = b""
    for piece in pieces:
        window = carry + piece
        if any(needle in window for needle in needles):
            return True
        carry = window[-keep:] if keep else b""
    return False


def _shown(name: str) -> str:
    return printable(name)


def check_replaced_version(existing: Attachment | None, name: str, expected: int) -> None:
    """A file that replaces an attachment is expected to find it at `expected`; 0 says that the file is new, and that nothing of that name is there."""
    current = existing.version if existing is not None else 0
    if current == expected:
        return
    if existing is None:
        raise ConflictError(
            f"The page has no attachment named {_shown(name)}, and --if-version says that it is at version {expected}.",
            hint="Read the page's attachments again (`conflu attachments PAGE`) and review the current state before writing.",
            details={"name": name, "version": 0, "expected": expected},
        )
    what = "has a file of that name already" if expected == 0 else f"is at version {current}, not {expected}"
    raise ConflictError(
        f"The attachment {_shown(name)} ({existing.id}) {what}.",
        hint="Read it again (`conflu attachment ID`) and review the current state before writing: the file would become a new version of it.",
        details={"attachmentId": existing.id, "name": name, "version": current, "expected": expected},
    )


def check_unchanged_since(existing: Attachment | None, name: str, since: str) -> None:
    """A file that replaces an attachment must not do so when the attachment was saved after `since`. A file that is new replaces nothing."""
    limit = parse_guard_time(since)  # an empty value is an error that names the option, never "no guard"
    if existing is None:
        return
    saved = existing.updated or existing.created
    if not saved:
        raise ValidationError(
            f"Confluence did not say when {_shown(name)} ({existing.id}) was saved, so --if-unchanged-since cannot be checked.",
            hint="Use --if-version instead.",
        )
    changed_at = parse_timestamp(saved)
    if changed_at > limit:
        raise ConflictError(
            f"The attachment {_shown(name)} ({existing.id}) changed in Confluence at {changed_at.isoformat()}, after {limit.isoformat()}.",
            hint="Read it again (`conflu attachment ID`) and review the current state before writing: the file would become a new version of it.",
            details={"attachmentId": existing.id, "name": name, "updated": changed_at.isoformat(), "since": limit.isoformat()},
        )
