"""What the real file system can say that `Files` does not: whether two paths are one place, and a file read piece by piece."""
import os
import tempfile
import unittest
from pathlib import Path

from conflu_c_cli.adapters.driven.system import LocalFiles
from conflu_c_cli.application.ports_attachments import ComparesPlaces, ReadsPieces
from conflu_c_cli.domain.errors import ValidationError


class PlacesTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name).resolve()
        self.files = LocalFiles()
        (self.root / "folder").mkdir()
        (self.root / "folder" / "settings.txt").write_text("one", encoding="utf-8")
        (self.root / "other.txt").write_text("two", encoding="utf-8")

    def same(self, first, second):
        return self.files.same_place(str(first), str(second))

    def test_the_real_file_system_offers_both_abilities(self):
        self.assertIsInstance(self.files, ComparesPlaces)
        self.assertIsInstance(self.files, ReadsPieces)

    def test_a_file_is_the_place_it_is_and_another_file_is_another_place(self):
        target = self.root / "folder" / "settings.txt"
        self.assertTrue(self.same(target, target))
        self.assertFalse(self.same(target, self.root / "other.txt"))
        self.assertFalse(self.same(self.root / "folder", target))

    def test_dots_and_a_folder_that_is_named_twice_lead_to_one_place(self):
        target = self.root / "folder" / "settings.txt"
        self.assertTrue(self.same(self.root / "folder" / ".." / "folder" / "settings.txt", target))
        self.assertTrue(self.same(self.root / "." / "folder" / "." / "settings.txt", target))
        self.assertTrue(self.same(str(self.root / "folder") + os.sep, self.root / "folder"))

    def test_two_places_of_which_one_is_not_there_yet_are_compared_by_where_they_lead(self):
        wanted = self.root / "folder" / "later" / "x.txt"
        self.assertTrue(self.same(self.root / "folder" / ".." / "folder" / "later" / "x.txt", wanted))
        self.assertFalse(self.same(wanted, self.root / "folder" / "later" / "y.txt"))
        self.assertFalse(self.same(wanted, self.root / "folder" / "settings.txt"))

    def test_a_path_that_cannot_be_looked_at_is_no_place_that_matches(self):
        self.assertFalse(self.same("bad\x00name", self.root / "other.txt"))
        self.assertFalse(self.same(self.root / "other.txt", "bad\x00name"))

    def test_a_relative_path_is_a_place_below_the_working_folder(self):
        target = self.root / "folder" / "settings.txt"
        try:
            relative = os.path.relpath(target)  # relative to wherever the tests run from
        except ValueError:
            self.skipTest("the folder of the test is on another drive than the working folder, so no relative path leads there")
        self.assertTrue(self.same(relative, target))
        self.assertTrue(self.same(os.path.join(os.path.dirname(relative), "..", os.path.basename(os.path.dirname(relative)), "settings.txt"), target))

    def test_a_symbolic_link_leads_to_the_place_it_points_to(self):
        link = self.root / "innocent.txt"
        try:
            os.symlink(self.root / "folder" / "settings.txt", link)
        except (OSError, NotImplementedError):
            self.skipTest("this system does not let a test make a symbolic link")
        self.assertTrue(self.same(link, self.root / "folder" / "settings.txt"))
        self.assertFalse(self.same(link, self.root / "other.txt"))

    def test_a_link_to_a_folder_leads_to_the_folder(self):
        link = self.root / "shortcut"
        try:
            os.symlink(self.root / "folder", link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("this system does not let a test make a symbolic link")
        self.assertTrue(self.same(link, self.root / "folder"))
        self.assertTrue(self.same(link / "settings.txt", self.root / "folder" / "settings.txt"))
        self.assertTrue(self.same(link / "not-yet.txt", self.root / "folder" / "not-yet.txt"))

    def test_a_hard_link_is_the_same_file(self):
        link = self.root / "hard.txt"
        try:
            os.link(self.root / "folder" / "settings.txt", link)
        except (OSError, NotImplementedError):
            self.skipTest("this file system does not have hard links")
        self.assertTrue(self.same(link, self.root / "folder" / "settings.txt"))

    def test_another_spelling_of_a_name_is_one_place_where_the_system_ignores_case(self):
        shouted = self.root / "FOLDER" / "SETTINGS.TXT"
        if not shouted.exists():
            self.skipTest("this file system tells upper case from lower case")
        self.assertTrue(self.same(shouted, self.root / "folder" / "settings.txt"))


class PiecesTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name)
        self.files = LocalFiles()

    def test_a_file_is_handed_out_in_pieces_of_at_most_the_size_asked_for(self):
        path = self.root / "data.bin"
        path.write_bytes(bytes(range(256)) * 10)
        pieces = list(self.files.read_pieces(str(path), 1000))
        self.assertEqual([len(piece) for piece in pieces], [1000, 1000, 560])
        self.assertEqual(b"".join(pieces), path.read_bytes())

    def test_a_small_file_is_one_piece_and_an_empty_file_none(self):
        small, empty = self.root / "small.txt", self.root / "empty.txt"
        small.write_bytes(b"abc")
        empty.write_bytes(b"")
        self.assertEqual(list(self.files.read_pieces(str(small), 1 << 20)), [b"abc"])
        self.assertEqual(list(self.files.read_pieces(str(empty), 1 << 20)), [])

    def test_a_file_that_cannot_be_read_is_a_validation_error_that_does_not_hold_the_path_open(self):
        with self.assertRaises(ValidationError) as caught:
            list(self.files.read_pieces(str(self.root / "missing.bin"), 10))
        self.assertIn("Cannot read", caught.exception.message)
        with self.assertRaises(ValidationError):
            list(self.files.read_pieces(str(self.root), 10))  # a folder

    def test_the_file_can_be_removed_when_the_last_piece_was_read(self):
        path = self.root / "gone.bin"
        path.write_bytes(b"x" * 100)
        for _ in self.files.read_pieces(str(path), 10):
            pass
        path.unlink()  # on Windows this fails when the file is still open
        self.assertFalse(path.exists())

    def test_a_search_that_stops_early_leaves_nothing_open_that_a_collected_generator_does_not_close(self):
        path = self.root / "early.bin"
        path.write_bytes(b"x" * 100)
        generator = self.files.read_pieces(str(path), 10)
        next(generator)
        generator.close()
        path.unlink()
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
