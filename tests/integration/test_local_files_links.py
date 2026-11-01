"""`import-md-dir` publishes the Markdown files of a folder, not what a link in it points at outside of it."""
import os
import tempfile
import unittest
from pathlib import Path

from conflu_c_cli.adapters.driven.system import LocalFiles


def make_link(link: Path, target: Path) -> bool:
    try:
        os.symlink(target, link)
        return True
    except (OSError, NotImplementedError):  # no privilege to make one on Windows, or a file system without links
        return False


class ListMatchingTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.docs = self.root / "docs"
        self.docs.mkdir()
        (self.docs / "a.md").write_text("# A\n", encoding="utf-8")
        (self.docs / "b.txt").write_text("not markdown", encoding="utf-8")
        (self.root / "outside.md").write_text("# Secret\n", encoding="utf-8")
        self.files = LocalFiles()

    def names(self):
        return [Path(path).name for path in self.files.list_matching(str(self.docs), "*.md")]

    def test_the_files_of_the_folder_are_listed_in_order(self):
        (self.docs / "0.md").write_text("# Zero\n", encoding="utf-8")
        self.assertEqual(self.names(), ["0.md", "a.md"])

    def test_a_link_to_a_file_outside_the_folder_is_left_out(self):
        if not make_link(self.docs / "leak.md", self.root / "outside.md"):
            self.skipTest("this system does not let a test make a symbolic link")
        self.assertEqual(self.names(), ["a.md"])

    def test_a_link_to_a_file_inside_the_folder_is_kept(self):
        if not make_link(self.docs / "same.md", self.docs / "a.md"):
            self.skipTest("this system does not let a test make a symbolic link")
        self.assertEqual(self.names(), ["a.md", "same.md"])

    def test_a_link_that_points_nowhere_or_in_a_circle_is_left_out_without_a_crash(self):
        if not make_link(self.docs / "gone.md", self.docs / "missing.md") or not make_link(self.docs / "loop.md", self.docs / "loop.md"):
            self.skipTest("this system does not let a test make a symbolic link")
        self.assertEqual(self.names(), ["a.md"])


if __name__ == "__main__":
    unittest.main()
