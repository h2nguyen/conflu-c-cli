"""A body that used to break the converter does not break the command: `tasks`, `task`, `template` and `task --complete`, the real program against the mock.

The bodies are the ones that raised an `AssertionError` (a section that the parser cannot name) or a `ValueError` (a number that is no number) out of the converter,
and ended a command in "unexpected AssertionError", a list in the middle, and a task that was changed and then reported as a crash.
"""
import unittest
from unittest import mock

from conflu_c_cli.application.tasks import UNREADABLE
from conflu_c_cli.domain import storage
from tests.integration.test_end_to_end import EndToEnd
from tests.support.mock_tasks import TasksRoutes
from tests.support.mock_templates import TemplatesRoutes

SECTION = "<span>x</span><![foo[ y ]]>"  # a section that the parser has no name for
LIST = '<ol start="x"><li>one</li></ol>'  # a list that starts at a number that is none
CELL = '<table><tr><td colspan="x" rowspan="y">a</td></tr></table>'  # a cell that reaches as far as a number that is none
SECTION_TEXT = "x<![foo[ y ]]>"  # what the section is now: the text that it is
BROKEN = AssertionError("unknown status keyword 'foo' in marked section")


class PoisonedTasks(EndToEnd):
    def setUp(self):
        super().setUp()
        self.area = self.mock.area(TasksRoutes)
        self.section = self.area.add_task("", storage=SECTION)
        self.list = self.area.add_task("", storage=LIST)
        self.cell = self.area.add_task("", storage=CELL)
        self.every = ("7201", "7202", "7203", "7204", "7205", "7206", self.section, self.list, self.cell)

    def texts(self, result):
        return {task["id"]: task["text"] for task in result.json()["tasks"]}

    def writes(self):
        return [item for item in self.mock.requests if item.method in ("PUT", "POST", "DELETE") and item.path != "/api/v2/content/convert-ids-to-types"]


