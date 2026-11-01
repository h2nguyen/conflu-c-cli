"""The name that a file gets on this computer when somebody else chose it: it stays in its folder, is no device, and is not longer than a file system takes."""
import unittest

from conflu_c_cli.domain.errors import ValidationError
from conflu_c_cli.domain.naming import safe_file_name


def size(name):
    return len(name.encode("utf-8"))


class SafeNameTest(unittest.TestCase):
    def test_a_name_that_is_fine_stays_as_it_is(self):
        for name in ("report.pdf", "Übersicht 日本語 ✓.docx", "a.b.c.tar.gz", "no extension", "AGENTS.md", "conftest.py", "x" * 200, "ä" * 100):
            with self.subTest(name=name[:20]):
                self.assertEqual(safe_file_name(name), name)

    def test_a_name_that_starts_with_a_dot_gets_an_underscore_in_front_so_that_no_hidden_file_is_planted(self):
        cases = {
            ".mcp.json": "_.mcp.json", ".vscode": "_.vscode", ".env": "_.env", ".hidden": "_.hidden", ".gitignore": "_.gitignore", "..hidden": "_..hidden",
            "../.env": "_.env", "..\\.ssh\\.config": "_.config", " .env": "_.env", ".env ": "_.env", ".a.b": "_.a.b", "\u200b.env": "_.env",
            ".con": "_.con",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                made = safe_file_name(name)
                self.assertEqual(made, expected)
                self.assertFalse(made.startswith("."))
        for name in ("a.env", "x.mcp.json", "name.", "a..b"):  # a dot elsewhere is a dot like any other
            self.assertEqual(safe_file_name(name).lstrip("_"), name.rstrip(". "), name)

    def test_what_leads_out_of_the_folder_or_shows_nothing_is_taken_out(self):
        cases = {
            "../../etc/passwd": "passwd", "..\\..\\evil.txt": "evil.txt", "/etc/cron.d/x": "x", "C:\\Windows\\win.ini": "win.ini", "a:b*c?.txt": "a_b_c_.txt",
            "trailing. ": "trailing", "invoice\u202etxt.exe": "invoice_txt.exe", "a\u200bb.txt": "a_b.txt", "a\x7fb\x85c.txt": "a_b_c.txt", "tab\tname": "tab_name",
            "stream.txt:hidden": "stream.txt_hidden", "pipe|and<angle>.txt": "pipe_and_angle_.txt", "lone\ud800surrogate\udfff.txt": "lone_surrogate_.txt",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(safe_file_name(name), expected)

    def test_nothing_that_is_left_of_a_name_is_an_error(self):
        for name in ("", ".", "..", "...", " ", "/", "\\", "a/..", "../", " . "):
            with self.subTest(name=name):
                with self.assertRaises(ValidationError):
                    safe_file_name(name)

    def test_the_names_of_devices_are_not_used_with_or_without_an_extension(self):
        for name in ("con", "NUL", "aux.txt", "Prn.tar.gz", "com1", "LPT9.log", "COM\u00b9", "lpt\u00b2.txt", "CONIN$", "conout$.txt", "con .txt", "nul  "):
            with self.subTest(name=name):
                made = safe_file_name(name)
                self.assertTrue(made.startswith("_"), made)
        for name in ("console.txt", "com10.txt", "comma", "auxiliary", "nulled", "com0", "lpt"):
            self.assertEqual(safe_file_name(name), name, name)


class LongNameTest(unittest.TestCase):
    def test_a_name_is_cut_where_a_file_system_would_refuse_it_and_keeps_its_extension(self):
        made = safe_file_name("a" * 400 + ".pdf")
        self.assertEqual((size(made) <= 200, made.endswith(".pdf"), made[:4]), (True, True, "aaaa"))
        self.assertEqual(size(made), 200)

    def test_the_cut_is_at_a_whole_character(self):
        for text in ("\u00e4", "\u65e5", "\U0001f600"):
            with self.subTest(character=ascii(text)):
                made = safe_file_name(text * 300 + ".txt")
                self.assertLessEqual(size(made), 200)
                self.assertTrue(made.endswith(".txt"))
                self.assertEqual(made[:-4].strip(text), "")  # nothing but whole characters is left
                made.encode("utf-8")  # and it is valid text

    def test_a_long_extension_is_no_extension_and_goes_with_the_rest(self):
        made = safe_file_name("name." + "x" * 300)
        self.assertEqual(size(made), 200)
        self.assertTrue(made.startswith("name.xxx"))

    def test_what_the_cut_leaves_at_the_end_is_made_safe_again(self):
        made = safe_file_name("a" * 190 + ". . . . . . . . . . . . . . . " + "b" * 50 + ".txt")
        self.assertFalse(made[:-4].endswith((".", " ")), made)
        self.assertEqual(safe_file_name(" " * 10 + "a" * 300).startswith("a"), True)

    def test_a_name_without_a_stem_is_not_empty(self):
        made = safe_file_name("." + "x" * 300)
        self.assertEqual(made, "_." + "x" * 199)  # the underscore of a name that starts with a dot comes after the cut: one byte more is no risk
        self.assertLessEqual(size(made), 255)

    def test_the_limit_is_exact(self):
        self.assertEqual(safe_file_name("x" * 200), "x" * 200)
        self.assertEqual(size(safe_file_name("x" * 201)), 200)
        self.assertEqual(safe_file_name("x" * 196 + ".txt"), "x" * 196 + ".txt")
        self.assertEqual(safe_file_name("x" * 197 + ".txt"), "x" * 196 + ".txt")

    def test_two_long_names_that_differ_only_at_the_end_become_one_which_the_download_refuses(self):
        self.assertEqual(safe_file_name("a" * 300 + "1.txt"), safe_file_name("a" * 300 + "2.txt"))


if __name__ == "__main__":
    unittest.main()
