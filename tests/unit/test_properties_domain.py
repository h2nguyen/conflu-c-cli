"""The rules about content properties that need no Confluence: which collection holds them, the key and the value that may be set, when two values are the same, and what may be shown."""
import time
import unittest
from pathlib import Path

from conflu_c_cli.domain.errors import UsageError, ValidationError
from conflu_c_cli.domain.privacy import blanked_attributes, redact_storage
from conflu_c_cli.domain.properties import (
    CUT_MARKER,
    MAX_DEPTH,
    MAX_KEY,
    MAX_VALUE_BYTES,
    STAND_INS,
    TOO_DEEP,
    USER_OBJECT,
    VALUE_HINT,
    altered_texts_written_back,
    collection_of,
    compact,
    copied_places,
    copies_written_back,
    create_payload,
    markers_in,
    markers_written_back,
    named,
    nesting,
    parse_value,
    same_value,
    shown_key,
    shown_text,
    shown_value,
    texts_in,
    update_payload,
    validate_key,
)

ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"
OLD_ACCOUNT = "557058:3f2c1a9e-4b7d-4c3e-9a1b-2d3e4f5a6b7c"
BLANKED = 'ri:account-id="hidden"'  # what a reading shows in the place of the account id of a mention in a text that is storage format


def deep(levels, inner=None):
    value = inner
    for _ in range(levels):
        value = [value]
    return value


class CollectionTest(unittest.TestCase):
    def test_every_kind_that_has_properties_has_a_collection_of_the_api(self):
        for kind, collection in (
            ("page", "pages"), ("blogpost", "blogposts"), ("folder", "folders"), ("whiteboard", "whiteboards"), ("database", "databases"), ("embed", "embeds"),
            ("attachment", "attachments"), ("footer-comment", "comments"), ("inline-comment", "comments"),
        ):
            with self.subTest(kind=kind):
                self.assertEqual(collection_of(kind), collection)

    def test_what_has_no_properties_here_has_no_collection(self):
        for kind in ("custom", "space", "comment", "Page", "", "pages", "../pages"):
            with self.subTest(kind=kind):
                self.assertIsNone(collection_of(kind))

    def test_a_message_names_the_content_as_a_person_would(self):
        for kind, content_id, text in (
            ("page", "2002", "the page 2002"), ("blogpost", "7390", "the blog post 7390"), ("embed", "7394", "the smart link 7394"),
            ("footer-comment", "4001", "the footer comment 4001"), ("inline-comment", "4003", "the inline comment 4003"), ("attachment", "att5001", "the attachment att5001"),
            ("folder", "7391", "the folder 7391"), ("whiteboard", "7392", "the whiteboard 7392"), ("database", "7393", "the database 7393"),
        ):
            with self.subTest(kind=kind):
                self.assertEqual(named(kind, content_id), text)


class KeyTest(unittest.TestCase):
    def test_a_key_of_letters_digits_and_a_few_marks_is_a_key(self):
        for key in ("a", "team.review", "my-app:state", "A_b-c.d:e", "0", "x" * MAX_KEY, "content-appearance-published"):
            with self.subTest(key=key[:30]):
                self.assertEqual(validate_key(key), key)

    def test_anything_else_is_refused_with_an_example(self):
        for key in (
            "", "x" * (MAX_KEY + 1), "bad key", "a@b.c", "tab\there", "new\nline", "key\n", "\u00e9", "../x", "a/b", "a\x00b", "\u202eevil", "a;b", "a=b", "a?b", "a#b", "%41",
            "\u0661\u0662", "key ", " key",
        ):
            with self.subTest(key=key[:30]), self.assertRaises(UsageError) as caught:
                validate_key(key)
            self.assertIn("255", caught.exception.message)
            self.assertIn("team.review", caught.exception.hint)

    def test_no_key_is_not_a_key(self):
        with self.assertRaises(UsageError):
            validate_key(None)  # type: ignore[arg-type]


class NestingTest(unittest.TestCase):
    def test_a_plain_value_does_not_nest_and_each_array_or_object_is_a_level(self):
        for value, levels in ((1, 0), ("text", 0), (None, 0), ([], 1), ({}, 1), ([[1]], 2), ({"a": [{"b": 1}]}, 3), ([1, [2, [3]]], 3), ({"a": 1, "b": {"c": 2}}, 2)):
            with self.subTest(value=value):
                self.assertEqual(nesting(value), levels)

    def test_a_value_nested_far_deeper_than_the_interpreter_can_walk_is_still_measured(self):
        self.assertEqual(nesting(deep(100_000)), 100_000)


class CompactTest(unittest.TestCase):
    def test_one_line_without_blanks_and_with_the_characters_as_they_are(self):
        self.assertEqual(compact({"a": [1, 2], "b": "\u00e9", "c": None, "d": True}), '{"a":[1,2],"b":"\u00e9","c":null,"d":true}')