class ListTest(PoisonedTasks):
    def test_one_poisoned_task_does_not_break_the_list_of_all(self):
        result = self.cli("tasks", "--all", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(sorted(self.texts(result)), sorted(self.every))
        self.assertEqual(result.json()["count"], len(self.every))
        texts = self.texts(result)
        self.assertEqual((texts[self.section], texts[self.list], texts[self.cell]), (SECTION_TEXT, "1. one", "a"))
        self.assertEqual(texts["7201"], "Check the numbers with @user")

    def test_the_table_of_the_list_shows_them_too(self):
        result = self.cli("tasks", "--all")
        self.assertEqual(result.code, 0, result.err)
        self.assertIn(SECTION_TEXT, result.out)
        self.assertIn("Update the docs home", result.out)
        self.assertNotIn("unexpected", result.err)

    def test_the_tasks_are_asked_for_by_their_id_and_read_one_by_one_as_well(self):
        listed = self.cli("tasks", "--task", self.section, "--task", self.list, "--json")
        self.assertEqual((listed.code, self.texts(listed)), (0, {self.section: SECTION_TEXT, self.list: "1. one"}))
        for task_id, text in ((self.section, SECTION_TEXT), (self.list, "1. one"), (self.cell, "a")):
            shown = self.cli("task", task_id)
            with self.subTest(task=task_id):
                self.assertEqual(shown.code, 0, shown.err)
                self.assertIn(text, shown.out)
                self.assertEqual(self.cli("task", task_id, "--json").json()["text"], text)


class ChangeTest(PoisonedTasks):
    def test_a_task_that_used_to_break_the_converter_is_completed_and_shown(self):
        for task_id, text in ((self.list, "1. one"), (self.section, SECTION_TEXT)):
            self.mock.requests.clear()
            result = self.cli("task", task_id, "--complete")
            with self.subTest(task=task_id):
                self.assertEqual(result.code, 0, result.err)
                self.assertIn(f"Completed task {task_id}: {text} (incomplete -> complete)", result.out)
                self.assertEqual(self.area.tasks[task_id]["status"], "complete")
                self.assertEqual(len(self.writes()), 1)
        self.assertEqual(self.area.changes, [(self.list, "complete"), (self.section, "complete")])

    def test_the_change_is_made_and_reported_when_the_converter_fails_for_any_reason(self):
        for failure in (BROKEN, ValueError("invalid literal for int() with base 10: 'x'"), RuntimeError("anything"), MemoryError()):
            self.mock.requests.clear()
            with mock.patch.object(storage._Builder, "close", side_effect=failure):
                result = self.cli("task", "7201", "--complete", "--json")
            with self.subTest(failure=type(failure).__name__):
                self.assertEqual(result.code, 0, result.err)
                data = result.json()
                self.assertEqual((data["action"], data["task"]["status"], data["readBack"], data["task"]["text"]), ("completed", "complete", True, UNREADABLE))
                self.assertEqual(len(self.writes()), 1)
            self.cli("task", "7201", "--reopen")  # the next failure starts from the same task

    def test_the_change_is_made_and_reported_when_what_shows_the_text_fails_after_the_write(self):
        with mock.patch("conflu_c_cli.application.tasks.render_body", side_effect=RuntimeError("after the write")):
            result = self.cli("task", "7203", "--complete")
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("Completed task 7203", result.out)
        self.assertIn(UNREADABLE, result.out)
        self.assertEqual(self.area.changes, [("7203", "complete")])

    def test_when_the_converter_fails_for_every_task_the_list_is_still_a_list(self):
        with mock.patch.object(storage._Builder, "close", side_effect=BROKEN):
            result = self.cli("tasks", "--all", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(set(self.texts(result).values()), {UNREADABLE})
        self.assertEqual(result.json()["count"], len(self.every))


class PoisonedTemplates(EndToEnd):
    def setUp(self):
        super().setUp()
        self.area = self.mock.area(TemplatesRoutes)
        self.section = self.area.add_template("Section", "<p>a</p><![foo[ b ]]>", space_key="ENG")
        self.cell = self.area.add_template("Cell", CELL, space_key="ENG")
        self.list = self.area.add_template("List", LIST, space_key="ENG")

    def test_a_template_with_a_section_that_has_no_name_is_shown_in_every_format(self):
        for fmt in ("markdown", "text", "storage"):
            result = self.cli("template", self.section, "--format", fmt, "--json")
            with self.subTest(format=fmt):
                self.assertEqual(result.code, 0, result.err)
                value = result.json()["body"]["value"]
                self.assertIn("a", value)
                self.assertIn("foo", value)
        plain = self.cli("template", self.section)
        self.assertEqual(plain.code, 0, plain.err)
        self.assertIn("a\n\n", plain.out)
        self.assertNotIn("unexpected", plain.err)

    def test_a_template_with_a_cell_or_a_list_that_has_a_number_that_is_none_is_shown(self):
        cell = self.cli("template", self.cell, "--json")
        self.assertEqual(cell.code, 0, cell.err)
        self.assertEqual(cell.json()["body"]["dropped"], [])
        self.assertIn("| a |", cell.json()["body"]["value"])
        listed = self.cli("template", self.list, "--format", "text", "--body-only")
        self.assertEqual((listed.code, listed.out), (0, "1. one\n"))

    def test_a_template_whose_body_cannot_be_read_says_how_to_read_it_and_ends_with_exit_code_1_and_not_with_a_crash(self):
        with mock.patch.object(storage._Builder, "close", side_effect=BROKEN):
            markdown = self.cli("template", self.section)
            storage_format = self.cli("template", self.section, "--format", "storage", "--body-only")
        self.assertEqual(markdown.code, 1)
        self.assertIn("cannot read this body as storage format", markdown.err)
        self.assertIn("--format storage", markdown.err)
        self.assertNotIn("unexpected", markdown.err)
        self.assertNotIn("foo", markdown.err)  # the words of the error are not printed: they quote the body
        self.assertEqual((storage_format.code, storage_format.out), (0, "<p>a</p><![foo[ b ]]>\n"))  # as Confluence keeps it, the body is not converted at all


class PoisonedPages(EndToEnd):
    def test_a_page_with_a_section_that_has_no_name_is_shown(self):
        self.mock.pages["2005"]["versions"][-1]["body"] = "<p>before</p><![foo[ y ]]><ol start=\"x\"><li>one</li></ol><p>after</p>"
        result = self.cli("page", "2005")
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("before", result.out)
        self.assertIn("1. one", result.out)
        self.assertIn("after", result.out)


if __name__ == "__main__":
    unittest.main()
