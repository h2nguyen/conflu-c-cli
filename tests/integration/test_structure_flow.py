"""Folders and the rest of the tree, the real program against the mock Confluence: publish below a folder (REQ-7), read a folder, move into one, export one."""
import json
import tempfile
import unittest
from pathlib import Path

from conflu_c_cli.domain.errors import ConfluCliError, NotFoundError, RejectedError
from conflu_c_cli.domain.model import PageRef
from conflu_c_cli.domain.structure import FieldValue
from tests.integration.test_end_to_end import ACCOUNT, EndToEnd
from tests.support.mock_structure import StructureRoutes


class StructureFlow(EndToEnd):
    def setUp(self):
        super().setUp()
        self.area = self.mock.area(StructureRoutes)

    def sent_writes(self):
        return [item for item in self.mock.requests if item.method != "GET" and item.path != "/api/v2/content/convert-ids-to-types"]

    def below_the_folder(self, title="Getting started"):
        return self.mock.add_page("ENG", title, "<p>Text.</p>", parent_id="7001")

    def work(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        return Path(folder.name)


class PublishBelowAFolderTest(StructureFlow):
    """REQ-7: a page is created below a folder without `conflu api`."""

    def test_the_dry_run_shows_the_parent_type_and_sends_nothing(self):
        result = self.cli("create", "--parent", "7001", "--title", "Getting started", "--space", "ENG", "--body", "Hello", "--dry-run", "--json")
        self.assertEqual(result.code, 0, result.err)
        data = result.json()
        self.assertEqual((data["dryRun"], data["parentId"], data["parentType"]), (True, "7001", "folder"))
        self.assertEqual(data["parent"], {"id": "7001", "type": "folder", "title": "Guides"})
        self.assertEqual(data["payload"]["parentId"], "7001")
        self.assertNotIn("parentType", data["payload"])  # the payload is what POST /pages takes, nothing else
        self.assertEqual(self.sent_writes(), [])
        text = self.cli("create", "--parent", "7001", "--title", "Getting started", "--space", "ENG", "--dry-run").out
        self.assertIn("Dry run: a page would be created below the folder 'Guides' [7001]; nothing was sent", text)

    def test_the_real_run_puts_the_page_below_the_folder_and_page_shows_it(self):
        created = self.cli("create", "--parent", "7001", "--title", "Getting started", "--space", "ENG", "--body", "Hello", "--json")
        self.assertEqual(created.code, 0, created.err)
        page_id = created.json()["pageId"]
        self.assertEqual(created.json()["payload"]["parentId"], "7001")
        shown = self.cli("page", page_id, "--json", "--ancestors").json()
        self.assertEqual((shown["parentId"], shown["parentType"]), ("7001", "folder"))
        self.assertEqual([item["id"] for item in shown["ancestors"]], ["7001"])
        self.assertIn("7001 (folder)", self.cli("page", page_id, "--no-body").out)

    def test_the_real_request_is_the_one_of_the_dry_run(self):
        preview = self.cli("create", "--parent", "7001", "--title", "Same payload", "--space", "ENG", "--body", "Hello", "--json", "--dry-run").json()["payload"]
        self.cli("create", "--parent", "7001", "--title", "Same payload", "--space", "ENG", "--body", "Hello", "--json")
        posted = [item for item in self.mock.requests if item.method == "POST" and item.path == "/api/v2/pages"]
        self.assertEqual([item.body for item in posted], [preview])

    def test_a_page_as_the_parent_costs_no_request_for_the_type(self):
        self.cli("create", "--parent", "2003", "--title", "Below a page", "--space", "ENG", "--dry-run", "--json")
        paths = [(item.method, item.path) for item in self.mock.requests]
        self.assertNotIn(("POST", "/api/v2/content/convert-ids-to-types"), paths)
        self.assertIn(("GET", "/api/v2/pages/2003"), paths)
        self.assertEqual([path for _, path in paths if "/folders" in path], [])

    def test_a_folder_address_names_the_parent(self):
        address = f"{self.mock.base_url}/spaces/ENG/folder/7001"
        data = self.cli("create", "--parent", address, "--title", "By address", "--space", "ENG", "--dry-run", "--json").json()
        self.assertEqual((data["parentId"], data["parentType"]), ("7001", "folder"))

    def test_every_other_container_may_be_the_parent(self):
        for parent_id, kind in (("7011", "folder"), ("7021", "whiteboard"), ("7041", "database"), ("7061", "embed")):
            with self.subTest(parent=parent_id):
                data = self.cli("create", "--parent", parent_id, "--title", f"Below {kind}", "--space", "ENG", "--json").json()
                self.assertEqual(data["parentType"], kind)
                self.assertEqual(self.cli("page", data["pageId"], "--json").json()["parentType"], kind)

    def test_import_md_publishes_below_a_folder(self):
        note = self.work() / "note.md"
        note.write_text("---\ntitle: From a file\n---\nText.\n", encoding="utf-8")
        data = self.cli("import-md", str(note), "--space", "ENG", "--parent", "7001", "--json").json()
        self.assertEqual((data["action"], data["parentType"], data["parent"]["id"]), ("created", "folder", "7001"))
        self.assertEqual(self.cli("page", data["pageId"], "--json").json()["parentType"], "folder")
        dry = self.work() / "dry.md"
        dry.write_text("# Dry one\n\nText.\n", encoding="utf-8")
        self.assertIn("would create a page below the folder 'Guides' [7001]", self.cli("import-md", str(dry), "--space", "ENG", "--parent", "7001", "--dry-run").out)

    def test_the_parent_line_of_the_front_matter_may_name_a_folder(self):
        note = self.work() / "note.md"
        note.write_text("---\ntitle: Parent in the file\nparent: 7011\n---\nText.\n", encoding="utf-8")
        data = self.cli("import-md", str(note), "--space", "ENG", "--json").json()
        self.assertEqual((data["parentType"], data["parent"]["id"]), ("folder", "7011"))
        self.assertEqual(self.mock.pages[data["pageId"]]["parentId"], "7011")

    def test_import_md_dir_publishes_a_folder_of_files_below_a_folder(self):
        folder = self.work() / "md"
        folder.mkdir()
        for name in ("a", "b", "c"):
            (folder / f"{name}.md").write_text(f"# Page {name}\n\nText.\n", encoding="utf-8")
        result = self.cli("import-md-dir", str(folder), "--space", "ENG", "--parent", "7001", "--json")
        self.assertEqual(result.code, 0, result.err)
        data = result.json()
        self.assertEqual((data["created"], data["failed"]), (3, 0))
        self.assertEqual({item["parentType"] for item in data["outcomes"]}, {"folder"})
        self.assertEqual([self.mock.pages[item["pageId"]]["parentId"] for item in data["outcomes"]], ["7001"] * 3)
        looked_up = [item for item in self.mock.requests if item.path == "/api/v2/content/convert-ids-to-types"]
        self.assertEqual(len(looked_up), 1)  # the folder is looked up once, not once per file

    def test_a_dry_run_of_a_folder_of_files_names_the_parent_and_writes_nothing(self):
        folder = self.work() / "md"
        folder.mkdir()
        (folder / "a.md").write_text("# Page a\n\nText.\n", encoding="utf-8")
        text = self.cli("import-md-dir", str(folder), "--space", "ENG", "--parent", "7001", "--dry-run").out
        self.assertIn("below the folder 'Guides' [7001]", text)
        self.assertEqual(self.sent_writes(), [])


class WhatIsRefusedTest(StructureFlow):
    def test_a_blog_post_cannot_be_a_parent(self):
        self.mock.content_kinds["7101"] = "blogpost"
        result = self.cli("create", "--parent", "7101", "--title", "Below a blog post", "--space", "ENG", "--dry-run")
        self.assertEqual(result.code, 1)
        self.assertIn("7101 is a blog post, which cannot be a parent", result.err)
        self.assertIn("a page, a folder, a whiteboard, a database or a smart link", result.err)
        self.assertEqual(self.sent_writes(), [])

    def test_a_comment_cannot_be_a_parent(self):
        result = self.cli("create", "--parent", "4001", "--title", "Below a comment", "--space", "ENG", "--dry-run")
        self.assertEqual(result.code, 1)
        self.assertIn("4001 is a footer comment", result.err)

    def test_an_attachment_cannot_be_a_parent(self):
        result = self.cli("create", "--parent", "att5001", "--title", "Below an attachment", "--space", "ENG", "--dry-run")
        self.assertEqual(result.code, 1)
        self.assertIn("att5001 is an attachment", result.err)
        self.assertEqual(self.sent_writes(), [])

    def test_an_unknown_id_is_not_found_with_a_hint(self):
        result = self.cli("create", "--parent", "99999", "--title", "Nowhere", "--space", "ENG", "--dry-run", "--json")
        self.assertEqual(result.code, 4)
        error = json.loads(result.err.strip().splitlines()[-1])["error"]
        self.assertEqual((error["code"], error["exitCode"]), ("NOT_FOUND", 4))
        self.assertIn("No page, folder, whiteboard, database or smart link with the id 99999", error["message"])
        self.assertIn("conflu folder ID --children", error["hint"])

    def test_a_parent_in_another_space_is_refused_before_anything_is_sent(self):
        other = self.mock.area(StructureRoutes).add("folder", "7099", "Elsewhere", None, space_id="1002")
        self.assertEqual(other["spaceId"], "1002")
        result = self.cli("create", "--parent", "7099", "--title", "Wrong space", "--space", "ENG", "--dry-run")
        self.assertEqual(result.code, 1)
        self.assertIn("The parent folder 7099 is not in space ENG", result.err)
        self.assertIn("A page is created in the space of its parent", result.err)
        self.assertEqual(self.sent_writes(), [])

    def test_hostile_ids_never_reach_the_server(self):
        for text in ("../x", "1" * 25, "12\x00", "7001/../../x", "7001?x=1", "page:ENG/Guides", "https://example.com/wiki/x/AbCd"):
            with self.subTest(parent=text):
                result = self.cli("create", "--parent", text, "--title", "Hostile", "--space", "ENG", "--dry-run")
                self.assertEqual(result.code, 1, result.err)
        for command in ("folder", "whiteboard", "database", "smartlink"):
            self.assertEqual(self.cli(command, "../x").code, 1)
        self.assertEqual(self.cli("tree", "../x").code, 1)
        self.assertEqual(self.cli("move", "2005", "--to", "../x").code, 1)
        touched = [item.path for item in self.mock.requests if item.path.startswith(("/api/v2/pages/", "/api/v2/folders/", "/api/v2/content"))]
        self.assertEqual(touched, [])  # an id that is none is refused before a request is made for it

    def test_a_page_id_given_to_folder_says_what_it_is(self):
        result = self.cli("folder", "2002")
        self.assertEqual(result.code, 4)
        self.assertIn("2002 is a page, not a folder: use `conflu page 2002`", result.err)
        self.assertEqual(self.cli("database", "7001").code, 4)
        self.assertIn("7001 is a folder, not a database: use `conflu folder 7001`", self.cli("database", "7001").err)


class TreeFromAFolderTest(StructureFlow):
    def test_a_tree_starts_at_a_folder(self):
        page = self.below_the_folder()
        data = self.cli("tree", "7001", "--json").json()
        self.assertEqual(data["root"], {"id": "7001", "title": "Guides", "type": "folder", "spaceKey": "ENG"})
        self.assertEqual({(node["id"], node["type"]) for node in data["nodes"]}, {("7011", "folder"), ("7021", "whiteboard"), ("7041", "database"), ("7061", "embed"), (page, "page")})
        self.assertEqual({node["parentId"] for node in data["nodes"]}, {"7001"})
        text = self.cli("tree", "7001").out
        self.assertTrue(text.startswith("Guides  [7001] (folder)\n"))
        self.assertIn("  Roadmap  [7061] (embed)", text)

    def test_a_page_below_a_folder_is_in_the_tree_of_its_parent_page_and_has_the_folder_as_ancestor(self):
        page = self.below_the_folder()
        child = self.mock.add_page("ENG", "Deeper", "<p>x</p>", parent_id=page)
        data = self.cli("tree", "7001", "--depth", "2", "--json").json()
        self.assertEqual([(node["id"], node["depth"]) for node in data["nodes"] if node["type"] == "page"], [(page, 1), (child, 2)])
        self.assertEqual([item["id"] for item in self.cli("page", child, "--ancestors", "--json").json()["ancestors"]], ["7001", page])

    def test_a_tree_from_a_page_is_the_request_sequence_that_it_was(self):
        self.cli("tree", "2001", "--json")
        paths = [item.path for item in self.mock.requests]
        self.assertEqual(paths, ["/api/v2/pages/2001", "/api/v2/pages/2001/descendants", "/api/v2/pages/2001/descendants"])  # the mock hands out two at a time

    def test_a_tree_from_a_folder_keeps_the_types_below_a_page(self):
        folder = self.mock.area(StructureRoutes).add("folder", "7090", "Below a page", "2003")
        self.assertEqual(folder["parentId"], "2003")
        nodes = self.cli("tree", "2003", "--json").json()["nodes"]
        self.assertIn(("7090", "folder"), [(node["id"], node["type"]) for node in nodes])

    def test_other_roots(self):
        for root, kind in (("7021", "whiteboard"), ("7041", "database"), ("7061", "embed")):
            with self.subTest(root=root):
                data = self.cli("tree", root, "--json").json()
                self.assertEqual((data["root"]["type"], data["nodes"]), (kind, []))
        self.assertIn("(nothing below this one)", self.cli("tree", "7011").out)

    def test_a_blog_post_or_an_unknown_id_cannot_start_a_tree(self):
        self.mock.content_kinds["7101"] = "blogpost"
        result = self.cli("tree", "7101")
        self.assertEqual(result.code, 1)
        self.assertIn("7101 is a blog post, which cannot be the start of a tree", result.err)
        self.assertEqual(self.cli("tree", "99999").code, 4)

    def test_select_and_format_work_on_the_nodes_of_a_folder(self):
        self.below_the_folder()
        result = self.cli("tree", "7001", "--select", "id,type", "--format", "tsv")
        self.assertEqual(result.out.splitlines()[0], "id\ttype")
        self.assertEqual(len(result.out.splitlines()), 6)


class MoveIntoAFolderTest(StructureFlow):
    def test_a_move_below_a_folder_saves_the_page_again_with_a_new_parent(self):
        before = self.mock.pages["2005"]["versions"][-1]["body"]
        result = self.cli("move", "2005", "--to", "7001", "--json")
        self.assertEqual(result.code, 0, result.err)
        data = result.json()
        self.assertEqual((data["action"], data["dryRun"], data["versionFrom"], data["versionTo"]), ("moved", False, 1, 2))
        self.assertEqual(data["target"], {"id": "7001", "type": "folder", "title": "Guides"})
        self.assertEqual(data["payload"]["parentId"], "7001")
        self.assertEqual(data["payload"]["version"], {"number": 2, "message": "Moved below Guides"})
        self.assertFalse(data["payloadRedacted"])  # nothing in this page to hide
        page = self.mock.pages["2005"]
        self.assertEqual((page["parentId"], len(page["versions"])), ("7001", 2))
        self.assertEqual(page["versions"][-1]["body"], before)  # the body went back as it was
        self.assertEqual(self.cli("page", "2005", "--json").json()["parentType"], "folder")
        puts = [item for item in self.mock.requests if item.method == "PUT"]
        self.assertEqual([item.path for item in puts], ["/api/v2/pages/2005"])
        self.assertEqual(puts[0].body, data["payload"])  # the request is what the output shows

    def test_the_dry_run_reads_and_sends_nothing(self):
        result = self.cli("move", "2005", "--to", "7001", "--dry-run", "--json")
        data = result.json()
        self.assertEqual((data["action"], data["dryRun"], data["versionFrom"], data["versionTo"]), ("moved", True, 1, 2))
        self.assertEqual(self.sent_writes(), [])
        self.assertEqual(self.mock.pages["2005"]["parentId"], "2001")
        text = self.cli("move", "2005", "--to", "7001", "--dry-run").out
        self.assertIn("would be moved below the folder 'Guides' [7001]. The move saves a new version of the page (version 1 to 2); nothing was sent", text)
        self.assertIn("If somebody has an unpublished draft of the page, Confluence merges this body into it", text)

    def test_a_page_that_is_below_the_folder_already_is_left_alone(self):
        self.cli("move", "2005", "--to", "7001")
        again = self.cli("move", "2005", "--to", "7001", "--json").json()
        self.assertEqual((again["action"], again["versionFrom"], again["versionTo"], again["payload"]), ("unchanged", 2, 2, None))
        self.assertEqual(len(self.mock.pages["2005"]["versions"]), 2)
        self.assertIn("is already below the folder 'Guides' [7001]", self.cli("move", "2005", "--to", "7001").out)

    def test_a_move_to_a_page_is_the_v1_call_with_no_new_version(self):
        data = self.cli("move", "2005", "--to", "2003", "--json").json()
        self.assertEqual((data["payload"], data["target"]["type"]), ({"pageId": "2005", "position": "append", "targetId": "2003"}, "page"))
        self.assertEqual(len(self.mock.pages["2005"]["versions"]), 1)
        calls = [(item.method, item.path) for item in self.mock.requests if item.method != "GET"]
        self.assertEqual(calls, [("PUT", "/rest/api/content/2005/move/append/2003")])
        self.assertNotIn("/api/v2/content/convert-ids-to-types", [item.path for item in self.mock.requests])
        self.assertEqual(self.mock.pages["2005"]["parentId"], "2003")

    def test_an_empty_guard_is_refused_and_nothing_is_asked_or_sent_not_even_in_a_dry_run(self):
        for target in ("7001", "2003"):
            for extra in ((), ("--dry-run",)):
                with self.subTest(target=target, dry_run=bool(extra)):
                    result = self.cli("move", "2005", "--to", target, "--if-unchanged-since", "", *extra)
                    self.assertEqual((result.code, result.out), (1, ""))
                    self.assertIn("--if-unchanged-since", result.err)
        self.assertEqual(self.mock.requests, [])
        self.assertEqual(self.mock.pages["2005"]["parentId"], "2001")
        self.assertEqual(self.cli("move", "2005", "--to", "7001", "--if-unchanged-since", "2026-10-30T00:00:00Z").code, 0)  # a time is a guard

    def test_a_move_whose_page_cannot_be_read_back_is_still_a_move_with_exit_code_0_and_a_warning(self):
        original = self.mock.take_failure

        def take_failure(method, path):
            if method == "PUT" and "/move/" in path:  # the move is asked for: from here on the page cannot be read
                self.mock.fail_next("/api/v2/pages/2005", 500, method="GET", body={"errors": [{"status": 500, "title": "Busy", "detail": "busy"}]})
            return original(method, path)

        self.mock.take_failure = take_failure
        result = self.cli("move", "2005", "--to", "2003", "--json", env={"CONFLUENCE_RETRY": "0"})
        self.assertEqual(result.code, 0, result.err)
        data = result.json()
        self.assertEqual((data["action"], data["pageId"], data["confirmed"]), ("moved", "2005", None))
        self.assertTrue(data["message"].startswith("The page was moved, but it could not be read back:"), data["message"])
        self.assertIn("could not be read back", result.err)
        self.assertEqual(self.mock.pages["2005"]["parentId"], "2003")  # the move was made, and the page is where it was moved to
        self.assertEqual([item.path for item in self.mock.requests if item.method == "PUT"], ["/rest/api/content/2005/move/append/2003"])

    def test_a_move_that_was_read_back_is_confirmed(self):
        for target in ("2003", "7001"):
            data = self.cli("move", "2005", "--to", target, "--json").json()
            self.assertEqual((data["confirmed"], data["message"]), (True, None))
        self.assertEqual(self.cli("move", "2005", "--to", "2003", "--dry-run", "--json").json()["confirmed"], None)

    def test_a_folder_only_takes_append(self):
        result = self.cli("move", "2005", "--to", "7001", "--position", "before")
        self.assertEqual(result.code, 2)
        self.assertIn("A folder can only be a parent: the position among its children cannot be given", result.err)
        self.assertEqual(self.sent_writes(), [])
        self.assertEqual(self.cli("move", "2005", "--to", "7001", "--position", "append", "--dry-run").code, 0)

    def test_before_or_after_the_home_page_is_refused_because_the_page_would_be_at_the_top_level(self):
        # The document of the move: "never use `before` or `after` positions when the `targetId` is a top-level page".
        loose = self.mock.add_page("ENG", "A page at the top level", "<p>x</p>")
        self.mock.pages[loose]["parentId"] = None  # not the home page, and no parent all the same
        for target in ("2001", loose):
            for position in ("before", "after"):
                for extra in ((), ("--dry-run",)):
                    with self.subTest(target=target, position=position, dry_run=bool(extra)):
                        result = self.cli("move", "2005", "--to", target, "--position", position, *extra)
                        self.assertEqual((result.code, result.out), (1, ""))
                        self.assertIn(f"Page {target} is at the top level of its space", result.err)
                        self.assertIn("--position append", result.err)
        self.assertEqual(self.sent_writes(), [])
        self.assertEqual(self.cli("move", "2005", "--to", "2001", "--position", "append", "--dry-run").code, 0)
        self.assertEqual(self.cli("move", "2005", "--to", loose, "--position", "append", "--dry-run").code, 0)

    def test_a_folder_cannot_be_moved(self):
        result = self.cli("move", "7001", "--to", "2003")
        self.assertEqual(result.code, 1)
        self.assertIn("7001 is a folder, and the API has no call to move a folder", result.err)
        self.assertEqual(self.cli("move", "7001", "--to", "7011").code, 1)
        self.assertEqual(self.sent_writes(), [])
        self.mock.content_kinds["7101"] = "blogpost"
        self.assertIn("7101 is a blog post, which cannot be moved", self.cli("move", "7101", "--to", "2003").err)
        self.assertEqual(self.cli("move", "99999", "--to", "7001").code, 4)

    def test_a_parent_that_is_no_container_is_refused(self):
        self.mock.content_kinds["7101"] = "blogpost"
        self.assertIn("7101 is a blog post, which cannot be the target of a move", self.cli("move", "2005", "--to", "7101").err)
        self.assertEqual(self.cli("move", "2005", "--to", "99999").code, 4)

    def test_a_folder_of_another_space_is_refused(self):
        self.mock.area(StructureRoutes).add("folder", "7099", "Elsewhere", None, space_id="1002")
        result = self.cli("move", "2005", "--to", "7099")
        self.assertEqual(result.code, 1)
        self.assertIn("is not in the space of page 2005", result.err)
        self.assertEqual(self.sent_writes(), [])

    def test_a_page_cannot_be_moved_below_its_own_descendant(self):
        folder = self.mock.area(StructureRoutes).add("folder", "7090", "Below Architecture", "2003")
        self.assertEqual(folder["parentId"], "2003")
        result = self.cli("move", "2003", "--to", "7090")
        self.assertEqual(result.code, 1)
        self.assertIn("A page cannot be moved below one of its own descendants", result.err)
        self.assertEqual(self.sent_writes(), [])

    def test_the_guards_of_update_work_for_a_move_as_well(self):
        stale = self.cli("move", "2002", "--to", "7001", "--if-version", "2")
        self.assertEqual(stale.code, 3)
        self.assertIn("is at version 3, not 2", stale.err)
        old = self.cli("move", "2002", "--to", "7001", "--if-unchanged-since", "2026-10-02T00:00:00Z")
        self.assertEqual(old.code, 3)
        self.assertEqual(self.sent_writes(), [])
        fine = self.cli("move", "2002", "--to", "7001", "--if-version", "3", "--if-unchanged-since", "2026-10-30T00:00:00Z")
        self.assertEqual(fine.code, 0, fine.err)
        self.assertEqual(len(self.mock.pages["2002"]["versions"]), 4)
        self.assertEqual(self.cli("move", "2005", "--to", "2003", "--if-version", "9").code, 3)  # the v1 move has the guard too

    def test_somebody_who_saves_in_between_makes_the_move_a_conflict(self):
        self.mock.fail_next("/api/v2/pages/2005", 409, method="PUT", body={"errors": [{"status": 409, "title": "Version conflict"}]})
        result = self.cli("move", "2005", "--to", "7001")
        self.assertEqual(result.code, 3)
        self.assertEqual(self.mock.pages["2005"]["parentId"], "2001")

    def test_what_the_page_holds_goes_back_untouched(self):
        self.assertEqual(self.cli("move", "2002", "--to", "7001").code, 0)
        body = self.mock.pages["2002"]["versions"][-1]["body"]
        self.assertEqual(body, self.mock.pages["2002"]["versions"][-2]["body"])
        self.assertIn('ri:account-id="5b10ac8d82e05b22cc7d4ef5"', body)  # the mention is still a mention
        self.assertIn("alex@example.com", body)

    def test_the_people_in_the_body_are_sent_back_but_not_printed(self):
        for argv in (("move", "2002", "--to", "7001", "--dry-run", "--json"), ("move", "2002", "--to", "7001", "--dry-run")):
            result = self.cli(*argv)
            self.assertEqual(result.code, 0, result.err)
            self.assertNotIn(ACCOUNT, result.out + result.err)
            self.assertNotIn("alex@example.com", result.out + result.err)
        data = self.cli("move", "2002", "--to", "7001", "--dry-run", "--json").json()
        self.assertEqual(data["payloadRedacted"], True)
        self.assertIn('ri:account-id="hidden"', data["payload"]["body"]["value"])
        self.assertIn("The body is shown without the people and addresses that it holds", self.cli("move", "2002", "--to", "7001", "--dry-run").out)
        real = self.cli("move", "2002", "--to", "7001", "--json")
        self.assertEqual(real.code, 0, real.err)
        self.assertNotIn(ACCOUNT, real.out)
        sent = [item for item in self.mock.requests if item.method == "PUT"][0].body
        self.assertIn(ACCOUNT, sent["body"]["value"])  # what is saved is the page as it is
        self.assertIn("alex@example.com", sent["body"]["value"])

    def test_with_users_shows_the_request_as_it_is_and_the_policy_refuses_it(self):
        exact = self.cli("move", "2002", "--to", "7001", "--dry-run", "--with-users", "--json").json()
        self.assertEqual(exact["payloadRedacted"], False)
        self.assertIn(ACCOUNT, exact["payload"]["body"]["value"])
        refused = self.cli("move", "2002", "--to", "7001", "--with-users", env={"CONFLUENCE_HIDE_USERS": "true"})
        self.assertEqual(refused.code, 1)
        self.assertIn("CONFLUENCE_HIDE_USERS=true", refused.err)
        self.assertEqual(self.sent_writes(), [])
        under_the_policy = self.cli("move", "2002", "--to", "7001", "--dry-run", "--json", env={"CONFLUENCE_HIDE_USERS": "true"})
        self.assertEqual(under_the_policy.code, 0)
        self.assertEqual(under_the_policy.json()["payloadRedacted"], True)

    def test_the_title_of_the_page_is_redacted_in_the_output_of_either_kind_of_move(self):
        self.mock.pages["2005"]["title"] = "Plain alex@example.com"
        for target in ("7001", "2003"):
            data = self.cli("move", "2005", "--to", target, "--dry-run", "--json").json()
            self.assertEqual(data["title"], "Plain [email]")
        self.assertNotIn("alex@example.com", self.cli("move", "2005", "--to", "7001", "--dry-run").out)
        self.assertNotIn("alex@example.com", self.cli("move", "2005", "--to", "7001").out)
        self.assertEqual(self.mock.pages["2005"]["title"], "Plain alex@example.com")  # the title that is saved is the one that the page has

    def test_the_address_of_the_page_does_not_show_its_title(self):
        self.mock.pages["2005"]["title"] = "Plain alex@example.com"
        for target in ("7001", "2003"):
            data = self.cli("move", "2005", "--to", target, "--dry-run", "--json").json()
            self.assertTrue(data["url"].endswith("/pages/2005"), data["url"])
        shown = self.cli("move", "2005", "--to", "2003", "--dry-run", "--json", "--with-users").json()
        self.assertIn("alex%40example.com", shown["url"])  # people are shown: the address is as Confluence names it
        for target in ("7001", "2003"):
            out = self.cli("move", "2005", "--to", target).out
            self.assertNotIn("%40", out)
            self.assertIn("/pages/2005", out)

    def test_a_title_with_an_address_is_redacted_in_the_message_of_the_version(self):
        self.mock.area(StructureRoutes).items["7001"]["title"] = "Guides of alex@example.com"
        data = self.cli("move", "2005", "--to", "7001", "--dry-run", "--json").json()
        self.assertEqual(data["payload"]["version"]["message"], "Moved below Guides of [email]")
        self.assertEqual(data["target"]["title"], "Guides of [email]")
        self.assertNotIn("alex@example.com", self.cli("move", "2005", "--to", "7001", "--dry-run").out)


class ReadTheStructureTest(StructureFlow):
    def test_a_folder(self):
        page = self.below_the_folder()
        data = self.cli("folder", "7001", "--children", "--ancestors", "--all", "--json").json()
        self.assertEqual((data["id"], data["type"], data["title"], data["spaceKey"], data["parentId"]), ("7001", "folder", "Guides", "ENG", None))
        self.assertEqual((data["author"], data["owner"], data["version"]["author"]), (None, None, None))
        self.assertEqual(data["ancestors"], [])
        self.assertIn(page, [child["id"] for child in data["children"]])
        self.assertEqual(data["children"][0], {"id": "7011", "type": "folder", "title": "Runbooks", "status": "current", "position": 0})
        text = self.cli("folder", "7001", "--children").out
        self.assertTrue(text.startswith("Guides  [7001]\n"))
        self.assertIn("Type:", text)

    def test_the_children_come_in_pieces_and_with_all(self):
        for index in range(3):
            self.below_the_folder(f"Piece {index}")
        first = self.cli("folder", "7001", "--children", "--limit", "2", "--json").json()
        self.assertEqual((first["count"], bool(first["nextCursor"]), first["truncated"]), (2, True, False))
        second = self.cli("folder", "7001", "--children", "--limit", "2", "--cursor", first["nextCursor"], "--json").json()
        self.assertEqual(len(second["children"]), 2)
        everything = self.cli("folder", "7001", "--children", "--all", "--json").json()
        self.assertEqual((everything["count"], everything["nextCursor"]), (7, None))
        self.assertEqual([item["id"] for item in everything["children"]][:2], ["7011", "7021"])

    def test_the_path_names_every_kind_of_ancestor(self):
        page = self.below_the_folder()
        inside = self.mock.add_page("ENG", "Inside", "<p>x</p>", parent_id=page)
        data = self.cli("folder", "7011", "--ancestors", "--json").json()
        self.assertEqual([(item["id"], item["type"], item["title"]) for item in data["ancestors"]], [("7001", "folder", "Guides")])
        deep = self.cli("page", inside, "--ancestors", "--json").json()["ancestors"]
        self.assertEqual([item["id"] for item in deep], ["7001", page])
        self.assertEqual(deep[1]["title"], "Getting started")
        under_a_page = self.mock.area(StructureRoutes).add("folder", "7090", "Under a page", "2003")
        self.assertEqual(under_a_page["spaceId"], "1001")
        mixed = self.cli("folder", "7090", "--ancestors", "--json").json()["ancestors"]
        self.assertEqual([(item["id"], item["type"], item["title"]) for item in mixed], [("2001", "page", "Engineering Home"), ("2003", "page", "Architecture")])
        self.assertIn("Path:    Engineering Home > Architecture > Under a page", self.cli("folder", "7090", "--ancestors").out)

    def test_a_whiteboard_says_that_its_content_cannot_be_read(self):
        data = self.cli("whiteboard", "7021", "--json").json()
        self.assertEqual((data["type"], data["parentType"], data["title"]), ("whiteboard", "folder", "Architecture sketch"))
        self.assertIn("the REST API has no call that returns what a whiteboard shows", self.cli("whiteboard", "7021").out)
        self.assertIn("whiteboard", self.cli("commands", "--json").out)

    def test_a_smart_link_shows_its_address(self):
        data = self.cli("smartlink", "7061", "--json").json()
        self.assertEqual((data["type"], data["embedUrl"]), ("embed", "https://example.com/roadmap"))
        self.assertIn("Address: https://example.com/roadmap", self.cli("smartlink", "7061").out)

    def test_a_personal_link_in_a_smart_link_is_redacted_unless_people_are_shown(self):
        self.area.items["7061"]["embedUrl"] = "https://example.atlassian.net/wiki/people/5b10ac8d82e05b22cc7d4ef5"
        hidden = self.cli("smartlink", "7061", "--json").json()
        self.assertEqual(hidden["embedUrl"], "[personal link]")
        shown = self.cli("smartlink", "7061", "--json", "--with-users").json()
        self.assertIn("/people/", shown["embedUrl"])

    def test_the_fields_the_views_and_the_entries_of_a_database(self):
        fields = self.cli("database", "7041", "--fields", "--all", "--json").json()
        self.assertEqual([(item["id"], item["type"]) for item in fields["fields"]], [("name", "text"), ("tier", "select"), ("owner", "user"), ("active", "checkbox"), ("docs", "hyperlink")])
        self.assertEqual(fields["fields"][1]["options"], ["Gold", "Silver", "Bronze"])
        views = self.cli("database", "7041", "--views", "--json").json()
        self.assertEqual([(item["id"], item["type"]) for item in views["views"]], [("view-all", "table"), ("view-tier", "board")])
        entries = self.cli("database", "7041", "--entries", "--all", "--json").json()
        self.assertEqual([column["name"] for column in entries["columns"]], ["Name", "Tier", "Owner", "Active", "Docs"])
        first, second, third = entries["entries"]
        self.assertEqual(first["values"], {"name": "Billing", "tier": ["Gold"], "owner": ["[hidden]"], "active": True, "docs": [{"url": "https://example.com/billing", "label": "Billing docs"}]})
        self.assertEqual((second["values"]["owner"], second["values"]["active"], second["values"]["docs"]), (None, False, None))
        self.assertEqual((third["values"]["name"], third["values"]["owner"]), ("Contact [email]", []))  # the address in a cell is redacted
        self.assertNotIn("alex@example.com", json.dumps(entries))
        self.assertNotIn(ACCOUNT, json.dumps(entries))

    def test_the_people_in_a_cell_are_named_only_with_with_users(self):
        named = self.cli("database", "7041", "--entries", "--all", "--with-users", "--json").json()
        self.assertEqual(named["entries"][0]["values"]["owner"], [{"accountId": ACCOUNT, "displayName": "Alex Example", "email": "alex@example.com"}])
        self.assertIn("alex@example.com", json.dumps(named))  # people are shown, so the text of a cell is not redacted either
        self.assertEqual(named["author"]["accountId"], ACCOUNT)
        refused = self.cli("database", "7041", "--entries", "--with-users", env={"CONFLUENCE_HIDE_USERS": "true"})
        self.assertEqual(refused.code, 1)
        self.assertIn("CONFLUENCE_HIDE_USERS=true", refused.err)

    def test_the_pages_of_a_list_of_entries_continue_with_the_cursor(self):
        first = self.cli("database", "7041", "--entries", "--limit", "2", "--json").json()
        self.assertEqual((len(first["entries"]), first["nextCursor"]), (2, "2"))
        second = self.cli("database", "7041", "--entries", "--limit", "2", "--cursor", "2", "--json").json()
        self.assertEqual(([entry["id"] for entry in second["entries"]], second["nextCursor"]), (["7053"], None))
        text = self.cli("database", "7041", "--entries", "--limit", "2")
        self.assertIn("More entries follow. Continue with --cursor 2", text.err)

    def test_the_text_of_the_entries_is_a_table_with_the_names_of_the_fields(self):
        lines = self.cli("database", "7041", "--entries", "--all").out.splitlines()
        header = next(line for line in lines if line.startswith("ID"))
        self.assertEqual(header.split(), ["ID", "Name", "Tier", "Owner", "Active", "Docs"])
        self.assertIn("Billing", self.cli("database", "7041", "--entries", "--all", "--format", "tsv", "--select", "id,values.name").out)

    def test_one_list_at_a_time_and_a_list_for_every_option_that_needs_one(self):
        self.assertEqual(self.cli("database", "7041", "--fields", "--views").code, 2)
        self.assertIn("one list at a time", self.cli("database", "7041", "--fields", "--entries").err)
        for argv in (("folder", "7001", "--cursor", "2"), ("folder", "7001", "--all"), ("folder", "7001", "--select", "id"), ("folder", "7001", "--format", "tsv")):
            with self.subTest(argv=argv):
                self.assertEqual(self.cli(*argv).code, 2)
        self.assertEqual(self.cli("folder", "7001", "--children", "--limit", "0").code, 2)
        self.assertEqual(self.cli("folder", "7001", "--fields").code, 2)  # a folder has no fields: the option does not exist
        self.assertEqual(self.cli("database", "7041", "--children", "--json", "--format", "md").code, 2)

    def test_nothing_is_written_by_reading(self):
        for argv in (("folder", "7001", "--children"), ("database", "7041", "--entries"), ("tree", "7001"), ("whiteboard", "7021", "--ancestors")):
            self.cli(*argv)
        self.assertEqual([item for item in self.mock.requests if item.method != "GET" and item.path != "/api/v2/content/convert-ids-to-types"], [])

    def test_the_mock_knows_nothing_that_the_document_does_not_list(self):
        self.cli("folder", "7001", "--children", "--ancestors")
        self.cli("database", "7041", "--entries", "--all")
        self.cli("tree", "7041")
        self.cli("folder-create", "--title", "Checked", "--space", "ENG", "--parent", "7001")
        self.assertEqual(self.mock.unknown_endpoints, [])
        self.assertEqual(self.mock.deprecated_endpoints, [])


class CreateFoldersAndSmartLinksTest(StructureFlow):
    def test_a_folder_is_created_below_a_page_and_below_a_folder(self):
        first = self.cli("folder-create", "--title", "Runbooks 2026", "--space", "ENG", "--parent", "2003", "--json")
        self.assertEqual(first.code, 0, first.err)
        data = first.json()
        self.assertEqual((data["action"], data["dryRun"], data["parentType"], data["spaceKey"]), ("created", False, "page", "ENG"))
        self.assertTrue(data["folderId"].startswith("70"))
        second = self.cli("folder-create", "--title", "Nested", "--space", "ENG", "--parent", data["folderId"], "--json").json()
        self.assertEqual((second["parentId"], second["parentType"], second["parent"]["title"]), (data["folderId"], "folder", "Runbooks 2026"))
        self.assertEqual(self.cli("folder", second["folderId"], "--ancestors", "--json").json()["ancestors"][-1]["id"], data["folderId"])
        text = self.cli("folder-create", "--title", "Plain", "--space", "ENG").out
        self.assertRegex(text, r"^Created folder 70\d\d: Plain\n")

    def test_the_dry_run_proves_the_parent_and_sends_nothing(self):
        data = self.cli("folder-create", "--title", "Preview", "--space", "ENG", "--parent", "7001", "--dry-run", "--json").json()
        self.assertEqual((data["dryRun"], data["folderId"], data["url"]), (True, None, None))
        self.assertEqual(data["payload"], {"spaceId": "1001", "title": "Preview", "parentId": "7001"})
        self.assertEqual(self.sent_writes(), [])
        self.assertEqual(self.cli("folder-create", "--title", "Preview", "--space", "ENG", "--parent", "99999", "--dry-run").code, 4)
        self.assertIn("would be created below the folder 'Guides' [7001]", self.cli("folder-create", "--title", "Preview", "--space", "ENG", "--parent", "7001", "--dry-run").out)

    def test_two_folders_may_have_one_title(self):
        one = self.cli("folder-create", "--title", "Twin", "--space", "ENG", "--json").json()["folderId"]
        two = self.cli("folder-create", "--title", "Twin", "--space", "ENG", "--json").json()["folderId"]
        self.assertNotEqual(one, two)
        self.assertEqual(self.cli("folder-create", "--title", "Twin", "--space", "ENG", "--dry-run").code, 0)

    def test_the_title_and_the_space_are_checked(self):
        self.assertEqual(self.cli("folder-create", "--title", "  ", "--space", "ENG").code, 1)
        self.assertEqual(self.cli("folder-create", "--title", "a\nb", "--space", "ENG").code, 1)
        self.assertEqual(self.cli("folder-create", "--title", "x" * 256, "--space", "ENG").code, 1)
        self.assertEqual(self.cli("folder-create", "--title", "No space").code, 2)
        self.assertEqual(self.cli("folder-create", "--title", "Wrong space", "--space", "NOPE").code, 4)
        self.assertEqual(self.cli("folder-create", "--space", "ENG").code, 2)
        self.assertEqual(self.sent_writes(), [])

    def test_a_folder_in_the_current_space(self):
        self.assertEqual(self.cli("use", "ENG").code, 0)
        self.assertEqual(self.cli("folder-create", "--title", "Here", "--json").json()["spaceKey"], "ENG")

    def test_a_smart_link_is_created_with_its_address_as_given(self):
        data = self.cli("smartlink-create", "--url", "https://example.com/Road%20map?x=1&y=2#top", "--title", "Roadmap", "--space", "ENG", "--parent", "7001", "--json").json()
        self.assertEqual((data["embedUrl"], data["parentType"]), ("https://example.com/Road%20map?x=1&y=2#top", "folder"))
        self.assertEqual(data["payload"]["embedUrl"], data["embedUrl"])
        shown = self.cli("smartlink", data["smartlinkId"], "--json").json()
        self.assertEqual((shown["type"], shown["embedUrl"], shown["parentType"]), ("embed", data["embedUrl"], "folder"))
        text = self.cli("smartlink-create", "--url", "https://example.com/x", "--title", "Plain", "--space", "ENG", "--dry-run").out
        self.assertIn('"embedUrl": "https://example.com/x"', text)

    def test_an_address_that_is_not_fit_is_refused_before_anything_is_sent(self):
        for url in ("ftp://example.com/x", "example.com/x", "https://user:secret@example.com/x", "https://example.com/a b", "https://example.com/\x07", "https://", "javascript:alert(1)", "https://example.com/" + "a" * 2100, "https://exa\u200bmple.com", ""):
            with self.subTest(url=url[:40]):
                result = self.cli("smartlink-create", "--url", url, "--title", "Bad", "--space", "ENG")
                self.assertEqual(result.code, 1, result.err)
                self.assertNotIn("secret", result.err)
        self.assertEqual(self.sent_writes(), [])
        self.assertEqual(self.mock.requests, [])  # not even a read: the address is judged first

    def test_the_mock_refuses_a_parent_in_another_space(self):
        self.area.add("folder", "7099", "Elsewhere", None, space_id="1002")
        result = self.cli("folder-create", "--title", "Wrong space", "--space", "ENG", "--parent", "7099")
        self.assertEqual(result.code, 1)
        self.assertIn("The parent folder 7099 is not in space ENG", result.err)


class EmptyOptionsTest(StructureFlow):
    """An option that was given and is empty is a mistake: nothing is asked of Confluence, and nothing is made in the space or at the place that it
    would have fallen back to."""

    def test_no_writer_takes_an_empty_space_or_parent_for_none(self):
        folder = self.work()
        (folder / "a.md").write_text("# From a file\n\nText.\n", encoding="utf-8")
        (folder / "md").mkdir()
        (folder / "md" / "a.md").write_text("# Page a\n\nText.\n", encoding="utf-8")
        commands = (
            ("create", "--title", "New", "--body", "Text."),
            ("folder-create", "--title", "New"),
            ("smartlink-create", "--title", "New", "--url", "https://example.com/new"),
            ("import-md", str(folder / "a.md")),
            ("import-md-dir", str(folder / "md")),
        )
        pages, containers = dict(self.mock.pages), dict(self.area.items)
        for command in commands:
            for options, message in ((("--space", ""), "The space is empty."), (("--space", "ENG", "--parent", ""), "The parent is empty.")):
                for extra in ((), ("--dry-run",)):
                    with self.subTest(command=command[0], options=options, dry_run=bool(extra)):
                        result = self.cli(*command, *options, *extra, env={"CONFLUENCE_SPACE": "DOCS"})
                        self.assertEqual((result.code, result.out), (2, ""))
                        self.assertIn(message, result.err)
        self.assertEqual(self.mock.requests, [])  # not even a read
        self.assertEqual((self.mock.pages, self.area.items), (pages, containers))

    def test_none_given_is_still_the_current_space_and_the_default_place(self):
        data = self.cli("folder-create", "--title", "Here", "--dry-run", "--json", env={"CONFLUENCE_SPACE": "DOCS"}).json()
        self.assertEqual((data["spaceKey"], data["parentId"]), ("DOCS", None))

    def test_export_takes_no_empty_page_or_space_for_none_and_writes_nothing(self):
        target = self.work() / "export"
        for argv, message in (
            (("--page", ""), "The page is empty."),  # it would have exported the whole current space
            (("--page", "  "), "The page is empty."),
            (("--space", ""), "The space is empty."),
            (("--space", "  "), "The space is empty."),
        ):
            for extra in ((), ("--dry-run",)):
                with self.subTest(argv=argv, dry_run=bool(extra)):
                    result = self.cli("export", *argv, "--out", str(target), *extra, env={"CONFLUENCE_SPACE": "DOCS"})
                    self.assertEqual((result.code, result.out), (2, ""))
                    self.assertIn(message, result.err)
        self.assertEqual(self.mock.requests, [])  # not even a read
        self.assertFalse(target.exists())  # and nothing was written
        done = self.cli("export", "--out", str(target), "--dry-run", "--json", env={"CONFLUENCE_SPACE": "DOCS"}).json()
        self.assertEqual((done["space"], done["root"]), ("DOCS", None))  # none given: the current space

    def test_tree_takes_no_empty_space_for_none(self):
        for root in ("2001", "page:Architecture", "7001"):
            for blank in ("", "  "):
                with self.subTest(root=root, space=blank):
                    result = self.cli("tree", root, "--space", blank, env={"CONFLUENCE_SPACE": "DOCS"})
                    self.assertEqual((result.code, result.out), (2, ""))
                    self.assertIn("The space is empty.", result.err)
        self.assertEqual(self.mock.requests, [])
        self.assertEqual(self.cli("tree", "page:Architecture", "--depth", "1", "--json", env={"CONFLUENCE_SPACE": "ENG"}).json()["root"]["id"], "2003")


class ExportBelowAFolderTest(StructureFlow):
    def test_the_pages_below_a_folder_are_exported_and_the_folder_is_not(self):
        first = self.below_the_folder("Getting started")
        second = self.below_the_folder("Troubleshooting")
        deeper = self.mock.add_page("ENG", "Deeper", "<p>Deep text.</p>", parent_id=first)
        target = self.work() / "export"
        result = self.cli("export", "--page", "7001", "--out", str(target), "--json")
        self.assertEqual(result.code, 0, result.err)
        data = result.json()
        self.assertEqual((data["root"], data["space"], data["count"]), ("7001", "ENG", 3))
        self.assertEqual(sorted(item["id"] for item in data["pages"]), sorted([first, second, deeper]))
        self.assertTrue(any("A folder is not a page" in note for note in data["notes"]))
        by_id = {item["id"]: item for item in data["pages"]}
        self.assertEqual((by_id[first]["parentId"], by_id[first]["path"]), ("7001", "Guides"))
        self.assertEqual(by_id[deeper]["path"], "Guides > Getting started")
        written = (target / by_id[first]["file"]).read_text(encoding="utf-8")
        self.assertIn("parent: 7001", written)  # export writes the id of whatever the parent is
        self.assertIn("path: Guides", written)

    def test_an_export_below_a_folder_can_be_imported_below_that_folder_again(self):
        first = self.below_the_folder("Getting started")
        target = self.work() / "export"
        self.assertEqual(self.cli("export", "--page", "7001", "--out", str(target)).code, 0)
        again = self.cli("import-md-dir", str(target), "--space", "ENG", "--dry-run", "--json").json()
        self.assertEqual((again["created"], again["updated"], again["unchanged"], again["failed"]), (0, 0, 1, 0))
        self.assertEqual(self.mock.pages[first]["parentId"], "7001")

    def test_the_path_names_a_folder_between_two_pages(self):
        under_a_page = self.mock.area(StructureRoutes).add("folder", "7090", "Archive", "2003")
        self.assertEqual(under_a_page["parentId"], "2003")
        self.mock.add_page("ENG", "Old notes", "<p>Old.</p>", parent_id="7090")
        target = self.work() / "export"
        data = self.cli("export", "--page", "2003", "--out", str(target), "--json").json()
        paths = {item["title"]: item["path"] for item in data["pages"]}
        self.assertEqual(paths["Old notes"], "Engineering Home > Architecture > Archive")

    def test_a_whiteboard_a_database_and_a_smart_link_may_be_the_root_too(self):
        for root, noun in (("7021", "A whiteboard"), ("7041", "A database"), ("7061", "A smart link")):
            with self.subTest(root=root):
                result = self.cli("export", "--page", root, "--out", str(self.work() / "x"), "--dry-run")
                self.assertEqual(result.code, 1)
                self.assertIn("There are no pages to export.", result.err)
        self.assertEqual(self.cli("export", "--page", "99999", "--out", str(self.work() / "y")).code, 4)

    def test_a_page_root_is_exported_as_it_was(self):
        data = self.cli("export", "--page", "2003", "--out", str(self.work() / "page"), "--json").json()
        self.assertEqual((data["root"], data["count"], data["notes"]), ("2003", 2, []))
        self.assertEqual({item["path"] for item in data["pages"]}, {"Engineering Home", "Engineering Home > Architecture"})

    def test_the_address_in_the_front_matter_does_not_show_the_title(self):
        self.mock.pages["2005"]["title"] = "Plain alex@example.com"
        target = self.work() / "export"
        data = self.cli("export", "--page", "2005", "--out", str(target), "--json").json()
        written = (target / {item["id"]: item for item in data["pages"]}["2005"]["file"]).read_text(encoding="utf-8")
        self.assertIn("title: Plain [email]", written)
        self.assertNotIn("alex", written)
        self.assertRegex(written, r"(?m)^url: \S+/pages/2005$")


PERSONAL = f"~{ACCOUNT}"


class PersonalSpaceTest(StructureFlow):
    """A personal space is keyed by `~` and the account id of its owner: neither the files that `export` writes nor what the commands print has them
    (the requests do: Confluence is asked for the space by the key that was typed)."""

    def setUp(self):
        super().setUp()
        self.space_id = self.mock.add_space(PERSONAL, "Alex Example", "personal")
        self.home = self.mock.spaces[self.space_id]["homepageId"]
        self.page = self.mock.add_page(PERSONAL, "Notes", "<p>Notes.</p>", versions=2)
        self.folder = self.area.add("folder", "7071", "Archive", self.home, space_id=self.space_id)["id"]  # not among the ids that the mock hands out (7090 to 7099)
        self.below = self.mock.add_page(PERSONAL, "Old notes", "<p>Old.</p>", parent_id=self.folder)

    @staticmethod
    def written(directory):
        return {path.name: path.read_text(encoding="utf-8") for path in sorted(directory.rglob("*")) if path.is_file()}  # the order of a folder is the system's: Linux has none

    def test_an_export_writes_no_key_and_no_account_id_whoever_typed_the_key(self):
        for options in (("--space", PERSONAL), ("--page", self.home), ("--page", self.page), ("--page", self.folder)):
            with self.subTest(options=options):
                target = self.work() / "export"
                result = self.cli("export", *options, "--out", str(target), "--json")
                self.assertEqual(result.code, 0, result.err)
                self.assertNotIn(ACCOUNT, result.out + result.err)
                self.assertEqual(result.json()["space"], "[hidden]")
                files = self.written(target)
                self.assertGreater(len(files), 1)
                for name, content in files.items():
                    self.assertNotIn(ACCOUNT, name + content)
                    self.assertNotIn("~", name)
                self.assertEqual(json.loads(files["index.json"])["space"], "[hidden]")

    def test_the_front_matter_has_no_key_and_an_address_that_names_the_page_by_its_id(self):
        target = self.work() / "export"
        data = self.cli("export", "--page", self.page, "--out", str(target), "--json").json()
        written = (target / {item["id"]: item for item in data["pages"]}[self.page]["file"]).read_text(encoding="utf-8")
        self.assertRegex(written, r"(?m)^space: \[hidden\]$")
        self.assertRegex(written, rf"(?m)^url: \S+/pages/viewpage\.action\?pageId={self.page}$")
        elsewhere = self.work() / "other"
        self.cli("export", "--page", "2003", "--out", str(elsewhere))
        pages = {name: text for name, text in self.written(elsewhere).items() if name.endswith(".md")}  # the index is no page
        self.assertEqual(sorted(pages), ["adr-0001-2004.md", "architecture-2003.md"])
        for text in pages.values():
            self.assertRegex(text, r"(?m)^space: ENG$")

    def test_the_request_names_the_space_by_the_key_that_was_typed(self):
        self.cli("export", "--space", PERSONAL, "--out", str(self.work() / "export"))
        asked = [item for item in self.mock.requests if item.path == "/api/v2/spaces"]
        self.assertEqual([item.query.get("keys") for item in asked], [[PERSONAL]])

    def test_an_exported_file_can_be_imported_again(self):
        target = self.work() / "export"
        self.assertEqual(self.cli("export", "--space", PERSONAL, "--out", str(target)).code, 0)
        again = self.cli("import-md-dir", str(target), "--dry-run", "--json")
        self.assertEqual(again.code, 0, again.err)
        self.assertEqual([again.json()[key] for key in ("created", "updated", "unchanged", "failed")], [0, 0, 3, 0])  # the pages are found by their ids

    def test_a_file_that_says_no_more_of_its_space_than_hidden_takes_the_space_of_the_option(self):
        folder = self.work()
        (folder / "new.md").write_text("---\ntitle: Fresh\nspace: [hidden]\n---\nText.\n", encoding="utf-8")
        named = self.cli("import-md", str(folder / "new.md"), "--space", PERSONAL, "--dry-run", "--json")
        self.assertEqual((named.code, named.json()["action"]), (0, "created"), named.err)
        self.assertNotIn(ACCOUNT, named.out + named.err)
        alone = self.cli("import-md", str(folder / "new.md"), "--dry-run")
        self.assertEqual(alone.code, 1)
        self.assertIn("has no space and no current space is selected", alone.err)

    def test_no_command_prints_the_key_or_the_account_id(self):
        runs = (
            ("tree", self.page),
            ("tree", self.folder, "--json"),
            ("tree", self.home, "--json"),
            ("folder", self.folder),
            ("folder", self.folder, "--json"),
            ("folder", self.folder, "--children", "--ancestors", "--json"),
            ("folder-create", "--title", "Top", "--space", PERSONAL, "--dry-run", "--json"),
            ("folder-create", "--title", "Top", "--space", PERSONAL, "--json"),
            ("folder-create", "--title", "Elsewhere", "--space", PERSONAL, "--parent", "7001"),
            ("smartlink-create", "--url", "https://example.com/x", "--title", "Link", "--space", PERSONAL, "--parent", self.folder),
            ("create", "--title", "New", "--space", PERSONAL, "--parent", self.folder, "--body", "Text."),
            ("create", "--title", "New", "--space", PERSONAL, "--parent", self.folder, "--body", "Text.", "--json"),
            ("create", "--title", "Notes", "--space", PERSONAL, "--body", "Text."),  # the title is taken
            ("move", self.page, "--to", self.folder, "--dry-run", "--json"),
            ("move", self.page, "--to", self.folder),
            ("move", self.below, "--to", self.page, "--json"),
            ("move", self.below, "--to", self.page),
            ("update", self.page, "--title", "Renamed"),
            ("update", self.page, "--title", "Renamed again", "--json"),
            ("restore", self.page, "--version", "1", "--dry-run", "--json"),
            ("restore", self.page, "--version", "1", "--json"),
            ("restore", self.page, "--version", "2"),
        )
        for env in ({}, {"CONFLUENCE_HIDE_USERS": "true"}):
            for argv in runs:
                with self.subTest(argv=argv, env=env):
                    result = self.cli(*argv, env=env)
                    self.assertNotIn(ACCOUNT, result.out + result.err)

    def test_what_is_printed_in_the_place_of_the_key_and_of_the_address(self):
        base = self.mock.base_url
        folder = self.cli("folder", self.folder, "--json").json()
        self.assertEqual((folder["spaceKey"], folder["url"]), ("[hidden]", f"{base}/spaces/[hidden]/folder/{self.folder}"))
        self.assertEqual(self.cli("tree", self.folder, "--json").json()["root"]["spaceKey"], "[hidden]")
        moved = self.cli("move", self.page, "--to", self.folder, "--json").json()
        self.assertTrue(moved["url"].endswith(f"/pages/viewpage.action?pageId={self.page}"), moved["url"])
        made = self.cli("folder-create", "--title", "Top", "--space", PERSONAL, "--json").json()
        self.assertEqual(made["spaceKey"], "[hidden]")
        self.assertIn("/spaces/[hidden]/folder/", made["url"])
        restored = self.cli("restore", self.page, "--version", "1", "--dry-run", "--json")
        self.assertEqual(restored.code, 0, restored.err)
        self.assertTrue(restored.json()["url"].endswith(f"/pages/viewpage.action?pageId={self.page}"), restored.json()["url"])

    def test_with_users_shows_what_confluence_names(self):
        base = self.mock.base_url
        folder = self.cli("folder", self.folder, "--with-users", "--json").json()
        self.assertEqual((folder["spaceKey"], folder["url"]), (PERSONAL, f"{base}/spaces/{PERSONAL}/folder/{self.folder}"))
        moved = self.cli("move", self.page, "--to", self.folder, "--with-users", "--json").json()
        self.assertIn(f"/spaces/{PERSONAL}/pages/{self.page}/", moved["url"])
        refused = self.cli("folder", self.folder, "--with-users", env={"CONFLUENCE_HIDE_USERS": "true"})
        self.assertEqual(refused.code, 1)
        self.assertNotIn(ACCOUNT, refused.out + refused.err)


class GatewayTest(unittest.TestCase):
    """The real adapter against the mock: what is asked for, in what form, and what the mock refuses."""

    def setUp(self):
        from conflu_c_cli.adapters.driven.confluence_rest import RestConfluenceGateway
        from conflu_c_cli.adapters.driven.http_transport import HttpTransport
        from conflu_c_cli.application.settings import Settings
        from tests.support.mock_confluence import MockConfluence

        self.mock = MockConfluence()
        self.mock.start()
        self.addCleanup(self.mock.stop)
        settings = Settings(base_url=self.mock.base_url, email=self.mock.email, api_token=self.mock.token, retry=0, connect_timeout=5.0, max_time=10.0)
        transport = HttpTransport(settings)
        self.addCleanup(transport.close)
        self.gateway = RestConfluenceGateway(settings, transport)

    def asked(self):
        return [(item.method, item.path, {key: values for key, values in item.query.items()}) for item in self.mock.requests]

    def test_each_kind_has_its_own_collection(self):
        for kind, collection, content_id in (("folder", "folders", "7001"), ("whiteboard", "whiteboards", "7021"), ("database", "databases", "7041"), ("embed", "embeds", "7061")):
            with self.subTest(kind=kind):
                found = self.gateway.get_container(kind, content_id)
                self.assertEqual((found.id, found.type, found.space_key, found.parent_type), (content_id, kind, "ENG", "" if content_id == "7001" else "folder"))
                self.assertIn(("GET", f"/api/v2/{collection}/{content_id}", {}), self.asked())
        self.assertEqual(self.mock.unknown_endpoints, [])

    def test_an_id_of_another_kind_is_not_found(self):
        for kind, content_id in (("folder", "7021"), ("whiteboard", "7001"), ("database", "2002"), ("embed", "99999")):
            with self.subTest(kind=kind), self.assertRaises(NotFoundError):
                self.gateway.get_container(kind, content_id)

    def test_what_holds_no_other_content_is_a_bug_not_a_request(self):
        for kind in ("blogpost", "hologram", ""):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.gateway.get_container(kind, "7101")
            with self.assertRaises(ValueError):
                self.gateway.list_children(kind, "7101")
        self.assertEqual(self.mock.requests, [])
    def test_the_children_the_descendants_and_the_ancestors(self):
        first = self.gateway.list_children("folder", "7001", limit=3)
        self.assertEqual(([node.id for node in first.items], first.cursor), (["7011", "7021"], "2"))  # the mock hands out two at a time
        second = self.gateway.list_children("folder", "7001", limit=3, cursor=first.cursor)
        self.assertEqual(([(node.id, node.type, node.parent_id, node.depth) for node in second.items], second.cursor), ([("7041", "database", "7001", 1), ("7061", "embed", "7001", 1)], ""))
        deep = self.gateway.list_container_descendants("folder", "7001", depth=2, limit=250)
        self.assertEqual([(node.id, node.depth) for node in deep.items], [("7011", 1), ("7021", 1)])
        self.assertEqual(self.gateway.list_container_ancestors("folder", "7011"), [PageRef("7001", "", "folder")])  # an ancestor has an id and a type
        self.assertEqual(self.gateway.list_container_ancestors("embed", "7061")[0].type, "folder")
        queries = {path: query for _, path, query in self.asked()}
        self.assertEqual(queries["/api/v2/folders/7001/direct-children"]["limit"], ["3"])
        self.assertEqual(queries["/api/v2/folders/7001/descendants"], {"depth": ["2"], "limit": ["250"]})
        self.assertEqual(queries["/api/v2/folders/7011/ancestors"], {"limit": ["250"]})

    def test_a_page_below_a_container_is_in_the_answers_of_both_apis_collections(self):
        page = self.mock.add_page("ENG", "Below", "<p>x</p>", parent_id="7021")
        self.assertEqual([node.id for node in self.gateway.list_children("whiteboard", "7021").items], [page])
        self.assertEqual(self.gateway.list_container_ancestors("whiteboard", "7021"), [PageRef("7001", "", "folder")])
        shown = self.gateway.get_page(page)
        self.assertEqual((shown.parent_id, shown.parent_type), ("7021", "whiteboard"))
        self.assertEqual([ref.id for ref in self.gateway.list_ancestors(page)], ["7001", "7021"])
        self.assertEqual([(ref.id, ref.type) for ref in self.gateway.list_ancestors(page)], [("7001", "folder"), ("7021", "whiteboard")])

    def test_what_is_created_is_sent_as_it_is_and_known_afterwards(self):
        payload = {"spaceId": "1001", "title": "Runbooks 2026", "parentId": "7001"}
        made = self.gateway.create_folder(payload)
        self.assertEqual((made.type, made.title, made.parent_id, made.parent_type, made.space_key, made.version_number), ("folder", "Runbooks 2026", "7001", "folder", "ENG", 1))
        sent = [item for item in self.mock.requests if item.method == "POST" and item.path == "/api/v2/folders"]
        self.assertEqual([item.body for item in sent], [payload])
        self.assertEqual(self.gateway.content_types([made.id]), {made.id: "folder"})
        link = self.gateway.create_smartlink({"spaceId": "1001", "title": "Roadmap", "embedUrl": "https://example.com/x"})
        self.assertEqual((link.type, link.embed_url, link.parent_id), ("embed", "https://example.com/x", ""))
        self.assertEqual(self.gateway.get_container("embed", link.id).embed_url, "https://example.com/x")

    def test_the_mock_refuses_what_confluence_refuses(self):
        for payload in (
            {"title": "No space"},
            {"spaceId": 1001, "title": "A number"},
            {"spaceId": "9999", "title": "Unknown space"},
            {"spaceId": "1001", "title": ""},
            {"spaceId": "1001", "title": "Unknown parent", "parentId": "99999"},
            {"spaceId": "1001", "title": "Parent of another space", "parentId": "3001"},
        ):
            with self.subTest(payload=payload), self.assertRaises(RejectedError):
                self.gateway.create_folder(payload)
        with self.assertRaises(RejectedError):
            self.gateway.create_smartlink({"spaceId": "1001", "title": "No address"})
        with self.assertRaises(RejectedError):
            self.gateway.create_smartlink({"spaceId": "1001", "title": "Bad address", "embedUrl": "ftp://example.com"})

    def test_the_mock_has_ten_ids_for_what_it_is_asked_to_create(self):
        for number in range(10):
            self.gateway.create_folder({"spaceId": "1001", "title": f"Folder {number}"})
        with self.assertRaises(ConfluCliError):
            self.gateway.create_folder({"spaceId": "1001", "title": "One too many"})

    def test_the_lists_of_a_database_use_the_pagination_of_its_api(self):
        first = self.gateway.list_database_entries("7041", limit=3)
        self.assertEqual(([entry.id for entry in first.items], first.cursor), (["7051", "7052"], "2"))
        second = self.gateway.list_database_entries("7041", limit=3, cursor=first.cursor)
        self.assertEqual(([entry.id for entry in second.items], second.cursor), (["7053"], ""))  # meta.hasMore says it is the last
        self.assertEqual(first.items[0].values["tier"], FieldValue("select", ["Gold"]))
        fields = self.gateway.list_database_fields("7041", limit=250)
        self.assertEqual([item.id for item in fields.items], ["name", "tier"])
        views = self.gateway.list_database_views("7041")
        self.assertEqual([item.id for item in views.items], ["view-all", "view-tier"])
        queries = {path: query for _, path, query in self.asked() if "limit" in query or "cursor" in query}
        self.assertEqual(queries["/api/v2/databases/7041/entries"], {"limit": ["3"], "cursor": ["2"]})
        with self.assertRaises(NotFoundError):
            self.gateway.list_database_fields("7001")  # a folder has no fields

    def test_what_the_document_does_not_list_is_refused_by_the_mock(self):
        with self.assertRaises(NotFoundError):
            self.gateway._call("GET", "/api/v2/folders/7001/fields")
        self.assertEqual(self.mock.unknown_endpoints, ["GET /api/v2/folders/7001/fields (v2 document)"])


class ChildProcessTest(StructureFlow):
    def test_the_real_program_reads_a_folder_and_creates_below_it(self):
        read = self.child("folder", "7001", "--json")
        self.assertEqual(read.code, 0, read.err)
        self.assertEqual(json.loads(read.out)["type"], "folder")
        made = self.child("create", "--parent", "7001", "--title", "From a child", "--space", "ENG", "--body", "x", "--json")
        self.assertEqual(made.code, 0, made.err)
        self.assertEqual(json.loads(made.out)["parentType"], "folder")
        self.assertEqual(self.child("folder", "2002").code, 4)


if __name__ == "__main__":
    unittest.main()
