"""The commands of the structure area on the command line, with the in-memory Confluence: what they print, what they refuse, how they are described."""
import json
import unittest

from conflu_c_cli.adapters.driving.cli.registry import all_commands, find_command
from conflu_c_cli.domain.errors import UnavailableError
from conflu_c_cli.domain.model import Space
from tests.support.cli import run_cli
from tests.support.fakes import ACCOUNT, BASE, FakeGateway, MemoryFiles, default_settings, sample_page

NEW_COMMANDS = ("folder", "whiteboard", "database", "smartlink", "folder-create", "smartlink-create")


def fresh():
    gateway = FakeGateway()
    gateway.add_page_below("7001", "7101", "Getting started")
    return gateway


class FailsToReadBack(FakeGateway):
    """A Confluence that cannot be asked for a page once a move has been made."""

    def get_page(self, page_id, *, with_body=True):
        if self.called("move_page"):
            raise UnavailableError("busy")
        return super().get_page(page_id, with_body=with_body)


class DescriptionTest(unittest.TestCase):
    def test_the_commands_are_in_the_structure_group_and_say_what_they_do(self):
        for name in NEW_COMMANDS:
            command = find_command(name)
            with self.subTest(command=name):
                self.assertEqual(command.group, "Structure")
                self.assertTrue(command.when and command.output and command.json_output and command.examples)
        for name in ("tree", "move"):
            self.assertNotEqual(find_command(name).group, "Structure")  # they stay where they were

    def test_the_readers_change_nothing_and_the_writers_only_add(self):
        for name in ("folder", "whiteboard", "database", "smartlink", "tree"):
            self.assertFalse(find_command(name).writes, name)
        for name in ("folder-create", "smartlink-create"):
            command = find_command(name)
            self.assertTrue(command.writes and not command.destructive and not command.idempotent and not command.for_person and not command.local, name)
            self.assertTrue(any("--dry-run" in arg.names for arg in command.args), name)
        move = find_command("move")
        self.assertTrue(move.writes and move.destructive and move.idempotent)  # it moves, and the same call again changes nothing more
        for name in ("create", "import-md", "import-md-dir"):
            self.assertTrue(find_command(name).writes, name)

    def test_an_argument_that_says_folder_is_not_a_path_of_this_computer(self):
        """What `conflu mcp` needs to know: an argument that looks like a path and is none says so. (The arguments of the older commands that
        are paths of this computer, `--file`, `FILE.md` and `DIR`, are declared by the agent of `mcp`.)"""
        mine = {name: None for name in NEW_COMMANDS}
        mine.update({"tree": {"ref"}, "move": {"--to", "--position"}, "create": {"--parent"}, "import-md": {"--parent"}, "import-md-dir": {"--parent"}})
        for name, only in mine.items():
            for arg in find_command(name).args:
                if only is not None and arg.names[0] not in only:
                    continue
                text = " ".join([*arg.names, arg.metavar, arg.help]).lower()
                with self.subTest(command=name, arg=arg.names[0]):
                    says = any(word in text for word in ("folder", "file", "path", "directory"))
                    self.assertTrue(not says or arg.not_a_path or arg.path or arg.at_file, f"{arg.names[0]} of {name} speaks of a folder, a file or a path and says it is none")
        for name in ("create", "import-md", "import-md-dir", "folder-create", "smartlink-create"):
            self.assertTrue(next(arg for arg in find_command(name).args if arg.names[0] == "--parent").not_a_path, name)
        self.assertTrue(next(arg for arg in find_command("move").args if arg.names[0] == "--to").not_a_path)

    def test_the_property_names_of_a_tool_are_distinct_and_the_texts_name_no_flag_of_their_own(self):
        from conflu_c_cli.adapters.driving.cli.help import mcp_property_names, mcp_tool

        for name in NEW_COMMANDS:
            command = find_command(name)
            names = mcp_property_names(command)
            self.assertEqual(len(names), len(set(names.values())), name)
            tool = mcp_tool(command)
            text = tool["description"] + " ".join(prop["description"] for prop in tool["inputSchema"]["properties"].values())
            for arg in command.args:
                if not arg.positional and not arg.text_only:
                    self.assertNotIn(f" {arg.names[0]} ", text + " ", f"{name}: {arg.names[0]} is written as a flag in the text of the tool")

    def test_the_catalog_lists_them_with_their_options(self):
        catalog = run_cli("commands", "--json").json()["commands"]
        database = next(item for item in catalog if item["name"] == "database")
        self.assertEqual([arg["names"][0] for arg in database["arguments"]][:7], ["ref", "--children", "--fields", "--views", "--entries", "--ancestors", "--with-users"])
        self.assertTrue(next(item for item in catalog if item["name"] == "folder-create")["changesData"])
        self.assertIn("parentType", next(item for item in catalog if item["name"] == "create")["jsonOutput"])
        self.assertEqual({command.name for command in all_commands() if command.group == "Structure"}, set(NEW_COMMANDS))


