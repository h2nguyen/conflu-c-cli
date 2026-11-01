"""Writing the text of a command that only reads into a file (`--out`), so that it reaches the file as it is.

`conflu page ID --body-only > page.xml` is the shell's write, and in Windows PowerShell 5.1 the shell re-encodes: the UTF-8 that the program prints
is decoded with the code page of the console and stored as UTF-16, so every character that is not ASCII is damaged, and `update --file page.xml`
then writes the damage back. A file that the program writes itself is UTF-8 without a byte order mark, with the line ends of the text.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from ..domain.attachguards import SCAN_LIMIT, SCAN_PIECE, holds_secret, secret_needles
from ..domain.attachmenttext import human_size, printable
from ..domain.errors import UsageError, ValidationError
from .attachments import _folder_of, _same_place  # the places of `download` and `attach`, compared the same way
from .ports import Files
from .ports_attachments import ReadsPieces
from .settings import Settings


@dataclass(frozen=True)
class Written:
    path: str  # as it was given
    size: int  # bytes in the file


class OutFile:
    """Writes the text of a command into the file that `--out` names. Never over a file that is there without `force`, and never over what must
    not be replaced even with it: the configuration of the CLI, a file in the folder where the CLI keeps it (the token is there) and a file that
    holds the token (a copy of the settings, a shell history, a log). The path is judged before the command asks Confluence for anything
    (`check`) and again just before the write, so a file that appeared meanwhile is not replaced either. The write is whole or not at all."""

    def __init__(self, files: Files, settings: Settings | None = None, *, protected: Sequence[str] = ()) -> None:
        self._files = files
        self._protected = tuple(path for path in protected if path)
        self._needles = secret_needles(settings.api_token, settings.email) if settings is not None else ()

    def check(self, path: str, *, force: bool = False) -> None:
        """Refuses a path that must not be written, and writes nothing. A value that is given and empty is an error, never "no file"."""
        if not path.strip():
            raise UsageError("--out is empty.", hint="Give the file to write, for example --out page.xml.")
        if path == "-":
            raise UsageError("--out names a file, and `-` is not standard output.", hint="Leave out --out to print the text.")
        if any(ord(char) < 32 or char == "\x7f" for char in path):
            raise UsageError("--out holds a control character.", hint="Write the path of the file without it.")
        if path.endswith(("/", "\\")):
            raise UsageError(f"{printable(path)} ends with a separator, which names a folder, and --out names a file.", hint=f"Add the name of the file, for example {path}page.xml.")
        self._refuse_own_files(path)
        if self._files.is_dir(path):
            raise ValidationError(f"{printable(path)} is a folder, not a file.", hint="Choose a file name with --out; --force does not replace a folder.")
        if not self._files.exists(path):
            return
        if not force:
            raise ValidationError(f"{printable(path)} exists already.", hint="Use --force to replace it, or choose another file with --out.")
        if not self._files.is_file(path):  # a device or a pipe has no end: it is not read for the token, and it is not "replaced"
            raise ValidationError(f"{printable(path)} is not a plain file (a device, a pipe or the like).", hint="Choose another file with --out; --force replaces a file and nothing else.")
        self._refuse_secrets(path)

    def write(self, path: str, text: str, *, force: bool = False) -> Written:
        self.check(path, force=force)
        data = text.encode("utf-8", errors="replace")  # as the files of the CLI are written: a character that has no encoding is a `?`, not a failure
        self._files.write_bytes(path, data)
        return Written(path, len(data))

    def _refuse_own_files(self, path: str) -> None:
        """The places are compared, not the spellings, so a relative path, `..`, a link or another case of the same name is caught too. A file in a
        folder below the one of the configuration is no risk."""
        folder = _folder_of(self._files, path) or "."
        for config in self._protected:
            if _same_place(self._files, path, config):
                raise UsageError(
                    f"{printable(path)} is the configuration file of this CLI. It holds the API token and is never replaced.",
                    hint="Choose another file with --out. This is refused with --force too.",
                )
            if _same_place(self._files, folder, _folder_of(self._files, config) or "."):
                raise UsageError(
                    f"{printable(path)} is in the folder where the CLI keeps its own configuration, which holds the token.",
                    hint="Choose a file somewhere else with --out. This is refused with --force too.",
                )

    def _refuse_secrets(self, path: str) -> None:
        """A file that is replaced is gone, and one that holds the token may be the only copy of it. It is looked at piece by piece, so a file of any
        size is searched without being held; one that is too large to be searched cannot be known to be free of it."""
        if not self._needles:
            return
        size = self._files.size(path)
        if size > SCAN_LIMIT:
            raise ValidationError(
                f"{printable(path)} is {human_size(size)}, more than the {human_size(SCAN_LIMIT)} that are searched for the API token before a file is "
                "replaced; a file that is not searched is not replaced.",
                hint="Choose another file with --out.",
            )
        if holds_secret(self._pieces(path), self._needles):
            raise UsageError(
                f"{printable(path)} holds the API token of this CLI. It is never replaced.",
                hint="Choose another file with --out. This is refused with --force too: a copy of the settings, a shell history or a log is where the token usually is.",
            )

    def _pieces(self, path: str) -> Iterable[bytes]:
        return self._files.read_pieces(path, SCAN_PIECE) if isinstance(self._files, ReadsPieces) else [self._files.read_bytes(path)]
