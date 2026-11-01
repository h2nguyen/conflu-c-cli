"""The commands `properties` and `property-set` on the command line, with the in-memory Confluence: what they print, what they refuse, how they are described."""
import json
import shlex
import sys
import unittest

from conflu_c_cli.adapters.driving.cli.help import mcp_tool, render_command_help
from conflu_c_cli.adapters.driving.cli.mcp_calls import MAX_RESULT_CHARS
from conflu_c_cli.adapters.driving.cli.parser import build_parser
from conflu_c_cli.adapters.driving.cli.registry import all_commands, find_command
from conflu_c_cli.adapters.driving.cli.spec import READS_FILE
from conflu_c_cli.domain.errors import ConflictError
from conflu_c_cli.domain.properties import CUT_MARKER, STAND_INS, TOO_DEEP, ContentProperty, compact
from tests.support.cli import run_cli
from tests.support.fakes import ACCOUNT, BASE, FakeGateway, MemoryFiles, default_settings

PEOPLE = (ACCOUNT, "Alex Example", "alex@example.com")


class CountingFiles(MemoryFiles):
    """Files that know what was read: `size` looks at a file without reading it."""

    def __init__(self, files=None):
        super().__init__(files)
        self.reads = []

    def size(self, path):
        return len(self.files[path])

    def read_bytes(self, path):
        self.reads.append(path)
        return super().read_bytes(path)

    def read_text(self, path, encoding="utf-8"):
        self.reads.append(path)
        return super().read_text(path, encoding)


def fresh():
    gateway = FakeGateway()
    gateway.content_kinds.update({"4001": "footer-comment", "4003": "inline-comment"})
    return gateway


def deep(levels):
    value = None
    for _ in range(levels):
        value = [value]
    return value


class DescriptionTest(unittest.TestCase):
    def test_both_are_in_the_group_of_tasks_and_properties_and_say_what_they_do(self):
        for name in ("properties", "property-set"):
            command = find_command(name)
            with self.subTest(command=name):
                self.assertEqual(command.group, "Tasks and properties")
                self.assertTrue(command.when and command.output and command.json_output and command.examples and command.notes)
                self.assertFalse(command.for_person or command.local)

    def test_properties_reads_and_property_set_replaces_what_is_there_and_can_be_repeated(self):
        self.assertFalse(find_command("properties").writes)
        command = find_command("property-set")
        self.assertTrue(command.writes and command.destructive and command.idempotent)  # it saves over the value that is there: that is not only additive
        self.assertTrue(any("--dry-run" in arg.names for arg in command.args))

    def test_the_options_are_those_of_the_calls_and_no_command_deletes(self):
        self.assertEqual([arg.names[0] for arg in find_command("properties").args], ["id", "--key", "--max-chars", "--with-users", "--limit", "--cursor", "--all"])
        self.assertEqual([arg.names[0] for arg in find_command("property-set").args], ["id", "--key", "--value", "--file", "--message", "--if-version", "--dry-run"])
        for name in ("properties", "property-set"):
            dests = {arg.dest for arg in find_command(name).args}
            self.assertFalse(dests & {"delete", "remove", "clear", "force"}, name)
        self.assertEqual([command.name for command in all_commands() if "propert" in command.name], ["properties", "property-set"])

    def test_the_arguments_that_look_like_paths_say_what_they_are(self):
        arguments = {arg.names[0]: arg for arg in find_command("property-set").args}
        self.assertEqual(arguments["--file"].path, READS_FILE)
        self.assertTrue(arguments["--value"].not_a_path)  # its help speaks of a file, and it is the value itself
        for name in ("properties", "property-set"):
            for arg in find_command(name).args:
                text = " ".join([*arg.names, arg.metavar, arg.help]).lower()
                with self.subTest(command=name, arg=arg.names[0]):
                    says = any(word in text for word in ("folder", "file", "path", "directory"))
                    self.assertTrue(not says or arg.not_a_path or arg.path or arg.at_file)

    def test_the_examples_parse(self):
        for name in ("properties", "property-set"):
            for example in find_command(name).examples:
                with self.subTest(example=example.command):
                    words = shlex.split(example.command)  # the examples are written for a shell, whose quotes are not part of an argument
                    self.assertEqual(words[:2], ["conflu", name])
                    build_parser(find_command(name)).parse_args(words[2:])

    def test_the_help_warns_that_apps_use_properties_and_that_there_is_no_undo(self):
        text = " ".join(render_command_help(find_command("property-set")).split())
        for phrase in ("Apps keep their settings in properties", "no undo", "no command deletes a property", "Windows PowerShell 5.1", "--file", "32 KiB", "--if-version"):
            self.assertIn(phrase, text)

    def test_an_agent_is_told_how_far_it_goes(self):
        annotations = mcp_tool(find_command("property-set"))["annotations"]
        self.assertEqual((annotations["readOnlyHint"], annotations["destructiveHint"], annotations["idempotentHint"]), (False, True, True))
        self.assertTrue(mcp_tool(find_command("properties"))["annotations"]["readOnlyHint"])
        tool = mcp_tool(find_command("property-set"))
        self.assertIn("Changes Confluence. Run it with dryRun first", tool["description"])
        self.assertEqual(set(tool["inputSchema"]["properties"]), {"id", "key", "value", "file", "message", "ifVersion", "dryRun"})
        self.assertEqual(tool["inputSchema"]["required"], ["id", "key"])

    def test_the_commands_are_listed_in_the_catalog(self):
        catalog = {item["name"]: item for item in run_cli("commands", "--json").json()["commands"]}
        self.assertTrue(catalog["property-set"]["changesData"] and not catalog["properties"]["changesData"])
        self.assertIn("propertyId", catalog["property-set"]["jsonOutput"])


