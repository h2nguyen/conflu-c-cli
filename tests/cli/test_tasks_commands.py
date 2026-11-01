"""The commands `tasks` and `task` on the command line, with the in-memory Confluence: what they print, what they refuse, how they are described."""
import dataclasses
import unittest

from conflu_c_cli.adapters.driving.cli.help import mcp_tool, render_command_help
from conflu_c_cli.adapters.driving.cli.parser import build_parser
from conflu_c_cli.adapters.driving.cli.registry import all_commands, find_command
from conflu_c_cli.domain.errors import AuthError, UnavailableError
from conflu_c_cli.domain.model import Chunk
from tests.support.cli import run_cli
from tests.support.fakes import ACCOUNT, BASE, FakeGateway, default_settings
from tests.support.fakes_tasks import BLOG_POST, SAM

ALL = ("7201", "7202", "7203", "7204", "7205", "7206")
PEOPLE = (ACCOUNT, SAM.account_id, "Alex Example", "alex@example.com", "Sam Example", "sam@example.com")


def fail_the_second_read(gateway):
    """The task is read once before a change and once after it: make the second read fail, as a server that stops answering would."""
    original = gateway.get_task
    reads = []

    def read(task_id):
        reads.append(task_id)
        if len(reads) > 1:
            raise UnavailableError("Confluence answered with a server error (HTTP 500).")
        return original(task_id)

    gateway.get_task = read


def rows(out):
    """The table of a list as lists of cells (every column is separated by two blanks, and the header is the first line)."""
    return [line.split() for line in out.splitlines()]


def ids(out):
    return [line.split()[0] for line in out.splitlines()[1:]]


class DescriptionTest(unittest.TestCase):
    def test_both_are_in_the_group_of_tasks_and_properties_and_say_what_they_do(self):
        for name in ("tasks", "task"):
            command = find_command(name)
            with self.subTest(command=name):
                self.assertEqual(command.group, "Tasks and properties")
                self.assertTrue(command.when and command.output and command.json_output and command.examples)
                self.assertFalse(command.for_person or command.local)

    def test_tasks_reads_and_task_changes_a_status_and_can_be_repeated_without_harm(self):
        self.assertFalse(find_command("tasks").writes)
        task = find_command("task")
        self.assertTrue(task.writes and task.idempotent)
        self.assertFalse(task.destructive)  # a status goes back with --reopen, and nothing else of a task can be changed here
        self.assertTrue(any("--dry-run" in arg.names for arg in task.args))

    def test_the_options_are_those_of_the_call_and_nothing_names_a_person(self):
        self.assertEqual(
            [arg.names[0] for arg in find_command("tasks").args],
            ["--space", "--page", "--task", "--status", "--mine", "--created-by-me", "--due-before", "--due-after", "--limit", "--cursor", "--all", "--with-users", "--select", "--format"],
        )
        self.assertEqual([arg.names[0] for arg in find_command("task").args], ["id", "--complete", "--reopen", "--dry-run"])
        for name in ("tasks", "task"):
            dests = {arg.dest for arg in find_command(name).args}
            self.assertFalse(dests & {"user", "account", "account_id", "assigned_to", "assignee", "created_by", "completed_by", "delete", "remove"}, name)

    def test_the_examples_parse(self):
        for name in ("tasks", "task"):
            for example in find_command(name).examples:
                with self.subTest(example=example.command):
                    build_parser(find_command(name)).parse_args(example.command.split()[2:])

    def test_the_help_says_what_the_filters_do_and_that_a_date_is_a_day_in_utc(self):
        text = " ".join(render_command_help(find_command("tasks")).split())
        for phrase in ("--mine", "never printed", "00:00 UTC", "YYYY-MM-DD", "A task without a due date is in no range", "--task", "at most 250", "that is no error"):
            self.assertIn(phrase, text)
        self.assertIn("--dry-run", render_command_help(find_command("task")))

    def test_the_ids_are_an_option_that_is_given_again_for_each_task_and_an_agent_gets_it_as_a_list(self):
        arg = next(arg for arg in find_command("tasks").args if arg.names == ("--task",))
        self.assertEqual((arg.kind, arg.metavar, arg.required), ("repeat", "ID", False))
        parsed = build_parser(find_command("tasks")).parse_args(["--task", "7201", "--task", "7203"])
        self.assertEqual(parsed.task, ["7201", "7203"])
        self.assertIsNone(build_parser(find_command("tasks")).parse_args([]).task)
        tool = mcp_tool(find_command("tasks"))
        schema = tool["inputSchema"]["properties"]["task"]
        self.assertEqual((schema["type"], schema["items"]), ("array", {"type": "string"}))
        self.assertIn("at most 250", schema["description"])
        self.assertTrue(tool["annotations"]["readOnlyHint"])  # one task is read without the command that can change tasks
        self.assertIn({"property": "task", "positional": False, "flag": "--task", "type": "array"}, tool["_meta"]["conflu"]["arguments"])

    def test_an_agent_is_told_how_far_it_goes(self):
        annotations = mcp_tool(find_command("task"))["annotations"]
        self.assertEqual((annotations["readOnlyHint"], annotations["destructiveHint"], annotations["idempotentHint"]), (False, False, True))
        self.assertTrue(mcp_tool(find_command("tasks"))["annotations"]["readOnlyHint"])
        self.assertIn("Changes Confluence. Run it with dryRun first", mcp_tool(find_command("task"))["description"])
        self.assertEqual(set(mcp_tool(find_command("task"))["inputSchema"]["properties"]), {"id", "complete", "reopen", "dryRun"})

    def test_an_argument_that_looks_like_a_path_says_what_it_is(self):
        for name in ("tasks", "task"):
            for arg in find_command(name).args:
                text = " ".join([*arg.names, arg.metavar, arg.help]).lower()
                with self.subTest(command=name, arg=arg.names[0]):
                    says = any(word in text for word in ("folder", "file", "path", "directory"))
                    self.assertTrue(not says or arg.not_a_path or arg.path or arg.at_file)

    def test_the_commands_are_listed_in_the_catalog(self):
        catalog = {item["name"]: item for item in run_cli("commands", "--json").json()["commands"]}
        self.assertTrue(catalog["task"]["changesData"] and not catalog["tasks"]["changesData"])
        self.assertIn("readBack", catalog["task"]["jsonOutput"])
        self.assertEqual([item.name for item in all_commands() if item.name in ("tasks", "task")], ["tasks", "task"])


