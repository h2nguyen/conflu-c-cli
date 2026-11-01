"""The commands of the attachments area on the command line, with the in-memory Confluence: what they print, what they refuse, how they are described."""
import dataclasses
import json
import unittest

from conflu_c_cli.adapters.driving.cli.registry import all_commands, find_command
from conflu_c_cli.adapters.driving.cli.spec import READS_FILES, WRITES_BELOW_FOLDER
from conflu_c_cli.domain.errors import AuthError, UnavailableError
from tests.support.attachment_data import AGENDA, PLAN, Edition, Fixture
from tests.support.cli import run_cli
from tests.support.fakes import ACCOUNT, FakeGateway, MemoryConfigStore, MemoryFiles, default_settings
from tests.support.places_attachments import PlacedFiles

CONFIG = "/home/me/.config/conflu-c-cli/config"
NAMES = ("attachments", "attachment", "download", "attach")


def fresh():
    fake = FakeGateway()
    fake.page_cap = 100
    return fake


class DescriptionTest(unittest.TestCase):
    def test_the_commands_are_there_and_say_when_to_use_them(self):
        for name in NAMES:
            command = find_command(name)
            with self.subTest(command=name):
                self.assertTrue(command.when and command.output and command.json_output and command.examples)
                self.assertTrue(all(arg.help for arg in command.args))
        self.assertEqual([find_command(name).group for name in NAMES], ["Read", "Read", "Read", "Work on a page"])
        self.assertEqual(len([command for command in all_commands() if command.name == "attachment"]), 1)

    def test_the_readers_change_nothing_and_attach_is_the_one_writer_and_only_adds(self):
        for name in ("attachments", "attachment", "download"):
            self.assertFalse(find_command(name).writes, name)
        attach = find_command("attach")
        self.assertTrue(attach.writes and not attach.destructive and not attach.idempotent and not attach.for_person and not attach.local)  # a new version keeps the old ones
        self.assertTrue(any("--dry-run" in arg.names for arg in attach.args))

    def test_download_says_what_conflu_mcp_needs_to_know(self):
        download = find_command("download")
        self.assertTrue(download.writes_files and not download.writes and not download.destructive and not download.idempotent)  # it changes nothing in Confluence
        arguments = {arg.names[0]: arg for arg in download.args}
        self.assertEqual(arguments["--out"].path, WRITES_BELOW_FOLDER)
        self.assertEqual(arguments["--out"].default, ".")  # the place that a call without --out writes into stays visible, for the policy of a program that runs it
        self.assertTrue(arguments["--force"].overwrites)
        for flag in ("--name", "target"):
            self.assertTrue(arguments[flag].not_a_path, flag)

    def test_attach_says_which_arguments_are_files_and_which_are_not(self):
        arguments = {arg.names[0]: arg for arg in find_command("attach").args}
        self.assertEqual(arguments["files"].path, READS_FILES)
        self.assertTrue(arguments["ref"].not_a_path)

    def test_an_argument_that_speaks_of_a_file_or_a_folder_says_what_it_is(self):
        for name in NAMES:
            for arg in find_command(name).args:
                text = " ".join([*arg.names, arg.metavar, arg.help]).lower()
                with self.subTest(command=name, arg=arg.names[0]):
                    says = any(word in text for word in ("folder", "file", "path", "directory"))
                    self.assertTrue(not says or arg.not_a_path or arg.path or arg.at_file, f"{arg.names[0]} of {name} speaks of a file or a folder and says it is none")

    def test_the_usage_of_attach_keeps_its_old_beginning_and_adds_the_guards_behind_dry_run(self):
        usage = find_command("attach").usage()
        self.assertTrue(usage.startswith("conflu attach PAGE FILE... [--comment TEXT] [--minor] [--dry-run] [--if-version N] [--if-unchanged-since ISO]"))

    def test_the_property_names_of_a_tool_are_distinct(self):
        from conflu_c_cli.adapters.driving.cli.help import mcp_property_names

        for name in NAMES:
            names = list(mcp_property_names(find_command(name)).values())
            self.assertEqual(len(names), len(set(names)), name)


