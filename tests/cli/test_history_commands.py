"""The commands of the history area on the command line, with the in-memory Confluence: `page` for an earlier version, for several pages and with its files, `diff` and `restore`."""
import json
import unittest

from conflu_c_cli.adapters.driving.cli.commands.pages import ATTACHMENT_NAMES, RULE
from conflu_c_cli.adapters.driving.cli.registry import find_command
from conflu_c_cli.domain.errors import UnavailableError
from conflu_c_cli.domain.model import Attachment, User, VersionInfo
from tests.support.cli import run_cli
from tests.support.fakes import ACCOUNT, BASE, FakeGateway, default_settings
from tests.support.fakes_history import SECOND_BODY


class DescriptionTest(unittest.TestCase):
    def test_diff_reads_and_restore_changes_the_page_without_losing_anything(self):
        diff, restore = find_command("diff"), find_command("restore")
        self.assertEqual((diff.group, diff.writes, diff.destructive, diff.json_output), ("Read", False, False, True))
        self.assertEqual((restore.group, restore.writes, restore.destructive, restore.idempotent, restore.json_output), ("Work on a page", True, True, False, True))
        self.assertTrue(any("--dry-run" in arg.names for arg in restore.args))
        self.assertFalse(any("--dry-run" in arg.names for arg in diff.args))
        for command in (diff, restore):
            self.assertTrue(command.when and command.description and command.output and command.examples, command.name)
            self.assertFalse(command.for_person or command.local, command.name)

    def test_the_options_of_the_two_are_what_the_brief_names(self):
        diff = {arg.names: arg for arg in find_command("diff").args}
        self.assertIn(("--from-version", "--from"), diff)
        self.assertIn(("--to-version", "--to"), diff)
        self.assertEqual({names[0] for names in diff}, {"ref", "--from-version", "--to-version", "--context", "--max-chars"})
        restore = {arg.names[0]: arg for arg in find_command("restore").args}
        self.assertEqual(set(restore), {"ref", "--version", "--message", "--restore-title", "--if-version", "--if-unchanged-since", "--dry-run"})
        self.assertTrue(restore["--version"].required)
        self.assertEqual(restore["--version"].kind, "int")

    def test_page_takes_several_pages_and_the_two_new_options(self):
        page = find_command("page")
        by_name = {arg.names[0]: arg for arg in page.args}
        self.assertEqual((by_name["ref"].kind, by_name["ref"].required), ("list", True))
        self.assertEqual((by_name["--version"].kind, by_name["--attachments"].kind), ("int", "flag"))
        self.assertIn("PAGE...", page.usage())

    def test_the_catalog_and_the_help_know_them(self):
        catalog = {item["name"]: item for item in run_cli("commands", "--json").json()["commands"]}
        self.assertFalse(catalog["diff"]["changesData"])
        self.assertTrue(catalog["restore"]["changesData"])
        self.assertIn("sourceIdentical", catalog["diff"]["jsonOutput"])
        self.assertIn("restoredVersion", catalog["restore"]["jsonOutput"])
        for name in ("diff", "restore", "page"):
            result = run_cli("help", name)
            self.assertEqual(result.code, 0, result.err)
            self.assertIn("Examples", result.out)


