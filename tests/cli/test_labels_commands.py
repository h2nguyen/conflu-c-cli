"""The commands `labels` and `label` on the command line, with the in-memory Confluence: what they print, what they refuse, how they are described.

The labels of a page and the adding and removing of labels were there before the labels of a space: what they print is checked to the character."""
import shlex
import unittest

from conflu_c_cli.adapters.driving.cli.help import mcp_property_names, mcp_tool
from conflu_c_cli.adapters.driving.cli.parser import build_parser
from conflu_c_cli.adapters.driving.cli.registry import find_command
from conflu_c_cli.domain.errors import NotFoundError
from conflu_c_cli.domain.model import Label
from tests.support.cli import run_cli
from tests.support.fakes import FakeGateway, default_settings


class DescriptionTest(unittest.TestCase):
    def test_what_a_reader_needs_to_choose_the_command_is_there(self):
        for name, group in (("labels", "Read"), ("label", "Work on a page")):
            command = find_command(name)
            with self.subTest(command=name):
                self.assertEqual(command.group, group)
                self.assertTrue(command.when and command.output and command.json_output and command.examples and command.description)

    def test_the_reader_says_where_to_find_the_pages_that_carry_a_label(self):
        command = find_command("labels")
        self.assertIn("`search`", command.when)
        self.assertIn("label option", command.when)
        self.assertTrue(any("conflu search --label" in note for note in command.notes))

    def test_the_reader_changes_nothing_and_the_writer_only_adds_or_removes_what_it_is_told_to(self):
        reader = find_command("labels")
        self.assertFalse(reader.writes or reader.destructive or reader.for_person or reader.local)
        writer = find_command("label")
        self.assertTrue(writer.writes and writer.destructive and writer.idempotent)
        self.assertFalse(writer.for_person or writer.local)
        self.assertTrue(any("--dry-run" in arg.names for arg in writer.args))

    def test_the_page_is_optional_now_and_the_options_of_a_list_are_there(self):
        arguments = {arg.names[0]: arg for arg in find_command("labels").args}
        self.assertFalse(arguments["ref"].required)
        for option in ("--space", "--limit", "--cursor", "--all", "--select", "--format"):
            self.assertIn(option, arguments)
        self.assertEqual(arguments["--limit"].kind, "int")

    def test_every_example_is_a_valid_command_line(self):
        for name in ("labels", "label"):
            command = find_command(name)
            for example in command.examples:
                with self.subTest(example=example.command):
                    words = shlex.split(example.command)
                    self.assertEqual(words[:2], ["conflu", name])
                    build_parser(command).parse_args(words[2:])

    def test_an_argument_that_speaks_of_a_path_says_whether_it_is_one(self):
        for name in ("labels", "label"):
            for arg in find_command(name).args:
                text = " ".join([*arg.names, arg.metavar, arg.help]).lower()
                with self.subTest(command=name, arg=arg.names[0]):
                    says = any(word in text for word in ("folder", "file", "path", "directory"))
                    self.assertTrue(not says or arg.not_a_path or arg.path or arg.at_file)

    def test_the_tool_of_an_agent_names_distinct_properties_and_no_flag_of_its_own_in_the_text(self):
        for name in ("labels", "label"):
            command = find_command(name)
            names = mcp_property_names(command)
            self.assertEqual(len(names), len(set(names.values())), name)
            tool = mcp_tool(command)
            text = tool["description"] + " ".join(prop["description"] for prop in tool["inputSchema"]["properties"].values())
            for arg in command.args:
                if not arg.positional and not arg.text_only:
                    with self.subTest(command=name, arg=arg.names[0]):
                        self.assertNotIn(f" {arg.names[0]} ", text + " ")
        self.assertEqual(mcp_tool(find_command("labels"))["inputSchema"]["required"], [])

    def test_the_catalog_lists_the_options(self):
        catalog = run_cli("commands", "--json").json()["commands"]
        labels = next(item for item in catalog if item["name"] == "labels")
        self.assertEqual([arg["names"][0] for arg in labels["arguments"]][:5], ["ref", "--space", "--limit", "--cursor", "--all"])
        self.assertFalse(next(arg for arg in labels["arguments"] if arg["names"][0] == "ref")["required"])
        self.assertFalse(labels["changesData"])
        self.assertTrue(next(item for item in catalog if item["name"] == "label")["changesData"])