class ParseValueTest(unittest.TestCase):
    def test_json_values_of_every_kind(self):
        for text, value in (
            ("42", 42), ("-1.5", -1.5), ("1e2", 100.0), ('"text"', "text"), ('"a \\"quoted\\" word"', 'a "quoted" word'), ("true", True), ("false", False), ("null", None), ("[1, 2]", [1, 2]),
            ('{"a": {"b": [1, {"c": null}]}}', {"a": {"b": [1, {"c": None}]}}), (" \n 7 \t", 7), ('"\u00e9\u4e2d"', "\u00e9\u4e2d"), ("[]", []), ("{}", {}), ('""', ""),
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_value(text, "--value"), value)

    def test_a_bare_word_is_a_usage_error_that_says_a_text_needs_quotes_and_how_to_pass_it_in_powershell(self):
        for text in ("open", "Hello world", "true story", "my-app", "status.open"):
            with self.subTest(text=text), self.assertRaises(UsageError) as caught:
                parse_value(text, "--value")
            self.assertIn("a text needs double quotes", caught.exception.message)
            self.assertEqual(caught.exception.hint, VALUE_HINT)
        self.assertIn("PowerShell 5.1", VALUE_HINT)
        self.assertIn("--file", VALUE_HINT)

    def test_invalid_json_says_where(self):
        for text in ('{"a":}', "{a: 1}", "[1,]", "1 2", "'text'", '{"a": 1', "[", '"unfinished', "{'a': 1}", "01", "+1", ".5"):
            with self.subTest(text=text), self.assertRaises(UsageError) as caught:
                parse_value(text, "--value")
            self.assertIn("not valid JSON", caught.exception.message)
            self.assertEqual(caught.exception.hint, VALUE_HINT)

    def test_the_words_that_are_json_in_python_but_not_in_json_are_refused(self):
        for text in ("NaN", "Infinity", "-Infinity", "[NaN]", '{"a": Infinity}'):
            with self.subTest(text=text), self.assertRaises(UsageError):
                parse_value(text, "--value")

    def test_a_number_too_large_to_be_a_number_is_refused_at_any_depth_and_nothing_of_it_is_a_value(self):
        # `1e999` is a number to the grammar and `Infinity` to the interpreter, which would print and send it as `Infinity`, and that is not JSON
        for text in ("1e999", "-1e999", "1E+999", "1.5e400", "1.8e308", "[1e999]", '[1, [2, {"a": -1e999}]]', '{"a": {"b": [1e400]}}', "1" + "0" * 400 + ".5"):
            with self.subTest(text=text), self.assertRaises(UsageError) as caught:
                parse_value(text, "--value")
            self.assertIn("The value is not valid JSON", caught.exception.message)
            self.assertIn("too large for a number", caught.exception.message)
            self.assertIn("no infinity", caught.exception.hint)

    def test_the_message_names_the_number_and_never_all_of_a_very_long_one(self):
        with self.assertRaises(UsageError) as caught:
            parse_value("[1e999]", "--value")
        self.assertIn("1e999 is too large", caught.exception.message)
        with self.assertRaises(UsageError) as caught:
            parse_value("1" + "0" * 5000 + ".5", "--value")
        self.assertLess(len(caught.exception.message), 200)

    def test_the_largest_numbers_that_a_program_can_store_and_the_smallest_are_values(self):
        for text, value in (
            ("1.7976931348623157e308", 1.7976931348623157e308), ("-1.7976931348623157e308", -1.7976931348623157e308), ("1e-999", 0.0), ("-0.0", -0.0),
            ("[1e308, -1e308, 2.5]", [1e308, -1e308, 2.5]), ("1" + "0" * 400, 10**400),
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_value(text, "--value"), value)

    def test_nothing_is_not_a_value_and_the_message_names_where_it_was_looked_for(self):
        for text in ("", "   ", "\n\n", None):
            with self.subTest(text=text), self.assertRaises(UsageError) as caught:
                parse_value(text, "value.json")  # type: ignore[arg-type]
            self.assertIn("value.json", caught.exception.message)
            self.assertEqual(caught.exception.hint, VALUE_HINT)

    def test_the_limit_is_32_kib_of_compact_json_in_utf_8(self):
        edge = '"' + "x" * (MAX_VALUE_BYTES - 2) + '"'
        self.assertEqual(len(parse_value(edge, "--value")), MAX_VALUE_BYTES - 2)
        with self.assertRaises(ValidationError) as caught:
            parse_value('"' + "x" * (MAX_VALUE_BYTES - 1) + '"', "--value")
        self.assertIn("32,769 bytes", caught.exception.message)
        self.assertIn("32 KiB", caught.exception.message)

    def test_blanks_do_not_count_but_a_multi_byte_character_counts_for_its_bytes(self):
        padded = "[" + "1," * 10_000 + "1]"  # 20,002 characters of compact JSON
        self.assertEqual(len(parse_value(padded, "--value")), 10_001)
        spaced = "[" + ", ".join(["1"] * 12_000) + "]"  # far more than 32 KiB with its blanks, 24,001 bytes without
        self.assertEqual(len(parse_value(spaced, "--value")), 12_000)
        with self.assertRaises(ValidationError):
            parse_value('"' + "\u00e9" * 16_384 + '"', "--value")  # 16,384 characters, 32,768 bytes and two quotes

    def test_arrays_and_objects_inside_each_other_stop_at_a_depth_that_no_app_writes(self):
        self.assertEqual(nesting(parse_value("[" * MAX_DEPTH + "]" * MAX_DEPTH, "--value")), MAX_DEPTH)
        self.assertEqual(MAX_DEPTH, 100)  # what the guide, the help and the reference say: 100 levels
        self.assertEqual(nesting(parse_value("[" * 100 + "]" * 100, "--value")), 100)
        with self.assertRaises(ValidationError):
            parse_value("[" * 101 + "]" * 101, "--value")
        for levels in (MAX_DEPTH + 1, 150, 900, 10_000, 100_000):
            with self.subTest(levels=levels), self.assertRaises(ValidationError) as caught:
                parse_value("[" * levels + "]" * levels, "--value")
            self.assertIn("too deeply", caught.exception.message)

    def test_objects_nested_deeply_are_refused_too(self):
        with self.assertRaises(ValidationError):
            parse_value('{"a":' * 5000 + "1" + "}" * 5000, "--value")

    def test_half_of_a_surrogate_pair_is_refused_and_a_whole_pair_is_a_character(self):
        with self.assertRaises(ValidationError) as caught:
            parse_value('"\\ud800"', "--value")
        self.assertIn("not valid Unicode", caught.exception.message)
        self.assertEqual(parse_value('"\\ud83d\\ude00"', "--value"), "\U0001f600")

    def test_a_number_with_thousands_of_digits_is_refused_or_read_and_never_breaks_the_program(self):
        try:
            value = parse_value("1" * 5000, "--value")
        except UsageError:
            pass  # newer versions of Python refuse to read an integer of more than 4300 digits
        else:
            self.assertIsInstance(value, int)

    def test_the_same_key_twice_in_an_object_is_one_key(self):
        self.assertEqual(parse_value('{"a": 1, "a": 2}', "--value"), {"a": 2})