class PageVersionTest(unittest.TestCase):
    def test_an_earlier_version_as_text(self):
        result = run_cli("page", "2002", "--version", "1")
        self.assertEqual(result.code, 0, result.err)
        lines = result.out.splitlines()
        self.assertEqual(lines[0], "Release notes (draft)  [2002]")
        self.assertIn("Version: 1 (an earlier version; the current one is 3)", lines)
        self.assertIn("Labels:  release, notes", lines)  # the labels are the page's
        self.assertIn("# Release notes", lines)
        self.assertIn("Draft.", lines)
        self.assertNotIn("Contact", result.out)

    def test_the_current_version_asked_for_by_number_says_that_it_is(self):
        self.assertIn("Version: 3 (the current version)", run_cli("page", "2002", "--version", "3").out)
        self.assertFalse(run_cli("page", "2002", "--version", "2", "--json").json()["version"]["current"] is True)
        self.assertTrue(run_cli("page", "2002", "--version", "3", "--json").json()["version"]["current"])

    def test_an_earlier_version_as_json(self):
        data = run_cli("page", "2002", "--version", "2", "--json").json()
        self.assertEqual(data["version"], {"number": 2, "created": "2026-10-05T10:00:00.000Z", "message": "", "minorEdit": False, "author": None, "current": False})
        self.assertEqual((data["currentVersion"], data["updated"], data["labels"]), (3, "2026-10-05T10:00:00.000Z", ["release", "notes"]))
        self.assertEqual(data["body"]["value"], "# Release notes\n\nContact @user.\n\n- First")
        self.assertEqual(data["body"]["dropped"], ["mention"])
        self.assertNotIn("ancestors", data)
        self.assertNotIn("comments", data)
        self.assertNotIn(ACCOUNT, json.dumps(data))

    def test_an_ordinary_page_has_no_current_flag_and_no_current_version(self):
        data = run_cli("page", "2002", "--json").json()
        self.assertNotIn("current", data["version"])
        self.assertNotIn("currentVersion", data)
        self.assertNotIn("attachments", data)
        self.assertNotIn("attachmentTotal", data)

    def test_the_options_that_shape_a_body_work_on_a_version(self):
        outline = run_cli("page", "2002", "--version", "3", "--outline", "--json").json()
        self.assertEqual([item["title"] for item in outline["outline"]], ["Release notes"])
        section = run_cli("page", "2002", "--version", "1", "--section", "release", "--json").json()
        self.assertEqual((section["body"]["section"], section["body"]["value"]), ("Release notes", "# Release notes\n\nDraft."))
        self.assertTrue(run_cli("page", "2002", "--version", "2", "--max-chars", "10", "--json").json()["body"]["truncated"])
        self.assertIsNone(run_cli("page", "2002", "--version", "2", "--no-body", "--json").json()["body"])
        storage = run_cli("page", "2002", "--version", "2", "--format", "storage", "--body-only").out
        self.assertIn('ri:account-id="hidden"', storage)
        self.assertNotIn(ACCOUNT, storage)
        self.assertEqual(run_cli("page", "2002", "--version", "1", "--body-only").out, "# Release notes\n\nDraft.\n")

    def test_the_raw_answer_of_a_version_and_the_people_of_that_time(self):
        raw = json.loads(run_cli("page", "2002", "--version", "2", "--raw").out)
        self.assertEqual(raw["version"]["number"], 2)
        self.assertNotIn(ACCOUNT, json.dumps(raw))
        shown = run_cli("page", "2002", "--version", "2", "--with-users", "--format", "storage", "--body-only").out
        self.assertIn(ACCOUNT, shown)
        refused = run_cli("page", "2002", "--version", "2", "--with-users", settings=default_settings(hide_users=True))
        self.assertEqual(refused.code, 1)

    def test_a_version_the_page_does_not_have_is_not_found_and_says_where_to_look(self):
        for number in ("9", "4"):
            result = run_cli("page", "2002", "--version", number)
            with self.subTest(version=number):
                self.assertEqual(result.code, 4)
                self.assertIn(f"Page 2002 has no version {number}.", result.err)
                self.assertIn("The page is at version 3. `conflu versions 2002` lists the versions it has.", result.err)
        error = run_cli("page", "2002", "--version", "9", "--json").error()
        self.assertEqual((error["code"], error["exitCode"], error["details"]["currentVersion"]), ("NOT_FOUND", 4, 3))

    def test_wrong_input_is_a_usage_error_with_a_hint(self):
        for argv in (
            ("page", "2002", "--version", "0"),
            ("page", "2002", "--version", "-1"),
            ("page", "2002", "--version", "x"),
            ("page", "2002", "--version", "1", "--comments"),
            ("page", "2002", "--version", "1", "--ancestors"),
            ("page", "2002", "2003", "--version", "1"),
        ):
            with self.subTest(argv=argv):
                gateway = FakeGateway()
                result = run_cli(*argv, gateway=gateway)
                self.assertEqual(result.code, 2, result.err)
                self.assertIn("Hint:", result.err)
                self.assertEqual(gateway.calls, [])
        both = run_cli("page", "2002", "--version", "1", "--comments")
        self.assertIn("Leave out --comments and --ancestors", both.err)

    def test_raw_is_refused_with_what_it_does_not_hold_and_nothing_is_asked(self):
        for extra in (("--comments",), ("--ancestors",), ("--attachments",), ("--outline",), ("--section", "x"), ("--max-chars", "10")):
            with self.subTest(option=extra[0]):
                gateway = FakeGateway()
                result = run_cli("page", "2002", "--raw", *extra, gateway=gateway)
                self.assertEqual(result.code, 2, result.err)
                self.assertIn("--raw prints Confluence's own JSON", result.err)
                self.assertIn("Hint:", result.err)
                self.assertEqual(gateway.calls, [])  # not asked, so not asked in vain
        gateway = FakeGateway()
        self.assertIn("--comments, --ancestors and --attachments", run_cli("page", "2002", "--raw", "--attachments", gateway=gateway).err)
        for argv in (("page", "2002", "--raw"), ("page", "2002", "--raw", "--no-body"), ("page", "2002", "--raw", "--version", "2"), ("page", "2002", "--raw", "--with-users")):
            with self.subTest(argv=argv):
                self.assertEqual(run_cli(*argv).code, 0, argv)  # what it was stays

    def test_the_id_of_a_folder_says_what_it_is(self):
        result = run_cli("page", "7001")
        self.assertEqual(result.code, 4)
        self.assertIn("Hint: 7001 is a folder, not a page: use `conflu folder 7001`.", result.err)
        self.assertEqual(run_cli("page", "99999").code, 4)

    def test_a_folder_in_the_path_has_its_title(self):
        gateway = FakeGateway()
        gateway.pages["2090"] = type(gateway.pages["2002"])("2090", "Below the runbooks", space_id="1001", space_key="ENG", parent_id="7011", parent_type="folder", version=VersionInfo(1))
        data = run_cli("page", "2090", "--ancestors", "--no-body", "--json", gateway=gateway).json()
        self.assertEqual(data["ancestors"], [{"id": "7001", "title": "Guides"}, {"id": "7011", "title": "Runbooks"}])
        self.assertIn("Path:    Guides > Runbooks > Below the runbooks", run_cli("page", "2090", "--ancestors", "--no-body", gateway=gateway).out)


