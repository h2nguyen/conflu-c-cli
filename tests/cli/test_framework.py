"""The command line framework: dispatch, help, the command catalog, error handling."""
import io
import json
import shlex
import unittest
from pathlib import Path

from conflu_c_cli.adapters.driving.cli.main import run
from conflu_c_cli.adapters.driving.cli.parser import build_parser
from conflu_c_cli.adapters.driving.cli.registry import all_commands, find_command
from conflu_c_cli.adapters.driving.cli.spec import GROUP_ORDER
from conflu_c_cli.domain.errors import EXIT_CODES, ConfigError, UnavailableError
from conflu_c_cli.version import __version__
from tests.support.cli import run_cli
from tests.support.fakes import FakeGateway

NAMES = [command.name for command in all_commands()]
ROOT = Path(__file__).resolve().parents[2]


class DispatchTest(unittest.TestCase):
    def test_no_arguments_show_the_overview(self):
        result = run_cli()
        self.assertEqual(result.code, 0)
        self.assertIn(f"conflu-c-cli {__version__}", result.out)
        for name in NAMES:
            self.assertIn(name, result.out)
        self.assertEqual(result.err, "")

    def test_help_flags_and_help_command_agree(self):
        overview = run_cli().out
        for argv in (("-h",), ("--help",), ("help",)):
            self.assertEqual(run_cli(*argv).out, overview)

    def test_version_in_every_spelling(self):
        for argv in (("version",), ("-V",), ("--version",)):
            self.assertEqual(run_cli(*argv).out, f"conflu-c-cli {__version__}\n")
        data = run_cli("version", "--json").json()
        self.assertEqual((data["name"], data["version"]), ("conflu-c-cli", __version__))

    def test_the_version_agrees_with_the_version_file(self):
        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), __version__)

    def test_unknown_command_suggests_and_exits_2(self):
        result = run_cli("pagez")
        self.assertEqual(result.code, 2)
        self.assertIn("Did you mean: page", result.err)
        self.assertIn("pages", result.err)
        self.assertEqual(result.out, "")

    def test_errors_are_json_on_stderr_when_asked(self):
        for argv, environ in ((("page", "--json"), {}), (("page",), {"CONFLUENCE_OUTPUT": "json"})):
            result = run_cli(*argv, environ=environ)
            error = result.error()
            self.assertEqual((result.code, error["code"], error["exitCode"]), (2, "USAGE", 2))
            self.assertIn("conflu help page", error["hint"])
            self.assertEqual(result.out, "")

    def test_help_for_every_command_works_offline_and_changes_nothing(self):
        for name in NAMES:
            for argv in (("help", name), (name, "--help"), (name, "-h")):
                gateway = FakeGateway()
                result = run_cli(*argv, gateway=gateway)
                with self.subTest(argv=argv):
                    self.assertEqual(result.code, 0, result.err)
                    self.assertIn(f"Usage: conflu {name}", result.out)
                    self.assertEqual(gateway.calls, [])

    def test_help_wins_over_missing_arguments(self):
        self.assertEqual(run_cli("page", "--help").code, 0)
        self.assertEqual(run_cli("create", "--help").code, 0)

    def test_help_of_an_unknown_command(self):
        result = run_cli("help", "updat")
        self.assertEqual(result.code, 2)
        self.assertIn("update", result.err)

    def test_aliases(self):
        for alias in ("changes", "history"):
            self.assertIn(__version__, run_cli(alias).out)
        for alias in ("howto", "readme", "docs"):
            self.assertIn("daily-workflow", run_cli(alias).out)

    def test_unknown_options_and_bad_values_are_usage_errors(self):
        for argv in (
            ("page", "2002", "--nope"),
            ("pages", "--limit", "many"),
            ("pages", "--status", "deleted"),
            ("page", "2002", "--format", "html"),
            ("page", "2002", "2003"),
            ("move", "2005", "--position", "sideways", "--to", "2003"),
        ):
            with self.subTest(argv=argv):
                self.assertEqual(run_cli(*argv).code, 2)

    def test_abbreviated_options_are_not_guessed(self):
        self.assertEqual(run_cli("page", "2002", "--comm").code, 2)

    def test_the_overview_groups_the_commands(self):
        overview = run_cli().out
        for group in GROUP_ORDER:
            self.assertIn(group, overview)


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.catalog = run_cli("commands", "--json").json()

    def test_everything_a_program_needs(self):
        self.assertEqual(self.catalog["version"], __version__)
        self.assertEqual([item["name"] for item in self.catalog["commands"]], NAMES)
        self.assertEqual([item["code"] for item in self.catalog["exitCodes"]], [code for code, _, _ in EXIT_CODES])
        names = [item["name"] for item in self.catalog["settings"]]
        self.assertIn("CONFLUENCE_HIDE_USERS", names)
        self.assertNotIn("secret-token", json.dumps(self.catalog))

    def test_commands_describe_their_arguments_and_output(self):
        page = next(item for item in self.catalog["commands"] if item["name"] == "page")
        self.assertTrue(page["supportsJson"])
        self.assertFalse(page["changesData"])
        self.assertEqual([arg["names"][0] for arg in page["arguments"]], ["ref", "--format", "--outline", "--section", "--max-chars", "--space", "--no-body", "--body-only", "--comments", "--ancestors", "--with-users", "--raw"])
        self.assertTrue(page["arguments"][0]["required"])
        self.assertEqual(page["arguments"][1]["choices"], ["markdown", "text", "storage"])
        self.assertIn("body{format,value,dropped[],section,truncated,totalChars}", page["jsonOutput"])
        update = next(item for item in self.catalog["commands"] if item["name"] == "update")
        self.assertTrue(update["changesData"])

    def test_settings_say_what_is_secret_and_personal(self):
        settings = {item["name"]: item for item in self.catalog["settings"]}
        self.assertTrue(settings["CONFLUENCE_API_TOKEN"]["secret"])
        self.assertTrue(settings["CONFLUENCE_EMAIL"]["personal"])
        self.assertFalse(settings["CONFLUENCE_SPACE"]["secret"])

    def test_the_text_catalog(self):
        result = run_cli("commands")
        self.assertTrue(all(name in result.out for name in NAMES))
        self.assertTrue(result.out.startswith("COMMAND"))


