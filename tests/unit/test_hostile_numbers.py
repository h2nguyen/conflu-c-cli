"""A number that `int()` refuses is a mistake of the text that holds it, never an `unexpected ValueError`.

`int()` refuses a text of more than 4,300 digits, and it refuses what `str.isdigit()` accepts and is no decimal digit (`²`, `①`). A list item that begins with
5,000 digits, `--section ①` and `--to` with 5,000 digits were all an `unexpected ValueError` at the end of a run, where the person gets a sentence. The same for
a number in an answer of Confluence that is larger than any number of its API: it cannot be turned into a float to be shown as a size.
"""
import unittest

from conflu_c_cli.adapters.driven.confluence_mapper import attachment_from
from conflu_c_cli.domain.errors import UnavailableError, UsageError, ValidationError
from conflu_c_cli.domain.history import parse_target
from conflu_c_cli.domain.markdown import markdown_to_storage
from conflu_c_cli.domain.sections import extract_section

PAGE = "# Alpha\n\ntext\n\n# Beta\n\nmore\n"


class ListMarkerTest(unittest.TestCase):
    def test_nine_digits_are_a_list_as_they_were(self):
        self.assertEqual(markdown_to_storage("123456789. x"), '<ol start="123456789"><li>x</li></ol>')

    def test_ten_digits_and_thousands_of_them_are_text(self):
        self.assertEqual(markdown_to_storage("1234567890. x"), "<p>1234567890. x</p>")
        text = markdown_to_storage("1" * 5000 + ". x")
        self.assertTrue(text.startswith("<p>1111"))
        self.assertNotIn("<ol", text)

    def test_the_same_inside_a_list_and_in_a_quote(self):
        for source in ("- a\n  " + "1" * 5000 + ". b\n", "> " + "1" * 5000 + ". b\n", "1. a\n" + "2" * 4400 + ". b\n"):
            with self.subTest(source=source[:12]):
                text = markdown_to_storage(source)
                self.assertIn(". b", text)
                self.assertNotIn("<ol start", text)


class SectionTest(unittest.TestCase):
    def test_a_number_still_names_the_heading(self):
        self.assertEqual(extract_section(PAGE, "2")[1].title, "Beta")

    def test_what_is_called_a_digit_and_is_none_names_nothing(self):
        for selector in ("\u2460", "\u00b2", "\u2467"):
            with self.subTest(selector=selector.encode("unicode_escape")), self.assertRaises(ValidationError) as caught:
                extract_section(PAGE, selector)
            self.assertIn("no heading like", caught.exception.message)

    def test_a_number_of_thousands_of_digits_names_nothing(self):
        with self.assertRaises(ValidationError) as caught:
            extract_section(PAGE, "1" * 5000)
        self.assertIn("no heading like", caught.exception.message)


class VersionTest(unittest.TestCase):
    def test_a_version_is_read_as_it_was(self):
        self.assertEqual(parse_target("12"), 12)
        self.assertEqual(parse_target("1" * 9), 111111111)
        self.assertIsNone(parse_target("current"))

    def test_more_digits_than_a_version_has_are_no_version(self):
        for text in ("1" * 10, "1" * 5000, "\u00b2"):
            with self.subTest(length=len(text)), self.assertRaises(UsageError) as caught:
                parse_target(text)
            self.assertIn("--to must be a version number", caught.exception.message)


class AnswerTest(unittest.TestCase):
    def test_a_size_that_no_file_has_is_a_damaged_answer(self):
        base = {"id": "att1", "title": "a.txt", "mediaType": "text/plain", "version": {"number": 1}}
        self.assertEqual(attachment_from({**base, "fileSize": 2**62}).size, 2**62)
        for size in (2**63, 10**400, -(10**400), 1e300):
            with self.subTest(size=str(size)[:12]), self.assertRaises(UnavailableError) as caught:
                attachment_from({**base, "fileSize": size})
            self.assertIn("a file size that is not a number", caught.exception.message)


if __name__ == "__main__":
    unittest.main()
