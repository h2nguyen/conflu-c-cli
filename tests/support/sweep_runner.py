"""Runs the command lines of the conformance sweep (tests/support/sweeps.py) against the mock Confluence, through the real adapters.

    python -m tests.support.sweep_runner      prints the rows of the table in docs/reference/compatibility.md ("Which API each command uses")

The test `tests/integration/test_conformance.py` uses `run_sweeps`; the command above is for whoever has to write the rows after a
command was added or changed.
"""
from __future__ import annotations

import io
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Mapping

from conflu_c_cli.adapters.driving.cli.main import run
from conflu_c_cli.bootstrap import create_application

from .conformance import version_of
from .mock_confluence import MockConfluence


@dataclass(frozen=True)
class LineOutput:
    """What one line of a sweep printed, for the privacy sweep. `written` is the text of the files that a line with `--out` wrote (`export`, `page --body-only --out`): a mirror is output too."""

    area: str
    argv: tuple[str, ...]
    code: int
    out: str
    err: str
    written: str = ""


@dataclass
class SweepResult:
    calls: dict[str, set[str]] = field(default_factory=dict)  # command -> the documented calls it made, as `GET /api/v2/pages/{id}`
    outside: dict[str, set[str]] = field(default_factory=dict)  # command -> the calls that are no REST call (see OUTSIDE_THE_REFERENCE)
    unknown: list[str] = field(default_factory=list)  # calls that the matching document does not list
    deprecated: list[str] = field(default_factory=list)  # calls that the matching document lists as deprecated
    invalid_requests: list[str] = field(default_factory=list)  # `area: conflu LINE: CALL: what the document does not allow in it` (see conformance.request_problems)
    deprecated_parameters: list[str] = field(default_factory=list)  # the same, for a query parameter that the document marks as deprecated
    seen_query_names: set[str] = field(default_factory=set)  # the name of every query parameter that a line sent to a documented call
    failures: list[str] = field(default_factory=list)  # runs that did not end with the exit code of their line
    outputs: list[LineOutput] = field(default_factory=list)  # what every run printed
    runs: int = 0


def _argument(text: str, work: Path) -> str:
    return text.replace("{work}", work.as_posix())


def _snapshot(work: Path) -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in work.rglob("*") if path.is_file()}


def _written_text(work: Path, before: dict[Path, int]) -> str:
    """The text of the Markdown and JSON files that appeared or changed since `before` (what `export` and the other `--out` write), in the order of their names."""
    texts = []
    for path in sorted(work.rglob("*")):
        if path.is_file() and path.suffix in (".md", ".json") and before.get(path) != path.stat().st_mtime_ns:
            texts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(texts)


def run_sweep(module: ModuleType, result: SweepResult, env: Mapping[str, str] | None = None, taint: bool = False) -> None:
    """One module of lines, in order, against a mock of its own. `env` is added to the environment of every run; `taint` makes the mock
    put an e-mail address into every free text it answers (see tests/support/taint.py). The mock refuses what the parameter files do not allow
    (`strict_parameters`), and `result.invalid_requests` names the command line that sent it. A module may have `PREPARE(mock)`, which is called
    on the mock before the lines run, to add what they need and the default data does not have (a personal space, see personal_space.py)."""
    mock = MockConfluence()
    mock.taint = taint
    mock.strict_parameters = True
    prepare = getattr(module, "PREPARE", None)
    if prepare is not None:
        prepare(mock)
    mock.start()
    try:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            work = root / "work"
            work.mkdir()
            base = {
                "CONFLUENCE_CONFIG_FILE": str(root / "config" / "conflu-c-cli" / "config"),
                "HOME": str(root),
                "XDG_CACHE_HOME": str(root / "cache"),  # the cache of `doctor` is never written into the profile of the person who runs the tests
                "CONFLUENCE_BASE_URL": mock.base_url,
                "CONFLUENCE_EMAIL": mock.email,
                "CONFLUENCE_API_TOKEN": mock.token,
                **(env or {}),
            }
            for item in module.LINES:
                for name, content in item.files:
                    path = Path(_argument(name, work)) if "{work}" in name else work / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
                argv = [_argument(text, work) for text in item.argv]
                environ = {**base, **dict(item.env)}
                used, outside = len(mock.used_endpoints), len(mock.outside_calls)
                refused, deprecated = len(mock.invalid_requests), len(mock.deprecated_parameters)
                before = _snapshot(work) if "--out" in argv else {}
                out, err = io.StringIO(), io.StringIO()
                code = run(
                    argv,
                    app_factory=lambda diagnostics, environ=environ: create_application(diagnostics, environ),
                    environ=environ,
                    stdout=out,
                    stderr=err,
                    stdin=io.StringIO(item.stdin),
                )
                result.runs += 1
                written = _written_text(work, before) if "--out" in argv else ""
                result.outputs.append(LineOutput(module.__name__.rpartition(".")[2], tuple(item.argv), code, out.getvalue(), err.getvalue(), written))
                if code != item.code:
                    result.failures.append(f"{module.__name__.rpartition('.')[2]}: conflu {' '.join(item.argv)} ended with {code}, not {item.code}: {err.getvalue().strip()[:300]}")
                result.calls.setdefault(item.command, set()).update(mock.used_endpoints[used:])
                result.outside.setdefault(item.command, set()).update(mock.outside_calls[outside:])
                line_text = f"{module.__name__.rpartition('.')[2]}: conflu {' '.join(item.argv)}"
                result.invalid_requests += [f"{line_text}: {entry}" for entry in mock.invalid_requests[refused:]]
                result.deprecated_parameters += [f"{line_text}: {entry}" for entry in mock.deprecated_parameters[deprecated:]]
        result.unknown += mock.unknown_endpoints
        result.deprecated += mock.deprecated_endpoints
        result.seen_query_names |= mock.seen_query_names
    finally:
        mock.stop()


def run_sweeps(modules: tuple[ModuleType, ...], env: Mapping[str, str] | None = None, taint: bool = False) -> SweepResult:
    result = SweepResult()
    for module in modules:
        run_sweep(module, result, env, taint)
    return result


def table_rows(result: SweepResult) -> list[str]:
    rows = []
    for command in sorted(result.calls):
        calls = sorted(result.calls[command], key=lambda call: (version_of(call.partition(" ")[2]), call.partition(" ")[2], call))
        if not calls:
            continue
        versions = sorted({version_of(call.partition(" ")[2]) for call in calls}, reverse=True)
        rows.append(f"| `{command}` | {' + '.join(versions)} | {', '.join(f'`{call}`' for call in calls)} |")
    return rows


if __name__ == "__main__":
    from .sweeps_all import SWEEPS

    outcome = run_sweeps(SWEEPS)
    print("\n".join(table_rows(outcome)))
    for problem in outcome.failures + outcome.unknown + outcome.deprecated + outcome.invalid_requests + outcome.deprecated_parameters:
        print("PROBLEM:", problem)
