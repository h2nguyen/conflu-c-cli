"""`conflu commands --format mcp`: the commands an agent may use, described as tools (name, input schema, annotations)."""
import json
import re
import unittest
from pathlib import Path

from conflu_c_cli.adapters.driving.cli.help import (
    catalog,
    mcp_property_names,
    mcp_tool,
    mcp_tools,
    render_command_help,
    tool_groups,
)
from conflu_c_cli.adapters.driving.cli.mcp_server import listed, select_tools
from conflu_c_cli.adapters.driving.cli.parser import build_parser
from conflu_c_cli.adapters.driving.cli.registry import all_commands, find_command
from conflu_c_cli.version import __version__
from tests.support.cli import run_cli

JSON_TYPES = {"string", "integer", "number", "boolean", "array"}
ROOT = Path(__file__).resolve().parents[2]
FOR_THE_PERSON = {"setup-token", "remove-token", "config", "use", "clear-space", "api", "help", "commands", "skill", "changelog", "setup", "mcp"}  # the commands that hold or change credentials and settings, the ones that describe the CLI, and the server that offers the tools
DESTRUCTIVE = {"update", "move", "label", "import-md", "import-md-dir", "comment"}  # they replace, move or remove (`comment --edit` replaces the text of a comment)
ADDITIVE = {"create", "attach"}  # as of 1.0.0: they add and never replace, move or remove
WRITE_FILES = {"export", "download"}  # they change nothing in Confluence and write files on this computer: not read-only, and offered by `conflu mcp` only with --allow-files


def tools(only="all"):
    return mcp_tools(all_commands(), __version__, only=only)["tools"]


def argv_from(tool, arguments):
    """What a program that reads `_meta.conflu` does: the arguments of a call become a command line."""
    meta = tool["_meta"]["conflu"]
    argv = list(meta["command"][1:])
    for item in meta["arguments"]:
        value = arguments.get(item["property"])
        if not item["positional"] or value is None:
            continue
        argv += [str(part) for part in value] if item["type"] == "array" else [str(value)]
    for item in meta["arguments"]:
        value = arguments.get(item["property"])
        if item["positional"] or value is None or value is False:
            continue
        if item["type"] == "boolean":
            argv.append(item["flag"])
        elif item["type"] == "array":
            for part in value:
                argv += [item["flag"], str(part)]
        else:
            argv += [item["flag"], str(value)]
    return argv + meta["alwaysAppend"]


def sample(schema):
    if "enum" in schema:
        return schema["enum"][-1]
    return {"boolean": True, "integer": 7, "number": 1.5, "array": ["one", "two"]}.get(schema["type"], "sample text")


class SchemaTest(unittest.TestCase):
    def test_every_tool_is_a_well_formed_description(self):
        names = set()
        for tool in tools():
            with self.subTest(tool=tool["name"]):
                self.assertRegex(tool["name"], r"^[a-zA-Z0-9_-]{1,64}$")
                self.assertNotIn(tool["name"], names)
                names.add(tool["name"])
                self.assertTrue(tool["title"])
                self.assertIn("When to use:", tool["description"])
                schema = tool["inputSchema"]
                self.assertEqual((schema["type"], schema["additionalProperties"]), ("object", False))
                self.assertLessEqual(set(schema["required"]), set(schema["properties"]))
                for name, prop in schema["properties"].items():
                    self.assertRegex(name, r"^[a-z][A-Za-z0-9]*$")
                    self.assertIn(prop["type"], JSON_TYPES)
                    self.assertTrue(prop["description"])
                    if "enum" in prop:
                        self.assertTrue(prop["enum"])
                    if prop["type"] == "array":
                        self.assertEqual(prop["items"], {"type": "string"})
                    if "default" in prop and "enum" in prop:
                        self.assertIn(prop["default"], prop["enum"])

    def test_the_properties_of_a_tool_have_distinct_names(self):
        for command in all_commands():
            names = list(mcp_property_names(command).values())
            with self.subTest(command=command.name):
                self.assertEqual(len(names), len(set(names)))

    def test_an_option_is_named_in_camel_case_and_a_positional_by_what_it_is(self):
        search = {t["name"]: t for t in tools()}["conflu_search"]["inputSchema"]["properties"]
        self.assertIn("text", search)
        self.assertEqual(search["match"]["enum"], ["all", "any", "auto"])
        self.assertEqual((search["snippets"]["type"], search["snippets"]["default"] if "default" in search["snippets"] else 0), ("integer", 0))
        update = {t["name"]: t for t in tools()}["conflu_update"]["inputSchema"]
        self.assertEqual(update["required"], ["page"])
        self.assertEqual({"ifVersion", "ifUnchangedSince", "dryRun", "append", "prepend", "maxChars"} & set(update["properties"]), {"ifVersion", "ifUnchangedSince", "dryRun", "append", "prepend"})
        self.assertEqual({t["name"]: t for t in tools()}["conflu_import_md_dir"]["inputSchema"]["required"], ["dir"])


