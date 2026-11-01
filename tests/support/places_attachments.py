"""Files in memory for the tests of what must never be written over, into or attached: places that a link, `..` or another case of a name lead to."""
from __future__ import annotations

from typing import Iterator, Mapping

from .fakes import MemoryFiles


class PlacedFiles(MemoryFiles):
    """Files that know where a path leads, as the real ones do (`ComparesPlaces`), and that can be read in pieces (`ReadsPieces`).

    `a/../b` and `./b` are one place, a relative path is one below `/work`, `links` maps a path or a folder to what it points to, and with
    `ignore_case` `B` and `b` are one file. Every operation goes by the place, so a file can be reached under another spelling: that is what a
    link or a relative path is. `piece` makes `read_pieces` hand out that many bytes at a time, however many were asked for."""

    def __init__(self, files: Mapping[str, str | bytes] | None = None, *, links: Mapping[str, str] | None = None, ignore_case: bool = False, piece: int = 0) -> None:
        super().__init__(files)
        self.links = dict(links or {})
        self.ignore_case = ignore_case
        self.piece = piece
        self.pieces_read: list[str] = []

    @staticmethod
    def _fold(path: str) -> str:
        parts: list[str] = []
        for part in path.split("/"):
            if part == "..":
                if parts:
                    parts.pop()
            elif part not in ("", "."):
                parts.append(part)
        return "/" + "/".join(parts)

    def place(self, path: str) -> str:
        found = self._fold(path if path.startswith("/") else "/work/" + path)
        for link, target in self.links.items():
            if found == link or found.startswith(link.rstrip("/") + "/"):
                found = self._fold(target + found[len(link) :])
                break
        return found.lower() if self.ignore_case else found

    def _key(self, path: str) -> str:
        """The name under which a file at this place is stored, else the path as it is."""
        place = self.place(path)
        return next((key for key in self.files if self.place(key) == place), path)

    def same_place(self, first: str, second: str) -> bool:
        return self.place(first) == self.place(second)

    def read_pieces(self, path: str, size: int) -> Iterator[bytes]:
        self.pieces_read.append(path)
        data = self.read_bytes(path)
        step = self.piece or size
        for start in range(0, len(data), step):
            yield data[start : start + step]

    def put(self, path: str, data: bytes) -> None:
        """A file that is there before the test starts, not written by the code under test."""
        self.files[self._key(path)] = data

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        return super().read_text(self._key(path), encoding)

    def read_bytes(self, path: str) -> bytes:
        return super().read_bytes(self._key(path))

    def write_text(self, path: str, text: str) -> None:
        super().write_text(self._key(path), text)

    def write_bytes(self, path: str, data: bytes) -> None:
        super().write_bytes(self._key(path), data)

    def size(self, path: str) -> int:
        return super().size(self._key(path))

    def exists(self, path: str) -> bool:
        place = self.place(path)
        return any(self.place(key) == place for key in self.files) or self.is_dir(path)

    def is_dir(self, path: str) -> bool:
        place = self.place(path).rstrip("/") + "/"
        return any(self.place(key).startswith(place) for key in self.files)
