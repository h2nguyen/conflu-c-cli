"""The JSON reference shows what the commands print: valid JSON, with the keys the program really uses.

Every `###` section of docs/reference/json-output.md names a command and shows its output. Here that command runs
against the mock Confluence and the keys of its output are compared with the keys of the example, level by level.
"""
import json
import re
import unittest

from tests.integration.test_end_to_end import ROOT, EndToEnd

DOCUMENTS = [ROOT / "README.md", ROOT / "skills" / "conflu-c-cli" / "SKILL.md", *sorted((ROOT / "docs").rglob("*.md"))]
REFERENCE = ROOT / "docs" / "reference" / "json-output.md"
BLOCK = re.compile(r"```json\n(.*?)```", re.DOTALL)
OPAQUE = ("payload", "properties")  # the request body Confluence would get, and the properties of a tool schema: they differ with every case
FREE_FORM = ("conflu api ... --json",)  # prints whatever the endpoint answers


def documented_examples() -> dict[str, list]:
    """Heading -> the parsed JSON examples under it."""
    found = {}
    for part in re.split(r"^(?=### )", REFERENCE.read_text(encoding="utf-8"), flags=re.MULTILINE):
        heading = re.match(r"### `([^`]+)`", part)
        if heading:
            found[heading.group(1)] = [json.loads(block) for block in BLOCK.findall(part)]
    return found


def differences(documented, printed, path="$") -> list[str]:
    """Keys that only one side has, and values of a different type. A null on either side hides what is below it."""
    if documented is None or printed is None:
        return []
    if isinstance(documented, dict) and isinstance(printed, dict):
        problems = []
        for key in sorted(documented.keys() - printed.keys()):
            problems.append(f"{path}.{key}: documented, but the command does not print it")
        for key in sorted(printed.keys() - documented.keys()):
            problems.append(f"{path}.{key}: printed, but not documented")
        for key in sorted(documented.keys() & printed.keys()):
            if key not in OPAQUE:
                problems += differences(documented[key], printed[key], f"{path}.{key}")
        return problems
    if isinstance(documented, list) and isinstance(printed, list):
        return differences(documented[0], printed[0], f"{path}[]") if documented and printed else []
    if type(documented) is not type(printed):
        return [f"{path}: documented as {type(documented).__name__}, printed as {type(printed).__name__}"]
    return []


class DifferencesTest(unittest.TestCase):
    def test_the_comparison_sees_missing_extra_and_mistyped_keys(self):
        self.assertEqual(differences({"a": 1, "b": [{"c": 1}]}, {"a": 1, "b": [{"c": 2}]}), [])
        self.assertEqual(differences({"a": 1}, {"a": 1, "b": 2}), ["$.b: printed, but not documented"])
        self.assertEqual(differences({"a": 1, "b": 2}, {"a": 1}), ["$.b: documented, but the command does not print it"])
        self.assertEqual(differences({"b": [{"c": 1}]}, {"b": [{"d": 1}]}), ["$.b[].c: documented, but the command does not print it", "$.b[].d: printed, but not documented"])
        self.assertEqual(differences({"a": 1}, {"a": "1"}), ["$.a: documented as int, printed as str"])
        self.assertEqual(differences({"a": None}, {"a": {"x": 1}}), [])
        self.assertEqual(differences({"payload": {"x": 1}}, {"payload": {"y": 1}}), [])