def size(value):
    return len(json.dumps(value, ensure_ascii=False))


TOOL_LIMIT, AVERAGE_LIMIT, GROUP_LIMIT = 7_000, 2_800, 40_000


class BudgetTest(unittest.TestCase):
    """What a client puts into the context of a model when it loads the tools of `conflu mcp`.

    The measure is what the server sends, `tools/list` as `mcp_server.listed` makes it, in characters of JSON (about four of them are a token).
    The table of the arguments and the examples in `_meta.conflu` are for a program that builds a command line itself: they stay in
    `conflu commands --format mcp` and are not sent over MCP, where they were a quarter of the listing.

    The three numbers, and why:

    - TOOL_LIMIT, 7,000 characters for one tool (about 1,750 tokens): the number that was there before, and still the most that one tool may
      cost, in the catalogue form too, which is the larger. The largest tool, `conflu_search`, uses two thirds of it.
    - AVERAGE_LIMIT, 2,800 characters for the tools of a set on average (about 700 tokens). The first design held about 20 read tools in
      45,000 characters, 2,200 each. Today the 33 read tools average about 2,150 and all 51 tools about 2,330, and the limit leaves a fifth
      above that for the tools that are still to come. It is an average and not a total so that the budget grows with the CLI: a total of
      45,000 failed as soon as the feature areas arrived (the read tools are about 71,000), and raising it to the new total would have let the
      next area through unseen.
    - GROUP_LIMIT, 40,000 characters for all the tools of one group with every switch on (about 10,000 tokens). `--group` is how a client that cannot
      afford the whole set loads one kind of work (`conflu mcp --group Read`, `conflu commands --format mcp --group Read`), so no group may cost
      more than that. `Read` is the largest, at about 31,000.

    A failure names the number that was passed. The way out is to shorten the text of the tool (the description, `output=`, the help of the
    arguments) or to split the command; if a number has to go up, the reason goes into the changelog and into docs/how-to/mcp-server.md,
    which names all three."""

    @staticmethod
    def sent(allow_write, allow_files):
        return [listed(tool) for tool in select_tools(all_commands(), allow_write=allow_write, allow_files=allow_files).tools]

    def test_no_tool_costs_more_than_the_limit_in_either_form(self):
        for tool in tools():
            self.assertLess(size(tool), TOOL_LIMIT, f"{tool['name']}: the catalogue form is over TOOL_LIMIT")
        for tool in self.sent(True, True):
            self.assertLess(size(tool), TOOL_LIMIT, f"{tool['name']}: over TOOL_LIMIT as `conflu mcp` sends it")

    def test_a_tool_costs_the_average_or_less_in_the_default_set_and_in_the_whole(self):
        for allow_write, allow_files in ((False, False), (True, True)):
            sent = self.sent(allow_write, allow_files)
            average = size(sent) / len(sent)
            self.assertLess(average, AVERAGE_LIMIT, f"{len(sent)} tools, {size(sent):,} characters: the average is over AVERAGE_LIMIT")

    def test_no_group_costs_more_than_the_limit_with_every_switch_on(self):
        by_group = {}
        for tool in self.sent(True, True):
            group = find_command(tool["_meta"]["conflu"]["command"][1]).group
            by_group[group] = by_group.get(group, 0) + size(tool)
        self.assertEqual(set(by_group), set(tool_groups(all_commands())))
        for group, cost in by_group.items():
            self.assertLess(cost, GROUP_LIMIT, f"the group {group}: {cost:,} characters, over GROUP_LIMIT")

    def test_what_the_server_sends_is_a_good_deal_less_than_the_catalogue(self):
        sent = self.sent(False, False)
        catalogue = mcp_tools(all_commands(), __version__, only="read")["tools"]
        self.assertEqual([tool["name"] for tool in sent], [tool["name"] for tool in catalogue])
        self.assertLess(size(sent), size(catalogue) * 0.8)

    def test_the_guide_names_the_three_numbers(self):
        guide = (ROOT / "docs" / "how-to" / "mcp-server.md").read_text(encoding="utf-8")
        for limit in (TOOL_LIMIT, AVERAGE_LIMIT, GROUP_LIMIT):
            self.assertIn(f"{limit:,}", guide, f"docs/how-to/mcp-server.md must state the limit {limit:,}")


