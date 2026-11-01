"""The text that Confluence puts into an error is redacted as every other free text is, and the account id inside a sentence goes too.

The review of the feature areas found it printed as it came: `No user found for alex@example.com (accountId 5b10ac8d82e05b22cc7d4ef5)` was in the
message of a 404, and under the policy that never prints people the e-mail address was replaced and the account id stayed.
"""
import time
import unittest

from conflu_c_cli.domain.errortext import ACCOUNT_MARKER, redact_error_text, redact_error_value

ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"
OLD_ACCOUNT = "712020:3f2c1a9e-4b7d-4c3e-9a1b-2d3e4f5a6b7c"


class AccountIdTest(unittest.TestCase):
    def test_an_account_id_of_24_hexadecimal_digits_is_replaced_wherever_it_stands(self):
        for text, expected in (
            (f"accountId {ACCOUNT}", "accountId [account id]"),
            (ACCOUNT, "[account id]"),
            (f'{{"accountId":"{ACCOUNT}"}}', '{"accountId":"[account id]"}'),
            (f"user={ACCOUNT}&x=1", "user=[account id]&x=1"),
            (f"({ACCOUNT})", "([account id])"),
            (f"'{ACCOUNT}'", "'[account id]'"),
            (f"user_{ACCOUNT}", "user_[account id]"),
            (ACCOUNT.upper(), "[account id]"),
            (f"a {ACCOUNT}, b 5b10ac8d82e05b22cc7d4f33.", "a [account id], b [account id]."),
            (f"{ACCOUNT}\n{ACCOUNT}", "[account id]\n[account id]"),
        ):
            with self.subTest(text=text):
                self.assertEqual(redact_error_text(text), expected)

    def test_the_older_form_is_a_number_a_colon_and_a_uuid(self):
        for text, expected in (
            (f"accountId {OLD_ACCOUNT}", "accountId [account id]"),
            ("557058:3f2c1a9e-4b7d-4c3e-9a1b-2d3e4f5a6b7c", "[account id]"),
            ("70121:3f2c1a9e-4b7d-4c3e-9a1b-2d3e4f5a6b7c", "[account id]"),
            ("1234567:3F2C1A9E-4B7D-4C3E-9A1B-2D3E4F5A6B7C", "[account id]"),
            (f"for {OLD_ACCOUNT}.", "for [account id]."),
            (f"{OLD_ACCOUNT} and {ACCOUNT}", "[account id] and [account id]"),
        ):
            with self.subTest(text=text):
                self.assertEqual(redact_error_text(text), expected)

    def test_what_is_not_an_account_id_stays(self):
        for text in (
            ACCOUNT[:-1],  # 23 digits
            ACCOUNT + "5",  # 25
            ACCOUNT + "a1b2c3d4",  # the first 24 of a longer number: a trace id, not a person
            "5b10ac8d82e05b22cc7d4eg5",  # a letter that is no digit of 16
            f"x{ACCOUNT}",
            f"{ACCOUNT}x",
            "page 123456 in space ENG",
            "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",  # a UUID without the number in front of it
            "12:3f2c1a9e-4b7d-4c3e-9a1b-2d3e4f5a6b7c",  # a number too short
            "12345678:3f2c1a9e-4b7d-4c3e-9a1b-2d3e4f5a6b7c",  # a number too long
            "712020:3f2c1a9e-4b7d-4c3e-9a1b",  # a UUID that is cut
            "",
            "Version conflict",
            "The page was updated by another user.",
        ):
            with self.subTest(text=text):
                self.assertEqual(redact_error_text(text), text)

    def test_e_mail_addresses_and_links_to_people_go_as_in_every_other_text(self):
        text = f"No user found for alex@example.com (accountId {ACCOUNT}), see https://example.atlassian.net/wiki/people/{ACCOUNT}"
        self.assertEqual(redact_error_text(text), "No user found for [email] (accountId [account id]), see [personal link]")
        self.assertEqual(redact_error_text("see /wiki/people/abc"), "see [personal link]")

    def test_the_marker_is_the_one_that_is_documented(self):
        self.assertEqual(ACCOUNT_MARKER, "[account id]")

    def test_it_is_a_text_function_for_whatever_it_is_given(self):
        self.assertEqual(redact_error_text(None), "")
        self.assertEqual(redact_error_text(404), "404")
        self.assertEqual(redact_error_text(redact_error_text(f"{ACCOUNT} {OLD_ACCOUNT}")), "[account id] [account id]")

    def test_no_text_makes_it_take_longer_than_its_own_length(self):
        hostile = (
            "a" * 1_000_000,
            "0123456789abcdef" * 100_000,
            "1234567:" * 150_000,
            "123456:aaaaaaaa-bbbb-" * 60_000,
            ":" * 1_000_000,
            (ACCOUNT[:-1] + "-") * 50_000,
            ("1" * 7 + ":" + "a" * 8 + "-" + "b" * 4 + "-" + "c" * 4 + "-" + "d" * 4 + "-" + "e" * 11 + " ") * 20_000,
            "a@" * 200_000,
            "people/" * 100_000,
        )
        for text in hostile:
            started = time.monotonic()
            redact_error_text(text)
            with self.subTest(size=len(text), head=text[:12]):
                self.assertLess(time.monotonic() - started, 3.0)


class WholeAnswerTest(unittest.TestCase):
    def test_every_string_and_every_key_at_any_depth_is_redacted_and_the_shape_stays(self):
        answer = {
            "message": f"No user found for alex@example.com (accountId {ACCOUNT})",
            "errors": [{"detail": f"{OLD_ACCOUNT} may not see it", "status": 403, "ok": False, "none": None, "ratio": 0.5}, f"see {ACCOUNT}", 7],
            "data": {"authorized": False, "who": {"mail": "alex@example.com"}},
            ACCOUNT: {"alex@example.com": ["x"]},
        }
        self.assertEqual(
            redact_error_value(answer),
            {
                "message": "No user found for [email] (accountId [account id])",
                "errors": [{"detail": "[account id] may not see it", "status": 403, "ok": False, "none": None, "ratio": 0.5}, "see [account id]", 7],
                "data": {"authorized": False, "who": {"mail": "[email]"}},
                "[account id]": {"[email]": ["x"]},
            },
        )

    def test_the_answer_that_was_given_is_not_changed(self):
        answer = {"message": f"{ACCOUNT} alex@example.com", "list": [f"{ACCOUNT}"]}
        redact_error_value(answer)
        self.assertEqual(answer, {"message": f"{ACCOUNT} alex@example.com", "list": [ACCOUNT]})

    def test_what_is_no_text_is_returned_as_it_is(self):
        for value in (None, True, 3, 2.5, [], {}):
            self.assertEqual(redact_error_value(value), value)

    def test_an_answer_nested_deeper_than_the_interpreter_allows_is_for_the_caller_to_answer(self):
        value: object = "x"
        for _ in range(5000):
            value = [value]
        with self.assertRaises(RecursionError):
            redact_error_value(value)


if __name__ == "__main__":
    unittest.main()
