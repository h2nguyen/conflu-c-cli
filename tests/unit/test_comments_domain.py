"""The rules for comments that need no Confluence: ids, the pseudonym of an author, which comments `--since` and `--last` choose, and what a change refuses."""
import hashlib
import hmac
import unittest
from datetime import datetime, timedelta, timezone

from conflu_c_cli.domain.comments import (
    RESOLUTIONS,
    author_ref,
    check_expected_version,
    describe_change,
    edit_payload,
    ensure_comment_unchanged_since,
    ensure_comment_version,
    markers_added,
    parse_comment_id,
    parse_since,
    same_text,
    select_comments,
)
from conflu_c_cli.domain.errors import ConflictError, UsageError, ValidationError
from conflu_c_cli.domain.model import Comment

ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"
OTHER = "5b10ac8d82e05b22cc7d4ef6"
SITE = "https://example.atlassian.net/wiki"
NOW = datetime(2026, 10, 15, 8, 0, 0, tzinfo=timezone.utc)


def comment(identifier: str, updated: str, **fields) -> Comment:
    return Comment(identifier, fields.pop("kind", "footer"), updated, fields.pop("body", "<p>x</p>"), **fields)


class CommentIdTest(unittest.TestCase):
    def test_a_number_is_an_id_and_the_blanks_around_it_are_not_part_of_it(self):
        self.assertEqual(parse_comment_id("4001"), "4001")
        self.assertEqual(parse_comment_id("  4001 \n"), "4001")
        self.assertEqual(parse_comment_id("9" * 19), "9" * 19)

    def test_nothing_else_is_an_id_and_the_message_stays_short(self):
        hostile = (
            "", "   ", "abc", "-1", "+1", "1.5", "0x10", "4001 4002", "4001,4002", "4001/../x", "4001?x=1", "4001#a", "4001\n4002", "att5001",
            "١٢٣٤",  # the digits of another script, which str.isdigit() accepts
            "4" * 20, "../4001", "4001%2F",
        )
        for text in hostile:
            with self.subTest(text=text):
                with self.assertRaises(ValidationError) as caught:
                    parse_comment_id(text)
                self.assertIn("A comment id is a number", caught.exception.hint)
        with self.assertRaises(ValidationError) as caught:
            parse_comment_id("x" * 5000)
        self.assertLess(len(caught.exception.message), 100)
        with self.assertRaises(ValidationError):
            parse_comment_id(None)  # type: ignore[arg-type]

    def test_an_empty_value_names_the_option_that_carried_it_and_says_to_leave_it_out(self):
        for text in ("", "   ", "\n", None):
            with self.subTest(text=text):
                with self.assertRaises(ValidationError) as caught:
                    parse_comment_id(text, "--reply-to")  # type: ignore[arg-type]
                self.assertEqual(caught.exception.message, "--reply-to is empty: it needs the id of a comment.")
                self.assertIn("A comment id is a number", caught.exception.hint)
                self.assertIn("Leave --reply-to out", caught.exception.hint)

    def test_a_value_that_is_no_number_names_the_option_too_and_the_message_stays_short(self):
        with self.assertRaises(ValidationError) as caught:
            parse_comment_id("abc", "--get")
        self.assertEqual(caught.exception.message, "Invalid comment id for --get: abc")
        self.assertNotIn("Leave", caught.exception.hint)
        with self.assertRaises(ValidationError) as caught:
            parse_comment_id("x" * 5000, "--edit")
        self.assertLess(len(caught.exception.message), 100)
        self.assertEqual(parse_comment_id(" 4001 ", "--get"), "4001")


