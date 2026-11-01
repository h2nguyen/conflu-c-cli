"""`OutFile`: the text of a command that only reads, in a file, as UTF-8; and what it never writes over."""
import unittest

from conflu_c_cli.application.outfile import OutFile, Written
from conflu_c_cli.domain.attachguards import SCAN_LIMIT
from conflu_c_cli.domain.errors import UsageError, ValidationError
from tests.support.fakes import MemoryFiles, default_settings
from tests.support.places_attachments import PlacedFiles

CONFIG = "/home/me/.config/conflu-c-cli/config"
TOKEN = "secret-token"  # the token of `default_settings()`
TEXT = "Grüße € naïve café – “quotes”\nSecond line\n"


def outfile(files, **more):
    return OutFile(files, default_settings(**more), protected=(CONFIG,))


class WriteTest(unittest.TestCase):
    def setUp(self):
        self.files = PlacedFiles()
        self.out = outfile(self.files)

    def test_the_text_is_written_as_utf_8_without_a_byte_order_mark(self):
        result = self.out.write("page.xml", TEXT)
        data = self.files.files["page.xml"]
        self.assertEqual(data, TEXT.encode("utf-8"))
        self.assertFalse(data.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")))
        self.assertEqual(result, Written("page.xml", len(data)))
        self.assertGreater(len(data), len(TEXT))  # the size is bytes, not characters

    def test_the_line_ends_are_the_ones_the_text_has(self):
        self.out.write("a.txt", "one\ntwo\n")
        self.assertEqual(self.files.files["a.txt"], b"one\ntwo\n")
        self.out.write("b.txt", "one\r\ntwo")
        self.assertEqual(self.files.files["b.txt"], b"one\r\ntwo")  # the command turns them into plain line ends, as it does for a screen

    def test_a_character_without_an_encoding_is_a_question_mark_and_no_failure(self):
        result = self.out.write("odd.txt", "a\ud800b")
        self.assertEqual((self.files.files["odd.txt"], result.size), (b"a?b", 3))

    def test_an_empty_text_is_an_empty_file(self):
        self.assertEqual(self.out.write("empty.txt", ""), Written("empty.txt", 0))
        self.assertEqual(self.files.files["empty.txt"], b"")

    def test_the_path_is_given_back_as_it_was_written(self):
        self.assertEqual(self.out.write("sub/../page.xml", "x").path, "sub/../page.xml")

    def test_a_check_writes_nothing(self):
        self.out.check("page.xml")
        self.out.check("deep/er/page.xml", force=True)
        self.assertEqual(self.files.writes, [])
        self.assertEqual(self.files.files, {})


class TheFileThatIsThereTest(unittest.TestCase):
    def setUp(self):
        self.files = PlacedFiles({"page.xml": "old"})
        self.out = outfile(self.files)

    def test_it_is_not_replaced_without_force(self):
        with self.assertRaises(ValidationError) as caught:
            self.out.write("page.xml", TEXT)
        self.assertEqual(caught.exception.exit_code, 1)
        self.assertIn("page.xml exists already", caught.exception.message)
        self.assertIn("--force", caught.exception.hint)
        self.assertEqual(self.files.files["page.xml"], b"old")
        self.assertEqual(self.files.writes, [])

    def test_it_is_replaced_with_force(self):
        self.out.write("page.xml", TEXT, force=True)
        self.assertEqual(self.files.files["page.xml"], TEXT.encode("utf-8"))

    def test_a_folder_is_never_replaced(self):
        files = PlacedFiles({"out/page.xml": "x"})
        for force in (False, True):
            with self.subTest(force=force):
                with self.assertRaises(ValidationError) as caught:
                    outfile(files).write("out", TEXT, force=force)
                self.assertIn("is a folder", caught.exception.message)
        self.assertEqual(files.writes, [])

    def test_a_file_that_appears_between_the_check_and_the_write_is_not_replaced_either(self):
        self.out.check("later.xml")
        self.files.put("later.xml", b"somebody was quicker")
        with self.assertRaises(ValidationError):
            self.out.write("later.xml", TEXT)
        self.assertEqual(self.files.files["later.xml"], b"somebody was quicker")

    def test_a_file_that_is_not_there_is_not_read_for_the_token(self):
        self.out.write("new.xml", TEXT, force=True)
        self.assertEqual(self.files.pieces_read, [])

    def test_a_device_or_a_pipe_is_neither_read_nor_replaced_not_even_with_force(self):
        """Reading `/dev/zero` or the console never ends: what is no plain file is refused before anything is read."""

        class WithADevice(PlacedFiles):
            def is_file(self, path):
                return False if path == "dev" else super().is_file(path)

        files = WithADevice({"dev": "x"})
        with self.assertRaises(ValidationError) as caught:
            outfile(files).write("dev", TEXT, force=True)
        self.assertIn("is not a plain file", caught.exception.message)
        self.assertIn("--force replaces a file and nothing else", caught.exception.hint)
        self.assertEqual((files.pieces_read, files.writes), ([], []))
        with self.assertRaises(ValidationError) as caught:
            outfile(files).write("dev", TEXT)
        self.assertIn("exists already", caught.exception.message)

    def test_a_file_that_is_there_is_not_read_without_force(self):
        with self.assertRaises(ValidationError):
            self.out.check("page.xml")
        self.assertEqual(self.files.pieces_read, [])


class TheValueTest(unittest.TestCase):
    def setUp(self):
        self.files = PlacedFiles()
        self.out = outfile(self.files)

    def test_a_value_that_is_given_and_empty_is_an_error_and_no_file(self):
        for value in ("", " ", "\t", "  \n"):
            with self.subTest(value=value):
                with self.assertRaises(UsageError) as caught:
                    self.out.check(value)
                self.assertEqual(caught.exception.exit_code, 2)
                self.assertIn("--out is empty", caught.exception.message)

    def test_a_dash_is_a_file_name_that_nobody_means_and_standard_output_is_not_offered(self):
        with self.assertRaises(UsageError) as caught:
            self.out.check("-")
        self.assertIn("not standard output", caught.exception.message)
        self.assertIn("Leave out --out", caught.exception.hint)

    def test_a_control_character_is_refused(self):
        for value in ("a\x00b.xml", "a\nb.xml", "a\x1bb.xml", "a\x7fb.xml"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(UsageError):
                    self.out.check(value)
        self.out.check("a b.xml")  # a blank inside a name is a name
        self.assertEqual(self.files.writes, [])

    def test_a_path_that_ends_with_a_separator_names_a_folder_and_not_a_file(self):
        for value in ("out/", "out\\", "/work/out/", "sub/deeper\\"):
            with self.subTest(value=value):
                with self.assertRaises(UsageError) as caught:
                    self.out.check(value)
                self.assertEqual(caught.exception.exit_code, 2)
                self.assertIn("ends with a separator", caught.exception.message)
                self.assertIn(f"{value}page.xml", caught.exception.hint)
        self.assertEqual(self.files.writes, [])


class TheConfigurationTest(unittest.TestCase):
    """The configuration holds the token: it is never written over, with `--force` either, and nothing is written next to it."""

    def refused(self, files, path, force=True, fragment="configuration file"):
        with self.assertRaises(UsageError) as caught:
            outfile(files).write(path, TEXT, force=force)
        self.assertEqual(caught.exception.exit_code, 2)
        self.assertIn(fragment, caught.exception.message)
        self.assertIn("--force too", caught.exception.hint)
        self.assertEqual(files.writes, [])

    def test_the_settings_file_is_refused_with_and_without_force(self):
        files = PlacedFiles({CONFIG: "CONFLUENCE_API_TOKEN=x\n"})
        for force in (False, True):
            with self.subTest(force=force):
                self.refused(files, CONFIG, force)
        self.assertEqual(files.files[CONFIG], b"CONFLUENCE_API_TOKEN=x\n")

    def test_the_settings_file_that_is_not_there_yet_is_refused_too(self):
        self.refused(PlacedFiles(), CONFIG)

    def test_a_spelling_that_leads_to_it_is_refused(self):
        files = PlacedFiles({CONFIG: "x"}, links={"/work/alias": "/home/me/.config/conflu-c-cli"}, ignore_case=True)
        for spelling in ("/home/me/.config/conflu-c-cli/../conflu-c-cli/config", "/home/me/./.config/conflu-c-cli/config", "alias/config", "/HOME/ME/.CONFIG/CONFLU-C-CLI/CONFIG"):
            with self.subTest(spelling=spelling):
                self.refused(files, spelling)

    def test_a_file_in_the_folder_of_the_settings_is_refused(self):
        files = PlacedFiles({CONFIG: "x"}, links={"/work/alias": "/home/me/.config/conflu-c-cli"})
        for path in ("/home/me/.config/conflu-c-cli/notes.xml", "alias/notes.xml", "/home/me/.config/conflu-c-cli/../conflu-c-cli/page.xml"):
            with self.subTest(path=path):
                self.refused(files, path, fragment="the folder where the CLI keeps its own configuration")

    def test_a_folder_below_the_settings_and_a_folder_beside_them_are_no_risk(self):
        files = PlacedFiles()
        for path in ("/home/me/.config/conflu-c-cli/sub/page.xml", "/home/me/.config/other/config", "/home/me/.config/page.xml"):
            with self.subTest(path=path):
                outfile(files).write(path, TEXT)
        self.assertEqual(len(files.writes), 3)

    def test_without_a_place_for_the_configuration_nothing_is_kept_out(self):
        files = PlacedFiles()
        OutFile(files, default_settings()).write(CONFIG, TEXT)
        self.assertEqual(files.writes, [CONFIG])

    def test_a_file_in_the_working_folder_is_no_neighbour_of_the_settings(self):
        files = PlacedFiles()
        outfile(files).write("page.xml", TEXT)  # the working folder is /work, not the folder of the settings
        self.assertEqual(files.writes, ["page.xml"])


class TheTokenTest(unittest.TestCase):
    """A file that is replaced is gone, and one that holds the token may be the only copy of it."""

    def refused(self, content, force=True):
        files = PlacedFiles({"notes.txt": content})
        with self.assertRaises(UsageError) as caught:
            outfile(files).write("notes.txt", TEXT, force=force)
        self.assertEqual(caught.exception.exit_code, 2)
        self.assertIn("holds the API token", caught.exception.message)
        self.assertNotIn(TOKEN, caught.exception.message + caught.exception.hint)  # the token is never shown
        self.assertEqual(files.files["notes.txt"], content if isinstance(content, bytes) else content.encode("utf-8"))
        self.assertEqual(files.writes, [])

    def test_a_copy_of_the_settings_is_not_replaced_with_force_either(self):
        self.refused(f"CONFLUENCE_BASE_URL=https://example.atlassian.net/wiki\nCONFLUENCE_API_TOKEN={TOKEN}\n")

    def test_every_encoding_that_the_cli_reads_is_looked_at(self):
        for codec in ("utf-8", "utf-16", "utf-16-le", "utf-32", "cp1252"):
            with self.subTest(codec=codec):
                self.refused(f"token: {TOKEN}\n".encode(codec))

    def test_the_header_that_carries_it_is_looked_at_too(self):
        import base64

        header = base64.b64encode(f"user@example.com:{TOKEN}".encode("utf-8")).decode("ascii")
        self.refused(f"Authorization: Basic {header}\n")

    def test_the_token_across_the_end_of_a_piece_is_found(self):
        files = PlacedFiles({"log.txt": "x" * 7 + TOKEN + "y" * 7}, piece=5)
        with self.assertRaises(UsageError):
            outfile(files).write("log.txt", TEXT, force=True)
        self.assertEqual(files.pieces_read, ["log.txt"])

    def test_a_file_without_the_token_is_replaced_with_force(self):
        files = PlacedFiles({"notes.txt": "nothing secret here\n"})
        outfile(files).write("notes.txt", TEXT, force=True)
        self.assertEqual(files.files["notes.txt"], TEXT.encode("utf-8"))
        self.assertEqual(files.pieces_read, ["notes.txt"])

    def test_a_token_that_is_too_short_to_be_one_is_not_looked_for(self):
        files = PlacedFiles({"notes.txt": "abc\n"})
        outfile(files, api_token="abc").write("notes.txt", TEXT, force=True)  # looking for it would refuse every file that holds the letters
        self.assertEqual(files.files["notes.txt"], TEXT.encode("utf-8"))

    def test_no_settings_no_search(self):
        files = PlacedFiles({"notes.txt": f"token {TOKEN}"})
        OutFile(files).write("notes.txt", TEXT, force=True)
        self.assertEqual(files.pieces_read, [])

    def test_a_file_too_large_to_be_searched_is_not_replaced(self):
        files = PlacedFiles({"big.bin": "x"})
        files.size = lambda path: SCAN_LIMIT + 1
        with self.assertRaises(ValidationError) as caught:
            outfile(files).write("big.bin", TEXT, force=True)
        self.assertIn("a file that is not searched is not replaced", caught.exception.message)
        self.assertEqual(files.files["big.bin"], b"x")

    def test_the_search_is_for_the_file_that_is_there_and_not_for_the_text_that_is_written(self):
        files = PlacedFiles()
        outfile(files).write("page.xml", f"a page that quotes {TOKEN}\n")  # what Confluence says is no business of the guard
        self.assertEqual(files.files["page.xml"], f"a page that quotes {TOKEN}\n".encode("utf-8"))


class MemoryFilesTest(unittest.TestCase):
    """Files that cannot say where a path leads (no `same_place`, no pieces) still keep the spelling of the settings file out."""

    def test_the_same_spelling_is_refused_and_the_rest_is_written(self):
        files = MemoryFiles()
        out = OutFile(files, default_settings(), protected=("memory://config",))
        with self.assertRaises(UsageError):
            out.write("memory://config", TEXT, force=True)
        out.write("page.xml", TEXT)
        self.assertEqual(files.writes, ["page.xml"])

    def test_the_token_is_found_with_the_whole_file_read_at_once(self):
        files = MemoryFiles({"notes.txt": f"token {TOKEN}"})
        with self.assertRaises(UsageError):
            OutFile(files, default_settings()).write("notes.txt", TEXT, force=True)


if __name__ == "__main__":
    unittest.main()