class TasksListTest(unittest.TestCase):
    def test_the_first_piece_as_a_table_and_a_note_for_the_next_piece_on_standard_error(self):
        result = run_cli("tasks", gateway=FakeGateway())
        self.assertEqual(result.code, 0, result.err)
        lines = result.out.splitlines()
        self.assertEqual(lines[0].split(), ["ID", "STATUS", "DUE", "PAGE", "TEXT"])
        self.assertEqual(lines[1].split(None, 4), ["7201", "incomplete", "2026-10-20T00:00:00.000Z", "2002", "Check the numbers with @user"])
        self.assertEqual(ids(result.out), ["7201", "7202"])
        self.assertEqual(result.err, "[conflu] More tasks follow. Continue with --cursor 2, or use --all.\n")

    def test_the_cursor_goes_on_and_all_reads_everything(self):
        second = run_cli("tasks", "--cursor", "2", gateway=FakeGateway())
        self.assertEqual(ids(second.out), ["7203", "7204"])
        everything = run_cli("tasks", "--all", gateway=FakeGateway())
        self.assertEqual(ids(everything.out), list(ALL))
        self.assertEqual(everything.err, "")

    def test_a_blog_post_gets_a_column_of_its_own_only_when_one_is_in_the_list(self):
        with_post = run_cli("tasks", "--all", gateway=FakeGateway()).out.splitlines()
        self.assertEqual(with_post[0].split(), ["ID", "STATUS", "DUE", "PAGE", "BLOG", "POST", "TEXT"])
        self.assertIn(BLOG_POST, next(line for line in with_post if line.startswith("7205")))
        without = run_cli("tasks", "--page", "2002", gateway=FakeGateway()).out.splitlines()
        self.assertNotIn("BLOG", without[0])

    def test_a_task_without_a_due_date_has_an_empty_cell(self):
        line = next(line for line in run_cli("tasks", "--all", gateway=FakeGateway()).out.splitlines() if line.startswith("7204"))
        self.assertEqual(line.split(None, 3)[:3], ["7204", "incomplete", "2005"])

    def test_nothing_found_says_so(self):
        result = run_cli("tasks", "--due-after", "2030-01-01", gateway=FakeGateway())
        self.assertEqual((result.code, result.out, result.err), (0, "No tasks.\n", ""))

    def test_every_filter_is_handed_on(self):
        gateway = FakeGateway()
        result = run_cli("tasks", "--space", "ENG", "--status", "incomplete", "--mine", "--created-by-me", "--due-after", "2026-10-20", "--due-before", "2026-10-25", "--limit", "5", gateway=gateway)
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(gateway.called("list_tasks")[-1], ("list_tasks", "incomplete", (), ("1001",), (), (), (ACCOUNT,), (ACCOUNT,), 1_792_454_400_000, 1_792_886_400_000, 5, ""))
        self.assertEqual(ids(result.out), ["7201", "7205"])

    def test_the_ids_that_are_given_are_handed_on_and_only_those_tasks_are_listed(self):
        gateway = FakeGateway()
        result = run_cli("tasks", "--task", "7203", "--task", "7201", gateway=gateway)
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(ids(result.out), ["7201", "7203"])
        self.assertEqual(gateway.called("list_tasks")[-1][1:3], ("", ("7203", "7201")))
        self.assertEqual(result.err, "")
        one = run_cli("tasks", "--task", "7204", gateway=gateway)
        self.assertEqual(ids(one.out), ["7204"])

    def test_the_ids_go_with_the_other_filters_and_each_filter_still_has_to_hold(self):
        gateway = FakeGateway()
        result = run_cli("tasks", "--task", "7201", "--task", "7202", "--task", "7203", "--status", "incomplete", "--page", "2002", gateway=gateway)
        self.assertEqual(ids(result.out), ["7201"])
        mine = run_cli("tasks", "--task", "7202", "--task", "7203", "--mine", "--json", gateway=gateway)
        self.assertEqual([task["id"] for task in mine.json()["tasks"]], ["7203"])

    def test_an_id_that_no_task_has_is_an_empty_list_and_no_error(self):
        result = run_cli("tasks", "--task", "99999", gateway=FakeGateway())
        self.assertEqual((result.code, result.out, result.err), (0, "No tasks.\n", ""))
        as_json = run_cli("tasks", "--task", "99999", "--json", gateway=FakeGateway())
        self.assertEqual((as_json.code, as_json.json()["count"], as_json.json()["tasks"]), (0, 0, []))

    def test_the_list_that_the_ids_make_has_the_shape_of_every_list(self):
        every = run_cli("tasks", "--all", "--json", gateway=FakeGateway()).json()
        chosen = run_cli("tasks", "--task", "7205", "--task", "7203", "--json", gateway=FakeGateway()).json()
        self.assertEqual(set(chosen), set(every))
        self.assertEqual((chosen["space"], chosen["count"], chosen["nextCursor"], chosen["truncated"]), (None, 2, None, False))
        self.assertEqual([task["id"] for task in chosen["tasks"]], ["7203", "7205"])
        self.assertEqual(set(chosen["tasks"][0]), set(every["tasks"][0]))
        self.assertEqual((chosen["tasks"][1]["pageId"], chosen["tasks"][1]["blogPostId"]), (None, BLOG_POST))

    def test_the_ids_are_listed_in_pieces_too(self):
        gateway = FakeGateway()
        first = run_cli("tasks", "--task", "7201", "--task", "7202", "--task", "7203", gateway=gateway)
        self.assertEqual((ids(first.out), first.err), (["7201", "7202"], "[conflu] More tasks follow. Continue with --cursor 2, or use --all.\n"))
        everything = run_cli("tasks", "--task", "7201", "--task", "7202", "--task", "7203", "--all", gateway=gateway)
        self.assertEqual(ids(everything.out), ["7201", "7202", "7203"])

    def test_nobody_is_named_by_the_ids_either_unless_the_people_are_asked_for(self):
        for argv in (("--task", "7201", "--task", "7202"), ("--task", "7201", "--task", "7202", "--json")):
            result = run_cli("tasks", *argv, gateway=FakeGateway())
            with self.subTest(argv=argv):
                for text in PEOPLE:
                    self.assertNotIn(text, result.out + result.err)
        shown = run_cli("tasks", "--task", "7201", "--with-users", "--json", gateway=FakeGateway())
        self.assertEqual(shown.json()["tasks"][0]["assignedTo"]["email"], "alex@example.com")
        refused = run_cli("tasks", "--task", "7201", "--with-users", gateway=FakeGateway(), settings=default_settings(hide_users=True))
        self.assertEqual(refused.code, 1)

    def test_a_page_a_blog_post_and_a_status(self):
        self.assertEqual(ids(run_cli("tasks", "--page", "2002", "--status", "complete", gateway=FakeGateway()).out), ["7202"])
        self.assertEqual(ids(run_cli("tasks", "--page", BLOG_POST, gateway=FakeGateway()).out), ["7205"])
        self.assertEqual(ids(run_cli("tasks", "--page", f"{BASE}/spaces/ENG/pages/2003/Architecture", gateway=FakeGateway()).out), ["7203"])

    def test_mine_does_not_print_who_that_is(self):
        result = run_cli("tasks", "--mine", "--all", "--json", gateway=FakeGateway())
        self.assertEqual([task["id"] for task in result.json()["tasks"]], ["7201", "7203", "7205"])
        for text in PEOPLE:
            self.assertNotIn(text, result.out + result.err)

    def test_nobody_is_named_unless_the_people_are_asked_for(self):
        for argv in (("tasks", "--all"), ("tasks", "--all", "--json"), ("tasks", "--all", "--select", "id,assignedTo", "--format", "tsv"), ("tasks", "--mine", "--created-by-me", "--all")):
            result = run_cli(*argv, gateway=FakeGateway())
            with self.subTest(argv=argv):
                self.assertEqual(result.code, 0, result.err)
                for text in PEOPLE:
                    self.assertNotIn(text, result.out + result.err)

    def test_the_people_come_with_a_column_and_in_the_json_when_asked_for(self):
        gateway = FakeGateway()
        gateway.users[SAM.account_id] = SAM
        text = run_cli("tasks", "--all", "--with-users", gateway=gateway)
        self.assertEqual(text.out.splitlines()[0].split()[-1], "ASSIGNED")
        self.assertIn("Alex Example", next(line for line in text.out.splitlines() if line.startswith("7201")))
        self.assertIn("Sam Example", next(line for line in text.out.splitlines() if line.startswith("7202")))
        data = run_cli("tasks", "--page", "2002", "--with-users", "--json", gateway=gateway).json()
        first, second = data["tasks"]
        self.assertEqual(first["assignedTo"], {"accountId": ACCOUNT, "displayName": "Alex Example", "email": "alex@example.com"})
        self.assertEqual((second["assignedTo"]["displayName"], second["completedBy"]["accountId"], first["completedBy"]), ("Sam Example", SAM.account_id, None))

    def test_the_policy_that_hides_people_refuses_them_and_still_lists_the_tasks(self):
        refused = run_cli("tasks", "--with-users", gateway=FakeGateway(), settings=default_settings(hide_users=True))
        self.assertEqual((refused.code, refused.out), (1, ""))
        self.assertIn("CONFLUENCE_HIDE_USERS", refused.err)
        for text in PEOPLE:
            self.assertNotIn(text, refused.err)
        self.assertEqual(run_cli("tasks", "--all", gateway=FakeGateway(), settings=default_settings(hide_users=True)).code, 0)

    def test_the_text_of_a_task_has_no_mention_and_no_address(self):
        out = run_cli("tasks", "--all", gateway=FakeGateway()).out
        self.assertIn("Check the numbers with @user", out)
        self.assertIn("Mail [email] about the plan", out)

    def test_the_json_has_the_keys_of_the_documentation_and_a_null_for_what_is_not_there(self):
        data = run_cli("tasks", "--page", BLOG_POST, "--json", gateway=FakeGateway()).json()
        self.assertEqual(list(data), ["space", "count", "nextCursor", "truncated", "tasks"])
        self.assertEqual((data["space"], data["count"], data["nextCursor"], data["truncated"]), (None, 1, None, False))
        self.assertEqual(
            list(data["tasks"][0]),
            ["id", "localId", "status", "pageId", "blogPostId", "spaceId", "text", "dueAt", "createdAt", "updatedAt", "completedAt", "assignedTo", "createdBy", "completedBy"],
        )
        self.assertEqual((data["tasks"][0]["pageId"], data["tasks"][0]["blogPostId"], data["tasks"][0]["completedAt"]), (None, BLOG_POST, None))
        self.assertEqual(run_cli("tasks", "--space", "eng", "--json", gateway=FakeGateway()).json()["space"], "ENG")

    def test_the_next_cursor_is_in_the_json_and_the_note_for_a_person_is_not(self):
        result = run_cli("tasks", "--json", gateway=FakeGateway())
        self.assertEqual(result.json()["nextCursor"], "2")
        self.assertEqual(result.err, "")

    def test_a_list_can_be_shaped_for_a_script(self):
        tsv = run_cli("tasks", "--all", "--select", "id,status,dueAt", "--format", "tsv", gateway=FakeGateway()).out.splitlines()
        self.assertEqual(tsv[:3], ["id\tstatus\tdueAt", "7201\tincomplete\t2026-10-20T00:00:00.000Z", "7202\tcomplete\t2026-10-10T00:00:00.000Z"])
        md = run_cli("tasks", "--page", "2002", "--format", "md", gateway=FakeGateway()).out.splitlines()
        self.assertEqual(md[0], "| ID | STATUS | DUE | PAGE | TEXT |")
        data = run_cli("tasks", "--all", "--select", "id,status", "--json", gateway=FakeGateway()).json()
        self.assertEqual(data["tasks"][0], {"id": "7201", "status": "incomplete"})
        self.assertEqual(data["count"], 6)

    def test_a_name_that_is_not_a_key_of_a_task_is_a_usage_error_that_lists_the_names(self):
        result = run_cli("tasks", "--select", "nope", gateway=FakeGateway())
        self.assertEqual(result.code, 2)
        self.assertIn("Valid names:", result.err)
        self.assertIn("assignedTo", result.err)

    def test_text_that_shapes_a_list_cannot_go_with_json(self):
        self.assertEqual(run_cli("tasks", "--format", "tsv", "--json", gateway=FakeGateway()).code, 2)