class ReadCommandsTest(unittest.TestCase):
    def test_a_folder(self):
        result = run_cli("folder", "7001", gateway=fresh())
        self.assertEqual(result.code, 0, result.err)
        lines = result.out.splitlines()
        self.assertEqual(lines[0], "Guides  [7001]")
        self.assertEqual(lines[1], f"{BASE}/spaces/ENG/folder/7001")
        self.assertIn("Type:    folder", lines)
        self.assertEqual(lines[-1], "Below it: show what is there with --children.")
        self.assertNotIn(ACCOUNT, result.out)

    def test_a_folder_as_json(self):
        data = run_cli("folder", "7011", "--ancestors", "--children", "--json", gateway=fresh()).json()
        self.assertEqual(
            [key for key in data],
            ["id", "type", "title", "status", "spaceId", "spaceKey", "parentId", "parentType", "position", "url", "version", "created", "updated", "author", "owner",
             "ancestors", "count", "nextCursor", "truncated", "children"],
        )
        self.assertEqual((data["parentId"], data["parentType"], data["position"], data["count"], data["children"]), ("7001", "folder", 0, 0, []))
        self.assertEqual(data["ancestors"], [{"id": "7001", "type": "folder", "title": "Guides"}])
        self.assertEqual(data["version"], {"number": 1, "created": "2026-10-01T08:00:00.000Z", "message": "", "minorEdit": False, "author": None})
        self.assertNotIn(ACCOUNT, json.dumps(data))

    def test_the_children_as_a_table_and_as_flat_rows(self):
        gateway = fresh()
        text = run_cli("folder", "7001", "--children", "--all", gateway=gateway).out
        self.assertIn("ID    TYPE        TITLE                STATUS", text)
        self.assertIn("7021  whiteboard  Architecture sketch  current", text)
        self.assertIn("7101  page        Getting started      current", text)
        tsv = run_cli("folder", "7001", "--children", "--all", "--select", "id,type", "--format", "tsv", gateway=gateway).out
        self.assertEqual(tsv.splitlines()[:3], ["id\ttype", "7021\twhiteboard", "7101\tpage"])
        md = run_cli("folder", "7001", "--children", "--limit", "2", "--format", "md", gateway=gateway).out
        self.assertEqual(md.splitlines()[0], "| ID | TYPE | TITLE | STATUS |")
        data = run_cli("folder", "7001", "--children", "--all", "--select", "id,position", "--json", gateway=gateway).json()
        self.assertEqual(data["children"][0], {"id": "7021", "position": 0})
        self.assertEqual(data["count"], 5)  # the rest of the document stays
        unknown = run_cli("folder", "7001", "--children", "--select", "nope", gateway=gateway)
        self.assertEqual(unknown.code, 2)
        self.assertIn("Valid names: id, position, status, title, type", unknown.err)

    def test_the_notes_for_a_person_stay_out_of_the_json(self):
        gateway = fresh()
        text = run_cli("folder", "7001", "--children", "--limit", "2", gateway=gateway)
        self.assertIn("More children follow. Continue with --cursor 2 (and the same --limit), or use --all.", text.err)
        as_json = run_cli("folder", "7001", "--children", "--limit", "2", "--json", gateway=gateway)
        self.assertEqual(as_json.err, "")
        self.assertEqual(as_json.json()["nextCursor"], "2")

    def test_a_whiteboard_a_database_and_a_smart_link(self):
        gateway = fresh()
        self.assertIn("Content: the REST API has no call that returns what a whiteboard shows", run_cli("whiteboard", "7021", gateway=gateway).out)
        self.assertIn("Below it, its fields, its views and its entries: --children, --fields, --views, --entries (one at a time).", run_cli("database", "7041", gateway=gateway).out)
        smart = run_cli("smartlink", "7061", "--ancestors", gateway=gateway).out
        self.assertIn("Address: https://example.com/roadmap", smart)
        self.assertIn("Path:    Guides > Roadmap", smart)
        self.assertEqual(run_cli("smartlink", "7061", "--json", gateway=gateway).json()["embedUrl"], "https://example.com/roadmap")
        self.assertNotIn("embedUrl", run_cli("folder", "7001", "--json", gateway=gateway).json())

    def test_the_lists_of_a_database(self):
        gateway = fresh()
        fields = run_cli("database", "7041", "--fields", "--all", gateway=gateway).out
        self.assertRegex(fields, r"(?m)^tier\s+Tier\s+select\s+Gold, Silver, Bronze$")
        views = run_cli("database", "7041", "--views", "--json", gateway=gateway).json()["views"]
        self.assertEqual(views, [{"id": "view-all", "name": "All services", "type": "table"}, {"id": "view-tier", "name": "By tier", "type": "board"}])
        entries = run_cli("database", "7041", "--entries", "--all", gateway=gateway).out
        self.assertRegex(entries, r"(?m)^7051\s+Billing\s+Gold\s+\[hidden\]\s+yes\s+Billing docs <https://example\.com/billing>$")
        self.assertIn("Billing docs <https://example.com/billing>", entries)
        self.assertIn("Contact [email]", entries)
        self.assertNotIn("alex@example.com", entries)
        tsv = run_cli("database", "7041", "--entries", "--all", "--format", "tsv", gateway=gateway).out.splitlines()
        self.assertEqual(tsv[0], "ID\tName\tTier\tOwner\tActive\tDocs")
        self.assertEqual(tsv[1].split("\t")[:4], ["7051", "Billing", "Gold", "[hidden]"])
        picked = run_cli("database", "7041", "--entries", "--all", "--select", "id,values.name", "--format", "tsv", gateway=gateway).out.splitlines()
        self.assertEqual(picked[:2], ["id\tvalues.name", "7051\tBilling"])

    def test_people_are_shown_only_with_with_users_and_never_under_the_policy(self):
        gateway = fresh()
        shown = run_cli("database", "7041", "--entries", "--all", "--with-users", gateway=gateway).out
        self.assertIn("Alex Example", shown)
        self.assertIn("Contact alex@example.com", shown)
        header = run_cli("folder", "7001", "--with-users", gateway=gateway).out
        self.assertIn("Author:", header)
        self.assertIn("Alex Example", header)
        policy = default_settings(hide_users=True)
        refused = run_cli("folder", "7001", "--with-users", gateway=gateway, settings=policy)
        self.assertEqual(refused.code, 1)
        self.assertIn("CONFLUENCE_HIDE_USERS=true", refused.err)
        self.assertEqual(run_cli("folder", "7001", gateway=gateway, settings=policy).code, 0)

    def test_a_title_that_names_somebody_is_redacted_unless_people_are_shown(self):
        gateway = fresh()
        gateway.containers["7001"].title = "Guides of alex@example.com"
        gateway.containers["7011"].title = "Runbooks of alex@example.com"
        gateway.containers["7061"].embed_url = "https://example.atlassian.net/wiki/people/5b10ac8d82e05b22cc7d4ef5"
        hidden = run_cli("folder", "7001", "--children", "--all", "--json", gateway=gateway)
        self.assertNotIn("alex@example.com", hidden.out + hidden.err)
        self.assertEqual(hidden.json()["title"], "Guides of [email]")
        self.assertIn("Runbooks of [email]", [child["title"] for child in hidden.json()["children"]])
        self.assertNotIn("alex@example.com", run_cli("folder", "7001", "--children", "--all", gateway=gateway).out)
        self.assertNotIn("alex@example.com", run_cli("tree", "7001", gateway=gateway).out)
        self.assertNotIn("alex@example.com", run_cli("folder", "7011", "--ancestors", gateway=gateway).out)
        self.assertEqual(run_cli("smartlink", "7061", "--json", gateway=gateway).json()["embedUrl"], "[personal link]")
        shown = run_cli("folder", "7001", "--with-users", "--json", gateway=gateway).json()
        self.assertEqual(shown["title"], "Guides of alex@example.com")
        self.assertEqual(run_cli("tree", "7001", "--json", gateway=gateway).json()["root"]["title"], "Guides of [email]")

    def test_what_is_refused_and_the_exit_codes(self):
        gateway = fresh()
        cases = (
            (("folder",), 2),  # no id
            (("folder", "abc"), 1),
            (("folder", "99999"), 4),
            (("folder", "2002"), 4),  # a page
            (("folder", "7001", "--cursor", "2"), 2),
            (("folder", "7001", "--all"), 2),
            (("folder", "7001", "--select", "id"), 2),
            (("folder", "7001", "--format", "tsv"), 2),
            (("folder", "7001", "--children", "--limit", "0"), 2),
            (("folder", "7001", "--children", "--limit", "251"), 2),
            (("folder", "7001", "--fields"), 2),
            (("database", "7041", "--fields", "--views"), 2),
            (("database", "7041", "--children", "--entries"), 2),
            (("folder", "7001", "--children", "--json", "--format", "tsv"), 2),
        )
        for argv, code in cases:
            with self.subTest(argv=argv):
                self.assertEqual(run_cli(*argv, gateway=gateway).code, code)
        self.assertEqual(gateway.called("create_folder") + gateway.called("create_page"), [])

    def test_the_hint_of_a_wrong_kind_names_the_command(self):
        gateway = fresh()
        self.assertIn("2002 is a page, not a folder: use `conflu page 2002`.", run_cli("folder", "2002", gateway=gateway).err)
        self.assertIn("7041 is a database, not a whiteboard: use `conflu database 7041`.", run_cli("whiteboard", "7041", gateway=gateway).err)
        error = run_cli("folder", "2002", "--json", gateway=gateway).error()
        self.assertEqual((error["code"], error["exitCode"], error["details"]["type"]), ("NOT_FOUND", 4, "page"))

    def test_the_envelope_wraps_a_read_and_a_failure(self):
        gateway = fresh()
        ok = run_cli("folder", "7001", "--json-envelope", gateway=gateway).json()
        self.assertEqual((ok["ok"], ok["data"]["id"]), (True, "7001"))
        failed = run_cli("folder", "99999", "--json-envelope", gateway=gateway)
        self.assertEqual((failed.code, failed.json()["ok"], failed.json()["error"]["code"]), (4, False, "NOT_FOUND"))


