"""A segment of a request path that is made of dots is never sent as it is, and a label cannot be made of dots."""
import unittest

from conflu_c_cli.adapters.driven.rest_support import quote
from conflu_c_cli.domain.drafts import normalize_labels
from conflu_c_cli.domain.errors import ValidationError


class QuoteTest(unittest.TestCase):
    def test_a_segment_of_dots_is_percent_encoded(self):
        self.assertEqual((quote(".."), quote("."), quote("...")), ("%2E%2E", "%2E", "%2E%2E%2E"))

    def test_other_segments_are_what_they_were(self):
        for value, expected in (("2002", "2002"), ("a.b", "a.b"), ("v1.2", "v1.2"), ("a/b", "a%2Fb"), ("a b", "a%20b"), ("..a", "..a"), ("", ""), ("~5b10", "~5b10")):
            with self.subTest(value=value):
                self.assertEqual(quote(value), expected)


class LabelTest(unittest.TestCase):
    def test_a_label_of_dots_is_refused(self):
        for label in ("..", ".", "..."):
            with self.subTest(label=label):
                with self.assertRaises(ValidationError):
                    normalize_labels([label])

    def test_a_label_with_dots_in_it_is_fine(self):
        self.assertEqual(normalize_labels(["v1.2", "a..b", ".hidden"]), ["v1.2", "a..b", ".hidden"])


if __name__ == "__main__":
    unittest.main()
