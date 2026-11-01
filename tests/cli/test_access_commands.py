"""The commands of the access area on the command line, with the in-memory Confluence: what they print, what they refuse, how they are described."""
import json
import re
import unittest

from conflu_c_cli.adapters.driving.cli.help import mcp_property_names, mcp_tool, mcp_tools
from conflu_c_cli.adapters.driving.cli.registry import all_commands, find_command
from conflu_c_cli.domain.access import RestrictionState, SpaceRole
from conflu_c_cli.domain.model import Space
from conflu_c_cli.version import __version__
from tests.support import data_access as data
from tests.support.cli import run_cli
from tests.support.fakes import FakeGateway, default_settings

COMMANDS = ("permissions", "restrictions", "space-access")
READS = {  # what these commands may ask: reads, and nothing that changes Confluence
    "content_types", "get_space", "list_operations", "get_restriction_state", "list_content_permissions", "get_space_role_mode", "list_space_permissions",
    "list_space_role_assignments", "list_space_roles",
}
PEOPLE = (data.ACCOUNT, data.SECOND, data.GROUP, data.GROUP_TWO, "authenticated-users", "alex@example.com", "Alex Example")
WITHOUT_PEOPLE = (
    ("permissions", "2002"),
    ("permissions", "2003", "--only", "update,delete"),
    ("permissions", "--space", "ENG"),
    ("permissions", "7501", "--json"),
    ("restrictions", "2002"),
    ("restrictions", "2002", "--json"),
    ("restrictions", "7501"),
    ("restrictions", "2003", "--json"),
    ("restrictions", "2001"),
    ("space-access", "ENG"),
    ("space-access", "ENG", "--json"),
    ("space-access", "DOCS"),
)


def fresh():
    return FakeGateway()


class DescriptionTest(unittest.TestCase):
    def test_the_commands_are_in_the_access_and_people_group_and_say_what_they_do(self):
        for name in COMMANDS:
            command = find_command(name)
            with self.subTest(command=name):
                self.assertEqual(command.group, "Access and people")
                self.assertTrue(command.when and command.output and command.json_output and command.examples and command.notes)
                self.assertTrue(command.summary and not command.summary.endswith("."))

    def test_they_only_read_and_a_model_may_be_offered_them(self):
        for name in COMMANDS:
            command = find_command(name)
            with self.subTest(command=name):
                self.assertFalse(command.writes or command.destructive or command.idempotent or command.for_person or command.local or command.writes_files)
                self.assertFalse(any("--dry-run" in arg.names for arg in command.args))  # there is nothing to preview
        offered = {tool["name"]: tool for tool in mcp_tools(all_commands(), __version__, only="read")["tools"]}
        written = {tool["name"] for tool in mcp_tools(all_commands(), __version__, only="write")["tools"]}
        for name in COMMANDS:
            tool = offered["conflu_" + name.replace("-", "_")]
            self.assertTrue(tool["annotations"]["readOnlyHint"] and tool["annotations"]["openWorldHint"])
            self.assertNotIn(tool["name"], written)

    def test_no_command_of_the_area_changes_who_may_see_content(self):
        names = {command.name for command in all_commands()}
        self.assertEqual({"permissions", "restrictions", "space-access"} & names, set(COMMANDS))
        self.assertEqual({name for name in names if name.startswith(("restrict", "grant", "revoke", "share"))}, {"restrictions"})
        for name in COMMANDS:
            self.assertTrue(any("web interface" in note for note in find_command(name).notes), name)  # where who may see content is changed

    def test_an_argument_that_says_folder_is_not_a_path_of_this_computer(self):
        for name in COMMANDS:
            for arg in find_command(name).args:
                text = " ".join([*arg.names, arg.metavar, arg.help]).lower()
                with self.subTest(command=name, arg=arg.names[0]):
                    says = any(word in text for word in ("folder", "file", "path", "directory"))
                    self.assertTrue(not says or arg.not_a_path or arg.path or arg.at_file, f"{arg.names[0]} of {name} speaks of a folder, a file or a path and says it is none")
        for name in ("permissions", "restrictions"):
            self.assertTrue(find_command(name).args[0].not_a_path, name)

    def test_the_property_names_of_a_tool_are_distinct_and_the_texts_name_no_flag_of_their_own(self):
        for name in COMMANDS:
            command = find_command(name)
            names = mcp_property_names(command)
            self.assertEqual(len(names), len(set(names.values())), name)
            tool = mcp_tool(command)
            text = tool["description"] + " ".join(prop["description"] for prop in tool["inputSchema"]["properties"].values())
            for arg in command.args:
                if not arg.positional and not arg.text_only:
                    self.assertNotIn(f" {arg.names[0]} ", text + " ", f"{name}: {arg.names[0]} is written as a flag in the text of the tool")
        self.assertIn("withUsers", mcp_property_names(find_command("restrictions")).values())
        self.assertNotIn("format", mcp_property_names(find_command("restrictions")).values())  # the format of a list is for a person

    def test_the_catalog_lists_them_with_their_options(self):
        catalog = {item["name"]: item for item in run_cli("commands", "--json").json()["commands"]}
        self.assertEqual([arg["names"][0] for arg in catalog["permissions"]["arguments"]], ["ref", "--space", "--only"])
        self.assertEqual([arg["names"][0] for arg in catalog["restrictions"]["arguments"]], ["ref", "--with-users", "--limit", "--cursor", "--all", "--select", "--format"])
        self.assertEqual([arg["names"][0] for arg in catalog["space-access"]["arguments"]], ["space", "--with-users", "--limit", "--cursor", "--all", "--select", "--format"])
        for name in COMMANDS:
            self.assertFalse(catalog[name]["changesData"], name)
        self.assertEqual({command.name for command in all_commands() if command.group == "Access and people"} & set(COMMANDS), set(COMMANDS))

    def test_the_help_says_where_people_come_in(self):
        for name in ("restrictions", "space-access"):
            help_text = " ".join(run_cli("help", name).out.split())
            self.assertIn("--with-users", help_text)
            self.assertIn("CONFLUENCE_HIDE_USERS=true", help_text)
            self.assertIn("web interface", help_text)