class SeveralPagesTest(unittest.TestCase):
    def test_the_pages_one_after_the_other_with_a_rule_between(self):
        gateway = FakeGateway()
        gateway.page_cap = 100
        result = run_cli("page", "2003", "2002", "--outline", gateway=gateway)
        self.assertEqual(result.code, 0, result.err)
        blocks = result.out.split(f"\n\n{RULE}\n\n")
        self.assertEqual(len(blocks), 2)
        self.assertTrue(blocks[0].startswith("Architecture  [2003]"))
        self.assertTrue(blocks[1].startswith("Release notes  [2002]"))
        self.assertEqual(len(RULE), 72)
        self.assertEqual(len(gateway.called("get_pages")), 1)
        self.assertIn("The labels are not read when several pages are asked for", result.err)

    def test_the_json_has_a_count_the_pages_and_the_errors(self):
        data = run_cli("page", "2002", "2003", "--json").json()
        self.assertEqual(list(data), ["count", "pages", "errors"])
        self.assertEqual((data["count"], [page["id"] for page in data["pages"]], data["errors"]), (2, ["2002", "2003"], []))
        self.assertEqual([page["labels"] for page in data["pages"]], [None, None])  # the request for several pages gives none
        self.assertEqual(data["pages"][0]["body"]["format"], "markdown")
        self.assertNotIn(ACCOUNT, json.dumps(data))

    def test_a_page_that_is_not_there_is_an_entry_and_the_exit_code_is_4(self):
        result = run_cli("page", "2002", "999", "2003", "--json")
        self.assertEqual(result.code, 4)
        data = result.json()
        self.assertEqual((data["count"], [page["id"] for page in data["pages"]]), (2, ["2002", "2003"]))
        self.assertEqual(list(data["errors"][0]), ["ref", "code", "message", "hint"])
        self.assertEqual((data["errors"][0]["ref"], data["errors"][0]["code"]), ("999", "NOT_FOUND"))
        self.assertEqual(result.err.count("ERROR"), 0)  # no error object on stderr: the result holds it
        text = run_cli("page", "2002", "999")
        self.assertEqual(text.code, 4)
        self.assertIn("999  [NOT_FOUND] Not found: GET /api/v2/pages/999", text.out)
        self.assertIn("Release notes  [2002]", text.out)

    def test_a_folder_among_them_is_named(self):
        data = run_cli("page", "2002", "7001", "--json").json()
        self.assertEqual(data["errors"][0]["hint"], "7001 is a folder, not a page: use `conflu folder 7001`.")

    def test_a_page_given_twice_is_shown_once_and_a_title_is_looked_up(self):
        data = run_cli("page", "2002", f"{BASE}/spaces/ENG/pages/2002/Release+notes", "page:ENG/Architecture", "--json").json()
        self.assertEqual([page["id"] for page in data["pages"]], ["2002", "2003"])

    def test_the_options_apply_to_every_page(self):
        data = run_cli("page", "2002", "2003", "--outline", "--attachments", "--comments", "--ancestors", "--json").json()
        self.assertTrue(all(page["body"] is None and "outline" in page for page in data["pages"]))
        self.assertTrue(all("attachments" in page and "comments" in page and "ancestors" in page for page in data["pages"]))
        self.assertEqual([page["attachmentTotal"] for page in data["pages"]], [2, 0])
        cut = run_cli("page", "2002", "2003", "--max-chars", "12", "--json").json()
        self.assertTrue(cut["pages"][0]["body"]["truncated"])

    def test_a_section_a_page_lacks_is_an_entry_of_that_page_only(self):
        result = run_cli("page", "2002", "2003", "--section", "release notes", "--json")
        self.assertEqual(result.code, 1)
        data = result.json()
        self.assertEqual(([page["id"] for page in data["pages"]], data["errors"][0]["ref"], data["errors"][0]["code"]), (["2002"], "2003", "INVALID"))

    def test_what_is_for_one_page_is_refused_for_several(self):
        for argv in (("page", "2002", "2003", "--raw"), ("page", "2002", "2003", "--body-only"), ("page", "2002", "2003", "--version", "1")):
            with self.subTest(argv=argv):
                gateway = FakeGateway()
                result = run_cli(*argv, gateway=gateway)
                self.assertEqual(result.code, 2, result.err)
                self.assertEqual(gateway.called("get_pages"), [])

    def test_something_that_is_no_id_refuses_the_whole_call(self):
        for bad in ("abc", "../2002", "2002;2003", "1" * 20):
            with self.subTest(bad=bad):
                gateway = FakeGateway()
                result = run_cli("page", "2002", bad, gateway=gateway)
                self.assertEqual(result.code, 1)
                self.assertEqual(gateway.calls, [])

    def test_a_failure_of_the_request_is_the_failure_of_the_call(self):
        gateway = FakeGateway()
        gateway.errors["get_pages"] = UnavailableError("busy")
        self.assertEqual(run_cli("page", "2002", "2003", gateway=gateway).code, 7)

    def test_one_page_is_what_it_always_was(self):
        gateway = FakeGateway()
        result = run_cli("page", "2002", gateway=gateway)
        self.assertEqual(result.code, 0)
        self.assertEqual(gateway.called("get_pages"), [])
        self.assertIn("Labels:  release, notes", result.out)
        self.assertNotIn(RULE, result.out)
        self.assertIsInstance(run_cli("page", "2002", "--json").json()["labels"], list)


