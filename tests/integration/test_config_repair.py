"""A configuration that cannot be read must not lock its owner out, and a value that would make it unreadable is never written.

The file of the settings is the one place where a line break in a value (typed, pasted, or sent by a server as the key of a space) made
every command fail, `config set` and `config unset` included, which are what the hint recommends. Here: what the store refuses, how it reads a
line, which line of which file it names, and that the commands that mend the file run while every other command fails as before, before it
sends anything.
"""
import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from conflu_c_cli.adapters.driven.file_config import FileConfigStore
from conflu_c_cli.application.settings import Settings, UnreadableSettings
from conflu_c_cli.domain.errors import ConfigError, UnavailableError
from tests.integration.test_end_to_end import EndToEnd
from tests.support.cli import run_cli
from tests.support.fakes import FakeGateway, MemoryConfigStore

# What is not one line: the control characters, and the two separators that Unicode adds. Each one is checked by itself.
NOT_ONE_LINE = {
    "a line feed": "\n",
    "a carriage return": "\r",
    "NUL": "\x00",
    "escape": "\x1b",
    "delete": "\x7f",
    "next line (U+0085)": "\x85",
    "the line separator (U+2028)": "\u2028",
    "the paragraph separator (U+2029)": "\u2029",
    "a vertical tab": "\x0b",
    "a form feed": "\x0c",
    "a file separator": "\x1c",
    "a tab": "\t",
}
PEM = "-----BEGIN CERTIFICATE-----\nMIIBszCCAVmgAwIBAgIUexample\n-----END CERTIFICATE-----"


class StoreTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.path = Path(holder.name) / "conf" / "config"
        self.store = FileConfigStore(self.path)

    def write(self, text: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(text.encode("utf-8"))  # bytes: the line ends are exactly these

    # -- what is written -----------------------------------------------------------------------

    def test_a_value_that_is_not_one_line_is_refused_whole_and_the_file_is_left_alone(self):
        self.write("CONFLUENCE_RETRY=3\n")
        before = self.path.read_bytes()
        for label, char in NOT_ONE_LINE.items():
            for value in (f"KEY-{char}-VALUE", f"{char}KEY", f"KEY{char}"):
                with self.subTest(label=label, value=repr(value)), self.assertRaises(ConfigError) as caught:
                    self.store.set("CONFLUENCE_SPACE", value)
                self.assertEqual(caught.exception.exit_code, 1)
                self.assertIn("CONFLUENCE_SPACE was not saved", caught.exception.message)  # it names the setting
                self.assertIn("one line", caught.exception.hint)  # and says what to do
                self.assertNotIn("KEY", caught.exception.message + caught.exception.hint)  # and does not repeat the value
        self.assertEqual(self.path.read_bytes(), before)

    def test_nothing_is_created_when_the_first_value_is_refused(self):
        with self.assertRaises(ConfigError):
            self.store.set("CONFLUENCE_SPACE", "ENG\nX")
        self.assertFalse(self.path.exists())
        self.assertFalse(self.path.parent.exists())

    def test_the_text_of_a_certificate_is_told_to_be_a_path(self):
        with self.assertRaises(ConfigError) as caught:
            self.store.set("CONFLUENCE_CA_BUNDLE", PEM)
        self.assertIn("CONFLUENCE_CA_BUNDLE was not saved", caught.exception.message)
        self.assertIn("path of a PEM file", caught.exception.hint)
        self.assertNotIn("MIIB", caught.exception.message + caught.exception.hint)

    def test_the_token_is_refused_too_and_never_repeated(self):
        with self.assertRaises(ConfigError) as caught:
            self.store.set("CONFLUENCE_API_TOKEN", "s3cr3t\x00token")
        self.assertIn("CONFLUENCE_API_TOKEN was not saved", caught.exception.message)
        self.assertNotIn("s3cr3t", caught.exception.message + caught.exception.hint)

    def test_what_is_one_line_is_saved_as_it_is(self):
        for value in ("ENG", "~712020abcdef", "C:/certs/my ca.pem", "Übung \u65e5\u672c\u8a9e \U0001f600", "it's \"quoted\" $HOME `x`", "", " padded ", "a\u00a0b", "a\u200bb"):
            with self.subTest(value=value):
                self.store.set("CONFLUENCE_SPACE", value)
                self.assertEqual(self.store.load()["CONFLUENCE_SPACE"], value)

    # -- how a line is read --------------------------------------------------------------------

    def test_a_line_ends_at_a_line_feed_a_carriage_return_or_both(self):
        self.write("CONFLUENCE_RETRY=1\rCONFLUENCE_SPACE=ENG\r\nCONFLUENCE_EMAIL=a@example.com\nCONFLUENCE_OUTPUT=json")
        self.assertEqual(self.store.load(), {"CONFLUENCE_RETRY": "1", "CONFLUENCE_SPACE": "ENG", "CONFLUENCE_EMAIL": "a@example.com", "CONFLUENCE_OUTPUT": "json"})

    def test_an_empty_file_a_lone_line_end_and_a_blank_line_are_what_they_were(self):
        for text, count in (("", 0), ("\n", 1), ("\r\n", 1), ("\n\n", 2), ("CONFLUENCE_SPACE=ENG\n", 1), ("CONFLUENCE_SPACE=ENG", 1)):
            with self.subTest(text=repr(text)):
                self.write(text)
                self.assertEqual(len(self.store._lines()), count)
        self.assertEqual(FileConfigStore(self.path.parent / "missing")._lines(), [])

    def test_a_separator_that_no_editor_means_as_a_line_end_does_not_start_a_line(self):
        """`str.splitlines()` cuts at these, and what follows a cut inside a comment would be read as a setting of its own."""
        for char in ("\u2028", "\u2029", "\x85", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e"):
            with self.subTest(char=repr(char)):
                self.write(f"# note{char}CONFLUENCE_SPACE=EVIL\nCONFLUENCE_RETRY=3\n")
                self.assertEqual(self.store.load(), {"CONFLUENCE_RETRY": "3"})
                self.store.set("CONFLUENCE_EMAIL", "a@example.com")
                self.assertEqual(self.path.read_bytes().decode("utf-8").split("\n")[0], f"# note{char}CONFLUENCE_SPACE=EVIL")  # the comment is rewritten as it was

    def test_a_separator_inside_a_quoted_value_stays_in_the_value(self):
        self.write("CONFLUENCE_SPACE='A\u2028B'\n")
        self.assertEqual(self.store.load(), {"CONFLUENCE_SPACE": "A\u2028B"})

    # -- which line is broken ------------------------------------------------------------------

    def test_a_broken_value_names_its_line_and_its_file(self):
        self.write("# my settings\nCONFLUENCE_RETRY=1\nCONFLUENCE_SPACE='ENG\nCONFLUENCE_EMAIL=a@example.com\n")
        with self.assertRaises(ConfigError) as caught:
            self.store.load()
        error = caught.exception
        self.assertEqual(error.exit_code, 1)
        self.assertIn("CONFLUENCE_SPACE has unbalanced quotes", error.message)
        self.assertIn("line 3", error.message)
        self.assertIn(str(self.path), error.message)
        self.assertIn("`conflu config set CONFLUENCE_SPACE VALUE`", error.hint)
        self.assertIn("`conflu config unset CONFLUENCE_SPACE`", error.hint)

    def test_every_kind_of_broken_value_says_the_line(self):
        for text, said in (
            ("CONFLUENCE_SPACE='ENG", "unbalanced quotes"),
            ("CONFLUENCE_SPACE=two words", "several words"),
            ("CONFLUENCE_SPACE=$(echo hi)", "shell syntax"),
            ("CONFLUENCE_SPACE=~/x", "shell syntax"),
        ):
            with self.subTest(text=text):
                self.write("CONFLUENCE_RETRY=1\n\n" + text + "\n")
                with self.assertRaises(ConfigError) as caught:
                    self.store.load()
                self.assertIn(said, caught.exception.message)
                self.assertIn("line 3", caught.exception.message)
                self.assertIn("conflu config unset CONFLUENCE_SPACE", caught.exception.hint)

    def test_the_line_number_counts_the_line_ends_of_every_kind(self):
        self.write("# a\r# b\r\n# c\nCONFLUENCE_SPACE='ENG\n")
        with self.assertRaises(ConfigError) as caught:
            self.store.load()
        self.assertIn("line 4", caught.exception.message)

    def test_a_broken_token_is_mended_with_the_commands_for_the_token(self):
        self.write("CONFLUENCE_API_TOKEN='open\n")
        with self.assertRaises(ConfigError) as caught:
            self.store.load()
        self.assertIn("`conflu setup-token`", caught.exception.hint)
        self.assertIn("`conflu remove-token`", caught.exception.hint)
        self.assertNotIn("config set CONFLUENCE_API_TOKEN", caught.exception.hint)  # that is refused: the token is not set on the command line

    def test_a_line_that_is_no_setting_of_this_program_is_to_be_edited_by_hand(self):
        self.write("SOMETHING_ELSE='open\n")
        with self.assertRaises(ConfigError) as caught:
            self.store.load()
        self.assertIn("SOMETHING_ELSE", caught.exception.message)
        self.assertIn("no setting of this program", caught.exception.hint)
        self.assertNotIn("conflu config", caught.exception.hint)

    # -- what mends it -------------------------------------------------------------------------

    def test_set_and_unset_read_no_value_so_they_work_on_a_file_that_load_refuses(self):
        broken = "# mine\nCONFLUENCE_SPACE='ENG\nCONFLUENCE_RETRY=3\nSOMETHING_ELSE='open\n"
        self.write(broken)
        self.store.set("CONFLUENCE_SPACE", "DOCS")
        text = self.path.read_bytes().decode("utf-8")
        self.assertEqual(text.split("\n"), ["# mine", "CONFLUENCE_RETRY=3", "SOMETHING_ELSE='open", "CONFLUENCE_SPACE=DOCS", ""])  # the other broken line is kept as it was
        self.write(broken)
        self.assertTrue(self.store.unset("CONFLUENCE_SPACE"))
        self.assertEqual(self.path.read_bytes().decode("utf-8").split("\n"), ["# mine", "CONFLUENCE_RETRY=3", "SOMETHING_ELSE='open", ""])


class ConfigRepairTest(EndToEnd):
    """The real program against the mock: the configuration file that cannot be read, and the commands that mend it."""

    def write(self, text: str) -> None:
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_bytes(text.encode("utf-8"))

    def file_env(self) -> dict:
        """The settings in the file: no variable of the test overrides it. The cache folder is the test's own."""
        return {
            "CONFLUENCE_CONFIG_FILE": str(self.config),
            "HOME": str(self.root),
            "XDG_CACHE_HOME": str(self.root / "cache"),
            "CONFLUENCE_BASE_URL": self.mock.base_url,
            "CONFLUENCE_EMAIL": self.mock.email,
            "CONFLUENCE_API_TOKEN": self.mock.token,
        }

    def run_cli(self, *argv, stdin: str = "", **more):
        return self.cli(*argv, stdin=stdin, env=self.file_env(), replace_env=True, **more)

    # -- a value that would break the file ---------------------------------------------------

    def test_a_line_break_in_a_setting_is_refused_and_every_command_goes_on_working(self):
        for label, char in NOT_ONE_LINE.items():
            with self.subTest(label=label):
                result = self.run_cli("config", "set", "CONFLUENCE_SPACE", f"ENG{char}X")
                self.assertEqual(result.code, 1)
                self.assertIn("CONFLUENCE_SPACE was not saved", result.err)
                self.assertEqual(self.run_cli("config", "show").code, 0)
        self.assertFalse(self.config.exists())

    def test_the_error_is_json_when_it_is_asked_for(self):
        result = self.run_cli("config", "set", "CONFLUENCE_SPACE", "ENG\nX", "--json")
        error = json.loads(result.err)["error"]
        self.assertEqual((result.code, error["code"], error["exitCode"]), (1, "CONFIG", 1))
        self.assertIn("CONFLUENCE_SPACE", error["message"])

    def test_pasted_certificate_text_is_refused_with_the_advice_to_give_a_path(self):
        result = self.run_cli("config", "set", "CONFLUENCE_CA_BUNDLE", PEM)
        self.assertEqual(result.code, 1)
        self.assertIn("path of a PEM file", result.err)
        self.assertFalse(self.config.exists())
        self.assertEqual(self.run_cli("config", "show").code, 0)

    def test_a_token_with_a_control_character_is_refused_and_never_printed(self):
        result = self.run_cli("setup-token", "--stdin", stdin="abc\x00def")
        self.assertEqual(result.code, 1)
        self.assertIn("CONFLUENCE_API_TOKEN was not saved", result.err)
        self.assertNotIn("abc", result.out + result.err)
        self.assertFalse(self.config.exists())

    # -- a space whose key is no key ---------------------------------------------------------

    def hostile_space(self, key: str) -> None:
        answer = {"results": [{"id": "1001", "key": key, "name": "Engineering", "type": "global", "status": "current"}]}
        self.mock.fail_next("/api/v2/spaces", 200, body=answer)  # the answer to the one request of `use`

    def test_a_space_key_from_a_server_that_holds_a_line_break_is_not_saved(self):
        for key in ("ENG\nX", "ENG\r\nCONFLUENCE_HIDE_USERS=false", "ENG\u2028X", "ENG X", "", "x" * 300, "ENG;rm", "ENG\x00"):
            with self.subTest(key=repr(key)[:30]):
                self.hostile_space(key)
                result = self.run_cli("use", "ENG")
                self.assertEqual(result.code, 7, result.err)  # an answer that cannot be used, not a mistake of the person
                self.assertIn("cannot be saved as the current space", result.err)
                self.assertIn("Nothing was saved", result.err)
                self.assertFalse(self.config.exists())
        self.assertEqual(self.run_cli("config", "show").code, 0)

    def test_a_good_key_is_saved_as_before(self):
        result = self.run_cli("use", "eng")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.config.read_text(encoding="utf-8"), "CONFLUENCE_SPACE=ENG\n")

    # -- a file that cannot be read ----------------------------------------------------------

    def test_the_commands_that_need_a_setting_fail_as_they_did_and_send_nothing(self):
        self.write("CONFLUENCE_HIDE_USERS='true\n")
        for argv in (("pages",), ("page", "2002"), ("ping",), ("current",), ("search", "release"), ("config", "show"), ("setup", "--discover", "--yes"), ("spaces",), ("use", "ENG")):
            with self.subTest(argv=argv):
                result = self.run_cli(*argv)
                self.assertEqual(result.code, 1, result.out)
                self.assertIn("CONFLUENCE_HIDE_USERS has unbalanced quotes in the config file (line 1 of", result.err)
                self.assertIn("conflu config set CONFLUENCE_HIDE_USERS VALUE", result.err)
        self.assertEqual(self.mock.requests, [])  # a policy that cannot be read is not replaced by a default: nothing was asked of Confluence

    def test_the_doctor_reports_the_line(self):
        self.write("CONFLUENCE_RETRY=1\nCONFLUENCE_SPACE='ENG\n")
        text = self.run_cli("doctor")
        self.assertEqual(text.code, 1)
        self.assertIn("[FAIL] configuration", text.out)
        self.assertIn("line 2", text.out)
        report = self.run_cli("doctor", "--json")
        self.assertEqual((report.code, report.json()["ok"], report.json()["checks"][0]["name"]), (1, False, "configuration"))
        self.assertEqual(self.mock.requests, [])

    def test_config_set_mends_the_line_and_then_everything_works(self):
        self.write("# notes\nCONFLUENCE_RETRY=1\nCONFLUENCE_SPACE='ENG\n")
        self.assertEqual(self.run_cli("pages").code, 1)
        self.assertEqual(self.run_cli("config", "path").out, f"{self.config}\n")  # also this works
        mended = self.run_cli("config", "set", "CONFLUENCE_SPACE", "ENG")
        self.assertEqual(mended.code, 0, mended.err)
        self.assertEqual(self.config.read_text(encoding="utf-8").split("\n"), ["# notes", "CONFLUENCE_RETRY=1", "CONFLUENCE_SPACE=ENG", ""])
        self.assertEqual(self.run_cli("config", "show").code, 0)
        self.assertEqual(self.run_cli("pages", "--limit", "1", "--json").json()["space"], "ENG")

    def test_config_unset_removes_the_line_and_then_everything_works(self):
        self.write("CONFLUENCE_SPACE=ENG\nCONFLUENCE_OUTPUT=xml\n")  # a value that is refused, not a line that does not parse
        self.assertEqual(self.run_cli("config", "show").code, 1)
        removed = self.run_cli("config", "unset", "CONFLUENCE_OUTPUT")
        self.assertEqual((removed.code, removed.out), (0, f"CONFLUENCE_OUTPUT removed from {self.config}\n"))
        self.assertEqual(self.config.read_text(encoding="utf-8"), "CONFLUENCE_SPACE=ENG\n")
        self.assertEqual(self.run_cli("config", "show").code, 0)

    def test_a_value_that_is_refused_can_be_replaced_too(self):
        self.write("CONFLUENCE_RETRY=many\n")
        self.assertEqual(self.run_cli("pages").code, 1)
        self.assertEqual(self.run_cli("config", "set", "CONFLUENCE_RETRY", "2").code, 0)
        self.assertEqual(self.run_cli("pages", "--limit", "1").code, 0)

    def test_the_token_is_mended_with_setup_token_and_the_hint_says_so(self):
        self.write("CONFLUENCE_API_TOKEN='open\n")
        failed = self.run_cli("ping")
        self.assertEqual(failed.code, 1)
        self.assertIn("conflu setup-token", failed.err)
        self.assertNotIn("config set CONFLUENCE_API_TOKEN", failed.err)
        self.assertEqual(self.run_cli("setup-token", "--stdin", stdin="a-token-123\n").code, 0)
        self.assertEqual(self.config.read_text(encoding="utf-8"), "CONFLUENCE_API_TOKEN=a-token-123\n")
        self.assertEqual(self.run_cli("config", "show").code, 0)

    def test_the_commands_that_clear_things_work_on_a_file_that_cannot_be_read(self):
        self.write("CONFLUENCE_SPACE='ENG\nCONFLUENCE_API_TOKEN=x\n")
        self.assertEqual(self.run_cli("clear-space").out, "The current space was cleared.\n")
        self.assertEqual(self.run_cli("remove-token").out, f"Token removed from {self.config}\n")
        self.assertEqual(self.config.read_text(encoding="utf-8"), "")

    def test_a_line_that_is_no_setting_cannot_be_mended_by_the_commands_but_the_others_still_can(self):
        self.write("SOMETHING_ELSE='open\n")
        failed = self.run_cli("pages")
        self.assertEqual(failed.code, 1)
        self.assertIn("no setting of this program", failed.err)
        self.assertEqual(self.run_cli("config", "unset", "SOMETHING_ELSE").code, 2)  # an unknown name: the hint says to edit the file
        self.write("")
        self.assertEqual(self.run_cli("pages", "--limit", "1").code, 0)

    def test_a_broken_variable_of_the_environment_does_not_lock_the_repair_out_either(self):
        result = self.cli("config", "set", "CONFLUENCE_SPACE", "ENG", env={"CONFLUENCE_RETRY": "many"})
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.config.read_text(encoding="utf-8"), "CONFLUENCE_SPACE=ENG\n")
        failed = self.cli("pages", env={"CONFLUENCE_RETRY": "many"})
        self.assertEqual(failed.code, 1)
        self.assertIn("CONFLUENCE_RETRY must be a whole number", failed.err)
        self.assertEqual(self.mock.requests, [])

    def test_what_needs_no_setting_works_whatever_the_file_holds(self):
        self.write("CONFLUENCE_SPACE='ENG\n")
        for argv in (("version",), ("help",), ("how-to",), ("commands", "--json")):
            with self.subTest(argv=argv):
                self.assertEqual(self.run_cli(*argv).code, 0)

    def test_an_error_is_reported_as_text_where_the_settings_cannot_say_otherwise(self):
        self.write("CONFLUENCE_OUTPUT='json\n")
        failed = self.run_cli("pages")
        self.assertEqual(failed.code, 1)
        self.assertTrue(failed.err.startswith("ERROR: "), failed.err)  # the same as before: a configuration that cannot be read cannot ask for JSON
        self.assertEqual(json.loads(self.run_cli("pages", "--json").err.strip().splitlines()[-1])["error"]["code"], "CONFIG")


