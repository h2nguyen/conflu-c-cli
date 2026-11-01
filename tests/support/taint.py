"""Marks the free text of every answer of the mock, so that a command that prints it without the redaction can be found.

A person's e-mail address can sit in a title, a name, a message, a description, a comment or a body, and in the address of a page, which
Confluence builds from the title. When people are not shown, no command may print it. `taint_payload` adds `TAINT` to every such text of an
answer (and the address in its slug form to the address of a page), and the privacy sweep (`tests/integration/test_privacy_sweep.py`) runs every
command line of every feature area against a mock that does it and fails when a `MARKERS` string comes out.
"""
from __future__ import annotations

from typing import Any

TAINT = "alex@example.com"
PEOPLE_MARKERS = ("5b10ac8d82e05b22cc7d4ef5", "alex example")  # the account id and the name of the one person that the mock holds
ADDRESS_MARKERS = (TAINT, "alex%40example.com", "alex-example-com", "alex_example_com")  # the address, as the slug of a page or of a file would carry it
MARKERS = PEOPLE_MARKERS + ADDRESS_MARKERS

FREE_TEXT = frozenset({"title", "name", "message", "description", "text", "comment", "plainText", "excerpt", "summary", "value", "label", "body"})
ADDRESSES = frozenset({"webui", "url"})
READABLE = {None, "storage", "view", "export_view", "styled_view", "anonymous_export_view", "editor", "wiki"}  # a body that is text, not JSON


def taint_payload(payload: Any) -> Any:
    """A copy of an answer with `TAINT` added to its free text. Ids, keys, types, dates and every non-text value stay as they are, and so do the
    names that are identifiers by design: the name of a label (`label --remove NAME`) and the title of an attachment (its file name)."""
    if isinstance(payload, list):
        return [taint_payload(item) for item in payload]
    if not isinstance(payload, dict):
        return payload
    marked: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, str):
            marked[key] = _taint_text(key, value, payload)
        else:
            marked[key] = taint_payload(value)
    return marked


def _identifier(key: str, owner: dict[str, Any]) -> bool:
    if key in {"name", "label"} and "prefix" in owner:
        return True  # a label
    return key == "title" and any(name in owner for name in ("mediaType", "fileSize", "fileId", "mediaTypeDescription"))  # an attachment


def _taint_text(key: str, value: str, owner: dict[str, Any]) -> str:
    if key in FREE_TEXT and value and not _identifier(key, owner):
        if key == "value" and owner.get("representation") not in READABLE:
            return value  # a body in a JSON format has to stay parseable
        return f"{value} {TAINT}"
    if key in ADDRESSES and ("/pages/" in value or "/blog/" in value):
        return f"{value}+{TAINT.replace('@', '%40')}"
    return value
