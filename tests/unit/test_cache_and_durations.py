"""Lengths of time, the file cache of the doctor and where that cache lives."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from conflu_c_cli.adapters.driven.file_cache import FileCache
from conflu_c_cli.adapters.driven.paths import cache_directory, config_file
from conflu_c_cli.domain.durations import parse_duration
from conflu_c_cli.domain.errors import ValidationError


class DurationTest(unittest.TestCase):
    def test_units(self):
        self.assertEqual(parse_duration("30s"), 30)
        self.assertEqual(parse_duration("10m"), 600)
        self.assertEqual(parse_duration("2h"), 7200)
        self.assertEqual(parse_duration("1d"), 86400)
        self.assertEqual(parse_duration("1w"), 7 * 86400)
        self.assertEqual(parse_duration("1.5h"), 5400)
        self.assertEqual(parse_duration(" 10 M "), 600)  # blanks and capitals do not matter

    def test_a_bare_number_counts_in_the_default_unit(self):
        self.assertEqual(parse_duration("30"), 30)
        self.assertEqual(parse_duration("30", default_unit="m"), 1800)
        self.assertEqual(parse_duration("2h", default_unit="m"), 7200)  # a unit that is written wins

    def test_zero_is_a_length_of_time(self):
        self.assertEqual(parse_duration("0"), 0)
        self.assertEqual(parse_duration("0m"), 0)

    def test_what_is_no_length_of_time_is_refused_with_a_hint(self):
        for text in ("", "soon", "-5m", "10x", "m10", "1e3", "1,5h", "٣m", "1" * 10, "9" * 5000, "10m 5s", "\n"):
            with self.subTest(text=text[:12]), self.assertRaises(ValidationError) as caught:
                parse_duration(text)
            self.assertIn("10m", caught.exception.hint)
            self.assertLess(len(caught.exception.message), 100)  # the text that was refused is not repeated whole

    def test_none_is_refused_too(self):
        with self.assertRaises(ValidationError):
            parse_duration(None)  # type: ignore[arg-type]


class FileCacheTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name)
        self.folder = self.root / "cache" / "conflu-c-cli"
        self.cache = FileCache(self.folder)

    def test_what_was_put_is_given_back_and_the_folder_is_made(self):
        self.assertFalse(self.folder.exists())
        self.cache.put("doctor", "0123456789abcdef", '{"at": "now"}')
        self.assertEqual(self.cache.get("doctor", "0123456789abcdef", 600), '{"at": "now"}')
        self.assertEqual([entry.name for entry in self.folder.iterdir()], ["doctor-0123456789abcdef.json"])  # one file, no temporary leftover

    @unittest.skipIf(os.name == "nt", "file permissions are those of Unix")
    def test_the_file_is_for_its_owner_only(self):
        self.cache.put("doctor", "a", "text")
        self.assertEqual((self.folder / "doctor-a.json").stat().st_mode & 0o777, 0o600)

    def test_a_put_replaces_and_a_key_that_was_never_put_is_none(self):
        self.cache.put("doctor", "a", "one")
        self.cache.put("doctor", "a", "two")
        self.assertEqual(self.cache.get("doctor", "a", 600), "two")
        self.assertIsNone(self.cache.get("doctor", "b", 600))
        self.assertIsNone(self.cache.get("other", "a", 600))
        self.assertIsNone(FileCache(self.root / "nowhere").get("doctor", "a", 600))

    def test_a_value_that_is_older_than_the_age_is_not_given(self):
        self.cache.put("doctor", "a", "text")
        path = self.folder / "doctor-a.json"
        os.utime(path, (time.time() - 700, time.time() - 700))
        self.assertIsNone(self.cache.get("doctor", "a", 600))
        self.assertEqual(self.cache.get("doctor", "a", 800), "text")
        self.assertIsNone(self.cache.get("doctor", "a", 0))

    def test_a_file_that_is_no_text_is_none_and_not_an_error(self):
        self.folder.mkdir(parents=True)
        (self.folder / "doctor-a.json").write_bytes(b"\xff\xfe\x00\x80 not utf-8")
        self.assertIsNone(self.cache.get("doctor", "a", 600))

    def test_a_folder_that_cannot_be_made_is_ignored(self):
        blocker = self.root / "blocker"
        blocker.write_text("a file where the folder should be")
        broken = FileCache(blocker / "conflu-c-cli")
        broken.put("doctor", "a", "text")  # does not raise
        self.assertIsNone(broken.get("doctor", "a", 600))

    def test_a_name_cannot_leave_the_folder(self):
        self.cache.put("../doctor", "../../a b", "text")
        written = [path for path in self.root.rglob("*") if path.is_file()]
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0].parent, self.folder)  # in the folder, whatever the names said
        self.assertNotIn("/", written[0].name)
        self.assertNotIn(" ", written[0].name)
        self.assertEqual(self.cache.get("../doctor", "../../a b", 600), "text")


class CacheDirectoryTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name)

    def test_xdg_cache_home_comes_first(self):
        environ = {"XDG_CACHE_HOME": str(self.root / "xdg"), "HOME": str(self.root / "home")}
        self.assertEqual(cache_directory(environ), self.root / "xdg" / "conflu-c-cli")

    def test_without_it_the_cache_is_below_the_home_folder(self):
        with mock.patch("pathlib.Path.home", return_value=self.root / "profile"):
            self.assertEqual(cache_directory({"HOME": str(self.root / "home")}), self.root / "home" / ".cache" / "conflu-c-cli")

    def test_the_cache_is_next_to_the_configuration_in_use(self):
        profile = self.root / "profile"
        config = profile / ".config" / "conflu-c-cli" / "config"
        config.parent.mkdir(parents=True)
        config.write_text("CONFLUENCE_SPACE=ENG\n")
        with mock.patch("pathlib.Path.home", return_value=profile):
            environ = {"HOME": str(self.root / "home")}
            self.assertEqual(config_file(environ), config)  # the configuration is found where it is
            self.assertEqual(cache_directory(environ), profile / ".cache" / "conflu-c-cli")

    def test_an_empty_xdg_variable_counts_as_not_set(self):
        with mock.patch("pathlib.Path.home", return_value=self.root / "profile"):
            self.assertEqual(cache_directory({"XDG_CACHE_HOME": "", "HOME": str(self.root / "home")}), self.root / "home" / ".cache" / "conflu-c-cli")


if __name__ == "__main__":
    unittest.main()