class AttachmentsTest(unittest.TestCase):
    def test_the_text_names_how_many_and_the_first_names(self):
        result = run_cli("page", "2002", "--attachments", "--no-body")
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("Attachments: 2 (diagram.png, notes.txt)", result.out)

    def test_a_page_without_files_says_none(self):
        self.assertIn("Attachments: none", run_cli("page", "2003", "--attachments", "--no-body").out)
        self.assertEqual(run_cli("page", "2003", "--attachments", "--json").json()["attachments"], [])

    def test_without_the_option_nothing_is_said_and_nothing_is_asked(self):
        gateway = FakeGateway()
        result = run_cli("page", "2002", gateway=gateway)
        self.assertNotIn("Attachments", result.out)
        self.assertEqual(gateway.called("list_attachments"), [])

    def test_the_json_has_the_files_and_their_number(self):
        data = run_cli("page", "2002", "--attachments", "--json").json()
        self.assertEqual(data["attachments"], [{"id": "att5001", "title": "diagram.png", "mediaType": "image/png", "size": 10}, {"id": "att5002", "title": "notes.txt", "mediaType": "text/plain", "size": 12}])
        self.assertEqual(data["attachmentTotal"], 2)

    def test_a_long_list_names_the_first_ones_and_counts_the_rest(self):
        gateway = FakeGateway()
        gateway.attachments["2003"] = [Attachment(f"att7{number:03d}", f"file{number}.txt", "text/plain", number, "2026-10-04T08:00:00.000Z", 1, "2003") for number in range(ATTACHMENT_NAMES + 3)]
        text = run_cli("page", "2003", "--attachments", "--no-body", gateway=gateway).out
        self.assertIn(f"Attachments: {ATTACHMENT_NAMES + 3} (file0.txt", text)
        self.assertIn(f"file{ATTACHMENT_NAMES - 1}.txt, ... and 3 more)", text)
        self.assertNotIn(f"file{ATTACHMENT_NAMES}.txt", text)
        self.assertEqual(run_cli("page", "2003", "--attachments", "--json", gateway=gateway).json()["attachmentTotal"], ATTACHMENT_NAMES + 3)

    def test_a_file_name_with_an_address_is_hidden_unless_people_are_shown(self):
        gateway = FakeGateway()
        gateway.attachments["2003"] = [Attachment("att7000", "alex@example.com.pdf", "application/pdf", 5, "2026-10-04T08:00:00.000Z", 1, "2003")]
        hidden = run_cli("page", "2003", "--attachments", "--no-body", "--json", gateway=gateway).out
        self.assertNotIn("alex@example.com", hidden)
        self.assertIn("[email]", hidden)
        shown = run_cli("page", "2003", "--attachments", "--no-body", "--with-users", "--json", gateway=gateway).out
        self.assertIn("alex@example.com.pdf", shown)

    def test_a_file_name_on_two_lines_stays_on_one(self):
        gateway = FakeGateway()
        gateway.attachments["2003"] = [Attachment("att7000", "one\ntwo.txt", "text/plain", 5, "2026-10-04T08:00:00.000Z", 1, "2003")]
        text = run_cli("page", "2003", "--attachments", "--no-body", gateway=gateway).out
        self.assertIn("Attachments: 1 (one two.txt)", text)

    def test_it_works_with_an_earlier_version_and_with_several_pages(self):
        self.assertIn("Attachments: 2 (diagram.png, notes.txt)", run_cli("page", "2002", "--version", "1", "--attachments", "--no-body").out)
        data = run_cli("page", "2002", "2003", "--attachments", "--no-body", "--json").json()
        self.assertEqual([page["attachmentTotal"] for page in data["pages"]], [2, 0])


