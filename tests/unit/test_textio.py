"""Decoding the text files that a person, or Windows PowerShell 5.1, wrote."""
import codecs
import unittest

from conflu_c_cli.domain.attachguards import holds_secret, secret_needles
from conflu_c_cli.domain.errors import UsageError, ValidationError
from conflu_c_cli.domain.textio import (
    BODY_LIMIT,
    BYTE_ORDER_MARKS,
    QUERY_LIMIT,
    TEXT_ENCODINGS,
    UNMARKED_ENCODINGS,
    check_length,
    decode_input,
    decode_text,
)

TEXT = "Überschrift — the page about Größe\nSecond line"


class DecodeTextTest(unittest.TestCase):
    def test_utf8_without_and_with_a_byte_order_mark(self):
        self.assertEqual(decode_text(TEXT.encode("utf-8")), TEXT)
        self.assertEqual(decode_text(b"\xef\xbb\xbf" + TEXT.encode("utf-8")), TEXT)

    def test_utf16_as_powershell_writes_it(self):
        self.assertEqual(decode_text(TEXT.encode("utf-16")), TEXT)  # little endian with a byte order mark
        self.assertEqual(decode_text(b"\xfe\xff" + TEXT.encode("utf-16-be")), TEXT)

    def test_utf32(self):
        self.assertEqual(decode_text(TEXT.encode("utf-32")), TEXT)

    def test_utf16_without_a_byte_order_mark(self):
        for encoding in ("utf-16-le", "utf-16-be"):
            with self.subTest(encoding=encoding):
                self.assertEqual(decode_text(TEXT.encode(encoding)), TEXT)
                self.assertEqual(decode_text("a".encode(encoding)), "a")
                self.assertNotIn("\x00", decode_text("# Größe".encode(encoding)))

    def test_text_that_only_looks_a_little_like_utf16_is_not_changed(self):
        for text in ("plain text", "Größe — ünïcode ✓", "x\x00y is no UTF-16, the rest of it is ASCII " * 3):
            with self.subTest(text=text[:12]):
                self.assertEqual(decode_text(text.encode("utf-8")), text)

    def test_ansi_text_that_is_no_utf8(self):
        self.assertEqual(decode_text("Überschrift — fertig".encode("cp1252")), "Überschrift — fertig")

    def test_line_ends_are_left_as_they_are(self):
        self.assertEqual(decode_text(b"one\r\ntwo\rthree\n"), "one\r\ntwo\rthree\n")

    def test_empty(self):
        self.assertEqual(decode_text(b""), "")


class DecodeInputTest(unittest.TestCase):
    def test_every_line_end_is_a_newline_and_no_byte_order_mark_is_left(self):
        for label, data in (
            ("UTF-8", "# One\r\n\r\ntext\r\n".encode("utf-8")),
            ("UTF-8 with a mark", b"\xef\xbb\xbf" + "# One\r\n\r\ntext\r\n".encode("utf-8")),
            ("UTF-16", "# One\r\n\r\ntext\r\n".encode("utf-16")),
            ("UTF-16 without a mark", "# One\r\n\r\ntext\r\n".encode("utf-16-be")),
            ("Windows-1252", "# One\r\n\r\ntext\r\n".encode("cp1252")),
        ):
            with self.subTest(label):
                text = decode_input(data, "input.md")
                self.assertEqual(text, "# One\n\ntext\n")
                self.assertNotIn("\ufeff", text)

    def test_an_old_mac_line_end_is_a_newline_too(self):
        self.assertEqual(decode_input(b"a\rb", "x"), "a\nb")

    def test_bytes_that_hold_a_nul_are_no_text_and_the_error_names_the_source(self):
        picture = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        with self.assertRaises(ValidationError) as caught:
            decode_input(picture, "diagram.png")
        self.assertIn("diagram.png is not text", caught.exception.message)
        self.assertEqual(caught.exception.exit_code, 1)
        with self.assertRaises(ValidationError):
            decode_input(b"text\x00more text\x00", "Standard input")

    def test_utf16_is_not_taken_for_binary(self):
        self.assertEqual(decode_input("plain".encode("utf-16-le"), "x"), "plain")
        self.assertEqual(decode_input("plain".encode("utf-16"), "x"), "plain")

    def test_empty(self):
        self.assertEqual(decode_input(b"", "x"), "")


