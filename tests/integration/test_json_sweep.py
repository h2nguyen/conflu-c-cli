"""Every command keeps its JSON promise, whichever way JSON was asked for.

The sweep of the commands (tests/support/sweeps_all.py, tests/support/sweep_local.py for the commands that never ask Confluence, and
tests/support/sweep_modes.py for the output modes that no line of an area uses) runs three times:
with `CONFLUENCE_OUTPUT=json` in the environment, with `--json` added to every line whose command declares `json_output`, and with
`CONFLUENCE_JSON_ENVELOPE=1`. A command that declares JSON prints exactly one JSON value on standard output (one compact line when it is piped, no byte
order mark, nothing before or after it), and a command that fails prints a JSON error object as the last line of standard error, with the exit code that the
process ends with. With the envelope every command prints exactly one JSON object on standard output, `{"ok": true, "data": ...}` or
`{"ok": false, "error": ...}`, and the exit code and standard error stay as they are. Every violation names the line of the sweep (`area: conflu LINE`),
so that whoever owns the command can find it.

A run is left out of a check only for a reason that the specs of the commands give (see tests/support/json_sweep.py, and ExemptionsTest below): a command that
streams (`mcp`, JSON-RPC on standard input and output) is never wrapped and declares no JSON, an option that shapes text for a person (`Arg.text_only`,
`--format tsv`) is refused together with JSON, an option whose help says that it wins over --json (`--body-only`) prints text, and a command that declares no
JSON takes no --json and only has to survive the other two switches.
"""
import json
import unittest

from conflu_c_cli.adapters.driving.cli.registry import all_commands, find_command
from conflu_c_cli.domain.errors import EXIT_CODES
from tests.support.json_sweep import ENVELOPE, ENVIRONMENT, FLAG, MODULES, SWITCHES, TEXT_ONLY, WINS_OVER_JSON, Run, runs, text_mode
from tests.support.sweeps import Line

ERROR_KEYS = {"code", "message", "hint", "exitCode", "details"}
# The error codes and the exit code that belongs to each: the table of docs/reference/exit-codes.md. EXIT is the code of an envelope for a command that
# answers and still asks for a non-zero exit code: it stands for any of them.
EXIT_OF = {name.strip(): number for number, names, _ in EXIT_CODES for name in names.split(",") if name.strip() != "OK"}
ANSWER_WITH_EXIT_CODE = "EXIT"
# The commands that answer and still end with a non-zero exit code, with their answer on standard output and no error on standard error. They are the
# documented ones (docs/reference/json-output.md, "The envelope", and the help of `page`); with the envelope they are `ok: false` with their data and the code EXIT.
ANSWERS_WITH_AN_EXIT_CODE = {
    "current": "no current space is set: {\"space\": null}, exit code 1",
    "doctor": "a check failed: the report, exit code 1",
    "page": "several pages were asked for and some are not there: the pages found and errors[], the exit code of the first that is missing",
}

STREAMS = "the command streams (Command.streams): a server talks JSON-RPC on standard input and output, so nothing of it is wrapped, and it declares no JSON"
NO_JSON = "the command declares no JSON (Command.json_output is False): it takes no --json, and with the other switches it only has to survive them"


def _no_constant(name: str):
    raise ValueError(f"{name} is no JSON")


def _parse(text: str):
    return json.loads(text, parse_constant=_no_constant)


def one_value(text: str) -> tuple[object, str]:
    """The JSON value that a stream holds, and "" when it holds exactly one, on one compact line; otherwise None and what is wrong."""
    if text.startswith("\ufeff"):
        return None, "starts with a byte order mark"
    if not text.strip():
        return None, "printed nothing"
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return None, "holds a character that cannot be written as UTF-8 (a lone surrogate)"
    lines = text.split("\n")
    if lines[-1] != "":
        return None, "does not end with a line end"
    if len(lines) != 2:
        return None, f"holds {len(lines) - 1} lines, not one compact line"
    try:
        return _parse(lines[0]), ""
    except ValueError as error:
        return None, f"is no JSON ({error}): {lines[0][:80]!r}"