class WhatIsOfferedTest(unittest.TestCase):
    def test_what_is_for_the_person_is_never_offered(self):
        offered = {tool["name"] for tool in tools()}
        for name in ("setup-token", "remove-token", "config", "use", "clear-space", "api", "help", "commands", "skill", "changelog", "setup", "mcp"):
            self.assertNotIn("conflu_" + name.replace("-", "_"), offered)
        self.assertEqual({command.name for command in all_commands() if command.for_person}, FOR_THE_PERSON)  # no stale name, none added by mistake

    def test_the_default_set_changes_nothing_in_confluence(self):
        by_name = {command.name: command for command in all_commands()}
        for tool in tools("read"):
            with self.subTest(tool=tool["name"]):
                command = by_name[tool["_meta"]["conflu"]["command"][1]]
                self.assertFalse(command.writes)
                self.assertTrue(tool["annotations"]["readOnlyHint"])
                self.assertNotIn("destructiveHint", tool["annotations"])  # meaningless for a read-only tool

    def test_the_write_set_is_all_writes_and_says_how_far_they_go(self):
        for tool in tools("write"):
            with self.subTest(tool=tool["name"]):
                annotations = tool["annotations"]
                self.assertFalse(annotations["readOnlyHint"])
                self.assertIsInstance(annotations["destructiveHint"], bool)
                self.assertIsInstance(annotations["idempotentHint"], bool)
                if tool["_meta"]["conflu"]["command"][1] in WRITE_FILES:
                    self.assertIn("Does not change Confluence", tool["description"])
                    self.assertNotIn("Changes Confluence", tool["description"])
                else:
                    self.assertIn("Changes Confluence", tool["description"])
        self.assertEqual(len(tools("all")), len(tools("read")) + len(tools("write")))

    def test_a_write_tool_says_exactly_how_far_it_goes(self):
        by_name = {tool["name"]: tool["annotations"] for tool in tools("write")}
        for name in ("update", "move", "label", "import_md", "import_md_dir", "comment"):
            self.assertTrue(by_name["conflu_" + name]["destructiveHint"], name)  # it replaces, moves or removes
        for name in ("create", "attach"):
            self.assertFalse(by_name["conflu_" + name]["destructiveHint"], name)  # it only adds
        for name in ("move", "label", "import_md", "import_md_dir"):
            self.assertTrue(by_name["conflu_" + name]["idempotentHint"], name)  # the same call again changes nothing more
        for name in ("update", "create", "comment", "attach"):
            self.assertFalse(by_name["conflu_" + name]["idempotentHint"], name)

    def test_every_command_that_changes_confluence_is_classified(self):
        by_name = {command.name: command for command in all_commands()}
        for name in DESTRUCTIVE:
            self.assertTrue(by_name[name].writes and by_name[name].destructive, name)
        for name in ADDITIVE:
            self.assertTrue(by_name[name].writes and not by_name[name].destructive, name)
        for command in all_commands():
            with self.subTest(command=command.name):
                if command.idempotent or command.destructive:
                    self.assertTrue(command.writes, "only a command that changes Confluence is destructive or idempotent")
                if command.local or command.for_person:
                    self.assertFalse(command.destructive or command.idempotent)
                if command.local:
                    self.assertFalse(command.writes, "a command that never asks Confluence changes nothing in it")
        self.assertEqual({name for name, command in by_name.items() if command.local} & FOR_THE_PERSON, set())

    def test_a_tool_says_whether_it_talks_to_confluence(self):
        by_name = {tool["name"]: tool for tool in tools()}
        self.assertFalse(by_name["conflu_convert"]["annotations"]["openWorldHint"])
        self.assertTrue(by_name["conflu_search"]["annotations"]["openWorldHint"])

    def test_the_whole_answer_names_its_version_its_set_and_how_to_run_a_tool(self):
        answer = mcp_tools(all_commands(), __version__, only="write")
        meta = answer["_meta"]["conflu"]
        self.assertEqual((meta["version"], meta["only"]), (__version__, "write"))
        self.assertIn("conflu NAME", meta["invoke"])
        self.assertIn("non-zero exit code", meta["invoke"])
        self.assertIn("item by item", meta["invoke"])  # how the files of `attach` become arguments
        self.assertEqual([item["code"] for item in meta["exitCodes"]][:2], [0, 1])
        with self.assertRaises(ValueError):
            mcp_tools(all_commands(), __version__, only="some")


