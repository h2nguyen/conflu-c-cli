"""Decoding the bytes of a text file that a person (or Windows PowerShell 5.1) wrote, and how much of one is read."""
from __future__ import annotations

import codecs

from .errors import UsageError, ValidationError

QUERY_LIMIT = 1024 * 1024  # bytes: a search text or a query is some lines long; more is a mistake (a log, a device), not a query
BODY_LIMIT = 16 * 1024 * 1024  # bytes: the text of a page or a comment, or a JSON body; far more than Confluence accepts, but a limit all the same

# What `decode_text` reads, as a table that whoever searches a file for a text reads too (the guard against publishing the token, `attachguards`),
# so that a file in an encoding that `decode_text` accepts cannot slip past a search that knows fewer. The marks are asked in this order: the mark
# of UTF-32 LE (FF FE 00 00) starts with the mark of UTF-16 LE (FF FE).
BYTE_ORDER_MARKS: tuple[tuple[bytes, str], ...] = (
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)
UNMARKED_ENCODINGS: tuple[str, ...] = ("utf-16-le", "utf-16-be", "utf-8", "cp1252")  # without a mark: UTF-16 (NUL in every second byte), UTF-8, else ANSI
TEXT_ENCODINGS: tuple[str, ...] = tuple(dict.fromkeys([codec for _, codec in BYTE_ORDER_MARKS] + list(UNMARKED_ENCODINGS)))


def check_length(length: int, limit: int, source: str, what: str = "text") -> None:
    """Refuses (exit code 2) what is longer than `limit`. A reader asks for `limit + 1` bytes and no more and passes the length of what it got:
    one more than the limit says that there is more, and a file of unknown size (a device, a pipe, a file that grows) cannot make it read on.
    A text that was read from a stream without a binary layer counts characters for bytes."""
    if length > limit:
        mebibytes = f" ({limit // (1024 * 1024)} MiB)" if limit >= 1024 * 1024 else ""
        raise UsageError(
            f"{source} holds more than {limit:,} bytes: a {what} may hold at most {limit:,} bytes{mebibytes}.",
            hint="Check that it is the file you meant (a log, a picture or a device is no text), or cut the text into smaller parts.",
        )


def decode_text(data: bytes) -> str:
    """The text of a file, whichever encoding the editor chose.

    A byte order mark decides (UTF-8, UTF-16 as `Out-File` and `>` write it in Windows PowerShell 5.1, UTF-32). UTF-16 without
    a mark is recognised by the NUL that every second byte of mostly ASCII text holds. Otherwise the bytes are read as UTF-8, and
    when they are not UTF-8 as Windows-1252, the "ANSI" text that `Set-Content` writes there. Line ends are left as they are."""
    for mark, codec in BYTE_ORDER_MARKS:
        if data.startswith(mark):
            return data[len(mark) :].decode(codec, "replace")
    unmarked = _utf16_without_mark(data)
    if unmarked is not None:
        return unmarked
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", "replace")


def _utf16_without_mark(data: bytes) -> str | None:
    """The text when the bytes look like UTF-16 with no byte order mark: NUL in (nearly) every second byte and nowhere else."""
    sample = data[:2048]
    pairs = len(sample) // 2
    if not pairs:
        return None
    even, odd = sample[0::2].count(0), sample[1::2].count(0)
    if odd >= pairs * 0.4 and even <= pairs * 0.05:
        return data.decode("utf-16-le", "replace")
    if even >= pairs * 0.4 and odd <= pairs * 0.05:
        return data.decode("utf-16-be", "replace")
    return None


def decode_input(data: bytes, source: str) -> str:
    """The text that a command works with, from a file or from standard input (`source` names it in the error).

    Decoded by `decode_text`, with `\\n` for every line end, as a text stream gives them, so that no byte order mark and no carriage
    return reaches a page, a title or a comment. Bytes that decode to a NUL character are no text (a picture or an archive passed by
    mistake): they are refused instead of being sent as garbage."""
    text = decode_text(data).replace("\r\n", "\n").replace("\r", "\n")
    if "\x00" in text:
        raise ValidationError(f"{source} is not text: it holds NUL characters.", hint="Pass a Markdown or plain text file, not a picture or another binary file.")
    return text
