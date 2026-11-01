"""`conflu help --brief`: every command with its arguments and main options in one short text, and the compact reference that the skill carries."""
import re
import sys
import unittest
from pathlib import Path

from conflu_c_cli.adapters.driving.cli.help import BRIEF_BUDGET, BRIEF_OPTIONS, render_brief, render_compact_reference
from conflu_c_cli.adapters.driving.cli.registry import all_commands
from conflu_c_cli.adapters.driving.cli.spec import GROUP_ORDER
from tests.support.cli import run_cli

ROOT = Path(__file__).resolve().parents[2]
NAMES = [command.name for command in all_commands()]
ABOUT_THE_FUTURE = 70  # the number of commands that the budget is designed for


def size(text: str) -> int:
    return len(text.encode("utf-8"))


class BriefTest(unittest.TestCase):
    def test_one_call_prints_every_command_in_at_most_four_kilobytes(self):
        result = run_cli("help", "--brief")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(BRIEF_BUDGET, 4096)
        self.assertLessEqual(size(result.out) - 1, BRIEF_BUDGET)  # the print adds a line end
        for name in NAMES:
            with self.subTest(command=name):
                self.assertRegex(result.out, rf"(?m)^  {re.escape(name)}\*?(?: |$)")

    def test_the_budget_holds_when_the_cli_has_about_seventy_commands(self):
        """Not only 4096 bytes now: what one command costs, with the headings counted, stays under 55 bytes, so that 70 of them fit."""
        text = render_brief(all_commands())
        average = size(text) / len(NAMES)
        self.assertLess(average, 55, f"{size(text)} bytes for {len(NAMES)} commands")
        # The projection, computed apart: what is fixed (the two lines that explain the notation and every group heading, also of the groups
        # that have no command yet) plus what a command costs, times the number of commands that the budget is designed for.
        lines = text.splitlines()
        headings = [line for line in lines if line.endswith(":") and not line.startswith(" ") and not line.startswith("conflu")]
        command_lines = [line for line in lines if line.startswith("  ")]
        self.assertEqual(len(command_lines), len(NAMES))
        fixed = size("\n".join(lines[:2])) + 1 + sum(size(group) + 3 for group in GROUP_ORDER)
        per_command = sum(size(line) + 1 for line in command_lines) / len(command_lines)
        self.assertLessEqual(len(headings), len(GROUP_ORDER))
        self.assertLessEqual(fixed + ABOUT_THE_FUTURE * per_command, BRIEF_BUDGET, f"{per_command:.1f} bytes a command, {fixed} fixed")

    def test_a_star_marks_the_commands_that_change_data_and_the_text_explains_it(self):
        out = run_cli("help", "--brief").out
        for name in ("update", "create", "comment", "label", "move", "attach", "import-md", "api"):
            self.assertRegex(out, rf"(?m)^  {re.escape(name)}\* ", name)
        self.assertRegex(out, r"(?m)^  page ")
        self.assertRegex(out, r"(?m)^  search ")
        self.assertIn("* changes data (use --dry-run first)", out)
        self.assertNotRegex(out, r"(?m)^  \S+\* .*--dry-run")  # the star says it

    def test_a_command_line_has_the_arguments_and_the_main_options(self):
        out = run_cli("help", "--brief").out
        self.assertRegex(out, r"(?m)^  page PAGE\.\.\. \[--format --outline --section --max-chars \.\.\.\]$")
        self.assertRegex(out, r"(?m)^  search \[TEXT\.\.\.\] \[--phrase --space --type --label \.\.\.\]$")
        self.assertRegex(out, r"(?m)^  attach\* PAGE FILE\.\.\. \[")
        self.assertRegex(out, r"(?m)^  space \[KEY\] \[--with-users\]$")  # the one option of `space`: a personal space is shown with its owner only with it

    def test_an_option_that_must_be_given_stands_outside_the_brackets_and_is_never_cut(self):
        out = run_cli("help", "--brief").out
        self.assertRegex(out, r"(?m)^  move\* PAGE --to \[--position --if-version --if-unchanged-since --with-users\]$")
        self.assertRegex(out, r"(?m)^  export --out \[")
        small = render_brief(all_commands(), budget=1)  # everything that can be cut is cut
        self.assertRegex(small, r"(?m)^  move\* PAGE --to(?: \[\.\.\.\])?$")
        self.assertRegex(small, r"(?m)^  export --out \[\.\.\.\]$")

    def test_the_shared_options_come_after_the_ones_that_make_a_command(self):
        out = run_cli("help", "--brief").out
        self.assertRegex(out, r"(?m)^  pages \[--space --title --status --sort \.\.\.\]$")  # not --select or --format first
        self.assertRegex(out, r"(?m)^  labels \[PAGE\] \[--space --limit --all --cursor \.\.\.\]$")  # a page or --space; the shared options after what makes the command

    def test_the_groups_are_named_and_help_for_one_command_is_pointed_to(self):
        out = run_cli("help", "--brief").out
        for group in GROUP_ORDER:
            if any(command.group == group for command in all_commands()):
                self.assertIn(f"\n{group}:\n", out)
        self.assertIn("conflu help COMMAND", out)
        self.assertIn("--json-envelope", out)

    def test_without_a_budget_and_with_all_options_nothing_is_cut(self):
        full = render_brief(all_commands(), options=None, budget=None)
        self.assertIn("--if-unchanged-since", full)
        self.assertNotIn(" ...]", full)
        self.assertNotIn("[...]", full)
        self.assertGreater(size(full), size(render_brief(all_commands())))

    def test_the_options_are_cut_when_the_text_would_be_too_long_and_the_cut_is_shown(self):
        design = render_brief(all_commands(), budget=None)
        cut = render_brief(all_commands(), budget=size(design) - 200)
        self.assertLess(size(cut), size(design))
        self.assertRegex(cut, r"( \.\.\.\]|\[\.\.\.\])")
        self.assertLessEqual(size(cut), size(design) - 200)

    def test_a_cli_that_has_grown_is_cut_further_until_it_fits(self):
        many = all_commands() * 2  # twice the commands that the design has room for: the options are cut, the commands stay
        text = render_brief(many, budget=BRIEF_BUDGET)
        self.assertLessEqual(size(text), BRIEF_BUDGET)
        self.assertGreater(size(render_brief(many, budget=None)), BRIEF_BUDGET)

    def test_a_smaller_budget_cuts_more_but_keeps_every_command(self):
        design = render_brief(all_commands(), budget=None)
        small = render_brief(all_commands(), budget=1200)
        for name in NAMES:
            self.assertRegex(small, rf"(?m)^  {re.escape(name)}\*?(?: |$)")
        self.assertLess(size(small), size(design))

    def test_the_number_of_options_is_the_design(self):
        self.assertEqual(BRIEF_OPTIONS, 4)
        for line in render_brief(all_commands()).splitlines():
            if line.startswith("  ") and "[--" in line:
                shown = re.search(r"\[((?:--[\w-]+ ?)+)(?:\.\.\.)?\]", line)
                self.assertIsNotNone(shown, line)
                self.assertLessEqual(len(shown.group(1).split()), BRIEF_OPTIONS, line)

    def test_names_keep_only_those_commands(self):
        text = render_brief(all_commands(), options=None, budget=None, names=("comment", "api"))
        self.assertIn("  comment* ", text)
        self.assertIn("  api* ", text)
        self.assertNotIn("  page ", text)

    def test_a_command_name_with_brief_is_a_usage_error(self):
        result = run_cli("help", "page", "--brief")
        self.assertEqual(result.code, 2)
        self.assertIn("conflu help COMMAND", result.err)
        self.assertEqual(result.out, "")

    def test_help_without_brief_is_unchanged(self):
        self.assertEqual(run_cli("help").out, run_cli().out)
        self.assertIn("conflu page - Show one page", run_cli("help", "page").out)
        self.assertNotIn("Read:\n  page PAGE [", run_cli("help").out)

    def test_brief_is_in_the_help_of_help(self):
        out = run_cli("help", "help").out
        self.assertIn("--brief", out)
        self.assertIn("conflu help --brief", out)

    def test_the_brief_is_plain_ascii_and_one_text(self):
        text = run_cli("help", "--brief").out
        self.assertTrue(text.isascii())
        self.assertNotIn("\t", text)
        self.assertEqual(run_cli("help", "--brief", "--json-envelope").json(), {"ok": True, "data": {"text": text.rstrip("\n")}})


