"""The lines about a personal space (tests/support/sweep_personal.py), read out of the runs of the privacy sweep, which runs every line of every module under both
policies and is not run twice here: that every line was run and ended as it says, that nothing it prints names the owner of the space, and that the scan is not empty
(with people asked for, the account id is there)."""
import unittest

from tests.integration.test_privacy_sweep import default_run, strict_run
from tests.support import sweep_personal
from tests.support.personal_space import PERSONAL
from tests.support.sweep_personal import BLOGPOST, LINKING, PAGE
from tests.support.taint import ADDRESS_MARKERS, MARKERS, PEOPLE_MARKERS

AREA = "sweep_personal"
# the commands that can print the key of a space, the id of one, an address or a path: each has a line for what lies in a personal space
READERS = {
    "pages", "page", "blogposts", "blogpost", "labels", "comments", "comment", "attachments", "attachment", "download", "versions", "diff", "restrictions",
    "permissions", "watching", "properties", "search", "export", "tree", "folder", "whiteboard", "database", "smartlink", "tasks", "task", "templates", "template",
}
WRITERS = {"blogpost-create", "blogpost-update", "label", "attach", "property-set", "watch", "task"}
# the lines that stand first among those of their command and are refused by the mock with HTTP 403, with the address of a person in the explanation (see PREPARE)
REFUSED = {("tasks", "--space", PERSONAL), ("templates", "--space", PERSONAL), ("templates", "--blueprints", "--space", PERSONAL)}


def printed(result):
    return [output for output in result.outputs if output.area == AREA]


def text_of(output):
    """Everything that a line gave out: what it printed and the files that `export` wrote."""
    return (output.out + output.err + output.written).lower()


class PersonalSweepTest(unittest.TestCase):
    def test_every_line_was_run_and_ended_as_it_says(self):
        self.assertEqual(len(printed(default_run())), len(sweep_personal.LINES))
        self.assertEqual([failure for failure in default_run().failures if failure.startswith(AREA)], [])

    def test_the_lines_read_the_space_with_every_command_that_can_name_it_and_write_to_it(self):
        commands = {item.argv[0] for item in sweep_personal.LINES}
        self.assertEqual(sorted(READERS - commands), [])
        self.assertEqual(sorted(WRITERS - commands), [])

    def test_a_page_of_the_space_and_a_page_that_links_into_it_are_read_in_every_form(self):
        read = {tuple(item.argv) for item in sweep_personal.LINES}
        for ref in (PAGE, LINKING):
            for option in ("--json", "--raw", "--with-users"):
                self.assertIn(("page", ref, option), read)
            self.assertIn(("page", ref, "--format", "storage"), read)
        self.assertIn(("blogpost", BLOGPOST, "--json", "--comments"), read)

    def test_without_people_nothing_names_the_owner_not_even_the_key_that_was_typed(self):
        leaked = [
            f"conflu {' '.join(output.argv)} printed {marker!r}"
            for output in printed(default_run())
            if "--with-users" not in output.argv
            for marker in PEOPLE_MARKERS + ADDRESS_MARKERS
            if marker in text_of(output)
        ]
        self.assertEqual(leaked, [])

    def test_under_the_policy_nothing_does_and_a_request_for_people_is_refused(self):
        leaked = [f"conflu {' '.join(output.argv)} printed {marker!r}" for output in printed(strict_run()) for marker in MARKERS if marker in text_of(output)]
        self.assertEqual(leaked, [])
        asked = [output for output in printed(strict_run()) if "--with-users" in output.argv]
        self.assertGreaterEqual(len(asked), 8)
        self.assertEqual([output.argv for output in asked if output.code != 1], [])

    def test_what_export_wrote_is_read_too(self):
        wrote = [output for output in printed(default_run()) if output.argv[0] == "export" and "--dry-run" not in output.argv]
        self.assertGreaterEqual(len(wrote), 5)
        for output in wrote:
            with self.subTest(argv=output.argv):
                self.assertIn('"pages"', output.written)  # the index of the export, and below it the pages
                self.assertIn("page_id:", output.written)

    def test_the_refused_lines_say_why_and_name_the_space_as_hidden(self):
        refused = {}
        for output in printed(default_run()):
            if tuple(output.argv) in REFUSED:
                refused.setdefault(tuple(output.argv), output)  # the first of the same lines is the one that was refused
        self.assertEqual(set(refused), REFUSED)
        for argv, output in refused.items():
            with self.subTest(argv=argv):
                self.assertEqual(output.code, 5)
                self.assertIn("(HTTP 403)", output.err)
                self.assertNotIn("alex@example.com", output.err)  # the explanation of Confluence is left out or redacted
        for argv in (("templates", "--space", PERSONAL), ("templates", "--blueprints", "--space", PERSONAL)):
            self.assertIn("templates of the space [hidden]", refused[argv].err)

    def test_with_people_asked_for_the_key_is_there_so_that_the_scan_is_not_empty(self):
        shown = {tuple(output.argv) for output in printed(default_run()) if "--with-users" in output.argv and PERSONAL in output.out}
        for argv in (
            ("page", PAGE, "--with-users"),
            ("page", LINKING, "--with-users"),
            ("comments", PAGE, "--with-users"),
            ("search", "Personal", "--space", PERSONAL, "--with-users"),
            ("tasks", "--space", PERSONAL, "--with-users", "--json"),
        ):
            self.assertIn(argv, shown)


if __name__ == "__main__":
    unittest.main()