class TreeAndMoveTest(unittest.TestCase):
    def test_a_tree_from_a_folder(self):
        gateway = fresh()
        gateway.add_page_below("7101", "7102", "Deeper")
        result = run_cli("tree", "7001", gateway=gateway)
        self.assertEqual(
            result.out.splitlines(),
            ["Guides  [7001] (folder)", "  Architecture sketch  [7021] (whiteboard)", "  Getting started  [7101]", "    Deeper  [7102]", "  Roadmap  [7061] (embed)", "  Runbooks  [7011] (folder)", "  Services  [7041] (database)"],
        )
        data = run_cli("tree", "7001", "--depth", "1", "--json", gateway=gateway).json()
        self.assertEqual(data["root"], {"id": "7001", "title": "Guides", "type": "folder", "spaceKey": "ENG"})
        self.assertEqual([node["id"] for node in data["nodes"]], ["7021", "7101", "7061", "7011", "7041"])
        self.assertIn("(nothing below this one)", run_cli("tree", "7011", gateway=gateway).out)
        self.assertEqual(run_cli("tree", "99999", gateway=gateway).code, 4)
        self.assertEqual(run_cli("tree", "7001", "--depth", "11", gateway=gateway).code, 2)

    def test_the_text_of_a_move_below_a_folder(self):
        gateway = fresh()
        dry = run_cli("move", "2005", "--to", "7001", "--dry-run", gateway=gateway).out
        self.assertTrue(dry.startswith("Dry run: page 2005 'Plain page' would be moved below the folder 'Guides' [7001]. The move saves a new version of the page (version 1 to 2); nothing was sent\n"))
        self.assertIn('"parentId": "7001"', dry)
        self.assertEqual(gateway.called("update_page"), [])
        real = run_cli("move", "2005", "--to", "7001", gateway=gateway).out
        self.assertTrue(real.startswith("Moved page 2005: Plain page below the folder 'Guides' [7001] (version 1 -> 2)\n"))
        self.assertEqual(real.splitlines()[1], f"{BASE}/spaces/ENG/pages/2005/Plain+page")  # a title with nothing to hide stays in the address
        again = run_cli("move", "2005", "--to", "7001", gateway=gateway).out
        self.assertEqual(again, "Nothing to change: page 2005 is already below the folder 'Guides' [7001].\n")

    def test_the_json_of_a_move_has_the_target_for_either_kind(self):
        gateway = fresh()
        folder = run_cli("move", "2005", "--to", "7001", "--json", gateway=gateway).json()
        self.assertEqual((folder["action"], folder["versionFrom"], folder["versionTo"], folder["target"]), ("moved", 1, 2, {"id": "7001", "type": "folder", "title": "Guides"}))
        self.assertEqual(folder["payload"]["version"]["message"], "Moved below Guides")
        page = run_cli("move", "2005", "--to", "2003", "--json", gateway=gateway).json()
        self.assertEqual((page["payload"], page["target"]), ({"pageId": "2005", "position": "append", "targetId": "2003"}, {"id": "2003", "type": "page", "title": "Architecture"}))
        self.assertEqual((folder["confirmed"], folder["message"], page["confirmed"], page["message"]), (True, None, True, None))  # read back below the new parent
        dry = run_cli("move", "2005", "--to", "7001", "--dry-run", "--json", gateway=gateway).json()
        self.assertEqual((dry["confirmed"], dry["message"]), (None, None))  # nothing was moved, so nothing is confirmed

    def test_the_text_of_a_move_to_a_page_is_what_it_was(self):
        gateway = fresh()
        self.assertIn("would be moved", run_cli("move", "2005", "--to", "2003", "--dry-run", gateway=gateway).out)
        self.assertIn("Moved page 2005", run_cli("move", "2005", "--to", "2003", gateway=gateway).out)

    def test_what_a_move_refuses(self):
        gateway = fresh()
        cases = (
            (("move", "2005", "--to", "7001", "--position", "before"), 2),
            (("move", "7001", "--to", "2003"), 1),
            (("move", "2005", "--to", "99999"), 4),
            (("move", "2005", "--to", "../x"), 1),
            (("move", "2002", "--to", "7001", "--if-version", "1"), 3),
            (("move", "2002", "--to", "7001", "--if-unchanged-since", "2026-10-02"), 3),
            (("move", "2002", "--to", "7001", "--if-unchanged-since", "not a time"), 1),
            (("move", "2005"), 2),
        )
        for argv, code in cases:
            with self.subTest(argv=argv):
                self.assertEqual(run_cli(*argv, gateway=gateway).code, code)
        self.assertEqual(gateway.called("update_page") + gateway.called("move_page"), [])
        self.assertIn("the API has no call to move a folder", run_cli("move", "7001", "--to", "2003", gateway=gateway).err)

    def test_an_empty_guard_is_refused_and_never_means_no_guard(self):
        for target in ("7001", "2003"):
            for guard in ("", " ", "yesterday"):
                for extra in ((), ("--dry-run",)):
                    with self.subTest(target=target, guard=guard, dry_run=bool(extra)):
                        gateway = fresh()
                        result = run_cli("move", "2002", "--to", target, "--if-unchanged-since", guard, *extra, gateway=gateway)
                        self.assertEqual((result.code, result.out), (1, ""))
                        self.assertIn("--if-unchanged-since", result.err)
                        self.assertEqual(gateway.calls, [])  # refused before anything was asked, so nothing was sent
        gateway = fresh()
        self.assertEqual(run_cli("move", "2002", "--to", "7001", "--if-unchanged-since", "2026-10-30T00:00:00Z", gateway=gateway).code, 0)  # a time: the guard holds

    def test_a_move_that_cannot_be_read_back_is_a_warning_and_exit_code_0(self):
        text = run_cli("move", "2005", "--to", "2003", gateway=FailsToReadBack())
        self.assertEqual(text.code, 0, text.err)
        self.assertTrue(text.out.startswith("Moved page 2005: Plain page\n"))
        self.assertIn("The page was moved, but it could not be read back: busy. Check it with `conflu page 2005 --json` (parentId).", text.err)
        run = run_cli("move", "2005", "--to", "2003", "--json", gateway=FailsToReadBack())
        self.assertEqual(run.code, 0, run.err)
        data = run.json()
        self.assertEqual((data["action"], data["pageId"], data["confirmed"]), ("moved", "2005", None))
        self.assertTrue(data["message"].startswith("The page was moved, but it could not be read back: busy."))
        self.assertIn("could not be read back", run.err)

    def test_a_move_that_confluence_did_not_make_is_said_with_confirmed_false(self):
        gateway = fresh()
        gateway.move_page = lambda page_id, position, target_id: gateway._enter("move_page", page_id, position, target_id)  # accepted, and nothing moved
        run = run_cli("move", "2005", "--to", "2003", "--json", gateway=gateway)
        self.assertEqual(run.code, 0, run.err)
        data = run.json()
        self.assertEqual((data["action"], data["confirmed"]), ("moved", False))
        self.assertTrue(data["message"].startswith("Confluence accepted the move, but page 2005 sits below 2001, not below 2003."))
        self.assertIn("Confluence accepted the move", run.err)