class PropertiesTest(unittest.TestCase):
    def test_the_properties_of_a_page_as_a_table_and_a_note_for_the_next_piece(self):
        result = run_cli("properties", "2002", gateway=fresh())
        self.assertEqual(result.code, 0, result.err)
        lines = result.out.splitlines()
        self.assertEqual(lines[0], "Properties of the page 2002:")
        self.assertEqual(lines[1].split(), ["ID", "KEY", "VERSION", "VALUE"])
        self.assertEqual(lines[2].split(None, 3), ["7302", "content-appearance-published", "2", '"full-width"'])
        self.assertEqual(lines[3].split(None, 3), ["7301", "editor", "1", '"v2"'])
        self.assertEqual(result.err, "[conflu] More properties follow. Continue with --cursor 2, or use --all.\n")

    def test_the_cursor_goes_on_and_all_reads_everything(self):
        self.assertEqual(run_cli("properties", "2002", "--cursor", "2", gateway=fresh()).out.splitlines()[2].split()[1], "team.review")
        everything = run_cli("properties", "2002", "--all", gateway=fresh())
        self.assertEqual([line.split()[1] for line in everything.out.splitlines()[2:]], ["content-appearance-published", "editor", "team.review"])
        self.assertEqual(everything.err, "")

    def test_one_key(self):
        result = run_cli("properties", "2002", "--key", "editor", gateway=fresh())
        self.assertEqual(result.out.splitlines()[2].split(), ["7301", "editor", "1", '"v2"'])
        self.assertEqual(result.err, "")

    def test_a_key_that_is_not_there_and_a_page_without_properties_say_so(self):
        self.assertEqual(run_cli("properties", "2002", "--key", "nope", gateway=fresh()).out, "No property with the key nope on the page 2002.\n")
        self.assertEqual(run_cli("properties", "2005", gateway=fresh()).out, "No properties on the page 2005.\n")

    def test_every_kind_of_content_is_named_as_what_it_is(self):
        for ref, name in (("7390", "the blog post 7390"), ("7391", "the folder 7391"), ("7392", "the whiteboard 7392"), ("7393", "the database 7393"), ("7394", "the smart link 7394"),
                          ("att5001", "the attachment att5001"), ("4001", "the footer comment 4001"), ("4003", "the inline comment 4003")):
            with self.subTest(ref=ref):
                result = run_cli("properties", ref, gateway=fresh())
                self.assertEqual(result.code, 0, result.err)
                self.assertEqual(result.out.splitlines()[0], f"Properties of {name}:")

    def test_the_address_of_a_page_names_it(self):
        self.assertEqual(run_cli("properties", f"{BASE}/spaces/ENG/pages/2002/Release+notes", gateway=fresh()).code, 0)

    def test_a_long_value_is_cut_and_a_note_says_how_to_see_it_whole(self):
        result = run_cli("properties", "2003", gateway=fresh())
        row = result.out.splitlines()[2]
        self.assertTrue(row.endswith(CUT_MARKER), row[-20:])
        self.assertEqual(
            result.err, f"[conflu] 1 value was cut to 2000 characters and end in {CUT_MARKER}; --max-chars 0 shows them whole. A value that was cut cannot be written back.\n"
        )
        short = run_cli("properties", "2003", "--max-chars", "30", gateway=fresh())
        self.assertIn('{"items":["item-000","item-001' + CUT_MARKER, short.out)
        whole = run_cli("properties", "2003", "--max-chars", "0", gateway=fresh())
        self.assertIn("item-399", whole.out)
        self.assertNotIn(CUT_MARKER, whole.out)
        self.assertEqual(whole.err, "")

    def test_people_in_a_value_are_hidden_unless_they_are_asked_for(self):
        for argv in (("properties", "2002", "--all"), ("properties", "2002", "--all", "--json"), ("properties", "2002", "--key", "team.review")):
            result = run_cli(*argv, gateway=fresh())
            with self.subTest(argv=argv):
                for text in PEOPLE:
                    self.assertNotIn(text, result.out + result.err)
        shown = run_cli("properties", "2002", "--key", "team.review", "--with-users", gateway=fresh()).out
        for text in (ACCOUNT, "Alex Example", "alex@example.com"):
            self.assertIn(text, shown)

    def test_the_policy_that_hides_people_refuses_them_and_still_shows_the_properties(self):
        refused = run_cli("properties", "2002", "--with-users", gateway=fresh(), settings=default_settings(hide_users=True))
        self.assertEqual((refused.code, refused.out), (1, ""))
        self.assertIn("CONFLUENCE_HIDE_USERS", refused.err)
        self.assertEqual(run_cli("properties", "2002", gateway=fresh(), settings=default_settings(hide_users=True)).code, 0)

    def test_the_json_has_the_keys_of_the_documentation(self):
        data = run_cli("properties", "2002", "--key", "editor", "--json", gateway=fresh()).json()
        self.assertEqual(list(data), ["target", "count", "nextCursor", "truncated", "properties"])
        self.assertEqual((data["target"], data["count"], data["nextCursor"], data["truncated"]), ({"id": "2002", "type": "page"}, 1, None, False))
        self.assertEqual(data["properties"], [{"id": "7301", "key": "editor", "version": 1, "updatedAt": "2026-10-01T08:00:00.000Z", "value": "v2", "truncated": False, "totalChars": None}])
        self.assertEqual(run_cli("properties", "2002", "--json", gateway=fresh()).json()["nextCursor"], "2")

    def test_a_value_in_the_json_is_the_value_and_a_cut_one_is_its_beginning(self):
        data = run_cli("properties", "7392", "--json", gateway=fresh()).json()
        self.assertEqual(data["properties"][0]["value"], {"zoom": 1.5})
        cut = run_cli("properties", "2003", "--max-chars", "40", "--json", gateway=fresh())
        item = cut.json()["properties"][0]
        self.assertEqual((item["truncated"], item["totalChars"], len(item["value"]), item["value"][:12]), (True, 4411, 40 + len(CUT_MARKER), '{"items":["i'))
        self.assertTrue(item["value"].endswith(CUT_MARKER))  # a copy that was cut says so in itself
        self.assertEqual(cut.err, "")  # the note for a person is not in the way of a script

    def test_what_is_not_there_is_not_found_and_what_is_no_id_is_invalid(self):
        self.assertEqual(run_cli("properties", "99999", gateway=fresh()).code, 4)
        self.assertEqual(run_cli("properties", "att99999", gateway=fresh()).code, 4)
        for ref in ("page", "../2002", "2002 2003", ""):
            with self.subTest(ref=ref):
                self.assertEqual(run_cli("properties", ref, gateway=fresh()).code, 1)
        self.assertEqual(run_cli("properties", gateway=fresh()).code, 2)

    def test_all_does_not_use_limit_and_cursor_but_a_limit_out_of_range_is_still_refused(self):
        for limit in ("0", "251", "999"):
            gateway = fresh()
            with self.subTest(limit=limit):
                self.assertEqual(run_cli("properties", "2002", "--all", "--limit", limit, gateway=gateway).code, 2)
                self.assertEqual(gateway.calls, [])
        every = run_cli("properties", "2002", "--all", "--limit", "1", "--cursor", "xyz", gateway=fresh())
        self.assertEqual([line.split()[1] for line in every.out.splitlines()[2:]], ["content-appearance-published", "editor", "team.review"])
        text = " ".join(render_command_help(find_command("properties")).split())
        self.assertIn("--limit and --cursor are not used then, but a --limit out of range is still refused", text)

    def test_a_negative_number_of_characters_and_a_limit_out_of_range_are_usage_errors(self):
        self.assertEqual(run_cli("properties", "2002", "--max-chars", "-1", gateway=fresh()).code, 2)
        for limit in ("0", "251"):
            self.assertEqual(run_cli("properties", "2002", "--limit", limit, gateway=fresh()).code, 2)

    def test_a_value_nested_too_deeply_or_with_control_characters_is_shown_safely(self):
        gateway = fresh()
        gateway.property_store[("pages", "2005")] = [
            ContentProperty("7399", "deep", 1, deep(5000)),
            ContentProperty("7398", "escape", 1, "before\x1b[2Jafter\nsecond line\u202e"),
            ContentProperty("7397", "half\ud800", 1, "pair\udc00"),
        ]
        for argv in (("properties", "2005", "--all"), ("properties", "2005", "--all", "--json")):
            result = run_cli(*argv, gateway=gateway)
            with self.subTest(argv=argv):
                self.assertEqual(result.code, 0, result.err)
                self.assertNotIn("\x1b", result.out)
                result.out.encode("utf-8")
        text = run_cli("properties", "2005", "--all", gateway=gateway).out
        self.assertIn(TOO_DEEP, text)
        self.assertEqual(sum(1 for line in text.splitlines() if line.split()[:1] == ["7398"]), 1)  # a line break in a value is not a new row
        self.assertIn("half\ufffd", text)


