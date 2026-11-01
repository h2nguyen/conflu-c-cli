"""What can be read of an attachment as text, and how a text that comes from outside is made fit to be shown.

An attachment is data that a stranger may have made. Its text is shown to a person at a terminal and to a program, perhaps an AI agent, so
it is never an instruction: the escape sequences that move a cursor or retitle a window are removed, so are the characters that a reader
cannot see but a program can read (a byte order mark, the controls that turn text around, the tag characters that spell a hidden text),
and e-mail addresses and links to people are redacted unless people are asked for. All pure: the bytes and Confluence are the business
of the ports.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .errors import UnreadableDocument
from .privacy import normalize_newlines, redact_storage
from .textio import decode_text

DEFAULT_MAX_CHARS = 20_000  # what `download --text` shows of one file unless told otherwise
KIND_TEXT, KIND_DOCUMENT, KIND_OTHER = "text", "document", "other"

_MEMO_LIMIT = 100_000  # characters that `printable` remembers the answer for
_ESCAPES = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")
_JOINABLE = r"[^\x00-\x7f\s\u200c\u200d]"  # a character that a zero width joiner can be part of the text next to: not ASCII, no blank, no joiner
_STRAY_JOINER = re.compile(rf"[\u200c\u200d](?:(?!{_JOINABLE})|(?<!{_JOINABLE}[\u200c\u200d]))")  # a joiner that lacks one on a side
_BINARY_HEAD = 8192  # the bytes at the start of a file that are looked at for the NUL that no text holds


class _Screen(dict[int, "int | str | None"]):
    """The table of `str.translate` for `printable`, filled as the characters come: a control character becomes U+FFFD (tab and line feed
    stay), a lone surrogate too (it cannot be written to a terminal), and a format character is dropped (category Cf: zero width
    characters, the bidirectional controls, the byte order mark, the tag characters U+E0000 to U+E007F that spell text nobody sees).
    The table lives as long as the process, so it stops growing at `_MEMO_LIMIT` entries: a text that uses every code point of Unicode
    must not make it large, it only has the rest looked up one by one."""

    def __init__(self) -> None:
        super().__init__({code: "\ufffd" for code in [*range(32), *range(127, 160)] if code not in (9, 10)})
        self[0x200C] = 0x200C  # the joiners that belong to the text are chosen by `_STRAY_JOINER` before the table is applied
        self[0x200D] = 0x200D

    def __missing__(self, code: int) -> int | str | None:
        category = unicodedata.category(chr(code))
        value = None if category == "Cf" else "\ufffd" if category == "Cs" else code
        if len(self) < _MEMO_LIMIT:
            self[code] = value
        return value


_FOR_THE_SCREEN = _Screen()


def printable(text: str) -> str:
    """Text as it may reach a terminal. What comes from outside (the content of an attachment, a file name) can hold escape sequences
    that move the cursor, clear the screen or rewrite what was printed before. They are removed. Other control characters become U+FFFD.
    Format characters (category Cf) are dropped: the controls that turn text around on the screen (a name that reads `exe.png` for
    `png.exe`), zero width characters, the byte order mark and the tag characters that spell text that nobody sees. The two joiners
    (zero width joiner and non-joiner) are the exception where they belong to the text: one that stands between two characters that are
    neither ASCII nor blanks nor joiners themselves, as in an emoji sequence or a Persian word, where dropping it changes the text. A
    joiner anywhere else, and every one of a run of them, is dropped like the rest. Tab and line feed stay."""
    text = _ESCAPES.sub("", text)
    if "\u200c" in text or "\u200d" in text:
        text = _STRAY_JOINER.sub("", text)
    return text.translate(_FOR_THE_SCREEN)


def human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    value = float(size)
    for unit in ("KB", "MB", "GB"):
        value /= 1024
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
    return f"{size} B"  # pragma: no cover


# -- what can be read --------------------------------------------------------------------------------

_TEXT_TYPES = frozenset(
    {
        "application/json", "application/xml", "application/yaml", "application/x-yaml", "application/toml", "application/javascript",
        "application/x-javascript", "application/ecmascript", "application/sql", "application/x-sql", "application/x-sh",
        "application/x-shellscript", "application/x-ndjson", "application/ndjson", "application/csv", "application/x-csv",
        "application/graphql", "application/x-httpd-php", "application/x-powershell",
    }
)
_TEXT_SUFFIXES = ("+json", "+xml", "+yaml")
_BINARY_FAMILIES = ("image/", "audio/", "video/", "font/")
_TEXT_EXTENSIONS = frozenset(
    (
        "txt log md markdown rst adoc csv tsv json jsonl ndjson har xml xsd xsl xslt wsdl xaml html htm xhtml svg yaml yml toml ini "
        "cfg conf config properties sql sh bash zsh ps1 psm1 bat cmd py pyi js mjs cjs ts tsx jsx java kt kts scala groovy gradle cs vb "
        "fs c h cc cpp cxx hpp hh go rs rb php pl pm lua swift r jl dart css scss sass less vue svelte tf tfvars hcl diff patch tex bib "
        "srt vtt ics graphql gql proto csproj props targets sln rss atom"
    ).split()
)
_TEXT_NAMES = frozenset({"dockerfile", "makefile", "readme", "license", "notice", "changelog"})
_OFFICE_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
}
_OFFICE_EXTENSIONS = {"docx": "docx", "docm": "docx", "xlsx": "xlsx", "xlsm": "xlsx", "pptx": "pptx", "pptm": "pptx"}


@dataclass(frozen=True)
class Reading:
    """How the content of an attachment can be read: as `text`, as a `document` of Word, Excel or PowerPoint (`format` is docx, xlsx or
    pptx), or not at all (`other`: a picture, a PDF, an archive)."""

    kind: str
    format: str = ""


def _extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _is_text_type(mime: str) -> bool:
    return mime.startswith("text/") or mime in _TEXT_TYPES or mime.endswith(_TEXT_SUFFIXES)


def reading_of(media_type: str, name: str) -> Reading:
    """How an attachment can be read. The media type and the extension both count: Confluence often says `application/octet-stream`, and a
    browser on Windows says `application/vnd.ms-excel` for a `.csv`. An extension of text does not make an image, a sound or a video text."""
    mime = (media_type or "").split(";")[0].strip().lower()
    extension = _extension(name)
    office = _OFFICE_TYPES.get(mime) or _OFFICE_EXTENSIONS.get(extension)
    if office:
        return Reading(KIND_DOCUMENT, office)
    if _is_text_type(mime):
        return Reading(KIND_TEXT)
    if (extension in _TEXT_EXTENSIONS or name.strip().lower() in _TEXT_NAMES) and not mime.startswith(_BINARY_FAMILIES):
        return Reading(KIND_TEXT)
    return Reading(KIND_OTHER)


def text_of(data: bytes, reading: Reading) -> str:
    """The text of the bytes of a file that `reading_of` said can be read, with `\\n` for every line end.

    A text file is decoded the way an editor or PowerShell wrote it (a byte order mark, else UTF-8, else Windows-1252). Bytes that are
    said to be text and are none (a NUL in the first 8 KiB once decoded) are refused. A document is read by `office_text`.
    Raises `UnreadableDocument`; the message names the kind of the failure and never the content."""
    if reading.kind == KIND_DOCUMENT:
        from .ooxml import office_text  # the reader brings `zipfile` and `xml.etree` with it: only a document needs them

        return office_text(data, reading.format)
    if "\x00" in decode_text(data[:_BINARY_HEAD]):
        raise UnreadableDocument("The content is binary, although the name or the type says text.")
    return normalize_newlines(decode_text(data))


def cut_text(text: str, limit: int) -> tuple[str, bool]:
    """`(text, truncated)`: the text as it is, or cut to at most `limit` characters at the end of a paragraph, else of a line, else of a
    word, taking the last of them that still leaves the reader half of the room (a cut that throws most away is no cut)."""
    if len(text) <= limit:
        return text, False
    for separator in ("\n\n", "\n", " "):
        at = text.rfind(separator, 0, limit + len(separator))  # a separator that starts at the limit ends a complete piece
        if at >= limit // 2 and at > 0:
            return text[:at].rstrip(), True
    return text[:limit], True


# -- people ----------------------------------------------------------------------------------------

def redact_people(text: str) -> str:
    """The text without e-mail addresses, links to the profile of a person and the accounts of mentions (what `redact_storage` takes out).

    The whole text is given to the patterns at once: a text that is cut into stretches first can have an address across a cut, and the
    half of an address is none. The patterns are linear in the length of the text, also for a file that is one long word."""
    if not any(mark in text for mark in ("@", "people/", "spaces/~", "ri:")):
        return text  # nothing in it can be an address, a link or a mention
    return redact_storage(text)
