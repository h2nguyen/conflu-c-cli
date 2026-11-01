"""JSON that an app stored as a text in a property, through the real program against the mock: what a reading shows, in the strict policy too, and what `property-set`
does with a value that was read and is written back.
"""
import json
import unittest

from conflu_c_cli.domain.properties import shown_value
from tests.integration.test_end_to_end import ACCOUNT, EndToEnd
from tests.support.mock_properties import PropertiesRoutes

PERSON = {"accountId": ACCOUNT, "displayName": "Alex Example", "email": "alex@example.com"}
STORED = json.dumps({"reviewer": PERSON, "n": 1})  # what `JSON.stringify` makes: a text
SHOWN = '{"reviewer":{"hidden":true},"n":1}'
STRICT = {"CONFLUENCE_HIDE_USERS": "true"}
READ = ("properties", "2002", "--key", "app.state", "--json", "--max-chars", "0")


class JsonTextFlow(EndToEnd):
    def setUp(self):
        super().setUp()
        self.area = self.mock.area(PropertiesRoutes)
        self.area.add_property("pages", "2002", "app.state", STORED)

    def held(self, key="app.state"):
        return next(item["value"] for item in self.area.store[("pages", "2002")] if item["key"] == key)

    def writes(self):
        return [item for item in self.mock.requests if item.method in ("PUT", "POST") and "/properties" in item.path]

    def value_of(self, result):
        (item,) = result.json()["properties"]
        return item["value"]


class ReadingTest(JsonTextFlow):
    def test_the_names_in_a_text_of_json_are_hidden_by_default_and_in_the_strict_policy(self):
        for env in ({}, STRICT):
            for argv in (READ, ("properties", "2002", "--key", "app.state", "--max-chars", "0")):
                result = self.cli(*argv, env=env)
                with self.subTest(env=env, argv=argv[-1]):
                    self.assertEqual(result.code, 0, result.err)
                    for secret in (ACCOUNT, "Alex Example", "alex@example.com"):
                        self.assertNotIn(secret, result.out + result.err)
                    self.assertIn("hidden", result.out)  # the stand-in of the user object: `{"hidden":true}` in the text

    def test_the_value_in_the_json_is_the_text_as_compact_json(self):
        self.assertEqual(self.value_of(self.cli(*READ)), SHOWN)
        self.assertEqual(self.value_of(self.cli(*READ, env=STRICT)), SHOWN)

    def test_with_the_people_asked_for_it_is_the_text_that_is_stored(self):
        result = self.cli("properties", "2002", "--key", "app.state", "--json", "--max-chars", "0", "--with-users")
        self.assertEqual(self.value_of(result), STORED)
        refused = self.cli("properties", "2002", "--key", "app.state", "--json", "--with-users", env=STRICT)
        self.assertEqual((refused.code, refused.out), (1, ""))

    def test_a_text_that_was_encoded_twice_and_an_account_id_in_capitals_are_hidden_too(self):
        self.area.add_property("pages", "2002", "app.twice", json.dumps(STORED))
        self.area.add_property("pages", "2002", "app.note", f"asked {ACCOUNT.upper()} to look")
        for env in ({}, STRICT):
            twice = self.cli("properties", "2002", "--key", "app.twice", "--json", "--max-chars", "0", env=env)
            note = self.cli("properties", "2002", "--key", "app.note", "--json", env=env)
            with self.subTest(env=env):
                self.assertEqual(self.value_of(twice), json.dumps(SHOWN))
                self.assertEqual(self.value_of(note), "asked [hidden] to look")


class WritingBackTest(JsonTextFlow):
    def test_the_text_as_it_was_shown_is_not_written_back_over_the_text_that_is_stored(self):
        for extra in ((), ("--dry-run",)):
            result = self.cli("property-set", "2002", "--key", "app.state", "--value", json.dumps(SHOWN), *extra)
            with self.subTest(extra=extra):
                self.assertEqual(result.code, 1, result.out)
                self.assertIn("conflu properties 2002 --key app.state --with-users --max-chars 0 --json", result.err)
                self.assertIn(SHOWN, result.err)  # the message shows the text that was changed by the reading
        self.assertEqual((self.held(), self.writes()), (STORED, []))

    def test_the_same_in_the_form_of_json_for_a_script(self):
        result = self.cli("property-set", "2002", "--key", "app.state", "--value", json.dumps(SHOWN), "--json")
        self.assertEqual((result.code, result.out), (1, ""))
        self.assertEqual(self.held(), STORED)

    def test_the_real_value_that_was_read_with_the_people_is_taken_back_as_unchanged(self):
        real = self.value_of(self.cli("properties", "2002", "--key", "app.state", "--json", "--max-chars", "0", "--with-users"))
        result = self.cli("property-set", "2002", "--key", "app.state", "--value", json.dumps(real), "--json")
        self.assertEqual(result.code, 0, result.err)
        data = result.json()
        self.assertEqual((data["action"], data["versionFrom"], data["versionTo"], data["payload"]), ("unchanged", 1, 1, None))
        self.assertEqual(self.writes(), [])

    def test_the_real_value_that_was_read_with_the_people_can_be_changed_and_written(self):
        real = self.value_of(self.cli("properties", "2002", "--key", "app.state", "--json", "--max-chars", "0", "--with-users"))
        changed = json.dumps({**json.loads(real), "n": 2})
        result = self.cli("property-set", "2002", "--key", "app.state", "--value", json.dumps(changed), "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual((result.json()["action"], result.json()["versionTo"]), ("updated", 2))
        self.assertEqual(self.held(), changed)
        self.assertIn(ACCOUNT, self.held())  # the account id of the reviewer is still there: nothing was redacted

    def test_a_text_of_json_that_somebody_writes_is_a_value_like_any_other(self):
        result = self.cli("property-set", "2002", "--key", "app.state", "--value", json.dumps('{"x":1}'))
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.held(), '{"x":1}')

    def test_a_text_without_people_is_what_the_reading_shows_and_goes_back_unchanged(self):
        self.area.add_property("pages", "2002", "app.plain", '{"a": 1,  "b": [1, 2]}')
        read = self.value_of(self.cli("properties", "2002", "--key", "app.plain", "--json"))
        self.assertEqual(read, '{"a": 1,  "b": [1, 2]}')
        result = self.cli("property-set", "2002", "--key", "app.plain", "--value", json.dumps(read), "--json")
        self.assertEqual((result.code, result.json()["action"]), (0, "unchanged"))


class SameAsTheDomainTest(unittest.TestCase):
    def test_what_the_program_shows_is_what_the_domain_says(self):
        self.assertEqual(shown_value(STORED, with_users=False), SHOWN)


if __name__ == "__main__":
    unittest.main()