class PropertySetTest(unittest.TestCase):
    def test_a_new_key_is_created(self):
        gateway = fresh()
        result = run_cli("property-set", "2002", "--key", "new.key", "--value", '{"a":1}', gateway=gateway)
        self.assertEqual((result.code, result.out, result.err), (0, "Created the property new.key on the page 2002 (id 7313, version 1).\n", ""))
        self.assertEqual(gateway.called("create_property")[0], ("create_property", "page", "2002", {"key": "new.key", "value": {"a": 1}}))

    def test_a_key_that_is_there_gets_its_next_version_and_the_old_value_is_shown(self):
        gateway = fresh()
        result = run_cli("property-set", "2002", "--key", "editor", "--value", '"v3"', "--message", "Switched", gateway=gateway)
        self.assertEqual(result.out, 'Updated the property editor of the page 2002 (version 1 -> 2).\nIt held: "v2"\n')
        self.assertEqual(gateway.called("update_property")[0][-1], {"key": "editor", "value": "v3", "version": {"number": 2, "message": "Switched"}})

    def test_the_value_that_is_there_already_is_left_alone(self):
        gateway = fresh()
        result = run_cli("property-set", "2002", "--key", "editor", "--value", '"v2"', gateway=gateway)
        self.assertEqual(result.out, "Nothing to change: the property editor of the page 2002 holds that value already (version 1).\n")
        self.assertEqual((gateway.called("update_property"), gateway.called("create_property")), ([], []))

    def test_the_dry_run_of_a_creation_and_of_a_change_send_nothing(self):
        gateway = fresh()
        create = run_cli("property-set", "2002", "--key", "new.key", "--value", "[1,2]", "--dry-run", gateway=gateway)
        self.assertEqual(create.out, "Dry run: the property new.key would be created on the page 2002; nothing was sent\nvalue: [1,2]\n")
        change = run_cli("property-set", "2002", "--key", "editor", "--value", '"v3"', "--dry-run", gateway=gateway)
        self.assertEqual(change.out, 'Dry run: the property editor of the page 2002 would go from version 1 to 2; nothing was sent\ncurrent: "v2"\nnew:     "v3"\n')
        self.assertEqual((gateway.called("create_property"), gateway.called("update_property")), ([], []))
        self.assertEqual(len(gateway.property_store[("pages", "2002")]), 3)

    def test_what_a_dry_run_shows_is_what_the_real_run_sends(self):
        gateway = fresh()
        dry = run_cli("property-set", "2002", "--key", "editor", "--value", '{"b":2,"a":[1]}', "--message", "M", "--dry-run", "--json", gateway=gateway).json()
        run_cli("property-set", "2002", "--key", "editor", "--value", '{"b":2,"a":[1]}', "--message", "M", gateway=gateway)
        self.assertEqual(gateway.called("update_property")[0][-1], dry["payload"])

    def test_the_json_of_every_outcome(self):
        gateway = fresh()
        created = run_cli("property-set", "2002", "--key", "new.key", "--value", "true", "--json", gateway=gateway).json()
        self.assertEqual(list(created), ["action", "dryRun", "target", "key", "propertyId", "versionFrom", "versionTo", "value", "current", "payload", "notes"])
        self.assertEqual(
            (created["action"], created["dryRun"], created["target"], created["propertyId"], created["versionFrom"], created["versionTo"], created["value"], created["current"], created["payload"], created["notes"]),
            ("created", False, {"id": "2002", "type": "page"}, "7313", None, 1, True, None, {"key": "new.key", "value": True}, []),
        )
        updated = run_cli("property-set", "2002", "--key", "team.review", "--value", '"closed"', "--json", gateway=gateway).json()
        self.assertEqual((updated["action"], updated["propertyId"], updated["versionFrom"], updated["versionTo"]), ("updated", "7303", 3, 4))
        self.assertEqual(updated["current"], {"status": "open", "reviewer": {"hidden": True}, "owners": ["[hidden]"], "note": "Ask [email]"})
        same = run_cli("property-set", "2002", "--key", "editor", "--value", '"v2"', "--json", gateway=gateway).json()
        self.assertEqual((same["action"], same["payload"], same["versionFrom"], same["versionTo"]), ("unchanged", None, 1, 1))
        dry = run_cli("property-set", "2002", "--key", "another", "--value", "1", "--dry-run", "--json", gateway=gateway).json()
        self.assertEqual((dry["action"], dry["dryRun"], dry["propertyId"]), ("created", True, None))

    def test_a_message_that_could_not_be_used_is_said_so_below_the_answer_and_in_the_json(self):
        result = run_cli("property-set", "2002", "--key", "new.key", "--value", "1", "--message", "Hello", gateway=fresh())
        self.assertEqual(result.err, "[conflu] --message was not sent: a new property has no version message.\n")
        data = run_cli("property-set", "2002", "--key", "new.key", "--value", "1", "--message", "Hello", "--json", gateway=fresh())
        self.assertEqual(len(data.json()["notes"]), 1)
        self.assertEqual(data.err, "")  # the notes of the JSON are not said twice

    def test_the_people_that_were_in_the_old_value_are_not_shown_not_even_in_the_text_of_a_change(self):
        for argv in (("--dry-run",), (), ("--json",), ("--dry-run", "--json")):
            result = run_cli("property-set", "2002", "--key", "team.review", "--value", '"closed"', *argv, gateway=fresh())
            with self.subTest(argv=argv):
                self.assertEqual(result.code, 0, result.err)
                for text in PEOPLE:
                    self.assertNotIn(text, result.out + result.err)

    def test_the_value_may_come_from_a_file_or_from_standard_input(self):
        gateway = fresh()
        files = MemoryFiles({"value.json": '{"from": "a file"}\n'})
        result = run_cli("property-set", "2002", "--key", "from.file", "--file", "value.json", gateway=gateway, files=files)
        self.assertEqual(result.code, 0, result.err)
        piped = run_cli("property-set", "2002", "--key", "from.pipe", "--file", "-", gateway=gateway, stdin="[1, 2, 3]\n")
        self.assertEqual(piped.code, 0, piped.err)
        self.assertEqual([call[-1]["value"] for call in gateway.called("create_property")], [{"from": "a file"}, [1, 2, 3]])

    def test_a_file_that_windows_powershell_wrote_is_read(self):
        gateway = fresh()
        files = MemoryFiles({"value.json": '{"text": "caf\u00e9"}'.encode("utf-16")})
        result = run_cli("property-set", "2002", "--key", "from.ps", "--file", "value.json", gateway=gateway, files=files)
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(gateway.called("create_property")[0][-1]["value"], {"text": "caf\u00e9"})

    def test_a_file_that_is_far_too_big_is_refused_unread_and_so_is_a_pipe(self):
        gateway = fresh()
        files = CountingFiles({"big.json": "[" + "1," * 600_000 + "1]"})
        result = run_cli("property-set", "2002", "--key", "big", "--file", "big.json", gateway=gateway, files=files)
        self.assertEqual(result.code, 1)
        self.assertIn("big.json is 1,200,003 bytes", result.err)  # its size was asked for; the message of a text that was read says characters
        self.assertEqual(files.reads, [])  # and it was not read
        piped = run_cli("property-set", "2002", "--key", "big", "--file", "-", gateway=gateway, stdin="[" + "1," * 600_000 + "1]")
        self.assertEqual(piped.code, 1)
        self.assertIn("standard input", piped.err)
        self.assertEqual(gateway.calls, [])  # nothing was asked of Confluence, not even what the content is

    def test_a_file_that_is_not_there_is_an_error(self):
        result = run_cli("property-set", "2002", "--key", "x", "--file", "missing.json", gateway=fresh(), files=MemoryFiles())
        self.assertNotEqual(result.code, 0)

    def test_the_value_and_the_file_are_exclusive_and_one_of_them_is_needed(self):
        gateway = fresh()
        both = run_cli("property-set", "2002", "--key", "x", "--value", "1", "--file", "-", gateway=gateway, stdin="2")
        self.assertEqual(both.code, 2)
        none = run_cli("property-set", "2002", "--key", "x", gateway=gateway)
        self.assertEqual(none.code, 2)
        self.assertIn("--value JSON", none.err)
        self.assertEqual(gateway.calls, [])

    def test_a_text_without_quotes_is_a_usage_error_with_the_hint_for_powershell(self):
        gateway = fresh()
        result = run_cli("property-set", "2002", "--key", "x", "--value", "open", gateway=gateway)
        self.assertEqual(result.code, 2)
        self.assertIn("a text needs double quotes", result.err)
        self.assertIn("PowerShell 5.1", result.err)
        self.assertIn("--file", result.err)
        self.assertEqual(gateway.calls, [])

    def test_a_value_that_is_not_json_or_is_empty_or_too_big_or_nested_too_deeply_is_refused_before_anything_is_asked(self):
        for text, code in (
            ('{"a":}', 2), ("", 2), ("   ", 2), ("NaN", 2), ("Infinity", 2), ("1e999", 2), ("[1, 1e999]", 2), ('"' + "x" * 40_000 + '"', 1), ("[" * 500 + "]" * 500, 1),
            ("[" * 50_000 + "]" * 50_000, 1), ('"\\ud800"', 1),
        ):
            gateway = fresh()
            result = run_cli("property-set", "2002", "--key", "x", "--value", text, gateway=gateway)
            with self.subTest(text=text[:30]):
                self.assertEqual(result.code, code, result.err)
                self.assertEqual(gateway.calls, [])

    def test_a_number_too_large_to_be_a_number_is_refused_before_anything_is_asked_whatever_way_it_comes(self):
        cases = ((("--value", "1e999"), ""), (("--value=-1e999",), ""), (("--value", '{"a":[1,{"b":-1e999}]}'), ""), (("--file", "-"), "[1e400]"), (("--value", "1e999", "--dry-run"), ""))
        for argv, stdin in cases:
            gateway = fresh()
            result = run_cli("property-set", "2002", "--key", "big.num", *argv, gateway=gateway, stdin=stdin)
            with self.subTest(argv=argv):
                self.assertEqual((result.code, result.out), (2, ""))
                self.assertIn("The value is not valid JSON", result.err)
                self.assertIn("too large for a number", result.err)
                self.assertEqual(gateway.calls, [])  # nothing is asked and nothing is sent, not even to show a dry run

    def test_a_negative_number_with_an_exponent_needs_the_equals_sign_and_a_plain_negative_number_does_not(self):
        gateway = fresh()
        self.assertEqual(run_cli("property-set", "2002", "--key", "n1", "--value=-1e5", gateway=gateway).code, 0)
        self.assertEqual(run_cli("property-set", "2002", "--key", "n2", "--value", "-5", gateway=gateway).code, 0)
        self.assertEqual(run_cli("property-set", "2002", "--key", "n3", "--value", "-1.5", gateway=gateway).code, 0)
        reads_it = sys.version_info >= (3, 14)  # argparse of Python 3.14 reads `-1e5` as a number; before it, the program takes it for an option: the guide says so
        self.assertEqual(run_cli("property-set", "2002", "--key", "n4", "--value", "-1e5", gateway=gateway).code, 0 if reads_it else 2)
        expected = {"n1": -100000.0, "n2": -5, "n3": -1.5, **({"n4": -100000.0} if reads_it else {})}
        self.assertEqual({call[-1]["key"]: call[-1]["value"] for call in gateway.called("create_property")}, expected)

    def test_a_value_that_was_cut_is_refused_with_exit_code_1_and_the_way_to_the_whole_one_works(self):
        gateway = fresh()
        cut = run_cli("properties", "2003", "--key", "inventory", "--json", gateway=gateway).json()["properties"][0]
        self.assertEqual((cut["truncated"], cut["totalChars"]), (True, 4411))
        for argv in ((), ("--dry-run",), ("--json",)):
            refused = run_cli("property-set", "2003", "--key", "inventory", "--file", "-", *argv, gateway=gateway, stdin=json.dumps(cut["value"]))
            with self.subTest(argv=argv):
                self.assertEqual((refused.code, refused.out), (1, ""))
                self.assertIn(f"The new value holds `{CUT_MARKER}`", refused.err)
                self.assertIn("conflu properties 2003 --key inventory --max-chars 0 --json", refused.err)
        self.assertEqual((gateway.called("update_property"), gateway.called("create_property")), ([], []))
        error = run_cli("property-set", "2003", "--key", "inventory", "--file", "-", "--json", gateway=gateway, stdin=json.dumps(cut["value"])).error()
        self.assertEqual((error["code"], error["details"]["markers"]), ("INVALID", [CUT_MARKER]))
        whole = run_cli("properties", "2003", "--key", "inventory", "--max-chars", "0", "--json", gateway=gateway).json()["properties"][0]
        self.assertEqual((whole["truncated"], whole["totalChars"]), (False, None))
        edited = {**whole["value"], "items": [*whole["value"]["items"], "item-new"]}
        taken = run_cli("property-set", "2003", "--key", "inventory", "--file", "-", gateway=gateway, stdin=json.dumps(edited))
        self.assertEqual(taken.code, 0, taken.err)
        self.assertEqual(len(gateway.called("update_property")[0][-1]["value"]["items"]), 401)

    def test_the_dry_run_shows_a_long_value_cut_at_500_characters_with_the_mark_and_how_many_more_there_are(self):
        gateway = fresh()
        held = compact({"items": [f"item-{number:03d}" for number in range(400)]})
        new = compact({"items": [f"new-{number:03d}" for number in range(100)]})
        lines = run_cli("property-set", "2003", "--key", "inventory", "--value", new, "--dry-run", gateway=gateway).out.splitlines()
        self.assertEqual(lines[1], f"current: {held[:500]}{CUT_MARKER} ({len(held) - 500:,} more characters)")
        self.assertEqual(lines[2], f"new:     {new[:500]}{CUT_MARKER} ({len(new) - 500:,} more characters)")
        short = run_cli("property-set", "2003", "--key", "inventory", "--value", "[1]", "--dry-run", gateway=gateway).out.splitlines()
        self.assertEqual(short[2], "new:     [1]")

    def test_a_key_that_is_not_a_key_is_refused_before_anything_is_asked(self):
        for key in ("bad key", "a/b", "x" * 256, "a\nb", "é", ""):
            gateway = fresh()
            result = run_cli("property-set", "2002", "--key", key, "--value", "1", gateway=gateway)
            with self.subTest(key=key[:20]):
                self.assertEqual(result.code, 2)
                self.assertEqual(gateway.calls, [])
        self.assertEqual(run_cli("property-set", "2002", "--value", "1", gateway=fresh()).code, 2)  # --key is needed

    def test_the_guard_refuses_with_exit_code_3_before_anything_is_sent(self):
        gateway = fresh()
        result = run_cli("property-set", "2002", "--key", "team.review", "--value", "1", "--if-version", "2", gateway=gateway)
        self.assertEqual((result.code, result.out), (3, ""))
        self.assertIn("is at version 3, not 2", result.err)
        self.assertIn("conflu properties 2002 --key team.review", result.err)
        self.assertEqual((gateway.called("update_property"), gateway.called("create_property")), ([], []))
        as_json = run_cli("property-set", "2002", "--key", "team.review", "--value", "1", "--if-version", "2", "--json", gateway=gateway)
        self.assertEqual((as_json.code, as_json.error()["code"], as_json.error()["exitCode"], as_json.error()["details"]), (3, "CONFLICT", 3, {"id": "2002", "key": "team.review", "version": 3, "expected": 2}))

    def test_the_value_that_the_people_were_hidden_from_is_refused_with_exit_code_1_and_nothing_is_sent(self):
        hidden = '{"status": "closed", "reviewer": {"hidden": true}, "owners": ["[hidden]"], "note": "Ask [email]"}'
        for argv in ((), ("--dry-run",), ("--if-version", "3"), ("--message", "Closed")):
            gateway = fresh()
            result = run_cli("property-set", "2002", "--key", "team.review", "--value", hidden, *argv, gateway=gateway)
            with self.subTest(argv=argv):
                self.assertEqual((result.code, result.out), (1, ""))
                self.assertIn("The new value holds `[hidden]`, `[email]` and `{\"hidden\": true}`", result.err)
                self.assertIn("the property team.review of the page 2002", result.err)
                self.assertIn("conflu properties 2002 --key team.review --with-users --max-chars 0 --json", result.err)
                self.assertEqual((gateway.called("update_property"), gateway.called("create_property")), ([], []))
                for text in PEOPLE:
                    self.assertNotIn(text, result.err)
        as_json = run_cli("property-set", "2002", "--key", "team.review", "--value", hidden, "--json", gateway=fresh())
        error = as_json.error()
        self.assertEqual((as_json.code, error["code"], error["exitCode"]), (1, "INVALID", 1))
        self.assertEqual(error["details"], {"id": "2002", "key": "team.review", "markers": ["[hidden]", "[email]", '{"hidden": true}']})

    def test_what_properties_shows_without_the_people_is_refused_and_what_it_shows_with_them_is_taken_back_as_it_is(self):
        gateway = fresh()
        shown = run_cli("properties", "2002", "--key", "team.review", "--json", gateway=gateway).json()["properties"][0]["value"]
        refused = run_cli("property-set", "2002", "--key", "team.review", "--file", "-", gateway=gateway, stdin=json.dumps(shown))
        self.assertEqual(refused.code, 1, refused.err)
        real = run_cli("properties", "2002", "--key", "team.review", "--with-users", "--json", gateway=gateway).json()["properties"][0]["value"]
        for argv, stdin in (((), json.dumps(real)), (("--json",), json.dumps({**real, "status": "closed"}))):
            taken = run_cli("property-set", "2002", "--key", "team.review", "--file", "-", *argv, gateway=gateway, stdin=stdin)
            self.assertEqual(taken.code, 0, taken.err)
        sent = gateway.called("update_property")
        self.assertEqual(len(sent), 1)  # the first was the value that is there already
        self.assertEqual((sent[0][-1]["value"]["reviewer"]["accountId"], sent[0][-1]["value"]["owners"]), (ACCOUNT, [ACCOUNT]))

    def test_the_help_of_both_commands_says_so(self):
        for name, phrases in (
            ("property-set", ("refused with exit code 1", "would overwrite what the property holds", "--with-users --max-chars 0", "refused for a new property too")),
            ("properties", ("property-set", "refuses the cut and the hidden form", "--with-users --max-chars 0", "0 cuts nothing")),
        ):
            text = " ".join(render_command_help(find_command(name)).split())
            for phrase in phrases:
                with self.subTest(command=name, phrase=phrase):
                    self.assertIn(phrase, text)

    def test_the_help_names_every_stand_in_that_is_refused_and_the_mark_of_a_cut_from_the_lists_that_refuse_them(self):
        for name in ("property-set", "properties"):
            text = " ".join(render_command_help(find_command(name)).split())
            tool = mcp_tool(find_command(name))["description"]
            for mark in (*STAND_INS, CUT_MARKER) if name == "property-set" else (CUT_MARKER,):
                with self.subTest(command=name, mark=mark):
                    self.assertIn(f"`{mark}`", text)
                    self.assertIn(f"`{mark}`", tool)  # an agent learns it from the tool as well
        self.assertEqual(len(STAND_INS), 6)  # the number is the length of the list, and no sentence says another

    def test_the_guard_that_is_right_lets_the_change_through_and_zero_means_new(self):
        gateway = fresh()
        self.assertEqual(run_cli("property-set", "2002", "--key", "team.review", "--value", "1", "--if-version", "3", gateway=gateway).code, 0)
        self.assertEqual(run_cli("property-set", "2002", "--key", "brand.new", "--value", "1", "--if-version", "0", gateway=gateway).code, 0)
        self.assertEqual(run_cli("property-set", "2002", "--key", "editor", "--value", '"x"', "--if-version", "0", gateway=gateway).code, 3)
        self.assertEqual(run_cli("property-set", "2002", "--key", "x", "--value", "1", "--if-version", "-1", gateway=gateway).code, 2)

    def test_a_save_that_lost_against_somebody_else_is_exit_code_3_and_the_hint_speaks_of_a_property(self):
        gateway = fresh()
        gateway.errors["update_property"] = ConflictError("Confluence reports a conflict (HTTP 409).", hint="The page changed meanwhile.", details={"status": 409})
        result = run_cli("property-set", "2002", "--key", "editor", "--value", '"v3"', gateway=gateway)
        self.assertEqual(result.code, 3)
        self.assertNotIn("The page changed", result.err)
        self.assertIn("conflu properties 2002 --key editor", result.err)

    def test_content_that_is_not_there_is_not_found_and_nothing_is_written(self):
        gateway = fresh()
        result = run_cli("property-set", "99999", "--key", "x", "--value", "1", gateway=gateway)
        self.assertEqual(result.code, 4)
        self.assertEqual((gateway.called("create_property"), gateway.called("list_properties")), ([], []))

    def test_every_kind_of_content_is_named_in_the_answer(self):
        for ref, name in (("7390", "the blog post 7390"), ("7391", "the folder 7391"), ("7392", "the whiteboard 7392"), ("7393", "the database 7393"), ("7394", "the smart link 7394"),
                          ("att5001", "the attachment att5001"), ("4001", "the footer comment 4001"), ("4003", "the inline comment 4003")):
            with self.subTest(ref=ref):
                result = run_cli("property-set", ref, "--key", "kind.test", "--value", "1", gateway=fresh())
                self.assertEqual(result.code, 0, result.err)
                self.assertIn(f"on {name}", result.out)

    def test_the_value_survives_the_trip_as_json_whatever_it_is(self):
        for text in ("0", "-1.5", "null", "false", '""', "[]", "{}", '"\u00e9\u4e2d\\n"', '{"a":{"b":[null,true,1.5e3]}}'):
            gateway = fresh()
            result = run_cli("property-set", "2002", "--key", "round.trip", "--value", text, "--json", gateway=gateway)
            with self.subTest(text=text):
                self.assertEqual(result.code, 0, result.err)
                self.assertEqual(json.loads(text), gateway.called("create_property")[0][-1]["value"])