class QualityBarTest(unittest.TestCase):
    """Rules every command must follow, so that a new one cannot ship half described."""

    def test_names_and_aliases_are_unique(self):
        seen = [command.name for command in all_commands()] + [alias for command in all_commands() for alias in command.aliases]
        self.assertEqual(len(seen), len(set(seen)))

    def test_every_command_is_in_a_known_group_and_is_described(self):
        for command in all_commands():
            with self.subTest(command=command.name):
                self.assertIn(command.group, GROUP_ORDER)
                self.assertTrue(command.summary and not command.summary.endswith("."))
                self.assertTrue(command.examples, "a command needs at least one example")
                for arg in command.args:
                    self.assertTrue(arg.help, f"{arg.names} has no help text")

    def test_json_support_is_documented_and_only_then(self):
        for command in all_commands():
            with self.subTest(command=command.name):
                self.assertEqual(bool(command.output), command.json_output)

    def test_commands_that_change_confluence_can_be_previewed(self):
        local = {"setup-token", "remove-token", "use", "clear-space", "config"}
        for command in all_commands():
            if command.writes and command.name not in local:
                with self.subTest(command=command.name):
                    self.assertTrue(any("--dry-run" in arg.names for arg in command.args))

    def test_no_argument_clashes_with_the_shared_options(self):
        for command in all_commands():
            destinations = [arg.dest for arg in command.args]
            with self.subTest(command=command.name):
                self.assertEqual(len(destinations), len(set(destinations)))
                self.assertFalse({"json", "verbose"} & set(destinations))

    def test_no_argument_is_named_like_a_python_keyword(self):
        import keyword

        for command in all_commands():
            for arg in command.args:
                with self.subTest(command=command.name, arg=arg.names):
                    self.assertFalse(keyword.iskeyword(arg.dest))

    def test_every_documented_example_is_valid_usage(self):
        for command in all_commands():
            for example in command.examples:
                tokens = shlex.split(example.command)
                if "|" in tokens:
                    tokens = tokens[tokens.index("|") + 1 :]
                if ">" in tokens:
                    tokens = tokens[: tokens.index(">")]  # a redirect into a file is the shell's, not an argument
                with self.subTest(example=example.command):
                    self.assertEqual(tokens[:2], ["conflu", command.name])
                    build_parser(command).parse_args(tokens[2:])  # raises UsageError when the example is wrong

    def test_find_command_by_name_and_alias(self):
        self.assertEqual(find_command("HISTORY").name, "changelog")
        self.assertIsNone(find_command("nope"))

    def test_the_command_that_never_change_anything_say_so(self):
        reading = {"page", "pages", "tree", "versions", "search", "comments", "labels", "attachments", "spaces", "space", "current", "ping", "doctor"}
        for name in reading:
            self.assertFalse(find_command(name).writes, name)
        for name in ("create", "update", "move", "comment", "label", "attach", "import-md", "import-md-dir", "api"):
            self.assertTrue(find_command(name).writes, name)