class PageLabelsTest(unittest.TestCase):
    """What `conflu labels PAGE` printed before the labels of a space: to the character."""

    def test_the_text_is_a_table_of_names_and_prefixes(self):
        result = run_cli("labels", "2002")
        self.assertEqual((result.code, result.out, result.err), (0, "NAME     PREFIX\nrelease  global\nnotes    global\n", ""))

    def test_a_page_without_labels_says_so(self):
        self.assertEqual(run_cli("labels", "2003").out, "No labels.\n")

    def test_the_json_has_the_two_keys_it_had_in_the_order_it_had_them(self):
        out = run_cli("labels", "2002", "--json").out
        self.assertEqual(out, '{"pageId":"2002","labels":[{"name":"release","prefix":"global"},{"name":"notes","prefix":"global"}]}\n')
        self.assertEqual(run_cli("labels", "2003", "--json").json(), {"pageId": "2003", "labels": []})

    def test_the_address_of_a_page_is_as_good_as_its_id(self):
        out = run_cli("labels", "https://example.atlassian.net/wiki/spaces/ENG/pages/2002/Release+notes").out
        self.assertTrue(out.startswith("NAME     PREFIX\nrelease"))

    def test_the_labels_of_a_page_are_listed_whole_in_one_request_of_the_use_case(self):
        gateway = FakeGateway()
        run_cli("labels", "2002", "--json", gateway=gateway)
        self.assertEqual(gateway.called("list_labels"), [("list_labels", "2002")])
        self.assertEqual(gateway.called("list_space_labels"), [])

    def test_the_new_options_may_be_used_with_a_page_where_they_make_sense(self):
        self.assertEqual(run_cli("labels", "2002", "--select", "name", "--format", "tsv").out, "name\nrelease\nnotes\n")
        self.assertEqual(run_cli("labels", "2002", "--select", "name", "--json").json(), {"pageId": "2002", "labels": [{"name": "release"}, {"name": "notes"}]})

    def test_what_belongs_to_a_space_is_refused_for_a_page_with_the_way_out(self):
        for option in (("--limit", "5"), ("--cursor", "2"), ("--all",)):
            with self.subTest(option=option):
                result = run_cli("labels", "2002", *option)
                self.assertEqual(result.code, 2)
                self.assertIn(f"{option[0]} applies to --space", result.err)
                self.assertIn("--space KEY", result.err)
                self.assertEqual(result.out, "")

    def test_a_page_that_does_not_exist_is_exit_code_4_and_a_bad_page_id_exit_code_1(self):
        self.assertEqual(run_cli("labels", "999").code, 4)
        self.assertEqual(run_cli("labels", "not-a-page").code, 1)