class TasksRefusalTest(unittest.TestCase):
    def test_a_date_that_is_no_day_is_a_usage_error_with_an_example_and_nothing_is_asked(self):
        for argv in (("--due-before", "2026-02-30"), ("--due-after", "next week"), ("--due-after", "2026-11-01", "--due-before", "2026-10-01"), ("--due-after", "1969-12-31")):
            gateway = FakeGateway()
            result = run_cli("tasks", *argv, gateway=gateway)
            with self.subTest(argv=argv):
                self.assertEqual((result.code, result.out), (2, ""))
                self.assertTrue(result.err.startswith("ERROR: "), result.err)
                self.assertEqual(gateway.calls, [])
        self.assertIn("--due-before 2026-10-31", run_cli("tasks", "--due-before", "x", gateway=FakeGateway()).err)

    def test_the_error_is_json_when_json_is_asked_for(self):
        result = run_cli("tasks", "--due-before", "x", "--json", gateway=FakeGateway())
        self.assertEqual(result.code, 2)
        self.assertEqual(result.error()["code"], "USAGE")
        self.assertEqual(result.error()["exitCode"], 2)

    def test_the_limit_is_between_1_and_250(self):
        for limit in ("0", "251", "-1"):
            with self.subTest(limit=limit):
                self.assertEqual(run_cli("tasks", "--limit", limit, gateway=FakeGateway()).code, 2)
        self.assertEqual(run_cli("tasks", "--limit", "250", gateway=FakeGateway()).code, 0)

    def test_an_unknown_status_is_refused_by_the_parser(self):
        result = run_cli("tasks", "--status", "done", gateway=FakeGateway())
        self.assertEqual(result.code, 2)
        self.assertIn("incomplete", result.err)

    def test_an_id_that_is_no_task_id_is_a_usage_error_before_anything_is_asked(self):
        for text in ("abc", "0", "-3", "7201,7202", "1.5", "", "9223372036854775808"):
            gateway = FakeGateway()
            result = run_cli("tasks", "--task", "7201", "--task", text, "--mine", "--page", "2002", gateway=gateway)
            with self.subTest(text=text):
                self.assertEqual((result.code, result.out), (2, ""))
                self.assertIn("--task needs a task id", result.err)
                self.assertEqual(gateway.calls, [])
        as_json = run_cli("tasks", "--task", "abc", "--json", gateway=FakeGateway())
        self.assertEqual((as_json.code, as_json.error()["code"], as_json.error()["exitCode"]), (2, "USAGE", 2))
        self.assertEqual(run_cli("tasks", "--task", gateway=FakeGateway()).code, 2)  # the option needs a value

    def test_more_than_250_ids_are_refused_and_exactly_250_are_sent(self):
        many = [item for number in range(8000, 8251) for item in ("--task", str(number))]
        gateway = FakeGateway()
        refused = run_cli("tasks", *many, gateway=gateway)
        self.assertEqual((refused.code, refused.out), (2, ""))
        self.assertIn("at most 250", refused.err)
        self.assertEqual(gateway.calls, [])
        allowed = run_cli("tasks", *many[:-2], gateway=gateway)
        self.assertEqual((allowed.code, allowed.out), (0, "No tasks.\n"))
        self.assertEqual(len(gateway.called("list_tasks")[-1][2]), 250)

    def test_what_is_not_there_is_not_found_and_content_that_holds_no_tasks_is_said_so(self):
        self.assertEqual(run_cli("tasks", "--space", "NOPE", gateway=FakeGateway()).code, 4)
        self.assertEqual(run_cli("tasks", "--page", "99999", gateway=FakeGateway()).code, 4)
        folder = run_cli("tasks", "--page", "7001", gateway=FakeGateway())
        self.assertEqual(folder.code, 1)
        self.assertIn("a folder", folder.err)
        self.assertEqual(run_cli("tasks", "--page", "x/y", gateway=FakeGateway()).code, 1)


