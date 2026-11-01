"""The kinds of content in the tree, and the names that a person gives one."""
import unittest

from conflu_c_cli.domain.content import BLOGPOST, CONTAINERS, FOLDER, KINDS, PAGE, describe, kind_named, parse_content_id
from conflu_c_cli.domain.errors import ValidationError


class KindsTest(unittest.TestCase):
    def test_a_kind_has_a_collection_in_the_v2_api(self):
        self.assertEqual([kind.collection for kind in KINDS], ["pages", "blogposts", "folders", "whiteboards", "databases", "embeds"])
        self.assertEqual(kind_named("folder"), FOLDER)
        self.assertIsNone(kind_named("footer-comment"))
        self.assertNotIn(BLOGPOST, CONTAINERS)  # a blog post holds no page
        self.assertIn(PAGE, CONTAINERS)

    def test_what_content_is_called_in_a_sentence(self):
        self.assertEqual(describe("folder"), "a folder")
        self.assertEqual(describe("embed"), "a smart link")
        self.assertEqual(describe("footer-comment"), "a footer comment")
        self.assertEqual(describe(None), "nothing that this account can see")
        self.assertEqual(describe("hologram"), "content of the type hologram")


class ParseContentIdTest(unittest.TestCase):
    def test_the_number_itself(self):
        self.assertEqual(parse_content_id(" 123456 "), "123456")

    def test_the_address_of_each_kind_as_the_browser_shows_it(self):
        base = "https://example.atlassian.net/wiki/spaces/ENG"
        for address, expected in (
            (f"{base}/pages/123456/Release+notes", "123456"),
            (f"{base}/pages/edit-v2/123456", "123456"),
            (f"{base}/folder/777", "777"),
            (f"{base}/blog/2026/10/15/888/Release+notes", "888"),
            (f"{base}/whiteboard/999?atlOrigin=abc", "999"),
            (f"{base}/database/555#top", "555"),
            (f"{base}/embed/444", "444"),
            ("https://example.atlassian.net/wiki/pages/viewpage.action?pageId=321", "321"),
        ):
            with self.subTest(address=address):
                self.assertEqual(parse_content_id(address), expected)

    def test_what_is_no_id(self):
        for text in ("", "abc", "12 34", "page:ENG/Title", "-5", "1" * 20, "https://example.atlassian.net/wiki/spaces/ENG/overview"):
            with self.subTest(text=text), self.assertRaises(ValidationError):
                parse_content_id(text)

    def test_a_short_link_is_refused_with_the_way_out(self):
        with self.assertRaises(ValidationError) as caught:
            parse_content_id("https://example.atlassian.net/wiki/x/AbCd")
        self.assertIn("cannot be resolved offline", caught.exception.message)


if __name__ == "__main__":
    unittest.main()