class PermissionsTest(unittest.TestCase):
    def test_what_this_account_may_do_with_a_page(self):
        result = run_cli("permissions", "2002", gateway=fresh())
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(
            result.out.splitlines(),
            [
                "What this account may do with the page [2002]:",
                "OPERATION         ALLOWED  ON",
                "read              yes      page",
                "update            yes      page",
                "delete            yes      page",
                "archive           yes      page",
                "copy              yes      page",
                "create            yes      attachment, comment",
                "restrict_content  yes      page",
            ],
        )
        self.assertEqual(result.err, "")

    def test_only_says_yes_or_no_for_each_name_in_the_order_given(self):
        result = run_cli("permissions", "2003", "--only", "update,delete,read", gateway=fresh())
        self.assertEqual(
            result.out.splitlines(),
            ["What this account may do with the page [2003]:", "OPERATION  ALLOWED  ON", "update     no", "delete     no", "read       yes      page"],
        )

    def test_what_this_account_may_do_in_a_space(self):
        gateway = fresh()
        text = run_cli("permissions", "--space", "ENG", gateway=gateway).out
        self.assertEqual(text.splitlines()[0], "What this account may do in the space ENG (Engineering):")
        self.assertRegex(text, r"(?m)^read\s+yes\s+space$")
        self.assertRegex(text, r"(?m)^update\s+no$")
        self.assertRegex(text, r"(?m)^create\s+yes\s+attachment, blogpost, comment, page$")
        self.assertEqual(run_cli("permissions", "--space", "ENG", gateway=gateway, settings=default_settings(space="DOCS")).out.splitlines()[0], "What this account may do in the space ENG (Engineering):")  # --space wins over the current space
        current = run_cli("permissions", gateway=gateway, settings=default_settings(space="DOCS"))
        self.assertEqual(current.out.splitlines()[0], "What this account may do in the space DOCS (Documentation):")

    def test_an_address_from_the_browser_names_the_content_as_well(self):
        result = run_cli("permissions", "https://example.atlassian.net/wiki/spaces/ENG/pages/2002/Release+notes", "--only", "update", gateway=fresh())
        self.assertEqual(result.out.splitlines()[0], "What this account may do with the page [2002]:")

    def test_the_kind_of_content_is_named_in_the_sentence(self):
        gateway = fresh()
        gateway.content_kinds.update({"4001": "footer-comment", "4003": "inline-comment"})
        for ref, sentence in (
            ("7501", "the folder [7501]"),
            ("7511", "the blog post [7511]"),
            ("7521", "the whiteboard [7521]"),
            ("7531", "the database [7531]"),
            ("7541", "the smart link [7541]"),
            ("4001", "the footer comment [4001]"),
            ("4003", "the inline comment [4003]"),
            ("att5001", "the attachment [att5001]"),
        ):
            with self.subTest(ref=ref):
                self.assertEqual(run_cli("permissions", ref, gateway=gateway).out.splitlines()[0], f"What this account may do with {sentence}:")

    def test_the_json_for_content_and_for_a_space(self):
        gateway = fresh()
        data_page = run_cli("permissions", "7501", "--json", gateway=gateway).json()
        self.assertEqual(list(data_page), ["target", "operations", "can"])
        self.assertEqual(data_page["target"], {"id": "7501", "type": "folder", "key": None, "title": None})
        self.assertEqual(data_page["operations"][0], {"operation": "delete", "targetType": "folder"})
        self.assertEqual(data_page["can"], {"read": True, "update": True, "delete": True, "restrict_content": True})
        space = run_cli("permissions", "--space", "ENG", "--only", "read,update,create", "--json", gateway=gateway).json()
        self.assertEqual(space["target"], {"id": "1001", "type": "space", "key": "ENG", "title": "Engineering"})
        self.assertEqual(space["can"], {"read": True, "update": False, "create": True})
        self.assertEqual([item["operation"] for item in space["operations"]], ["create", "create", "create", "create", "read"])

    def test_an_operation_that_is_not_allowed_is_false_and_has_no_entry(self):
        data_page = run_cli("permissions", "2003", "--only", "update,delete", "--json", gateway=fresh()).json()
        self.assertEqual((data_page["can"], data_page["operations"]), ({"update": False, "delete": False}, []))

    def test_what_is_wrong_with_the_command_line_is_refused_before_anything_is_asked(self):
        gateway = fresh()
        cases = (
            (("permissions", "2002", "--only", "updat"), 2),
            (("permissions", "2002", "--only", ","), 2),
            (("permissions", "2002", "--space", "ENG"), 2),
            (("permissions",), 2),  # no content, no space, no current space
            (("permissions", "ENG"), 1),
            (("permissions", "abc"), 1),
            (("permissions", "../2002"), 1),
            (("permissions", "--space", "../x"), 1),
            (("permissions", "2002", "--limit", "5"), 2),  # not an option of this command
        )
        for argv, code in cases:
            with self.subTest(argv=argv):
                self.assertEqual(run_cli(*argv, gateway=gateway).code, code)
        self.assertEqual(gateway.calls, [])

    def test_the_hint_for_the_key_of_a_space(self):
        result = run_cli("permissions", "ENG", gateway=fresh())
        self.assertIn("Invalid id: ENG", result.err)
        self.assertIn("If ENG is the key of a space, use --space ENG.", result.err)

    def test_what_does_not_exist_is_not_found(self):
        gateway = fresh()
        for argv in (("permissions", "99999"), ("permissions", "--space", "NOSUCH")):
            with self.subTest(argv=argv):
                self.assertEqual(run_cli(*argv, gateway=gateway).code, 4)
        error = run_cli("permissions", "99999", "--json", gateway=gateway).error()
        self.assertEqual((error["code"], error["exitCode"], error["details"]), ("NOT_FOUND", 4, {"id": "99999"}))

    def test_content_of_a_type_that_the_cli_does_not_ask_about_says_so(self):
        gateway = fresh()
        gateway.content_kinds["7600"] = "ac:example:thing"
        result = run_cli("permissions", "7600", gateway=gateway)
        self.assertEqual(result.code, 1)
        self.assertIn("7600 is content of the type ac:example:thing", result.err)

    def test_the_envelope_wraps_the_answer(self):
        data_page = run_cli("permissions", "2002", "--json-envelope", gateway=fresh()).json()
        self.assertEqual((data_page["ok"], list(data_page["data"])), (True, ["target", "operations", "can"]))