class TaskShowTest(unittest.TestCase):
    def test_a_task_with_its_text_and_where_it_is(self):
        result = run_cli("task", "7201", gateway=FakeGateway())
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(
            result.out,
            "Check the numbers with @user  [7201]\nStatus:   incomplete\nPage:     2002\nSpace id: 1001\nDue:      2026-10-20T00:00:00.000Z\nCreated:  2026-10-02T09:00:00.000Z\nUpdated:  2026-10-02T09:00:00.000Z\n",
        )

    def test_a_task_of_a_blog_post_and_a_completed_one_show_what_they_have(self):
        post = run_cli("task", "7205", gateway=FakeGateway()).out
        self.assertIn("Blog post: " + BLOG_POST, post)
        self.assertNotIn("Page:", post)
        done = run_cli("task", "7202", gateway=FakeGateway()).out
        self.assertIn("Completed: 2026-10-09T12:00:00.000Z", done)

    def test_nobody_is_named_not_even_with_json(self):
        for argv in (("task", "7202"), ("task", "7202", "--json")):
            result = run_cli(*argv, gateway=FakeGateway())
            for text in PEOPLE:
                self.assertNotIn(text, result.out + result.err)
        data = run_cli("task", "7202", "--json", gateway=FakeGateway()).json()
        self.assertEqual((data["assignedTo"], data["createdBy"], data["completedBy"]), (None, None, None))
        self.assertEqual(list(data), ["id", "localId", "status", "pageId", "blogPostId", "spaceId", "text", "dueAt", "createdAt", "updatedAt", "completedAt", "assignedTo", "createdBy", "completedBy"])

    def test_a_task_that_is_not_there_or_an_id_that_is_wrong(self):
        self.assertEqual(run_cli("task", "99999", gateway=FakeGateway()).code, 4)
        for text in ("abc", "7201x", "-1", "7201/../1"):
            with self.subTest(text=text):
                self.assertEqual(run_cli("task", text, gateway=FakeGateway()).code, 1)
        self.assertEqual(run_cli("task", gateway=FakeGateway()).code, 2)

    def test_a_text_with_a_newline_cannot_pretend_to_be_another_line(self):
        gateway = FakeGateway()
        gateway.tasks["7201"] = gateway.tasks["7201"].__class__("7201", "incomplete\nSpace id: spoof", "1001", "2002", body="<span>Real text</span>")
        out = run_cli("task", "7201", gateway=gateway).out
        self.assertEqual(sum(1 for line in out.splitlines() if line.startswith("Space id:")), 1)