class SameValueTest(unittest.TestCase):
    def test_objects_have_no_order_and_lists_have(self):
        self.assertTrue(same_value({"a": 1, "b": [1, 2]}, {"b": [1, 2], "a": 1}))
        self.assertFalse(same_value([1, 2], [2, 1]))
        self.assertFalse(same_value({"a": 1}, {"a": 1, "b": None}))

    def test_one_and_one_point_zero_are_one_number_and_one_and_true_are_not(self):
        self.assertTrue(same_value(1, 1.0))
        self.assertTrue(same_value({"n": [1.0, 2]}, {"n": [1, 2.0]}))
        self.assertTrue(same_value(100.0, 100))
        self.assertFalse(same_value(1, True))
        self.assertFalse(same_value(0, False))
        self.assertFalse(same_value(1, "1"))
        self.assertFalse(same_value(1.5, 1))
        self.assertFalse(same_value([1], [True]))

    def test_nothing_is_not_an_empty_object_or_text(self):
        self.assertTrue(same_value(None, None))
        for other in ({}, [], "", 0, False):
            with self.subTest(other=other):
                self.assertFalse(same_value(None, other))
        self.assertFalse(same_value({}, []))

    def test_a_value_nested_too_deeply_to_compare_is_not_the_same_and_does_not_break(self):
        self.assertFalse(same_value(deep(50_000), deep(50_000)))
        self.assertFalse(same_value(deep(50_000), [1]))
        self.assertTrue(same_value(deep(50), deep(50)))


class ShownValueTest(unittest.TestCase):
    def test_a_value_without_people_is_as_it_is(self):
        value = {"status": "open", "n": [1, 2.5, None, True], "text": "hello", "nested": {"a": []}}
        self.assertEqual(shown_value(value, with_users=False), value)
        self.assertEqual(shown_value(value, with_users=True), value)

    def test_user_objects_account_ids_and_addresses_are_hidden(self):
        value = {
            "reviewer": {"accountId": ACCOUNT, "displayName": "Alex Example"},
            "owners": [ACCOUNT, OLD_ACCOUNT],
            "note": "Ask alex@example.com",
            "accountId": ACCOUNT,
            "authorId": ACCOUNT,
            "profile": "https://example.atlassian.net/wiki/people/" + ACCOUNT,
        }
        shown = shown_value(value, with_users=False)
        self.assertEqual(shown["reviewer"], {"hidden": True})
        self.assertEqual(shown["owners"], ["[hidden]", "[hidden]"])
        self.assertEqual((shown["note"], shown["accountId"], shown["authorId"]), ("Ask [email]", "[hidden]", "[hidden]"))
        self.assertEqual(shown["profile"], "[personal link]")
        for marker in (ACCOUNT, OLD_ACCOUNT, "alex@example.com", "Alex Example"):
            self.assertNotIn(marker, compact(shown))

    def test_an_account_id_inside_a_text_is_hidden_and_a_longer_word_is_not_an_account_id(self):
        shown = shown_value(
            {"a": f"reviewer={ACCOUNT}", "b": f"[~accountid:{ACCOUNT}] and {OLD_ACCOUNT}!", "c": "a" * 24 + "b", "d": "f" * 40, "e": "x" + "a" * 24 + "x", "f": f"{ACCOUNT},{ACCOUNT}"},
            with_users=False,
        )
        self.assertEqual(shown["a"], "reviewer=[hidden]")
        self.assertEqual(shown["b"], "[~accountid:[hidden]] and [hidden]!")
        self.assertEqual((shown["c"], shown["d"], shown["e"]), ("a" * 24 + "b", "f" * 40, "x" + "a" * 24 + "x"))
        self.assertEqual(shown["f"], "[hidden],[hidden]")

    def test_the_mention_in_a_text_that_is_storage_format_loses_its_account_id(self):
        text = f'<ac:link><ri:user ri:account-id="{ACCOUNT}" /></ac:link>'
        self.assertNotIn(ACCOUNT, compact(shown_value({"t": text}, with_users=False)))
        self.assertIn(ACCOUNT, compact(shown_value({"t": text}, with_users=True)))

    def test_a_key_is_free_text_too(self):
        shown = shown_value({ACCOUNT: 1, "alex@example.com": 2, "plain": 3}, with_users=False)
        self.assertEqual(shown, {"[hidden]": 1, "[email]": 2, "plain": 3})

    def test_keys_that_look_alike_once_hidden_stay_two_and_none_is_lost(self):
        shown = shown_value({ACCOUNT: 1, "5b10ac8d82e05b22cc7d4ef6": 2, "a@b.example": 3, "c@d.example": 4}, with_users=False)
        self.assertEqual(sorted(shown.values()), [1, 2, 3, 4])
        self.assertEqual(len(shown), 4)
        many = shown_value({f"{number:024x}": number for number in range(3000)}, with_users=False)
        self.assertEqual(len(many), 3000)

    def test_a_key_that_is_named_like_the_one_made_for_a_second_look_alike_is_not_lost_either(self):
        shown = shown_value({ACCOUNT: 1, "5b10ac8d82e05b22cc7d4ef6": 2, "[hidden] (2)": 3}, with_users=False)  # the second one is shown as `[hidden] (2)`
        self.assertEqual((sorted(shown.values()), len(shown)), ([1, 2, 3], 3))
        self.assertEqual(list(shown), ["[hidden]", "[hidden] (2)", "[hidden] (2)+"])

    def test_with_the_people_shown_nothing_is_hidden(self):
        value = {"reviewer": {"accountId": ACCOUNT, "displayName": "Alex Example"}, "note": "Ask alex@example.com", ACCOUNT: [OLD_ACCOUNT]}
        self.assertEqual(shown_value(value, with_users=True), value)

    def test_half_of_a_surrogate_pair_is_replaced_whether_or_not_the_people_are_shown(self):
        for with_users in (False, True):
            with self.subTest(with_users=with_users):
                shown = shown_value({"a\ud800": "b\udc00c"}, with_users=with_users)
                self.assertEqual(shown, {"a\ufffd": "b\ufffdc"})
                compact(shown).encode("utf-8")  # a terminal can show it

    def test_a_value_nested_too_deeply_is_not_walked_and_says_so(self):
        for with_users in (False, True):
            with self.subTest(with_users=with_users):
                self.assertEqual(shown_value(deep(MAX_DEPTH + 1), with_users=with_users), TOO_DEEP)
                self.assertEqual(shown_value(deep(100_000), with_users=with_users), TOO_DEEP)
        self.assertEqual(nesting(shown_value(deep(MAX_DEPTH), with_users=False)), MAX_DEPTH)

    def test_the_value_that_was_given_is_not_changed(self):
        value = {"owners": [ACCOUNT], "note": "alex@example.com"}
        shown_value(value, with_users=False)
        self.assertEqual(value, {"owners": [ACCOUNT], "note": "alex@example.com"})

    def test_a_key_that_is_shown(self):
        self.assertEqual(shown_key("team.review", with_users=False), "team.review")
        self.assertEqual(shown_key("alex@example.com", with_users=False), "[email]")
        self.assertEqual(shown_key(ACCOUNT, with_users=False), "[hidden]")
        self.assertEqual(shown_key("alex@example.com", with_users=True), "alex@example.com")
        self.assertEqual(shown_key("a\ud800b", with_users=True), "a\ufffdb")