class AuthorRefTest(unittest.TestCase):
    def test_it_is_a_keyed_hash_over_the_site_and_the_account_and_nothing_else(self):
        message = f"conflu-c-cli authorRef 1\n{SITE}\n{ACCOUNT}".encode()
        expected = "a-" + hmac.new(b"secret-token", message, hashlib.sha256).hexdigest()[:8]
        self.assertEqual(author_ref("secret-token", SITE, ACCOUNT), expected)

    def test_it_has_the_form_a_dash_and_eight_hexadecimal_digits(self):
        for account in (ACCOUNT, OTHER, "712020:0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"):
            self.assertRegex(author_ref("secret-token", SITE, account), r"^a-[0-9a-f]{8}$")

    def test_the_same_author_gives_the_same_text_and_another_author_another(self):
        first = author_ref("secret-token", SITE, ACCOUNT)
        self.assertEqual(first, author_ref("secret-token", SITE, ACCOUNT))
        self.assertEqual(first, author_ref("secret-token", SITE, f"  {ACCOUNT}\n"))
        self.assertNotEqual(first, author_ref("secret-token", SITE, OTHER))

    def test_another_token_gives_another_text_so_nobody_without_the_token_can_compute_one(self):
        self.assertNotEqual(author_ref("secret-token", SITE, ACCOUNT), author_ref("another-token", SITE, ACCOUNT))
        unkeyed = "a-" + hashlib.sha256(f"conflu-c-cli authorRef 1\n{SITE}\n{ACCOUNT}".encode()).hexdigest()[:8]
        self.assertNotEqual(author_ref("secret-token", SITE, ACCOUNT), unkeyed)

    def test_another_site_gives_another_text_and_the_way_the_address_is_written_does_not_matter(self):
        first = author_ref("secret-token", SITE, ACCOUNT)
        self.assertNotEqual(first, author_ref("secret-token", "https://wiki.example.org/wiki", ACCOUNT))
        self.assertEqual(first, author_ref("secret-token", SITE + "/", ACCOUNT))
        self.assertEqual(first, author_ref("secret-token", SITE.upper().replace("HTTPS", "https"), ACCOUNT))

    def test_without_a_key_or_without_an_account_there_is_none_and_never_an_unkeyed_hash(self):
        self.assertIsNone(author_ref("", SITE, ACCOUNT))
        self.assertIsNone(author_ref(None, SITE, ACCOUNT))  # type: ignore[arg-type]
        self.assertIsNone(author_ref("secret-token", SITE, ""))
        self.assertIsNone(author_ref("secret-token", SITE, "   "))

    def test_the_text_holds_nothing_of_the_account_or_the_token(self):
        text = author_ref("secret-token", SITE, ACCOUNT)
        self.assertNotIn(ACCOUNT[:6], text)
        self.assertNotIn("secret", text)


class SinceTest(unittest.TestCase):
    def test_a_time_ago_counts_back_from_now(self):
        for text, delta in (
            ("2d", timedelta(days=2)), ("12h", timedelta(hours=12)), ("1w", timedelta(weeks=1)), ("30m", timedelta(minutes=30)),
            ("45s", timedelta(seconds=45)), ("1.5h", timedelta(hours=1.5)), (" 2D ", timedelta(days=2)), ("0d", timedelta(0)),
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_since(text, NOW), NOW - delta)

    def test_a_date_or_a_time_without_an_offset_counts_as_utc(self):
        self.assertEqual(parse_since("2026-10-01", NOW), datetime(2026, 10, 1, tzinfo=timezone.utc))
        self.assertEqual(parse_since("2026-10-01T08:30:00", NOW), datetime(2026, 10, 1, 8, 30, tzinfo=timezone.utc))
        self.assertEqual(parse_since("2026-10-01T08:30:00Z", NOW), datetime(2026, 10, 1, 8, 30, tzinfo=timezone.utc))

    def test_an_offset_is_honoured_in_every_spelling(self):
        expected = datetime(2026, 10, 1, 6, 30, tzinfo=timezone.utc)
        for text in ("2026-10-01T08:30:00+02:00", "2026-10-01T08:30:00+0200", "2026-10-01T08:30:00.000+02:00"):
            with self.subTest(text=text):
                self.assertEqual(parse_since(text, NOW), expected)

    def test_a_value_that_is_no_time_is_a_usage_error_with_the_forms_that_work(self):
        for text in ("", "   ", "yesterday", "2x", "d", "-2d", "12", "2026-13-45", "2026-10-01T25:00:00", "2d 3h", "1 week", "999999999w", "0x10", "2d;ls"):
            with self.subTest(text=text):
                with self.assertRaises(UsageError) as caught:
                    parse_since(text, NOW)
                self.assertEqual(caught.exception.exit_code, 2)
                self.assertIn("2d, 12h, 1w", caught.exception.hint)
                self.assertIn("Not a time for --since", caught.exception.message)

    def test_a_very_long_value_does_not_fill_the_message(self):
        with self.assertRaises(UsageError) as caught:
            parse_since("x" * 5000, NOW)
        self.assertLess(len(caught.exception.message), 100)


