"""install.py: install, update, uninstall, and the launchers it writes."""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
WINDOWS_ONLY = unittest.skipUnless(os.name == "nt", "the home drive is a Windows setting")


def load_installer():
    spec = importlib.util.spec_from_file_location("conflu_installer", ROOT / "install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InstallerCase(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name)
        self.app = self.root / "app"
        self.bin = self.root / "bin"
        self.env = {key: value for key, value in os.environ.items() if not key.startswith(("CONFLUENCE_", "PYTHON")) and key not in ("HOMEDRIVE", "HOMEPATH")}
        # Every place the program takes for a home or local folder points into the temporary folder: --purge and the
        # defaults must never reach the real ones.
        self.env.update(
            HOME=str(self.root),
            USERPROFILE=str(self.root / "profile"),
            LOCALAPPDATA=str(self.root / "local"),
            XDG_CONFIG_HOME=str(self.root / "xdg"),
            XDG_CACHE_HOME=str(self.root / "cache"),
        )

    def install(self, *extra, env=None):
        return subprocess.run(
            [sys.executable, "-B", str(ROOT / "install.py"), "--prefix", str(self.app), "--bin-dir", str(self.bin), *extra],
            capture_output=True, text=True, env={**self.env, **(env or {})}, timeout=120,
        )

    def uninstall(self, *extra, env=None):
        return self.install("--uninstall", *extra, env=env)

    def launcher(self):
        return self.bin / ("conflu.cmd" if os.name == "nt" else "conflu")

    def run_launcher(self, *argv, env=None, cwd=None):
        return subprocess.run([str(self.launcher()), *argv], capture_output=True, text=True, env={**self.env, **(env or {})}, cwd=cwd or self.root, timeout=60)


class InstallTest(InstallerCase):
    def test_the_program_is_copied_and_the_launchers_work(self):
        done = self.install()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(f"Installed conflu-c-cli {VERSION}.", done.stdout)
        for name in ("conflu.py", "install.py", "VERSION", "README.md", "CHANGELOG.md", "LICENSE"):
            self.assertTrue((self.app / name).is_file(), name)
        self.assertTrue((self.app / "conflu_c_cli" / "__init__.py").is_file())
        self.assertTrue((self.app / "conflu_c_cli" / "adapters" / "driving" / "cli" / "commands" / "pages.py").is_file())
        for left_out in ("tests", "scripts", "src", ".gitignore", ".github"):
            self.assertFalse((self.app / left_out).exists(), left_out)
        other_folder = self.root / "somewhere" / "else"
        other_folder.mkdir(parents=True)
        self.assertEqual(self.run_launcher("version", cwd=other_folder).stdout, f"conflu-c-cli {VERSION}\n")

    def test_the_launchers_start_the_python_that_ran_the_installer_in_isolated_utf8_mode(self):
        self.install()
        text = self.launcher().read_text(encoding="utf-8")
        self.assertIn("conflu-c-cli launcher, written by install.py", text)
        self.assertIn(" -I -X utf8 ", text)
        self.assertIn(str(Path(sys.executable)) if os.name == "nt" else Path(sys.executable).as_posix(), text)
        if os.name == "nt":
            self.assertTrue((self.bin / "conflu").is_file())  # Git Bash needs the sh launcher too
            self.assertEqual((self.bin / "conflu").read_bytes().count(b"\r"), 0)  # and plain line ends

    def test_a_dry_run_changes_nothing(self):
        done = self.install("--dry-run")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Dry run: nothing was changed.", done.stdout)
        self.assertFalse(self.app.exists() or self.bin.exists())

    def test_an_update_replaces_the_program_completely_and_keeps_the_configuration(self):
        config = self.root / "xdg" / "conflu-c-cli" / "config"
        config.parent.mkdir(parents=True)
        config.write_text("CONFLUENCE_SPACE=ENG\n")
        self.install()
        (self.app / "conflu_c_cli" / "removed_module.py").write_text("# from an older version\n")
        (self.app / "stale.txt").write_text("stale")
        self.assertEqual(self.install().returncode, 0)
        self.assertFalse((self.app / "conflu_c_cli" / "removed_module.py").exists())
        self.assertFalse((self.app / "stale.txt").exists())
        self.assertEqual(config.read_text(), "CONFLUENCE_SPACE=ENG\n")
        self.assertEqual([entry.name for entry in self.root.iterdir() if ".new-" in entry.name or ".old-" in entry.name], [])

    def test_a_folder_that_is_not_an_installation_is_refused_and_with_force_moved_aside(self):
        self.app.mkdir()
        (self.app / "precious.txt").write_text("mine")
        refused = self.install()
        self.assertEqual(refused.returncode, 1)
        self.assertIn("not an installation of conflu-c-cli", refused.stderr)
        self.assertTrue((self.app / "precious.txt").is_file())
        self.assertFalse(self.bin.exists())
        forced = self.install("--force")
        self.assertEqual(forced.returncode, 0, forced.stderr)
        kept = [entry for entry in self.root.iterdir() if entry.name.startswith("app.old-")]
        self.assertEqual(len(kept), 1)
        self.assertEqual((kept[0] / "precious.txt").read_text(), "mine")  # moved, never deleted
        self.assertIn("was kept in", forced.stdout)

    def test_a_launcher_that_is_not_ours_is_refused_before_anything_changes(self):
        self.bin.mkdir()
        (self.bin / self.launcher().name).write_text("my own script\n")
        refused = self.install()
        self.assertEqual(refused.returncode, 1)
        self.assertIn("is not a conflu-c-cli launcher", refused.stderr)
        self.assertFalse(self.app.exists())
        self.assertEqual((self.bin / self.launcher().name).read_text(), "my own script\n")
        self.assertEqual(self.install("--force").returncode, 0)
        self.assertIn("written by install.py", self.launcher().read_text(encoding="utf-8"))

    def test_the_source_folder_cannot_be_the_target(self):
        done = subprocess.run([sys.executable, "-B", str(ROOT / "install.py"), "--prefix", str(ROOT), "--bin-dir", str(self.bin)], capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(done.returncode, 1)
        self.assertIn("source folder", done.stderr)

    def test_the_path_is_explained_when_the_launchers_are_not_on_it(self):
        done = self.install()
        self.assertIn("is not on the PATH of this shell", done.stdout)
        self.assertIn("Next:", done.stdout)
        self.assertIn("conflu doctor", done.stdout)

    def test_the_documentation_travels_with_the_program(self):
        if not (ROOT / "docs").is_dir():
            self.skipTest("no docs yet")
        self.install()
        done = self.run_launcher("how-to")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("configure", done.stdout)
        self.assertIn("name: conflu-c-cli", self.run_launcher("skill").stdout)

    def test_the_installation_can_be_checked_without_a_configuration(self):
        self.install()
        done = self.run_launcher("doctor", "--json")
        self.assertEqual(done.returncode, 1)  # nothing is configured in the temporary home
        self.assertIn('"ok":false', done.stdout.replace(" ", ""))


class UninstallTest(InstallerCase):
    def config(self):
        path = self.root / "xdg" / "conflu-c-cli" / "config"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("CONFLUENCE_API_TOKEN=secret\n")
        return path

    def test_the_program_and_the_launchers_go_and_the_configuration_stays(self):
        self.install()
        config = self.config()
        done = self.uninstall()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse(self.app.exists())
        self.assertFalse((self.bin / "conflu").exists() or (self.bin / "conflu.cmd").exists())
        self.assertTrue(config.is_file())
        self.assertIn("The configuration was kept", done.stdout)

    def test_purge_also_deletes_the_configuration_and_its_empty_folder(self):
        self.install()
        config = self.config()
        done = self.uninstall("--purge")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse(config.exists() or config.parent.exists())

    def test_purge_keeps_a_folder_that_holds_something_else(self):
        self.install()
        config = self.config()
        (config.parent / "notes.txt").write_text("not ours")
        self.uninstall("--purge")
        self.assertFalse(config.exists())
        self.assertTrue((config.parent / "notes.txt").is_file())

    def cache(self, base="cache"):
        path = self.root / base / "conflu-c-cli" / "doctor-0123456789abcdef.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"at": "2026-10-15T08:00:00+00:00", "checks": []}')
        return path

    def test_purge_also_deletes_the_cache_and_its_empty_folder(self):
        self.install()
        config, cache = self.config(), self.cache()
        done = self.uninstall("--purge")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse(cache.exists() or cache.parent.exists())
        self.assertFalse(config.exists() or config.parent.exists())

    def test_the_cache_in_every_place_the_program_looks_goes(self):
        self.install()
        in_home = self.root / ".cache" / "conflu-c-cli" / "doctor-fedcba9876543210.json"
        in_home.parent.mkdir(parents=True)
        in_home.write_text("{}")
        elsewhere = self.cache()
        self.uninstall("--purge")
        self.assertFalse(elsewhere.exists() or in_home.exists())

    def test_a_cache_is_kept_without_purge(self):
        self.install()
        cache = self.cache()
        done = self.uninstall()
        self.assertTrue(cache.is_file())
        self.assertIn("with the token and the cache", done.stdout)

    def test_purge_keeps_what_else_lies_in_the_cache_folder(self):
        self.install()
        cache = self.cache()
        (cache.parent / "notes.txt").write_text("not ours")
        (cache.parent / "other.txt").write_text("not ours either")
        self.uninstall("--purge")
        self.assertFalse(cache.exists())
        self.assertTrue((cache.parent / "notes.txt").is_file() and (cache.parent / "other.txt").is_file())  # only the *.json files are the program's

    def test_a_dry_run_purge_removes_no_cache(self):
        self.install()
        cache = self.cache()
        done = self.uninstall("--dry-run", "--purge")
        self.assertIn(str(cache), done.stdout)
        self.assertTrue(cache.is_file())

    def test_a_folder_of_another_name_is_not_a_cache_of_the_program(self):
        self.install()
        other = self.root / "cache" / "another-program" / "doctor-1.json"
        other.parent.mkdir(parents=True)
        other.write_text("{}")
        self.uninstall("--purge")
        self.assertTrue(other.is_file())

    def test_purge_never_touches_the_folder_of_an_explicit_configuration_file(self):
        folder = self.root / "kept" / "conflu-c-cli"
        folder.mkdir(parents=True)
        explicit = folder / "config"
        explicit.write_text("CONFLUENCE_SPACE=ENG\n")
        self.install()
        self.uninstall("--purge", env={"CONFLUENCE_CONFIG_FILE": str(explicit)})
        self.assertFalse(explicit.exists())
        self.assertTrue(folder.is_dir())

    def test_a_dry_run_removes_nothing(self):
        self.install()
        config = self.config()
        done = self.uninstall("--dry-run", "--purge")
        self.assertIn("Would remove", done.stdout)
        self.assertTrue(self.app.is_dir() and self.launcher().is_file() and config.is_file())

    def test_only_what_is_recognised_is_removed(self):
        self.app.mkdir()
        (self.app / "conflu.py").write_text("# a lone file is not an installation\n")
        self.bin.mkdir()
        other = self.bin / "conflu"
        other.write_text("#!/bin/sh\n# written by somebody else\nexec something-else\n")
        done = self.uninstall()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("does not look like an installation", done.stdout)
        self.assertTrue((self.app / "conflu.py").is_file() and other.is_file())

    def test_a_launcher_that_starts_another_installation_stays(self):
        self.install()
        elsewhere = self.root / "second"
        done = subprocess.run([sys.executable, "-B", str(ROOT / "install.py"), "--uninstall", "--prefix", str(elsewhere), "--bin-dir", str(self.bin)], capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Nothing to remove.", done.stdout)
        self.assertTrue(self.launcher().is_file() and self.app.is_dir())


class DefaultPlacesTest(InstallerCase):
    def dry_run(self, **env):
        done = subprocess.run([sys.executable, "-B", str(ROOT / "install.py"), "--dry-run"], capture_output=True, text=True, env={**self.env, **env}, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_the_defaults_keep_the_program_on_a_local_disk_and_the_launchers_in_the_home_folder(self):
        out = self.dry_run()
        expected = self.root / "local" / "conflu-c-cli" if os.name == "nt" else self.root / ".local" / "share" / "conflu-c-cli"
        self.assertIn(f"Install to:  {expected}", out)
        self.assertIn(str(self.root / "bin" / "conflu"), out)

    def test_environment_variables_choose_the_places(self):
        program, launchers = self.root / "elsewhere" / "program", self.root / "elsewhere" / "launchers"
        out = self.dry_run(CONFLUENCE_CLI_INSTALL_DIR=str(program), CONFLUENCE_CLI_BIN_DIR=str(launchers))
        self.assertIn(f"Install to:  {program}", out)
        self.assertIn(str(launchers / "conflu"), out)

    def test_a_mapped_network_drive_is_kept_as_written(self):
        """`Path.resolve()` turns H:\\ into \\\\server\\share\\...; the launchers must keep the drive letter."""
        installer = load_installer()
        self.assertEqual(os.fspath(installer.absolute(r"H:\bin")), os.path.abspath(r"H:\bin"))

    def test_the_home_folders_follow_the_program(self):
        installer = load_installer()
        profile = self.root / "profile"
        with mock.patch("pathlib.Path.home", return_value=profile), mock.patch.dict(os.environ, {"HOME": str(self.root / "home")}, clear=False):
            self.assertEqual(installer.home_directories(), [self.root / "home", profile])
        with mock.patch("pathlib.Path.home", return_value=profile), mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(installer.home_directories(), [profile])

    @WINDOWS_ONLY
    def test_without_home_the_launchers_go_to_the_home_drive_like_in_git_bash(self):
        folder = self.root / "mapped"
        folder.mkdir()
        drive, rest = os.path.splitdrive(str(folder))
        env = {key: value for key, value in self.env.items() if key != "HOME"}
        env.update(HOMEDRIVE=drive, HOMEPATH=rest)
        done = subprocess.run([sys.executable, "-B", str(ROOT / "install.py"), "--dry-run"], capture_output=True, text=True, env=env, timeout=60)
        self.assertIn(str(folder / "bin" / "conflu"), done.stdout)


class LauncherTextTest(unittest.TestCase):
    def test_the_launchers(self):
        installer = load_installer()
        python, app, bin_dir = Path("C:/Python/python.exe"), Path("C:/app/conflu-c-cli"), Path("C:/home/bin")
        windows = installer.launchers(python, app, bin_dir, True)
        sh, cmd = windows[bin_dir / "conflu"], windows[bin_dir / "conflu.cmd"]
        self.assertEqual(sh[1], "\n")
        self.assertEqual(cmd[1], "\r\n")
        self.assertIn('exec "C:/Python/python.exe" -I -X utf8 "C:/app/conflu-c-cli/conflu.py" "$@"', sh[0])
        self.assertIn("-I -X utf8", cmd[0])
        self.assertIn("exit /b %ERRORLEVEL%", cmd[0])
        self.assertEqual(list(installer.launchers(python, app, bin_dir, False)), [bin_dir / "conflu"])
        for text, _ in windows.values():
            self.assertIn(installer.SIGNATURE, text)


if __name__ == "__main__":
    unittest.main()