class DocumentedJsonTest(EndToEnd):
    def test_every_json_block_in_the_documents_is_valid_json(self):
        checked = 0
        for path in DOCUMENTS:
            for block in BLOCK.findall(path.read_text(encoding="utf-8")):
                with self.subTest(file=path.name, block=block[:50]):
                    json.loads(block)
                    checked += 1
        self.assertGreater(checked, 30)

    def ran(self, *argv, stdin=""):
        result = self.cli(*argv, stdin=stdin)
        self.assertEqual(result.code, 0, f"conflu {' '.join(argv)}: {result.err}")
        return json.loads(result.out)

    def runs(self):
        """Heading -> one function per example under it, each running a command that prints the same thing."""
        picture = self.root / "files" / "diagram.png"
        picture.parent.mkdir(parents=True, exist_ok=True)
        picture.write_bytes(b"PNGDATA123")
        single = self.root / "single" / "notes.md"
        single.parent.mkdir(parents=True, exist_ok=True)
        single.write_text("# Notes\n\nSome text.\n", encoding="utf-8")
        folder = self.root / "folder"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "first.md").write_text("# First\n\nOne.\n", encoding="utf-8")
        (folder / "second.md").write_text("# Second\n\nTwo.\n", encoding="utf-8")
        ran = self.ran
        return {
            "conflu page PAGE --json": [lambda: ran("page", "2002", "--comments", "--ancestors", "--json")],
            "conflu page PAGE --outline --json": [lambda: ran("page", "2002", "--outline", "--json")],
            "conflu commands --format mcp": [lambda: ran("commands", "--format", "mcp")],
            "conflu pages --json": [lambda: ran("pages", "--space", "ENG", "--limit", "2", "--json")],
            "conflu tree PAGE --json": [lambda: ran("tree", "2001", "--depth", "3", "--json")],
            "conflu versions PAGE --json": [lambda: ran("versions", "2002", "--json")],
            "conflu search --json": [lambda: ran("search", "release", "--space", "ENG", "--json")],
            "conflu export --json": [lambda: ran("export", "--space", "ENG", "--out", str(self.root / "mirror"), "--json")],
            "conflu comments PAGE --json": [lambda: ran("comments", "2002", "--json")],
            "conflu labels PAGE --json": [lambda: ran("labels", "2002", "--json")],
            "conflu attachments PAGE --json": [lambda: ran("attachments", "2002", "--json")],
            "conflu download ... --json": [lambda: ran("download", "2002", "--all", "--out", str(self.root / "downloads"), "--json")],
            "conflu update PAGE --json": [lambda: ran("update", "2005", "--body", "Added.", "--message", "Added text", "--append", "--dry-run", "--json")],
            "conflu move PAGE --json": [lambda: ran("move", "2005", "--to", "2003", "--dry-run", "--json")],
            "conflu comment PAGE --json": [lambda: ran("comment", "2005", "--text", "Reviewed.", "--json")],
            "conflu label PAGE --json": [lambda: ran("label", "2002", "--add", "reviewed", "--remove", "notes", "--json")],
            "conflu attach PAGE FILE... --json": [lambda: ran("attach", "2005", str(picture), "--json")],
            "conflu create --json": [lambda: ran("create", "--space", "ENG", "--title", "Monthly checklist", "--body", "Run the checks.", "--labels", "operations,checklist", "--parent", "2001", "--json")],
            "conflu import-md FILE --json": [lambda: ran("import-md", str(single), "--space", "ENG", "--json")],
            "conflu import-md-dir DIR --json": [lambda: ran("import-md-dir", str(folder), "--space", "ENG", "--json")],
            "conflu spaces --json": [lambda: ran("spaces", "--json")],
            "conflu space [KEY] --json": [lambda: ran("space", "ENG", "--json")],
            "conflu setup-token --json": [lambda: ran("setup-token", "--stdin", "--json", stdin=self.mock.token + "\n")],
            "conflu remove-token --json": [lambda: ran("remove-token", "--json")],
            "conflu use KEY --json": [lambda: ran("use", "ENG", "--json")],
            "conflu current --json": [lambda: ran("current", "--json")],
            "conflu clear-space --json": [lambda: ran("clear-space", "--json")],
            "conflu config show --json": [lambda: ran("config", "show", "--json")],
            "conflu ping --json": [lambda: ran("ping", "--json")],
            "conflu doctor --json": [lambda: ran("doctor", "--json")],
            "conflu commands --json": [lambda: ran("commands", "--json")],
            "conflu version --json": [lambda: ran("version", "--json")],
            "conflu how-to --json": [lambda: ran("how-to", "--json"), lambda: ran("how-to", "daily-workflow", "--json")],
            "conflu skill --json": [lambda: ran("skill", "--json"), lambda: ran("skill", "install", "--dir", str(self.root / "skills"), "--json")],
        }

    def test_every_command_prints_the_keys_its_example_shows(self):
        examples = documented_examples()
        runs = self.runs()
        for heading, shown in examples.items():
            if heading in FREE_FORM:
                continue
            with self.subTest(command=heading):
                self.assertIn(heading, runs, "add a run for this command to DocumentedJsonTest.runs")
                self.assertEqual(len(shown), len(runs[heading]), "one run per example")
                for example, run in zip(shown, runs[heading]):
                    self.assertEqual(differences(example, run()), [])

    def test_no_documented_command_is_left_out_of_the_runs(self):
        self.assertEqual(sorted(set(self.runs()) - set(documented_examples())), [], "a run for a command the reference does not show")


if __name__ == "__main__":
    unittest.main()
