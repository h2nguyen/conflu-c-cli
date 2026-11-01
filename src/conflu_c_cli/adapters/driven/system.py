"""The file system and the clock."""
from __future__ import annotations

import fnmatch
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from ...application.ports_local import Clock, Files
from ...domain.errors import ValidationError
from ...domain.textio import BODY_LIMIT, check_length, decode_input
from .atomic import write_bytes_atomically, write_text_atomically


def _inside(entry: Path, root: Path) -> bool:
    """True when the file, after links are followed, is in the folder `root` (already resolved) or below it."""
    try:
        return entry.resolve().is_relative_to(root)
    except (OSError, RuntimeError):  # a link loop, or a name the system refuses
        return False


class LocalFiles(Files):
    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        """The default encoding means: the text as a person or Windows PowerShell 5.1 wrote it (UTF-8, UTF-16, Windows-1252, with or
        without a byte order mark). An encoding that is asked for by name is used as it is. A file of more than `BODY_LIMIT` bytes is
        refused, and read no further than one byte beyond it: a device or a pipe has no end."""
        data = self.read_up_to(path, BODY_LIMIT + 1)
        check_length(len(data), BODY_LIMIT, path)
        if encoding.lower().replace("_", "-") in ("utf-8", "utf8"):
            return decode_input(data, path)
        try:
            return data.decode(encoding).replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError as error:
            raise ValidationError(f"{path} is not valid {encoding} text.") from error

    def read_bytes(self, path: str) -> bytes:
        try:
            return Path(path).read_bytes()
        except OSError as error:
            raise ValidationError(f"Cannot read {path}: {error.strerror or error}") from error

    def read_up_to(self, path: str, count: int) -> bytes:
        try:
            with Path(path).open("rb") as stream:
                return stream.read(count)
        except OSError as error:
            raise ValidationError(f"Cannot read {path}: {error.strerror or error}") from error

    def write_text(self, path: str, text: str) -> None:
        try:
            write_text_atomically(Path(path), text)
        except OSError as error:
            raise ValidationError(f"Cannot write {path}: {error.strerror or error}") from error

    def write_bytes(self, path: str, data: bytes) -> None:
        try:
            write_bytes_atomically(Path(path), data)
        except OSError as error:
            raise ValidationError(f"Cannot write {path}: {error.strerror or error}") from error

    # Before Python 3.13 `Path.exists`, `is_dir` and `is_file` let an error other than "not there" through (a name longer than the file system allows is
    # ENAMETOOLONG on Linux and macOS): such a path is no file and no folder, which is all that these three are asked.
    def exists(self, path: str) -> bool:
        try:
            return Path(path).exists()
        except OSError:
            return False

    def is_dir(self, path: str) -> bool:
        try:
            return Path(path).is_dir()
        except OSError:
            return False

    def is_file(self, path: str) -> bool:
        try:
            return Path(path).is_file()  # False for a device, a pipe and a socket, which a read would wait on for ever
        except OSError:
            return False

    def size(self, path: str) -> int:
        try:
            return Path(path).stat().st_size
        except OSError as error:
            raise ValidationError(f"Cannot read {path}: {error.strerror or error}") from error

    def list_matching(self, directory: str, pattern: str) -> list[str]:
        """The files of a folder that match, by name. A link to a file outside the folder is left out: a folder that somebody else filled (a clone) could
        otherwise make `import-md-dir` publish any text file that the person can read."""
        try:
            root = Path(directory).resolve()
            entries = sorted(Path(directory).iterdir(), key=lambda entry: entry.name)
        except OSError as error:
            raise ValidationError(f"Cannot read {directory}: {error.strerror or error}") from error
        return [str(entry) for entry in entries if entry.is_file() and fnmatch.fnmatch(entry.name, pattern) and _inside(entry, root)]

    def join(self, *parts: str) -> str:
        return os.path.join(*parts)

    def name(self, path: str) -> str:
        return os.path.basename(path)

    def same_place(self, first: str, second: str) -> bool:
        """What `ComparesPlaces` asks: a link, `..`, another case of a name on Windows, a short name and a hard link all lead to one place."""
        try:
            if os.path.exists(first) and os.path.exists(second):
                return os.path.samefile(first, second)
            return os.path.normcase(os.path.realpath(first)) == os.path.normcase(os.path.realpath(second))
        except (OSError, ValueError):
            return False

    def read_pieces(self, path: str, size: int) -> Iterator[bytes]:
        """What `ReadsPieces` asks: a file of any size without holding it in memory."""
        try:
            with open(path, "rb") as stream:
                while True:
                    piece = stream.read(size)
                    if not piece:
                        return
                    yield piece
        except OSError as error:
            raise ValidationError(f"Cannot read {path}: {error.strerror or error}") from error


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(timezone.utc)