def error_body_problem(body: object, code: int) -> str:
    """"" when `body` is the error object of json-output.md for a process that ended with `code`."""
    if not isinstance(body, dict) or set(body) != ERROR_KEYS:
        return f"the error has the keys {sorted(body) if isinstance(body, dict) else type(body).__name__}, not {sorted(ERROR_KEYS)}"
    if not isinstance(body["code"], str) or (body["code"] not in EXIT_OF and body["code"] != ANSWER_WITH_EXIT_CODE):
        return f"the error code is {body['code']!r}, not one of {sorted(EXIT_OF)}"
    if not isinstance(body["message"], str) or not isinstance(body["hint"], str) or not isinstance(body["details"], dict):
        return "message and hint must be text and details an object"
    if body["exitCode"] != code or isinstance(body["exitCode"], bool):
        return f"the error says exitCode {body['exitCode']!r}, the process ended with {code}"
    if body["code"] != ANSWER_WITH_EXIT_CODE and EXIT_OF[body["code"]] != code:
        return f"the error code {body['code']} belongs to exit code {EXIT_OF[body['code']]} (docs/reference/exit-codes.md), the process ended with {code}"
    if body["code"] == "ERROR" and body["message"].startswith("unexpected "):
        return f"the command crashed: {body['message'][:120]}"
    return ""


def error_on_stderr_problem(text: str, code: int) -> str:
    """"" when the last non-empty line of standard error is `{"error": {...}}` for a process that ended with `code`."""
    lines = [item for item in text.split("\n") if item.strip()]
    if not lines:
        return "failed without an error on standard error"
    try:
        value = _parse(lines[-1])
    except ValueError:
        return f"the last line of standard error is no JSON: {lines[-1][:100]!r}"
    if not isinstance(value, dict) or set(value) != {"error"}:
        return f"the last line of standard error is not {{\"error\": ...}}: {lines[-1][:100]!r}"
    return error_body_problem(value["error"], code)


def crash_problem(text: str) -> str:
    for item in text.split("\n"):
        if item.startswith("ERROR: unexpected ") or item.startswith("Traceback (most recent call last)"):
            return f"the command crashed: {item[:120]}"
    return ""


def exit_code_problem(run: Run) -> str:
    return "" if run.code == run.line.code else f"ended with {run.code}, not {run.line.code}: {run.err.strip()[-160:]!r}"


def _listed(problem: str) -> list[str]:
    return [problem] if problem else []


def _about(subject: str, problem: str) -> list[str]:
    return [f"{subject} {problem}"] if problem else []


def json_problems(run: Run) -> list[str]:
    """What breaks the promise of `--json` and of `CONFLUENCE_OUTPUT=json` in one run."""
    if not run.applied or run.command.streams:
        return []
    held_to_json = run.command.json_output and not run.text_mode
    answered = run.out.strip() != ""
    found: list[str] = []
    if held_to_json and (run.code == 0 or answered):
        found += _about("standard output", one_value(run.out)[1])
    elif run.code == 0:
        text = run.out.strip()
        if run.out.startswith("\ufeff"):
            found.append("standard output starts with a byte order mark")
        if not run.command.json_output and text[:1] in ("{", "[") and one_value(run.out)[1]:  # a command without JSON must not print what looks like JSON and is none
            found.append(f"standard output looks like JSON and is none: {text[:80]!r}")
    if run.code != 0 and not (held_to_json and answered and run.command.name in ANSWERS_WITH_AN_EXIT_CODE):
        found += _listed(error_on_stderr_problem(run.err, run.code))
    return found