class TaskChangeTest(unittest.TestCase):
    def test_complete_says_what_was_done(self):
        gateway = FakeGateway()
        result = run_cli("task", "7201", "--complete", gateway=gateway)
        self.assertEqual((result.code, result.out, result.err), (0, "Completed task 7201: Check the numbers with @user (incomplete -> complete)\n", ""))
        self.assertEqual(gateway.tasks["7201"].status, "complete")

    def test_reopen_says_what_was_done(self):
        gateway = FakeGateway()
        result = run_cli("task", "7202", "--reopen", gateway=gateway)
        self.assertEqual(result.out, "Reopened task 7202: Publish the release notes (complete -> incomplete)\n")
        self.assertEqual(gateway.tasks["7202"].status, "incomplete")

    def test_the_same_change_again_changes_nothing_and_says_so(self):
        gateway = FakeGateway()
        run_cli("task", "7201", "--complete", gateway=gateway)
        before = len(gateway.called("update_task"))
        again = run_cli("task", "7201", "--complete", gateway=gateway)
        self.assertEqual((again.code, again.out), (0, "Nothing to change: task 7201 is complete already.\n"))
        self.assertEqual(len(gateway.called("update_task")), before)

    def test_a_dry_run_shows_what_would_be_sent_and_sends_nothing(self):
        gateway = FakeGateway()
        result = run_cli("task", "7201", "--complete", "--dry-run", gateway=gateway)
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(result.out, 'Dry run: task 7201 would be completed (incomplete -> complete); nothing was sent\n{\n  "status": "complete"\n}\n')
        self.assertEqual((gateway.called("update_task"), gateway.tasks["7201"].status), ([], "incomplete"))

    def test_a_dry_run_of_what_is_so_already_says_so(self):
        result = run_cli("task", "7202", "--complete", "--dry-run", gateway=FakeGateway())
        self.assertEqual(result.out, "Nothing to change: task 7202 is complete already.\n")

    def test_the_json_of_a_change_and_of_a_dry_run(self):
        real = run_cli("task", "7203", "--complete", "--json", gateway=FakeGateway()).json()
        self.assertEqual(list(real), ["action", "dryRun", "taskId", "statusFrom", "statusTo", "readBack", "notes", "payload", "task", "confirmed", "message"])
        self.assertEqual((real["action"], real["dryRun"], real["taskId"], real["statusFrom"], real["statusTo"], real["readBack"], real["notes"], real["payload"]), ("completed", False, "7203", "incomplete", "complete", True, [], {"status": "complete"}))
        self.assertEqual((real["confirmed"], real["message"]), (True, None))
        self.assertEqual((real["task"]["status"], real["task"]["completedAt"] is not None), ("complete", True))
        dry = run_cli("task", "7203", "--complete", "--dry-run", "--json", gateway=FakeGateway()).json()
        self.assertEqual((dry["dryRun"], dry["readBack"], dry["payload"], dry["task"]["status"]), (True, False, {"status": "complete"}, "incomplete"))
        self.assertEqual((dry["confirmed"], dry["message"]), (None, None))
        same = run_cli("task", "7202", "--complete", "--json", gateway=FakeGateway()).json()
        self.assertEqual((same["action"], same["payload"], same["readBack"]), ("unchanged", None, False))
        self.assertEqual((same["confirmed"], same["message"]), (None, None))

    def test_nobody_is_named_in_a_change(self):
        for argv in (("--complete",), ("--complete", "--json"), ("--complete", "--dry-run"), ("--reopen", "--json")):
            result = run_cli("task", "7202", *argv, gateway=FakeGateway())
            with self.subTest(argv=argv):
                for text in PEOPLE:
                    self.assertNotIn(text, result.out + result.err)

    def test_both_flags_together_are_a_usage_error_and_nothing_is_asked(self):
        gateway = FakeGateway()
        result = run_cli("task", "7201", "--complete", "--reopen", gateway=gateway)
        self.assertEqual((result.code, result.out), (2, ""))
        self.assertEqual(gateway.calls, [])

    def test_a_dry_run_alone_has_nothing_to_preview(self):
        gateway = FakeGateway()
        result = run_cli("task", "7201", "--dry-run", gateway=gateway)
        self.assertEqual(result.code, 2)
        self.assertIn("--complete or --reopen", result.err)
        self.assertEqual(gateway.calls, [])

    def test_a_change_that_cannot_be_read_back_is_still_a_change_with_a_warning_and_exit_code_0(self):
        gateway = FakeGateway()
        fail_the_second_read(gateway)
        result = run_cli("task", "7201", "--complete", gateway=gateway)
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("Completed task 7201", result.out)
        self.assertIn("could not be read back", result.err)
        again = FakeGateway()
        fail_the_second_read(again)
        data = run_cli("task", "7201", "--complete", "--json", gateway=again).json()
        self.assertEqual((data["action"], data["readBack"], len(data["notes"])), ("completed", False, 1))
        # what is shown is what Confluence answered to the change (it saved the time and who completed it), not the task as it was with the new status
        saved = again.tasks["7201"]
        self.assertEqual((data["task"]["updatedAt"], data["task"]["completedAt"]), (saved.updated, saved.completed))
        self.assertNotEqual(data["task"]["updatedAt"], "2026-10-02T09:00:00.000Z")

    def test_all_does_not_use_limit_and_cursor_but_a_limit_out_of_range_is_still_refused(self):
        for limit in ("0", "251", "999"):
            gateway = FakeGateway()
            with self.subTest(limit=limit):
                self.assertEqual(run_cli("tasks", "--all", "--limit", limit, gateway=gateway).code, 2)
                self.assertEqual(gateway.calls, [])
        every = run_cli("tasks", "--all", "--limit", "1", "--cursor", "xyz", gateway=FakeGateway())
        self.assertEqual(ids(every.out), list(ALL))
        text = " ".join(render_command_help(find_command("tasks")).split())
        self.assertIn("--limit and --cursor are not used then, but a --limit out of range is still refused", text)

    def test_a_list_that_stops_at_its_limit_says_so_in_the_json_and_with_a_warning(self):
        gateway = FakeGateway()
        model = gateway.tasks["7201"]

        def endless(*, limit=25, cursor="", **filters):
            """A list that never ends: every piece holds new tasks and points to the next one."""
            first = int(cursor or 0) * limit
            return Chunk([dataclasses.replace(model, id=str(first + number)) for number in range(limit)], str(int(cursor or 0) + 1))

        gateway.list_tasks = endless
        text = run_cli("tasks", "--all", "--select", "id", "--format", "tsv", gateway=gateway)
        self.assertEqual(text.code, 0, text.err)
        self.assertIn("The list was cut short at its limit; narrow it with --space, --page, --status or --due-before.", text.err)
        data = run_cli("tasks", "--all", "--select", "id", "--json", gateway=gateway).json()
        self.assertEqual((data["truncated"], data["count"]), (True, 20000))
        self.assertEqual(run_cli("tasks", "--all", "--json", gateway=FakeGateway()).json()["truncated"], False)

    def test_a_task_that_is_not_there_and_a_refusal_of_confluence(self):
        self.assertEqual(run_cli("task", "99999", "--complete", gateway=FakeGateway()).code, 4)
        gateway = FakeGateway()
        gateway.errors["update_task"] = AuthError("Confluence refused this request (HTTP 403).", hint="No permission.")
        result = run_cli("task", "7201", "--complete", gateway=gateway)
        self.assertEqual(result.code, 5)
        self.assertEqual(gateway.tasks["7201"].status, "incomplete")


if __name__ == "__main__":
    unittest.main()