class DiffTest(unittest.TestCase):
    def test_the_current_version_against_the_one_before_it_is_a_unified_diff(self):
        result = run_cli("diff", "2002")
        self.assertEqual(result.code, 0, result.err)
        lines = result.out.splitlines()
        self.assertEqual(lines[0], "--- version 2\t2026-10-05T10:00:00.000Z")
        self.assertEqual(lines[1], "+++ version 3 (current)\t2026-10-10T09:00:00.000Z")
        self.assertIn("-Contact @user.", lines)
        self.assertIn("+Contact @user or write to [email].", lines)
        self.assertIn("+- Second", lines)
        self.assertIn("The Markdown cannot show: macro:toc, mention, redacted-text. A change in these is not in the diff.", result.err)
        self.assertNotIn(ACCOUNT, result.out)
        self.assertNotIn("alex@example.com", result.out)

    def test_the_two_versions_can_be_named_in_either_order_and_the_target_can_be_current(self):
        both = run_cli("diff", "2002", "--from", "1", "--to", "2").out
        self.assertTrue(both.startswith("--- version 1\t"))
        self.assertIn("-Draft.", both)
        backwards = run_cli("diff", "2002", "--from", "3", "--to", "1").out
        self.assertIn("--- version 3 (current)", backwards)
        self.assertIn("+Draft.", backwards)
        current = run_cli("diff", "2002", "--from-version", "1", "--to-version", "current").out
        self.assertIn("+++ version 3 (current)", current)
        self.assertEqual(run_cli("diff", "2002", "--to", "CURRENT", "--json").json()["to"]["number"], 3)

    def test_the_json_names_both_sides_and_counts_the_lines(self):
        data = run_cli("diff", "2002", "--json").json()
        self.assertEqual(
            list(data),
            ["pageId", "title", "from", "to", "identical", "added", "removed", "truncated", "totalChars", "dropped", "sourceIdentical", "note", "diff"],
        )
        self.assertEqual(data["from"], {"number": 2, "created": "2026-10-05T10:00:00.000Z", "message": "", "title": "Release notes", "current": False})
        self.assertEqual(data["to"]["current"], True)
        self.assertEqual((data["added"], data["removed"], data["identical"], data["sourceIdentical"], data["note"]), (2, 1, False, False, None))
        self.assertEqual(data["dropped"], ["macro:toc", "mention", "redacted-text"])
        self.assertEqual(data["diff"].splitlines()[0], "--- version 2\t2026-10-05T10:00:00.000Z")

    def test_a_page_with_one_version_has_nothing_to_compare_and_that_is_no_failure(self):
        result = run_cli("diff", "2005")
        self.assertEqual((result.code, result.out), (0, "Page 2005 has one version only: there is nothing to compare.\n"))
        data = run_cli("diff", "2005", "--json").json()
        self.assertEqual((data["from"], data["identical"], data["diff"], data["note"]), (None, True, "", "Page 2005 has one version only: there is nothing to compare."))

    def test_the_first_version_of_a_page_that_has_more_has_nothing_before_it_and_the_page_has_more_than_one(self):
        note = "Version 1 is the first version of page 2002: nothing came before it, so there is nothing to compare. `--from 1` compares it with the current version."
        result = run_cli("diff", "2002", "--to", "1")
        self.assertEqual((result.code, result.out), (0, note + "\n"))
        self.assertNotIn("one version only", result.out)
        data = run_cli("diff", "2002", "--to", "1", "--json").json()
        self.assertEqual((data["from"], data["identical"], data["sourceIdentical"], data["diff"], data["note"]), (None, False, False, "", note))
        self.assertEqual((data["to"]["number"], data["to"]["current"], data["added"], data["removed"]), (1, False, 0, 0))
        self.assertEqual(run_cli("diff", "2002", "--to-version", "1").out, note + "\n")
        self.assertIn("-Draft.", run_cli("diff", "2002", "--from", "1").out)  # the way the note names

    def test_version_1_of_a_page_with_one_version_is_that_page(self):
        self.assertEqual(run_cli("diff", "2005", "--to", "1").out, "Page 2005 has one version only: there is nothing to compare.\n")

    def test_versions_that_read_the_same_say_so(self):
        gateway = FakeGateway()
        gateway.version_bodies[("2002", 1)] = "<h1>Release notes</h1><p>Same.</p>"
        gateway.version_bodies[("2002", 2)] = '<h1>Release notes</h1><p>Same.</p><ac:structured-macro ac:name="toc" ac:schema-version="1" />'
        result = run_cli("diff", "2002", "--from", "1", "--to", "2", gateway=gateway)
        self.assertEqual(result.code, 0)
        self.assertIn("Versions 1 and 2 read the same as Markdown.", result.out)
        self.assertIn("The versions differ in what the Markdown cannot say (macro:toc): that is not in a diff of the Markdown.", result.out)
        gateway.version_bodies[("2002", 1)] = gateway.version_bodies[("2002", 2)]
        self.assertEqual(run_cli("diff", "2002", "--from", "1", "--to", "2", gateway=gateway).out, "Versions 1 and 2 are the same.\n")
        self.assertEqual(run_cli("diff", "2002", "--from", "2", "--to", "2", gateway=gateway).out, "Version 2 is compared with itself.\n")

    def test_the_diff_can_be_cut_and_the_context_changed(self):
        cut = run_cli("diff", "2002", "--from", "1", "--max-chars", "60")
        self.assertIn("The diff was cut:", cut.err)
        self.assertLessEqual(len(cut.out.rstrip("\n")), 60)
        data = run_cli("diff", "2002", "--from", "1", "--max-chars", "60", "--json").json()
        self.assertTrue(data["truncated"])
        self.assertGreater(data["totalChars"], 60)
        self.assertFalse(any(line.startswith(" ") for line in run_cli("diff", "2002", "--context", "0").out.splitlines()))

    def test_people_are_not_in_the_diff_nor_in_what_it_says_about_the_versions(self):
        gateway = FakeGateway()
        gateway.versions["2002"][1] = VersionInfo(2, "2026-10-05T10:00:00.000Z", "Mail alex@example.com", False, User(ACCOUNT, "Alex Example"))
        gateway.pages["2002"].title = "Notes of alex@example.com"
        data = run_cli("diff", "2002", "--json", gateway=gateway)
        self.assertNotIn("alex", data.out)
        self.assertNotIn(ACCOUNT, data.out)
        self.assertEqual((data.json()["title"], data.json()["from"]["message"]), ("Notes of [email]", "Mail [email]"))

    def test_the_versions_the_page_does_not_have_are_not_found(self):
        for argv in (("diff", "2002", "--from", "9"), ("diff", "2002", "--to", "9"), ("diff", "2002", "--from", "1", "--to", "9")):
            with self.subTest(argv=argv):
                result = run_cli(*argv)
                self.assertEqual(result.code, 4)
                self.assertIn("Page 2002 has no version 9.", result.err)
                self.assertIn("conflu versions 2002", result.err)
        self.assertEqual(run_cli("diff", "999").code, 4)

    def test_wrong_input_is_a_usage_error_before_anything_is_asked(self):
        for argv in (
            ("diff", "2002", "--from", "0"),
            ("diff", "2002", "--to", "0"),
            ("diff", "2002", "--to", "abc"),
            ("diff", "2002", "--to", ""),
            ("diff", "2002", "--to", "1.5"),
            ("diff", "2002", "--context", "-1"),
            ("diff", "2002", "--context", "5000"),
            ("diff", "2002", "--max-chars", "-5"),
            ("diff", "2002", "--from", "x"),
        ):
            with self.subTest(argv=argv):
                gateway = FakeGateway()
                result = run_cli(*argv, gateway=gateway)
                self.assertEqual(result.code, 2, result.err)
                self.assertEqual(gateway.calls, [])
        for ref in ("", "abc", "../2002", "1" * 20):
            self.assertIn(run_cli("diff", ref).code, (1, 2))

    def test_the_id_of_a_folder_says_what_it_is(self):
        result = run_cli("diff", "7001")
        self.assertEqual(result.code, 4)
        self.assertIn("7001 is a folder, not a page", result.err)