class SelectTest(unittest.TestCase):
    def setUp(self):
        self.comments = [
            comment("1", "2026-10-01T08:00:00.000Z"),
            comment("2", "2026-10-14T08:00:00.000Z"),
            comment("3", "2026-10-10T08:00:00.000Z"),
            comment("4", "2026-10-15T07:00:00.000Z"),
            comment("5", "not a time"),
        ]

    def ids(self, **options):
        return [item.id for item in select_comments(self.comments, **options)]

    def test_without_options_every_comment_stays_in_its_place(self):
        self.assertEqual(self.ids(), ["1", "2", "3", "4", "5"])

    def test_since_keeps_the_comments_saved_at_or_after_it_and_those_without_a_readable_time_go(self):
        self.assertEqual(self.ids(since=NOW - timedelta(days=2)), ["2", "4"])
        self.assertEqual(self.ids(since=datetime(2026, 10, 14, 8, 0, tzinfo=timezone.utc)), ["2", "4"])  # at the moment itself
        self.assertEqual(self.ids(since=datetime(2026, 10, 14, 8, 0, 1, tzinfo=timezone.utc)), ["4"])
        self.assertEqual(self.ids(since=NOW + timedelta(days=1)), [])

    def test_last_keeps_the_newest_and_leaves_them_in_the_order_they_were_given(self):
        self.assertEqual(self.ids(last=2), ["2", "4"])
        self.assertEqual(self.ids(last=1), ["4"])
        self.assertEqual(self.ids(last=3), ["2", "3", "4"])
        self.assertEqual(self.ids(last=50), ["1", "2", "3", "4", "5"])  # more than there are

    def test_the_time_of_the_comment_is_when_it_was_saved_so_an_edit_makes_it_recent(self):
        self.assertEqual(self.ids(last=1), ["4"])
        self.comments[0] = comment("1", "2026-10-15T07:59:00.000Z", version=2)  # an old comment, edited a minute ago
        self.assertEqual(self.ids(last=1), ["1"])

    def test_last_looks_at_what_since_let_through(self):
        self.assertEqual(self.ids(since=NOW - timedelta(days=6), last=1), ["4"])
        self.assertEqual(self.ids(since=NOW - timedelta(days=4), last=3), ["2", "4"])

    def test_a_time_with_an_offset_is_compared_as_the_moment_it_is(self):
        zoned = [comment("a", "2026-10-15T09:00:00.000+02:00"), comment("b", "2026-10-15T07:30:00.000Z")]
        self.assertEqual([item.id for item in select_comments(zoned, last=1)], ["b"])  # 07:00 UTC against 07:30 UTC


class TextTest(unittest.TestCase):
    def test_the_same_text_apart_from_line_ends_and_the_blanks_around_it(self):
        self.assertTrue(same_text("<p>a</p>\r\n", " <p>a</p>"))
        self.assertTrue(same_text("<p>a</p>\n<p>b</p>", "<p>a</p>\r\n<p>b</p>"))
        self.assertFalse(same_text("<p>a</p>", "<p>b</p>"))
        self.assertFalse(same_text("<p>a b</p>", "<p>a  b</p>"))

    def test_a_stand_in_of_a_reading_is_found_only_when_the_comment_does_not_hold_it_already(self):
        self.assertEqual(markers_added("<p>Write to alex@example.com</p>", "<p>Write to [email]</p>"), ["[email]"])
        self.assertEqual(markers_added("<p>a</p>", "<p>see [personal link] and [email]</p>"), ["[email]", "[personal link]"])
        self.assertEqual(markers_added("<p>It says [email] on purpose</p>", "<p>It says [email] still</p>"), [])
        self.assertEqual(markers_added("<p>a</p>", "<p>Notes [draft] and e-mail</p>"), [])

    def test_the_change_is_a_unified_diff_of_the_two_texts(self):
        diff = describe_change("One\n\nTwo\n\nThree", "One\n\nTwo changed\n\nThree")
        self.assertEqual(diff.splitlines()[:2], ["--- current", "+++ new"])
        self.assertIn("-Two", diff)
        self.assertIn("+Two changed", diff)
        self.assertNotIn("\r", describe_change("a\r\nb", "a\r\nc"))

    def test_the_same_text_has_no_diff(self):
        self.assertEqual(describe_change("a\n\nb", "a\r\n\r\nb\n"), "")


