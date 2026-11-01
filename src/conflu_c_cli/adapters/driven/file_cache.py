"""The cache of the one thing the CLI remembers: the online checks of the last successful `conflu doctor`.

It is a folder of small JSON files, one for each key, and nothing else is ever put in it. Best effort: a folder that cannot be read or
written, a file that is damaged or a clock that is wrong makes the cache behave as an empty one, never as an error.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from ...application.ports_local import Cache
from .atomic import write_text_atomically


class FileCache(Cache):
    def __init__(self, directory: str | Path) -> None:
        self._directory = Path(directory)

    def _file(self, namespace: str, key: str) -> Path:
        return self._directory / (re.sub(r"[^A-Za-z0-9_.-]", "_", f"{namespace}-{key}") + ".json")

    def get(self, namespace: str, key: str, max_age: float) -> str | None:
        path = self._file(namespace, key)
        try:
            if time.time() - path.stat().st_mtime > max_age:
                return None
            return path.read_text(encoding="utf-8")
        except (OSError, ValueError):  # a file that is no UTF-8 text is a damaged one
            return None

    def put(self, namespace: str, key: str, value: str) -> None:
        try:
            write_text_atomically(self._file(namespace, key), value, private=True)  # nothing secret is in it, but nobody else needs to read it
        except OSError:
            pass