class ErrorHandlingTest(unittest.TestCase):
    def test_a_known_error_gets_its_exit_code(self):
        result = run_cli("page", "999")
        self.assertEqual(result.code, 4)
        self.assertTrue(result.err.startswith("ERROR: Not found"))

    def test_json_error_shape(self):
        error = run_cli("page", "999", "--json").error()
        self.assertEqual(set(error), {"code", "message", "hint", "exitCode", "details"})
        self.assertEqual((error["code"], error["exitCode"]), ("NOT_FOUND", 4))

    def test_hints_are_printed(self):
        gateway = FakeGateway()
        gateway.errors["get_page"] = UnavailableError("Cannot reach Confluence.", hint="Check the VPN.")
        result = run_cli("page", "2002", gateway=gateway)
        self.assertEqual(result.code, 7)
        self.assertEqual(result.err, "ERROR: Cannot reach Confluence.\nHint: Check the VPN.\n")

    def test_a_reader_that_closed_early(self):
        gateway = FakeGateway()
        gateway.errors["get_page"] = BrokenPipeError()
        self.assertEqual(run_cli("page", "2002", gateway=gateway).code, 141)

    def test_interrupt(self):
        gateway = FakeGateway()
        gateway.errors["get_page"] = KeyboardInterrupt()
        result = run_cli("page", "2002", gateway=gateway)
        self.assertEqual((result.code, result.err), (130, "Interrupted.\n"))

    def test_a_bug_is_reported_plainly(self):
        gateway = FakeGateway()
        gateway.errors["get_page"] = RuntimeError("boom")
        result = run_cli("page", "2002", gateway=gateway)
        self.assertEqual(result.code, 1)
        self.assertIn("unexpected RuntimeError: boom", result.err)
        self.assertNotIn("Traceback", result.err)
        self.assertIn("Traceback", run_cli("page", "2002", "--verbose", gateway=gateway).err)

    def test_a_broken_configuration_is_a_clean_error(self):
        def factory(diagnostics):
            raise ConfigError("CONFLUENCE_RETRY must be a whole number, not 'x'.", hint="Fix it.")

        err = io.StringIO()
        code = run(["page", "2002"], app_factory=factory, environ={}, stdout=io.StringIO(), stderr=err, stdin=io.StringIO())
        self.assertEqual(code, 1)
        self.assertIn("CONFLUENCE_RETRY", err.getvalue())

    def test_doctor_reports_a_broken_configuration_instead_of_crashing(self):
        def factory(diagnostics):
            raise ConfigError("CONFLUENCE_RETRY must be a whole number, not 'x'.", hint="Fix it.")

        out = io.StringIO()
        code = run(["doctor"], app_factory=factory, environ={}, stdout=out, stderr=io.StringIO(), stdin=io.StringIO())
        self.assertEqual(code, 1)
        self.assertIn("[FAIL] configuration", out.getvalue())
        as_json = io.StringIO()
        code = run(["doctor", "--json"], app_factory=factory, environ={}, stdout=as_json, stderr=io.StringIO(), stdin=io.StringIO())
        self.assertEqual(code, 1)
        report = json.loads(as_json.getvalue())
        self.assertEqual((report["ok"], report["checks"][0]["name"], report["checks"][0]["status"]), (False, "configuration", "fail"))
        self.assertEqual(report["checks"][0]["hint"], "Fix it.")


if __name__ == "__main__":
    unittest.main()