class AttachmentsCommandTest(unittest.TestCase):
    def test_a_page_as_a_table(self):
        result = run_cli("attachments", "2004", gateway=fresh())
        self.assertEqual(result.code, 0, result.err)
        lines = result.out.splitlines()
        self.assertEqual(lines[0].split(), ["ID", "NAME", "SIZE", "TYPE", "VERSION", "CREATED"])
        self.assertEqual(len(lines), 7)
        self.assertEqual(lines[1].split()[:6], ["att5101", "plan.txt", f"{len(PLAN[2].data)}", "B", "text/plain", "3"])

    def test_a_blog_post_works_as_a_page_does(self):
        result = run_cli("attachments", "7102", gateway=fresh())
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("agenda.txt", result.out)
        self.assertIn("minutes.md", result.out)
        data = run_cli("attachments", "7102", "--json", gateway=fresh()).json()
        self.assertEqual((data["pageId"], data["blogPostId"], data["count"], data["nextCursor"]), (None, "7102", 2, None))
        self.assertEqual({item["blogPostId"] for item in data["attachments"]}, {"7102"})
        self.assertEqual({item["pageId"] for item in data["attachments"]}, {None})

    def test_the_json_of_a_page(self):
        data = run_cli("attachments", "2004", "--limit", "1", "--json", gateway=FakeGateway()).json()
        self.assertEqual((data["pageId"], data["blogPostId"], data["count"], data["nextCursor"]), ("2004", None, 1, "1"))
        item = data["attachments"][0]
        self.assertEqual(set(item), {"id", "title", "mediaType", "size", "version", "created", "updated", "pageId", "blogPostId", "downloadLink", "comment"})
        self.assertEqual((item["id"], item["version"], item["updated"], item["comment"]), ("att5101", 3, "2026-10-09T14:00:00.000Z", "The plan for the October release"))

    def test_more_follows_is_said_on_stderr_and_never_in_the_json(self):
        fake = FakeGateway()
        fake.page_cap = 2
        text = run_cli("attachments", "2004", gateway=fake)
        self.assertIn("--cursor 2", text.err)
        self.assertEqual(run_cli("attachments", "2004", "--json", gateway=fake).err, "")
        self.assertEqual(run_cli("attachments", "2004", "--all", gateway=fake).err, "")

    def test_select_and_format_work_as_on_every_list(self):
        result = run_cli("attachments", "2004", "--select", "id,title,size", "--format", "tsv", gateway=fresh())
        self.assertEqual(result.out.splitlines()[:2], ["id\ttitle\tsize", f"att5101\tplan.txt\t{len(PLAN[2].data)}"])
        data = run_cli("attachments", "7102", "--select", "id,blogPostId", "--json", gateway=fresh()).json()
        self.assertEqual(data["attachments"], [{"id": "att5111", "blogPostId": "7102"}, {"id": "att5112", "blogPostId": "7102"}])

    def test_a_name_filter(self):
        result = run_cli("attachments", "2004", "--name", "plan.txt", "--json", gateway=fresh())
        self.assertEqual([item["id"] for item in result.json()["attachments"]], ["att5101"])
        self.assertEqual(run_cli("attachments", "2004", "--name", "nothing.txt", gateway=fresh()).out, "No attachments.\n")

    def test_names_and_comments_are_redacted_until_people_are_asked_for(self):
        fake = fresh()
        fake.add_attachment_fixture(Fixture("att5301", "2004", "alex@example.com.txt", "text/plain", (Edition(b"x", "", False, "2026-10-20T09:00:00.000Z"),), (), "from alex@example.com"))
        item = run_cli("attachments", "2004", "--json", gateway=fake).json()["attachments"][-1]
        self.assertEqual((item["title"], item["comment"]), ("[email]", "from [email]"))
        self.assertNotIn("alex@example.com", run_cli("attachments", "2004", gateway=fake).out)
        shown = run_cli("attachments", "2004", "--with-users", "--json", gateway=fake).json()["attachments"][-1]
        self.assertEqual((shown["title"], shown["comment"]), ("alex@example.com.txt", "from alex@example.com"))
        refused = run_cli("attachments", "2004", "--with-users", settings=default_settings(hide_users=True), gateway=fake)
        self.assertEqual(refused.code, 1)
        self.assertIn("CONFLUENCE_HIDE_USERS", refused.err)

    def test_the_type_is_redacted_in_every_place_that_prints_it_unless_people_are_asked_for(self):
        fake = fresh()
        fake.add_attachment_fixture(Fixture("att5303", "2004", "odd.bin", "application/x-alex@example.com", (Edition(b"x", "", False, "2026-10-20T09:00:00.000Z"),)))
        prints_the_type = (
            ("attachments", "2004", "--json"), ("attachments", "2004"), ("attachment", "att5303", "--json"), ("attachment", "att5303"),
            ("page", "2004", "--attachments", "--no-body", "--json"), ("download", "att5303", "--text", "--json"), ("download", "att5303", "--text"),
        )
        for argv in (*prints_the_type, ("page", "2004", "--attachments", "--no-body")):
            with self.subTest(argv=argv):
                result = run_cli(*argv, gateway=fake)
                self.assertEqual(result.code, 0, result.err)
                self.assertNotIn("alex", (result.out + result.err).lower())
                if argv in prints_the_type:
                    self.assertIn("application/[email]", result.out)
        for argv in prints_the_type:
            with self.subTest(argv=argv, people=True):
                result = run_cli(*argv, "--with-users", gateway=fake)
                self.assertEqual(result.code, 0, result.err)
                self.assertIn("application/x-alex@example.com", result.out)
        hint = run_cli("download", "att5303", "--text", gateway=fake).out
        self.assertIn("Not shown as text (application/[email]).", hint)  # the head of the entry and its hint say what the field says
        self.assertIn("(application/[email], 1 B)", hint)

    def test_what_a_terminal_would_obey_in_a_name_is_taken_out_of_the_text_and_escaped_in_the_json(self):
        fake = fresh()
        fake.add_attachment_fixture(Fixture("att5302", "2004", "\x1b[2Jevil\u202egnp.txt", "text/plain\x1b[0m", (Edition(b"x", "", False, "2026-10-20T09:00:00.000Z"),)))
        text = run_cli("attachments", "2004", gateway=fake).out
        self.assertNotIn("\x1b", text)
        self.assertNotIn("\u202e", text)
        self.assertIn("evilgnp.txt", text)
        raw = run_cli("attachments", "2004", "--json", gateway=fake).out
        self.assertNotIn("\x1b", raw)  # the escape of a JSON string
        self.assertIn("\\u001b", raw)

    def test_errors_and_their_exit_codes(self):
        self.assertEqual(run_cli("attachments", "999", gateway=fresh()).code, 4)
        self.assertEqual(run_cli("attachments", "att5101", gateway=fresh()).code, 1)
        self.assertEqual(run_cli("attachments", "not-an-id", gateway=fresh()).code, 1)
        self.assertEqual(run_cli("attachments", "2004", "--limit", "0", gateway=fresh()).code, 2)
        self.assertEqual(run_cli("attachments", gateway=fresh()).code, 2)
        folder = fresh()
        folder.content_kinds["7001"] = "folder"
        result = run_cli("attachments", "7001", gateway=folder)
        self.assertEqual(result.code, 4)
        self.assertIn("a folder", result.err)