class GuardTest(unittest.TestCase):
    def test_a_comment_saved_after_the_time_is_a_conflict_with_the_facts_in_its_details(self):
        saved = comment("4001", "2026-10-15T08:30:00.000Z")
        with self.assertRaises(ConflictError) as caught:
            ensure_comment_unchanged_since("2002", saved, datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc))
        error = caught.exception
        self.assertEqual(error.exit_code, 3)
        self.assertEqual(error.details, {"pageId": "2002", "commentId": "4001", "updated": "2026-10-15T08:30:00+00:00", "since": "2026-10-15T08:00:00+00:00"})
        self.assertIn("conflu comment 2002 --get 4001", error.hint)

    def test_a_comment_saved_at_or_before_the_time_passes(self):
        saved = comment("4001", "2026-10-15T08:00:00.000Z")
        ensure_comment_unchanged_since("2002", saved, datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc))
        ensure_comment_unchanged_since("2002", saved, datetime(2026, 10, 16, tzinfo=timezone.utc))

    def test_a_comment_without_a_readable_time_cannot_be_judged_and_says_so(self):
        for updated in ("", "yesterday"):
            with self.subTest(updated=updated):
                with self.assertRaises(ValidationError) as caught:
                    ensure_comment_unchanged_since("2002", comment("4001", updated), datetime(2026, 10, 16, tzinfo=timezone.utc))
                self.assertIn("cannot be checked", caught.exception.message)


class VersionGuardTest(unittest.TestCase):
    def test_a_comment_at_another_version_is_a_conflict_with_the_facts_in_its_details(self):
        with self.assertRaises(ConflictError) as caught:
            ensure_comment_version("2002", comment("4001", "2026-10-15T08:30:00.000Z", version=3), 2)
        error = caught.exception
        self.assertEqual(error.exit_code, 3)
        self.assertEqual(error.message, "Comment 4001 of page 2002 is at version 3, not 2.")
        self.assertEqual(error.details, {"pageId": "2002", "commentId": "4001", "version": 3, "expected": 2})
        self.assertIn("conflu comment 2002 --get 4001", error.hint)

    def test_a_comment_at_the_version_passes(self):
        ensure_comment_version("2002", comment("4001", "2026-10-15T08:30:00.000Z", version=3), 3)

    def test_a_version_below_one_is_a_usage_error_and_nothing_or_a_real_version_is_not(self):
        check_expected_version(None)
        check_expected_version(1)
        check_expected_version(40)
        for number in (0, -1, -100):
            with self.subTest(number=number):
                with self.assertRaises(UsageError) as caught:
                    check_expected_version(number)
                self.assertEqual(caught.exception.exit_code, 2)
                self.assertIn("--get", caught.exception.hint)


class PayloadTest(unittest.TestCase):
    def test_a_footer_comment_sends_the_next_version_and_the_text(self):
        self.assertEqual(edit_payload(2, "<p>x</p>"), {"version": {"number": 2}, "body": {"representation": "storage", "value": "<p>x</p>"}})

    def test_an_inline_comment_always_sends_its_state_so_that_a_change_of_the_text_keeps_it(self):
        self.assertEqual(edit_payload(3, "<p>x</p>", resolved=False)["resolved"], False)
        self.assertEqual(edit_payload(3, "<p>x</p>", resolved=True)["resolved"], True)

    def test_the_states_are_the_four_that_confluence_names(self):
        self.assertEqual(RESOLUTIONS, ("open", "resolved", "reopened", "dangling"))


if __name__ == "__main__":
    unittest.main()
