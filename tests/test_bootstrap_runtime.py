"""What `conflu doctor` learns about the program itself: the launcher on the PATH, how this run started, the installer."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from conflu_c_cli.bootstrap import create_application, runtime_facts
from conflu_c_cli.version import __version__
from tests.support.fakes import RecordingDiagnostics


class RuntimeFactsTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name)

    def make_launcher(self, folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        launcher = folder / ("conflu.cmd" if os.name == "nt" else "conflu")
        launcher.write_text("echo conflu\n", encoding="utf-8")
        launcher.chmod(0o755)
        return launcher

    def test_the_launcher_is_found_on_the_path_given(self):
        launcher = self.make_launcher(self.root / "bin")
        facts = runtime_facts({"PATH": str(self.root / "bin")}, self.root)
        self.assertEqual(Path(facts["launcher"]).resolve(), launcher.resolve())

    def test_it_is_the_path_of_the_environment_that_counts_not_the_one_of_this_process(self):
        self.make_launcher(self.root / "bin")
        facts = runtime_facts({"PATH": str(self.root / "nowhere")}, self.root)
        self.assertEqual(facts["launcher"], "")

    def test_no_launcher_on_the_path_is_an_empty_text(self):
        self.assertEqual(runtime_facts({"PATH": str(self.root / "nowhere")}, self.root)["launcher"], "")
        self.assertEqual(runtime_facts({"PATH": ""}, self.root)["launcher"], "")

    def test_the_installer_is_named_only_in_a_source_checkout(self):
        (self.root / "install.py").write_text("# installer\n", encoding="utf-8")
        # an installation holds a copy of install.py too, but that copy refuses to install over itself
        self.assertEqual(runtime_facts({"PATH": ""}, self.root)["install_script"], "")
        (self.root / "src" / "conflu_c_cli").mkdir(parents=True)
        self.assertEqual(Path(runtime_facts({"PATH": ""}, self.root)["install_script"]), self.root / "install.py")
        self.assertEqual(runtime_facts({"PATH": ""}, self.root / "elsewhere")["install_script"], "")

    def test_a_source_checkout_without_the_installer_names_none(self):
        (self.root / "src" / "conflu_c_cli").mkdir(parents=True)
        self.assertEqual(runtime_facts({"PATH": ""}, self.root)["install_script"], "")

    def test_a_python_file_of_that_name_is_not_a_launcher(self):
        """Windows finds `conflu.py` when `.PY` is among its executable extensions: that is the program started by hand, not a launcher."""
        folder = self.root / "bin"
        folder.mkdir()
        (folder / "conflu.py").write_text("# the source of the program\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"PATHEXT": ".PY;.CMD;.EXE"}):
            self.assertEqual(runtime_facts({"PATH": str(folder)}, self.root)["launcher"], "")

    def test_the_rest(self):
        facts = runtime_facts({"PATH": ""}, self.root)
        self.assertEqual((facts["version"], facts["python"]), (__version__, sys.version.split()[0]))
        self.assertEqual(facts["program"], sys.argv[0])
        self.assertEqual(set(facts), {"version", "python", "launcher", "program", "install_script", "entry"})

    def test_the_entry_is_the_file_that_a_program_runs_with_python_instead_of_a_launcher(self):
        """`cmd.exe` splits the command line before `conflu.cmd` runs, so a program that passes arguments starts `python conflu.py ...`."""
        self.assertEqual(runtime_facts({"PATH": ""}, self.root)["entry"], "")  # no such file in this folder
        (self.root / "conflu.py").write_text("# the entry point\n", encoding="utf-8")
        self.assertEqual(Path(runtime_facts({"PATH": ""}, self.root)["entry"]), self.root / "conflu.py")
        self.assertEqual(runtime_facts({"PATH": ""}, self.root / "elsewhere")["entry"], "")


class LazyFactsTest(unittest.TestCase):
    """The program hands the facts to the doctor, which is the only one that asks: the PATH is not scanned for the other commands."""

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        root = Path(holder.name)
        profile = mock.patch("pathlib.Path.home", return_value=root / "profile")  # the profile folder of the person who runs the tests is no home folder here
        profile.start()
        self.addCleanup(profile.stop)
        self.environ = {"CONFLUENCE_CONFIG_FILE": str(root / "config"), "HOME": str(root), "XDG_CACHE_HOME": str(root / "cache"), "PATH": str(root / "bin")}

    def test_the_path_is_not_scanned_when_the_application_is_made_or_used_for_something_else(self):
        with mock.patch("shutil.which", side_effect=AssertionError("the PATH was scanned")):
            app = create_application(RecordingDiagnostics(), self.environ)
            self.addCleanup(app.close)
            self.assertEqual(app.settings.base_url, "")

    def test_the_doctor_gets_the_facts_with_one_scan_whatever_it_asks(self):
        scans = []

        def which(name, path=None):
            scans.append((name, path))
            return ""

        with mock.patch("shutil.which", which):
            app = create_application(RecordingDiagnostics(), self.environ)
            self.addCleanup(app.close)
            facts = app.doctor._runtime
            self.assertEqual(facts.get("launcher"), "")
            self.assertEqual(facts["version"], __version__)
            self.assertEqual(facts.get("nothing", "default"), "default")
            self.assertEqual(set(facts), {"version", "python", "launcher", "program", "install_script", "entry"})
            self.assertEqual(len(facts), 6)
        self.assertEqual(scans, [("conflu", self.environ["PATH"])])  # once, for the PATH of the environment the program was given


if __name__ == "__main__":
    unittest.main()