class CreateBelowTest(unittest.TestCase):
    def test_the_text_names_a_folder_and_stays_what_it_was_for_a_page(self):
        gateway = fresh()
        dry = run_cli("create", "--space", "ENG", "--title", "New page", "--parent", "7001", "--body", "Hello", "--dry-run", gateway=gateway).out
        self.assertTrue(dry.startswith("Dry run: a page would be created below the folder 'Guides' [7001]; nothing was sent\n"))
        real = run_cli("create", "--space", "ENG", "--title", "New page", "--parent", "7001", "--labels", "a,b", gateway=gateway).out
        self.assertTrue(real.startswith("Created page 20001: New page below the folder 'Guides' [7001] with the labels a, b\n"))
        page = run_cli("create", "--space", "ENG", "--title", "Under a page", "--parent", "2003", "--labels", "a", gateway=gateway).out
        self.assertTrue(page.startswith("Created page 20002: Under a page with the labels a\n"))
        plain = run_cli("create", "--space", "ENG", "--title", "At the home page", "--dry-run", gateway=gateway).out
        self.assertTrue(plain.startswith("Dry run: a page would be created; nothing was sent\n"))

    def test_the_json_names_the_parent_outside_the_payload(self):
        gateway = fresh()
        data = run_cli("create", "--space", "ENG", "--title", "New page", "--parent", "7001", "--json", gateway=gateway).json()
        self.assertEqual((data["parentId"], data["parentType"], data["parent"]), ("7001", "folder", {"id": "7001", "type": "folder", "title": "Guides"}))
        self.assertEqual(data["payload"]["parentId"], "7001")
        self.assertEqual(set(data["payload"]), {"spaceId", "status", "title", "parentId", "body"})
        page = run_cli("create", "--space", "ENG", "--title", "Under a page", "--parent", "2003", "--json", gateway=gateway).json()
        self.assertEqual((page["parentType"], page["parent"]["title"]), ("page", "Architecture"))
        none = run_cli("create", "--space", "ENG", "--title", "At the home page", "--json", gateway=gateway).json()
        self.assertEqual((none["parentId"], none["parentType"], none["parent"]), (None, None, None))

    def test_what_create_refuses_below(self):
        gateway = fresh()
        gateway.content_kinds["7201"] = "blogpost"
        for parent, code in (("7201", 1), ("4001", 4), ("99999", 4), ("../x", 1)):
            with self.subTest(parent=parent):
                self.assertEqual(run_cli("create", "--space", "ENG", "--title", "T", "--parent", parent, gateway=gateway).code, code)
        gateway.add_container("folder", "7099", "Elsewhere", space_key="DOCS")
        result = run_cli("create", "--space", "ENG", "--title", "T", "--parent", "7099", gateway=gateway)
        self.assertEqual(result.code, 1)
        self.assertIn("The parent folder 7099 is not in space ENG.", result.err)
        self.assertEqual(gateway.called("create_page"), [])

    def test_import_md_and_import_md_dir_name_the_folder(self):
        files = MemoryFiles({"a.md": "# From a file\n\nText.\n", "md/b.md": "# Page b\n\ntext\n", "md/c.md": "# Page c\n\ntext\n"})
        gateway = fresh()
        dry = run_cli("import-md", "a.md", "--space", "ENG", "--parent", "7001", "--dry-run", gateway=gateway, files=files).out
        self.assertTrue(dry.startswith("Dry run: would create a page below the folder 'Guides' [7001]; nothing was sent\n"))
        real = run_cli("import-md", "a.md", "--space", "ENG", "--parent", "7001", gateway=gateway, files=files).out
        self.assertTrue(real.startswith("Created page 20001: From a file below the folder 'Guides' [7001]\n"))
        data = run_cli("import-md", "md/b.md", "--space", "ENG", "--parent", "7001", "--json", gateway=gateway, files=files).json()
        self.assertEqual((data["parentType"], data["parent"]), ("folder", {"id": "7001", "type": "folder", "title": "Guides"}))
        batch = run_cli("import-md-dir", "md", "--space", "ENG", "--parent", "7011", "--dry-run", gateway=gateway, files=files).out
        self.assertIn("would create  md/c.md below the folder 'Runbooks' [7011]", batch)
        again = run_cli("import-md-dir", "md", "--space", "ENG", "--parent", "7011", "--json", gateway=gateway, files=files).json()
        self.assertEqual(([item["action"] for item in again["outcomes"]], {item["parentType"] for item in again["outcomes"]}), (["unchanged", "created"], {"folder", None}))
        self.assertEqual(again["outcomes"][1]["parent"]["id"], "7011")


