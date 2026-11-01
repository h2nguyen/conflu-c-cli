"""The rules about content properties read a value in a time that grows with its size, whatever it is made of (the values and the keys of `properties`, the value that
`property-set` is given, the comparison that guards a write). Every shape here is a million characters, or the most that a shape can have of them, and the limit is 3 s,
as in the neighbouring tests; each takes a fraction of a second.
"""
import json
import time
import unittest

from conflu_c_cli.domain.errors import UsageError, ValidationError
from conflu_c_cli.domain.properties import (
    MAX_DEPTH,
    compact,
    copies_written_back,
    markers_in,
    nesting,
    parse_value,
    same_value,
    shown_key,
    shown_text,
    shown_value,
    validate_key,
)

LIMIT_SECONDS = 3.0
MEGABYTE = 1_000_000
ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"


def seconds(call, *args, **kwargs) -> float:
    started = time.perf_counter()
    try:
        call(*args, **kwargs)
    except (UsageError, ValidationError):
        pass  # a value that is refused is the right answer: the time is what is measured
    return time.perf_counter() - started


class ShownValueTest(unittest.TestCase):
    def test_a_text_of_a_million_characters_is_read_in_a_moment_whatever_it_is_made_of(self):
        for label, text in (
            ("hexadecimal digits", "a" * MEGABYTE),
            ("decimal digits", "1" * MEGABYTE),
            ("numbers and colons", "1:" * (MEGABYTE // 2)),
            ("the start of an old account id", "123456:" * (MEGABYTE // 7)),
            ("account ids", (ACCOUNT + " ") * (MEGABYTE // 25)),
            ("account ids in capitals", (ACCOUNT.upper() + " ") * (MEGABYTE // 25)),
            ("less-than signs", "<" * MEGABYTE),
            ("ampersands", "&" * MEGABYTE),
            ("at signs", "a@" * (MEGABYTE // 2)),
            ("addresses of people", "/wiki/people/" * (MEGABYTE // 13)),
            ("half of a surrogate pair", "\ud800" * MEGABYTE),
            ("brackets", "[" * MEGABYTE),
        ):
            for with_users in (False, True):
                with self.subTest(text=label, with_users=with_users):
                    self.assertLess(seconds(shown_value, text, with_users=with_users), LIMIT_SECONDS)
            self.assertLess(seconds(shown_key, text, with_users=False), LIMIT_SECONDS)

    def test_a_million_characters_of_texts_that_look_like_json_are_read_in_a_moment(self):
        for label, value in (
            ("short texts that begin like an array", ["[hidden]"] * 100_000),
            ("short texts of JSON", ['{"a":1}'] * 60_000),
            ("one text of JSON", json.dumps([{"accountId": ACCOUNT, "displayName": "A", "k": number} for number in range(12_000)])),
            ("one text of JSON that was encoded twice", json.dumps(json.dumps([{"accountId": ACCOUNT, "k": number} for number in range(8_000)]))),
            ("a text that begins like JSON and is longer than the limit", "[" + "x" * (2 * MEGABYTE)),
            ("brackets that nest deeper than the interpreter reads", "[" * MEGABYTE),
        ):
            with self.subTest(value=label):
                self.assertLess(seconds(shown_value, value, with_users=False), LIMIT_SECONDS)

    def test_a_value_of_many_members_is_read_in_a_moment(self):
        for label, value in (
            ("keys", {f"k{number}": number for number in range(100_000)}),
            ("keys that are account ids", {f"5b10ac8d82e05b22cc7d4{number:03x}": number for number in range(4096)}),
            ("a list of lists", [[1]] * 300_000),
            ("a chain of objects, each with a text next to it", self.chain()),
        ):
            with self.subTest(value=label):
                self.assertLess(seconds(shown_value, value, with_users=False), LIMIT_SECONDS)
                self.assertLess(seconds(shown_text, shown_value(value, with_users=True), 0), LIMIT_SECONDS)
                self.assertLess(seconds(nesting, value), LIMIT_SECONDS)

    @staticmethod
    def chain():
        value = {"a": "x"}
        for _ in range(MAX_DEPTH - 2):
            value = {"k": value, "pad": "p" * 10_000}
        return {"user": {"accountId": ACCOUNT, "displayName": "A"}, "k": value}


class GuardTest(unittest.TestCase):
    def test_the_comparison_of_a_write_with_what_was_read_is_made_in_a_moment_for_a_property_of_a_million_characters(self):
        big = {f"key{number}": {"accountId": ACCOUNT, "displayName": "Alex", "n": number} for number in range(12_000)}
        chain = ShownValueTest.chain()
        for label, current, new in (("an object of many members", big, {"key1": 1}), ("a chain of objects as deep as is read", chain, {"user": 1, "k": {"k": {"k": {"k": 1}}}})):
            shown = shown_value(current, with_users=False)
            with self.subTest(property=label):
                self.assertLess(seconds(copies_written_back, new, current, shown), LIMIT_SECONDS)
                self.assertLess(seconds(same_value, current, dict(current)), LIMIT_SECONDS)
                self.assertLess(seconds(compact, current), LIMIT_SECONDS)

    def test_the_markers_of_a_value_that_is_as_large_as_a_write_may_be_are_counted_in_a_moment(self):
        self.assertLess(seconds(markers_in, {"a": "[hidden] " * 4000, "b": ["[email]"] * 4000}), LIMIT_SECONDS)


class ParseValueTest(unittest.TestCase):
    def test_a_value_that_a_person_types_is_judged_in_a_moment_even_when_it_is_a_file_of_a_megabyte(self):
        for label, text in (
            ("a word of a million characters", "a" * MEGABYTE),
            ("brackets that are never closed", "[" * MEGABYTE),
            ("a text of a million characters", '"' + "a" * MEGABYTE + '"'),
            ("blanks and a number", " " * MEGABYTE + "1"),
            ("escapes", '"' + "\\u00e9" * 150_000 + '"'),
            ("an object that is deep", '{"a":' * 5000 + "1" + "}" * 5000),
        ):
            with self.subTest(text=label):
                self.assertLess(seconds(parse_value, text, "--value"), LIMIT_SECONDS)

    def test_a_key_of_a_million_characters_is_refused_in_a_moment(self):
        self.assertLess(seconds(validate_key, "a" * MEGABYTE), LIMIT_SECONDS)
        self.assertLess(seconds(validate_key, "a-" * MEGABYTE), LIMIT_SECONDS)


if __name__ == "__main__":
    unittest.main()