class CheckLengthTest(unittest.TestCase):
    def test_what_fits_passes_and_one_more_is_a_usage_error_that_names_the_source_and_the_limit(self):
        for length in (0, 1, 9, 10):
            check_length(length, 10, "query.txt")
        with self.assertRaises(UsageError) as caught:
            check_length(11, 10, "query.txt", "query")
        self.assertEqual(caught.exception.exit_code, 2)
        self.assertEqual(caught.exception.message, "query.txt holds more than 10 bytes: a query may hold at most 10 bytes.")
        self.assertTrue(caught.exception.hint)

    def test_the_two_limits_are_a_mebibyte_for_a_query_and_sixteen_for_any_other_text(self):
        self.assertEqual((QUERY_LIMIT, BODY_LIMIT), (1024 * 1024, 16 * 1024 * 1024))
        for limit, mebibytes in ((QUERY_LIMIT, "1 MiB"), (BODY_LIMIT, "16 MiB")):
            with self.subTest(limit=limit):
                check_length(limit, limit, "Standard input")
                with self.assertRaises(UsageError) as caught:
                    check_length(limit + 1, limit, "Standard input")
                self.assertIn(f"{limit:,} bytes ({mebibytes})", caught.exception.message)
                self.assertTrue(caught.exception.message.startswith("Standard input holds more than"))


class EncodingTableTest(unittest.TestCase):
    """What `decode_text` reads is a table (`BYTE_ORDER_MARKS`, `UNMARKED_ENCODINGS`) that the search of a file for the token reads too
    (`attachguards.secret_needles`): the two cannot know different encodings, so a copy of the settings file that an editor or Windows
    PowerShell saved in an encoding that `decode_text` accepts is found, and a new encoding in the one is a new needle for the other."""

    SECRET = "example-secret-0123456789"

    def forms(self):
        text = f"CONFLUENCE_API_TOKEN={self.SECRET}\r\n"
        for mark, codec in BYTE_ORDER_MARKS:
            yield f"{codec} with a mark", mark + text.encode(codec)
        for codec in UNMARKED_ENCODINGS:
            yield f"{codec} without a mark", text.encode(codec)

    def test_every_mark_of_the_table_is_read_as_the_text_that_it_marks(self):
        for mark, codec in BYTE_ORDER_MARKS:
            with self.subTest(codec=codec):
                self.assertEqual(decode_text(mark + TEXT.encode(codec)), TEXT)

    def test_a_mark_that_starts_another_mark_is_asked_after_it(self):
        marks = [mark for mark, _ in BYTE_ORDER_MARKS]
        for index, mark in enumerate(marks):
            for later in marks[index + 1 :]:
                self.assertFalse(later.startswith(mark), (mark, later))

    def test_every_mark_that_the_codecs_module_has_is_in_the_table(self):
        marks = dict(BYTE_ORDER_MARKS)
        found = [name for name in dir(codecs) if name.startswith("BOM_UTF")]
        self.assertIn("BOM_UTF32_LE", found)
        for name in found:
            with self.subTest(name=name):
                self.assertIn(getattr(codecs, name), marks)

    def test_the_table_of_all_encodings_is_what_the_two_lists_hold_once_each(self):
        self.assertEqual(set(TEXT_ENCODINGS), {codec for _, codec in BYTE_ORDER_MARKS} | set(UNMARKED_ENCODINGS))
        self.assertEqual(len(TEXT_ENCODINGS), len(set(TEXT_ENCODINGS)))
        for encoding in ("utf-8", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be", "cp1252"):
            self.assertIn(encoding, TEXT_ENCODINGS)

    def test_a_file_that_decode_text_reads_with_the_secret_in_it_is_found_by_the_search_for_it(self):
        needles = secret_needles(self.SECRET, "alex@example.com")
        forms = list(self.forms())
        self.assertGreaterEqual(len(forms), 9)
        for label, data in forms:
            with self.subTest(label):
                self.assertIn(self.SECRET, decode_text(data))
                self.assertTrue(holds_secret([data], needles))
                self.assertTrue(holds_secret([data[:7], data[7:20], data[20:]], needles))  # also across the end of a piece

    def test_a_secret_with_a_character_that_the_ansi_encoding_has_no_byte_for_is_no_error(self):
        secret = "tökën-✓-0123456789"
        needles = secret_needles(secret)
        for codec in ("utf-8", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"):
            self.assertIn(secret.encode(codec), needles)
        self.assertTrue(holds_secret([secret.encode("utf-16")], needles))


if __name__ == "__main__":
    unittest.main()