class RestoreTest(unittest.TestCase):
    def test_a_dry_run_shows_the_request_and_what_changes_and_sends_nothing(self):
        gateway = FakeGateway()
        result = run_cli("restore", "2002", "--version", "1", "--dry-run", gateway=gateway)
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("Dry run: version 1 of page 2002 'Release notes' would come back as version 4; nothing was sent", result.out)
        self.assertIn("As Markdown shows them, the page gains 1 line and loses 4 lines.", result.out)
        self.assertIn('"operationKey": "restore"', result.out)
        self.assertIn('"versionNumber": 1', result.out)
        self.assertEqual(gateway.called("restore_page_version"), [])
        self.assertEqual(gateway.pages["2002"].version_number, 3)

    def test_the_real_run_makes_a_new_version_and_names_the_two(self):
        gateway = FakeGateway()
        result = run_cli("restore", "2002", "--version", "2", "--message", "Back to the reviewed text", "--if-version", "3", gateway=gateway)
        self.assertEqual(result.code, 0, result.err)
        first, second, third = result.out.splitlines()
        self.assertEqual(first, "Restored version 2 of page 2002: Release notes (version 3 -> 4)")
        self.assertEqual(second, f"{BASE}/spaces/ENG/pages/2002/Release+notes")
        self.assertEqual(third, "As Markdown shows them, the page gains 1 line and loses 2 lines.")
        self.assertEqual(gateway.pages["2002"].version_number, 4)
        self.assertEqual(gateway.pages["2002"].version.message, "Back to the reviewed text")
        self.assertEqual(gateway.pages["2002"].body, SECOND_BODY)  # the mention came back untouched, nothing went through Markdown
        self.assertEqual(result.err, "")

    def test_the_json_of_a_dry_run_and_of_the_real_run(self):
        gateway = FakeGateway()
        dry = run_cli("restore", "2002", "--version", "1", "--restore-title", "--dry-run", "--json", gateway=gateway).json()
        self.assertEqual(
            list(dry), ["action", "dryRun", "pageId", "title", "url", "restoredVersion", "versionFrom", "versionTo", "added", "removed", "payload"]
        )
        self.assertEqual((dry["action"], dry["dryRun"], dry["restoredVersion"], dry["versionFrom"], dry["versionTo"]), ("restored", True, 1, 3, 4))
        self.assertEqual(dry["title"], "Release notes (draft)")  # the title the page would have
        self.assertEqual(dry["payload"], {"operationKey": "restore", "params": {"versionNumber": 1, "message": "Restored version 1", "restoreTitle": True}})
        real = run_cli("restore", "2002", "--version", "1", "--restore-title", "--json", gateway=gateway).json()
        self.assertEqual((real["dryRun"], real["versionFrom"], real["versionTo"], real["payload"]), (False, 3, 4, dry["payload"]))
        self.assertEqual(gateway.called("restore_page_version"), [("restore_page_version", "2002", dry["payload"])])
        self.assertEqual(gateway.pages["2002"].title, "Release notes (draft)")

    def test_what_a_restore_does_not_do(self):
        gateway = FakeGateway()
        run_cli("restore", "2002", "--version", "1", gateway=gateway)
        self.assertEqual(gateway.pages["2002"].title, "Release notes")  # the title stays unless asked for
        self.assertEqual(gateway.pages["2002"].version_number, 4)
        self.assertIn("alex@example.com", gateway.version_bodies[("2002", 3)])  # the version that was covered is still there, whole

    def test_the_guards_refuse_with_exit_code_3_and_the_dry_run_checks_them_too(self):
        gateway = FakeGateway()
        for argv in (
            ("restore", "2002", "--version", "1", "--if-version", "2"),
            ("restore", "2002", "--version", "1", "--if-unchanged-since", "2026-10-09T00:00:00Z"),
            ("restore", "2002", "--version", "1", "--if-version", "1", "--dry-run"),
        ):
            with self.subTest(argv=argv):
                result = run_cli(*argv, gateway=gateway)
                self.assertEqual(result.code, 3, result.err)
                self.assertIn("Read it again and review the current state before writing.", result.err)
        self.assertEqual(gateway.called("restore_page_version"), [])
        self.assertEqual(run_cli("restore", "2002", "--version", "1", "--if-version", "3", "--if-unchanged-since", "2026-10-10T09:00:00Z", gateway=gateway).code, 0)

    def test_an_empty_guard_is_refused_with_the_name_of_the_option_and_nothing_is_sent_in_a_dry_run_too(self):
        for extra in ((), ("--dry-run",)):
            with self.subTest(dry_run=bool(extra)):
                gateway = FakeGateway()
                result = run_cli("restore", "2002", "--version", "1", "--if-unchanged-since", "", *extra, gateway=gateway)
                self.assertEqual(result.code, 1, result.err)
                self.assertIn("--if-unchanged-since: Not an ISO 8601 timestamp: ''", result.err)
                self.assertEqual(result.out, "")
                self.assertEqual(gateway.called("restore_page_version"), [])
                self.assertEqual(gateway.calls, [])
                self.assertEqual(gateway.pages["2002"].version_number, 3)
        error = run_cli("restore", "2002", "--version", "1", "--if-unchanged-since", "", "--json").error()
        self.assertEqual((error["code"], error["exitCode"]), ("INVALID", 1))
        self.assertEqual(run_cli("restore", "2002", "--version", "1", "--dry-run").code, 0)  # no guard given is no guard

    def test_the_current_version_is_nothing_to_restore(self):
        result = run_cli("restore", "2002", "--version", "3")
        self.assertEqual(result.code, 2)
        self.assertIn("Version 3 is the current version of page 2002: there is nothing to restore.", result.err)
        self.assertIn("conflu versions 2002", result.err)

    def test_a_version_that_does_not_exist_is_not_found_and_says_where_to_look(self):
        result = run_cli("restore", "2002", "--version", "9")
        self.assertEqual(result.code, 4)
        self.assertIn("Page 2002 has no version 9.", result.err)
        self.assertIn("The page is at version 3.", result.err)

    def test_a_page_that_is_not_current_is_not_restored(self):
        gateway = FakeGateway()
        gateway.pages["2005"].status = "archived"
        result = run_cli("restore", "2005", "--version", "1", gateway=gateway)
        self.assertEqual(result.code, 1)
        self.assertIn("Page 2005 is archived and is not restored.", result.err)

    def test_wrong_input_is_refused_before_anything_is_asked(self):
        for argv, code in (
            (("restore", "2002"), 2),  # no version
            (("restore", "2002", "--version", "0"), 2),
            (("restore", "2002", "--version", "-1"), 2),
            (("restore", "2002", "--version", "x"), 2),
            (("restore", "2002", "--version", "1", "--if-version", "x"), 2),
            (("restore", "2002", "--version", "1", "--if-version", ""), 2),  # an empty guard is no number, and no "not given"
            (("restore", "2002", "--version", "1", "--if-version", "", "--dry-run"), 2),
            (("restore", "2002", "--version", "1", "--if-unchanged-since", "yesterday"), 1),
            (("restore", "../2002", "--version", "1"), 1),
            (("restore", "", "--version", "1"), 1),
            (("restore", "2002 2003", "--version", "1"), 1),
            (("restore", "999", "--version", "1"), 4),
            (("restore", "7001", "--version", "1"), 4),
        ):
            with self.subTest(argv=argv):
                gateway = FakeGateway()
                result = run_cli(*argv, gateway=gateway)
                self.assertEqual(result.code, code, result.err)
                self.assertEqual(gateway.called("restore_page_version"), [])

    def test_the_title_and_the_address_in_the_answer_name_nobody(self):
        gateway = FakeGateway()
        gateway.pages["2002"].title = "Notes of alex@example.com"
        gateway.pages["2002"].url = f"{BASE}/spaces/ENG/pages/2002/Notes+of+alex%40example.com"
        data = run_cli("restore", "2002", "--version", "1", "--dry-run", "--json", gateway=gateway).json()
        self.assertEqual((data["title"], data["url"]), ("Notes of [email]", f"{BASE}/spaces/ENG/pages/2002"))

    def test_when_the_page_cannot_be_read_back_it_is_a_warning_and_the_restore_stands(self):
        gateway = FakeGateway()
        original = gateway.get_page

        def get_page(page_id, *, with_body=True):
            if not with_body and gateway.called("restore_page_version"):
                raise UnavailableError("busy")
            return original(page_id, with_body=with_body)

        gateway.get_page = get_page
        result = run_cli("restore", "2002", "--version", "1", gateway=gateway)
        self.assertEqual(result.code, 0)
        self.assertIn("version 3 -> 4", result.out)
        self.assertIn("The version was restored, but the page could not be read back: busy", result.err)