class CreateFolderAndSmartLinkTest(unittest.TestCase):
    def test_a_folder_in_text_and_json(self):
        gateway = fresh()
        dry = run_cli("folder-create", "--title", "Runbooks 2026", "--space", "ENG", "--parent", "7001", "--dry-run", gateway=gateway).out
        self.assertTrue(dry.startswith("Dry run: a folder would be created below the folder 'Guides' [7001]; nothing was sent\n"))
        self.assertIn('"title": "Runbooks 2026"', dry)
        self.assertEqual(gateway.called("create_folder"), [])
        real = run_cli("folder-create", "--title", "Runbooks 2026", "--space", "ENG", "--parent", "7001", gateway=gateway).out
        self.assertEqual(real, f"Created folder 20001: Runbooks 2026 below the folder 'Guides' [7001]\n{BASE}/spaces/ENG/folder/20001\n")
        data = run_cli("folder-create", "--title", "Top", "--space", "ENG", "--json", gateway=gateway).json()
        self.assertEqual(
            list(data),
            ["action", "dryRun", "folderId", "title", "spaceKey", "url", "parentId", "parentType", "parent", "payload"],
        )
        self.assertEqual((data["folderId"], data["parent"], data["payload"]), ("20002", None, {"spaceId": "1001", "title": "Top"}))
        dry_json = run_cli("folder-create", "--title", "Top", "--space", "ENG", "--dry-run", "--json", gateway=gateway).json()
        self.assertEqual((dry_json["folderId"], dry_json["url"], dry_json["dryRun"]), (None, None, True))

    def test_a_smart_link_in_text_and_json(self):
        gateway = fresh()
        argv = ("smartlink-create", "--url", "https://example.com/roadmap?a=1&b=2", "--title", "Roadmap", "--space", "ENG")
        dry = run_cli(*argv, "--parent", "7001", "--dry-run", gateway=gateway).out
        self.assertTrue(dry.startswith("Dry run: a smart link would be created below the folder 'Guides' [7001]; nothing was sent\n"))
        self.assertIn('"embedUrl": "https://example.com/roadmap?a=1&b=2"', dry)
        real = run_cli(*argv, gateway=gateway).out
        self.assertEqual(real, f"Created smart link 20001: Roadmap\n{BASE}/spaces/ENG/embed/20001\n")
        data = run_cli(*argv, "--json", gateway=gateway).json()
        self.assertEqual(
            list(data),
            ["action", "dryRun", "smartlinkId", "title", "spaceKey", "url", "embedUrl", "parentId", "parentType", "parent", "payload"],
        )
        self.assertEqual((data["smartlinkId"], data["embedUrl"]), ("20002", "https://example.com/roadmap?a=1&b=2"))

    def test_what_is_refused_before_anything_is_read(self):
        gateway = fresh()
        for argv, code in (
            (("folder-create", "--title", " ", "--space", "ENG"), 1),
            (("folder-create", "--title", "x" * 256, "--space", "ENG"), 1),
            (("folder-create", "--space", "ENG"), 2),
            (("folder-create", "--title", "T"), 2),  # no space
            (("smartlink-create", "--url", "ftp://example.com", "--title", "T", "--space", "ENG"), 1),
            (("smartlink-create", "--url", "https://u:p@example.com", "--title", "T", "--space", "ENG"), 1),
            (("smartlink-create", "--title", "T", "--space", "ENG"), 2),
            (("smartlink-create", "--url", "https://example.com", "--space", "ENG"), 2),
        ):
            with self.subTest(argv=argv):
                self.assertEqual(run_cli(*argv, gateway=gateway).code, code)
        self.assertEqual(gateway.calls, [])

    def test_what_the_error_texts_leave_out(self):
        result = run_cli("smartlink-create", "--url", "https://user:topsecret@example.com", "--title", "T", "--space", "ENG")
        self.assertNotIn("topsecret", result.out + result.err)
        self.assertNotIn("user:", result.err)

    def test_a_parent_that_cannot_be_one(self):
        gateway = fresh()
        gateway.content_kinds["7201"] = "blogpost"
        self.assertEqual(run_cli("folder-create", "--title", "T", "--space", "ENG", "--parent", "7201", gateway=gateway).code, 1)
        self.assertEqual(run_cli("folder-create", "--title", "T", "--space", "ENG", "--parent", "99999", gateway=gateway).code, 4)
        self.assertEqual(run_cli("smartlink-create", "--url", "https://example.com", "--title", "T", "--space", "ENG", "--parent", "7201", gateway=gateway).code, 1)
        self.assertEqual(gateway.called("create_folder") + gateway.called("create_smartlink"), [])


