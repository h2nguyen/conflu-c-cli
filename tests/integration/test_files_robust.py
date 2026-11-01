"""The three questions about a path that the file system adapter answers: it never raises for a name that the file system refuses (before Python 3.13
`Path.exists`, `is_dir` and `is_file` let an error such as ENAMETOOLONG through), so a search text such as `@` + 5,000 letters is searched for as text."""
import errno
import unittest
from unittest import mock

from conflu_c_cli.adapters.driven.system import LocalFiles
from tests.integration.test_end_to_end import EndToEnd


class NamesThatTheFileSystemRefusesTest(unittest.TestCase):
    def test_a_name_that_is_too_long_is_no_file_and_no_folder(self):
        files = LocalFiles()
        for method in ("exists", "is_dir", "is_file"):
            for error in (OSError(errno.ENAMETOOLONG, "File name too long"), OSError(errno.EACCES, "Permission denied"), OSError(errno.EIO, "Input/output error")):
                with self.subTest(method=method, error=error.errno):
                    with mock.patch(f"pathlib.Path.{method}", side_effect=error):
                        self.assertFalse(getattr(files, method)("x" * 300))

    def test_what_is_there_is_still_found(self):
        files = LocalFiles()
        here = __file__
        self.assertEqual((files.exists(here), files.is_file(here), files.is_dir(here)), (True, True, False))
        self.assertEqual((files.exists("nothing-here-at-all"), files.is_file("nothing-here-at-all")), (False, False))


class ASearchTextThatIsNoFileNameTest(EndToEnd):
    def test_a_very_long_text_that_starts_with_an_at_sign_is_searched_for_as_text(self):
        for length in (300, 5000):
            with self.subTest(length=length):
                result = self.cli("search", "@" + "a" * length, "--json")
                self.assertEqual(result.code, 0, result.err)
                self.assertIn("starts with @ and no file of that name was found", result.err)