def envelope_problems(run: Run) -> list[str]:
    """What breaks the promise of `--json-envelope` and of `CONFLUENCE_JSON_ENVELOPE=1` in one run."""
    if not run.applied:
        return []
    if run.command.streams:  # whatever a server prints is its own: JSON-RPC, never an envelope
        first = run.out.split("\n", 1)[0].strip()
        try:
            value = _parse(first) if first else None
        except ValueError:
            value = None
        return ["standard output is wrapped in an envelope, but the command streams"] if isinstance(value, dict) and "ok" in value else []
    value, problem = one_value(run.out)
    if problem:
        return [f"standard output {problem}"]
    if not isinstance(value, dict):
        return [f"standard output is {type(value).__name__}, not an object"]
    ok = value.get("ok")
    if not isinstance(ok, bool) or set(value) - {"ok", "data", "error"}:
        return [f"standard output is no envelope: keys {sorted(value)}, ok {ok!r}"]
    if ok != (run.code == 0):
        return [f"the envelope says ok {ok}, the process ended with {run.code}"]
    found = []
    if ok and ("data" not in value or "error" in value):
        found.append("an envelope with ok true holds data and no error")
    if not ok:
        found += _listed(error_body_problem(value.get("error"), run.code))
    if "data" in value:
        data = value["data"]
        is_text = isinstance(data, dict) and set(data) == {"text"}
        if run.command.json_output and not run.text_mode and is_text:
            found.append("the data is the text of the command, not its JSON")
        if not run.command.json_output and not is_text:
            found.append(f"a command without JSON has data that is not {{\"text\": ...}}: {str(data)[:80]!r}")
    error = value.get("error")
    if not ok and isinstance(error, dict):
        if error.get("code") == ANSWER_WITH_EXIT_CODE and run.command.name not in ANSWERS_WITH_AN_EXIT_CODE:
            found.append(f"{run.command.name} answered and asked for the exit code {run.code}, and is not one of the documented commands that do: {sorted(ANSWERS_WITH_AN_EXIT_CODE)}")
        if error.get("code") != ANSWER_WITH_EXIT_CODE and "ERROR:" not in run.err:  # standard error stays as it is
            found.append("standard error does not hold the error as text, as it does without the envelope")
    return found


def problems_of(run: Run, check) -> list[str]:
    """Every violation of one run, each naming the line of the sweep and the switch."""
    found = [problem for problem in (exit_code_problem(run), crash_problem(run.err)) if problem] + check(run)
    return [f"{run.label}  [{run.switch}]: {problem}" for problem in found]


def violations(switch: str, check) -> list[str]:
    return [item for run in runs(switch) for item in problems_of(run, check)]


def fake(argv: tuple[str, ...], switch: str, out: str = "", err: str = "", code: int = 0, applied: bool = True) -> Run:
    command = find_command(argv[0])
    assert command is not None
    return Run("area", Line(argv, code=code), command, switch, applied, text_mode(command, argv), code, out, err)


ERROR_LINE = json.dumps({"error": {"code": "NOT_FOUND", "message": "Not found: x", "hint": "", "exitCode": 4, "details": {}}}) + "\n"


