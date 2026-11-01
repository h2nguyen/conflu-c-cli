"""The command line entry point: from arguments to an exit code."""
from __future__ import annotations

import errno
import io
import json
import os
import sys
from typing import Mapping, Sequence, TextIO

from ....domain.errors import ConfluCliError, UsageError
from ....version import __version__
from .help import render_command_help, render_overview
from .registry import all_commands, find_command, suggestions
from .render import dumps_json, printable, to_jsonable
from .runtime import AppFactory, Context, StderrDiagnostics, environment_wants_json
from .spec import Command

_CLOSED_PIPE = (errno.EPIPE, errno.EINVAL)
_TRUE = ("1", "true", "yes", "on")
_UNEXPECTED_HINT = "Run again with --verbose for details and report it if it persists."


def _wants_help(arguments: Sequence[str]) -> bool:
    return any(item in ("-h", "--help") for item in arguments)


def _error_text(error: ConfluCliError) -> str:
    """A message can carry what the server or a page said, so it is made safe for a terminal like everything else."""
    lines = [f"ERROR: {error.message}"]
    if error.hint:
        lines.append(f"Hint: {error.hint}")
    return printable("\n".join(lines))


def _error_body(error: ConfluCliError) -> dict[str, object]:
    return {
        "code": error.code,
        "message": error.message,
        "hint": error.hint,
        "exitCode": error.exit_code,
        "details": error.details,
    }


def _error_json(error: ConfluCliError) -> str:
    return dumps_json(to_jsonable({"error": _error_body(error)}), pretty=False)


def _wants_json(arguments: Sequence[str], environ: Mapping[str, str]) -> bool:
    return "--json" in arguments or environment_wants_json(environ)


def _settings_say_json(app_factory: AppFactory) -> bool:
    """Whether the settings (the configuration file, the agent profile) make JSON the default, asked of a throw-away application: it reads
    the configuration and connects to nothing. For an error that came before any command had built its own."""
    try:
        app = app_factory(StderrDiagnostics(io.StringIO()))
    except Exception:  # a broken configuration is reported by the command, as text
        return False
    try:
        return app.settings.json_by_default
    finally:
        app.close()


def _environment_wants_envelope(environ: Mapping[str, str]) -> bool:
    return environ.get("CONFLUENCE_JSON_ENVELOPE", "").strip().lower() in _TRUE


def _envelope_switched_on(arguments: Sequence[str], environ: Mapping[str, str]) -> bool:
    return "--json-envelope" in arguments or _environment_wants_envelope(environ)


def _streams(arguments: Sequence[str]) -> bool:
    """Whether the command talks on standard input and output itself (a server): nothing of it can be wrapped."""
    command = find_command(arguments[0]) if arguments and arguments[0] not in ("-V", "--version") else None
    return bool(command and command.streams)


def _envelope(value: Mapping[str, object]) -> str:
    return dumps_json(to_jsonable(value), pretty=False)


def _envelope_data(command: Command, text: str) -> object:
    """What a command printed, as the `data` of an envelope: its JSON, or for a command without JSON (or a mode without it, such as
    `page --body-only`) its text."""
    if command.json_output:
        try:
            return json.loads(text) if text.strip() else None
        except ValueError:
            pass
    return {"text": text.rstrip("\n")}


def run(
    argv: Sequence[str],
    *,
    app_factory: AppFactory,
    environ: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    stdin: TextIO | None = None,
) -> int:
    out, err, source = stdout or sys.stdout, stderr or sys.stderr, stdin or sys.stdin
    env = os.environ if environ is None else environ
    arguments = list(argv)
    envelope = _envelope_switched_on(arguments, env) and not _streams(arguments)
    try:
        return _dispatch(arguments, app_factory, env, out, err, source)
    except ConfluCliError as error:
        as_json = _wants_json(arguments, env)
        if not as_json:  # the settings may ask for JSON too; the command knows when it got as far as reading them
            as_json = _settings_say_json(app_factory) if error.report_as_json is None else error.report_as_json
        err.write((_error_json(error) if as_json else _error_text(error)) + "\n")
        if envelope:
            out.write(_envelope({"ok": False, "error": _error_body(error)}) + "\n")
        return error.exit_code
    except BrokenPipeError:
        return 141  # the reader of our output went away, as in `conflu pages | head`
    except KeyboardInterrupt:
        err.write("Interrupted.\n")
        return 130
    except Exception as error:  # a bug: say so plainly, with the traceback only on request
        if isinstance(error, OSError) and error.errno in _CLOSED_PIPE:
            return 141  # Windows reports a closed pipe as EINVAL
        verbose = "-v" in arguments or "--verbose" in arguments
        body: dict[str, object] = {
            "code": "ERROR",
            "message": f"unexpected {type(error).__name__}: {error}",
            "hint": "" if verbose else _UNEXPECTED_HINT,
            "exitCode": 1,
            "details": {},
        }
        trace = ""
        if verbose:
            import traceback

            trace = printable(traceback.format_exc())
        if _wants_json(arguments, env) or _settings_say_json(app_factory):  # a failure is a JSON error when JSON is asked for, a bug as well
            err.write(trace + dumps_json(to_jsonable({"error": body}), pretty=False) + "\n")
        else:
            err.write(printable(f"ERROR: {body['message']}") + "\n" + (trace or f"Hint: {_UNEXPECTED_HINT}\n"))
        if envelope:
            out.write(_envelope({"ok": False, "error": body}) + "\n")
        return 1


def _dispatch(
    arguments: list[str], app_factory: AppFactory, env: Mapping[str, str], out: TextIO, err: TextIO, source: TextIO
) -> int:
    if not arguments or arguments[0] in ("-h", "--help"):
        out.write(render_overview(all_commands(), __version__) + "\n")  # only the overview lists every command: any other command imports its own module only
        return 0
    if arguments[0] in ("-V", "--version"):
        arguments = ["version", *arguments[1:]]
    name, rest = arguments[0], arguments[1:]
    command = find_command(name)
    if command is None:
        close = suggestions(name)
        raise UsageError(
            f"Unknown command: {name}" + (f". Did you mean: {', '.join(close)}?" if close else "."),
            hint="Run `conflu help` for the list of commands.",
        )
    if _wants_help(rest):
        out.write(render_command_help(command) + "\n")
        return 0
    from .parser import build_parser  # argparse is only needed to run a command, not to print help

    namespace = build_parser(command).parse_args(rest)
    enveloped = (bool(getattr(namespace, "json_envelope", False)) or _environment_wants_envelope(env)) and not command.streams
    buffer = io.StringIO() if enveloped else None  # what the command prints is wrapped when it is done, and dropped when it fails
    context = Context(
        command=command,
        app_factory=app_factory,
        out=out if buffer is None else buffer,
        err=err,
        stdin=source,
        json_flag=bool(getattr(namespace, "json", False)) or (enveloped and command.json_output),
        verbose=bool(getattr(namespace, "verbose", False)),
        environ=env,
    )
    try:
        code = command.handler(context, namespace) or 0
    except ConfluCliError as error:
        error.report_as_json = context.settings_json_default
        raise
    finally:
        context.close()
    if buffer is not None:
        message: dict[str, object] = {"ok": code == 0, "data": _envelope_data(command, buffer.getvalue())}
        if code != 0:  # a command that answers and still asks for a non-zero exit code, such as `current` without a space
            message["error"] = {"code": "EXIT", "message": f"The command finished with exit code {code}.", "hint": "", "exitCode": code, "details": {}}
        out.write(_envelope(message) + "\n")
    return code
