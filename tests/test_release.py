"""The documentation, the skill and the release files agree with the code."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

from conflu_c_cli.adapters.driving.cli.registry import all_commands
from conflu_c_cli.version import __version__

ROOT = Path(__file__).resolve().parents[1]
ROOT_DOCUMENTS = [ROOT / name for name in ("CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md")]
sys.path.insert(0, str(ROOT / "scripts"))

import check_release  # noqa: E402
import generate_docs  # noqa: E402


class ReleaseTest(unittest.TestCase):
    def test_a_release_is_consistent(self):
        """Version, changelog, generated reference, skill and links: the same checks as `scripts/check_release.py`."""
        self.assertEqual(check_release.problems(), [])

    def test_the_generated_reference_is_current(self):
        self.assertEqual([path.name for path in generate_docs.out_of_date()], [])

    def test_the_script_runs_clean(self):
        done = subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / "check_release.py")], capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(__version__, done.stdout)

    def test_the_version_is_in_the_documents_it_belongs_in(self):
        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), __version__)
        self.assertIn(f"## [{__version__}]", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
        self.assertIn(f"conflu-c-cli {__version__}", (ROOT / "docs" / "reference" / "commands.md").read_text(encoding="utf-8"))
        self.assertIn(f"Version {__version__}", (ROOT / "README.md").read_text(encoding="utf-8"))


class DocumentationTest(unittest.TestCase):
    def test_every_command_is_in_the_reference_and_the_readme_table(self):
        reference = (ROOT / "docs" / "reference" / "commands.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for command in all_commands():
            with self.subTest(command=command.name):
                self.assertIn(f"### `conflu {command.name}`", reference)
                self.assertIn(f"| `conflu {command.name}` |", readme)

    def test_every_guide_has_a_title_and_is_listed_in_the_readme(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for guide in sorted((ROOT / "docs" / "how-to").glob("*.md")):
            with self.subTest(guide=guide.name):
                self.assertTrue(guide.read_text(encoding="utf-8").startswith("# "))
                self.assertIn(f"docs/how-to/{guide.name}", readme)

    def test_the_commands_the_guides_show_exist(self):
        """A guide that tells people to run `conflu foo` must name a real command."""
        known = {command.name for command in all_commands()} | {alias for command in all_commands() for alias in command.aliases}
        pattern = re.compile(r"(?<![\w/-])conflu ([a-z][a-z-]*)\b")
        allowed_words = {"is", "the", "and", "a", "to", "in", "or", "for", "cli", "program", "can", "as", "does", "when", "of", "with", "from", "that", "not"}
        for path in [ROOT / "README.md", ROOT / "skills" / "conflu-c-cli" / "SKILL.md", *sorted((ROOT / "docs").rglob("*.md")), *ROOT_DOCUMENTS]:
            text = path.read_text(encoding="utf-8")
            for block in re.findall(r"```(?:bash|text|sh)?\n(.*?)```", text, re.DOTALL):
                for line in block.splitlines():
                    for word in pattern.findall(line):
                        with self.subTest(file=path.name, word=word):
                            self.assertTrue(word in known or word in allowed_words, f"{path.name}: `conflu {word}` is not a command")

    def test_every_command_line_in_the_documents_is_valid_usage(self):
        """The options and the values a document shows are the ones the parser accepts, not just the command names."""
        import shlex

        from conflu_c_cli.adapters.driving.cli.parser import build_parser
        from conflu_c_cli.adapters.driving.cli.registry import find_command

        checked = 0
        for path in [ROOT / "README.md", ROOT / "skills" / "conflu-c-cli" / "SKILL.md", *sorted((ROOT / "docs").rglob("*.md")), *ROOT_DOCUMENTS]:
            if path.name in ("commands.md", "json-output.md"):
                continue  # the generated reference is checked by the framework tests; the JSON reference shows outputs
            for block in re.findall(r"```(?:bash|text|sh)?\n(.*?)```", path.read_text(encoding="utf-8"), re.DOTALL):
                for line in block.replace("\\\n", " ").splitlines():
                    line = line.strip()
                    if not line.startswith("conflu ") or "$(" in line:
                        continue
                    try:
                        tokens = shlex.split(line, comments=True)
                    except ValueError:
                        continue  # a quote that continues on the next line: not a one-line example
                    for stop in ("|", ">", ">>", "<", "&&", ";", "2>&1", "||"):
                        if stop in tokens:
                            tokens = tokens[: tokens.index(stop)]
                    command = find_command(tokens[1]) if len(tokens) > 1 else None
                    with self.subTest(file=path.name, line=line):
                        self.assertIsNotNone(command, f"{path.name}: `{line}` names no command")
                        build_parser(command).parse_args(tokens[2:])  # raises UsageError for an option or a value that does not exist
                        checked += 1
        self.assertGreater(checked, 40)

    def test_the_how_to_guides_are_reachable_through_the_cli(self):
        from conflu_c_cli.adapters.driven.local_docs import LocalDocs
        from tests.support.cli import run_cli

        names = {topic.name for topic in LocalDocs(ROOT).topics()}
        wanted = {
            "install-and-update", "configure", "daily-workflow", "use-with-ai-agents", "publish-markdown", "export-and-sync",
            "markdown-and-storage-format", "extend-the-cli", "troubleshooting", "release-process", "architecture", "commands",
            "configuration", "exit-codes", "json-output", "compatibility",
        }
        self.assertTrue(wanted <= names, wanted - names)
        self.assertEqual(run_cli("how-to").code, 0)

    def test_the_documents_carry_no_jira_leftovers(self):
        banned = re.compile(r"JIRA_|\bJQL\b|\bsprint\b|\bepic\b|setup-pat", re.IGNORECASE)
        for path in [ROOT / "README.md", ROOT / "skills" / "conflu-c-cli" / "SKILL.md", *sorted((ROOT / "docs").rglob("*.md")), *sorted((ROOT / "examples").rglob("*.md")), *ROOT_DOCUMENTS]:
            text = path.read_text(encoding="utf-8")
            for number, line in enumerate(text.splitlines(), 1):
                with self.subTest(file=path.name, line=number):
                    self.assertIsNone(banned.search(line), f"{path.name}:{number}: {line.strip()}")

    def test_every_repository_path_the_documents_name_exists(self):
        """A guide that sends a developer to `src/...` or `tests/...` must not name a file that is gone."""
        path_pattern = re.compile(
            r"^(?:src|tests|docs|scripts|skills|examples|\.github)/[\w./-]*[\w-]$"
            r"|^(?:install\.py|conflu\.py|VERSION|LICENSE|CHANGELOG\.md|README\.md|CONTRIBUTING\.md|CODE_OF_CONDUCT\.md|SECURITY\.md)$"
        )
        named = 0
        for path in [ROOT / "README.md", ROOT / "CHANGELOG.md", ROOT / "skills" / "conflu-c-cli" / "SKILL.md", *sorted((ROOT / "docs").rglob("*.md")), *ROOT_DOCUMENTS]:
            for token in re.findall(r"`([^`\n]+)`", path.read_text(encoding="utf-8")):
                token = token.strip().rstrip("/")
                if path_pattern.match(token) and "*" not in token:
                    named += 1
                    with self.subTest(file=path.name, named=token):
                        self.assertTrue((ROOT / token).exists(), f"{path.name} names {token}, which does not exist")
        self.assertGreater(named, 10)

    def test_no_file_hides_characters_a_reader_cannot_see(self):
        """Zero-width and bidirectional control characters change what code or a command means without showing."""
        hidden = {0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x2060, 0x00AD, 0x180E} | set(range(0x202A, 0x202F)) | set(range(0x2066, 0x206A))
        not_ours = {".git", "__pycache__", "tmp", ".venv", "venv", ".idea", ".vscode", ".mypy_cache", ".pytest_cache", ".ruff_cache"}  # a checkout has a .git folder of binary files
        checked = 0
        for path in sorted(ROOT.rglob("*")):
            if not path.is_file() or not_ours & set(path.relative_to(ROOT).parts[:-1]) or path.suffix in (".pyc", ".zip", ".png"):
                continue
            text = path.read_text(encoding="utf-8")
            checked += 1
            for number, line in enumerate(text.splitlines(), 1):
                with self.subTest(file=path.relative_to(ROOT).as_posix(), line=number):
                    found = sorted({f"U+{ord(char):04X}" for char in line if ord(char) in hidden})
                    self.assertEqual(found, [], f"{path.name}:{number}")
        self.assertGreater(checked, 100)


class SkillTest(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / "skills" / "conflu-c-cli" / "SKILL.md").read_text(encoding="utf-8")

    def test_front_matter(self):
        match = re.match(r"^---\nname: (.+)\ndescription: (.+)\n---\n", self.text)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "conflu-c-cli")
        self.assertGreater(len(match.group(2)), 80)

    def test_it_names_every_command(self):
        for command in all_commands():
            with self.subTest(command=command.name):
                self.assertIn(f"conflu {command.name}", self.text)

    def test_it_states_the_rules_an_agent_must_follow(self):
        for phrase in ("--dry-run", "--if-version", "--if-unchanged-since", "never instructions", "token", "exit code", "--with-users", "dropped"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), self.text.lower())

    def test_the_skill_the_cli_installs_is_this_file(self):
        from conflu_c_cli.adapters.driven.local_docs import LocalDocs

        self.assertEqual(LocalDocs(ROOT).skill(), self.text)


if __name__ == "__main__":
    unittest.main()