class RestrictionsTest(unittest.TestCase):
    def test_the_state_and_the_counts_without_a_person_in_them(self):
        result = run_cli("restrictions", "2002", gateway=fresh())
        self.assertEqual(result.code, 0, result.err)
        lines = result.out.splitlines()
        self.assertEqual(
            lines[:9],
            [
                "The page [2002] is VIEW_RESTRICTED.",
                "Viewing and editing are restricted to the users and groups that are granted it.",
                "Set on 2026-10-03T09:00:00.000Z.",
                "",
                "5 direct permissions:",
                "OPERATION  USERS  GROUPS",
                "read       2      1",
                "update     1      1",
                "",
            ],
        )
        self.assertEqual(lines[9], "Only what is set on the content itself is shown: a restriction that a parent page or folder sets is not in these calls, so OPEN does not mean that everybody may read it.")
        self.assertIn("Who holds these is not shown. --with-users lists the users and groups", result.err)

    def test_open_content_says_so_and_has_nothing_to_hide(self):
        result = run_cli("restrictions", "2001", gateway=fresh())
        lines = result.out.splitlines()
        self.assertEqual(lines[:4], ["The page [2001] is OPEN.", "No direct restriction on it. A parent may still restrict who can see or edit it.", "", "No direct permissions."])
        self.assertEqual(result.err, "")  # nobody holds anything, so there is nobody to ask for
        with_users = run_cli("restrictions", "2001", "--with-users", gateway=fresh())
        self.assertEqual(with_users.out, result.out)  # an empty list is not announced twice
        self.assertEqual(with_users.err, "")

    def test_a_piece_beyond_the_end_of_the_list_says_that_it_is_empty(self):
        result = run_cli("restrictions", "2002", "--with-users", "--cursor", "99", gateway=fresh())
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("(none in this piece of the list)", result.out)
        self.assertEqual(result.err, "")
        self.assertEqual(run_cli("restrictions", "2002", "--with-users", "--cursor", "99", "--json", gateway=fresh()).json()["permissions"], [])

    def test_with_people_the_principals_and_who_set_the_restriction_are_listed(self):
        result = run_cli("restrictions", "2002", "--with-users", gateway=fresh())
        self.assertEqual(result.code, 0, result.err)
        lines = result.out.splitlines()
        self.assertEqual(lines[2], f"Set on 2026-10-03T09:00:00.000Z by {data.ACCOUNT}.")
        self.assertEqual(
            lines[9:15],
            [
                "OPERATION  TYPE   PRINCIPAL",
                f"read       group  {data.GROUP}",
                f"read       user   {data.ACCOUNT}",
                f"read       user   {data.SECOND}",
                f"update     group  {data.GROUP}",
                f"update     user   {data.ACCOUNT}",
            ],
        )
        self.assertEqual(result.err, "")

    def test_a_piece_of_the_list_says_how_to_go_on(self):
        gateway = fresh()
        first = run_cli("restrictions", "2002", "--with-users", "--limit", "2", gateway=gateway)
        self.assertIn(f"read       user   {data.ACCOUNT}", first.out)
        self.assertNotIn(data.SECOND, first.out)
        self.assertIn("More principals follow. Continue with --cursor 2, or use --all.", first.err)
        second = run_cli("restrictions", "2002", "--with-users", "--limit", "2", "--cursor", "2", gateway=gateway)
        self.assertIn(data.SECOND, second.out)
        self.assertIn("--cursor 4", second.err)
        last = run_cli("restrictions", "2002", "--with-users", "--limit", "2", "--cursor", "4", gateway=gateway)
        self.assertEqual(last.err, "")
        everything = run_cli("restrictions", "2002", "--with-users", "--limit", "1", "--all", gateway=gateway)
        self.assertEqual(everything.err, "")
        self.assertEqual(len(re.findall(r"(?m)^(?:read|update)\s+(?:user|group)\s+\S+$", everything.out)), 5)  # --all ignores --limit

    def test_the_json_without_people(self):
        result = run_cli("restrictions", "2002", "--json", gateway=fresh())
        data_json = result.json()
        self.assertEqual(result.err, "")
        self.assertEqual(
            list(data_json),
            ["target", "state", "meaning", "createdAt", "createdBy", "counts", "total", "usersShown", "count", "nextCursor", "truncated", "permissions", "notes"],
        )
        self.assertEqual(data_json["target"], {"id": "2002", "type": "page", "key": None, "title": None})
        self.assertEqual((data_json["state"], data_json["createdAt"], data_json["createdBy"]), ("VIEW_RESTRICTED", "2026-10-03T09:00:00.000Z", None))
        self.assertEqual(data_json["counts"], {"read": {"user": 2, "group": 1}, "update": {"user": 1, "group": 1}})
        self.assertEqual((data_json["total"], data_json["usersShown"], data_json["count"], data_json["nextCursor"], data_json["truncated"], data_json["permissions"]), (5, False, None, None, False, None))
        self.assertEqual(len(data_json["notes"]), 1)
        self.assertIn("a parent page or folder sets", data_json["notes"][0])

    def test_the_json_with_people(self):
        data_json = run_cli("restrictions", "2002", "--with-users", "--limit", "2", "--json", gateway=fresh()).json()
        self.assertEqual((data_json["createdBy"], data_json["usersShown"], data_json["count"], data_json["nextCursor"]), (data.ACCOUNT, True, 2, "2"))
        self.assertEqual(
            data_json["permissions"][0],
            {"operation": "read", "principalType": "group", "principalId": data.GROUP, "createdAt": "2026-10-03T09:00:00.000Z", "createdBy": data.ACCOUNT},
        )
        picked = run_cli("restrictions", "2002", "--with-users", "--all", "--select", "operation,principalId", "--json", gateway=fresh()).json()
        self.assertEqual(picked["permissions"][1], {"operation": "read", "principalId": data.ACCOUNT})
        self.assertEqual(picked["total"], 5)  # the rest of the document stays

    def test_the_principals_as_rows_for_a_script(self):
        gateway = fresh()
        tsv = run_cli("restrictions", "2002", "--with-users", "--all", "--select", "operation,principalType", "--format", "tsv", gateway=gateway)
        self.assertEqual(tsv.out.splitlines(), ["operation\tprincipalType", "read\tgroup", "read\tuser", "read\tuser", "update\tgroup", "update\tuser"])
        self.assertIn("a parent page or folder sets", tsv.err)  # the note is for a person: not among the rows
        md = run_cli("restrictions", "2002", "--with-users", "--limit", "1", "--format", "md", gateway=gateway)
        self.assertEqual(md.out.splitlines()[:3], ["| OPERATION | TYPE | PRINCIPAL |", "| --- | --- | --- |", f"| read | group | {data.GROUP} |"])
        unknown = run_cli("restrictions", "2002", "--with-users", "--select", "nope", gateway=gateway)
        self.assertEqual(unknown.code, 2)
        self.assertIn("Valid names: createdAt, createdBy, operation, principalId, principalType", unknown.err)
        self.assertEqual(run_cli("restrictions", "2002", "--with-users", "--json", "--format", "tsv", gateway=gateway).code, 2)

    def test_what_shapes_the_list_of_principals_needs_the_principals(self):
        gateway = fresh()
        for argv in (("--limit", "5"), ("--cursor", "1"), ("--all",), ("--select", "operation"), ("--format", "tsv"), ("--format", "md")):
            with self.subTest(argv=argv):
                result = run_cli("restrictions", "2002", *argv, gateway=gateway)
                self.assertEqual(result.code, 2)
                self.assertIn("is shown only with --with-users", result.err)
        self.assertEqual(gateway.calls, [])

    def test_the_policy_refuses_people_and_leaves_the_counts(self):
        gateway = fresh()
        policy = default_settings(hide_users=True)
        refused = run_cli("restrictions", "2002", "--with-users", gateway=gateway, settings=policy)
        self.assertEqual((refused.code, refused.out), (1, ""))
        self.assertIn("CONFLUENCE_HIDE_USERS=true", refused.err)
        self.assertEqual(gateway.calls, [])
        counts = run_cli("restrictions", "2002", "--json", gateway=gateway, settings=policy)
        self.assertEqual(counts.code, 0, counts.err)
        self.assertEqual(counts.json()["total"], 5)
        self.assertNotIn(data.ACCOUNT, counts.out)

    def test_content_that_has_no_restriction_of_its_own_is_said_to_have_none(self):
        gateway = fresh()
        gateway.content_kinds["4001"] = "footer-comment"
        for ref, message in (
            ("7541", "7541 is a smart link, which has no restrictions of its own."),
            ("4001", "4001 is a footer comment, which has no restrictions of its own."),
            ("att5001", "att5001 is an attachment, which has no restrictions of its own."),
        ):
            with self.subTest(ref=ref):
                result = run_cli("restrictions", ref, gateway=gateway)
                self.assertEqual(result.code, 1)
                self.assertIn(message, result.err)
                self.assertIn("follows the content it belongs to", result.err)

    def test_every_kind_that_has_a_state_is_read_in_its_own_collection(self):
        gateway = fresh()
        for ref, sentence in (("7501", "The folder [7501] is VIEW_RESTRICTED."), ("7511", "The blog post [7511] is OPEN."), ("7521", "The whiteboard [7521] is OPEN."), ("7531", "The database [7531] is OPEN.")):
            with self.subTest(ref=ref):
                self.assertEqual(run_cli("restrictions", ref, gateway=gateway).out.splitlines()[0], sentence)

    def test_what_is_wrong_with_the_command_line_is_refused_before_anything_is_asked(self):
        gateway = fresh()
        cases = (
            (("restrictions",), 2),
            (("restrictions", "abc"), 1),
            (("restrictions", "../2002"), 1),
            (("restrictions", "ENG"), 1),
            (("restrictions", "2002", "--with-users", "--limit", "0"), 2),
            (("restrictions", "2002", "--with-users", "--limit", "251"), 2),
            (("restrictions", "2002", "--with-users", "--limit", "x"), 2),
            (("restrictions", "2002", "--with-users", "--cursor", "abc"), 2),
            (("restrictions", "2002", "--with-users", "--cursor", "-1"), 2),
            (("restrictions", "2002", "--space", "ENG"), 2),
        )
        for argv, code in cases:
            with self.subTest(argv=argv):
                self.assertEqual(run_cli(*argv, gateway=gateway).code, code)
        self.assertEqual(gateway.calls, [])

    def test_what_does_not_exist_is_not_found(self):
        self.assertEqual(run_cli("restrictions", "99999", gateway=fresh()).code, 4)

    def test_the_restriction_state_that_confluence_does_not_return_is_shown_as_it_is(self):
        gateway = fresh()
        gateway.restriction_states["2005"] = RestrictionState("SOMETHING_NEW")
        text = run_cli("restrictions", "2005", gateway=gateway).out.splitlines()
        self.assertEqual((text[0], text[1]), ("The page [2005] is SOMETHING_NEW.", ""))  # no sentence is made up for a state that the CLI does not know
        self.assertIsNone(run_cli("restrictions", "2005", "--json", gateway=gateway).json()["meaning"])
        gateway.restriction_states["2005"] = RestrictionState("")  # an answer that names no state at all
        self.assertEqual(run_cli("restrictions", "2005", gateway=gateway).out.splitlines()[0], "Confluence names no restriction state for the page [2005].")