class FileToolsTest(unittest.TestCase):
    """`export` and `download` change nothing in Confluence and write files on this computer: they are not read-only, and not of the default set."""

    def test_the_commands_that_write_files_are_those_that_say_so(self):
        self.assertEqual({command.name for command in all_commands() if command.writes_files}, WRITE_FILES)
        for command in all_commands():
            if command.writes_files:
                self.assertFalse(command.writes or command.for_person or command.local, command.name)

    def test_they_are_in_the_write_set_and_the_all_set_and_not_in_the_read_set(self):
        read, write, everything = ({tool["name"] for tool in tools(only)} for only in ("read", "write", "all"))
        for name in WRITE_FILES:
            tool = "conflu_" + name
            self.assertNotIn(tool, read)
            self.assertIn(tool, write)
            self.assertIn(tool, everything)
        self.assertEqual(everything, read | write)
        self.assertTrue(read.isdisjoint(write))

    def test_their_annotations_say_that_they_are_not_read_only_and_can_replace_a_file(self):
        by_name = {tool["name"]: tool["annotations"] for tool in tools("write")}
        for name in WRITE_FILES:
            with self.subTest(tool=name):
                self.assertEqual(
                    by_name["conflu_" + name],
                    {"title": by_name["conflu_" + name]["title"], "readOnlyHint": False, "openWorldHint": True, "destructiveHint": True, "idempotentHint": True},
                )

    def test_the_catalogue_says_what_a_shell_can_do_and_the_server_says_what_it_does(self):
        shell = {tool["name"]: tool for tool in mcp_tools(all_commands(), __version__, only="write")["tools"]}
        served = {tool["name"]: tool for tool in select_tools(all_commands(), allow_write=True, allow_files=True).tools}
        for name in WRITE_FILES:
            tool = "conflu_" + name
            self.assertIn("ask before you use it on a folder that holds work", shell[tool]["description"])
            self.assertNotIn("Refused over MCP", json.dumps(shell[tool]))
            self.assertIn("never replaces one", served[tool]["description"])
            self.assertTrue(served[tool]["inputSchema"]["properties"]["force"]["description"].startswith("Refused over MCP"))
            self.assertEqual(
                {key: value for key, value in served[tool]["annotations"].items()}, {key: value for key, value in shell[tool]["annotations"].items()}
            )  # the hints are those of the command, in both

    def test_a_property_that_overrides_is_marked_in_the_server_and_not_in_the_catalogue(self):
        shell = mcp_tool(find_command("update"))
        served = {tool["name"]: tool for tool in select_tools(all_commands(), allow_write=True).tools}["conflu_update"]
        self.assertFalse(shell["inputSchema"]["properties"]["force"]["description"].startswith("Refused"))
        self.assertTrue(served["inputSchema"]["properties"]["force"]["description"].startswith("Refused over MCP"))
        self.assertIn("Over MCP `force` is refused", served["description"])
        self.assertNotIn("Over MCP", shell["description"])