class EmptyOptionsTest(unittest.TestCase):
    """An option that was given and is empty is a mistake and never means "not given": the current space, the home page of the space, the top of it."""

    def refused(self, argv, message, files=None):
        for extra in ((), ("--dry-run",)):
            with self.subTest(argv=argv, dry_run=bool(extra)):
                gateway = fresh()
                result = run_cli(*argv, *extra, gateway=gateway, files=files, settings=default_settings(space="DOCS"))
                self.assertEqual(result.code, 2, result.err)
                self.assertEqual(result.out, "")
                self.assertIn(message, result.err)
                self.assertEqual(gateway.calls, [])  # nothing was asked, so nothing was made in DOCS, below the home page or at the top of ENG

    def both_options(self, command, files=None):
        for blank in ("", "  "):
            self.refused((*command, "--space", blank), "The space is empty.", files)
            self.refused((*command, "--space", "ENG", "--parent", blank), "The parent is empty.", files)

    def test_create(self):
        self.both_options(("create", "--title", "New", "--body", "Text."))
        done = run_cli("create", "--title", "New", "--body", "Text.", "--dry-run", "--json", settings=default_settings(space="DOCS")).json()
        self.assertEqual((done["dryRun"], done["payload"]["spaceId"]), (True, "1002"))  # none given: the current space

    def test_folder_create(self):
        self.both_options(("folder-create", "--title", "New"))
        done = run_cli("folder-create", "--title", "New", "--dry-run", "--json", settings=default_settings(space="DOCS")).json()
        self.assertEqual((done["spaceKey"], done["parentId"]), ("DOCS", None))

    def test_smartlink_create(self):
        self.both_options(("smartlink-create", "--title", "New", "--url", "https://example.com/new"))
        done = run_cli("smartlink-create", "--title", "New", "--url", "https://example.com/new", "--dry-run", "--json", settings=default_settings(space="DOCS")).json()
        self.assertEqual((done["spaceKey"], done["parentId"]), ("DOCS", None))

    def test_import_md(self):
        files = MemoryFiles({"a.md": "# A page\n\nText.\n"})
        self.both_options(("import-md", "a.md"), files)
        done = run_cli("import-md", "a.md", "--dry-run", "--json", files=files, settings=default_settings(space="DOCS")).json()
        self.assertEqual((done["action"], done["payload"]["spaceId"]), ("created", "1002"))

    def test_import_md_dir(self):
        files = MemoryFiles({"md/a.md": "# Page a\n\nText.\n", "md/b.md": "# Page b\n\nText.\n"})
        self.both_options(("import-md-dir", "md"), files)  # refused as a whole, not file by file
        done = run_cli("import-md-dir", "md", "--dry-run", "--json", files=files, settings=default_settings(space="DOCS")).json()
        self.assertEqual((done["created"], done["failed"]), (2, 0))

    def refused_everywhere(self, argv, message, dry_run=True):
        """Exit code 2 and no output, nothing asked and nothing written, whether a dry run is asked or not (`dry_run=False`: the command has none)."""
        for extra in ((), ("--dry-run",)) if dry_run else ((),):
            with self.subTest(argv=argv, dry_run=bool(extra)):
                gateway, files = fresh(), MemoryFiles()
                result = run_cli(*argv, *extra, gateway=gateway, files=files, settings=default_settings(space="DOCS"))
                self.assertEqual((result.code, result.out), (2, ""), result.err)
                self.assertIn(message, result.err)
                self.assertEqual((gateway.calls, files.writes), ([], []))

    def test_export_page(self):
        for blank in ("", "  "):
            self.refused_everywhere(("export", "--page", blank, "--out", "out"), "The page is empty.")  # it would have exported the whole current space
        done = run_cli("export", "--out", "out", "--dry-run", "--json", settings=default_settings(space="DOCS")).json()
        self.assertEqual((done["space"], done["root"], done["count"]), ("DOCS", None, 1))  # none given: the current space

    def test_export_space(self):
        for blank in ("", "  "):
            self.refused_everywhere(("export", "--space", blank, "--out", "out"), "The space is empty.")
        done = run_cli("export", "--space", "ENG", "--out", "out", "--dry-run", "--json", settings=default_settings(space="DOCS")).json()
        self.assertEqual((done["space"], done["count"]), ("ENG", 5))

    def test_export_out(self):
        for blank in ("", "  "):
            self.refused_everywhere(("export", "--space", "ENG", "--out", blank), "The output folder is empty.")  # it would have written into the folder that you are in

    def test_tree_space(self):
        for blank in ("", "  "):
            for root in ("2001", "page:Architecture"):  # an id has no use for a space, and an empty one is a mistake all the same
                self.refused_everywhere(("tree", root, "--space", blank), "The space is empty.", dry_run=False)
        done = run_cli("tree", "page:Architecture", "--depth", "1", "--json", settings=default_settings(space="ENG")).json()
        self.assertEqual(done["root"]["title"], "Architecture")  # none given: the current space

    def test_tree_root(self):
        for blank in ("", "  "):
            with self.subTest(root=blank):
                gateway = fresh()
                result = run_cli("tree", blank, gateway=gateway)
                self.assertEqual((result.code, result.out), (1, ""))  # an empty root has always been an invalid id
                self.assertIn("Invalid id", result.err)
                self.assertEqual(gateway.calls, [])


