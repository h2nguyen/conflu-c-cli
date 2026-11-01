"""What a change says about itself: a task that Confluence accepted and did not change is not reported as completed, and a property that was created does not
come with an empty id. The real program against the mock, whose hook `ignores_changes` is a server that says yes and does nothing.
"""
import re
import unittest

from tests.integration.test_end_to_end import EndToEnd
from tests.support.mock_tasks import TasksRoutes

CHECK = "check it with `conflu task 7203 --json` (status)."


class TaskConfirmationTest(EndToEnd):
    def setUp(self):
        super().setUp()
        self.area = self.mock.area(TasksRoutes)

    def puts(self):
        return [item for item in self.mock.requests if item.method == "PUT"]

    def test_a_change_that_the_read_after_it_shows_is_completed_and_confirmed(self):
        result = self.cli("task", "7203", "--complete")
        self.assertEqual((result.code, result.out, result.err), (0, "Completed task 7203: Write ADR 0002 (incomplete -> complete)\n", ""))
        data = self.cli("task", "7201", "--complete", "--json").json()
        self.assertEqual((data["action"], data["readBack"], data["confirmed"], data["message"], data["notes"]), ("completed", True, True, None, []))
        reopened = self.cli("task", "7202", "--reopen", "--json").json()
        self.assertEqual((reopened["action"], reopened["confirmed"], reopened["message"]), ("reopened", True, None))

    def test_a_server_that_says_yes_and_does_nothing_is_not_a_task_that_was_completed(self):
        self.area.ignores_changes = True
        result = self.cli("task", "7203", "--complete")
        self.assertEqual(result.code, 0, result.err)  # the exit code of a change that was sent and could not be confirmed is 0, as for `move`
        self.assertEqual(result.out, "Confluence accepted the request to complete task 7203 (incomplete -> complete), but it still shows the task as incomplete.\n")
        self.assertNotIn("Completed", result.out)
        self.assertIn("WARNING: Confluence accepted the change, but it holds task 7203 as incomplete, not as complete.", result.err)
        self.assertIn(CHECK, result.err)
        self.assertEqual((self.area.changes, self.area.ignored), ([], [("7203", "complete")]))
        self.assertEqual(len(self.puts()), 1)

    def test_the_json_says_so_with_confirmed_false_and_the_same_message_as_a_note(self):
        self.area.ignores_changes = True
        result = self.cli("task", "7203", "--complete", "--json")
        self.assertEqual(result.code, 0, result.err)
        data = result.json()
        self.assertEqual((data["action"], data["readBack"], data["confirmed"], data["statusFrom"], data["statusTo"]), ("completed", True, False, "incomplete", "complete"))
        self.assertEqual(data["task"]["status"], "incomplete")  # the task as Confluence holds it
        self.assertEqual(data["message"], "Confluence accepted the change, but it holds task 7203 as incomplete, not as complete. Somebody may have changed it again; " + CHECK)
        self.assertEqual(data["notes"], [data["message"]])
        self.assertEqual(result.err.count("WARNING"), 1)  # said once

    def test_a_task_that_is_reopened_and_stays_complete_is_said_the_same_way(self):
        self.area.ignores_changes = True
        result = self.cli("task", "7202", "--reopen")
        self.assertEqual(result.out, "Confluence accepted the request to reopen task 7202 (complete -> incomplete), but it still shows the task as complete.\n")
        self.assertNotIn("Reopened", result.out)
        self.assertEqual(self.cli("task", "7202", "--reopen", "--json").json()["confirmed"], False)

    def test_the_same_request_again_is_sent_again_because_the_task_is_not_in_the_state_asked_for(self):
        self.area.ignores_changes = True
        for _ in range(2):
            self.cli("task", "7203", "--complete")
        self.assertEqual(len(self.puts()), 2)
        self.area.ignores_changes = False
        self.assertEqual(self.cli("task", "7203", "--complete", "--json").json()["confirmed"], True)

    def test_a_change_that_cannot_be_read_back_is_neither_confirmed_nor_denied(self):
        self.area.read_back_fails = True
        result = self.cli("task", "7201", "--complete")
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("Completed task 7201", result.out)  # the task was changed: what the call answered is all that is known
        self.assertIn("could not be read back", result.err)
        self.area.read_back_fails = True
        data = self.cli("task", "7201", "--reopen", "--json").json()
        self.assertEqual((data["action"], data["readBack"], data["confirmed"]), ("reopened", False, None))
        self.assertEqual(data["notes"], [data["message"]])
        self.assertIn("could not be read back", data["message"])

    def test_a_dry_run_and_a_task_that_is_in_the_state_already_have_nothing_to_confirm(self):
        for argv in (("task", "7203", "--complete", "--dry-run", "--json"), ("task", "7202", "--complete", "--json"), ("task", "7202", "--complete", "--dry-run", "--json")):
            data = self.cli(*argv).json()
            with self.subTest(argv=argv):
                self.assertEqual((data["confirmed"], data["message"], data["notes"]), (None, None, []))
        self.assertEqual(self.mock.used_endpoints.count("PUT /api/v2/tasks/{id}"), 0)


class PropertyCreatedTest(EndToEnd):
    def test_what_confluence_says_of_the_new_property_is_what_the_line_says(self):
        result = self.cli("property-set", "2002", "--key", "zz.new", "--value", "1")
        self.assertEqual(result.code, 0, result.err)
        self.assertRegex(result.out, r"^Created the property zz\.new on the page 2002 \(id \d+, version 1\)\.\n$")

    def test_an_answer_that_names_no_id_is_a_creation_without_an_id(self):
        for answer in ({"key": "zz.new", "value": 1, "version": {"number": 1}}, {"key": "zz.new"}, {}, {"id": "", "key": "zz.new"}):
            self.mock.fail_next("/api/v2/pages/2002/properties", 200, method="POST", body=answer)
            result = self.cli("property-set", "2002", "--key", "zz.new", "--value", "1")
            with self.subTest(answer=answer):
                self.assertEqual(result.code, 0, result.err)
                self.assertEqual(result.out, "Created the property zz.new on the page 2002.\n")
                self.assertNotIn("(id", result.out)
                self.assertFalse(re.search(r"id\s*[,)]", result.out))
            self.mock.fail_next("/api/v2/pages/2002/properties", 200, method="POST", body=answer)
            data = self.cli("property-set", "2002", "--key", "zz.next", "--value", "1", "--json").json()
            with self.subTest(answer=answer, json=True):
                self.assertEqual((data["action"], data["propertyId"], data["versionTo"]), ("created", None, 1))

    def test_a_change_of_a_property_that_is_there_has_its_id_from_the_property_it_read(self):
        result = self.cli("property-set", "2002", "--key", "editor", "--value", '"v3"')
        self.assertEqual(result.code, 0, result.err)
        self.assertTrue(result.out.startswith("Updated the property editor of the page 2002 (version 1 -> 2)."), result.out)


if __name__ == "__main__":
    unittest.main()
