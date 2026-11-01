"""Blog posts in the domain: the request bodies, the title rule, the guards of a change and what a blog post's address must stay."""
import unittest

from conflu_c_cli.domain.blogposts import (
    BlogpostDraft,
    create_blogpost_payload,
    ensure_blogpost_unchanged_since,
    ensure_blogpost_version,
    update_blogpost_payload,
    validate_blogpost_title,
)
from conflu_c_cli.domain.content import parse_content_id
from conflu_c_cli.domain.errors import ConflictError, ValidationError
from conflu_c_cli.domain.privacy import redact_address

WIKI = "https://example.atlassian.net/wiki"


class AddressTest(unittest.TestCase):
    """The commands print an address through `redact_address` (the tests of its rules are in test_privacy_of_writes.py): what is left must still name the blog post."""

    def test_an_address_without_a_person_in_it_is_as_it_is(self):
        for url in (f"{WIKI}/spaces/ENG/blog/2026/10/15/7101/Release+2026.10+is+out", f"{WIKI}/spaces/ENG/blog/2026/10/15/7101", ""):
            with self.subTest(url=url):
                self.assertEqual(redact_address(url), url)

    def test_a_title_that_holds_an_e_mail_address_goes_from_the_address_of_a_blog_post_and_the_id_stays(self):
        shown = redact_address(f"{WIKI}/spaces/ENG/blog/2026/10/15/7101/Mail+alex%40example.com")
        self.assertEqual(shown, f"{WIKI}/spaces/ENG/blog/2026/10/15/7101")
        self.assertEqual(parse_content_id(shown), "7101")


class TitleTest(unittest.TestCase):
    def test_a_title_is_trimmed(self):
        self.assertEqual(validate_blogpost_title("  Release 2026.10 is out \n"), "Release 2026.10 is out")

    def test_an_empty_title_is_refused_and_says_blog_post(self):
        for title in ("", "   ", None):
            with self.subTest(title=title):
                with self.assertRaises(ValidationError) as caught:
                    validate_blogpost_title(title)
                self.assertIn("blog post title is empty", caught.exception.message)
                self.assertIn("--title", caught.exception.hint)

    def test_a_line_break_or_another_control_character_is_refused(self):
        for title in ("two\nlines", "tab\there", "nul\x00", "esc\x1b[31m", "del\x7f"):
            with self.subTest(title=title):
                with self.assertRaises(ValidationError):
                    validate_blogpost_title(title)

    def test_the_longest_title_is_255_characters(self):
        self.assertEqual(len(validate_blogpost_title("x" * 255)), 255)
        with self.assertRaises(ValidationError) as caught:
            validate_blogpost_title("x" * 256)
        self.assertIn("256", caught.exception.message)


class PayloadTest(unittest.TestCase):
    def test_a_creation_names_the_space_the_status_the_title_and_the_body(self):
        self.assertEqual(
            create_blogpost_payload("1001", "Weekly update", "<p>Hi</p>"),
            {"spaceId": "1001", "status": "current", "title": "Weekly update", "body": {"representation": "storage", "value": "<p>Hi</p>"}},
        )

    def test_an_update_names_the_id_the_whole_body_and_the_version_it_becomes(self):
        payload = update_blogpost_payload("7101", "T", "<p>B</p>", 4, "  Added  ")
        self.assertEqual(
            payload,
            {"id": "7101", "status": "current", "title": "T", "body": {"representation": "storage", "value": "<p>B</p>"}, "version": {"number": 4, "message": "Added"}},
        )

    def test_a_blank_message_is_left_out_and_a_draft_stays_a_draft(self):
        payload = update_blogpost_payload("7101", "T", "<p>B</p>", 1, "   ", "draft")
        self.assertEqual((payload["version"], payload["status"]), ({"number": 1}, "draft"))

    def test_a_draft_holds_what_a_blog_post_to_create_holds(self):
        draft = BlogpostDraft(space="ENG", title="T", body="<p>x</p>", labels=["a"])
        self.assertEqual((draft.space, draft.title, draft.body, draft.labels), ("ENG", "T", "<p>x</p>", ["a"]))
        self.assertEqual(BlogpostDraft().labels, [])


class GuardTest(unittest.TestCase):
    def test_the_version_that_was_read_is_the_one_the_blog_post_is_at(self):
        ensure_blogpost_version("7101", 3, 3)
        with self.assertRaises(ConflictError) as caught:
            ensure_blogpost_version("7101", 4, 3)
        error = caught.exception
        self.assertEqual(error.message, "Blog post 7101 is at version 4, not 3.")
        self.assertEqual(error.details, {"blogpostId": "7101", "version": 4, "expected": 3})
        self.assertEqual(error.exit_code, 3)

    def test_a_change_after_the_time_that_was_read_is_a_conflict(self):
        ensure_blogpost_unchanged_since("7101", "2026-10-14T10:00:00.000Z", "2026-10-14T10:00:00Z")
        ensure_blogpost_unchanged_since("7101", "2026-10-14T10:00:00.000Z", "2026-10-15T00:00:00+02:00")
        with self.assertRaises(ConflictError) as caught:
            ensure_blogpost_unchanged_since("7101", "2026-10-14T10:00:00.000Z", "2026-10-13T00:00:00Z")
        self.assertIn("Blog post 7101 changed in Confluence", caught.exception.message)
        self.assertEqual(caught.exception.details["blogpostId"], "7101")
        self.assertNotIn("pageId", caught.exception.details)

    def test_a_time_that_cannot_be_read_is_a_validation_error_that_names_the_option(self):
        for since in ("yesterday", "", " ", None):
            with self.subTest(since=since):
                with self.assertRaises(ValidationError) as caught:
                    ensure_blogpost_unchanged_since("7101", "2026-10-14T10:00:00.000Z", since)
                self.assertIn("--if-unchanged-since", caught.exception.message)
                self.assertIn("Not an ISO 8601 timestamp", caught.exception.message)

    def test_a_draft_that_names_no_space_has_none(self):
        self.assertIsNone(BlogpostDraft().space)
        self.assertEqual(BlogpostDraft(space="").space, "")  # an empty name is kept as it was given: the use case refuses it


if __name__ == "__main__":
    unittest.main()
