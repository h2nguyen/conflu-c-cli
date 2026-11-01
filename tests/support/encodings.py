"""The encodings in which a text file or a pipe may reach the program on Windows: what the tests of the input run through."""
from __future__ import annotations

from typing import Callable

TEXT = "Grüße, Größe und Übung — fertig"
STORAGE = "<p>Grüße, Größe und Übung — fertig</p>"  # what the converter makes of TEXT

ENCODINGS: dict[str, Callable[[str], bytes]] = {
    "UTF-8": lambda text: text.encode("utf-8"),
    "UTF-8 with a byte order mark": lambda text: b"\xef\xbb\xbf" + text.encode("utf-8"),
    "UTF-16 with a mark": lambda text: text.encode("utf-16"),  # little endian: what Windows PowerShell 5.1 writes with `>` and `Out-File`
    "UTF-16 big endian with a mark": lambda text: b"\xfe\xff" + text.encode("utf-16-be"),
    "UTF-16 without a mark": lambda text: text.encode("utf-16-le"),
    "UTF-16 big endian without a mark": lambda text: text.encode("utf-16-be"),
    "Windows-1252": lambda text: text.encode("cp1252"),  # what `Set-Content` writes there
}
