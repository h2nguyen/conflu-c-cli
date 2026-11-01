"""Text files and standard input given to a command: what Windows PowerShell 5.1 writes arrives as the text it holds, never with a byte
order mark in front, and a file that is no text says so."""
import unittest

from tests.support.cli import run_cli
from tests.support.encodings import ENCODINGS, STORAGE, TEXT
from tests.support.fakes import FakeGateway, MemoryConfigStore, MemoryFiles


class InputFilesTest(unittest.TestCase):
    """Every run starts with a new Confluence in memory, so that one encoding cannot change what the next one meets."""

    def run_file(self, *argv, name="input.txt", data=b""):
        self.gateway = FakeGateway()
        files = MemoryFiles()
        files.write_bytes(name, data)
        return run_cli(*argv, gateway=self.gateway, files=files)

    def run_piped(self, *argv, stdin):
        self.gateway = FakeGateway()
        return run_cli(*argv, gateway=self.gateway, stdin=stdin)

    def test_a_comment_from_a_file_has_the_text_of_the_file(self):
        for label, encode in ENCODINGS.items():
            with self.subTest(label):
                result = self.run_file("comment", "2002", "--file", "input.txt", data=encode(TEXT))
                self.assertEqual(result.code, 0, result.err)
                self.assertEqual(self.gateway.called("add_comment")[0][1]["body"]["value"], STORAGE)

    def test_the_body_of_a_new_page_from_a_file_has_the_text_of_the_file(self):
        for label, encode in ENCODINGS.items():
            with self.subTest(label):
                result = self.run_file("create", "--space", "ENG", "--title", "From a file", "--file", "input.txt", data=encode(TEXT))
                self.assertEqual(result.code, 0, result.err)
                payload = self.gateway.called("create_page")[0][1]
                self.assertEqual((payload["title"], payload["body"]["value"]), ("From a file", STORAGE))

    def test_the_new_body_of_a_page_from_a_file_has_the_text_of_the_file(self):
        for label, encode in ENCODINGS.items():
            with self.subTest(label):
                result = self.run_file("update", "2005", "--file", "input.txt", "--dry-run", "--json", data=encode(TEXT))
                self.assertEqual(result.code, 0, result.err)
                self.assertEqual(result.json()["payload"]["body"]["value"], STORAGE)
                result = self.run_file("update", "2005", "--file", "input.txt", data=encode(TEXT))
                self.assertEqual(result.code, 0, result.err)
                self.assertEqual(self.gateway.called("update_page")[0][2]["body"]["value"], STORAGE)

    def test_a_body_in_storage_format_from_a_file_has_no_byte_order_mark_either(self):
        for label, encode in ENCODINGS.items():
            with self.subTest(label):
                result = self.run_file("update", "2005", "--file", "input.txt", "--format", "storage", "--dry-run", "--json", data=encode(STORAGE))
                self.assertEqual(result.code, 0, result.err)
                self.assertEqual(result.json()["payload"]["body"]["value"], STORAGE)

    def test_line_ends_of_windows_are_plain_newlines_in_what_is_sent(self):
        for label, encode in ENCODINGS.items():
            with self.subTest(label):
                result = self.run_file("update", "2005", "--file", "input.txt", "--dry-run", "--json", data=encode("First line\r\n\r\nSecond line\r\n"))
                value = result.json()["payload"]["body"]["value"]
                self.assertNotIn("\r", value)
                self.assertEqual(value.replace("\n", ""), "<p>First line</p><p>Second line</p>")

    def test_convert_reads_a_file_in_any_encoding(self):
        for label, encode in ENCODINGS.items():
            with self.subTest(label):
                result = self.run_file("convert", "input.txt", data=encode(TEXT))
                self.assertEqual(result.code, 0, result.err)
                self.assertEqual(result.out, STORAGE + "\n")

    def test_front_matter_after_a_byte_order_mark_is_still_front_matter(self):
        for label, encode in ENCODINGS.items():
            with self.subTest(label):
                result = self.run_file("convert", "input.txt", data=encode("---\r\ntitle: Grüße\r\n---\r\nBody text\r\n"))
                self.assertEqual(result.out, "<p>Body text</p>\n")

    def test_a_request_body_from_a_file_may_be_utf16_or_have_a_mark(self):
        document = '{"status": "current", "title": "Grüße"}'
        for label, encode in ENCODINGS.items():
            with self.subTest(label):
                result = self.run_file("api", "PUT", "api/v2/pages/2005/title", "--data-file", "input.txt", "--write", data=encode(document))
                self.assertEqual(result.code, 0, result.err)
                self.assertEqual(self.gateway.called("request")[0][3], {"status": "current", "title": "Grüße"})

    def test_standard_input_is_decoded_like_a_file(self):
        for label, encode in ENCODINGS.items():
            with self.subTest(label):
                result = self.run_piped("comment", "2002", "--file", "-", stdin=encode(TEXT))
                self.assertEqual(result.code, 0, result.err)
                self.assertEqual(self.gateway.called("add_comment")[0][1]["body"]["value"], STORAGE)

    def test_convert_reads_standard_input_in_any_encoding(self):
        for label, encode in ENCODINGS.items():
            with self.subTest(label):
                self.assertEqual(self.run_piped("convert", stdin=encode(TEXT)).out, STORAGE + "\n")

    def test_line_ends_of_standard_input_are_plain_newlines(self):
        result = self.run_piped("convert", stdin="# One\r\n\r\ntext\r\n".encode("utf-8"))
        self.assertNotIn("\r", result.out)
        self.assertEqual(result.out.replace("\n", ""), "<h1>One</h1><p>text</p>")

    def test_text_that_a_test_stream_hands_over_as_text_loses_a_byte_order_mark_too(self):
        self.assertEqual(self.run_piped("convert", stdin="\ufeff# One\n").out, "<h1>One</h1>\n")

    def test_a_file_that_is_no_text_is_refused_and_nothing_is_sent(self):
        picture = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10"
        for argv in (
            ("comment", "2002", "--file", "diagram.png"),
            ("update", "2005", "--file", "diagram.png"),
            ("create", "--space", "ENG", "--title", "T", "--file", "diagram.png"),
            ("convert", "diagram.png"),
        ):
            with self.subTest(argv=argv):
                result = self.run_file(*argv, name="diagram.png", data=picture)
                self.assertEqual(result.code, 1)
                self.assertIn("diagram.png is not text", result.err)
                self.assertEqual(result.out, "")
                self.assertEqual([call for call in self.gateway.calls if call[0] in ("add_comment", "update_page", "create_page")], [])

    def test_standard_input_that_is_no_text_is_refused(self):
        result = self.run_piped("comment", "2002", "--file", "-", stdin=b"abc\x00\x01\x02")
        self.assertEqual(result.code, 1)
        self.assertIn("Standard input is not text", result.err)
        self.assertEqual(self.gateway.called("add_comment"), [])

    def test_a_missing_file_still_says_so(self):
        result = run_cli("comment", "2002", "--file", "missing.md", files=MemoryFiles())
        self.assertEqual(result.code, 1)
        self.assertIn("missing.md", result.err)


