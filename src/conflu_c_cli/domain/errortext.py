"""The text that Confluence puts into an error, as it may be printed.

The explanation of a refusal is free text that the server wrote about a request, and servers put people into it: `No user found for
alex@example.com (accountId 5b10ac8d82e05b22cc7d4ef5)`. It ends up in the message of an error, so it goes through the redaction of every other free
text (e-mail addresses, links to people) and through one more: the account id, which a sentence holds as bare text.

Page bodies are not scanned for account ids: a run of 24 hexadecimal digits is a hash or an identifier there as often as it is a person, and a page
that is cut up by a guess is worse than one that keeps a hash. In an error message the guess costs nothing, and an id of a person is worth more than
the identifier that was hidden by mistake.
"""
from __future__ import annotations

import re
from typing import Any

from .privacy import redact_text

ACCOUNT_MARKER = "[account id]"

# An account id is 24 hexadecimal digits (`5b10ac8d82e05b22cc7d4ef5`) or, in the older form, a number, a colon and a UUID (`712020:` and 36 more characters).
# A match must be the whole run of letters and digits it is in: 24 digits of a longer hexadecimal number (a trace id of 32) is not an account id. Both patterns
# start only at the beginning of such a run and have bounded repeats, so no text can make them take longer than its own length.
_RUN_START = r"(?<![0-9A-Za-z])"
_RUN_END = r"(?![0-9A-Za-z])"
_ACCOUNT_ID = re.compile(_RUN_START + r"[0-9a-f]{24}" + _RUN_END, re.IGNORECASE)
_OLD_ACCOUNT_ID = re.compile(
    _RUN_START + r"[0-9]{5,7}:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}" + _RUN_END,
    re.IGNORECASE,
)


def redact_error_text(text: Any) -> str:
    """The text without e-mail addresses, links to people and account ids (`[email]`, `[personal link]`, `[account id]`)."""
    cleaned = redact_text(text)
    if len(cleaned) >= 24:  # no account id is shorter: a short text need not be looked at
        cleaned = _OLD_ACCOUNT_ID.sub(ACCOUNT_MARKER, cleaned)
        cleaned = _ACCOUNT_ID.sub(ACCOUNT_MARKER, cleaned)
    return cleaned


def redact_error_value(value: Any) -> Any:
    """The same for the answer that held the text: every string in it, and every key, at any depth. The shape stays, so that what is left is still
    readable as an answer. A structure nested deeper than the interpreter allows raises `RecursionError`, which is for the caller to answer."""
    if isinstance(value, str):
        return redact_error_text(value)
    if isinstance(value, dict):
        return {redact_error_text(key) if isinstance(key, str) else key: redact_error_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_error_value(item) for item in value]
    return value
