"""The agent profile: one setting that keeps people out, makes JSON the default and keeps informational messages off standard error."""
import unittest

from conflu_c_cli.application.settings import Settings
from conflu_c_cli.domain.errors import ConfigError
from tests.support.cli import run_cli
from tests.support.fakes import BASE, default_settings

STORED = {"CONFLUENCE_BASE_URL": BASE, "CONFLUENCE_EMAIL": "user@example.com", "CONFLUENCE_API_TOKEN": "secret-token"}


def agent(**extra: str) -> Settings:
    return Settings.from_mapping({**STORED, "CONFLUENCE_PROFILE": "agent", **extra})


class ProfileSettingsTest(unittest.TestCase):
    def test_the_agent_profile_implies_people_hidden_json_and_quiet(self):
        settings = agent()
        self.assertEqual((settings.profile, settings.hide_users, settings.output, settings.quiet), ("agent", True, "json", True))

    def test_a_value_that_was_set_wins_over_the_profile_even_when_it_is_false(self):
        settings = agent(CONFLUENCE_HIDE_USERS="false", CONFLUENCE_OUTPUT="text")
        self.assertEqual((settings.hide_users, settings.output, settings.quiet), (False, "text", True))

    def test_the_profile_name_is_not_case_sensitive_and_nothing_else_is_known(self):
        self.assertEqual(Settings.from_mapping({"CONFLUENCE_PROFILE": "AGENT"}).profile, "agent")
        with self.assertRaises(ConfigError) as caught:
            Settings.from_mapping({"CONFLUENCE_PROFILE": "robot"})
        self.assertIn("robot", caught.exception.message)

    def test_without_the_profile_nothing_changes(self):
        settings = Settings.from_mapping(STORED)
        self.assertEqual((settings.profile, settings.hide_users, settings.output, settings.quiet), ("", False, "text", False))


class ProfileCommandTest(unittest.TestCase):
    def test_people_stay_out_and_the_output_is_json_by_default(self):
        result = run_cli("page", "2002", settings=agent())
        self.assertEqual(result.code, 0, result.err)
        data = result.json()
        self.assertIsNone(data["author"])
        refused = run_cli("page", "2002", "--with-users", settings=agent())
        self.assertEqual(refused.code, 1)
        self.assertIn("CONFLUENCE_HIDE_USERS=true", refused.err)

    def test_an_error_is_json_when_the_settings_ask_for_it_and_not_only_with_the_flag(self):
        result = run_cli("page", "999", settings=agent())
        self.assertEqual((result.code, result.error()["code"], result.error()["exitCode"]), (4, "NOT_FOUND", 4))
        plain = run_cli("page", "999", settings=default_settings())
        self.assertTrue(plain.err.startswith("ERROR: "))

    def test_an_error_before_any_command_ran_is_json_too_when_the_environment_has_the_profile(self):
        result = run_cli("pagez", environ={"CONFLUENCE_PROFILE": "agent"})
        self.assertEqual((result.code, result.error()["code"]), (2, "USAGE"))
        explicit = run_cli("pagez", environ={"CONFLUENCE_PROFILE": "agent", "CONFLUENCE_OUTPUT": "text"})
        self.assertTrue(explicit.err.startswith("ERROR: "))

    def test_informational_messages_are_left_out_and_warnings_stay(self):
        loud = run_cli("pages", "--space", "ENG", "--limit", "1", settings=default_settings(output="text"))
        self.assertIn("[conflu] More pages follow", loud.err)
        quiet = run_cli("pages", "--space", "ENG", "--limit", "1", settings=agent(CONFLUENCE_OUTPUT="text"))
        self.assertNotIn("[conflu]", quiet.err)


if __name__ == "__main__":
    unittest.main()