class TokenFromAPipeTest(unittest.TestCase):
    def test_a_token_from_a_pipe_in_any_encoding_is_saved_as_the_token(self):
        for label, data in (
            ("a byte order mark", b"\xef\xbb\xbfTOKEN123\r\n"),
            ("UTF-16", "TOKEN123\r\n".encode("utf-16")),
            ("UTF-16 without a mark", "TOKEN123\r\n".encode("utf-16-le")),
            ("Windows-1252", "TOKEN123\r\n".encode("cp1252")),
            ("a text stream", "\ufeffTOKEN123\r\n"),
        ):
            with self.subTest(label):
                store = MemoryConfigStore()
                result = run_cli("setup-token", "--stdin", store=store, stdin=data)
                self.assertEqual(result.code, 0, result.err)
                self.assertEqual(store.values, {"CONFLUENCE_API_TOKEN": "TOKEN123"})
                self.assertNotIn("TOKEN123", result.out + result.err)

    def test_what_is_no_token_is_refused_without_being_printed(self):
        for data in (b"SECRET1\nSECRET2", "SECRET TOKEN".encode("utf-16"), b"SECRET\x00\x01\x02"):
            with self.subTest(data=data[:6]):
                store = MemoryConfigStore()
                result = run_cli("setup-token", "--stdin", store=store, stdin=data)
                self.assertEqual(result.code, 1)
                self.assertNotIn("SECRET", result.out + result.err)
                self.assertEqual(store.values, {})


if __name__ == "__main__":
    unittest.main()