class AttachmentCommandTest(unittest.TestCase):
    def test_the_properties_as_text(self):
        result = run_cli("attachment", "att5101", gateway=fresh())
        self.assertEqual(result.code, 0, result.err)
        fields = {line.split(":", 1)[0]: line.split(":", 1)[1].strip() for line in result.out.splitlines() if ":" in line}
        self.assertEqual((fields["ID"], fields["Name"], fields["Type"], fields["Version"], fields["Page"]), ("att5101", "plan.txt", "text/plain", "3", "2004"))
        self.assertEqual((fields["Created"], fields["Updated"]), ("2026-10-05T09:00:00.000Z", "2026-10-09T14:00:00.000Z"))
        self.assertEqual(fields["Comment"], "The plan for the October release")
        self.assertIn("Download", fields)
        self.assertNotIn("Labels", fields)
        self.assertNotIn("VERSION", result.out)

    def test_an_attachment_of_a_blog_post_says_blog_post(self):
        out = run_cli("attachment", "att5111", gateway=fresh()).out
        self.assertIn("Blog post: 7102", out)
        self.assertNotIn("Page:", out)

    def test_the_versions_and_labels_as_text(self):
        result = run_cli("attachment", "att5101", "--versions", "--labels", gateway=fresh())
        self.assertEqual(result.code, 0, result.err)
        self.assertRegex(result.out, r"Labels: +draft, plan")
        lines = result.out.splitlines()
        header = next(index for index, line in enumerate(lines) if line.startswith("VERSION"))
        self.assertEqual(lines[header].split(), ["VERSION", "SAVED", "SIZE", "MESSAGE"])
        self.assertEqual(lines[header + 1].split()[:2], ["3", "2026-10-09T14:00:00.000Z"])
        self.assertEqual(" ".join(lines[header + 2].split()[2:]), f"{len(PLAN[1].data)} B Added the contact")
        self.assertNotIn("AUTHOR", result.out)
        self.assertNotIn(ACCOUNT, result.out)

    def test_labels_of_none(self):
        self.assertRegex(run_cli("attachment", "att5111", "--labels", gateway=fresh()).out, r"Labels: +none")

    def test_the_json_has_the_properties_and_what_was_asked_for(self):
        plain = run_cli("attachment", "att5101", "--json", gateway=fresh()).json()
        self.assertEqual(set(plain), {"id", "title", "mediaType", "size", "version", "created", "updated", "pageId", "blogPostId", "downloadLink", "comment"})
        data = run_cli("attachment", "att5101", "--versions", "--labels", "--json", gateway=fresh()).json()
        self.assertEqual(set(data) - set(plain), {"versions", "nextCursor", "labels"})
        self.assertEqual(data["labels"], [{"name": "draft", "prefix": "global"}, {"name": "plan", "prefix": "global"}])
        self.assertEqual([version["number"] for version in data["versions"]], [3, 2, 1])
        self.assertEqual(set(data["versions"][0]), {"number", "created", "message", "minorEdit", "size", "author"})
        self.assertEqual([(version["minorEdit"], version["size"], version["author"]) for version in data["versions"]], [(True, len(PLAN[2].data), None), (False, len(PLAN[1].data), None), (False, len(PLAN[0].data), None)])
        only_labels = run_cli("attachment", "att5101", "--labels", "--json", gateway=fresh()).json()
        self.assertEqual(set(only_labels) - set(plain), {"labels"})

    def test_the_versions_are_paged_and_the_next_page_is_said_on_stderr(self):
        fake = FakeGateway()
        fake.page_cap = 2
        first = run_cli("attachment", "att5101", "--versions", "--limit", "2", gateway=fake)
        self.assertIn("--cursor 2", first.err)
        data = run_cli("attachment", "att5101", "--versions", "--limit", "2", "--json", gateway=fake)
        self.assertEqual((data.json()["nextCursor"], data.err), ("2", ""))
        last = run_cli("attachment", "att5101", "--versions", "--cursor", "2", "--json", gateway=fake).json()
        self.assertEqual(([version["number"] for version in last["versions"]], last["nextCursor"]), ([1], None))
        everything = run_cli("attachment", "att5101", "--versions", "--all", "--json", gateway=fake).json()
        self.assertEqual([version["number"] for version in everything["versions"]], [3, 2, 1])

    def test_select_and_format_work_on_the_versions(self):
        result = run_cli("attachment", "att5101", "--versions", "--select", "number,size", "--format", "tsv", gateway=fresh())
        self.assertEqual(result.out.splitlines(), ["number\tsize", f"3\t{len(PLAN[2].data)}", f"2\t{len(PLAN[1].data)}", f"1\t{len(PLAN[0].data)}"])
        data = run_cli("attachment", "att5101", "--versions", "--select", "number", "--json", gateway=fresh()).json()
        self.assertEqual(data["versions"], [{"number": 3}, {"number": 2}, {"number": 1}])
        self.assertEqual(data["id"], "att5101")  # what is no part of the list stays
        labels = run_cli("attachment", "att5101", "--labels", "--format", "md", gateway=fresh()).out
        self.assertEqual(labels.splitlines()[:3], ["| NAME | PREFIX |", "| --- | --- |", "| draft | global |"])

    def test_select_and_format_need_a_list(self):
        for extra in (("--select", "id"), ("--format", "tsv"), ("--cursor", "2"), ("--all",)):
            with self.subTest(extra=extra):
                result = run_cli("attachment", "att5101", *extra, gateway=fresh())
                self.assertEqual(result.code, 2)
                self.assertIn("--versions or --labels", result.err)

    def test_versions_and_labels_cannot_be_made_one_text_list_and_nothing_is_asked(self):
        for extra in (("--format", "tsv"), ("--format", "md"), ("--select", "number")):
            with self.subTest(extra=extra):
                fake = fresh()
                result = run_cli("attachment", "att5101", "--versions", "--labels", *extra, gateway=fake)
                self.assertEqual(result.code, 2)
                self.assertIn("--versions with --labels asks for two", result.err)
                self.assertIn("--json carries both", result.err)
                self.assertEqual((fake.calls, result.out), ([], ""))  # refused before anything was asked, and nothing was printed that leaves the labels out
        data = run_cli("attachment", "att5101", "--versions", "--labels", "--select", "number", "--json", gateway=fresh()).json()
        self.assertEqual(data["versions"], [{"number": 3}, {"number": 2}, {"number": 1}])
        self.assertEqual([label["name"] for label in data["labels"]], ["draft", "plan"])  # in JSON the select trims the versions and the labels stay
        as_json = run_cli("attachment", "att5101", "--versions", "--labels", "--format", "tsv", "--json", gateway=fresh())
        self.assertEqual(as_json.code, 2)
        self.assertIn("cannot be combined with --json", as_json.err)  # the older and more exact refusal is not hidden by the new one
        for argv in (("--versions", "--format", "tsv"), ("--labels", "--select", "name"), ("--versions", "--labels"), ("--versions", "--labels", "--format", "table")):
            self.assertEqual(run_cli("attachment", "att5101", *argv, gateway=fresh()).code, 0, argv)
        both = run_cli("attachment", "att5101", "--versions", "--labels", gateway=fresh()).out
        self.assertIn("Labels", both)  # the table of both is the one text that carries them
        self.assertIn("VERSION", both)

    def test_who_saved_a_version_is_shown_only_when_asked_for(self):
        shown = run_cli("attachment", "att5101", "--versions", "--with-users", gateway=fresh())
        self.assertEqual(shown.code, 0, shown.err)
        self.assertIn("AUTHOR", shown.out)
        self.assertIn("Alex Example", shown.out)
        data = run_cli("attachment", "att5101", "--versions", "--with-users", "--json", gateway=fresh()).json()
        self.assertEqual(data["versions"][0]["author"], {"accountId": ACCOUNT, "displayName": "Alex Example", "email": "alex@example.com"})
        refused = run_cli("attachment", "att5101", "--versions", "--with-users", settings=default_settings(hide_users=True), gateway=fresh())
        self.assertEqual(refused.code, 1)

    def test_a_version_message_is_redacted_unless_people_are_shown(self):
        fake = fresh()
        fake.attachment_versions["att5101"][1] = type(fake.attachment_versions["att5101"][1])(2, "2026-10-07T09:30:00.000Z", "Sent to alex@example.com", False)
        self.assertNotIn("alex@example.com", run_cli("attachment", "att5101", "--versions", gateway=fake).out)
        self.assertIn("Sent to alex@example.com", run_cli("attachment", "att5101", "--versions", "--with-users", gateway=fake).out)

    def test_the_sizes_that_were_not_asked_for_are_said_on_stderr(self):
        fake = fresh()
        editions = tuple(Edition(f"v{number}".encode(), "", False, f"2026-10-20T09:{number % 60:02d}:00.000Z") for number in range(1, 61))
        fake.add_attachment_fixture(Fixture("att5400", "2004", "long.txt", "text/plain", editions))
        result = run_cli("attachment", "att5400", "--versions", "--all", gateway=fake)
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("9 are left without", result.err)
        self.assertEqual(run_cli("attachment", "att5400", "--versions", "--all", "--json", gateway=fake).err, "")

    def test_errors_and_their_exit_codes(self):
        self.assertEqual(run_cli("attachment", "att999", gateway=fresh()).code, 4)
        self.assertEqual(run_cli("attachment", "2004", gateway=fresh()).code, 1)
        self.assertEqual(run_cli("attachment", gateway=fresh()).code, 2)
        self.assertEqual(run_cli("attachment", "att5101", "--versions", "--limit", "500", gateway=fresh()).code, 2)
        failing = fresh()
        failing.errors["list_attachment_versions"] = UnavailableError("Confluence answered with a server error (HTTP 503).")
        self.assertEqual(run_cli("attachment", "att5101", "--versions", gateway=failing).code, 7)

    def test_a_name_that_a_terminal_would_obey_is_taken_out_of_the_text(self):
        fake = fresh()
        fake.add_attachment_fixture(Fixture("att5302", "2004", "\x1b]0;owned\x07evil.txt", "text/plain", (Edition(b"x", "Msg \x1b[31mred", False, "2026-10-20T09:00:00.000Z"),), (), "c\x1b[2J"))
        text = run_cli("attachment", "att5302", "--versions", gateway=fake).out
        self.assertNotIn("\x1b", text)
        self.assertNotIn("\x07", text)
        self.assertIn("evil.txt", text)