class UnreadableSettingsTest(unittest.TestCase):
    def problem(self) -> ConfigError:
        return ConfigError("CONFLUENCE_SPACE has unbalanced quotes in the config file (line 3 of x).", hint="Fix the line.", details={"line": 3})

    def test_it_answers_what_the_report_of_an_error_asks_and_nothing_else_at_any_time(self):
        settings = UnreadableSettings(self.problem())
        for sealed in (False, True):
            if sealed:
                settings.seal()
            self.assertIs(settings.json_by_default, False)
            self.assertIs(settings.quiet, False)

    def test_the_credentials_are_answered_while_the_application_is_made_and_not_after(self):
        settings = UnreadableSettings(self.problem())
        self.assertEqual((settings.api_token, settings.email), ("", ""))
        settings.seal()
        for name in ("api_token", "email"):
            with self.subTest(name=name), self.assertRaises(ConfigError):
                getattr(settings, name)

    def test_every_other_setting_is_the_explanation_that_every_command_got_before(self):
        settings = UnreadableSettings(self.problem())
        names = [field for field in Settings.__dataclass_fields__ if field not in ("api_token", "email")] + ["wiki_url"]
        for name in names:
            with self.subTest(name=name), self.assertRaises(ConfigError) as caught:
                getattr(settings, name)
            self.assertEqual((caught.exception.message, caught.exception.hint, caught.exception.details), (self.problem().message, "Fix the line.", {"line": 3}))
            self.assertEqual(caught.exception.exit_code, 1)

    def test_each_error_is_a_new_one_so_that_none_collects_the_tracebacks_of_the_others(self):
        settings = UnreadableSettings(self.problem())
        errors = []
        for _ in range(3):
            with self.assertRaises(ConfigError) as caught:
                settings.hide_users
            errors.append(caught.exception)
        self.assertEqual(len({id(error) for error in errors}), 3)

    def test_what_asks_for_something_that_is_no_setting_gets_none(self):
        settings = UnreadableSettings(self.problem())
        self.assertIsNone(getattr(settings, "__deepcopy__", None))
        self.assertIsNone(getattr(settings, "_nothing", None))
        self.assertIsInstance(repr(settings), str)
        self.assertEqual(copy.deepcopy(settings)._problem.message, self.problem().message)

    def test_it_is_not_taken_for_settings_that_were_read(self):
        self.assertNotIsInstance(UnreadableSettings(self.problem()), Settings)