class PageOfAFolderTest(unittest.TestCase):
    """REQ-7: pages and folders have ids of one sequence, so the id of a folder given to `conflu page` says what it is."""

    def test_the_id_of_a_folder_names_the_command_that_shows_it(self):
        gateway = fresh()
        result = run_cli("page", "7001", gateway=gateway)
        self.assertEqual(result.code, 4)
        self.assertIn("Hint: 7001 is a folder, not a page: use `conflu folder 7001`.", result.err)
        error = run_cli("page", "7001", "--json", gateway=gateway).error()
        self.assertEqual((error["code"], error["details"]), ("NOT_FOUND", {"type": "folder"}))

    def test_a_folder_in_the_path_of_a_page_has_its_title(self):
        ancestors = run_cli("page", "7101", "--ancestors", "--json", gateway=fresh()).json()["ancestors"]
        self.assertEqual(ancestors, [{"id": "7001", "title": "Guides"}])


PERSONAL = f"~{ACCOUNT}"


def personal():
    """The in-memory Confluence with a personal space, which is keyed by `~` and the account id of its owner: a page, a folder and a page below it."""
    gateway = FakeGateway()
    gateway.spaces[PERSONAL] = Space("1003", PERSONAL, "Alex Example", "personal", "current", "", "30000", "2026-09-01T08:00:00.000Z", f"{BASE}/spaces/{PERSONAL}")
    gateway.pages["30000"] = sample_page("30000", "Start", space_id="1003", space_key=PERSONAL)
    gateway.add_page_below("30000", "30001", "Notes alex@example.com", space_key=PERSONAL)
    gateway.add_container("folder", "7095", "Archive", parent_id="30000", space_key=PERSONAL)
    gateway.add_page_below("7095", "30002", "Old notes", space_key=PERSONAL)
    return gateway