class DownloadCommandTest(unittest.TestCase):
    def test_an_empty_output_folder_is_a_usage_error_and_not_the_current_folder(self):
        for value in ("", "  "):
            with self.subTest(value=value):
                files, gateway = MemoryFiles(), fresh()
                result = run_cli("download", "att5101", "--out", value, files=files, gateway=gateway)
                self.assertEqual((result.code, result.out), (2, ""))
                self.assertIn("The output folder is empty.", result.err)
                self.assertEqual((files.writes, gateway.calls), ([], []))  # nothing was asked and nothing written
        self.assertEqual(run_cli("download", "att5101", files=MemoryFiles(), gateway=fresh()).code, 0)  # no --out at all is the current folder

    def test_saving_prints_what_was_written_and_the_json_names_the_version(self):
        files = MemoryFiles()
        result = run_cli("download", "att5101", "--out", "out", files=files, gateway=fresh())
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(result.out.strip().split(), ["downloaded", "out/plan.txt", f"({len(PLAN[2].data)}", "B)"])
        self.assertEqual(files.files["out/plan.txt"], PLAN[2].data)
        data = run_cli("download", "2004", "--name", "plan.txt", "--name", "contacts.csv", "--out", "more", "--json", files=files, gateway=fresh()).json()
        self.assertEqual((data["dryRun"], data["count"]), (False, 2))
        self.assertEqual(data["files"][0], {"attachmentId": "att5101", "name": "plan.txt", "path": "more/plan.txt", "size": len(PLAN[2].data), "version": 3, "action": "downloaded"})

    def test_a_version_is_saved_and_named(self):
        files = MemoryFiles()
        result = run_cli("download", "att5101", "--version", "2", "--out", "out", files=files, gateway=fresh())
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(files.files["out/plan.txt"], PLAN[1].data)
        self.assertIn("version 2", result.out)
        data = run_cli("download", "att5101", "--version", "1", "--out", "o1", "--json", files=files, gateway=fresh()).json()
        self.assertEqual((data["files"][0]["version"], data["files"][0]["size"]), (1, len(PLAN[0].data)))

    def test_a_version_that_is_not_there_is_not_found(self):
        result = run_cli("download", "att5101", "--version", "9", "--out", "out", gateway=fresh())
        self.assertEqual(result.code, 4)
        self.assertIn("conflu attachment att5101 --versions", result.err)

    def test_a_version_that_cannot_be_is_a_usage_error(self):
        self.assertEqual(run_cli("download", "att5101", "--version", "0", "--out", "o", gateway=fresh()).code, 2)
        self.assertEqual(run_cli("download", "2004", "--all", "--version", "1", "--out", "o", gateway=fresh()).code, 2)
        self.assertEqual(run_cli("download", "2004", "--name", "plan.txt", "--name", "spec.docx", "--version", "1", "--out", "o", gateway=fresh()).code, 2)

    def test_the_files_of_a_blog_post(self):
        files = MemoryFiles()
        result = run_cli("download", "7102", "--all", "--out", "blog", files=files, gateway=fresh())
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(sorted(files.files), ["blog/agenda.txt", "blog/minutes.md"])
        self.assertEqual(files.files["blog/agenda.txt"], AGENDA[1].data)
        only = run_cli("download", "7102", "--name", "agenda.txt", "--version", "1", "--out", "v1", files=files, gateway=fresh())
        self.assertEqual(only.code, 0, only.err)
        self.assertEqual(files.files["v1/agenda.txt"], AGENDA[0].data)

    def test_a_dry_run_says_what_would_happen_and_writes_nothing(self):
        files = MemoryFiles()
        fake = fresh()
        result = run_cli("download", "7102", "--all", "--out", "dry", "--dry-run", files=files, gateway=fake)
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(result.out.count("would download"), 2)
        self.assertEqual((files.files, fake.called("fetch_attachment") + fake.called("download_attachment")), ({}, []))

    def test_a_file_that_is_there_stops_the_run_unless_force_is_given(self):
        files = MemoryFiles({"out/plan.txt": "mine"})
        result = run_cli("download", "att5101", "--out", "out", files=files, gateway=fresh())
        self.assertEqual(result.code, 1)
        self.assertIn("--force", result.err)
        self.assertEqual(files.files["out/plan.txt"], b"mine")
        self.assertEqual(run_cli("download", "att5101", "--out", "out", "--force", files=files, gateway=fresh()).code, 0)

    def test_a_file_over_max_bytes_is_refused_before_anything_is_fetched(self):
        files, fake = MemoryFiles(), fresh()
        result = run_cli("download", "2004", "--all", "--out", "out", "--max-bytes", "100", files=files, gateway=fake)
        self.assertEqual(result.code, 1)
        self.assertIn("--max-bytes 100", result.err)
        self.assertEqual((files.files, fake.called("download_attachment")), ({}, []))
        self.assertEqual(run_cli("download", "att5101", "--out", "out", "--max-bytes", "100", files=files, gateway=fake).code, 0)
        for bad in ("0", "-3"):
            self.assertEqual(run_cli("download", "att5101", "--out", "o", "--max-bytes", bad, gateway=fake).code, 2, bad)

    def test_a_name_with_an_address_is_printed_and_saved_redacted_unless_people_are_asked_for(self):
        fake = fresh()
        fake.add_attachment_fixture(Fixture("att5301", "2004", "alex@example.com-cv.txt", "text/plain", (Edition(b"cv data", "", False, "2026-10-20T09:00:00.000Z"),)))
        files = MemoryFiles()
        data = run_cli("download", "att5301", "--out", "out", "--json", files=files, gateway=fake).json()
        self.assertEqual(data["files"][0], {"attachmentId": "att5301", "name": "[email]", "path": "out/[email]", "size": 7, "version": 1, "action": "downloaded"})
        self.assertEqual(files.files, {"out/[email]": b"cv data"})
        plain = run_cli("download", "att5301", "--out", "text", files=files, gateway=fake)
        self.assertEqual(plain.out.split()[:2], ["downloaded", "text/[email]"])
        self.assertNotIn("alex", plain.out.lower())
        dry = run_cli("download", "att5301", "--out", "dry", "--dry-run", files=files, gateway=fake)
        self.assertNotIn("alex", dry.out.lower())
        own = run_cli("download", "att5301", "--out", "own", "--with-users", "--json", files=files, gateway=fake).json()["files"][0]
        self.assertEqual((own["name"], own["path"]), ("alex@example.com-cv.txt", "own/alex@example.com-cv.txt"))
        self.assertEqual(sorted(files.files), ["out/[email]", "own/alex@example.com-cv.txt", "text/[email]"])
        refused = run_cli("download", "att5301", "--out", "no", "--with-users", settings=default_settings(hide_users=True), files=files, gateway=fake)
        self.assertEqual((refused.code, refused.out), (1, ""))
        self.assertNotIn("no/", " ".join(files.files))

    def test_help_says_what_with_users_does_to_the_names(self):
        text = " ".join(run_cli("help", "download").out.split())
        self.assertIn("in names, which are then the names that attachments are saved under", text)
        self.assertIn("redacted, in the saved name too, unless you add --with-users", text)

    def test_a_run_that_stops_half_way_says_which_files_were_written_whatever_stopped_it(self):
        class Hostile(FakeGateway):
            def download_attachment(self, attachment):
                if attachment.id == "att5103":
                    raise ValueError("Port out of range 0-65535")
                return super().download_attachment(attachment)

        fake, files = Hostile(), MemoryFiles()
        fake.page_cap = 100
        result = run_cli("download", "2004", "--all", "--out", "out", files=files, gateway=fake)
        self.assertEqual(result.code, 7, result.err)
        self.assertIn("2 of the 6 files were written to out before that: plan.txt, spec.docx.", result.err)
        self.assertIn("unexpected ValueError", result.err)
        self.assertNotIn("Port out of range", result.err)
        self.assertEqual(sorted(files.files), ["out/plan.txt", "out/spec.docx"])
        as_json = run_cli("download", "2004", "--all", "--out", "again", "--json", files=files, gateway=fake)
        error = json.loads(as_json.err)["error"]
        self.assertEqual((as_json.code, error["code"], error["exitCode"]), (7, "UNAVAILABLE", 7))
        self.assertEqual([item["path"] for item in error["details"]["written"]], ["again/plan.txt", "again/spec.docx"])
        self.assertEqual(error["details"]["failed"], {"attachmentId": "att5103"})

    def test_the_folder_of_the_configuration_is_refused_with_every_option(self):
        files = PlacedFiles({CONFIG: "CONFLUENCE_API_TOKEN=secret-token\n"})
        store = MemoryConfigStore(path=CONFIG)
        for extra in ((), ("--force",), ("--dry-run",), ("--force", "--dry-run")):
            with self.subTest(extra=extra):
                result = run_cli("download", "att5101", "--out", "/home/me/.config/conflu-c-cli", *extra, files=files, store=store, gateway=fresh())
                self.assertEqual(result.code, 2)
                self.assertIn("--out", result.err)
        self.assertEqual(files.files, {CONFIG: b"CONFLUENCE_API_TOKEN=secret-token\n"})

    def test_help_shows_the_default_place_and_the_new_options(self):
        text = run_cli("help", "download").out
        for option in ("--version N", "--max-bytes N", "--text", "--max-chars N", "--with-users"):
            self.assertIn(option, text)
        self.assertIn("Default: .", text)

    def test_errors_and_their_exit_codes(self):
        self.assertEqual(run_cli("download", "2004", gateway=fresh()).code, 2)  # nothing chosen
        self.assertEqual(run_cli("download", "att5101", "--all", "--out", "o", gateway=fresh()).code, 2)
        self.assertEqual(run_cli("download", "att999", "--out", "o", gateway=fresh()).code, 4)
        self.assertEqual(run_cli("download", "2004", "--name", "none.txt", "--out", "o", gateway=fresh()).code, 4)
        self.assertEqual(run_cli("download", "999", "--all", "--out", "o", gateway=fresh()).code, 4)
        self.assertEqual(run_cli("download", "att5101", "--out", "o", "--with-users", settings=default_settings(hide_users=True), gateway=fresh()).code, 1)


