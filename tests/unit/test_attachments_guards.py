"""The guards of `attach`: the bytes that hold the token, wherever a piece ends, and the conflict guards of a file that becomes a new version."""
import base64
import unittest

from conflu_c_cli.domain.attachguards import (
    MIN_SECRET,
    check_replaced_version,
    check_unchanged_since,
    holds_secret,
    secret_needles,
)
from conflu_c_cli.domain.errors import ConflictError, ValidationError
from conflu_c_cli.domain.model import Attachment

TOKEN = "ATATT" + "-example-token_0123456789AB12"  # in two pieces: no literal in this file looks like the token of a real account
EMAIL = "alex@example.com"


def pieces(data: bytes, size: int):
    return [data[start : start + size] for start in range(0, len(data), size)]


class NeedlesTest(unittest.TestCase):
    def test_the_token_is_looked_for_as_it_is_and_as_the_header_that_carries_it_in_every_encoding_a_file_may_have(self):
        needles = secret_needles(TOKEN, EMAIL)
        header = base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
        for text in (TOKEN, header):
            for encoding in ("utf-8", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"):
                self.assertIn(text.encode(encoding), needles, (text[:6], encoding))
        self.assertEqual(len(needles), 10)  # the ANSI bytes of a token of ASCII characters are the UTF-8 bytes

    def test_a_token_that_is_too_short_to_be_one_is_no_needle(self):
        self.assertEqual(secret_needles("x" * (MIN_SECRET - 1), EMAIL), ())
        self.assertEqual(secret_needles("", EMAIL), ())
        self.assertNotEqual(secret_needles("x" * MIN_SECRET, EMAIL), ())

    def test_without_an_address_the_header_is_the_one_of_a_token_alone(self):
        needles = secret_needles(TOKEN)
        self.assertIn(base64.b64encode(f":{TOKEN}".encode()), needles)


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.needles = secret_needles(TOKEN, EMAIL)
        self.header = base64.b64encode(f"{EMAIL}:{TOKEN}".encode())

    def test_every_form_of_the_token_is_found(self):
        forms = {
            "as it is": f"CONFLUENCE_API_TOKEN={TOKEN}\n".encode(),
            "utf-16 with a mark": f"CONFLUENCE_API_TOKEN={TOKEN}\r\n".encode("utf-16"),
            "utf-16 without a mark": f"token {TOKEN}".encode("utf-16-le"),
            "utf-16 big endian": f"token {TOKEN}".encode("utf-16-be"),
            "a header of a request": b"GET /wiki/api/v2/pages HTTP/1.1\r\nAuthorization: Basic " + self.header + b"\r\n",
            "a header in utf-16": ("Authorization: Basic " + self.header.decode()).encode("utf-16-le"),
        }
        for label, data in forms.items():
            with self.subTest(label):
                self.assertTrue(holds_secret([data], self.needles))

    def test_a_file_without_it_is_not_refused(self):
        for data in (b"", b"A release plan without secrets\n", TOKEN[:-1].encode(), TOKEN[1:].encode(), TOKEN[:7].encode() * 100):
            with self.subTest(data=data[:8]):
                self.assertFalse(holds_secret([data], self.needles))
        self.assertFalse(holds_secret([], self.needles))
        self.assertFalse(holds_secret([TOKEN.encode()], ()))

    def test_it_is_found_wherever_a_piece_ends(self):
        for form in (TOKEN.encode(), TOKEN.encode("utf-16-le"), self.header):
            data = b"x" * 37 + form + b"y" * 41
            for size in (1, 2, 3, 5, 7, 16, len(form) - 1, len(form), len(form) + 1, 64, len(data)):
                with self.subTest(form=form[:6], size=size):
                    self.assertTrue(holds_secret(pieces(data, size), self.needles))

    def test_what_is_not_there_is_not_made_by_the_joining_of_pieces(self):
        data = (b"x" * 40 + TOKEN.encode()[:-1] + b"?" + b"y" * 40)
        for size in (1, 3, 8, 50):
            self.assertFalse(holds_secret(pieces(data, size), self.needles), size)

    def test_a_piece_may_be_a_generator_and_is_read_once(self):
        seen = []
        data = b"aaaa" + TOKEN.encode() + b"b" * 30

        def generator():
            for piece in pieces(data, 6):
                seen.append(piece)
                yield piece

        self.assertTrue(holds_secret(generator(), self.needles))
        self.assertLess(len(b"".join(seen)), len(data))  # it stops as soon as it has found it


class ConflictGuardsTest(unittest.TestCase):
    def item(self, version=3, updated="2026-10-09T14:00:00.000Z", created="2026-10-05T09:00:00.000Z"):
        return Attachment("att5101", "plan.txt", "text/plain", 59, created, version, "2004", updated=updated)

    def test_the_version_that_was_read_is_the_version_that_is_there(self):
        check_replaced_version(self.item(3), "plan.txt", 3)
        check_replaced_version(None, "report.txt", 0)  # a file that is new, and is expected to be
        with self.assertRaises(ConflictError) as caught:
            check_replaced_version(self.item(4), "plan.txt", 3)
        self.assertEqual(caught.exception.exit_code, 3)
        self.assertIn("is at version 4, not 3", caught.exception.message)
        self.assertEqual(caught.exception.details, {"attachmentId": "att5101", "name": "plan.txt", "version": 4, "expected": 3})

    def test_zero_says_that_the_file_must_be_new(self):
        with self.assertRaises(ConflictError) as caught:
            check_replaced_version(self.item(3), "plan.txt", 0)
        self.assertIn("has a file of that name already", caught.exception.message)
        self.assertNotIn("not 0", caught.exception.message)

    def test_an_attachment_that_is_not_there_cannot_be_at_a_version(self):
        with self.assertRaises(ConflictError) as caught:
            check_replaced_version(None, "plan.txt", 2)
        self.assertIn("no attachment named plan.txt", caught.exception.message)
        self.assertEqual(caught.exception.details["version"], 0)

    def test_a_file_that_was_saved_after_the_time_is_a_conflict_and_one_that_was_not_is_not(self):
        check_unchanged_since(self.item(), "plan.txt", "2026-10-09T14:00:00Z")  # the very moment is no change
        check_unchanged_since(self.item(), "plan.txt", "2026-10-10T00:00:00+0200")
        check_unchanged_since(None, "new.txt", "2020-01-01T00:00:00Z")  # a file that is new replaces nothing
        with self.assertRaises(ConflictError) as caught:
            check_unchanged_since(self.item(), "plan.txt", "2026-10-09T13:59:59Z")
        self.assertEqual(caught.exception.exit_code, 3)
        self.assertEqual(caught.exception.details["since"], "2026-10-09T13:59:59+00:00")
        self.assertIn("changed in Confluence at 2026-10-09T14:00:00+00:00", caught.exception.message)

    def test_a_time_with_an_offset_is_compared_as_the_moment_it_is(self):
        with self.assertRaises(ConflictError):
            check_unchanged_since(self.item(), "plan.txt", "2026-10-09T15:59:00+02:00")  # 13:59 UTC
        check_unchanged_since(self.item(), "plan.txt", "2026-10-09T16:00:00+02:00")  # 14:00 UTC

    def test_the_time_of_the_first_upload_is_used_when_the_time_of_the_version_is_not_known(self):
        with self.assertRaises(ConflictError):
            check_unchanged_since(self.item(updated=""), "plan.txt", "2026-10-01T00:00:00Z")
        check_unchanged_since(self.item(updated=""), "plan.txt", "2026-10-06T00:00:00Z")
        with self.assertRaises(ValidationError) as caught:
            check_unchanged_since(self.item(updated="", created=""), "plan.txt", "2026-10-06T00:00:00Z")
        self.assertIn("--if-version", caught.exception.hint)

    def test_a_time_that_cannot_be_read_is_refused_whatever_the_attachment(self):
        for existing in (self.item(), None):
            with self.assertRaises(ValidationError):
                check_unchanged_since(existing, "plan.txt", "yesterday")

    def test_an_empty_time_is_an_error_that_names_the_option_and_is_no_guard_that_lets_everything_through(self):
        for existing in (self.item(), None):
            for value in ("", "  "):
                with self.assertRaises(ValidationError) as caught:
                    check_unchanged_since(existing, "plan.txt", value)
                self.assertIn("--if-unchanged-since", caught.exception.message)

    def test_a_name_in_a_message_cannot_move_the_cursor(self):
        with self.assertRaises(ConflictError) as caught:
            check_replaced_version(self.item(4), "\x1b[2Jplan\u202e.txt", 3)
        self.assertNotIn("\x1b", caught.exception.message)
        self.assertNotIn("\u202e", caught.exception.message)


if __name__ == "__main__":
    unittest.main()