class StandInsTest(unittest.TestCase):
    """What a reading shows in the place of people must not be written back over them."""

    PEOPLE = {
        "status": "open",
        "reviewer": {"accountId": ACCOUNT, "displayName": "Alex Example"},
        "owners": [ACCOUNT],
        "note": "Ask alex@example.com",
        "profile": "https://example.atlassian.net/wiki/people/" + ACCOUNT,
    }

    def written(self, new, current=PEOPLE):
        return markers_written_back(new, current, shown_value(current, with_users=False))

    def test_every_stand_in_is_counted_in_texts_keys_and_objects(self):
        value = {"[hidden]": ["Ask [email] or [email]", {"hidden": True}], "t": f'<ri:user ri:account-id="hidden" /> [personal link] [personal space] {TOO_DEEP} {CUT_MARKER}'}
        self.assertEqual(
            dict(markers_in(value)),
            {"[hidden]": 1, "[email]": 2, USER_OBJECT: 1, BLANKED: 1, "[personal link]": 1, "[personal space]": 1, TOO_DEEP: 1, CUT_MARKER: 1},
        )

    def test_what_is_no_stand_in_is_not_counted(self):
        values = (None, 1, "text", [], {}, {"hidden": False}, {"hidden": 1}, {"hidden": "true"}, {"hidden": [True]}, {"hidden": True, "other": 1}, self.PEOPLE)
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(dict(markers_in(value)), {})

    def test_a_value_is_walked_without_recursion_and_a_long_text_is_counted_at_once(self):
        self.assertEqual(dict(markers_in(deep(100_000, "[email]"))), {"[email]": 1})
        self.assertEqual(dict(markers_in("[email]" * 100_000)), {"[email]": 100_000})

    def test_the_hidden_form_of_a_property_is_all_stand_ins_and_each_is_named(self):
        shown = shown_value(self.PEOPLE, with_users=False)
        self.assertEqual(self.written(shown), ["[hidden]", "[email]", "[personal link]", USER_OBJECT])

    def test_each_stand_in_alone_is_found_wherever_it_stands(self):
        cases = (
            ({"owners": ["[hidden]"]}, ["[hidden]"]),
            ({"note": "Ask [email]"}, ["[email]"]),
            ({"profile": "[personal link]"}, ["[personal link]"]),
            ({"reviewer": {"hidden": True}}, [USER_OBJECT]),
            ({"[hidden]": 1}, ["[hidden]"]),  # as a key
            ({"moved": {"to": [{"hidden": True}]}}, [USER_OBJECT]),  # not where it was read
            ("Ask [email]", ["[email]"]),  # the whole value is another one
        )
        for new, expected in cases:
            with self.subTest(new=new):
                self.assertEqual(self.written(new), expected)

    def test_a_personal_space_a_blanked_mention_and_a_value_too_deep_to_show_have_stand_ins_too(self):
        space = {"space": {"key": "~" + ACCOUNT, "name": "Alex Example", "type": "personal"}}
        self.assertEqual(self.written({"key": "[hidden]", "name": "[personal space]"}, space), ["[hidden]", "[personal space]"])
        mention = {"t": f'<p><ri:user ri:account-id="{ACCOUNT}" /></p>'}
        self.assertEqual(self.written({"t": '<p><ri:user ri:account-id="hidden" /></p>'}, mention), [BLANKED])
        self.assertEqual(self.written(TOO_DEEP, deep(MAX_DEPTH + 5)), [TOO_DEEP])
        self.assertEqual(self.written({"flat": True}, deep(MAX_DEPTH + 5)), [])

    def test_two_keys_that_look_alike_once_hidden_are_two_stand_ins(self):
        current = {ACCOUNT: 1, "5b10ac8d82e05b22cc7d4ef6": 2}
        self.assertEqual(self.written({"[hidden]": 1, "[hidden] (2)": 2}, current), ["[hidden]"])

    def test_the_real_value_and_a_change_of_it_hold_no_stand_in(self):
        for new in (self.PEOPLE, {**self.PEOPLE, "status": "closed"}, {"status": "closed"}, {"owners": []}, "x", None):
            with self.subTest(new=new):
                self.assertEqual(self.written(new), [])

    def test_a_stand_in_that_the_property_holds_itself_is_none(self):
        current = {"flag": {"hidden": True}, "text": "write [email] here", "list": ["[hidden]"]}
        self.assertEqual(self.written(current, current), [])
        self.assertEqual(self.written({"flag": {"hidden": True}, "more": ["[hidden]"]}, current), [])

    def test_an_apps_flag_that_looks_like_the_user_object_may_be_set_when_the_reading_hid_nobody(self):
        self.assertEqual(self.written({"hidden": True}, {"hidden": False}), [])
        self.assertEqual(self.written({"owners": ["[hidden]"], "note": "[email]", "x": {"hidden": True}}, {"status": "open"}), [])

    def test_a_stand_in_where_the_property_holds_one_itself_and_a_person_is_found_by_how_often_it_is_there(self):
        owner = {"accountId": ACCOUNT, "displayName": "Alex Example"}
        current = {"flag": {"hidden": True}, "owner": owner}
        self.assertEqual(self.written({"flag": {"hidden": True}, "owner": {"hidden": True}}, current), [USER_OBJECT])
        self.assertEqual(self.written({"flag": {"hidden": True}, "owner": owner}, current), [])
        mails = {"text": "see [email] and a@b.example"}
        self.assertEqual(self.written({"text": "see [email]"}, mails), [])
        self.assertEqual(self.written({"text": "see [email] and [email]"}, mails), ["[email]"])

    def test_a_mention_whose_account_id_was_blanked_is_a_stand_in_in_every_attribute_that_holds_one_and_is_named_as_it_stands(self):
        for name in ("ri:account-id", "ri:userkey", "ri:username", "data-account-id", "data-userkey", "data-username"):
            current = {"t": f'<a {name}="{ACCOUNT}">@Alex</a> reviewed', "n": 1}
            shown = shown_value(current, with_users=False)
            with self.subTest(attribute=name):
                self.assertEqual(shown["t"], f'<a {name}="hidden">@Alex</a> reviewed')
                self.assertEqual(self.written({**shown, "n": 2}, current), [f'{name}="hidden"'])
                self.assertEqual(self.written({"t": "changed", "n": 2}, current), [])  # a change that leaves the mention out copies nothing

    def test_the_spelling_of_the_attribute_does_not_matter_and_the_key_of_a_personal_space_is_one_too(self):
        current = {"t": f"<a DATA-Account-Id = '{ACCOUNT}'>x</a> <ri:page ri:space-key=\"~{ACCOUNT}\" ri:content-title=\"T\"/>"}
        shown = shown_value(current, with_users=False)
        found = self.written(shown, current)
        self.assertIn('data-account-id="hidden"', found)
        self.assertIn('ri:space-key="[hidden]"', found)

    def test_blanked_attributes_are_counted_each_and_not_once_for_a_text(self):
        # a text that holds an attribute that reads like a blanked one, and a real one: the reading holds two where the property holds one
        current = {"t": f'<a data-account-id="hidden">a</a> <a data-account-id="{ACCOUNT}">b</a>'}
        shown = shown_value(current, with_users=False)
        self.assertEqual(markers_in(shown)['data-account-id="hidden"'], 2)
        self.assertEqual(markers_in(current)['data-account-id="hidden"'], 1)
        self.assertEqual(self.written(shown, current), ['data-account-id="hidden"'])

    def test_whatever_a_reading_changes_in_a_text_is_refused_when_that_is_written_back(self):
        texts = (
            f'<ri:user ri:account-id="{ACCOUNT}"/>', f'<a data-user-id="{ACCOUNT}">x</a>', f'<a data-mention-id="{ACCOUNT}">x</a>', f"<a data-account-id='{ACCOUNT}'>x</a>",
            f'<ri:page ri:space-key="~{ACCOUNT}"/>', f"see {ACCOUNT} and {OLD_ACCOUNT}", "mail alex@example.com now", "https://example.atlassian.net/wiki/people/" + ACCOUNT,
            "https://example.atlassian.net/wiki/spaces/ENG/pages/124/Contact+alex%40example.com", f"https://example.atlassian.net/wiki/spaces/~{ACCOUNT}/pages/124/Notes",
            f"/wiki/spaces/~{ACCOUNT}/overview", "https://example.atlassian.net/wiki/spaces/ENG/pages/124/Plain+title",
        )
        changed = 0
        for text in texts:
            current = {"t": text}
            shown = shown_value(current, with_users=False)
            with self.subTest(text=text):
                if shown != current:
                    changed += 1
                    self.assertTrue(self.copies(shown, current), shown)
                else:
                    self.assertEqual(self.copies(shown, current), [])
        self.assertGreaterEqual(changed, 10)

    def test_an_address_that_lost_its_title_in_a_reading_is_a_copy_of_it_and_is_refused(self):
        url = "https://example.atlassian.net/wiki/spaces/ENG/pages/124/Contact+alex%40example.com"
        current = {"url": url, "n": 1}
        shown = shown_value(current, with_users=False)
        self.assertEqual(shown["url"], "https://example.atlassian.net/wiki/spaces/ENG/pages/124")  # no marker stands in it
        self.assertEqual(self.written({**shown, "n": 2}, current), [])
        self.assertEqual(altered_texts_written_back({**shown, "n": 2}, current, shown), [shown["url"]])
        self.assertEqual(altered_texts_written_back({"url": url, "n": 2}, current, shown), [])  # the address that Confluence holds is no copy
        self.assertEqual(altered_texts_written_back({"url": "https://example.atlassian.net/wiki/spaces/ENG/pages/125", "n": 2}, current, shown), [])  # nor one that a person wrote

    def test_an_address_in_a_personal_space_is_a_personal_link_in_a_reading_and_is_refused_by_its_marker(self):
        current = {"url": f"https://example.atlassian.net/wiki/spaces/~{ACCOUNT}/pages/124/Notes"}
        shown = shown_value(current, with_users=False)
        self.assertEqual(shown["url"], "[personal link]")
        self.assertEqual(self.written(shown, current), ["[personal link]"])
        self.assertEqual(altered_texts_written_back(shown, current, shown), [])  # the marker rule has it

    def test_a_text_with_a_stand_in_in_it_is_the_business_of_the_stand_ins_and_is_not_listed_twice(self):
        current = {"note": "Ask alex@example.com", "owner": ACCOUNT}
        shown = shown_value(current, with_users=False)
        self.assertEqual(altered_texts_written_back(shown, current, shown), [])
        self.assertEqual(self.written(shown, current), ["[hidden]", "[email]"])

    def test_a_text_that_the_property_holds_in_some_place_is_not_a_copy(self):
        short = "https://example.atlassian.net/wiki/spaces/ENG/pages/124"
        current = {"a": short + "/Contact+alex%40example.com", "b": short}
        shown = shown_value(current, with_users=False)
        self.assertEqual(altered_texts_written_back({"a": short, "b": short}, current, shown), [])  # the limit of a rule that looks at texts and not at places

    def test_nothing_that_is_no_text_is_a_text_and_every_key_is_one(self):
        self.assertEqual(texts_in({"a": [1, None, True, 2.5, "x", {"k": "y"}], 5: "z"}), {"a", "x", "k", "y", "z"})
        self.assertEqual(texts_in(None), set())
        self.assertEqual(texts_in(deep(100_000, "end")), {"end"})

    def test_the_key_of_the_object_that_stands_for_a_person_is_no_text_and_any_other_key_is(self):
        self.assertEqual(texts_in({"hidden": True}), set())
        self.assertEqual(texts_in({"owner": {"hidden": True}}), {"owner"})
        for value in ({"hidden": False}, {"hidden": True, "x": 1}, {"hidden": 1}, {"hidden": "true"}):
            with self.subTest(value=value):
                self.assertIn("hidden", texts_in(value))

    def test_the_end_mark_of_a_cut_value_is_refused_wherever_it_stands_and_for_a_new_property_too(self):
        cut, was_cut, _ = shown_text({"items": list(range(100))}, 20)
        self.assertEqual((was_cut, cut.endswith(CUT_MARKER), cut), (True, True, '{"items":[0,1,2,3,4,' + CUT_MARKER))
        for new in (cut, {"copy": cut}, [cut], {CUT_MARKER: 1}, f"x{CUT_MARKER}y"):
            with self.subTest(new=new):
                self.assertEqual(self.written(new), [CUT_MARKER])
                self.assertEqual(markers_written_back(new, None, None), [CUT_MARKER])  # a new property has nothing to overwrite, and no cut copy is wanted

    def test_a_value_made_to_slow_the_counting_down_is_counted_in_a_moment(self):
        started = time.perf_counter()
        for text in (
            ("ri:account-id" + " " * 200) * 150, "ri:account-id=" + " " * 30_000, "data-" * 6000, ("ri:space-key=" + " " * 100 + '"[hidde') * 200, "[hidden]" * 4000, "=" * 30_000,
            "ri:account-id" + " " * 30_000 + "=" + " " * 30_000 + '"hidden', "https://example.atlassian.net/wiki/spaces/ENG/pages/124/" + "a+" * 15_000,
        ):
            value = {"a": text, "b": [text], text[:50]: 1}
            markers_in(value)
            markers_written_back(value, value, value)
            altered_texts_written_back(value, value, value)
            shown_value(value, with_users=False)
        self.assertLess(time.perf_counter() - started, 5)

    def test_the_end_mark_comes_last_and_a_cut_value_that_holds_people_names_both(self):
        new = {"owners": ["[hidden]"], "copy": CUT_MARKER}
        self.assertEqual(self.written(new), ["[hidden]", CUT_MARKER])

    def test_a_cut_mark_that_the_property_holds_itself_is_none_and_one_more_is(self):
        current = {"log": f"the line was cut {CUT_MARKER}"}
        self.assertEqual(self.written(current, current), [])
        self.assertEqual(self.written({"log": f"{CUT_MARKER} {CUT_MARKER}"}, current), [CUT_MARKER])

    def test_the_names_of_the_stand_ins_are_the_ones_a_help_may_list(self):
        self.assertEqual(STAND_INS, ("[hidden]", "[email]", "[personal link]", "[personal space]", '{"hidden": true}', "[nested too deeply to show]"))
        self.assertEqual(CUT_MARKER, "[value cut]")

    def copies(self, new, current):
        """Everything that is refused when `new` is written over `current`: the stand-ins, and the texts that a reading changed."""
        shown = shown_value(current, with_users=False)
        return markers_written_back(new, current, shown) + altered_texts_written_back(new, current, shown)


