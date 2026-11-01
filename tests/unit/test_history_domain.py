"""Earlier versions of a page in the domain: which version is meant, the diff of two texts, and the restore request."""
import unittest

from conflu_c_cli.domain.errors import UsageError
from conflu_c_cli.domain.history import (
    Difference,
    check_context,
    check_version_number,
    compare,
    cut_lines,
    parse_target,
    restore_payload,
)


class VersionNumberTest(unittest.TestCase):
    def test_a_version_number_is_one_or_more(self):
        self.assertEqual(check_version_number(1), 1)
        self.assertEqual(check_version_number(120), 120)
        for number in (0, -3, True, 2.5, "2", None):
            with self.subTest(number=number):
                with self.assertRaises(UsageError) as caught:
                    check_version_number(number)
                self.assertIn("conflu versions PAGE", caught.exception.hint)

    def test_the_message_names_the_option_that_was_wrong(self):
        with self.assertRaises(UsageError) as caught:
            check_version_number(0, "--from")
        self.assertIn("--from", caught.exception.message)

    def test_the_target_is_a_number_or_current(self):
        for text in (None, "current", "CURRENT", " Current "):
            with self.subTest(text=text):
                self.assertIsNone(parse_target(text))
        self.assertEqual(parse_target("4"), 4)
        self.assertEqual(parse_target(" 12 "), 12)

    def test_an_empty_target_is_a_mistake_and_not_the_same_as_none_given(self):
        for text in ("", "   "):
            with self.subTest(text=text):
                with self.assertRaises(UsageError) as caught:
                    parse_target(text)
                self.assertIn("--to", caught.exception.message)

    def test_a_target_that_is_neither_is_a_usage_error(self):
        for text in ("latest", "0", "-1", "2.5", "1e3", "\u00b2", "\u0663", "1 2"):
            with self.subTest(text=text):
                with self.assertRaises(UsageError) as caught:
                    parse_target(text)
                self.assertIn("--to", caught.exception.message)

    def test_the_context_is_a_small_number_of_lines(self):
        self.assertEqual((check_context(0), check_context(3), check_context(1000)), (0, 3, 1000))
        for context in (-1, 1001):
            with self.assertRaises(UsageError):
                check_context(context)


class RestorePayloadTest(unittest.TestCase):
    def test_the_request_names_the_version_and_holds_no_content(self):
        payload = restore_payload(2, "Restored version 2")
        self.assertEqual(payload, {"operationKey": "restore", "params": {"versionNumber": 2, "message": "Restored version 2", "restoreTitle": False}})
        self.assertEqual(restore_payload(2, "m", True)["params"]["restoreTitle"], True)
        self.assertNotIn("body", payload)


class CutLinesTest(unittest.TestCase):
    def test_a_text_that_fits_is_left_alone(self):
        self.assertEqual(cut_lines("a\nb", 10), ("a\nb", False))
        self.assertEqual(cut_lines("a\nb", 0), ("a\nb", False))
        self.assertEqual(cut_lines("a\nb", 3), ("a\nb", False))

    def test_a_longer_text_is_cut_after_the_last_whole_line_that_fits(self):
        self.assertEqual(cut_lines("aaa\nbbb\nccc", 8), ("aaa\nbbb", True))
        self.assertEqual(cut_lines("aaa\nbbb\nccc", 7), ("aaa\nbbb", True))
        self.assertEqual(cut_lines("aaa\nbbb\nccc", 6), ("aaa", True))

    def test_a_first_line_that_is_longer_is_cut_in_the_line(self):
        self.assertEqual(cut_lines("abcdefghij\nx", 4), ("abcd", True))


class CompareTest(unittest.TestCase):
    def test_equal_texts_have_no_diff(self):
        difference = compare("a\nb\n", "a\nb\n")
        self.assertEqual(difference, Difference("", 0, 0))
        self.assertTrue(difference.identical)

    def test_the_diff_names_both_sides_with_their_dates_and_counts_lines(self):
        difference = compare("one\ntwo\nthree", "one\n2\nthree\nfour", old_label="version 1", new_label="version 2 (current)", old_date="2026-10-01", new_date="2026-10-02")
        self.assertEqual(difference.text.splitlines()[:2], ["--- version 1\t2026-10-01", "+++ version 2 (current)\t2026-10-02"])
        self.assertIn("-two", difference.text)
        self.assertIn("+2", difference.text)
        self.assertIn("+four", difference.text)
        self.assertEqual((difference.added, difference.removed, difference.identical, difference.truncated), (2, 1, False, False))

    def test_a_line_that_looks_like_a_header_is_still_a_line(self):
        difference = compare("--- a rule\nkeep", "+++ a heading\nkeep")
        self.assertEqual((difference.added, difference.removed), (1, 1))

    def test_context_is_the_number_of_unchanged_lines_around_a_change(self):
        old = "\n".join(str(number) for number in range(1, 21))
        new = old.replace("10", "ten")
        self.assertEqual(sum(1 for line in compare(old, new, context=0).text.splitlines() if line.startswith(" ")), 0)
        self.assertEqual(sum(1 for line in compare(old, new, context=1).text.splitlines() if line.startswith(" ")), 2)
        self.assertEqual(sum(1 for line in compare(old, new).text.splitlines() if line.startswith(" ")), 6)

    def test_a_cut_diff_says_how_long_the_whole_one_is(self):
        old = "\n".join(f"line {number}" for number in range(30))
        new = "\n".join(f"LINE {number}" for number in range(30))
        whole = compare(old, new)
        cut = compare(old, new, max_chars=100)
        self.assertTrue(cut.truncated)
        self.assertLessEqual(len(cut.text), 100)
        self.assertEqual(cut.total_chars, len(whole.text))
        self.assertEqual((cut.added, cut.removed), (whole.added, whole.removed))  # the counts are those of the whole diff
        self.assertTrue(whole.text.startswith(cut.text))
        self.assertEqual(whole.total_chars, 0)

    def test_the_text_is_split_into_lines_whatever_the_line_end(self):
        self.assertTrue(compare("a\r\nb", "a\nb").identical)


if __name__ == "__main__":
    unittest.main()
