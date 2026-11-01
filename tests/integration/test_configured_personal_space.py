"""The key of the configured personal space is the account id of its owner: `current`, `config show`, `doctor` (and the cache it keeps) and the message of a
space that is not there print `[hidden]`, as `use`, `spaces` and `pages` do. The setting itself, in the settings file or the environment, keeps the real key."""
import json

from tests.integration.test_end_to_end import EndToEnd

ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"
KEY = f"~{ACCOUNT}"


class ConfiguredPersonalSpaceTest(EndToEnd):
    def setUp(self):
        super().setUp()
        self.mock.add_space(KEY, "Alex Example", "personal")
        self.cache = self.root / "cache"
        self.env["XDG_CACHE_HOME"] = str(self.cache)

    def run_with(self, *argv, strict=False):
        env = {"CONFLUENCE_SPACE": KEY}
        if strict:
            env["CONFLUENCE_HIDE_USERS"] = "true"
        return self.cli(*argv, env=env)

    def test_current_prints_hidden_in_text_and_in_json_and_still_succeeds(self):
        for strict in (False, True):
            with self.subTest(strict=strict):
                text = self.run_with("current", strict=strict)
                self.assertEqual((text.code, text.out), (0, "[hidden]\n"))
                data = self.run_with("current", "--json", strict=strict)
                self.assertEqual((data.code, data.json()), (0, {"space": "[hidden]"}))
        self.assertEqual(self.cli("current", env={"CONFLUENCE_SPACE": ""}).code, 1)  # no current space: still exit code 1, nothing printed as a key

    def test_a_space_that_is_not_personal_is_shown_as_it_is(self):
        self.assertEqual(self.cli("current", env={"CONFLUENCE_SPACE": "ENG"}).out, "ENG\n")
        self.assertEqual(self.cli("current", "--json", env={"CONFLUENCE_SPACE": "ENG"}).json(), {"space": "ENG"})

    def test_config_show_hides_the_key_and_the_file_keeps_it(self):
        self.assertEqual(self.cli("use", KEY).code, 0)
        shown = self.cli("config", "show")
        self.assertNotIn(ACCOUNT, shown.out + shown.err)
        as_json = self.cli("config", "show", "--json")
        entry = next(item for item in as_json.json()["settings"] if item["name"] == "CONFLUENCE_SPACE")
        self.assertEqual((entry["value"], entry["source"]), ("[hidden]", "config file"))
        self.assertIn(ACCOUNT, self.config.read_text(encoding="utf-8"))  # the file is the person's own and keeps the real key (quoted, because of the `~`)
        again = self.cli("config", "show", env={"CONFLUENCE_SPACE": KEY})
        self.assertNotIn(ACCOUNT, again.out)

    def test_doctor_hides_the_key_in_what_it_prints_and_in_what_it_remembers(self):
        for strict in (False, True):
            with self.subTest(strict=strict):
                result = self.run_with("doctor", "--cached", "10m", "--json", strict=strict)
                self.assertEqual(result.code, 0, result.err)
                checks = {item["name"]: item for item in result.json()["checks"]}
                self.assertEqual(checks["space"]["detail"], "[hidden] is accessible")
                self.assertNotIn(ACCOUNT, result.out + result.err)
        remembered = [path.read_text(encoding="utf-8", errors="replace") for path in self.cache.rglob("*") if path.is_file()]
        self.assertTrue(remembered)
        self.assertEqual([text for text in remembered if ACCOUNT in text], [])

    def test_doctor_that_cannot_find_the_space_does_not_print_its_key_either(self):
        result = self.cli("doctor", "--json", env={"CONFLUENCE_SPACE": "~gone-account"})
        space = next(item for item in result.json()["checks"] if item["name"] == "space")
        self.assertEqual(space["status"], "fail")
        self.assertIn("[hidden]: No space with the key [hidden].", space["detail"])
        self.assertNotIn("gone-account", result.out + result.err)

    def test_the_message_for_a_space_that_is_not_there_hides_a_personal_key_and_names_any_other(self):
        text = self.cli("pages", "--space", "~gone-account")
        self.assertEqual(text.code, 4)
        self.assertIn("No space with the key [hidden].", text.err)
        self.assertNotIn("gone-account", text.err)
        as_json = self.cli("pages", "--space", "~gone-account", "--json")
        error = json.loads(as_json.err.strip().splitlines()[-1])["error"]
        self.assertEqual((error["code"], error["message"], error["details"]["space"]), ("NOT_FOUND", "No space with the key [hidden].", "[hidden]"))
        other = self.cli("pages", "--space", "NOPE")
        self.assertIn("No space with the key NOPE.", other.err)
        self.assertEqual(json.loads(self.cli("pages", "--space", "NOPE", "--json").err.strip().splitlines()[-1])["error"]["details"]["space"], "NOPE")
