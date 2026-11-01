"""JSON that an app stored as a text, in a content property: a reading hides the people in it like the people in any other value, and the guard of `property-set`
still sees what a reading changed.

Apps keep `JSON.stringify(state)` as the value of a property, so the value is a text that holds a user object, and the name in it is neither an address nor an
account id, which are what a text rule can find.
"""
import json
import time
import unittest
from unittest import mock

from conflu_c_cli.domain import properties
from conflu_c_cli.domain.properties import MAX_DEPTH, MAX_EMBEDDED_LAYERS, copies_written_back, shown_key, shown_value

ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"
OLD_ACCOUNT = "557058:3f2c1a9e-4b7d-4c3e-9a1b-2d3e4f5a6b7c"
PERSON = {"accountId": ACCOUNT, "displayName": "Alex Example", "email": "alex@example.com"}
STORED = json.dumps({"reviewer": PERSON, "n": 1})  # what `JSON.stringify` makes: a text
SHOWN = '{"reviewer":{"hidden":true},"n":1}'


def encoded(text, times):
    for _ in range(times):
        text = json.dumps(text)
    return text


def nested_in_lists(levels, inner):
    for _ in range(levels):
        inner = [inner]
    return inner


class ReadAsJsonTest(unittest.TestCase):
    def test_a_user_object_in_a_text_is_hidden_and_the_text_is_compact_json_again(self):
        shown = shown_value(STORED, with_users=False)
        self.assertEqual(shown, SHOWN)
        for secret in (ACCOUNT, "Alex Example", "alex@example.com"):
            self.assertNotIn(secret, shown)

    def test_so_is_one_in_a_list_in_an_object_and_in_a_list(self):
        self.assertEqual(shown_value(json.dumps([json.loads(STORED), 2]), with_users=False), '[{"reviewer":{"hidden":true},"n":1},2]')
        self.assertEqual(shown_value({"state": STORED, "all": [STORED, "plain"], "n": 1}, with_users=False), {"state": SHOWN, "all": [SHOWN, "plain"], "n": 1})

    def test_the_names_that_stand_next_to_an_account_id_in_a_text_go_with_the_object_they_are_in(self):
        text = json.dumps({"owner": {"id": ACCOUNT}, "createdBy": ACCOUNT, "assignedTo": OLD_ACCOUNT, "team": {"publicName": "Alex"}, "title": "Plan"})
        shown = shown_value(text, with_users=False)
        for secret in (ACCOUNT, OLD_ACCOUNT, "Alex"):
            self.assertNotIn(secret, shown)
        self.assertIn('"title":"Plan"', shown)

    def test_json_that_was_encoded_twice_is_read_through_both_and_written_the_same_way(self):
        self.assertEqual(shown_value(encoded(STORED, 1), with_users=False), json.dumps(SHOWN))
        self.assertEqual(shown_value(encoded(STORED, 2), with_users=False), encoded(SHOWN, 2))
        self.assertEqual(shown_value(encoded(STORED, MAX_EMBEDDED_LAYERS), with_users=False), encoded(SHOWN, MAX_EMBEDDED_LAYERS))

    def test_a_text_that_is_encoded_more_often_than_anybody_does_it_stays_a_text(self):
        shown = shown_value(encoded(STORED, MAX_EMBEDDED_LAYERS + 1), with_users=False)
        self.assertNotIn(ACCOUNT, shown)  # the text rules read it, as they always did
        self.assertIn("Alex Example", shown)  # and that is all that reads it: this is the limit

    def test_a_text_that_holds_nobody_stays_as_it_is_down_to_its_blanks(self):
        for text in ('{"a": 1, "b": [1, 2]}', "[1,   2, 3]", '{ "a" : { "b" : null } }', '  {"a": "x"}  ', '["a", "b"]'):
            with self.subTest(text=text):
                self.assertEqual(shown_value(text, with_users=False), text)

    def test_what_only_begins_like_json_is_a_text(self):
        for text in ("[hidden]", "[email]", "[x", "{{macro}}", "{x}", "[personal link] and more", '"quoted"', "[1, 2", "[1, 2] and 3", "{}x"):
            with self.subTest(text=text):
                self.assertEqual(shown_value(text, with_users=False), text)
        self.assertEqual(shown_value("[1, 2] " + ACCOUNT, with_users=False), "[1, 2] [hidden]")  # the text rules read it, as they always did

    def test_with_the_people_asked_for_the_text_is_what_is_stored_to_the_last_blank(self):
        for text in (STORED, encoded(STORED, 2), f'  {{"a" :  "{ACCOUNT}"}} '):
            with self.subTest(text=text[:30]):
                self.assertEqual(shown_value(text, with_users=True), text)
                self.assertEqual(shown_value({"a": [text]}, with_users=True), {"a": [text]})

    def test_a_text_with_a_number_that_json_does_not_have_is_read_by_the_text_rules_alone(self):
        for number in ("NaN", "Infinity", "-Infinity", "1e999"):
            with self.subTest(number=number):
                shown = shown_value('{"n": %s, "who": "%s"}' % (number, ACCOUNT), with_users=False)
                self.assertEqual(shown, '{"n": %s, "who": "[hidden]"}' % number)

    def test_a_text_that_would_nest_the_value_deeper_than_the_limit_is_read_by_the_text_rules_alone(self):
        levels = MAX_DEPTH - 2  # the object of STORED is two levels deep
        self.assertEqual(properties.nesting(json.loads(STORED)), 2)
        inside = shown_value(nested_in_lists(levels, STORED), with_users=False)
        outer = inside
        for _ in range(levels):
            outer = outer[0]
        self.assertEqual(outer, SHOWN)
        beyond = shown_value(nested_in_lists(levels + 1, STORED), with_users=False)
        for _ in range(levels + 1):
            beyond = beyond[0]
        self.assertNotIn(ACCOUNT, beyond)
        self.assertIn("Alex Example", beyond)

    def test_a_text_that_is_longer_than_the_limit_is_read_by_the_text_rules_alone(self):
        with mock.patch.object(properties, "MAX_EMBEDDED_CHARS", len(STORED)):
            self.assertEqual(shown_value(STORED, with_users=False), SHOWN)
        with mock.patch.object(properties, "MAX_EMBEDDED_CHARS", len(STORED) // 2):  # the text has been through the redaction of its address by then, which makes it a little shorter
            shown = shown_value(STORED, with_users=False)
        self.assertNotIn(ACCOUNT, shown)
        self.assertIn("Alex Example", shown)

    def test_a_million_characters_of_json_are_read_in_a_moment(self):
        big = json.dumps([{"accountId": ACCOUNT, "displayName": "A", "k": number} for number in range(12_000)])
        started = time.perf_counter()
        shown = shown_value(big, with_users=False)
        self.assertLess(time.perf_counter() - started, 3.0)
        self.assertNotIn(ACCOUNT, shown)
        started = time.perf_counter()
        shown_value("[" + "x" * 2_000_000, with_users=False)
        shown_value(["[hidden]"] * 100_000, with_users=False)
        self.assertLess(time.perf_counter() - started, 3.0)


class UpperCaseAccountIdTest(unittest.TestCase):
    def test_an_account_id_in_capitals_is_one(self):
        self.assertEqual(shown_value(f"see {ACCOUNT.upper()} please", with_users=False), "see [hidden] please")
        self.assertEqual(shown_value(f"{ACCOUNT[:12].upper()}{ACCOUNT[12:]}", with_users=False), "[hidden]")  # one case or two
        self.assertEqual(shown_value({"who": [ACCOUNT.upper()]}, with_users=False), {"who": ["[hidden]"]})
        self.assertEqual(shown_key(ACCOUNT.upper(), with_users=False), "[hidden]")
        self.assertEqual(shown_value(f"user {OLD_ACCOUNT.upper()}", with_users=False), "user [hidden]")

    def test_it_is_still_the_whole_word_that_counts(self):
        for text in (ACCOUNT.upper() + "0", "0" + ACCOUNT.upper(), ACCOUNT.upper()[:-1], "G" * 24, "5B10AC8D82E05B22CC7D4EF5" * 2):
            with self.subTest(text=text):
                self.assertEqual(shown_value(text, with_users=False), text)

    def test_what_people_may_see_when_they_are_shown_is_not_touched(self):
        self.assertEqual(shown_value(ACCOUNT.upper(), with_users=True), ACCOUNT.upper())


class GuardTest(unittest.TestCase):
    """`property-set` refuses a value that is a copy of what a reading showed. A text that was read as JSON is such a copy when it is written back as shown."""

    def test_the_text_as_it_was_shown_is_a_copy_and_the_text_as_it_is_stored_is_not(self):
        shown = shown_value(STORED, with_users=False)
        markers, texts = copies_written_back(shown, STORED, shown)
        self.assertEqual((markers, texts), ([], [SHOWN]))
        self.assertEqual(copies_written_back(STORED, STORED, shown), ([], []))

    def test_it_holds_where_the_text_stands_in_a_value(self):
        current = {"state": STORED, "n": 1}
        shown = shown_value(current, with_users=False)
        self.assertEqual(copies_written_back(shown, current, shown), ([], [SHOWN]))
        self.assertEqual(copies_written_back({"state": SHOWN, "n": 2}, current, shown), ([], [SHOWN]))
        self.assertEqual(copies_written_back(current, current, shown), ([], []))
        self.assertEqual(copies_written_back({"state": STORED, "n": 2}, current, shown), ([], []))

    def test_a_text_that_somebody_wrote_is_no_copy(self):
        shown = shown_value(STORED, with_users=False)
        self.assertEqual(copies_written_back('{"x":1}', STORED, shown), ([], []))
        self.assertEqual(copies_written_back("a text", STORED, shown), ([], []))

    def test_a_text_that_was_encoded_twice_is_a_copy_in_the_form_that_was_shown(self):
        current = encoded(STORED, 2)
        shown = shown_value(current, with_users=False)
        self.assertNotEqual(shown, current)
        self.assertEqual(copies_written_back(shown, current, shown), ([], [shown]))
        self.assertEqual(copies_written_back(current, current, shown), ([], []))

    def test_a_text_without_people_is_what_it_was_so_nothing_is_a_copy(self):
        current = '{"a": 1,  "b": [1, 2]}'
        shown = shown_value(current, with_users=False)
        self.assertEqual(shown, current)
        self.assertEqual(copies_written_back(shown, current, shown), ([], []))


if __name__ == "__main__":
    unittest.main()