class TheChecksCatchWhatTheyAreMeantToTest(unittest.TestCase):
    """The checks themselves, on made-up runs: what they let through and what they name. `config path` printing its path under --json is what
    started this test; nothing in the suite had caught it."""

    def test_a_command_that_prints_text_under_json_is_named_with_its_line(self):
        run = fake(("config", "path"), FLAG, out="/home/example/.config/conflu-c-cli/config\n")
        found = problems_of(run, json_problems)
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].startswith("area: conflu config path  [--json]: standard output is no JSON"), found)

    def test_one_compact_json_value_passes(self):
        for argv, out in ((("config", "path"), '{"file":"x"}\n'), (("how-to",), '[{"topic":"a","title":"b"}]\n'), (("version",), '"1.0.0"\n')):
            with self.subTest(argv=argv):
                self.assertEqual(json_problems(fake(argv, FLAG, out=out)), [])
                self.assertEqual(json_problems(fake(argv, ENVIRONMENT, out=out)), [])

    def test_what_is_not_exactly_one_compact_value_is_refused(self):
        for label, out, expected in (
            ("text", "saved to x\n", "is no JSON"),
            ("indented", '{\n  "file": "x"\n}\n', "holds 3 lines"),
            ("two values on two lines", '{"a":1}\n{"b":2}\n', "holds 2 lines"),
            ("two values on one line", '{"a":1} {"b":2}\n', "is no JSON"),
            ("text before", 'saved\n{"a":1}\n', "holds 2 lines"),
            ("no line end", '{"a":1}', "does not end with a line end"),
            ("a byte order mark", '\ufeff{"a":1}\n', "byte order mark"),
            ("nothing", "", "printed nothing"),
            ("a constant that is no JSON", '{"a":NaN}\n', "is no JSON"),
            ("a lone surrogate", '{"a":"\ud800"}\n', "cannot be written as UTF-8"),
        ):
            with self.subTest(label):
                found = json_problems(fake(("config", "path"), FLAG, out=out))
                self.assertTrue(found and expected in found[0], found)

    def test_a_failure_is_a_json_error_object_on_the_last_line_of_standard_error(self):
        self.assertEqual(json_problems(fake(("page", "1"), FLAG, err=ERROR_LINE, code=4)), [])
        self.assertEqual(json_problems(fake(("page", "1"), FLAG, err="[conflu] a warning\n" + ERROR_LINE, code=4)), [])
        for label, err, code, expected in (
            ("text", "ERROR: Not found: x\nHint: y\n", 4, "is no JSON"),
            ("another exit code", ERROR_LINE, 1, "exitCode 4"),
            ("nothing", "", 4, "without an error"),
            ("text after the error", ERROR_LINE + "Hint: y\n", 4, "is no JSON"),
            ("a key missing", json.dumps({"error": {"code": "USAGE", "message": "m", "hint": "", "exitCode": 2}}) + "\n", 2, "keys"),
            ("another object", '{"message":"x"}\n', 4, "not {"),
            ("a crash", json.dumps({"error": {"code": "ERROR", "message": "unexpected KeyError: 'x'", "hint": "", "exitCode": 1, "details": {}}}) + "\n", 1, "crashed"),
            ("an unknown code", json.dumps({"error": {"code": "BOOM", "message": "m", "hint": "", "exitCode": 4, "details": {}}}) + "\n", 4, "error code"),
            ("a code of another exit code", json.dumps({"error": {"code": "NOT_FOUND", "message": "m", "hint": "", "exitCode": 2, "details": {}}}) + "\n", 2, "belongs to exit code 4"),
        ):
            with self.subTest(label):
                found = json_problems(fake(("page", "1"), FLAG, err=err, code=code))
                self.assertTrue(found and expected in found[0], found)

    def test_a_command_that_answers_and_asks_for_a_non_zero_exit_code_passes_only_when_it_is_a_documented_one(self):
        self.assertEqual(json_problems(fake(("current",), FLAG, out='{"space":null}\n', code=1)), [])
        self.assertEqual(json_problems(fake(("doctor",), FLAG, out='{"ok":false,"checks":[]}\n', code=1)), [])
        self.assertEqual(json_problems(fake(("page", "1", "9"), FLAG, out='{"count":1,"pages":[],"errors":[]}\n', code=4)), [])
        self.assertTrue(json_problems(fake(("current",), FLAG, out="No current space.\n", code=1)))  # its answer must be JSON too
        found = json_problems(fake(("search", "x"), FLAG, out='{"hits":[]}\n', code=1))  # nobody documents this one
        self.assertTrue(found and "without an error" in found[0], found)

    def test_a_command_without_json_must_not_print_json_that_is_none(self):
        self.assertEqual(json_problems(fake(("help",), ENVIRONMENT, out="Usage: conflu COMMAND\n")), [])
        self.assertEqual(json_problems(fake(("help",), ENVIRONMENT, out='{"a":1}\n')), [])
        self.assertTrue(json_problems(fake(("help",), ENVIRONMENT, out='{"a": broken\n')))
        self.assertEqual(json_problems(fake(("help", "x"), ENVIRONMENT, err=ERROR_LINE, code=4)), [])
        self.assertTrue(json_problems(fake(("help", "x"), ENVIRONMENT, err="ERROR: x\n", code=2)))

    def test_what_a_spec_says_is_text_is_not_held_to_json(self):
        body_only = ("page", "1", "--body-only")
        self.assertEqual(text_mode(find_command("page"), body_only), WINS_OVER_JSON)
        self.assertEqual(json_problems(fake(body_only, FLAG, out="The body\n")), [])
        self.assertTrue(json_problems(fake(("page", "1"), FLAG, out="The body\n")))
        tsv = ("pages", "--format=tsv")
        self.assertEqual(text_mode(find_command("pages"), tsv), TEXT_ONLY)
        self.assertEqual(json_problems(fake(tsv, FLAG, out="id\ttitle\n", applied=False)), [])
        self.assertEqual(envelope_problems(fake(tsv, ENVELOPE, out="id\ttitle\n", applied=False)), [])

    def test_a_server_is_not_looked_at_for_json_and_must_not_be_wrapped(self):
        self.assertEqual(json_problems(fake(("mcp",), ENVIRONMENT, out='{"jsonrpc":"2.0","id":1,"result":{}}\n{"jsonrpc":"2.0","id":2,"result":{}}\n')), [])
        self.assertEqual(envelope_problems(fake(("mcp",), ENVELOPE, out='{"jsonrpc":"2.0","id":1,"result":{}}\n')), [])
        self.assertEqual(envelope_problems(fake(("mcp",), ENVELOPE, out="")), [])
        self.assertTrue(envelope_problems(fake(("mcp",), ENVELOPE, out='{"ok":true,"data":{"text":""}}\n')))

    def test_a_good_envelope_passes(self):
        self.assertEqual(envelope_problems(fake(("config", "path"), ENVELOPE, out='{"ok":true,"data":{"file":"x"}}\n')), [])
        self.assertEqual(envelope_problems(fake(("help",), ENVELOPE, out='{"ok":true,"data":{"text":"Usage"}}\n')), [])
        self.assertEqual(envelope_problems(fake(("page", "1", "--body-only"), ENVELOPE, out='{"ok":true,"data":{"text":"The body"}}\n')), [])
        failed = '{"ok":false,"error":{"code":"NOT_FOUND","message":"m","hint":"","exitCode":4,"details":{}}}\n'
        self.assertEqual(envelope_problems(fake(("page", "1"), ENVELOPE, out=failed, err="ERROR: m\n", code=4)), [])
        answered = '{"ok":false,"data":{"space":null},"error":{"code":"EXIT","message":"m","hint":"","exitCode":1,"details":{}}}\n'
        self.assertEqual(envelope_problems(fake(("current",), ENVELOPE, out=answered, code=1)), [])

    def test_what_is_no_envelope_is_refused(self):
        for label, argv, out, err, code, expected in (
            ("text", ("config", "path"), "x\n", "", 0, "is no JSON"),
            ("the bare json", ("config", "path"), '{"file":"x"}\n', "", 0, "no envelope"),
            ("a list", ("how-to",), "[1]\n", "", 0, "not an object"),
            ("ok against the exit code", ("config", "path"), '{"ok":true,"data":{}}\n', "", 1, "ended with 1"),
            ("no data", ("config", "path"), '{"ok":true}\n', "", 0, "holds data"),
            ("an error with a result", ("config", "path"), '{"ok":true,"data":{},"error":{}}\n', "", 0, "holds data and no error"),
            ("an error without its keys", ("page", "1"), '{"ok":false,"error":{"code":"NOT_FOUND"}}\n', "ERROR: m\n", 4, "keys"),
            ("another exit code in the error", ("page", "1"), '{"ok":false,"error":{"code":"NOT_FOUND","message":"m","hint":"","exitCode":1,"details":{}}}\n', "ERROR: m\n", 4, "exitCode 1"),
            ("the text of a command that has JSON", ("config", "path"), '{"ok":true,"data":{"text":"x"}}\n', "", 0, "not its JSON"),
            ("data of a command without JSON", ("help",), '{"ok":true,"data":{"a":1}}\n', "", 0, "without JSON"),
            ("standard error changed", ("page", "1"), '{"ok":false,"error":{"code":"NOT_FOUND","message":"m","hint":"","exitCode":4,"details":{}}}\n', "", 4, "standard error"),
            ("an answer with an exit code that nobody documents", ("search", "x"), '{"ok":false,"data":{},"error":{"code":"EXIT","message":"m","hint":"","exitCode":1,"details":{}}}\n', "", 1, "documented commands"),
        ):
            with self.subTest(label):
                found = envelope_problems(fake(argv, ENVELOPE, out=out, err=err, code=code))
                self.assertTrue(found and expected in found[0], found)

    def test_the_exit_code_and_a_crash_are_checked_for_every_run(self):
        run = fake(("config", "path"), FLAG, out='{"file":"x"}\n', err="ERROR: unexpected KeyError: 'x'\n", code=1)
        found = problems_of(run, json_problems)
        self.assertTrue(any("crashed" in item for item in found), found)
        wrong = Run("area", Line(("config", "path"), code=0), find_command("config"), FLAG, True, "", 3, '{"file":"x"}\n', "")
        self.assertTrue(any("ended with 3, not 0" in item for item in problems_of(wrong, json_problems)))