class CopiedPlacesTest(unittest.TestCase):
    """What the counts cannot see: a stand-in that the property holds itself, or a text that it holds in another place, does not hide what a reading changed in this place."""

    @staticmethod
    def shown(current):
        return shown_value(current, with_users=False)

    def copies(self, new, current):
        return copies_written_back(new, current, self.shown(current))

    def test_a_stand_in_that_the_property_holds_itself_does_not_hide_a_person_that_was_replaced_by_one(self):
        # an app wrote the text `[hidden]` into one place and the account id of a person stands in another: the reading shows `[hidden]` in both
        current = {"a": "[hidden]", "b": ACCOUNT}
        shown = self.shown(current)
        self.assertEqual(shown, {"a": "[hidden]", "b": "[hidden]"})
        new = {"a": "changed", "b": "[hidden]"}
        self.assertEqual(markers_written_back(new, current, shown), [])  # the counts cannot tell: the property holds one stand-in and so does the new value
        self.assertEqual(copied_places(new, current, shown), [("[hidden]", ACCOUNT)])
        self.assertEqual(self.copies(new, current), (["[hidden]"], []))
        for fine in ({"a": "changed", "b": ACCOUNT}, {"a": "[hidden]", "b": ACCOUNT}, {"a": "[hidden]", "b": "somebody else"}, current):
            with self.subTest(new=fine):
                self.assertEqual(self.copies(fine, current), ([], []))

    def test_the_same_in_a_list_in_an_object_in_a_list_and_by_the_key_that_the_reading_made_of_it(self):
        current = {"rows": [{"owner": "[hidden]"}, {"owner": ACCOUNT}], ACCOUNT: "x"}
        shown = self.shown(current)
        self.assertEqual(shown, {"rows": [{"owner": "[hidden]"}, {"owner": "[hidden]"}], "[hidden]": "x"})
        new = {"rows": [{"owner": "kept"}, {"owner": "[hidden]"}], "[hidden]": "y"}
        self.assertCountEqual(copied_places(new, current, shown), [("[hidden]", ACCOUNT), ({"owner": "[hidden]"}, {"owner": ACCOUNT})])
        self.assertEqual(self.copies(new, current), (["[hidden]"], []))
        self.assertEqual(self.copies({"rows": [{"owner": "kept"}, {"owner": ACCOUNT}], ACCOUNT: "y"}, current), ([], []))

    def test_a_user_object_that_the_reading_made_of_a_person_is_found_in_its_place(self):
        current = {"flag": {"hidden": True}, "owner": {"accountId": ACCOUNT, "displayName": "Alex Example"}}
        shown = self.shown(current)
        new = {"flag": "off", "owner": {"hidden": True}}
        self.assertEqual(markers_written_back(new, current, shown), [])  # one user object in the property, one in the new value
        self.assertEqual(self.copies(new, current), ([USER_OBJECT], []))
        self.assertEqual(self.copies({"flag": "off", "owner": current["owner"]}, current), ([], []))

    def test_an_address_that_lost_its_title_is_found_in_its_place_though_the_property_holds_that_text_elsewhere(self):
        short = "https://example.atlassian.net/wiki/spaces/ENG/pages/124"
        current = {"a": short + "/Contact+alex%40example.com", "b": short}
        shown = self.shown(current)
        new = {"a": short, "b": "changed"}
        self.assertEqual(altered_texts_written_back(new, current, shown), [])  # the text is one that the property holds: the texts cannot tell
        self.assertEqual(self.copies(new, current), ([], [short]))
        self.assertEqual(self.copies({"a": short + "/Contact+alex%40example.com", "b": "changed"}, current), ([], []))

    def test_a_value_that_is_no_copy_finds_nothing_and_a_new_property_has_nothing_to_copy(self):
        for current in (None, 1, "text", [], {}, {"a": [1, {"b": "c"}]}, {"owner": "alex"}, {"hidden": False}):
            with self.subTest(current=current):
                self.assertEqual(copied_places(current, current, self.shown(current)), [])
        self.assertEqual(copies_written_back({"a": "[hidden]", "b": {"hidden": True}}, None, None), ([], []))

    def test_a_stand_in_that_the_property_holds_itself_is_not_named_when_the_place_that_was_copied_holds_it_too(self):
        current = {"row": {"note": "write [email] here", "owner": ACCOUNT}}
        shown = self.shown(current)
        self.assertEqual(shown["row"], {"note": "write [email] here", "owner": "[hidden]"})
        self.assertEqual(self.copies({"row": shown["row"]}, current), (["[hidden]"], []))  # the text `[email]` is the property's own: the message does not blame the copy for it

    def test_a_restructured_value_has_no_place_to_compare_and_is_left_to_the_counts(self):
        current = {"owners": [ACCOUNT, OLD_ACCOUNT]}
        new = {"people": [{"id": "[hidden]"}]}
        self.assertEqual(copied_places(new, current, self.shown(current)), [])
        self.assertEqual(self.copies(new, current), (["[hidden]"], []))
        self.assertEqual(self.copies({"owners": ["[hidden]"]}, current), (["[hidden]"], []))  # a list that got shorter: the counts, too

    def test_a_change_that_has_neither_a_marker_nor_a_text_is_still_a_copy_and_the_reading_is_shown(self):
        self.assertEqual(copies_written_back({"n": 2}, {"n": 1}, {"n": 2}), ([], ['{"n":2}']))

    def test_the_markers_of_the_places_come_in_the_order_of_the_message_and_the_end_mark_stays_last(self):
        current = {"a": ACCOUNT, "b": {"accountId": ACCOUNT, "displayName": "Alex"}, "c": f'<a data-userkey="{ACCOUNT}">x</a>', "d": "mail alex@example.com"}
        shown = self.shown(current)
        markers, texts = copies_written_back({**shown, "e": CUT_MARKER}, current, shown)
        self.assertEqual((markers, texts), (["[hidden]", "[email]", USER_OBJECT, 'data-userkey="hidden"', CUT_MARKER], []))

    def test_a_long_value_and_a_deep_one_are_compared_in_a_moment(self):
        started = time.perf_counter()
        current = {"rows": [{"owner": ACCOUNT, "n": number} for number in range(3000)]}
        shown = self.shown(current)
        markers, _ = copies_written_back({"rows": [{**row, "n": 0} for row in shown["rows"]]}, current, shown)
        self.assertEqual(markers, ["[hidden]"])
        nested = deep(MAX_DEPTH - 1, ACCOUNT)
        shown = self.shown(nested)
        self.assertEqual(copies_written_back(deep(MAX_DEPTH - 1, "[hidden]"), nested, shown), (["[hidden]"], []))
        self.assertEqual(copies_written_back(deep(MAX_DEPTH - 1, ACCOUNT), nested, shown), ([], []))
        self.assertLess(time.perf_counter() - started, 10)


