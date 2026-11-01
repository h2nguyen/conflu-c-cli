"""The ports to this computer: the settings file, the memory between two runs, files, the clock, messages and the documentation.

They need nothing of what Confluence holds (no page, no space, no person), so the command line framework can use them without loading the
models of every feature area. `ports.py` has the gateway to Confluence and names these again, so that `from .ports import Files` keeps working.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


class ConfigStore(ABC):
    """Persistent settings: `KEY=value` pairs."""

    @property
    @abstractmethod
    def path(self) -> str: ...

    @abstractmethod
    def load(self) -> dict[str, str]: ...

    @abstractmethod
    def set(self, key: str, value: str) -> None: ...

    @abstractmethod
    def unset(self, key: str) -> bool:
        """True when the key was there."""


class Cache(ABC):
    """What the CLI remembers between two runs. There is exactly one thing: the online checks of the last successful `conflu doctor`, so that
    `conflu doctor --cached AGE` can answer without asking Confluence. Nothing else is cached, ever: no page, no space, no person, no token.
    Best effort: a cache that cannot be read or written behaves as an empty one."""

    @abstractmethod
    def get(self, namespace: str, key: str, max_age: float) -> str | None:
        """The text stored under the key, or None when there is none, when it is older than `max_age` seconds or when it cannot be read."""

    @abstractmethod
    def put(self, namespace: str, key: str, value: str) -> None:
        """Stores the text, replacing what the key held. Errors are ignored."""


class Files(ABC):
    @abstractmethod
    def read_text(self, path: str, encoding: str = "utf-8") -> str: ...

    @abstractmethod
    def read_bytes(self, path: str) -> bytes: ...

    def read_up_to(self, path: str, count: int) -> bytes:
        """At most `count` bytes of the file. A caller that refuses a file longer than `limit` asks for `limit + 1` and looks at what it got: it need not
        read a file to its end, and a device or a pipe has none. This default reads everything and cuts; an adapter that can stop early does."""
        return self.read_bytes(path)[:count]

    @abstractmethod
    def write_text(self, path: str, text: str) -> None:
        """Creates missing parent folders."""

    @abstractmethod
    def write_bytes(self, path: str, data: bytes) -> None:
        """Creates missing parent folders."""

    @abstractmethod
    def exists(self, path: str) -> bool: ...

    @abstractmethod
    def is_dir(self, path: str) -> bool: ...

    def is_file(self, path: str) -> bool:
        """A file that holds bytes with an end: not a folder, and not a device, a pipe or a socket, which have none (reading `/dev/zero` or the console
        never ends). This default says that what exists and is no folder is one; an adapter that can tell the difference does."""
        return self.exists(path) and not self.is_dir(path)

    @abstractmethod
    def size(self, path: str) -> int: ...

    @abstractmethod
    def list_matching(self, directory: str, pattern: str) -> list[str]:
        """Full paths of the files in `directory` that match the glob `pattern`, sorted by name."""

    @abstractmethod
    def join(self, *parts: str) -> str: ...

    @abstractmethod
    def name(self, path: str) -> str: ...


class Clock(ABC):
    @abstractmethod
    def now(self) -> datetime:
        """The current time, timezone aware (UTC)."""


class Diagnostics(ABC):
    """Messages for the person at the terminal (or the agent), apart from the result."""

    @abstractmethod
    def info(self, message: str) -> None: ...

    @abstractmethod
    def warn(self, message: str) -> None: ...

    @abstractmethod
    def debug(self, message: str) -> None: ...


@dataclass(frozen=True)
class DocTopic:
    name: str
    title: str


class Docs(ABC):
    """The documentation that ships with the CLI."""

    @abstractmethod
    def topics(self) -> list[DocTopic]: ...

    @abstractmethod
    def topic(self, name: str) -> str: ...

    @abstractmethod
    def readme(self) -> str: ...

    @abstractmethod
    def changelog(self) -> str: ...

    @abstractmethod
    def skill(self) -> str: ...