class CommandLineTest(unittest.TestCase):
    """The description is only good if a call made from it is a command line that the parser reads as meant."""

    def check(self, tool, arguments):
        command = find_command(tool["_meta"]["conflu"]["command"][1])
        argv = argv_from(tool, arguments)
        namespace = build_parser(command).parse_args(argv[1:])
        names = mcp_property_names(command)
        for arg in command.args:
            wanted = None if arg.text_only else arguments.get(names[arg.names[0]])
            if wanted is None or wanted is False:
                continue
            self.assertEqual(getattr(namespace, arg.dest), wanted, f"{tool['name']}: {arg.names[0]} in {argv}")
        self.assertEqual(bool(getattr(namespace, "json", False)), command.json_output)

    def test_a_call_with_only_what_is_required_becomes_a_command_line(self):
        for tool in tools():
            with self.subTest(tool=tool["name"]):
                properties = tool["inputSchema"]["properties"]
                self.check(tool, {name: sample(properties[name]) for name in tool["inputSchema"]["required"]})

    def test_a_call_with_every_property_becomes_a_command_line(self):
        for tool in tools():
            with self.subTest(tool=tool["name"]):
                self.check(tool, {name: sample(schema) for name, schema in tool["inputSchema"]["properties"].items()})

    def test_the_meta_lists_every_property_once_and_in_the_order_of_the_command(self):
        for tool in tools():
            with self.subTest(tool=tool["name"]):
                listed = [item["property"] for item in tool["_meta"]["conflu"]["arguments"]]
                self.assertEqual(listed, list(tool["inputSchema"]["properties"]))
                for item in tool["_meta"]["conflu"]["arguments"]:
                    self.assertEqual(item["flag"] is None, item["positional"])
                    self.assertEqual(item["type"], tool["inputSchema"]["properties"][item["property"]]["type"])

    def test_a_search_from_a_call_is_what_a_person_would_type(self):
        search = {t["name"]: t for t in tools()}["conflu_search"]
        argv = argv_from(search, {"text": "SSO group", "space": "ENG", "snippets": 5, "match": "any", "label": "adr"})
        self.assertEqual(argv, ["search", "SSO group", "--space", "ENG", "--label", "adr", "--match", "any", "--snippets", "5", "--json"])

    def test_a_list_option_is_repeated_and_a_false_flag_is_left_out(self):
        attach = {t["name"]: t for t in tools()}["conflu_attach"]
        argv = argv_from(attach, {"page": "123", "file": ["a.png", "b.pdf"], "minor": False, "dryRun": True})
        self.assertEqual(argv, ["attach", "123", "a.png", "b.pdf", "--dry-run", "--json"])


class TextsTest(unittest.TestCase):
    def test_a_text_names_the_properties_and_tools_a_reader_of_the_description_has(self):
        for tool in tools():
            text = tool["description"] + " ".join(prop["description"] for prop in tool["inputSchema"]["properties"].values())
            with self.subTest(tool=tool["name"]):
                for item in tool["_meta"]["conflu"]["arguments"]:
                    if item["flag"]:
                        self.assertIsNone(re.search(r"(?<![\w-])" + re.escape(item["flag"]) + r"(?![\w-])", text), f"{item['flag']} is a command line flag, here it is `{item['property']}`")
        offered = {tool["name"] for tool in tools()}
        for tool in tools():
            for mention in re.findall(r"`(conflu_[a-z_]+)`", tool["description"]):
                self.assertIn(mention, offered, f"{tool['name']} names {mention}")

    def test_the_search_tool_tells_when_to_use_it_and_what_comes_back(self):
        description = {t["name"]: t for t in tools()}["conflu_search"]["description"]
        for phrase in ("When to use: Use first", "`snippets`", "Returns JSON:", "path", "relaxed", "`conflu_page`"):
            self.assertIn(phrase, description)

    def test_every_tool_command_says_when_to_use_it_in_the_help_and_the_catalog(self):
        entries = {entry["name"]: entry for entry in catalog(all_commands(), __version__)["commands"]}
        for command in all_commands():
            if command.for_person and command.name not in FOR_THE_PERSON:
                continue
            with self.subTest(command=command.name):
                self.assertTrue(command.when, "write one sentence: when to use it, and when another command is better")
                self.assertEqual(entries[command.name]["whenToUse"], command.when)
                self.assertIn("When to use:", render_command_help(command))