class SpaceAccessTest(unittest.TestCase):
    def test_how_many_users_groups_and_roles_hold_what(self):
        result = run_cli("space-access", "ENG", gateway=fresh())
        self.assertEqual(result.code, 0, result.err)
        lines = result.out.splitlines()
        self.assertEqual(lines[:2], ["Access to the space ENG (Engineering)", "Role mode: ROLES_TRANSITION"])
        self.assertIn("7 permission assignments:", lines)
        self.assertIn("OPERATION   ON       USERS  GROUPS  ROLES", lines)
        self.assertIn("read        space    2      1       0", lines)
        self.assertIn("5 role assignments:", lines)
        self.assertIn("ROLE         TYPE    USERS  GROUPS  ACCESS CLASSES", lines)
        self.assertIn("Viewer       SYSTEM  1      1       1", lines)
        self.assertIn("The site is moving from permissions to roles (ROLES_TRANSITION): both are shown.", lines)
        self.assertIn("Who holds these is not shown. --with-users lists the users and groups", result.err)

    def test_with_people_who_holds_what_is_listed(self):
        result = run_cli("space-access", "ENG", "--with-users", "--all", gateway=fresh())
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(result.err, "")
        lines = result.out.splitlines()
        start = lines.index("MODEL        TYPE          PRINCIPAL                             GRANTED")
        self.assertEqual(lines[start + 1], f"permissions  user          {data.ACCOUNT}              administer space")
        self.assertRegex(result.out, rf"(?m)^roles\s+group\s+{data.GROUP}\s+Contributor$")
        self.assertRegex(result.out, r"(?m)^roles\s+access_class\s+authenticated-users\s+Viewer$")

    def test_a_piece_of_the_list_says_how_to_go_on(self):
        gateway = fresh()
        result = run_cli("space-access", "ENG", "--with-users", "--limit", "5", gateway=gateway)
        self.assertIn("More principals follow. Continue with --cursor 5, or use --all.", result.err)
        self.assertNotIn("authenticated-users", result.out)
        middle = run_cli("space-access", "ENG", "--with-users", "--limit", "5", "--cursor", "5", gateway=gateway)
        self.assertIn("authenticated-users", middle.out)
        self.assertIn("--cursor 10", middle.err)
        last = run_cli("space-access", "ENG", "--with-users", "--limit", "5", "--cursor", "10", gateway=gateway)
        self.assertEqual(last.err, "")
        self.assertIn(data.GROUP_TWO, last.out)

    def test_the_json_without_people(self):
        result = run_cli("space-access", "ENG", "--json", gateway=fresh())
        data_json = result.json()
        self.assertEqual(result.err, "")
        self.assertEqual(
            list(data_json),
            ["target", "mode", "models", "permissionTotal", "permissionCounts", "roleTotal", "roleCounts", "usersShown", "total", "count", "nextCursor", "truncated", "principals", "notes"],
        )
        self.assertEqual(data_json["target"], {"id": "1001", "type": "space", "key": "ENG", "title": "Engineering"})
        self.assertEqual((data_json["mode"], data_json["models"], data_json["permissionTotal"], data_json["roleTotal"], data_json["total"]), ("ROLES_TRANSITION", ["permissions", "roles"], 7, 5, 12))
        self.assertEqual(data_json["permissionCounts"][0], {"operation": "administer", "targetType": "space", "user": 1, "group": 0, "role": 0})
        self.assertEqual(data_json["roleCounts"][2], {"roleId": data.ROLE_VIEWER, "name": "Viewer", "type": "SYSTEM", "user": 1, "group": 1, "accessClass": 1})
        self.assertEqual((data_json["usersShown"], data_json["count"], data_json["nextCursor"], data_json["truncated"], data_json["principals"]), (False, None, None, False, None))
        self.assertEqual(len(data_json["notes"]), 1)

    def test_the_json_with_people(self):
        data_json = run_cli("space-access", "ENG", "--with-users", "--limit", "3", "--json", gateway=fresh()).json()
        self.assertEqual((data_json["usersShown"], data_json["count"], data_json["nextCursor"]), (True, 3, "3"))
        self.assertEqual(
            data_json["principals"][0],
            {"model": "permissions", "principalType": "user", "principalId": data.ACCOUNT, "operation": "administer", "targetType": "space", "roleId": None, "roleName": None},
        )
        roles = run_cli("space-access", "ENG", "--with-users", "--all", "--json", gateway=fresh()).json()["principals"]
        self.assertEqual(roles[-1], {"model": "roles", "principalType": "user", "principalId": data.SECOND, "operation": None, "targetType": None, "roleId": data.ROLE_VIEWER, "roleName": "Viewer"})

    def test_the_principals_as_rows_for_a_script(self):
        gateway = fresh()
        tsv = run_cli("space-access", "ENG", "--with-users", "--all", "--select", "model,principalType,roleName", "--format", "tsv", gateway=gateway).out.splitlines()
        self.assertEqual(tsv[0], "model\tprincipalType\troleName")
        self.assertEqual(tsv[1], "permissions\tuser\t")
        self.assertEqual(tsv[-1], "roles\tuser\tViewer")
        md = run_cli("space-access", "ENG", "--with-users", "--limit", "1", "--format", "md", gateway=gateway).out.splitlines()
        self.assertEqual(md[0], "| MODEL | TYPE | PRINCIPAL | OPERATION | ON | ROLE |")
        self.assertEqual(run_cli("space-access", "ENG", "--with-users", "--select", "nope", gateway=gateway).code, 2)

    def test_a_site_with_one_model_shows_that_model(self):
        gateway = fresh()
        gateway.role_mode = "PRE_ROLES"
        before = run_cli("space-access", "ENG", "--json", gateway=gateway).json()
        self.assertEqual((before["mode"], before["models"], before["roleCounts"], before["roleTotal"], before["total"]), ("PRE_ROLES", ["permissions"], None, None, 7))
        self.assertEqual(before["notes"], [])
        text = run_cli("space-access", "ENG", gateway=gateway).out
        self.assertNotIn("role assignment", text)
        gateway.role_mode = "ROLES"
        after = run_cli("space-access", "ENG", "--json", gateway=gateway).json()
        self.assertEqual((after["mode"], after["models"], after["permissionCounts"], after["permissionTotal"], after["total"]), ("ROLES", ["roles"], None, None, 5))
        self.assertNotIn("permission assignment", run_cli("space-access", "ENG", gateway=gateway).out)

    def test_a_site_that_reports_no_mode_says_so(self):
        gateway = fresh()
        gateway.role_mode = None  # a site without space roles
        result = run_cli("space-access", "ENG", gateway=gateway)
        self.assertEqual(result.out.splitlines()[1], "Role mode: not reported by this site")
        self.assertIn("7 permission assignments:", result.out)
        self.assertNotIn("role assignments:", result.out)
        data_json = run_cli("space-access", "ENG", "--json", gateway=gateway).json()
        self.assertEqual((data_json["mode"], data_json["models"], data_json["roleCounts"], data_json["roleTotal"]), (None, ["permissions"], None, None))
        self.assertEqual(len(data_json["notes"]), 2)

    def test_a_space_that_nobody_holds_anything_in_and_a_piece_beyond_the_end(self):
        gateway = fresh()
        empty = run_cli("space-access", "DOCS", "--with-users", gateway=gateway)
        self.assertEqual(empty.code, 0, empty.err)
        self.assertIn("0 permission assignments:\n(none)", empty.out)
        self.assertIn("0 role assignments:\n(none)", empty.out)
        self.assertNotIn("(none in this piece of the list)", empty.out)  # there is nothing, and that is said once
        self.assertEqual(empty.err, "")
        beyond = run_cli("space-access", "ENG", "--with-users", "--cursor", "99", gateway=gateway)
        self.assertIn("(none in this piece of the list)", beyond.out)
        self.assertEqual(beyond.err, "")

    def test_the_current_space_is_the_default(self):
        gateway = fresh()
        result = run_cli("space-access", gateway=gateway, settings=default_settings(space="ENG"))
        self.assertEqual(result.out.splitlines()[0], "Access to the space ENG (Engineering)")
        missing = run_cli("space-access", gateway=gateway)
        self.assertEqual(missing.code, 2)
        self.assertIn("conflu use KEY", missing.err)

    def test_a_personal_space_comes_out_without_its_owner_unless_people_are_shown(self):
        gateway = fresh()
        key = f"~{data.ACCOUNT}"
        gateway.spaces[key] = Space("1003", key, "Alex Example", "personal", "current")
        hidden = run_cli("space-access", key, "--json", gateway=gateway)
        self.assertEqual(hidden.json()["target"], {"id": "1003", "type": "space", "key": "[hidden]", "title": "[personal space]"})
        everything = hidden.out + run_cli("space-access", key, gateway=gateway).out + run_cli("permissions", "--space", key, gateway=gateway).out
        self.assertNotIn("Alex Example", everything)
        self.assertNotIn(data.ACCOUNT, everything)
        self.assertEqual(run_cli("space-access", key, gateway=gateway).out.splitlines()[0], "Access to the space [hidden] ([personal space])")
        self.assertEqual(run_cli("permissions", "--space", key, gateway=gateway).out.splitlines()[0], "What this account may do in the space [hidden] ([personal space]):")
        shown = run_cli("space-access", key, "--with-users", "--json", gateway=gateway)
        self.assertEqual(shown.json()["target"], {"id": "1003", "type": "space", "key": key, "title": "Alex Example"})
        gateway.spaces["ENG"] = Space("1001", "ENG", "Team of alex@example.com", "global", "current")
        self.assertEqual(run_cli("space-access", "ENG", "--json", gateway=gateway).json()["target"]["title"], "Team of [email]")

    def test_the_name_of_a_role_cannot_move_the_cursor_or_name_a_person(self):
        gateway = fresh()
        gateway.space_roles[2] = SpaceRole(data.ROLE_VIEWER, "Readers\x1b[2J of alex@example.com", "CUSTOM")
        text = run_cli("space-access", "ENG", gateway=gateway).out
        self.assertNotIn("\x1b", text)
        self.assertNotIn("alex@example.com", text)
        self.assertIn("Readers[2J of [email]", text)
        self.assertNotIn("alex@example.com", run_cli("space-access", "ENG", "--json", gateway=gateway).out)

    def test_what_is_wrong_with_the_command_line_is_refused_before_anything_is_asked(self):
        gateway = fresh()
        cases = (
            (("space-access", "../x"), 1),
            (("space-access", "ENG", "--limit", "5"), 2),
            (("space-access", "ENG", "--with-users", "--limit", "251"), 2),
            (("space-access", "ENG", "--with-users", "--cursor", "x"), 2),
            (("space-access", "ENG", "--format", "tsv"), 2),
            (("space-access", "ENG", "--select", "model"), 2),
            (("space-access", "ENG", "--all"), 2),
            (("space-access", "ENG", "--space", "DOCS"), 2),
        )
        for argv, code in cases:
            with self.subTest(argv=argv):
                self.assertEqual(run_cli(*argv, gateway=gateway).code, code)
        self.assertEqual(gateway.calls, [])
        self.assertEqual(run_cli("space-access", "NOSUCH", gateway=gateway).code, 4)

    def test_the_policy_refuses_people_and_leaves_the_counts(self):
        gateway = fresh()
        policy = default_settings(hide_users=True)
        refused = run_cli("space-access", "ENG", "--with-users", gateway=gateway, settings=policy)
        self.assertEqual((refused.code, refused.out), (1, ""))
        self.assertIn("CONFLUENCE_HIDE_USERS=true", refused.err)
        self.assertEqual(gateway.calls, [])
        self.assertEqual(run_cli("space-access", "ENG", "--json", gateway=gateway, settings=policy).code, 0)