class OtherCommandsOnWhatIsNoPageTest(unittest.TestCase):
    """`labels`, `label`, `comments`, `comment` and `update` say what the id of a folder or of a blog post is, as `page` does."""

    FOLDER = "7001 is a folder, not a page: use `conflu folder 7001`."
    BLOG_POST = "7101 is a blog post, not a page: use `conflu blogpost 7101`."

    COMMANDS = (
        ("labels",),
        ("label", "--add", "x"),
        ("label", "--add", "x", "--dry-run"),
        ("comments",),
        ("comments", "--inline"),
        ("comment", "--text", "Hi"),
        ("comment", "--text", "Hi", "--dry-run"),
        ("update", "--title", "T"),
        ("update", "--title", "T", "--dry-run"),
    )

    def test_a_folder_and_a_blog_post_say_what_they_are(self):
        for ref, hint in (("7001", self.FOLDER), ("7101", self.BLOG_POST)):
            for command in self.COMMANDS:
                argv = (command[0], ref, *command[1:])
                with self.subTest(argv=argv):
                    result = run_cli(*argv)
                    self.assertEqual(result.code, 4, result.err)
                    self.assertIn(f"Hint: {hint}", result.err)

    def test_the_answer_in_json_names_the_kind_too_and_what_confluence_said_stays(self):
        error = run_cli("labels", "7001", "--json").error()
        self.assertEqual((error["code"], error["exitCode"], error["hint"]), ("NOT_FOUND", 4, self.FOLDER))
        self.assertEqual(error["message"], "Not found: GET /api/v2/pages/7001")

    def test_an_id_that_is_nothing_keeps_the_plain_error(self):
        for command in self.COMMANDS:
            argv = (command[0], "99999", *command[1:])
            with self.subTest(argv=argv):
                result = run_cli(*argv)
                self.assertEqual(result.code, 4, result.err)
                self.assertNotIn("not a page", result.err)

    def test_a_page_is_answered_as_it_was(self):
        self.assertEqual(run_cli("labels", "2002").code, 0)
        self.assertEqual(run_cli("label", "2002", "--add", "x", "--dry-run").code, 0)
        self.assertEqual(run_cli("comments", "2002").code, 0)
        self.assertEqual(run_cli("comment", "2002", "--text", "Hi", "--dry-run").code, 0)
        self.assertEqual(run_cli("update", "2005", "--title", "T", "--dry-run").code, 0)


if __name__ == "__main__":
    unittest.main()