class SpaceLabelsTest(unittest.TestCase):
    def test_the_labels_of_the_content_of_a_space_a_piece_at_a_time(self):
        result = run_cli("labels", "--space", "ENG")
        self.assertEqual(result.code, 0)
        self.assertEqual(result.out, "NAME   PREFIX\nadr    global\nnotes  global\n")
        self.assertIn("More labels follow. Continue with --cursor 2, or use --all.", result.err)

    def test_the_cursor_continues_and_the_last_piece_has_no_note(self):
        result = run_cli("labels", "--space", "ENG", "--cursor", "2")
        self.assertEqual(result.out, "NAME     PREFIX\nrelease  global\n")
        self.assertEqual(result.err, "")

    def test_all_reads_every_piece_and_says_nothing_of_more(self):
        result = run_cli("labels", "--space", "ENG", "--all")
        self.assertEqual(result.out.split(), ["NAME", "PREFIX", "adr", "global", "notes", "global", "release", "global"])
        self.assertEqual(result.err, "")

    def test_the_json_is_one_document_with_the_space_and_the_labels(self):
        data = run_cli("labels", "--space", "ENG", "--all", "--json").json()
        self.assertEqual(list(data), ["space", "spaceId", "count", "nextCursor", "truncated", "labels"])
        self.assertEqual((data["space"], data["spaceId"], data["count"], data["nextCursor"], data["truncated"]), ("ENG", "1001", 3, None, False))
        self.assertEqual(data["labels"], [{"name": "adr", "prefix": "global"}, {"name": "notes", "prefix": "global"}, {"name": "release", "prefix": "global"}])

    def test_one_piece_in_json_has_the_cursor_for_the_next_and_no_note_on_standard_error(self):
        result = run_cli("labels", "--space", "ENG", "--json")
        self.assertEqual((result.json()["count"], result.json()["nextCursor"]), (2, "2"))
        self.assertEqual(result.err, "")
        last = run_cli("labels", "--space", "ENG", "--cursor", "2", "--json").json()
        self.assertEqual((last["count"], last["nextCursor"]), (1, None))

    def test_a_space_in_any_case_and_a_space_without_labels(self):
        self.assertEqual(run_cli("labels", "--space", "eng", "--all", "--json").json()["space"], "ENG")
        self.assertEqual(run_cli("labels", "--space", "DOCS").out, "No labels.\n")
        data = run_cli("labels", "--space", "DOCS", "--json").json()
        self.assertEqual((data["space"], data["count"], data["labels"], data["nextCursor"]), ("DOCS", 0, [], None))

    def test_the_labels_may_be_cut_to_their_names_and_printed_as_a_table(self):
        self.assertEqual(run_cli("labels", "--space", "ENG", "--all", "--select", "name", "--format", "tsv").out, "name\nadr\nnotes\nrelease\n")
        table = run_cli("labels", "--space", "ENG", "--all", "--format", "md").out.splitlines()
        self.assertEqual(table[:3], ["| NAME | PREFIX |", "| --- | --- |", "| adr | global |"])
        data = run_cli("labels", "--space", "ENG", "--all", "--select", "name", "--json").json()
        self.assertEqual(data["labels"], [{"name": "adr"}, {"name": "notes"}, {"name": "release"}])
        self.assertEqual(data["space"], "ENG")
        self.assertEqual(run_cli("labels", "--space", "DOCS", "--format", "tsv").out, "NAME\tPREFIX\n")

    def test_the_limit_is_the_size_of_a_piece_and_must_be_between_one_and_250(self):
        gateway = FakeGateway()
        run_cli("labels", "--space", "ENG", "--limit", "7", gateway=gateway)
        self.assertEqual(gateway.called("list_space_labels"), [("list_space_labels", "1001", 7, "")])
        default = FakeGateway()
        run_cli("labels", "--space", "ENG", gateway=default)
        self.assertEqual(default.called("list_space_labels")[0][2], 25)
        for value in ("0", "251", "-1", "many"):
            with self.subTest(limit=value):
                self.assertEqual(run_cli("labels", "--space", "ENG", "--limit", value).code, 2)

    def test_a_page_or_a_space_must_be_named_and_not_both(self):
        both = run_cli("labels", "2002", "--space", "ENG")
        self.assertEqual(both.code, 2)
        self.assertIn("Name a page or a space, not both.", both.err)
        neither = run_cli("labels")
        self.assertEqual(neither.code, 2)
        self.assertIn("Name a page or a space.", neither.err)
        self.assertIn("The current space of `conflu use` is not assumed here.", neither.err)

    def test_the_current_space_is_not_assumed(self):
        result = run_cli("labels", settings=default_settings(space="ENG"))
        self.assertEqual(result.code, 2)
        self.assertEqual(result.out, "")

    def test_a_space_that_does_not_exist_is_exit_code_4_and_a_bad_key_exit_code_1(self):
        self.assertEqual(run_cli("labels", "--space", "NOPE").code, 4)
        for key in ("", "E N G", "ENG/../x", "ENG?x=1"):
            with self.subTest(key=key):
                gateway = FakeGateway()
                self.assertEqual(run_cli("labels", "--space", key, gateway=gateway).code, 1)
                self.assertEqual(gateway.calls, [])

    def test_a_failure_of_confluence_is_reported_with_its_exit_code(self):
        gateway = FakeGateway()
        gateway.errors["list_space_labels"] = NotFoundError("Not found: GET /api/v2/spaces/1001/content/labels", details={"status": 404})
        error = run_cli("labels", "--space", "ENG", "--json", gateway=gateway)
        self.assertEqual(error.code, 4)
        self.assertEqual(error.error()["code"], "NOT_FOUND")

    def test_a_label_with_a_prefix_other_than_global_is_listed_with_it(self):
        gateway = FakeGateway()
        gateway.pages["2003"].labels.append(Label("mine", "my"))
        data = run_cli("labels", "--space", "ENG", "--all", "--json", gateway=gateway).json()
        self.assertIn({"name": "mine", "prefix": "my"}, data["labels"])

    def test_a_label_with_a_hostile_name_is_printed_as_text(self):
        gateway = FakeGateway()
        gateway.pages["2003"].labels.append(Label("a|b\nc\x1b[31m"))
        out = run_cli("labels", "--space", "ENG", "--all", "--format", "md", gateway=gateway).out
        self.assertNotIn("\x1b", out)
        self.assertIn("a\\|b c", out)  # a pipe is escaped in a Markdown table and a line end is one blank