class BlankedAttributesTest(unittest.TestCase):
    """`privacy.blanked_attributes` is the list that the guard of `property-set` reads; it must not fall behind `redact_storage`, which blanks them."""

    def test_each_attribute_comes_back_by_itself_with_a_lower_case_name_and_double_quotes(self):
        text = "<a DATA-Account-Id = 'hidden'>x</a> <ri:user ri:userkey=\"hidden\"/> <ri:page ri:space-key='[hidden]'/> <ri:user ri:username=\"hidden\"/>"
        self.assertEqual(blanked_attributes(text), ['data-account-id="hidden"', 'ri:userkey="hidden"', 'ri:space-key="[hidden]"', 'ri:username="hidden"'])

    def test_what_is_not_blanked_is_not_listed(self):
        for text in (None, "", "text", f'<a data-account-id="{ACCOUNT}">', '<a data-account-id="hidden2">', '<a data-account-id=hidden>', 'ri:space-key="ENG"', "data-account-id"):
            with self.subTest(text=text):
                self.assertEqual(blanked_attributes(text), [])

    def test_every_attribute_that_redact_storage_blanks_is_listed_in_each_spelling(self):
        names = ("ri:account-id", "ri:userkey", "ri:username", "data-account-id", "data-userkey", "data-username")
        for name in names:
            for quote in ('"', "'"):
                for blank in ("", " "):
                    original = f"<a {name}{blank}={blank}{quote}{ACCOUNT}{quote}>x</a>"
                    with self.subTest(original=original):
                        self.assertEqual(blanked_attributes(redact_storage(original)), [f'{name}="hidden"'])
        space = f'<ri:page ri:space-key="~{ACCOUNT}" ri:content-title="T"/>'
        self.assertEqual(blanked_attributes(redact_storage(space)), ['ri:space-key="[hidden]"'])

    def test_an_attribute_that_redact_storage_blanks_is_never_missing_from_the_list(self):
        # Names that apps and editors use for the person behind a mention. If a pattern of `redact_storage` learns one of them, this list must know it too.
        candidates = (
            "ri:user-key", "ri:accountid", "ri:account", "data-user-id", "data-user-key", "data-accountid", "data-account", "data-mention-id", "data-user", "ri:user-id", "account-id",
        )
        for name in candidates:
            original = f'<a {name}="{ACCOUNT}">x</a>'
            blanked = redact_storage(original)
            with self.subTest(attribute=name):
                if f'{name}="hidden"' in blanked:
                    self.assertEqual(blanked_attributes(blanked), [f'{name}="hidden"'])