class TextCommandTest(unittest.TestCase):
    def test_the_text_of_a_text_file_and_of_documents(self):
        result = run_cli("download", "2004", "--all", "--text", gateway=fresh())
        self.assertEqual(result.code, 0, result.err)
        out = result.out
        self.assertIn(f"--- att5101 plan.txt (text/plain, {len(PLAN[2].data)} B)\nRelease plan\n\nFinal version.", out)
        self.assertIn("# Specification\nThe scope is small. Questions go to [email].", out)
        self.assertIn("## Plan\nItem\tAmount\nHardware\t1200", out)
        self.assertIn("## Slide 1", out)
        self.assertIn("Release Team,[email]", out)
        self.assertNotIn("alex@example.com", out)
        self.assertIn("\n\n--- att5102", out)  # the files are told apart by a line of their own

    def test_nothing_is_written_and_nothing_is_saved(self):
        files = MemoryFiles()
        run_cli("download", "att5101", "--text", files=files, gateway=fresh())
        self.assertEqual((files.files, files.writes), ({}, []))

    def test_the_json(self):
        data = run_cli("download", "att5102", "--text", "--json", gateway=fresh()).json()
        self.assertEqual((data["dryRun"], data["count"]), (False, 1))
        entry = data["files"][0]
        self.assertEqual(set(entry), {"attachmentId", "name", "mediaType", "size", "version", "kind", "action", "text", "truncated", "totalChars", "hint"})
        self.assertEqual((entry["attachmentId"], entry["name"], entry["kind"], entry["action"], entry["truncated"], entry["hint"]), ("att5102", "spec.docx", "document", "read", False, None))
        self.assertEqual(entry["totalChars"], len(entry["text"]))
        self.assertIn("[email]", entry["text"])

    def test_a_picture_gives_its_properties_and_a_hint_and_the_json_has_no_text(self):
        result = run_cli("download", "att5001", "--text", gateway=fresh())
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("--- att5001 diagram.png (image/png, 10 B)", result.out)
        self.assertIn("conflu download att5001", result.out)
        entry = run_cli("download", "att5001", "--text", "--json", gateway=fresh()).json()["files"][0]
        self.assertEqual((entry["kind"], entry["action"], entry["text"], entry["totalChars"], entry["truncated"]), ("other", "not text", None, None, False))
        self.assertIn("conflu download att5001", entry["hint"])

    def test_a_damaged_document_is_a_hint_and_the_run_goes_on_and_ends_well(self):
        result = run_cli("download", "2004", "--name", "broken.docx", "--name", "plan.txt", "--text", gateway=fresh())
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("no Office Open XML document", result.out)
        self.assertIn("Final version.", result.out)
        self.assertNotIn("this is no document", result.out)

    def test_the_text_is_cut_and_the_cut_is_said(self):
        text = run_cli("download", "att5101", "--text", "--max-chars", "30", gateway=fresh())
        self.assertEqual(text.code, 0, text.err)
        self.assertIn("[cut: ", text.out)
        self.assertIn("characters shown. --max-chars shows more; `conflu download att5101` saves the file]", text.out)
        entry = run_cli("download", "att5101", "--text", "--max-chars", "30", "--json", gateway=fresh()).json()["files"][0]
        self.assertTrue(entry["truncated"])
        self.assertEqual(entry["totalChars"], len(PLAN[2].data))
        self.assertLessEqual(len(entry["text"]), 30)

    def test_a_version_is_read_and_named_in_the_head(self):
        result = run_cli("download", "att5101", "--text", "--version", "1", gateway=fresh())
        self.assertIn(f"({'text/plain'}, {len(PLAN[0].data)} B, version 1)", result.out)
        self.assertIn("First draft.", result.out)
        self.assertNotIn("Final version.", result.out)

    def test_the_text_of_a_blog_post_attachment(self):
        result = run_cli("download", "7102", "--name", "minutes.md", "--text", gateway=fresh())
        self.assertIn("Decisions were made.", result.out)

    def test_people_are_kept_only_when_asked_for_and_refused_under_the_policy(self):
        shown = run_cli("download", "att5105", "--text", "--with-users", gateway=fresh())
        self.assertIn("alex@example.com", shown.out)
        refused = run_cli("download", "att5105", "--text", "--with-users", settings=default_settings(hide_users=True), gateway=fresh())
        self.assertEqual(refused.code, 1)
        self.assertEqual(refused.out, "")

    def test_a_dry_run_fetches_nothing(self):
        fake = fresh()
        result = run_cli("download", "2004", "--all", "--text", "--dry-run", gateway=fake)
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(result.out.count("would be read as text"), 6)
        self.assertEqual(fake.called("fetch_attachment") + fake.called("download_attachment"), [])
        data = run_cli("download", "2004", "--all", "--text", "--dry-run", "--json", gateway=fake).json()
        self.assertEqual((data["dryRun"], {entry["action"] for entry in data["files"]}, {entry["text"] for entry in data["files"]}), (True, {"would read"}, {None}))

    def test_a_dry_run_says_what_the_limit_would_refuse(self):
        result = run_cli("download", "2004", "--all", "--text", "--dry-run", "--max-bytes", "100", gateway=fresh())
        self.assertEqual(result.out.count("too large, it would be refused"), 3)

    def test_a_file_over_the_limit_is_refused(self):
        result = run_cli("download", "2004", "--all", "--text", "--max-bytes", "100", gateway=fresh())
        self.assertEqual(result.code, 1)
        self.assertEqual(result.out, "")

    def test_a_file_that_is_longer_than_it_was_said_to_be_is_refused_and_nothing_is_printed_of_it(self):
        fake = fresh()
        items = fake.attachments["2004"]
        items[0] = dataclasses.replace(items[0], size=1)  # what Confluence says: one byte
        fake.attachment_data["att5101"] = b"x" * 5000  # what arrives
        result = run_cli("download", "att5101", "--text", "--max-bytes", "100", gateway=fake)
        self.assertEqual(result.code, 1)
        self.assertEqual(result.out, "")
        self.assertIn("plan.txt arrived with 4.9 KB, more than --max-bytes 100 (100 B); nothing was read from it.", result.err)
        again = run_cli("download", "att5101", "--text", "--max-bytes", "100", "--json", gateway=fake)
        self.assertEqual((again.code, json.loads(again.err)["error"]["details"]), (1, {"attachmentId": "att5101", "size": 5000, "maxBytes": 100}))

    def test_out_and_force_are_for_saving(self):
        for extra in (("--out", "tmp"), ("--force",), ("--out", "tmp", "--force")):
            with self.subTest(extra=extra):
                result = run_cli("download", "att5101", "--text", *extra, gateway=fresh())
                self.assertEqual(result.code, 2)
                self.assertIn("--text", result.err)
                self.assertEqual(result.out, "")

    def test_max_chars_is_for_text(self):
        result = run_cli("download", "att5101", "--max-chars", "10", "--out", "o", gateway=fresh())
        self.assertEqual(result.code, 2)
        self.assertEqual(run_cli("download", "att5101", "--text", "--max-chars", "0", gateway=fresh()).code, 2)

    def test_what_a_terminal_would_obey_in_a_file_is_taken_out(self):
        fake = fresh()
        hostile = "plain\x1b[31m red \x1b]0;a title\x07and \u202egnp\u200b hidden " + "".join(chr(0xE0000 + ord(letter)) for letter in "ignore") + " end\n"
        fake.add_attachment_fixture(Fixture("att5303", "2004", "hostile.txt", "text/plain", (Edition(hostile.encode("utf-8"), "", False, "2026-10-20T09:00:00.000Z"),)))
        result = run_cli("download", "att5303", "--text", gateway=fake)
        self.assertIn("plain red and gnp hidden  end", result.out)
        for char in ("\x1b", "\x07", "\u202e", "\u200b", chr(0xE0069)):
            self.assertNotIn(char, result.out)
        entry = run_cli("download", "att5303", "--text", "--json", gateway=fake).json()["files"][0]
        for char in ("\x1b", "\x07", "\u202e", "\u200b", chr(0xE0069)):
            self.assertNotIn(char, entry["text"])