class EveryCommandIsSweptTest(unittest.TestCase):
    def test_every_command_has_a_line_in_the_sweep(self):
        swept = {find_command(item.argv[0]).name for module in MODULES for item in module.LINES}
        missing = sorted(command.name for command in all_commands() if command.name not in swept)
        self.assertEqual(missing, [], "a command has no line in the sweep: add one to tests/support/sweep_<area>.py (sweep_local.py when it never asks Confluence)")

    def test_the_three_runs_are_whole_sweeps_with_failing_lines_in_them(self):
        counts = {switch: len(runs(switch)) for switch in SWITCHES}
        self.assertEqual(len(set(counts.values())), 1, counts)
        self.assertGreater(min(counts.values()), 500)
        for switch in SWITCHES:
            with self.subTest(switch):
                self.assertGreater(len([run for run in runs(switch) if run.code != 0]), 50)
                self.assertGreater(len([run for run in runs(switch) if run.code == 0 and run.applied and run.command.json_output]), 300)

    def test_every_exit_code_of_the_table_ends_a_line_in_every_pass_so_that_every_json_error_is_run(self):
        wanted = {number for number, _, _ in EXIT_CODES if number}
        for switch in SWITCHES:
            with self.subTest(switch):
                self.assertEqual(sorted(wanted - {run.code for run in runs(switch)}), [], "add a line that ends with the exit code to sweep_modes.py")


