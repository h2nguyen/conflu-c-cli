"""Text from the files and the pipes of Windows, through the real adapters against the mock Confluence: what reaches Confluence is the
text, never a byte order mark or a carriage return, and a settings file that Notepad or PowerShell saved is read."""
import json
import os
import subprocess
import sys
import unittest

from tests.integration.test_end_to_end import ROOT, EndToEnd
from tests.support.encodings import ENCODINGS, STORAGE, TEXT

DOCUMENT = "---\r\ntitle: {title}\r\nlabels: umlaute, gruesse\r\n---\r\n# Überschrift\r\n\r\n" + TEXT + "\r\n"


class RealFilesTest(EndToEnd):
    def write_bytes(self, name, data):
        path = self.root / "in" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def page(self, title):
        found = [record for record in self.mock.pages.values() if record["title"] == title]
        self.assertEqual(len(found), 1, f"{title}: {[record['title'] for record in self.mock.pages.values()]}")
        return found[0]

    def assert_clean(self, text):
        self.assertNotIn("\ufeff", text)
        self.assertNotIn("\r", text)
        self.assertNotIn("\x00", text)

    def test_import_md_reads_a_file_in_any_encoding_and_sends_its_text(self):
        for number, (label, encode) in enumerate(ENCODINGS.items()):
            with self.subTest(label):
                title = f"Größe {number}"
                path = self.write_bytes(f"page{number}.md", encode(DOCUMENT.format(title=title)))
                result = self.cli("import-md", str(path), "--space", "ENG", "--json")
                self.assertEqual(result.code, 0, result.err)
                self.assertEqual(result.json()["title"], title)
                record = self.page(title)
                body = record["versions"][-1]["body"]
                self.assert_clean(record["title"] + body)
                self.assertIn(TEXT, body)
                self.assertEqual(sorted(record["labels"]), ["gruesse", "umlaute"])

    def test_import_md_dir_reads_files_in_different_encodings_in_one_run(self):
        folder = self.root / "docs"
        folder.mkdir()
        for number, (label, encode) in enumerate(ENCODINGS.items()):
            (folder / f"page{number}.md").write_bytes(encode(DOCUMENT.format(title=f"Folder page {number}")))
        result = self.cli("import-md-dir", str(folder), "--space", "ENG", "--json")
        self.assertEqual(result.code, 0, result.err)
        report = result.json()
        self.assertEqual((report["created"], report["failed"]), (len(ENCODINGS), 0))
        for number in range(len(ENCODINGS)):
            record = self.page(f"Folder page {number}")
            self.assert_clean(record["title"] + record["versions"][-1]["body"])
        again = self.cli("import-md-dir", str(folder), "--space", "ENG", "--json").json()
        self.assertEqual((again["created"], again["unchanged"]), (0, len(ENCODINGS)))  # the same text, whatever the encoding

    def test_create_update_and_comment_send_the_text_of_a_file(self):
        for number, (label, encode) in enumerate(ENCODINGS.items()):
            with self.subTest(label):
                path = self.write_bytes(f"text{number}.txt", encode(TEXT + "\r\n"))
                created = self.cli("create", "--space", "ENG", "--title", f"Created {number}", "--file", str(path), "--json")
                self.assertEqual(created.code, 0, created.err)
                record = self.page(f"Created {number}")
                self.assertEqual(record["versions"][-1]["body"], STORAGE)
                updated = self.cli("update", "2005", "--file", str(path), "--append", "--json")
                self.assertEqual(updated.code, 0, updated.err)
                self.assert_clean(self.mock.pages["2005"]["versions"][-1]["body"])
                commented = self.cli("comment", "2005", "--file", str(path), "--json")
                self.assertEqual(commented.code, 0, commented.err)
                self.assertEqual(self.mock.comments[commented.json()["commentId"]]["body"], STORAGE)

    def test_a_file_that_is_no_text_sends_nothing(self):
        picture = self.write_bytes("diagram.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10")
        before = len(self.mock.requests)
        for argv in (("comment", "2005", "--file", str(picture)), ("update", "2005", "--file", str(picture)), ("import-md", str(picture), "--space", "ENG")):
            with self.subTest(argv=argv[0]):
                result = self.cli(*argv)
                self.assertEqual(result.code, 1)
                self.assertIn("is not text", result.err)
        self.assertEqual([item.target for item in self.mock.requests[before:] if item.method in ("POST", "PUT")], [])

    def test_a_settings_file_saved_as_utf16_configures_the_program(self):
        text = f"CONFLUENCE_BASE_URL={self.mock.base_url}\r\nCONFLUENCE_EMAIL={self.mock.email}\r\nCONFLUENCE_API_TOKEN={self.mock.token}\r\nCONFLUENCE_SPACE=ENG\r\n"
        file_env = {"CONFLUENCE_CONFIG_FILE": str(self.config), "HOME": str(self.root)}
        for label, data in (("UTF-16 with a mark", text.encode("utf-16")), ("UTF-16 without a mark", text.encode("utf-16-le")), ("Windows-1252", text.encode("cp1252"))):
            with self.subTest(label):
                self.config.parent.mkdir(parents=True, exist_ok=True)
                self.config.write_bytes(data)
                ping = self.cli("ping", env=file_env, replace_env=True)
                self.assertEqual(ping.out, f"OK: connected to {self.mock.base_url} as Alex Example\n")
                self.assertEqual(self.cli("pages", "--limit", "1", "--json", env=file_env, replace_env=True).json()["space"], "ENG")
                self.assertEqual(self.cli("current", env=file_env, replace_env=True).out, "ENG\n")


class RealPipeTest(EndToEnd):
    """As a separate program, with the bytes that a Windows shell puts into the pipe."""

    def child_with(self, *argv, stdin, env=None):
        base = {key: value for key, value in os.environ.items() if not key.startswith(("CONFLUENCE_", "PYTHON"))}
        done = subprocess.run(
            [sys.executable, "-I", "-X", "utf8", str(ROOT / "conflu.py"), *argv],
            input=stdin,
            capture_output=True,
            env={**base, **self.env, **(env or {})},
            timeout=60,
        )
        return done.returncode, done.stdout.decode("utf-8"), done.stderr.decode("utf-8")

    def test_a_token_from_a_utf16_pipe_is_saved_as_the_token(self):
        for label, data in (("UTF-16", "child-token-123\r\n".encode("utf-16")), ("UTF-8 with a mark", b"\xef\xbb\xbfchild-token-123\r\n")):
            with self.subTest(label):
                code, out, err = self.child_with("setup-token", "--stdin", stdin=data, env={"CONFLUENCE_API_TOKEN": "", "CONFLUENCE_CONFIG_FILE": str(self.config)})
                self.assertEqual(code, 0, err)
                self.assertIn("CONFLUENCE_API_TOKEN=child-token-123\n", self.config.read_text(encoding="utf-8"))
                self.assertNotIn("child-token-123", out + err)

    def test_a_comment_and_a_conversion_from_a_utf16_pipe(self):
        code, out, err = self.child_with("comment", "2005", "--file", "-", "--json", stdin=(TEXT + "\r\n").encode("utf-16"))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.mock.comments[json.loads(out)["commentId"]]["body"], STORAGE)
        code, out, err = self.child_with("convert", stdin=("# Überschrift\r\n\r\n" + TEXT + "\r\n").encode("utf-16"))
        self.assertEqual(code, 0, err)
        self.assertNotIn("\r", out)
        self.assertNotIn("\ufeff", out)
        self.assertIn("<h1>Überschrift</h1>", out)


if __name__ == "__main__":
    unittest.main()
