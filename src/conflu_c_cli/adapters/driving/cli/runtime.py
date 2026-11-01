"""What a running command has at hand: the application, the streams and the output mode."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Mapping, TextIO

from ....application.ports_local import Diagnostics
from ....domain.errors import ConfluCliError
from ....domain.textio import BODY_LIMIT, check_length, decode_input
from .render import dumps_json, printable, to_jsonable
from .spec import Command

if TYPE_CHECKING:
    from ....application.app import Application

AppFactory = Callable[[Diagnostics], "Application"]


def environment_wants_json(environ: Mapping[str, str]) -> bool:
    """CONFLUENCE_OUTPUT=json in the environment, or the agent profile there (JSON is its default, unless CONFLUENCE_OUTPUT says otherwise)."""
    output = environ.get("CONFLUENCE_OUTPUT", "").strip().lower()
    if output:
        return output == "json"
    return environ.get("CONFLUENCE_PROFILE", "").strip().lower() == "agent"


class StderrDiagnostics(Diagnostics):
    """Messages for the person (or agent) at the terminal. They go to stderr, never into the result."""

    def __init__(self, stream: TextIO, verbose: bool = False) -> None:
        self._stream = stream
        self._verbose = verbose
        self.is_quiet: Callable[[], bool] = lambda: False  # the agent profile: informational messages are left out, warnings stay

    def info(self, message: str) -> None:
        if not self.is_quiet():
            self._stream.write(printable(f"[conflu] {message}") + "\n")

    def warn(self, message: str) -> None:
        self._stream.write(printable(f"[conflu] WARNING: {message}") + "\n")

    def debug(self, message: str) -> None:
        if self._verbose:
            self._stream.write(printable(f"[conflu] debug: {message}") + "\n")


class Context:
    def __init__(
        self,
        *,
        command: Command,
        app_factory: AppFactory,
        out: TextIO,
        err: TextIO,
        stdin: TextIO,
        json_flag: bool,
        verbose: bool,
        environ: Mapping[str, str],
    ) -> None:
        self.command = command
        self.out = out
        self.err = err
        self.stdin = stdin
        self.diagnostics = StderrDiagnostics(err, verbose)
        self.diagnostics.is_quiet = self._is_quiet
        self._app_factory = app_factory
        self._app: Application | None = None
        self._json_flag = json_flag
        self.environ = environ

    @property
    def app(self) -> Application:
        if self._app is None:
            self._app = self._app_factory(self.diagnostics)
        return self._app

    def _is_quiet(self) -> bool:
        """Whether the settings keep informational messages off standard error. Reads them only for a command that needs them."""
        if self._app is None and not self.command.needs_app:
            return False
        try:
            return self.app.settings.quiet
        except ConfluCliError:
            return False  # a broken configuration is reported by the command itself

    @property
    def app_factory(self) -> AppFactory:
        """How an application is built, for a front end that runs commands itself (`conflu mcp`)."""
        return self._app_factory

    @property
    def explicit_json(self) -> bool:
        """JSON was asked for on the command line or in the environment (CONFLUENCE_OUTPUT, the agent profile); no settings need to be read for that."""
        return self._json_flag or environment_wants_json(self.environ)

    @property
    def json_flag(self) -> bool:
        """`--json` was given on the command line itself (not only through CONFLUENCE_OUTPUT)."""
        return self._json_flag

    @property
    def settings_json_default(self) -> bool | None:
        """Whether the settings (CONFLUENCE_OUTPUT in the config file, the agent profile) make JSON the default; None while no application was built."""
        return None if self._app is None else self._app.settings.json_by_default

    @property
    def json_mode(self) -> bool:
        if not self.command.json_output:
            return False
        if self.explicit_json:
            return True
        return self.command.needs_app and self.app.settings.json_by_default

    def close(self) -> None:
        if self._app is not None:
            self._app.close()

    def print(self, text: str = "") -> None:
        self.out.write(printable(text) + "\n")

    def print_json(self, value: Any) -> None:
        """Pretty on a terminal, compact when piped (agents and scripts)."""
        pretty = bool(getattr(self.out, "isatty", lambda: False)())
        self.print(dumps_json(to_jsonable(value), pretty=pretty))

    def read_stdin(self, limit: int = BODY_LIMIT, what: str = "text") -> str:
        """Standard input as text. As with a file, a byte order mark, UTF-16 and Windows-1252 text are what they are: Windows PowerShell 5.1
        pipes UTF-16 or "ANSI" text. Line ends are `\\n` (what a text stream gives). At most `limit` bytes: it is read to one byte beyond
        that and no further, and more is refused, because a pipe may never end."""
        raw = getattr(self.stdin, "buffer", None)
        if raw is None:
            text = self.stdin.read(limit + 1)
            check_length(len(text), limit, "Standard input", what)
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            return text[1:] if text.startswith("\ufeff") else text
        data = raw.read(limit + 1)
        check_length(len(data), limit, "Standard input", what)
        return decode_input(data, "Standard input")

    def read_input(self, path: str, limit: int = BODY_LIMIT, what: str = "text") -> str:
        """The text of a file, or of standard input when the path is `-`. A file may be UTF-8, UTF-8 with a byte order mark, UTF-16
        (what Windows PowerShell 5.1 writes) or Windows-1252, so a byte order mark never ends up in the text that is sent to Confluence.
        It is read to one byte beyond `limit` and no further (a device has no end, whatever size it claims), and a longer one is refused."""
        if path == "-":
            return self.read_stdin(limit, what)
        data = self.app.files.read_up_to(path, limit + 1)
        check_length(len(data), limit, path, what)
        return decode_input(data, path)