class ExemptionsTest(unittest.TestCase):
    """A run is left out of a check only for a reason that the specs give, and the specs agree with each other."""

    def test_a_command_that_streams_declares_no_json(self):
        self.assertEqual([command.name for command in all_commands() if command.streams and command.json_output], [])

    def test_a_text_only_option_belongs_to_a_command_that_has_json(self):
        self.assertEqual([command.name for command in all_commands() if any(arg.text_only for arg in command.args) and not command.json_output], [])

    def test_what_wins_over_json_is_an_option_of_a_command_that_has_json(self):
        for command in all_commands():
            for arg in command.args:
                if "wins over --json" in arg.help.lower():
                    with self.subTest(command=command.name, option=arg.names[0]):
                        self.assertTrue(command.json_output)
                        self.assertEqual(arg.kind, "flag")
                        self.assertFalse(arg.text_only)

    def test_the_commands_that_answer_with_an_exit_code_are_the_documented_ones_and_the_sweep_has_each_do_it(self):
        answering = {run.command.name for run in runs(FLAG) if run.code != 0 and run.out.strip() and error_on_stderr_problem(run.err, run.code)}
        self.assertEqual(sorted(answering), sorted(ANSWERS_WITH_AN_EXIT_CODE))

    def test_the_runs_that_are_left_out_have_one_of_the_reasons_and_the_others_are_most_of_them(self):
        for switch in SWITCHES:
            with self.subTest(switch):
                left_out = {}
                for run in runs(switch):
                    if run.command.streams:
                        reason = STREAMS
                    elif run.text_mode:
                        reason = run.text_mode
                    elif switch == FLAG and not run.command.json_output:
                        reason = NO_JSON
                    else:
                        continue
                    left_out.setdefault(reason, []).append(run.label)
                self.assertLessEqual(set(left_out), {STREAMS, TEXT_ONLY, WINS_OVER_JSON, NO_JSON})
                self.assertLess(sum(len(labels) for labels in left_out.values()), len(runs(switch)) // 4)


class JsonEnvironmentTest(unittest.TestCase):
    """CONFLUENCE_OUTPUT=json: the commands that declare JSON print it, and every failure is a JSON error on standard error."""

    def test_every_line_keeps_the_promise(self):
        self.assertEqual(violations(ENVIRONMENT, json_problems), [])


class JsonFlagTest(unittest.TestCase):
    """--json on every line whose command declares JSON."""

    def test_every_line_keeps_the_promise(self):
        self.assertEqual(violations(FLAG, json_problems), [])


class JsonEnvelopeTest(unittest.TestCase):
    """CONFLUENCE_JSON_ENVELOPE=1: one object on standard output whatever happens, the exit code and standard error as they are."""

    def test_every_line_keeps_the_promise(self):
        self.assertEqual(violations(ENVELOPE, envelope_problems), [])


if __name__ == "__main__":
    unittest.main()
