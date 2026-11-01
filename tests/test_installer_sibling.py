"""install.py offers the folder that already holds the launcher of the sibling CLI (jira): both launchers belong side by side."""
import os
import subprocess
import sys
import unittest
from pathlib import Path

from tests.test_installer import ROOT, InstallerCase


class SiblingLauncherTest(InstallerCase):
    def folder_with_jira(self, name: str = "shared-launchers") -> Path:
        shared = self.root / name
        shared.mkdir()
        (shared / ("jira.cmd" if os.name == "nt" else "jira")).write_text("# the sibling launcher\n", encoding="utf-8")
        return shared

    def on_path(self, *folders: Path) -> dict:
        return {"PATH": os.pathsep.join([*(str(folder) for folder in folders), self.env.get("PATH", "")])}

    def test_the_exact_command_for_that_folder_is_printed_when_the_chosen_one_is_not_on_the_path(self):
        shared = self.folder_with_jira()
        done = self.install(env=self.on_path(shared))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("is not on the PATH of this shell", done.stdout)
        self.assertIn("the folder that holds the launcher of jira", done.stdout)
        self.assertIn(f'python install.py --bin-dir "{shared}"', done.stdout)

    def test_the_hint_of_today_is_still_there(self):
        shared = self.folder_with_jira()
        done = self.install(env=self.on_path(shared))
        self.assertIn("Call the launcher by its full path, or put the folder on your PATH:", done.stdout)
        self.assertIn("Git Bash:", done.stdout)
        self.assertIn("PowerShell:", done.stdout)
        self.assertIn("Next:", done.stdout)

    def test_nothing_is_offered_when_no_folder_on_the_path_holds_it(self):
        done = self.install(env={"PATH": str(self.root / "nowhere")})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("is not on the PATH of this shell", done.stdout)
        self.assertNotIn("launcher of jira", done.stdout)

    def test_a_folder_that_holds_the_launcher_but_is_not_on_the_path_is_not_offered(self):
        self.folder_with_jira()
        done = self.install(env={"PATH": str(self.root / "nowhere")})
        self.assertNotIn("launcher of jira", done.stdout)

    def test_the_chosen_folder_is_not_offered_again_and_needs_no_note(self):
        self.bin.mkdir()
        (self.bin / ("jira.cmd" if os.name == "nt" else "jira")).write_text("# the sibling launcher\n", encoding="utf-8")
        done = self.install(env=self.on_path(self.bin))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotIn("launcher of jira", done.stdout)
        self.assertNotIn("is not on the PATH", done.stdout)

    def test_the_first_folder_on_the_path_that_holds_it_is_the_one(self):
        first, second = self.folder_with_jira("first"), self.folder_with_jira("second")
        done = self.install(env=self.on_path(first, second))
        self.assertIn(f'python install.py --bin-dir "{first}"', done.stdout)
        self.assertNotIn(str(second), done.stdout)

    @unittest.skipIf(os.name == "nt", "a folder is made read-only by its mode on Unix; on Windows the installer tries to write a file")
    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can write everywhere")
    def test_a_folder_that_this_user_cannot_write_to_is_not_offered(self):
        shared = self.folder_with_jira()
        shared.chmod(0o555)
        self.addCleanup(shared.chmod, 0o755)
        done = self.install(env={"PATH": str(shared)})  # nothing else on the PATH, so a launcher of the sibling that really is there cannot be offered instead
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotIn("launcher of jira", done.stdout)

    def test_the_command_it_prints_does_install_there(self):
        shared = self.folder_with_jira()
        env = self.on_path(shared)
        self.assertIn(f'--bin-dir "{shared}"', self.install(env=env).stdout)
        done = subprocess.run(  # into another folder for the program: an installation that was just started is not renamed away on Windows
            [sys.executable, "-B", str(ROOT / "install.py"), "--prefix", str(self.root / "second-app"), "--bin-dir", str(shared)],
            capture_output=True, text=True, env={**self.env, **env}, timeout=120,
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue((shared / ("conflu.cmd" if os.name == "nt" else "conflu")).is_file())
        self.assertTrue((shared / ("jira.cmd" if os.name == "nt" else "jira")).is_file())  # the sibling's launcher is not touched
        self.assertNotIn("is not on the PATH", done.stdout)  # the folder is on the PATH: there is nothing left to say


if __name__ == "__main__":
    unittest.main()
