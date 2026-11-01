"""The settings file: `KEY=value` lines in the format the Bash CLI used.

The file is parsed as data and never executed. Quoting follows the shell (`'a b'`, `"a b"`, `a\\ b`).
What a shell would expand (`$(...)`, backticks, `$'...'`, `$VAR`) is refused instead of being guessed,
unless it sits inside single quotes or is escaped, where the shell takes it literally too.

A line ends at `\\r\\n`, `\\r` or `\\n` and nowhere else (`str.splitlines()` also cuts at U+2028, U+0085 and the form feed, which no editor of
this file means as a line end), and a value with a line break or another control character is never written: it would make the file
unreadable, and every command with it.
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path

from ...application.ports_local import ConfigStore
from ...application.settings import setting_definition
from ...domain.errors import ConfigError
from ...domain.textio import decode_text
from .atomic import write_text_atomically

_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_EXPANSION = re.compile(r"\$[(\'{A-Za-z0-9_@*#?!$-]")
_LINE_END = re.compile(r"\r\n|\r|\n")
_NOT_ONE_LINE = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029]")  # the control characters, and the line and the paragraph separator


def _split_lines(text: str) -> list[str]:
    lines = _LINE_END.split(text)
    if lines and lines[-1] == "":
        lines.pop()  # the line end of the last line: it is not a line of its own (nor is the end of an empty text)
    return lines


def _how_to_mend(name: str) -> str:
    """The command that replaces or removes the line of a setting, or the advice when it is no setting of this program."""
    definition = setting_definition(name)
    if definition is None:
        return f"{name} is no setting of this program: remove the line from the file."
    if definition.secret:
        return "Save the token again with `conflu setup-token`, or remove it with `conflu remove-token`."
    return f"Replace it with `conflu config set {name} VALUE`, or remove it with `conflu config unset {name}`."


def parse_value(name: str, text: str, where: str = "") -> str:
    """The value of one assignment. `where` says which line it was, for the error: ` (line 3 of the file)`."""
    if _expands(text):
        raise ConfigError(
            f"{name} uses shell syntax that the CLI does not execute{where}.",
            hint=f"Write the value itself in the file (in single quotes if it holds a $ or a ~), or set it as an environment variable. {_how_to_mend(name)}",
        )
    try:
        tokens = shlex.split(text, comments=True, posix=True)
    except ValueError as error:
        raise ConfigError(f"{name} has unbalanced quotes in the config file{where}.", hint=f"Fix the line. {_how_to_mend(name)}") from error
    if len(tokens) > 1:
        raise ConfigError(f"{name} has several words without quotes in the config file{where}.", hint=f"Put the value in quotes. {_how_to_mend(name)}")
    return tokens[0] if tokens else ""


def _expands(text: str) -> bool:
    """True when a shell would substitute something in this value."""
    in_single = in_double = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_single:
            in_single = char != "'"
        elif char == "\\":
            index += 1  # the next character is literal
        elif char == "#" and not in_double and (index == 0 or text[index - 1].isspace()):
            break  # the rest is a comment
        elif char == "~" and not in_double and (index == 0 or text[index - 1] == ":"):
            return True  # the home folder
        elif char == "`" or (char == "$" and _EXPANSION.match(text, index)):
            return True
        elif char == "'" and not in_double:
            in_single = True
        elif char == '"':
            in_double = not in_double
        index += 1
    return False


class FileConfigStore(ConfigStore):
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> str:
        return str(self._path)

    def load(self) -> dict[str, str]:
        """All the assignments of the file. A value that cannot be read is a ConfigError that says which line of which file it is: `set`
        and `unset` do not read the values, so they mend a file that `load` refuses."""
        values: dict[str, str] = {}
        for number, line in enumerate(self._lines(), start=1):
            match = _ASSIGNMENT.match(line)
            if match:
                values[match.group(1)] = parse_value(match.group(1), match.group(2), f" (line {number} of {self._path})")
        return values

    def set(self, key: str, value: str) -> None:
        if _NOT_ONE_LINE.search(value):
            raise ConfigError(
                f"{key} was not saved: the value holds a line break or another control character, which would make the configuration file unreadable.",
                hint=(
                    "CONFLUENCE_CA_BUNDLE takes the path of a PEM file, not the text of the certificates: save the text in a file and give its path."
                    if key == "CONFLUENCE_CA_BUNDLE"
                    else "Write the value on one line, without control characters."
                ),
            )
        lines = [line for line in self._lines() if not self._assigns(line, key)]
        lines.append(f"{key}={shlex.quote(value)}")
        self._write(lines)

    def unset(self, key: str) -> bool:
        lines = self._lines()
        kept = [line for line in lines if not self._assigns(line, key)]
        if len(kept) == len(lines):
            return False
        self._write(kept)
        return True

    @staticmethod
    def _assigns(line: str, key: str) -> bool:
        match = _ASSIGNMENT.match(line)
        return bool(match and match.group(1) == key)

    def _lines(self) -> list[str]:
        try:
            return _split_lines(decode_text(self._path.read_bytes()))  # a file from Notepad (UTF-16) or an "ANSI" editor is read too
        except FileNotFoundError:
            return []
        except OSError as error:
            raise ConfigError(f"Cannot read the config file {self._path}: {error}") from error

    def _write(self, lines: list[str]) -> None:
        text = "\n".join(lines) + ("\n" if lines else "")
        try:
            write_text_atomically(self._path, text, private=True)
        except OSError as error:
            raise ConfigError(f"Cannot write the config file {self._path}: {error}") from error