class CommandsCommandTest(unittest.TestCase):
    def test_the_default_is_the_read_only_set_as_json(self):
        result = run_cli("commands", "--format", "mcp")
        self.assertEqual(result.code, 0, result.err)
        answer = json.loads(result.out)
        names = [tool["name"] for tool in answer["tools"]]
        self.assertIn("conflu_search", names)
        self.assertNotIn("conflu_update", names)
        self.assertEqual(answer["_meta"]["conflu"]["only"], "read")

    def test_only_write_and_only_all(self):
        write = json.loads(run_cli("commands", "--format", "mcp", "--only", "write").out)["tools"]
        everything = json.loads(run_cli("commands", "--format", "mcp", "--only", "all").out)["tools"]
        self.assertEqual({tool["name"] for tool in write} & {"conflu_update", "conflu_create", "conflu_import_md_dir"}, {"conflu_update", "conflu_create", "conflu_import_md_dir"})
        self.assertNotIn("conflu_search", [tool["name"] for tool in write])
        self.assertEqual(len(everything), len(json.loads(run_cli("commands", "--format", "mcp").out)["tools"]) + len(write))

    def test_json_format_is_the_catalog_and_the_table_stays_the_default(self):
        catalog_by_flag = json.loads(run_cli("commands", "--json").out)
        self.assertEqual(json.loads(run_cli("commands", "--format", "json").out), catalog_by_flag)
        self.assertIn("whenToUse", catalog_by_flag["commands"][0])
        self.assertEqual(run_cli("commands").out.splitlines()[0].split(), ["COMMAND", "GROUP", "SUMMARY"])

    def test_a_wrong_format_or_set_is_a_usage_error(self):
        self.assertEqual(run_cli("commands", "--format", "xml").code, 2)
        self.assertEqual(run_cli("commands", "--format", "mcp", "--only", "some").code, 2)

    def test_the_write_set_of_the_command_lists_the_file_tools_and_the_read_set_does_not(self):
        read = {tool["name"] for tool in json.loads(run_cli("commands", "--format", "mcp").out)["tools"]}
        write = {tool["name"] for tool in json.loads(run_cli("commands", "--format", "mcp", "--only", "write").out)["tools"]}
        self.assertTrue(read.isdisjoint({"conflu_export", "conflu_download"}))
        self.assertTrue({"conflu_export", "conflu_download", "conflu_update"} <= write)

    def test_a_group_keeps_the_tools_of_that_group_and_their_text_is_the_one_of_the_whole_set(self):
        whole = {tool["name"]: tool for tool in json.loads(run_cli("commands", "--format", "mcp", "--only", "all").out)["tools"]}
        part = json.loads(run_cli("commands", "--format", "mcp", "--only", "all", "--group", "spaces", "--group", "Tools").out)
        wanted = {command.name for command in all_commands() if command.group in ("Spaces", "Tools") and not command.for_person and not command.streams}
        self.assertEqual({tool["_meta"]["conflu"]["command"][1] for tool in part["tools"]}, wanted)
        for tool in part["tools"]:
            self.assertEqual(tool, whole[tool["name"]])  # a group keeps a part of the set and changes no text
        self.assertEqual(part["_meta"]["conflu"]["groups"], ["Spaces", "Tools"])
        self.assertNotIn("groups", json.loads(run_cli("commands", "--format", "mcp").out)["_meta"]["conflu"])  # the default answer keeps its shape

    def test_a_group_makes_the_answer_smaller(self):
        everything = run_cli("commands", "--format", "mcp", "--only", "all").out
        one = run_cli("commands", "--format", "mcp", "--only", "all", "--group", "Spaces").out
        self.assertLess(len(one), len(everything) / 4)

    def test_an_unknown_group_or_a_group_without_the_format_is_a_usage_error_that_says_what_to_do(self):
        unknown = run_cli("commands", "--format", "mcp", "--group", "Nope")
        self.assertEqual((unknown.code, unknown.out), (2, ""))
        self.assertIn("Unknown group: 'Nope'", unknown.err)
        self.assertIn("The groups are: Read, ", unknown.err)
        without = run_cli("commands", "--group", "Read")
        self.assertEqual(without.code, 2)
        self.assertIn("--group is for --format mcp", without.err)

    def test_the_groups_of_the_listing_are_the_groups_of_the_help_that_hold_a_tool(self):
        groups = tool_groups(all_commands())
        self.assertEqual(groups[0], "Read")
        self.assertEqual(len(groups), len(set(groups)))
        for group in groups:
            self.assertTrue(any(command.group == group and not command.for_person and not command.streams for command in all_commands()), group)

    def test_the_help_of_a_command_says_when_to_use_it(self):
        self.assertIn("When to use: Use first when you do not know where information is.", run_cli("help", "search").out.replace("\n", " ").replace("  ", " "))


if __name__ == "__main__":
    unittest.main()