class CompactReferenceTest(unittest.TestCase):
    def test_all_options_and_one_example_per_command(self):
        text = render_compact_reference(all_commands(), ("comment", "api", "page"))
        lines = text.splitlines()
        self.assertTrue(lines[0].startswith("comment* PAGE ["))
        self.assertIn("--reply-to", lines[0])
        self.assertNotIn("...", lines[0])
        self.assertTrue(lines[1].startswith("    conflu comment "))
        self.assertTrue(any(line.startswith("api* METHOD PATH [--param --data --data-file --write]") for line in lines))
        self.assertTrue(any(line.startswith("page PAGE... [--format --outline --section --max-chars --space") for line in lines))

    def test_an_example_note_follows_as_a_comment(self):
        self.assertIn("    conflu page 123456    # the page as Markdown", render_compact_reference(all_commands(), ("page",)))

    def test_the_skill_carries_it_for_the_commands_agents_need_most(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import generate_docs

        self.assertEqual(generate_docs.SKILL_REFERENCE, ("page", "search", "update", "create", "comment", "api"))
        skill = (ROOT / "skills" / "conflu-c-cli" / "SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(skill.count(generate_docs.REFERENCE_START), 1)
        self.assertEqual(skill.count(generate_docs.REFERENCE_END), 1)
        for name in generate_docs.SKILL_REFERENCE:
            self.assertRegex(skill, rf"(?m)^{re.escape(name)}\*? ")
        block = skill.split(generate_docs.REFERENCE_START, 1)[1].split(generate_docs.REFERENCE_END, 1)[0]
        self.assertEqual(block.strip(), "```text\n" + render_compact_reference(all_commands(), generate_docs.SKILL_REFERENCE) + "\n```")

    def test_the_release_check_covers_the_skill(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import generate_docs

        skill = ROOT / "skills" / "conflu-c-cli" / "SKILL.md"
        self.assertIn(skill, generate_docs.generated())
        text = skill.read_text(encoding="utf-8")
        stale = re.sub(r"(page PAGE(?:\.\.\.)? \[--format)", r"\1ted", text, count=1)  # `page` takes several pages: PAGE...
        self.assertNotEqual(generate_docs.with_compact_reference(stale), stale)  # the generator puts it right
        self.assertEqual(generate_docs.with_compact_reference(text), text)  # and leaves a current block as it is

    def test_the_generator_asks_for_the_markers(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import generate_docs

        with self.assertRaises(SystemExit):
            generate_docs.with_compact_reference("# A skill without the markers\n")


if __name__ == "__main__":
    unittest.main()