class NoPersonByDefaultTest(unittest.TestCase):
    def test_no_account_id_no_group_id_no_name_and_no_address_in_any_answer_without_with_users(self):
        gateway = fresh()
        for argv in WITHOUT_PEOPLE:
            result = run_cli(*argv, gateway=gateway)
            with self.subTest(argv=argv):
                self.assertEqual(result.code, 0, result.err)
                for person in PEOPLE:
                    self.assertNotIn(person, result.out + result.err)

    def test_the_same_holds_under_the_policy_and_it_changes_nothing_else(self):
        gateway = fresh()
        policy = default_settings(hide_users=True)
        for argv in WITHOUT_PEOPLE:
            with self.subTest(argv=argv):
                plain = run_cli(*argv, gateway=gateway)
                hidden = run_cli(*argv, gateway=gateway, settings=policy)
                self.assertEqual((hidden.code, hidden.out), (plain.code, plain.out))

    def test_the_people_are_there_with_with_users_so_the_scan_above_is_not_empty(self):
        gateway = fresh()
        text = run_cli("restrictions", "2002", "--with-users", gateway=gateway).out + run_cli("space-access", "ENG", "--with-users", "--all", gateway=gateway).out
        for person in (data.ACCOUNT, data.SECOND, data.GROUP, data.GROUP_TWO, "authenticated-users"):
            self.assertIn(person, text)

    def test_these_commands_only_read(self):
        gateway = fresh()
        for argv in (*WITHOUT_PEOPLE, ("restrictions", "2002", "--with-users", "--all"), ("space-access", "ENG", "--with-users", "--all")):
            run_cli(*argv, gateway=gateway)
        self.assertLessEqual({call[0] for call in gateway.calls}, READS)
        self.assertGreater(len(gateway.calls), 30)


class AsJsonForAProgramTest(unittest.TestCase):
    def test_the_documents_are_one_line_and_the_keys_are_camel_case(self):
        gateway = fresh()
        for argv in (("permissions", "2002"), ("restrictions", "2002", "--with-users"), ("space-access", "ENG", "--with-users")):
            result = run_cli(*argv, "--json", gateway=gateway)
            with self.subTest(argv=argv):
                self.assertEqual(len(result.out.splitlines()), 1)
                self.assertEqual(result.err, "")

                def keys(value):
                    if isinstance(value, dict):
                        for key, item in value.items():
                            yield key
                            yield from keys(item)
                    elif isinstance(value, list):
                        for item in value:
                            yield from keys(item)

                for key in keys(json.loads(result.out)):
                    if key in {"read", "update", "delete", "archive", "copy", "create", "restrict_content", "user", "group"}:
                        continue  # the names that Confluence gives to an operation or to a kind of principal
                    self.assertRegex(key, r"^[a-z][A-Za-z]*$")


if __name__ == "__main__":
    unittest.main()