class AttachCommandTest(unittest.TestCase):
    def setUp(self):
        self.files = PlacedFiles({"in/new.txt": "fresh", "in/plan.txt": "a new plan\n"})
        self.store = MemoryConfigStore(path=CONFIG)

    def run_attach(self, *argv, gateway=None, **options):
        return run_cli("attach", *argv, files=self.files, store=self.store, gateway=gateway or fresh(), **options)

    def test_a_dry_run_shows_which_file_replaces_which_attachment_and_sends_nothing(self):
        fake = fresh()
        result = self.run_attach("2004", "in/plan.txt", "in/new.txt", "--dry-run", gateway=fake)
        self.assertEqual(result.code, 0, result.err)
        lines = result.out.splitlines()
        self.assertEqual(lines[0], "Dry run: nothing was sent.")
        self.assertEqual(lines[1].split(), ["ACTION", "NAME", "SIZE", "REPLACES", "VERSION"])
        self.assertEqual(lines[2].split(), ["would", "upload", "plan.txt", "11", "B", "att5101", "3", "->", "4"])
        self.assertEqual(lines[3].split(), ["would", "upload", "new.txt", "5", "B", "1"])
        self.assertEqual(fake.called("upload_attachment"), [])

    def test_the_json_of_a_dry_run_and_of_a_real_run(self):
        fake = fresh()
        dry = self.run_attach("2004", "in/plan.txt", "--comment", "October", "--minor", "--dry-run", "--json", gateway=fake).json()
        self.assertEqual((dry["pageId"], dry["dryRun"], dry["comment"], dry["minorEdit"]), ("2004", True, "October", True))
        self.assertEqual(dry["files"], [{"path": "in/plan.txt", "name": "plan.txt", "size": 11, "action": "would upload", "attachmentId": None, "version": None, "replaces": "att5101", "versionFrom": 3, "versionTo": 4}])
        done = self.run_attach("2004", "in/plan.txt", "in/new.txt", "--json", gateway=fake).json()
        self.assertEqual((done["comment"], done["minorEdit"], done["dryRun"]), (None, False, False))
        self.assertEqual([(item["name"], item["action"], item["replaces"], item["versionFrom"], item["versionTo"], item["version"]) for item in done["files"]], [("plan.txt", "uploaded", "att5101", 3, 4, 4), ("new.txt", "uploaded", None, None, 1, 1)])
        self.assertTrue(all(item["attachmentId"] for item in done["files"]))
        self.assertEqual(fake.called("upload_attachment")[0][1:], ("2004", "plan.txt", b"a new plan\n", "", False))

    def test_the_text_of_a_real_run_has_the_ids_and_versions(self):
        result = self.run_attach("2004", "in/plan.txt", "in/new.txt")
        self.assertEqual(result.code, 0, result.err)
        lines = result.out.splitlines()
        self.assertEqual(lines[0].split(), ["ACTION", "NAME", "SIZE", "ATTACHMENT", "VERSION"])
        self.assertEqual(lines[1].split()[:6], ["uploaded", "plan.txt", "11", "B", "att5101", "4"])

    def test_when_the_attachments_of_the_page_cannot_be_read_for_want_of_permission_the_files_go_and_the_output_does_not_pretend_to_know(self):
        def refusing():
            fake = fresh()
            fake.errors["list_attachments"] = AuthError("Confluence refused this request (HTTP 403).", details={"status": 403})
            return fake

        dry = self.run_attach("2004", "in/plan.txt", "in/new.txt", "--dry-run", gateway=refusing())
        self.assertEqual(dry.code, 0, dry.err)
        self.assertIn("Could not read the attachments of page 2004", dry.err)
        self.assertIn("the files would be sent", dry.err)
        rows = [line.split() for line in dry.out.splitlines()[2:]]
        self.assertEqual(rows, [["would", "upload", "plan.txt", "11", "B", "?", "?"], ["would", "upload", "new.txt", "5", "B", "?", "?"]])
        as_json = self.run_attach("2004", "in/plan.txt", "--dry-run", "--json", gateway=refusing()).json()
        self.assertEqual([(item["replaces"], item["versionFrom"], item["versionTo"]) for item in as_json["files"]], [(None, None, None)])
        fake = refusing()
        done = self.run_attach("2004", "in/plan.txt", "in/new.txt", "--json", gateway=fake)
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(len(fake.called("upload_attachment")), 2)
        self.assertEqual([(item["action"], item["replaces"], item["versionFrom"], item["versionTo"]) for item in done.json()["files"]], [("uploaded", None, None, 4), ("uploaded", None, None, 1)])
        guarded = self.run_attach("2004", "in/plan.txt", "--if-version", "3", gateway=refusing())
        self.assertEqual(guarded.code, 5, guarded.err)  # a guard needs the read: the refusal stops the command, nothing is sent

    def test_any_other_failure_of_the_read_is_the_failure_of_the_command_in_a_dry_run_and_in_a_real_run(self):
        for error, code in ((UnavailableError("Confluence answered with a server error (HTTP 500).", details={"status": 500}), 7), (AuthError("Confluence did not accept the credentials (HTTP 401).", details={"status": 401}), 5)):
            for dry in ((), ("--dry-run",)):
                with self.subTest(code=code, dry=dry):
                    fake = fresh()
                    fake.errors["list_attachments"] = error
                    result = self.run_attach("2004", "in/plan.txt", *dry, gateway=fake)
                    self.assertEqual((result.code, result.out), (code, ""))
                    self.assertEqual(fake.called("upload_attachment"), [])

    def test_the_conflict_guards_are_exit_code_3_and_keep_to_a_dry_run(self):
        for extra in (("--if-version", "2"), ("--if-unchanged-since", "2026-10-09T13:00:00Z")):
            for dry in ((), ("--dry-run",)):
                with self.subTest(extra=extra, dry=dry):
                    fake = fresh()
                    result = self.run_attach("2004", "in/plan.txt", *extra, *dry, gateway=fake)
                    self.assertEqual(result.code, 3)
                    self.assertEqual(fake.called("upload_attachment"), [])
        ok = self.run_attach("2004", "in/plan.txt", "--if-version", "3", "--if-unchanged-since", "2026-10-09T14:00:00Z")
        self.assertEqual(ok.code, 0, ok.err)

    def test_the_guards_for_what_cannot_be_asked(self):
        self.assertEqual(self.run_attach("2004", "in/plan.txt", "in/new.txt", "--if-version", "3").code, 2)
        self.assertEqual(self.run_attach("2004", "in/plan.txt", "--if-version", "-1").code, 2)
        self.assertEqual(self.run_attach("2004", "in/plan.txt", "--if-unchanged-since", "yesterday").code, 1)

    def test_an_empty_guard_time_is_an_error_that_names_the_option_in_a_dry_run_too_and_nothing_is_asked(self):
        for value in ("", " "):
            for dry in ((), ("--dry-run",)):
                with self.subTest(value=value, dry=dry):
                    fake = fresh()
                    result = self.run_attach("2004", "in/plan.txt", "--if-unchanged-since", value, *dry, gateway=fake)  # the file is the one that the page has: the guard would have counted
                    self.assertEqual(result.code, 1)
                    self.assertIn("--if-unchanged-since", result.err)
                    self.assertEqual((fake.calls, result.out), ([], ""))  # not asked, so not sent
        self.assertEqual(self.run_attach("2004", "in/plan.txt", "--dry-run").code, 0)  # no option at all is no guard

    def test_a_run_that_fails_after_it_uploaded_says_which_files_went(self):
        class Failing(FakeGateway):
            def upload_attachment(self, page_id, filename, data, *, comment="", minor=False):
                if filename == "new.txt":
                    raise UnavailableError("Cannot reach Confluence (TimeoutError: timed out).", hint="Check the network.")
                return super().upload_attachment(page_id, filename, data, comment=comment, minor=minor)

        def failing():
            fake = Failing()
            fake.page_cap = 100
            return fake

        result = self.run_attach("2004", "in/plan.txt", "in/new.txt", gateway=failing())
        self.assertEqual((result.code, result.out), (7, ""))
        self.assertIn("Cannot reach Confluence (TimeoutError: timed out). 1 of the 2 files were uploaded to page 2004 before that: plan.txt.", result.err)
        self.assertIn("do not run the same command as it is", result.err)
        self.assertIn("`conflu attachments 2004`", result.err)
        self.assertIn("the files that are left: new.txt.", result.err)
        as_json = self.run_attach("2004", "in/plan.txt", "in/new.txt", "--json", gateway=failing())
        error = as_json.error()
        self.assertEqual((as_json.code, error["code"], error["exitCode"]), (7, "UNAVAILABLE", 7))
        self.assertEqual([(item["name"], item["path"], item["version"]) for item in error["details"]["uploaded"]], [("plan.txt", "in/plan.txt", 4)])
        self.assertEqual(error["details"]["failed"], {"path": "in/new.txt", "name": "new.txt"})

    def test_the_configuration_and_a_file_that_holds_the_token_are_refused_in_a_dry_run_too(self):
        self.files.put(CONFIG, b"CONFLUENCE_EMAIL=user@example.com\nCONFLUENCE_API_TOKEN=secret-token\n")
        self.files.put("in/log.txt", "GET /wiki Authorization: token secret-token".encode("utf-16"))
        for path in (CONFIG, "/work/../home/me/.config/conflu-c-cli/config", "in/log.txt"):
            for dry in ((), ("--dry-run",)):
                with self.subTest(path=path, dry=dry):
                    fake = fresh()
                    result = self.run_attach("2004", "in/new.txt", path, *dry, gateway=fake)
                    self.assertEqual(result.code, 2)
                    self.assertNotIn("secret-token", result.err)
                    self.assertEqual(fake.calls, [])
                    self.assertEqual(result.out, "")

    def test_an_error_names_the_file_and_never_the_token_in_json_too(self):
        self.files.put("in/log.txt", b"token=secret-token")
        result = self.run_attach("2004", "in/log.txt", "--json")
        self.assertEqual(result.code, 2)
        error = result.error()
        self.assertEqual((error["code"], error["exitCode"]), ("USAGE", 2))
        self.assertIn("in/log.txt holds the API token", error["message"])
        self.assertNotIn("secret-token", result.err)

    def test_missing_files_nothing_to_attach_and_a_page_that_is_none(self):
        self.assertEqual(self.run_attach("2004", "in/missing.txt").code, 1)
        self.assertEqual(self.run_attach("2004", "in").code, 1)
        self.assertEqual(self.run_attach("2004").code, 2)
        self.assertEqual(self.run_attach("999", "in/new.txt").code, 4)
        result = self.run_attach("7102", "in/new.txt")
        self.assertEqual(result.code, 4)
        self.assertIn("a blog post", result.err)

    def test_help_keeps_the_old_beginning_of_the_usage(self):
        self.assertIn("Usage: conflu attach PAGE FILE... [--comment TEXT] [--minor] [--dry-run]", run_cli("help", "attach").out)


if __name__ == "__main__":
    unittest.main()
