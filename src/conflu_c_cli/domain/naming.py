"""File names for exported pages and downloaded attachments."""
from __future__ import annotations

import re
import unicodedata

from .errors import ValidationError

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# The names that Windows reads as a device, with or without an extension. `\u00b9\u00b2\u00b3` are the superscript digits that it treats as digits too.
_RESERVED = {"con", "prn", "aux", "nul", "conin$", "conout$", *(f"{device}{digit}" for device in ("com", "lpt") for digit in "123456789\u00b9\u00b2\u00b3")}
_MAX_BYTES = 200  # a name may have 255 bytes of UTF-8 (Linux, macOS) or 255 characters (Windows) in a folder: some room is left for what the folder adds


def _shortened(name: str) -> str:
    """The name cut to `_MAX_BYTES` bytes of UTF-8, at a whole character and keeping a short extension. A system refuses a longer name, which
    would stop a download after other files were written."""
    if len(name.encode("utf-8")) <= _MAX_BYTES:
        return name
    stem, dot, extension = name.rpartition(".")
    if not dot or not stem or len(extension.encode("utf-8")) > 20:
        stem, extension = name, ""
    room = _MAX_BYTES - (len(extension.encode("utf-8")) + 1 if extension else 0)
    stem = stem.encode("utf-8")[:room].decode("utf-8", "ignore").rstrip(". ") or "_"
    return f"{stem}.{extension}" if extension else stem


def slugify(text: str, max_length: int = 60) -> str:
    """Lower case words joined by hyphens, ASCII only; `page` when nothing is left."""
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[a-z0-9]+", folded.lower())
    slug = "-".join(words)[:max_length].strip("-")
    return slug or "page"


_ID_CHARS = re.compile(r"[^0-9A-Za-z_-]")


def export_file_name(title: str, page_id: str, extension: str = ".md") -> str:
    """`title-slug-123.md`: readable, and the id keeps it unique when titles collide. The id comes out of Confluence's answer and is no path: whatever
    is not a letter, a digit, `_` or `-` becomes `_`, so that no id can name a folder (`7/../../x`) and write outside the export folder."""
    return f"{slugify(title)}-{_ID_CHARS.sub('_', str(page_id)) or '_'}{extension}"


def safe_file_name(name: str) -> str:
    """A name that is safe to create in a folder on any system: no folders in it, no characters Windows refuses or that
    show nothing, no device name, not longer than a file system takes. Raises when nothing is left of it."""
    base = re.split(r"[\\/]", name or "")[-1]
    # Control and format characters (zero-width, a right-to-left override that makes `.exe` look like `.txt`) show nothing, and a lone surrogate (which
    # JSON can carry) is no text that a file system or a terminal takes.
    visible = "".join("_" if unicodedata.category(char) in ("Cc", "Cf", "Cs") else char for char in base)
    cleaned = _shortened(_INVALID.sub("_", visible).strip().rstrip(". "))
    if cleaned in ("", ".", ".."):
        raise ValidationError(f"The name cannot be used as a file name: {name!r}")
    if cleaned.startswith("."):
        cleaned = "_" + cleaned  # a download must not plant a hidden file such as `.mcp.json` or `.env` where the person did not look
    if cleaned.split(".")[0].rstrip().lower() in _RESERVED:
        cleaned = "_" + cleaned
    return cleaned
