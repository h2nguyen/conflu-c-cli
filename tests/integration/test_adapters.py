"""The file adapters: config file, files, bundled documentation and the file locations."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from conflu_c_cli.adapters.driven.file_config import FileConfigStore, parse_value
from conflu_c_cli.adapters.driven.local_docs import LocalDocs, find_root
from conflu_c_cli.adapters.driven.paths import active_home, config_file, home_directories
from conflu_c_cli.adapters.driven.system import LocalFiles, SystemClock
from conflu_c_cli.bootstrap import effective_values
from conflu_c_cli.domain.errors import ConfigError, NotFoundError, ValidationError


WINDOWS_ONLY = unittest.skipUnless(os.name == "nt", "the home drive is a Windows setting")


class Folder(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name)


class ConfigStoreTest(Folder):
    def setUp(self):
        super().setUp()
        self.path = self.root / "conf" / "config"
        self.store = FileConfigStore(self.path)

    def write(self, text):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(text, encoding="utf-8")

    def test_a_missing_file_is_empty(self):
        self.assertEqual(self.store.load(), {})

    def test_round_trip_with_awkward_values(self):
        values = {"CONFLUENCE_BASE_URL": "https://example.atlassian.net/wiki", "CONFLUENCE_CA_BUNDLE": "C:/certs/my ca.pem", "CONFLUENCE_EMAIL": "o'brien", "CONFLUENCE_API_TOKEN": "a$b`c\"d"}
        for key, value in values.items():
            self.store.set(key, value)
        self.assertEqual(self.store.load(), values)

    def test_set_replaces_and_keeps_the_other_lines(self):
        self.write("# my settings\nCONFLUENCE_SPACE=OLD\nCONFLUENCE_RETRY=3\n")
        self.store.set("CONFLUENCE_SPACE", "ENG")
        self.assertEqual(self.path.read_text(encoding="utf-8").splitlines(), ["# my settings", "CONFLUENCE_RETRY=3", "CONFLUENCE_SPACE=ENG"])

    def test_unset(self):
        self.write("CONFLUENCE_SPACE=ENG\nCONFLUENCE_RETRY=3\n")
        self.assertTrue(self.store.unset("CONFLUENCE_SPACE"))
        self.assertEqual(self.store.load(), {"CONFLUENCE_RETRY": "3"})
        stamp = self.path.stat().st_mtime_ns
        self.assertFalse(self.store.unset("CONFLUENCE_SPACE"))
        self.assertEqual(self.path.stat().st_mtime_ns, stamp)  # nothing to remove: the file is left alone

    def test_the_shell_style_format_is_read(self):
        self.write("\ufeff# comment\n\nCONFLUENCE_API_TOKEN=abc123\nexport CONFLUENCE_SPACE=ENG\nCONFLUENCE_CA_BUNDLE='C:/a b/ca.pem'\nCONFLUENCE_EMAIL=\"jdoe\"\nCONFLUENCE_X=value # note\nCONFLUENCE_Y=a\\ b\n  CONFLUENCE_Z=z\n")
        self.assertEqual(
            self.store.load(),
            {"CONFLUENCE_API_TOKEN": "abc123", "CONFLUENCE_SPACE": "ENG", "CONFLUENCE_CA_BUNDLE": "C:/a b/ca.pem", "CONFLUENCE_EMAIL": "jdoe", "CONFLUENCE_X": "value", "CONFLUENCE_Y": "a b", "CONFLUENCE_Z": "z"},
        )

    def test_the_file_is_data_and_is_never_executed(self):
        for text in (
            "CONFLUENCE_API_TOKEN=$(echo hi)", "CONFLUENCE_API_TOKEN=`echo hi`", "CONFLUENCE_API_TOKEN=$'a\\nb'", 'CONFLUENCE_API_TOKEN="x $(echo hi)"', 'CONFLUENCE_API_TOKEN="$HOME/ca.pem"',
            "CONFLUENCE_API_TOKEN=${TOKEN}", "CONFLUENCE_API_TOKEN=$TOKEN", "CONFLUENCE_API_TOKEN=$$", "CONFLUENCE_API_TOKEN=$?", "CONFLUENCE_API_TOKEN=$@", "CONFLUENCE_API_TOKEN=$!", "CONFLUENCE_API_TOKEN=$*", "CONFLUENCE_API_TOKEN=$#",
            "CONFLUENCE_CA_BUNDLE=~/certs/ca.pem", "CONFLUENCE_CA_BUNDLE=~", "CONFLUENCE_CA_BUNDLE=a:~/b",
        ):
            with self.subTest(text=text):
                self.write(text + "\n")
                with self.assertRaises(ConfigError):
                    self.store.load()

    def test_what_a_shell_takes_literally_is_kept_literally(self):
        self.write("CONFLUENCE_A='$(not run) `nor this` $HOME'\nCONFLUENCE_B=\\$HOME\nCONFLUENCE_C=value # a $(comment)\nCONFLUENCE_D=\"cost: 5$\"\nCONFLUENCE_E='it'\"'\"'s'\nCONFLUENCE_F='~/x'\nCONFLUENCE_G=a~b\nCONFLUENCE_H=\"~/x\"\nCONFLUENCE_I=\\~\n")
        self.assertEqual(
            self.store.load(),
            {"CONFLUENCE_A": "$(not run) `nor this` $HOME", "CONFLUENCE_B": "$HOME", "CONFLUENCE_C": "value", "CONFLUENCE_D": "cost: 5$", "CONFLUENCE_E": "it's", "CONFLUENCE_F": "~/x", "CONFLUENCE_G": "a~b", "CONFLUENCE_H": "~/x", "CONFLUENCE_I": "~"},
        )

    def test_a_failed_write_keeps_the_old_file_and_leaves_no_copy_of_the_token_behind(self):
        self.store.set("CONFLUENCE_API_TOKEN", "the-first-token")
        with mock.patch("os.replace", side_effect=OSError("disk says no")), self.assertRaises(ConfigError):
            self.store.set("CONFLUENCE_API_TOKEN", "the-second-token")
        self.assertEqual(self.store.load(), {"CONFLUENCE_API_TOKEN": "the-first-token"})
        self.assertEqual([entry.name for entry in self.path.parent.iterdir()], ["config"])

    @unittest.skipIf(os.name == "nt", "Windows has no Unix permissions")
    def test_the_file_with_the_token_is_private(self):
        self.store.set("CONFLUENCE_API_TOKEN", "secret")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_broken_lines_are_config_errors(self):
        for text in ("CONFLUENCE_API_TOKEN='open", "CONFLUENCE_API_TOKEN=two words"):
            with self.subTest(text=text):
                self.write(text + "\n")
                with self.assertRaises(ConfigError):
                    self.store.load()

    def test_writing_leaves_no_temporary_files(self):
        self.store.set("CONFLUENCE_SPACE", "ENG")
        self.store.set("CONFLUENCE_RETRY", "1")
        self.assertEqual([entry.name for entry in self.path.parent.iterdir()], ["config"])

    def test_the_dollar_sign_in_a_value_is_kept_not_expanded(self):
        self.assertEqual(parse_value("X", "'a$HOME'"), "a$HOME")

    def test_path(self):
        self.assertEqual(self.store.path, str(self.path))


class FilesTest(Folder):
    def setUp(self):
        super().setUp()
        self.files = LocalFiles()

    def test_write_creates_folders_with_plain_newlines(self):
        target = self.root / "a" / "b" / "out.txt"
        self.files.write_text(str(target), "one\ntwo\n")
        self.assertEqual(target.read_bytes(), b"one\ntwo\n")

    def test_a_write_replaces_the_file_completely_or_not_at_all(self):
        target = self.root / "dump.json"
        self.files.write_text(str(target), "first dump")
        self.files.write_text(str(target), "second dump")
        self.assertEqual(target.read_text(), "second dump")
        with mock.patch("os.replace", side_effect=OSError("the disk went away")), self.assertRaises(ValidationError):
            self.files.write_text(str(target), "interrupted")
        self.assertEqual(target.read_text(), "second dump")
        self.assertEqual(sorted(entry.name for entry in self.root.iterdir()), ["dump.json"])  # no temporary file left

    @unittest.skipIf(os.name == "nt", "Windows has no Unix permissions")
    def test_a_written_file_is_not_private_unless_it_has_to_be(self):
        target = self.root / "shared.json"
        self.files.write_text(str(target), "x")
        self.assertEqual(target.stat().st_mode & 0o044, 0o044)  # readable by group and others, as the umask allows

    def test_bytes_round_trip_and_size(self):
        target = self.root / "x" / "data.bin"
        self.files.write_bytes(str(target), b"\x00\xff data")
        self.assertEqual(self.files.read_bytes(str(target)), b"\x00\xff data")
        self.assertEqual(self.files.size(str(target)), 7)

    def test_a_failed_binary_write_keeps_the_old_file(self):
        target = self.root / "picture.png"
        self.files.write_bytes(str(target), b"old")
        with mock.patch("os.replace", side_effect=OSError("the disk went away")), self.assertRaises(ValidationError):
            self.files.write_bytes(str(target), b"new")
        self.assertEqual(target.read_bytes(), b"old")
        self.assertEqual([entry.name for entry in self.root.iterdir()], ["picture.png"])

    def test_missing_files_are_validation_errors_for_bytes_and_size_too(self):
        for call in (self.files.read_bytes, self.files.size):
            with self.assertRaises(ValidationError):
                call(str(self.root / "missing.bin"))
        with self.assertRaises(ValidationError):
            self.files.list_matching(str(self.root / "missing"), "*.md")

    def test_text_with_lone_surrogates_is_written_not_crashed_on(self):
        target = self.root / "odd.md"
        self.files.write_text(str(target), "a\ud800b")
        self.assertEqual(target.read_text(encoding="utf-8"), "a?b")

    def test_read_errors_are_validation_errors(self):
        with self.assertRaises(ValidationError):
            self.files.read_text(str(self.root / "missing.txt"))
        binary = self.root / "binary"
        binary.write_bytes(b"\xff\xfe\x00\x80")
        with self.assertRaises(ValidationError):
            self.files.read_text(str(binary))

    def test_byte_order_mark(self):
        target = self.root / "bom.csv"
        target.write_bytes("\ufeffa,b\n".encode("utf-8"))
        self.assertEqual(self.files.read_text(str(target), "utf-8-sig"), "a,b\n")

    def test_windows_line_endings_are_normalised_on_read(self):
        target = self.root / "crlf.md"
        target.write_bytes(b"---\r\nsummary: x\r\n---\r\nbody\r\n")
        self.assertEqual(self.files.read_text(str(target)), "---\nsummary: x\n---\nbody\n")

    def test_listing(self):
        for name in ("002-b.md", "001-a.md", "notes.txt", "010-c.md", "x-001.md"):
            (self.root / name).write_text("x")
        (self.root / "003-dir.md").mkdir()
        found = [self.files.name(path) for path in self.files.list_matching(str(self.root), "[0-9][0-9][0-9]-*.md")]
        self.assertEqual(found, ["001-a.md", "002-b.md", "010-c.md"])
        self.assertTrue(self.files.is_dir(str(self.root)) and self.files.exists(str(self.root / "notes.txt")))
        self.assertFalse(self.files.exists(str(self.root / "nope")))

    def test_clock_is_utc(self):
        self.assertEqual(SystemClock().now().utcoffset().total_seconds(), 0)


class DocsTest(Folder):
    def setUp(self):
        super().setUp()
        (self.root / "docs" / "how-to").mkdir(parents=True)
        (self.root / "docs" / "reference").mkdir()
        (self.root / "skills" / "conflu-c-cli").mkdir(parents=True)
        (self.root / "README.md").write_text("# Readme\n", encoding="utf-8")
        (self.root / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
        (self.root / "docs" / "how-to" / "daily-workflow.md").write_text("# The daily workflow\n\ntext\n", encoding="utf-8")
        (self.root / "docs" / "reference" / "exit-codes.md").write_text("<!-- generated -->\n# Exit codes\n", encoding="utf-8")
        (self.root / "docs" / "architecture.md").write_text("# Architecture\n", encoding="utf-8")
        (self.root / "skills" / "conflu-c-cli" / "SKILL.md").write_text("---\nname: conflu-c-cli\n---\n", encoding="utf-8")
        self.docs = LocalDocs(self.root)

    def test_topics_and_titles(self):
        self.assertEqual([(topic.name, topic.title) for topic in self.docs.topics()], [("architecture", "Architecture"), ("daily-workflow", "The daily workflow"), ("exit-codes", "Exit codes")])

    def test_topic_lookup_is_forgiving(self):
        self.assertIn("text", self.docs.topic("Daily-Workflow"))
        self.assertIn("text", self.docs.topic("daily-workflow.md"))
        with self.assertRaises(NotFoundError) as caught:
            self.docs.topic("nope")
        self.assertIn("conflu how-to", caught.exception.hint)

    def test_readme_changelog_skill(self):
        self.assertEqual(self.docs.readme(), "# Readme\n")
        self.assertEqual(self.docs.changelog(), "# Changelog\n")
        self.assertIn("name: conflu-c-cli", self.docs.skill())

    def test_a_missing_file_says_how_to_fix_it(self):
        (self.root / "README.md").unlink()
        with self.assertRaises(NotFoundError) as caught:
            self.docs.readme()
        self.assertIn("CONFLUENCE_CLI_HOME", caught.exception.hint)

    def test_root_override(self):
        with mock.patch.dict(os.environ, {"CONFLUENCE_CLI_HOME": str(self.root)}):
            self.assertEqual(find_root(), self.root)

    def test_the_root_is_found_from_the_source_tree(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CONFLUENCE_CLI_HOME", None)
            self.assertTrue((find_root() / "VERSION").is_file())


class PathsTest(Folder):
    def setUp(self):
        super().setUp()
        self.home = self.root / "home"
        self.profile = self.root / "profile"
        self.env = {"HOME": str(self.home)}
        patcher = mock.patch("pathlib.Path.home", return_value=self.profile)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make(self, base):
        target = base / ".config" / "conflu-c-cli" / "config"
        target.parent.mkdir(parents=True)
        target.write_text("x")
        return target

    def test_explicit_file_wins(self):
        self.assertEqual(config_file({**self.env, "CONFLUENCE_CONFIG_FILE": "x/y"}), Path("x/y"))

    def test_a_new_file_goes_where_home_points(self):
        self.assertEqual(config_file(self.env), self.home / ".config" / "conflu-c-cli" / "config")

    def test_without_home_the_profile_is_used(self):
        self.assertEqual(config_file({}), self.profile / ".config" / "conflu-c-cli" / "config")

    def test_an_existing_file_in_the_profile_is_found_when_home_has_none(self):
        existing = self.make(self.profile)
        self.assertEqual(config_file(self.env), existing)

    def test_home_beats_the_profile_when_both_exist(self):
        existing = self.make(self.home)
        self.make(self.profile)
        self.assertEqual(config_file(self.env), existing)

    def test_xdg_comes_first(self):
        xdg = self.root / "xdg"
        target = xdg / "conflu-c-cli" / "config"
        target.parent.mkdir(parents=True)
        target.write_text("x")
        self.make(self.home)
        self.assertEqual(config_file({**self.env, "XDG_CONFIG_HOME": str(xdg)}), target)

    def home_drive(self, name="mapped", create=True):
        """The home drive and path of a managed Windows laptop (`H:` and `\\...`), without HOME, as PowerShell and cmd see them."""
        folder = self.root / name
        if create:
            folder.mkdir()
        drive, rest = os.path.splitdrive(str(folder))
        return folder, {"HOMEDRIVE": drive, "HOMEPATH": rest}

    @WINDOWS_ONLY
    def test_powershell_finds_the_configuration_that_git_bash_made(self):
        folder, env = self.home_drive()
        existing = self.make(folder)
        self.make(self.profile)
        self.assertEqual(config_file(env), existing)

    @WINDOWS_ONLY
    def test_without_home_a_new_file_goes_where_git_bash_would_put_it(self):
        folder, env = self.home_drive()
        self.assertEqual(config_file(env), folder / ".config" / "conflu-c-cli" / "config")

    @WINDOWS_ONLY
    def test_the_profile_is_still_found_when_the_home_drive_has_no_file(self):
        _, env = self.home_drive()
        existing = self.make(self.profile)
        self.assertEqual(config_file(env), existing)

    @WINDOWS_ONLY
    def test_the_home_in_use_is_the_one_that_holds_the_configuration(self):
        _, env = self.home_drive()
        self.make(self.profile)
        self.assertEqual(active_home(env), self.profile)

    @WINDOWS_ONLY
    def test_a_home_drive_that_is_not_there_is_skipped(self):
        _, env = self.home_drive("missing", create=False)
        self.assertEqual(config_file(env), self.profile / ".config" / "conflu-c-cli" / "config")

    @WINDOWS_ONLY
    def test_a_malformed_home_path_is_skipped(self):
        """HOMEPATH always starts with a separator; `H:` + `C:\\Users\\x` would be a path nobody means."""
        folder, env = self.home_drive()
        self.assertEqual(home_directories({"HOMEDRIVE": env["HOMEDRIVE"], "HOMEPATH": folder.name}), [self.profile])

    def test_only_a_drive_letter_counts_as_a_home_drive(self):
        """Nothing outside Windows has these variables; if somebody sets them to paths they are not a home folder."""
        (self.root / "tmp").mkdir()
        self.assertEqual(home_directories({"HOMEDRIVE": str(self.root), "HOMEPATH": os.sep + "tmp"}), [self.profile])
        self.assertEqual(home_directories({"HOMEDRIVE": "/", "HOMEPATH": "/tmp"}), [self.profile])

    @WINDOWS_ONLY
    def test_with_home_set_the_home_drive_is_not_even_looked_at(self):
        """Git Bash has HOME: probing a network drive as well would only add a wait."""
        folder, env = self.home_drive()
        self.assertEqual(home_directories({**env, "HOME": str(self.home)}), [self.home, self.profile])
        self.assertEqual(home_directories({**env, "HOME": str(self.profile)}), [self.profile])

    @WINDOWS_ONLY
    def test_without_home_the_home_drive_comes_before_the_profile(self):
        folder, env = self.home_drive()
        self.assertEqual(home_directories(env), [folder, self.profile])
        self.assertEqual(home_directories({}), [self.profile])


class EffectiveValuesTest(unittest.TestCase):
    def test_the_environment_wins_and_only_known_names_count(self):
        values = effective_values({"CONFLUENCE_SPACE": "FILE", "CONFLUENCE_RETRY": "1"}, {"CONFLUENCE_SPACE": "ENV", "PATH": "x", "CONFLUENCE_UNKNOWN": "y"})
        self.assertEqual(values, {"CONFLUENCE_SPACE": "ENV", "CONFLUENCE_RETRY": "1"})

    def test_an_empty_variable_is_not_set_so_it_cannot_switch_off_a_policy_of_the_file(self):
        values = effective_values({"CONFLUENCE_HIDE_USERS": "true", "CONFLUENCE_SPACE": "FILE"}, {"CONFLUENCE_HIDE_USERS": "", "CONFLUENCE_SPACE": ""})
        self.assertEqual(values, {"CONFLUENCE_HIDE_USERS": "true", "CONFLUENCE_SPACE": "FILE"})


if __name__ == "__main__":
    unittest.main()