def served(*calls, allow_write=False, gateway=None):
    """`conflu mcp` with the fake Confluence behind it: `(is an error, the text)` of the result of each call, which is `(tool, arguments)`."""
    requests = [{"jsonrpc": "2.0", "id": number, "method": "tools/call", "params": {"name": name, "arguments": arguments}} for number, (name, arguments) in enumerate(calls, start=1)]
    result = run_cli("mcp", *(("--allow-write",) if allow_write else ()), stdin="".join(json.dumps(request) + "\n" for request in requests), gateway=gateway or fresh())
    return [(reply["result"]["isError"], reply["result"]["content"][0]["text"]) for reply in (json.loads(line) for line in result.out.splitlines())]


class AgentTest(unittest.TestCase):
    """The agent that edits a property through the tools: the whole value is `maxChars` 0 of `conflu_properties`, and a cut value that it writes back is refused."""

    def test_a_value_is_cut_by_default_and_the_whole_of_it_comes_with_max_chars_zero(self):
        (cut_error, cut_text), (whole_error, whole_text) = served(
            ("conflu_properties", {"id": "2003", "key": "inventory"}), ("conflu_properties", {"id": "2003", "key": "inventory", "maxChars": 0})
        )
        cut, whole = json.loads(cut_text)["properties"][0], json.loads(whole_text)["properties"][0]
        self.assertEqual((cut_error, whole_error), (False, False))
        self.assertEqual((cut["truncated"], cut["totalChars"], cut["value"].endswith(CUT_MARKER)), (True, 4411, True))
        self.assertEqual((whole["truncated"], len(whole["value"]["items"])), (False, 400))

    def test_the_largest_value_that_can_be_written_is_read_whole_within_what_a_result_may_hold(self):
        gateway = fresh()
        largest = ["x" * 30_000, "y" * 2_000]  # compact JSON of a little under 32 KiB: the most that `property-set` takes
        gateway.property_store[("pages", "2005")] = [ContentProperty("7399", "largest", 1, largest)]
        ((error, text),) = served(("conflu_properties", {"id": "2005", "key": "largest", "maxChars": 0}), gateway=gateway)
        self.assertFalse(error)
        self.assertEqual(json.loads(text)["properties"][0]["value"], largest)
        self.assertLess(len(text), MAX_RESULT_CHARS // 2)

    def test_the_cut_value_that_an_agent_writes_back_is_refused_and_the_property_is_as_it_was(self):
        gateway = fresh()
        ((_, text),) = served(("conflu_properties", {"id": "2003", "key": "inventory"}), gateway=gateway)
        cut = json.loads(text)["properties"][0]["value"]
        for arguments in ({"value": json.dumps(cut)}, {"value": json.dumps(cut), "dryRun": True}):
            ((error, answer),) = served(("conflu_property_set", {"id": "2003", "key": "inventory", **arguments}), allow_write=True, gateway=gateway)
            with self.subTest(arguments=sorted(arguments)):
                self.assertTrue(error)
                failure = json.loads(answer)["error"]
                self.assertEqual((failure["code"], failure["exitCode"], failure["details"]["markers"]), ("INVALID", 1, [CUT_MARKER]))
                self.assertIn("--max-chars 0", failure["hint"])
        self.assertEqual((gateway.called("update_property"), gateway.called("create_property")), ([], []))

    def test_the_tools_name_the_way_to_the_whole_value_and_stay_far_below_the_limit_of_a_tool(self):
        reading, writing = (mcp_tool(find_command(name)) for name in ("properties", "property-set"))
        self.assertIn("`withUsers` `maxChars` 0", reading["description"])  # the options of a command are the arguments of its tool: --max-chars is `maxChars`
        self.assertIn("with --with-users --max-chars 0", writing["description"])  # and those of another command are left as they are: they are options of `properties`
        for tool in (reading, writing):
            self.assertLess(len(json.dumps(tool, ensure_ascii=False)), 7_000)


if __name__ == "__main__":
    unittest.main()
