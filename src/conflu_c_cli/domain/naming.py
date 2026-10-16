"""File names for exported pages and downloaded attachments."""
from __future__ import annotations

import re
import unicodedata

from .errors import ValidationError

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)), *(f"lpt{n}" for n in range(1, 10))}


def slugify(text: str, max_length: int = 60) -> str:
    """Lower case words joined by hyphens, ASCII only; `page` when nothing is left."""
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[a-z0-9]+", folded.lower())
    slug = "-".join(words)[:max_length].strip("-")
    return slug or "page"


def export_file_name(title: str, page_id: str, extension: str = ".md") -> str:
    """`title-slug-123.md`: readable, and the id keeps it unique when titles collide."""
    return f"{slugify(title)}-{page_id}{extension}"


def safe_file_name(name: str) -> str:
    """A name that is safe to create in a folder on any system: no folders in it, no characters Windows refuses or that
    show nothing, no device name. Raises when nothing is left of it."""
    base = re.split(r"[\\/]", name or "")[-1]
    # Control and format characters (zero-width, a right-to-left override that makes `.exe` look like `.txt`) show nothing.
    visible = "".join("_" if unicodedata.category(char) in ("Cc", "Cf") else char for char in base)
    cleaned = _INVALID.sub("_", visible).strip().rstrip(". ")
    if cleaned in ("", ".", ".."):
        raise ValidationError(f"The name cannot be used as a file name: {name!r}")
    if cleaned.split(".")[0].lower() in _RESERVED:
        cleaned = "_" + cleaned
    return cleaned