class LabelCommandTest(unittest.TestCase):
    """Adding and removing labels: as it was, to the character."""

    def test_the_dry_run_names_what_would_change_and_sends_nothing(self):
        gateway = FakeGateway()
        out = run_cli("label", "2002", "--add", "reviewed,adr", "--remove", "notes", "--dry-run", gateway=gateway).out
        self.assertEqual(out, "Dry run (nothing was sent): page 2002: would add: reviewed, adr; would remove: notes\nLabels: release, notes\n")
        self.assertEqual((gateway.called("add_labels"), gateway.called("remove_label")), ([], []))

    def test_adding_and_removing(self):
        gateway = FakeGateway()
        self.assertEqual(run_cli("label", "2002", "--add", "reviewed", gateway=gateway).out, "page 2002: added: reviewed\nLabels now: release, notes, reviewed\n")
        data = run_cli("label", "2002", "--remove", "notes", "--json", gateway=gateway).json()
        self.assertEqual(data, {"pageId": "2002", "dryRun": False, "added": [], "removed": ["notes"], "labels": ["release", "reviewed"]})

    def test_a_label_that_is_there_already_or_not_at_all_is_skipped(self):
        out = run_cli("label", "2002", "--add", "release", "--remove", "absent").out
        self.assertEqual(out, "page 2002: nothing to change, the labels are as asked\nLabels now: release, notes\n")

    def test_no_labels_is_exit_code_1_and_a_label_in_both_lists_is_too(self):
        self.assertEqual(run_cli("label", "2002").code, 1)
        both = run_cli("label", "2002", "--add", "x", "--remove", "x")
        self.assertEqual(both.code, 1)
        self.assertIn("is in --add and in --remove", both.err)

    def test_a_label_that_confluence_would_refuse_is_exit_code_1_before_any_request_to_change(self):
        gateway = FakeGateway()
        result = run_cli("label", "2002", "--add", "a b", gateway=gateway)
        self.assertEqual(result.code, 1)
        self.assertEqual(gateway.called("add_labels"), [])

    def refused_when_empty(self, option, *others):
        for value in ("", "  ", ",", " , "):
            for extra in ((), ("--dry-run",)):
                with self.subTest(option=option, value=value, extra=extra):
                    gateway = FakeGateway()
                    result = run_cli("label", "2002", option, value, *others, *extra, gateway=gateway)
                    self.assertEqual(result.code, 1)
                    self.assertIn(f"{option} is empty", result.err.splitlines()[0])
                    self.assertEqual(result.out, "")
                    self.assertEqual(gateway.calls, [])  # not even a read of the page

    def test_an_empty_add_is_an_error_that_names_it_and_nothing_is_read_or_sent(self):
        self.refused_when_empty("--add", "--remove", "notes")
        self.refused_when_empty("--add")

    def test_an_empty_remove_is_an_error_that_names_it_and_nothing_is_read_or_sent(self):
        self.refused_when_empty("--remove", "--add", "reviewed")
        self.refused_when_empty("--remove")

    def test_an_empty_item_among_names_is_skipped_as_it_was_and_an_option_that_is_left_out_is_not_given(self):
        out = run_cli("label", "2002", "--add", "reviewed,,adr", "--dry-run").out
        self.assertEqual(out, "Dry run (nothing was sent): page 2002: would add: reviewed, adr\nLabels: release, notes\n")
        self.assertEqual(run_cli("label", "2002", "--remove", "notes", "--dry-run").code, 0)


if __name__ == "__main__":
    unittest.main()