class ShownTextTest(unittest.TestCase):
    def test_the_whole_text_when_it_is_short_enough(self):
        self.assertEqual(shown_text({"a": [1, 2]}, 100), ('{"a":[1,2]}', False, 11))
        self.assertEqual(shown_text("text", 6), ('"text"', False, 6))

    def test_the_beginning_with_the_mark_of_a_cut_and_the_size_of_the_whole_when_it_is_longer(self):
        self.assertEqual(shown_text({"a": [1, 2]}, 5), ('{"a":' + CUT_MARKER, True, 11))
        text, cut, total = shown_text(["x" * 100], 10)
        self.assertEqual((text, cut, total), ('["xxxxxxxx' + CUT_MARKER, True, 104))

    def test_a_value_that_is_exactly_as_long_as_asked_is_not_cut(self):
        self.assertEqual(shown_text({"a": [1, 2]}, 11), ('{"a":[1,2]}', False, 11))
        self.assertEqual(shown_text({"a": [1, 2]}, 10), ('{"a":[1,2]' + CUT_MARKER, True, 11))

    def test_zero_cuts_nothing(self):
        text, cut, total = shown_text(["x" * 10_000], 0)
        self.assertEqual((len(text), cut, total), (10_004, False, 10_004))
        self.assertNotIn(CUT_MARKER, text)


