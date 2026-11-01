"""Every command names the REST API it uses (`conflu help COMMAND`, the key `api` of `conflu commands --json`, the command reference), and what it names is
what the commands really send: the table of `adapters/driving/cli/apis.py` is held to the calls that the sweep of every command recorded."""
import json
import unittest

from conflu_c_cli.adapters.driving.cli.apis import API_OF, BOTH, NAMED, NONE, TOOLS, V1, V2, api_line, api_of
from conflu_c_cli.adapters.driving.cli.help import catalog, commands_markdown
from conflu_c_cli.adapters.driving.cli.registry import all_commands
from conflu_c_cli.version import __version__
from tests.support.cli import run_cli
from tests.support.conformance import version_of
from tests.support.sweep_runner import run_sweeps
from tests.support.sweeps_all import SWEEPS

OPEN = {"api": NAMED, "mcp": TOOLS}  # the commands whose API is not theirs to say: the path names it, or the tools do


class TheTableKnowsEveryCommandTest(unittest.TestCase):
    def test_it_has_every_command_and_nothing_else(self):
        self.assertEqual(sorted(API_OF), sorted(command.name for command in all_commands()), "a new command needs its entry in adapters/driving/cli/apis.py")

    def test_every_entry_is_one_of_the_documented_values_and_has_a_sentence(self):
        for name, api in API_OF.items():
            with self.subTest(command=name):
                self.assertIn(api, (V2, V1, BOTH, NONE, NAMED, TOOLS))
                self.assertTrue(api_line(name).endswith("."), name)
        self.assertEqual((api_of("page"), api_of("nothing")), (V2, ""))
        self.assertEqual(api_line("nothing"), "")


class TheTableIsWhatTheCommandsSendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_sweeps(SWEEPS)

    def test_a_command_that_sends_calls_names_the_api_of_the_calls_it_sent(self):
        for command, calls in sorted(self.result.calls.items()):
            if command in OPEN or not calls:
                continue
            versions = {version_of(call.partition(" ")[2]) for call in calls}
            expected = BOTH if versions == {"v1", "v2"} else (V1 if versions == {"v1"} else V2)
            with self.subTest(command=command):
                self.assertEqual(API_OF[command], expected, f"{command} sent {sorted(calls)}")

    def test_a_command_that_sent_nothing_says_none_or_says_what_it_is(self):
        sent = {command for command, calls in self.result.calls.items() if calls}
        for name, api in sorted(API_OF.items()):
            if name in sent or name in OPEN:
                continue
            with self.subTest(command=name):
                self.assertEqual(api, NONE, f"{name} sent no call in the sweep: say 'none', or add a sweep line that shows its calls")

    def test_the_commands_that_leave_it_open_say_so(self):
        for name, api in OPEN.items():
            self.assertEqual(API_OF[name], api)


class TheHelpTheCatalogAndTheReferenceSayItTest(unittest.TestCase):
    def test_the_help_of_a_command_has_the_line(self):
        for name, expected in (
            ("page", "REST API: v2 (/wiki/api/v2)."),
            ("template", "REST API: v1 (/wiki/rest/api), because v2 has no call for it"),
            ("search", "REST API: v2 (/wiki/api/v2), and v1 (/wiki/rest/api) for what v2 cannot do"),
            ("convert", "REST API: none, it works on this computer."),
            ("api", "REST API: the one that PATH names"),
            ("setup", "REST API: none of the two"),
        ):
            with self.subTest(command=name):
                text = run_cli("help", name).out
                self.assertIn(expected, text)
                self.assertLess(text.index("Changes data:"), text.index("REST API:"))

    def test_the_catalog_has_the_key_for_every_command(self):
        commands = catalog(all_commands(), __version__)["commands"]
        self.assertEqual({item["name"]: item["api"] for item in commands}, dict(API_OF))
        self.assertEqual(json.loads(run_cli("commands", "--json").out)["commands"][0]["api"], API_OF[commands[0]["name"]])

    def test_the_reference_has_the_line_for_every_command(self):
        text = commands_markdown(all_commands(), __version__)
        self.assertEqual(text.count("\nREST API: "), len(API_OF))
        self.assertIn("Changes data: no.\n\nREST API: v2 (/wiki/api/v2).", text)


if __name__ == "__main__":
    unittest.main()