class PersonalSpaceTest(unittest.TestCase):
    """Nothing that these commands print may carry the key of a personal space, or the account id in it, unless `--with-users` asks for it."""

    def test_no_command_prints_the_key_or_the_account_id(self):
        runs = (
            ("tree", "30001"),
            ("tree", "7095", "--json"),
            ("tree", "30000", "--json"),
            ("folder", "7095"),
            ("folder", "7095", "--json"),
            ("folder", "7095", "--children", "--ancestors"),
            ("folder", "7095", "--ancestors", "--json"),
            ("folder-create", "--title", "Top", "--space", PERSONAL, "--dry-run"),
            ("folder-create", "--title", "Top", "--space", PERSONAL),
            ("folder-create", "--title", "Top", "--space", PERSONAL, "--json"),
            ("folder-create", "--title", "Elsewhere", "--space", PERSONAL, "--parent", "7001"),
            ("smartlink-create", "--url", "https://example.com/x", "--title", "Link", "--space", PERSONAL, "--parent", "7095"),
            ("smartlink-create", "--url", "https://example.com/x", "--title", "Link", "--space", PERSONAL, "--json"),
            ("create", "--title", "New", "--space", PERSONAL, "--parent", "7095", "--body", "Text."),
            ("create", "--title", "New", "--space", PERSONAL, "--parent", "7095", "--body", "Text.", "--json"),
            ("create", "--title", "New", "--space", PERSONAL, "--parent", "7095", "--body", "Text.", "--dry-run", "--json"),
            ("create", "--title", "Notes alex@example.com", "--space", PERSONAL, "--body", "Text."),  # the title is taken
            ("create", "--title", "Notes alex@example.com", "--space", PERSONAL, "--body", "Text.", "--json"),
            ("move", "30001", "--to", "7095", "--dry-run"),
            ("move", "30001", "--to", "7095", "--dry-run", "--json"),
            ("move", "30001", "--to", "7095"),
            ("move", "30001", "--to", "7095", "--json"),
            ("move", "30001", "--to", "30002", "--dry-run", "--json"),
            ("move", "30001", "--to", "30002"),
            ("export", "--space", PERSONAL, "--out", "out"),
            ("export", "--space", PERSONAL, "--out", "out", "--json"),
            ("export", "--page", "30001", "--out", "out", "--json"),
            ("export", "--page", "7095", "--out", "out", "--json"),
        )
        for argv in runs:
            with self.subTest(argv=argv):
                result = run_cli(*argv, gateway=personal(), files=MemoryFiles())
                self.assertNotIn(ACCOUNT, result.out + result.err)

    def test_what_is_shown_in_the_place_of_the_key_and_of_the_address(self):
        tree = run_cli("tree", "30001", "--json", gateway=personal()).json()
        self.assertEqual(tree["root"]["spaceKey"], "[hidden]")
        folder = run_cli("folder", "7095", "--json", gateway=personal()).json()
        self.assertEqual((folder["spaceKey"], folder["url"]), ("[hidden]", f"{BASE}/spaces/[hidden]/folder/7095"))
        text = run_cli("folder", "7095", gateway=personal()).out.splitlines()
        self.assertEqual((text[0], text[1]), ("Archive  [7095]", f"{BASE}/spaces/[hidden]/folder/7095"))
        self.assertIn("Space:   [hidden]", text)
        made = run_cli("folder-create", "--title", "Top", "--space", PERSONAL, "--json", gateway=personal()).json()
        self.assertEqual((made["spaceKey"], made["url"]), ("[hidden]", f"{BASE}/spaces/[hidden]/folder/20001"))
        link = run_cli("smartlink-create", "--url", "https://example.com/x", "--title", "L", "--space", PERSONAL, "--json", gateway=personal()).json()
        self.assertEqual((link["spaceKey"], link["url"]), ("[hidden]", f"{BASE}/spaces/[hidden]/embed/20001"))
        created = run_cli("create", "--title", "New", "--space", PERSONAL, "--parent", "7095", "--body", "Text.", "--json", gateway=personal()).json()
        self.assertEqual(created["url"], f"{BASE}/pages/viewpage.action?pageId=20001")  # the address that names the page by its id alone

    def test_a_move_names_the_page_by_its_id_alone(self):
        address = f"{BASE}/pages/viewpage.action?pageId=30001"
        for target in ("7095", "30002"):
            with self.subTest(target=target):
                data = run_cli("move", "30001", "--to", target, "--json", gateway=personal()).json()
                self.assertEqual((data["title"], data["url"]), ("Notes [email]", address))
                self.assertEqual(run_cli("move", "30001", "--to", target, gateway=personal()).out.splitlines()[-1], address)

    def test_with_users_shows_everything_as_confluence_gives_it(self):
        folder = run_cli("folder", "7095", "--with-users", "--json", gateway=personal()).json()
        self.assertEqual((folder["spaceKey"], folder["url"]), (PERSONAL, f"{BASE}/spaces/{PERSONAL}/folder/7095"))
        moved = run_cli("move", "30001", "--to", "7095", "--with-users", "--json", gateway=personal()).json()
        self.assertEqual((moved["title"], moved["url"]), ("Notes alex@example.com", f"{BASE}/spaces/{PERSONAL}/pages/30001/Notes+alex@example.com"))
        text = run_cli("move", "30001", "--to", "7095", "--with-users", gateway=personal()).out
        self.assertIn(f"{BASE}/spaces/{PERSONAL}/pages/30001/Notes+alex@example.com", text)

    def test_the_key_of_another_space_is_shown_as_it_is(self):
        self.assertEqual(run_cli("tree", "2003", "--json", gateway=personal()).json()["root"]["spaceKey"], "ENG")
        self.assertEqual(run_cli("folder", "7001", "--json", gateway=personal()).json()["spaceKey"], "ENG")
        self.assertEqual(run_cli("folder-create", "--title", "Top", "--space", "ENG", "--json", gateway=personal()).json()["spaceKey"], "ENG")


if __name__ == "__main__":
    unittest.main()