class PayloadTest(unittest.TestCase):
    def test_a_new_property_is_a_key_and_a_value(self):
        self.assertEqual(create_payload("team.review", {"a": 1}), {"key": "team.review", "value": {"a": 1}})
        self.assertEqual(create_payload("flag", None), {"key": "flag", "value": None})

    def test_a_change_is_the_next_version_and_the_message_only_when_there_is_one(self):
        self.assertEqual(update_payload("k", [1], 4), {"key": "k", "value": [1], "version": {"number": 4}})
        self.assertEqual(update_payload("k", [1], 4, "Reviewed"), {"key": "k", "value": [1], "version": {"number": 4, "message": "Reviewed"}})
        self.assertEqual(update_payload("k", [1], 4, ""), {"key": "k", "value": [1], "version": {"number": 4}})


class StandInsAreDocumentedTest(unittest.TestCase):
    """The guide and the reference name every marker that `property-set` refuses, and the mark of a cut value, from the lists that refuse them."""

    def documents(self):
        root = Path(__file__).resolve().parents[2]
        guide = (root / "docs" / "how-to" / "tasks-properties-and-templates.md").read_text(encoding="utf-8")
        reference = (root / "docs" / "reference" / "json-output.md").read_text(encoding="utf-8")
        section = reference.split("### `conflu property-set ID --json`")[1].split("<!-- json:properties -->")[0]
        return {"the guide": guide, "the reference of property-set": section}

    def test_every_marker_that_is_refused_and_the_mark_of_a_cut_are_named(self):
        for name, text in self.documents().items():
            for mark in (*STAND_INS, CUT_MARKER, BLANKED):
                with self.subTest(document=name, mark=mark):
                    self.assertIn(f"`{mark}`", text)

    def test_no_sentence_counts_the_markers_and_gets_the_number_wrong(self):
        for name, text in self.documents().items():
            with self.subTest(document=name):
                self.assertNotRegex(text, r"(?i)\b(?:four|five|six|seven|eight|\d+) (?:stand-ins|markers)\b")

    def test_the_way_to_read_a_value_whole_and_real_is_named_in_both(self):
        for name, text in self.documents().items():
            with self.subTest(document=name):
                self.assertIn("conflu properties ID --key KEY --with-users --max-chars 0 --json", text)


if __name__ == "__main__":
    unittest.main()