class SelectSpaceTest(unittest.TestCase):
    """The key that a server answers is held to the rule that the key a person types is: it is written into the file."""

    def space_with_key(self, key: str) -> FakeGateway:
        gateway = FakeGateway()
        gateway.spaces["ENG"] = replace(gateway.spaces["ENG"], key=key)
        return gateway

    def test_a_key_that_is_none_is_refused_as_an_answer_and_nothing_is_saved(self):
        for key in ("ENG\nX", "ENG\r\nCONFLUENCE_HIDE_USERS=false", "ENG\u2028X", "ENG X", "", "x" * 300, "ENG;rm", "ENG\x00", "'ENG"):
            store = MemoryConfigStore()
            with self.subTest(key=repr(key)[:30]):
                result = run_cli("use", "ENG", gateway=self.space_with_key(key), store=store)
                self.assertEqual(result.code, 7, result.err)
                self.assertIn("cannot be saved as the current space", result.err)
                self.assertEqual(store.values, {})
                self.assertNotIn("CONFLUENCE_HIDE_USERS", result.err + result.out)  # what the answer said is not repeated

    def test_the_error_is_an_unavailable_error_from_the_use_case(self):
        from tests.support.fakes import build_app

        app = build_app(gateway=self.space_with_key("ENG\nX"), store=MemoryConfigStore())
        with self.assertRaises(UnavailableError) as caught:
            app.config.select_space("ENG")
        self.assertIn("Nothing was saved", caught.exception.hint)

    def test_the_keys_that_confluence_uses_are_saved(self):
        for key in ("ENG", "~712020abcdef0123", "my-space_1", "A.B:C", "a" * 255):
            store = MemoryConfigStore()
            with self.subTest(key=key[:20]):
                result = run_cli("use", "ENG", gateway=self.space_with_key(key), store=store)
                self.assertEqual(result.code, 0, result.err)
                self.assertEqual(store.values, {"CONFLUENCE_SPACE": key})


if __name__ == "__main__":
    unittest.main()
