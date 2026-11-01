"""The command modules are imported when they are needed, and the table that says which module has which command is what the modules declare."""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from conflu_c_cli.adapters.driving.cli import registry
from conflu_c_cli.adapters.driving.cli.commands import MODULE_NAMES, WHERE, load
from conflu_c_cli.adapters.driving.cli.registry import all_commands, find_command

ROOT = Path(__file__).resolve().parents[2]
COMMANDS_PACKAGE = "conflu_c_cli.adapters.driving.cli.commands"


class TheTableIsWhatTheModulesDeclareTest(unittest.TestCase):
    def test_every_name_and_alias_is_listed_with_its_module_and_nothing_else(self):
        declared = {}
        for name in MODULE_NAMES:
            for command in load(name).COMMANDS:
                for key in (command.name, *command.aliases):
                    self.assertNotIn(key, declared, f"{key} is declared twice")
                    declared[key] = name
        self.assertEqual(WHERE, declared, "adapters/driving/cli/commands/__init__.py: the table WHERE is not what the command modules declare")

    def test_the_modules_are_the_files_of_the_folder_and_the_attribute_for_all_of_them_still_works(self):
        from conflu_c_cli.adapters.driving.cli import commands

        on_disk = {path.stem for path in (ROOT / "src" / "conflu_c_cli" / "adapters" / "driving" / "cli" / "commands").glob("*.py") if not path.stem.startswith("_")}
        self.assertEqual(on_disk, set(MODULE_NAMES))
        self.assertEqual([module.__name__.rpartition(".")[2] for module in commands.MODULES], list(MODULE_NAMES))
        with self.assertRaises(AttributeError):
            commands.NOT_THERE  # noqa: B018

    def test_every_command_is_found_by_its_name_and_by_each_alias(self):
        for command in all_commands():
            for key in (command.name, *command.aliases, command.name.upper(), f"  {command.name} "):
                with self.subTest(key=key):
                    self.assertIs(find_command(key), command)
        self.assertIsNone(find_command("no-such-command"))

    def test_a_command_that_the_table_does_not_list_is_found_all_the_same(self):
        with mock.patch.object(registry, "WHERE", {}):
            self.assertEqual(find_command("page").name, "page")
            self.assertIsNone(find_command("no-such-command"))


class OnlyWhatIsNeededIsImportedTest(unittest.TestCase):
    """Fresh interpreters, because this process has imported everything already."""

    def modules_after(self, code: str) -> list[str]:
        script = (
            "import sys\n"
            f"sys.path.insert(0, {str(ROOT / 'src')!r})\n"
            f"{code}\n"
            f"print('\\n'.join(sorted(name.rpartition('.')[2] for name in sys.modules if name.startswith({COMMANDS_PACKAGE + '.'!r}) and name.count('.') == {COMMANDS_PACKAGE.count('.') + 1})))\n"
        )
        done = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True, text=True, timeout=60, cwd=str(ROOT))
        self.assertEqual(done.returncode, 0, done.stderr)
        return [line for line in done.stdout.splitlines() if line]

    def test_finding_one_command_imports_the_module_of_that_command_only(self):
        loaded = self.modules_after("from conflu_c_cli.adapters.driving.cli.registry import find_command\nassert find_command('page').name == 'page'")
        self.assertIn("pages", loaded)
        self.assertEqual(sorted(set(loaded) - {"pages", "_common", "_outfile"}), [])

    def test_a_command_in_another_module_imports_that_one(self):
        loaded = self.modules_after("from conflu_c_cli.adapters.driving.cli.registry import find_command\nassert find_command('task').name == 'task'")
        self.assertIn("tasks", loaded)
        self.assertNotIn("pages", loaded)
        self.assertNotIn("mcp", loaded)

    def test_the_list_of_all_commands_imports_every_module(self):
        loaded = self.modules_after("from conflu_c_cli.adapters.driving.cli.registry import all_commands\nassert len(all_commands()) > 50")
        self.assertTrue(set(MODULE_NAMES) <= set(loaded), sorted(set(MODULE_NAMES) - set(loaded)))

    def test_running_a_command_through_the_entry_point_does_not_import_the_others(self):
        code = (
            "from conflu_c_cli.adapters.driving.cli.main import run\n"
            "import io\n"
            "run(['version'], app_factory=lambda diagnostics: None, environ={}, stdout=io.StringIO(), stderr=io.StringIO())\n"
        )
        loaded = self.modules_after(code)
        self.assertIn("info", loaded)
        self.assertNotIn("pages", loaded)
        self.assertNotIn("mcp", loaded)
        self.assertNotIn("tasks", loaded)


if __name__ == "__main__":
    unittest.main()
