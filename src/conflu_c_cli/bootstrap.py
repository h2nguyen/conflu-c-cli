"""The composition root: the one place that knows the real adapters and wires them to the application.

Nothing else imports from here. The command line adapter gets an `app_factory` and never learns
which adapters are behind it, so tests hand it a factory with fakes instead.

Nothing is imported before it is needed, because on a computer where every file costs a virus scan that is most of what a call
takes: the application and the file adapters when it is created (a command that needs no application, such as `help` or `version`,
loads none of them), the use cases when one is first used (`application/app.py`), and the code that talks to Confluence (HTTP, TLS and the
REST calls of every feature area) when a use case first asks Confluence for something (`_LazyGateway`), so `conflu config show` and
`conflu current` never load it. `tests/test_startup.py` holds this to what a real start loads.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator, Mapping, Sequence, TextIO, cast

from .adapters.driving.cli.main import run
from .domain.errors import ConfigError
from .version import __version__

if TYPE_CHECKING:
    from .adapters.driven.http_transport import HttpTransport
    from .application.app import Application
    from .application.ports import ConfluenceGateway
    from .application.ports_local import Diagnostics
    from .application.settings import Settings


def effective_values(stored: Mapping[str, str], environ: Mapping[str, str]) -> dict[str, str]:
    """The config file overlaid with the environment: a variable set in the shell wins. An empty variable counts as
    not set, so `export CONFLUENCE_HIDE_USERS=` cannot switch off a policy that the file sets."""
    from .application.settings import SETTING_DEFS

    values = dict(stored)
    values.update({definition.name: environ[definition.name] for definition in SETTING_DEFS if environ.get(definition.name)})
    return values


class _LazyGateway:
    """The gateway to Confluence, made when a use case first calls it. Making it loads the HTTP and TLS code and the REST calls of every feature
    area, which a command that never asks Confluence has no use for. Everything that is asked of this object is asked of the real gateway."""

    def __init__(self, settings: Settings, diagnostics: Diagnostics) -> None:
        self._settings = settings
        self._diagnostics = diagnostics
        self._transport: HttpTransport | None = None
        self._real: ConfluenceGateway | None = None

    def _gateway(self) -> ConfluenceGateway:
        if self._real is None:
            from .adapters.driven.confluence_rest import RestConfluenceGateway
            from .adapters.driven.http_transport import HttpTransport

            self._transport = HttpTransport(self._settings, debug=self._diagnostics.debug)
            self._real = RestConfluenceGateway(self._settings, self._transport)
        return self._real

    def __getattr__(self, name: str) -> Any:  # only for what this object has not itself: the operations of the gateway
        return getattr(self._gateway(), name)

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()


def create_application(diagnostics: Diagnostics, environ: Mapping[str, str] | None = None) -> Application:
    from .adapters.driven.file_cache import FileCache
    from .adapters.driven.file_config import FileConfigStore
    from .adapters.driven.local_docs import LocalDocs, find_root
    from .adapters.driven.paths import cache_directory, config_file
    from .adapters.driven.system import LocalFiles, SystemClock
    from .application.app import Application
    from .application.settings import Settings, UnreadableSettings

    env = os.environ if environ is None else environ
    store = FileConfigStore(config_file(env))
    try:
        settings = Settings.from_mapping(effective_values(store.load(), env))
    except ConfigError as problem:  # a line of the file, or a value, that cannot be read: the commands that mend it must still run
        settings = UnreadableSettings(problem)  # type: ignore[assignment]  # it answers for `Settings`, and only what an error report and the repairs need
    gateway = _LazyGateway(settings, diagnostics)
    root = find_root()
    app = Application.create(
        settings=settings,
        gateway=cast("ConfluenceGateway", gateway),
        store=store,
        files=LocalFiles(),
        clock=SystemClock(),
        docs=LocalDocs(root),
        diagnostics=diagnostics,
        environ=env,
        runtime=_LazyFacts(env, root),
        closers=(gateway.close,),
        cache=FileCache(cache_directory(env)),
    )
    if isinstance(settings, UnreadableSettings):
        settings.seal()
    return app


def runtime_facts(environ: Mapping[str, str], root: Path) -> dict[str, str]:
    """What `conflu doctor` says about the program itself: the version, the Python, whether `conflu` is found by name on the PATH
    (and from where this run was started), the `conflu.py` of this installation that a program runs (`python "<entry>" ...`) instead of a
    launcher, and the installer that can put the launcher on the PATH. The installer is named only in a source checkout: the copy inside an
    installation refuses to install over itself."""
    import shutil  # only the doctor needs it

    launcher = shutil.which("conflu", path=environ.get("PATH")) or ""
    if launcher.lower().endswith((".py", ".pyw")):  # the `conflu.py` of a source folder, which Windows finds when `.PY` is in PATHEXT: no launcher
        launcher = ""
    installer = root / "install.py"
    entry = root / "conflu.py"
    source_checkout = (root / "src" / "conflu_c_cli").is_dir()
    return {
        "version": __version__,
        "python": sys.version.split()[0],
        "launcher": launcher,
        "program": sys.argv[0] if sys.argv else "",
        "entry": str(entry) if entry.is_file() else "",
        "install_script": str(installer) if source_checkout and installer.is_file() else "",
    }


class _LazyFacts(Mapping[str, str]):
    """The facts of `runtime_facts`, made when the doctor first asks for one. Looking for the launcher scans the whole PATH, which is not
    worth its time for the commands that never ask, and dear when a folder of the PATH is on a slow network drive."""

    def __init__(self, environ: Mapping[str, str], root: Path) -> None:
        self._environ = environ
        self._root = root
        self._facts: dict[str, str] | None = None

    def _load(self) -> dict[str, str]:
        if self._facts is None:
            self._facts = runtime_facts(self._environ, self._root)
        return self._facts

    def __getitem__(self, key: str) -> str:
        return self._load()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._load())

    def __len__(self) -> int:
        return len(self._load())


def _use_utf8(stream: TextIO, **options: str) -> None:
    """UTF-8 and plain `\\n` on every platform, so `$(conflu current)` has no stray carriage return."""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace", **options)


def _silence_stdout() -> None:
    """Point stdout at the null device, so the flush at exit cannot fail on a closed pipe."""
    try:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    except (OSError, ValueError):
        pass


def _flush_quietly() -> int:
    """Flush at the end; a reader that closed early (`| head`) must not end in a traceback."""
    try:
        sys.stdout.flush()
        return 0
    except OSError:
        _silence_stdout()
        return 141


def main(argv: Sequence[str] | None = None) -> int:
    _use_utf8(sys.stdout, newline="\n")
    _use_utf8(sys.stderr, newline="\n")
    _use_utf8(sys.stdin)
    code = run(sys.argv[1:] if argv is None else argv, app_factory=create_application)
    if code == 141:
        _silence_stdout()
        return code
    return code or _flush_quietly()
