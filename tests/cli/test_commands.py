"""Every command through the command line, with fakes behind it: output, JSON shapes, exit codes."""
import io
import json
import unittest

from conflu_c_cli.adapters.driving.cli.runtime import StderrDiagnostics
from conflu_c_cli.domain.errors import AuthError, ConflictError, RejectedError
from conflu_c_cli.version import __version__
from tests.support.cli import run_cli
from tests.support.fakes import ACCOUNT, BASE, FakeGateway, MemoryConfigStore, MemoryFiles, default_settings


class PageCommandTest(unittest.TestCase):
    def test_the_page_as_text(self):
        result = run_cli("page", "2002")
        self.assertEqual(result.code, 0, result.err)
        out = result.out
        self.assertTrue(out.startswith("Release notes  [2002]\n"))
        self.assertIn(f"{BASE}/spaces/ENG/pages/2002/Release+notes", out)
        for text in ("Space:", "ENG", "Version:", "Labels:", "release, notes", "# Release notes", "First", "Comments: show them with --comments"):
            self.assertIn(text, out)
        self.assertNotIn(ACCOUNT, out)
        self.assertNotIn("alex@example.com", out)
        self.assertNotIn("Author:", out)
        self.assertIn("macro:toc, mention", result.err)  # what the Markdown cannot show goes to stderr

    def test_the_json_shape(self):
        data = run_cli("page", "2002", "--json").json()
        self.assertEqual(
            set(data),
            {"id", "title", "status", "spaceId", "spaceKey", "parentId", "parentType", "url", "version", "created", "updated", "labels", "author", "owner", "body"},
        )
        self.assertEqual((data["id"], data["spaceKey"], data["parentId"], data["labels"]), ("2002", "ENG", "2001", ["release", "notes"]))
        self.assertEqual((data["parentType"], run_cli("page", "2001", "--json").json()["parentType"]), ("page", None))  # a page without a parent has no parent type
        self.assertEqual((data["author"], data["owner"], data["version"]["author"]), (None, None, None))
        self.assertEqual(data["version"]["number"], 3)
        self.assertEqual(data["body"]["format"], "markdown")
        self.assertEqual(data["body"]["dropped"], ["macro:toc", "mention", "redacted-text"])
        self.assertNotIn(ACCOUNT, json.dumps(data))

    def test_storage_format_and_text_format(self):
        storage = run_cli("page", "2002", "--format", "storage", "--json").json()["body"]
        self.assertEqual(storage["format"], "storage")
        self.assertIn("<h1>Release notes</h1>", storage["value"])
        self.assertNotIn(ACCOUNT, storage["value"])
        plain = run_cli("page", "2002", "--format", "text").out
        self.assertIn("Release notes", plain)
        self.assertNotIn("# Release notes", plain)
        self.assertNotIn("**", plain)

    def test_no_body_comments_and_ancestors(self):
        data = run_cli("page", "2004", "--no-body", "--ancestors", "--json").json()
        self.assertIsNone(data["body"])
        self.assertEqual([item["id"] for item in data["ancestors"]], ["2001", "2003"])
        text = run_cli("page", "2004", "--ancestors", "--no-body").out
        self.assertIn("Engineering Home > Architecture > ADR 0001", text)
        comments = run_cli("page", "2002", "--comments").out
        self.assertIn("Comments: 2", comments)
        self.assertIn("--- #4001 footer", comments)
        self.assertIn("    --- #4002 footer", comments)
        self.assertIn("(reply to #4001)", comments)
        data = run_cli("page", "2002", "--comments", "--json").json()
        self.assertEqual([item["id"] for item in data["comments"]], ["4001", "4002"])
        self.assertEqual(data["comments"][1]["parentId"], "4001")

    def test_with_users_names_people(self):
        out = run_cli("page", "2002", "--with-users").out
        self.assertIn("Author:", out)
        self.assertIn("Alex Example", out)
        data = run_cli("page", "2002", "--with-users", "--json").json()
        self.assertEqual(data["author"], {"accountId": ACCOUNT, "displayName": "Alex Example", "email": "alex@example.com"})

    def test_the_policy_refuses_with_users(self):
        result = run_cli("page", "2002", "--with-users", settings=default_settings(hide_users=True))
        self.assertEqual(result.code, 1)
        self.assertIn("CONFLUENCE_HIDE_USERS", result.err)

    def test_raw_is_confluences_own_json_without_people(self):
        raw = json.loads(run_cli("page", "2002", "--raw").out)
        self.assertEqual(raw["title"], "Release notes")
        self.assertNotIn(ACCOUNT, json.dumps(raw))

    def test_the_body_alone_for_a_file_or_a_pipe(self):
        markdown = run_cli("page", "2005", "--body-only")
        self.assertEqual((markdown.code, markdown.out), (0, "Just a paragraph & text.\n"))
        storage = run_cli("page", "2002", "--body-only", "--format", "storage", "--with-users")
        self.assertTrue(storage.out.startswith("<h1>Release notes</h1>"))
        self.assertIn(ACCOUNT, storage.out)
        self.assertNotIn("Release notes  [2002]", storage.out)
        self.assertEqual(run_cli("page", "2005", "--body-only", "--json").out, "Just a paragraph & text.\n")  # an explicit flag wins
        self.assertIn("macro:toc", run_cli("page", "2002", "--body-only").err)
        for extra in ("--no-body", "--raw", "--comments", "--ancestors"):
            with self.subTest(extra=extra):
                self.assertEqual(run_cli("page", "2005", "--body-only", extra).code, 2)

    def test_a_page_address_works_and_errors_have_exit_codes(self):
        self.assertEqual(run_cli("page", f"{BASE}/spaces/ENG/pages/2003/Architecture", "--json").json()["id"], "2003")
        self.assertEqual(run_cli("page", "999").code, 4)
        self.assertEqual(run_cli("page", "abc").code, 1)

    def test_json_by_default_from_the_settings_or_the_environment(self):
        self.assertEqual(run_cli("page", "2005", settings=default_settings(output="json")).json()["id"], "2005")
        self.assertEqual(run_cli("page", "2005", environ={"CONFLUENCE_OUTPUT": "json"}).json()["id"], "2005")


class ListCommandsTest(unittest.TestCase):
    def test_pages_table_and_the_hint_for_more(self):
        result = run_cli("pages", "--space", "ENG", "--limit", "2")
        self.assertEqual(result.code, 0, result.err)
        lines = result.out.splitlines()
        self.assertEqual(lines[0].split(), ["ID", "TITLE", "STATUS", "VERSION", "UPDATED"])
        self.assertEqual([line.split()[0] for line in lines[1:]], ["2001", "2002"])
        self.assertIn("--cursor 2", result.err)

    def test_pages_json_and_paging(self):
        data = run_cli("pages", "--space", "ENG", "--limit", "2", "--json").json()
        self.assertEqual((data["space"], data["count"], data["nextCursor"], data["truncated"]), ("ENG", 2, "2", False))
        self.assertEqual(set(data["pages"][0]), {"id", "title", "status", "spaceId", "parentId", "version", "updated", "url"})
        more = run_cli("pages", "--space", "ENG", "--limit", "2", "--cursor", "2", "--json").json()
        self.assertEqual([page["id"] for page in more["pages"]], ["2003", "2004"])
        everything = run_cli("pages", "--space", "ENG", "--all", "--json").json()
        self.assertEqual((everything["count"], everything["nextCursor"]), (5, None))

    def test_pages_of_the_current_space_and_without_any(self):
        self.assertEqual(run_cli("pages", "--all", "--json", settings=default_settings(space="DOCS")).json()["space"], "DOCS")
        self.assertIsNone(run_cli("pages", "--all", "--json").json()["space"])
        self.assertEqual(run_cli("pages", "--space", "ENG", "--title", "Plain page", "--json").json()["count"], 1)
        self.assertEqual(run_cli("pages", "--space", "ENG", "--title", "Nothing", "--json").json()["count"], 0)
        self.assertEqual(run_cli("pages", "--space", "ENG", "--title", "Nothing").out, "No pages.\n")

    def test_pages_sorted_downwards(self):
        gateway = FakeGateway()
        data = run_cli("pages", "--space", "ENG", "--sort", "id", "--desc", "--limit", "2", "--json", gateway=gateway).json()
        self.assertEqual([page["id"] for page in data["pages"]], ["2005", "2004"])
        self.assertEqual(gateway.called("list_pages")[0][5], "-id")
        self.assertEqual(run_cli("pages", "--space", "ENG", "--sort", "title", "--json").json()["pages"][0]["title"], "ADR 0001")
        self.assertEqual(run_cli("pages", "--space", "ENG", "--desc").code, 2)
        self.assertEqual(run_cli("pages", "--space", "ENG", "--sort", "-id").code, 2)

    def test_pages_argument_errors(self):
        self.assertEqual(run_cli("pages", "--limit", "0").code, 2)
        self.assertEqual(run_cli("pages", "--limit", "251").code, 2)
        self.assertEqual(run_cli("pages", "--root").code, 2)
        self.assertEqual(run_cli("pages", "--space", "NOPE").code, 4)

    def test_tree(self):
        result = run_cli("tree", "2001")
        self.assertEqual(
            result.out.splitlines(),
            ["Engineering Home  [2001]", "  Architecture  [2003]", "    ADR 0001  [2004]", "  Plain page  [2005]", "  Release notes  [2002]"],
        )
        data = run_cli("tree", "2001", "--depth", "1", "--json").json()
        self.assertEqual((data["root"], data["depth"], data["truncated"]), ({"id": "2001", "title": "Engineering Home", "type": "page", "spaceKey": "ENG"}, 1, False))
        self.assertEqual([(node["id"], node["parentId"], node["depth"]) for node in data["nodes"]], [("2003", "2001", 1), ("2005", "2001", 1), ("2002", "2001", 1)])
        self.assertIn("(no pages below this one)", run_cli("tree", "2004").out)
        self.assertEqual(run_cli("tree", "2001", "--depth", "11").code, 2)

    def test_versions(self):
        result = run_cli("versions", "2002", "--all")
        self.assertEqual(result.out.splitlines()[0].split(), ["NUMBER", "SAVED", "MESSAGE"])
        self.assertIn("Added the October notes", result.out)
        data = run_cli("versions", "2002", "--limit", "2", "--json").json()
        self.assertEqual((data["pageId"], data["count"], data["nextCursor"]), ("2002", 2, "2"))
        self.assertEqual(set(data["versions"][0]), {"number", "created", "message", "minorEdit", "author"})
        self.assertIsNone(data["versions"][0]["author"])
        self.assertIn("AUTHOR", run_cli("versions", "2002", "--with-users").out)

    def test_search_table_json_and_raw(self):
        gateway = FakeGateway()
        result = run_cli("search", "ports", "--space", "ENG", gateway=gateway)
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(result.out.splitlines()[0].split(), ["ID", "TYPE", "SPACE", "TITLE", "MODIFIED", "PATH"])
        self.assertIn("Showing 2 of 3", result.err)
        self.assertEqual(gateway.called("search")[0][1], 'type = page AND space = "ENG" AND text ~ "ports"')
        data = run_cli("search", "ports", "--all", "--json").json()
        self.assertEqual((data["total"], data["count"], data["truncated"]), (3, 3, False))
        self.assertEqual(set(data["hits"][0]), {"id", "type", "title", "spaceKey", "path", "labels", "version", "url", "excerpt", "snippet", "matched", "lastModified"})
        self.assertEqual({hit["excerpt"] for hit in data["hits"]}, {None})  # it can name people
        raw = json.loads(run_cli("search", "ports", "--raw").out)
        self.assertEqual(raw["total"], 3)
        self.assertNotIn(ACCOUNT, json.dumps(raw))
        self.assertEqual({item["excerpt"] for item in raw["results"]}, {None})

    def test_excerpts_need_with_users_because_they_can_name_people(self):
        hidden = run_cli("search", "x", "--excerpts", "--limit", "1")
        self.assertEqual(hidden.code, 0, hidden.err)
        self.assertNotIn("the october notes", hidden.out)
        self.assertEqual(hidden.out.splitlines()[0].split(), ["ID", "TYPE", "SPACE", "TITLE", "MODIFIED", "PATH"])  # the table, not the excerpts
        self.assertIn("--with-users", hidden.err)
        shown = run_cli("search", "x", "--excerpts", "--with-users", "--limit", "1")
        self.assertIn("    the october notes", shown.out)
        self.assertNotIn("Excerpts can name people", shown.err)
        self.assertEqual(run_cli("search", "x", "--with-users", "--limit", "1", "--json").json()["hits"][0]["excerpt"], "the october notes")
        self.assertEqual(run_cli("search", "x", "--with-users", "--limit", "1", "--raw").out.count("the october notes"), 1)

    def test_the_policy_forbids_the_excerpts_altogether(self):
        policy = default_settings(hide_users=True)
        refused = run_cli("search", "x", "--with-users", settings=policy)
        self.assertEqual(refused.code, 1)
        self.assertIn("CONFLUENCE_HIDE_USERS", refused.err)
        self.assertEqual(run_cli("search", "x", "--json", settings=policy).json()["hits"][0]["excerpt"], None)

    def test_search_errors(self):
        self.assertEqual(run_cli("search").code, 1)
        self.assertEqual(run_cli("search", "x", "--since", "yesterday").code, 1)
        self.assertEqual(run_cli("search", "x", "--type", "space").code, 2)
        self.assertEqual(run_cli("search", "x", "--start", "-1").code, 2)

    def test_spaces_and_space(self):
        table = run_cli("spaces").out.splitlines()
        self.assertEqual(table[0].split(), ["KEY", "NAME", "TYPE", "STATUS", "HOMEPAGE"])
        data = run_cli("spaces", "--all", "--json").json()
        self.assertEqual([space["key"] for space in data["spaces"]], ["DOCS", "ENG"])
        self.assertEqual(set(data["spaces"][0]), {"id", "key", "name", "type", "status", "homepageId", "description", "created", "url"})
        shown = run_cli("space", "ENG").out
        self.assertTrue(shown.startswith("ENG\n"))
        self.assertIn("Engineering documentation", shown)
        self.assertEqual(run_cli("space", "--json", settings=default_settings(space="DOCS")).json()["key"], "DOCS")
        self.assertEqual(run_cli("space").code, 2)
        self.assertEqual(run_cli("space", "NOPE").code, 4)


class TerminalSafetyTest(unittest.TestCase):
    """Text that other people wrote must not be able to drive the terminal of the reader."""

    def setUp(self):
        self.gateway = FakeGateway()
        self.gateway.pages["2005"].title = "Plain\x1b[2J\x1b]0;owned\x07 page\x9b"
        self.gateway.pages["2005"].body = "<p>Text\x1b[31m red \x08\x08 \x00 end</p>"

    def test_control_characters_are_not_printed(self):
        for argv in (("pages", "--space", "ENG", "--all"), ("page", "2005"), ("tree", "2001"), ("export", "--space", "ENG", "--out", "out", "--dry-run")):
            result = run_cli(*argv, gateway=self.gateway)
            with self.subTest(argv=argv):
                self.assertEqual(result.code, 0, result.err)
                for char in ("\x1b", "\x07", "\x08", "\x00", "\x9b"):
                    self.assertNotIn(char, result.out)
        self.assertIn("Plain[2J]0;owned page", run_cli("pages", "--space", "ENG", "--all", gateway=self.gateway).out)

    def test_json_escapes_them(self):
        out = run_cli("page", "2005", "--json", gateway=self.gateway).out
        self.assertNotIn("\x1b", out)
        self.assertNotIn("\x9b", out)
        self.assertIn("\\u001b", out)
        self.assertIn("\\u009b", out)
        self.assertEqual(json.loads(out)["title"], "Plain\x1b[2J\x1b]0;owned\x07 page\x9b")

    def test_what_the_server_says_in_an_error_cannot_drive_the_terminal_either(self):
        hostile = "remote\x1b]0;owned\x07 text\x9b2J end"
        self.gateway.errors["get_page"] = RejectedError(hostile, hint=hostile, details={"remote": hostile})
        text = run_cli("page", "2005", gateway=self.gateway)
        as_json = run_cli("page", "2005", "--json", gateway=self.gateway)
        self.assertEqual((text.code, as_json.code), (6, 6))
        for result in (text, as_json):
            for char in ("\x1b", "\x07", "\x9b"):
                self.assertNotIn(char, result.err)
        self.assertIn("remote]0;owned text2J end", text.err)
        self.assertEqual(json.loads(as_json.err)["error"]["details"]["remote"], hostile)  # JSON keeps every character, escaped

    def test_the_messages_for_the_person_at_the_terminal_are_made_safe(self):
        stream = io.StringIO()
        diagnostics = StderrDiagnostics(stream, verbose=True)
        for write in (diagnostics.info, diagnostics.warn, diagnostics.debug):
            write("Markdown cannot show: macro:x\x1b[2J\x9b")
        self.assertEqual(len(stream.getvalue().splitlines()), 3)
        for char in ("\x1b", "\x9b"):
            self.assertNotIn(char, stream.getvalue())

    def test_an_error_with_a_detail_json_cannot_print_still_gets_out(self):
        self.gateway.errors["get_page"] = RejectedError("odd", details={"when": object.__new__(type("Odd", (), {}))})
        result = run_cli("page", "2005", "--json", gateway=self.gateway)
        self.assertEqual(result.code, 6)
        self.assertEqual(json.loads(result.err)["error"]["message"], "odd")

    def test_tabs_and_line_breaks_stay(self):
        self.gateway.pages["2005"].body = "<pre>a\tb\nc</pre>"
        out = run_cli("page", "2005", "--format", "storage", gateway=self.gateway).out
        self.assertIn("a\tb\nc", out)


class PartsCommandsTest(unittest.TestCase):
    def test_comments(self):
        out = run_cli("comments", "2002").out
        self.assertIn("--- #4001 footer", out)
        self.assertIn("Looks good.", out)
        self.assertNotIn("#4003", out)
        self.assertIn("--- #4003 inline [open]", run_cli("comments", "2002", "--inline").out)
        data = run_cli("comments", "2002", "--inline", "--json").json()
        self.assertEqual((data["pageId"], data["count"]), ("2002", 3))
        self.assertEqual(set(data["comments"][0]), {"id", "kind", "updated", "parentId", "resolution", "author", "authorRef", "byMe", "body"})  # authorRef and byMe were added
        self.assertEqual((data["comments"][2]["kind"], data["comments"][2]["resolution"]), ("inline", "open"))
        self.assertEqual(run_cli("comments", "2003").out, "No comments.\n")
        self.assertIn("Alex Example", run_cli("comments", "2002", "--with-users").out)

    def test_labels(self):
        self.assertEqual(run_cli("labels", "2002").out.splitlines()[0].split(), ["NAME", "PREFIX"])
        self.assertEqual(run_cli("labels", "2002", "--json").json(), {"pageId": "2002", "labels": [{"name": "release", "prefix": "global"}, {"name": "notes", "prefix": "global"}]})
        self.assertEqual(run_cli("labels", "2003").out, "No labels.\n")

    def test_attachments(self):
        out = run_cli("attachments", "2002", "--all").out
        self.assertEqual(out.splitlines()[0].split(), ["ID", "NAME", "SIZE", "TYPE", "VERSION", "CREATED"])
        self.assertIn("diagram.png", out)
        self.assertIn("10 B", out)
        data = run_cli("attachments", "2002", "--limit", "1", "--json").json()
        self.assertEqual((data["count"], data["nextCursor"]), (1, "1"))
        self.assertEqual(
            set(data["attachments"][0]),
            {"id", "title", "mediaType", "size", "version", "created", "updated", "pageId", "blogPostId", "downloadLink", "comment"},  # `updated` and `blogPostId` came with the attachments area
        )
        self.assertEqual(run_cli("attachments", "2003").out, "No attachments.\n")

    def test_download(self):
        files = MemoryFiles()
        result = run_cli("download", "att5001", "--out", "out", files=files)
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("downloaded", result.out)
        self.assertEqual(files.files["out/diagram.png"], b"PNGDATA123")
        data = run_cli("download", "2002", "--name", "notes.txt", "--name", "diagram.png", "--out", "more", "--json", files=files).json()
        self.assertEqual((data["count"], data["dryRun"]), (2, False))
        self.assertEqual(set(data["files"][0]), {"attachmentId", "name", "path", "size", "version", "action"})  # `version` came with the attachments area
        self.assertEqual(files.files["more/notes.txt"], b"hello notes\n")
        again = run_cli("download", "att5001", "--out", "out", files=files)
        self.assertEqual(again.code, 1)
        self.assertIn("--force", again.err)
        self.assertEqual(run_cli("download", "2002", "--all", "--out", "dry", "--dry-run", files=files).code, 0)
        self.assertNotIn("dry/notes.txt", files.files)
        self.assertEqual(run_cli("download", "2002").code, 2)


class ChangeCommandsTest(unittest.TestCase):
    def test_update_dry_run_shows_what_is_sent(self):
        gateway = FakeGateway()
        result = run_cli("update", "2005", "--title", "Renamed", "--body", "New **text**", "--dry-run", gateway=gateway)
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("Dry run: page 2005 'Plain page' would go from version 1 to 2; nothing was sent", result.out)
        self.assertIn('"number": 2', result.out)
        self.assertIn("<strong>text</strong>", result.out)
        self.assertEqual(gateway.called("update_page"), [])
        data = run_cli("update", "2005", "--body", "New", "--dry-run", "--json").json()
        self.assertEqual((data["action"], data["dryRun"], data["versionFrom"], data["versionTo"]), ("updated", True, 1, 2))
        self.assertEqual(data["payload"]["body"], {"representation": "storage", "value": "<p>New</p>"})

    def test_update_for_real(self):
        gateway = FakeGateway()
        result = run_cli("update", "2005", "--body", "Rewritten", "--message", "Why", "--if-version", "1", gateway=gateway)
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("Updated page 2005: Plain page (version 1 -> 2)", result.out)
        self.assertEqual(gateway.pages["2005"].body, "<p>Rewritten</p>")
        self.assertEqual(gateway.called("update_page")[0][2]["version"], {"number": 2, "message": "Why"})

    def test_update_from_a_file_and_from_standard_input(self):
        gateway = FakeGateway()
        files = MemoryFiles({"notes.md": "From a file.\n"})
        run_cli("update", "2005", "--file", "notes.md", gateway=gateway, files=files)
        self.assertEqual(gateway.pages["2005"].body, "<p>From a file.</p>")
        run_cli("update", "2005", "--file", "-", "--append", stdin="Tail.\n", gateway=gateway)
        self.assertTrue(gateway.pages["2005"].body.endswith("\n<p>Tail.</p>"))

    def test_update_refuses_what_would_lose_content_and_force_allows_it(self):
        result = run_cli("update", "2002", "--body", "Replacement")
        self.assertEqual(result.code, 1)
        self.assertIn("macro:toc", result.err)
        self.assertEqual(run_cli("update", "2002", "--body", "Replacement", "--force").code, 0)

    def test_update_conflicts_have_exit_code_3(self):
        self.assertEqual(run_cli("update", "2002", "--title", "T", "--if-version", "1").code, 3)
        gateway = FakeGateway()
        gateway.errors["update_page"] = ConflictError("Confluence reports a conflict (HTTP 409).")
        self.assertEqual(run_cli("update", "2005", "--body", "x", gateway=gateway).code, 3)

    def test_update_argument_errors(self):
        for argv in (
            ("update", "2005"),
            ("update", "2005", "--append", "--prepend", "--body", "x"),
            ("update", "2005", "--append"),
            ("update", "2005", "--body", "x", "--file", "y.md"),
            ("update", "2005", "--body", "x", "--format", "rtf"),
        ):
            with self.subTest(argv=argv):
                self.assertIn(run_cli(*argv).code, (1, 2))
        result = run_cli("update", "2005", "--body", '<p><ri:user ri:account-id="hidden" /></p>', "--format", "storage")
        self.assertEqual(result.code, 1)
        self.assertIn("--with-users", result.err)

    def test_update_that_changes_nothing(self):
        out = run_cli("update", "2005", "--title", "Plain page").out
        self.assertIn("Nothing to change", out)
        self.assertEqual(run_cli("update", "2005", "--title", "Plain page", "--json").json()["action"], "unchanged")

    def test_an_empty_file_or_pipe_does_not_blank_the_body(self):
        """An editor that saved nothing, or a pipe that failed, must not clear a page; `--body ''` on the command line does it on purpose."""
        gateway = FakeGateway()
        for argv, stdin, files in (
            (("update", "2005", "--file", "empty.md"), "", MemoryFiles({"empty.md": "\n  \n"})),
            (("update", "2005", "--file", "-"), "", None),
            (("update", "2005", "--file", "-", "--append"), "  \n", None),
        ):
            with self.subTest(argv=argv):
                result = run_cli(*argv, stdin=stdin, files=files, gateway=gateway)
                self.assertEqual(result.code, 2)
                self.assertIn("is empty", result.err)
                self.assertIn("--body ''", result.err)
        self.assertEqual(gateway.called("update_page"), [])
        self.assertEqual(gateway.pages["2005"].body, "<p>Just a paragraph &amp; text.</p>")
        self.assertEqual(run_cli("update", "2005", "--body", "", "--dry-run").code, 0)

    def test_move(self):
        gateway = FakeGateway()
        out = run_cli("move", "2005", "--to", "2003", "--dry-run", gateway=gateway).out
        self.assertIn("would be moved", out)
        self.assertEqual(gateway.called("move_page"), [])
        out = run_cli("move", "2005", "--to", "2003", gateway=gateway).out
        self.assertIn("Moved page 2005", out)
        data = run_cli("move", "2005", "--to", "2002", "--position", "before", "--json", gateway=gateway).json()
        self.assertEqual(data["payload"], {"pageId": "2005", "position": "before", "targetId": "2002"})
        self.assertEqual(run_cli("move", "2005").code, 2)

    def test_comment(self):
        gateway = FakeGateway()
        out = run_cli("comment", "2002", "--text", "Reviewed.", "--dry-run", gateway=gateway).out
        self.assertIn("Dry run: page 2002 exists; nothing was sent", out)
        self.assertEqual(gateway.called("add_comment"), [])
        out = run_cli("comment", "2002", "--text", "Reviewed.", "--reply-to", "4001", gateway=gateway).out
        self.assertEqual(out, "Commented on page 2002 (comment 20001)\n")
        self.assertEqual(gateway.called("add_comment")[0][1]["parentCommentId"], "4001")
        data = run_cli("comment", "2002", "--file", "-", "--json", stdin="From stdin\n", gateway=gateway).json()
        self.assertEqual((data["pageId"], data["dryRun"], data["commentId"]), ("2002", False, "20002"))
        result = run_cli("comment", "2002")
        self.assertEqual(result.code, 2)
        self.assertIn("--text", result.err)

    def test_label(self):
        gateway = FakeGateway()
        out = run_cli("label", "2002", "--add", "reviewed,adr", "--remove", "notes", "--dry-run", gateway=gateway).out
        self.assertIn("Dry run (nothing was sent): page 2002: would add: reviewed, adr; would remove: notes", out)
        self.assertEqual(gateway.called("add_labels"), [])
        out = run_cli("label", "2002", "--add", "reviewed", gateway=gateway).out
        self.assertIn("added: reviewed", out)
        self.assertIn("Labels now: release, notes, reviewed", out)
        data = run_cli("label", "2002", "--remove", "notes", "--json", gateway=gateway).json()
        self.assertEqual((data["removed"], data["labels"]), (["notes"], ["release", "reviewed"]))
        self.assertEqual(run_cli("label", "2002").code, 1)

    def test_attach(self):
        gateway = FakeGateway()
        files = MemoryFiles({"a.txt": "alpha", "b.bin": b"\x00\x01"})
        out = run_cli("attach", "2003", "a.txt", "b.bin", "--dry-run", gateway=gateway, files=files).out
        self.assertIn("would upload", out)
        self.assertEqual(gateway.called("upload_attachment"), [])
        data = run_cli("attach", "2003", "a.txt", "b.bin", "--comment", "c", "--minor", "--json", gateway=gateway, files=files).json()
        self.assertEqual([(item["name"], item["size"], item["action"]) for item in data["files"]], [("a.txt", 5, "uploaded"), ("b.bin", 2, "uploaded")])
        self.assertTrue(all(item["attachmentId"] for item in data["files"]))
        self.assertEqual(gateway.called("upload_attachment")[0][4:], ("c", True))
        self.assertEqual(run_cli("attach", "2003").code, 2)
        self.assertEqual(run_cli("attach", "2003", "missing.txt", files=files).code, 1)


class CreateAndImportCommandsTest(unittest.TestCase):
    def test_create(self):
        gateway = FakeGateway()
        out = run_cli("create", "--space", "ENG", "--title", "New page", "--body", "Hello", "--dry-run", gateway=gateway).out
        self.assertIn("Dry run: a page would be created; nothing was sent", out)
        self.assertIn('"spaceId": "1001"', out)
        self.assertEqual(gateway.called("create_page"), [])
        out = run_cli("create", "--space", "ENG", "--title", "New page", "--body", "Hello", "--labels", "a,b", "--parent", "2003", gateway=gateway).out
        self.assertTrue(out.startswith("Created page 20001: New page with the labels a, b\n"))
        self.assertIn("/pages/20001/", out)
        data = run_cli("create", "--space", "DOCS", "--title", "Other", "--json", gateway=gateway).json()
        self.assertEqual((data["action"], data["pageId"], data["versionTo"], data["labels"]), ("created", "20002", 1, []))
        self.assertEqual(data["payload"]["body"]["value"], "")

    def test_create_errors(self):
        self.assertEqual(run_cli("create", "--space", "ENG").code, 2)
        self.assertEqual(run_cli("create", "--title", "T").code, 2)
        self.assertEqual(run_cli("create", "--space", "ENG", "--title", "Plain page").code, 3)
        self.assertEqual(run_cli("create", "--space", "ENG", "--title", "T", "--parent", "3001").code, 1)

    def test_import_md(self):
        gateway = FakeGateway()
        files = MemoryFiles({"notes.md": "# Imported\n\nSome text.\n", "plain.md": "---\ntitle: Plain page\n---\nJust a paragraph & text.\n"})
        out = run_cli("import-md", "notes.md", "--space", "ENG", "--dry-run", gateway=gateway, files=files).out
        self.assertIn("Dry run: would create a page; nothing was sent", out)
        self.assertEqual(gateway.called("create_page"), [])
        out = run_cli("import-md", "notes.md", "--space", "ENG", gateway=gateway, files=files).out
        self.assertTrue(out.startswith("Created page 20001: Imported"))
        data = run_cli("import-md", "plain.md", "--space", "ENG", "--json", gateway=gateway, files=files).json()
        self.assertEqual((data["action"], data["pageId"], data["file"]), ("unchanged", "2005", "plain.md"))
        self.assertIn("Nothing to change", run_cli("import-md", "plain.md", "--space", "ENG", gateway=gateway, files=files).out)
        self.assertEqual(run_cli("import-md", "missing.md", "--space", "ENG", files=files).code, 1)

    def test_import_md_warns_when_force_drops_content(self):
        files = MemoryFiles({"x.md": "---\npage_id: 2002\n---\nReplacement\n"})
        self.assertEqual(run_cli("import-md", "x.md", files=files).code, 1)
        result = run_cli("import-md", "x.md", "--force", files=files)
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("macro:toc", result.err)

    def test_import_md_dir(self):
        files = MemoryFiles({"docs/a.md": "# Alpha\n", "docs/b.md": "No title\n", "docs/c.md": "# Gamma\n"})
        result = run_cli("import-md-dir", "docs", "--space", "ENG", files=files)
        self.assertEqual(result.code, 1)
        self.assertIn("created       20001 docs/a.md", result.out)
        self.assertIn("FAILED        docs/b.md", result.out)
        self.assertIn("Done: files=2 created=1 updated=0 unchanged=0 failed=1", result.out)
        result = run_cli("import-md-dir", "docs", "--space", "ENG", "--continue-on-error", "--dry-run", files=files)
        self.assertEqual(result.code, 1)
        self.assertIn("would create", result.out)
        self.assertIn("(dry run, nothing was sent)", result.out)
        data = run_cli("import-md-dir", "docs", "--space", "ENG", "--continue-on-error", "--json", files=files)
        self.assertEqual(data.code, 1)
        report = data.json()
        self.assertEqual((report["created"], report["failed"], len(report["outcomes"])), (2, 1, 3))
        self.assertEqual(run_cli("import-md-dir", "nowhere").code, 1)


class SessionCommandsTest(unittest.TestCase):
    def test_the_token_from_standard_input(self):
        store = MemoryConfigStore()
        result = run_cli("setup-token", "--stdin", stdin="atlassian-token-123\n", store=store)
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(result.out, "Token saved to memory://config\n")
        self.assertEqual(store.values["CONFLUENCE_API_TOKEN"], "atlassian-token-123")
        self.assertNotIn("atlassian-token-123", result.out + result.err)
        self.assertEqual(run_cli("setup-token", "--stdin", "--json", stdin="x-token-2", store=store).json(), {"saved": True, "file": "memory://config"})

    def test_a_token_typed_where_it_may_show_is_warned_about(self):
        store = MemoryConfigStore()
        result = run_cli("setup-token", stdin="typed-token\n", store=store)
        self.assertEqual(store.values["CONFLUENCE_API_TOKEN"], "typed-token")
        self.assertIn("may be visible", result.err)

    def test_an_empty_token_is_refused(self):
        store = MemoryConfigStore()
        self.assertEqual(run_cli("setup-token", "--stdin", stdin="  \n", store=store).code, 1)
        self.assertEqual(store.values, {})

    def test_the_token_is_not_accepted_as_an_argument(self):
        self.assertEqual(run_cli("setup-token", "abc123").code, 2)
        self.assertEqual(run_cli("config", "set", "CONFLUENCE_API_TOKEN", "abc123").code, 2)

    def test_remove_token(self):
        store = MemoryConfigStore({"CONFLUENCE_API_TOKEN": "x"})
        self.assertIn("Token removed", run_cli("remove-token", store=store).out)
        self.assertEqual(run_cli("remove-token", "--json", store=store).json(), {"removed": False, "file": "memory://config"})

    def test_use_current_and_clear_space(self):
        store = MemoryConfigStore()
        self.assertEqual(run_cli("use", "eng", store=store).out, "Current space: ENG (Engineering)\n")
        self.assertEqual(store.values["CONFLUENCE_SPACE"], "ENG")
        self.assertEqual(run_cli("use", "NOPE", store=store).code, 4)
        self.assertEqual(run_cli("current", settings=default_settings(space="ENG")).out, "ENG\n")
        self.assertEqual(run_cli("current", "--json", settings=default_settings(space="ENG")).json(), {"space": "ENG"})
        none = run_cli("current")
        self.assertEqual((none.code, none.out), (1, ""))
        self.assertEqual(run_cli("current", "--json").json(), {"space": None})
        self.assertEqual(run_cli("clear-space", store=store).out, "The current space was cleared.\n")
        self.assertEqual(run_cli("clear-space", store=store).out, "No current space was set.\n")

    def test_a_variable_that_overrides_the_file_is_pointed_out(self):
        result = run_cli("use", "ENG", environ={"CONFLUENCE_SPACE": "DOCS"})
        self.assertIn("CONFLUENCE_SPACE is also set in the environment", result.err)

    def test_config(self):
        store = MemoryConfigStore({"CONFLUENCE_API_TOKEN": "very-secret-token", "CONFLUENCE_EMAIL": "alex@example.com"})
        shown = run_cli("config", store=store).out
        self.assertIn("Configuration file: memory://config", shown)
        self.assertIn("********", shown)
        self.assertNotIn("very-secret-token", shown)
        self.assertIn("a***@example.com", shown)
        self.assertNotIn("alex@example.com", shown)
        data = run_cli("config", "show", "--json", store=store).json()
        self.assertEqual(data["file"], "memory://config")
        entry = next(item for item in data["settings"] if item["name"] == "CONFLUENCE_API_TOKEN")
        self.assertEqual((entry["secret"], entry["source"]), (True, "config file"))
        self.assertEqual(run_cli("config", "path", store=store).out, "memory://config\n")
        self.assertIn("saved to", run_cli("config", "set", "CONFLUENCE_HIDE_USERS", "true", store=store).out)
        self.assertEqual(store.values["CONFLUENCE_HIDE_USERS"], "true")
        self.assertIn("removed from", run_cli("config", "unset", "CONFLUENCE_HIDE_USERS", store=store).out)
        self.assertIn("was not set", run_cli("config", "unset", "CONFLUENCE_HIDE_USERS", store=store).out)
        self.assertEqual(run_cli("config", "set", "CONFLUENCE_NOPE", "x", store=store).code, 2)
        self.assertEqual(run_cli("config", "set", "CONFLUENCE_HIDE_USERS", store=store).code, 2)
        self.assertEqual(run_cli("config", "set", store=store).code, 2)

    def test_ping(self):
        self.assertEqual(run_cli("ping").out, f"OK: connected to {BASE} as Alex Example\n")
        self.assertEqual(run_cli("ping", "--quiet").out, "OK\n")
        self.assertEqual(run_cli("ping", settings=default_settings(hide_users=True)).out, f"OK: connected to {BASE}\n")
        data = run_cli("ping", "--json").json()
        self.assertEqual((data["ok"], data["baseUrl"], data["user"]["displayName"]), (True, BASE, "Alex Example"))
        self.assertIsNone(run_cli("ping", "--json", "--quiet").json()["user"])

    def test_ping_with_an_address_that_lacks_the_wiki_shows_the_one_that_is_used(self):
        out = run_cli("ping", settings=default_settings(base_url="https://example.atlassian.net")).out
        self.assertIn("https://example.atlassian.net/wiki", out)

    def test_a_refused_login_is_exit_code_5(self):
        gateway = FakeGateway()
        gateway.errors["current_user"] = AuthError("Confluence did not accept the credentials (HTTP 401).", hint="Run `conflu setup-token`.")
        result = run_cli("ping", gateway=gateway)
        self.assertEqual(result.code, 5)
        self.assertIn("setup-token", result.err)

    def test_doctor(self):
        files = MemoryFiles({"memory://config": "x"})
        result = run_cli("doctor", files=files, settings=default_settings(space="ENG"))
        self.assertEqual(result.code, 0, result.out)
        self.assertIn("[ok]   connection", result.out)
        self.assertNotIn("secret-token", result.out)
        data = run_cli("doctor", "--json", files=files, settings=default_settings(space="ENG")).json()
        self.assertTrue(data["ok"])
        self.assertEqual({check["status"] for check in data["checks"]}, {"ok"})
        self.assertEqual(set(data["checks"][0]), {"name", "status", "detail", "hint"})

    def test_doctor_fails_with_hints_when_the_setup_is_missing(self):
        from conflu_c_cli.application.settings import Settings

        result = run_cli("doctor", settings=Settings())
        self.assertEqual(result.code, 1)
        self.assertIn("[FAIL] base url", result.out)
        self.assertIn("Hint: Run `conflu config set CONFLUENCE_BASE_URL", result.out)
        self.assertIn("[warn] connection", result.out)


class InfoCommandsTest(unittest.TestCase):
    def test_help_text(self):
        out = run_cli("help", "update").out
        self.assertIn("conflu update - Change the title or the body of a page", out)
        self.assertIn("Usage: conflu update PAGE", out)
        self.assertIn("--if-version N", out)
        self.assertIn("Changes data: yes, preview with --dry-run", out)
        self.assertIn("Changes data: no", run_cli("help", "page").out)
        self.assertIn("JSON output: id, title", run_cli("help", "page").out)

    def test_a_command_that_takes_several_files_says_so_in_its_usage(self):
        self.assertIn("Usage: conflu attach PAGE FILE... [--comment TEXT] [--minor] [--dry-run]", run_cli("help", "attach").out)

    def test_changelog_how_to_and_skill(self):
        self.assertIn(f"## [{__version__}]", run_cli("changelog").out)
        listing = run_cli("how-to").out
        self.assertIn("daily-workflow", listing)
        self.assertIn("conflu how-to TOPIC", listing)
        self.assertEqual(run_cli("how-to", "daily-workflow").out, "# daily-workflow\n\nText of daily-workflow.\n")
        self.assertEqual(run_cli("how-to", "readme").out, "# conflu-c-cli\n\nOverview.\n")
        self.assertEqual(run_cli("how-to", "daily-workflow", "--json").json()["topic"], "daily-workflow")
        self.assertEqual([item["topic"] for item in run_cli("how-to", "--json").json()], ["readme", "daily-workflow", "exit-codes"])
        self.assertEqual(run_cli("how-to", "nope").code, 4)
        self.assertIn("name: conflu-c-cli", run_cli("skill").out)
        self.assertEqual(run_cli("skill", "--json").json()["name"], "conflu-c-cli")

    def test_the_skill_is_installed_where_asked(self):
        files = MemoryFiles()
        out = run_cli("skill", "install", "--dir", "skills", files=files).out
        self.assertEqual(out, "Skill installed: skills/conflu-c-cli/SKILL.md\n")
        self.assertIn("already up to date", run_cli("skill", "install", "--dir", "skills", files=files).out)
        files.write_text("skills/conflu-c-cli/SKILL.md", "mine")
        self.assertEqual(run_cli("skill", "install", "--dir", "skills", files=files).code, 1)
        self.assertIn("replaced", run_cli("skill", "install", "--dir", "skills", "--force", files=files).out)
        self.assertEqual(run_cli("skill", "install", "--dir", "elsewhere", "--dry-run", files=files).out, "Would write the skill to elsewhere/conflu-c-cli/SKILL.md\n")
        self.assertNotIn("elsewhere/conflu-c-cli/SKILL.md", files.files)

    def test_convert_in_both_directions(self):
        files = MemoryFiles({"notes.md": "---\ntitle: T\n---\n# Hello\n\n**bold**\n"})
        out = run_cli("convert", "notes.md", files=files).out
        self.assertIn("<h1>Hello</h1>", out)
        self.assertNotIn("title", out)
        piped = run_cli("convert", stdin="Some `code`\n")
        self.assertEqual(piped.out, "<p>Some <code>code</code></p>\n")
        back = run_cli("convert", "--source", "storage", stdin='<h1>Hi</h1><ac:structured-macro ac:name="toc" />')
        self.assertTrue(back.out.startswith("# Hi"))
        self.assertIn("macro:toc", back.err)
        self.assertEqual(run_cli("convert", stdin_tty=True).code, 2)

    def test_api_is_read_free_and_writes_need_confirmation(self):
        gateway = FakeGateway()
        out = run_cli("api", "GET", "api/v2/pages/2002", gateway=gateway).out
        self.assertEqual(json.loads(out)["ok"], True)
        self.assertEqual(gateway.called("request")[0][1:], ("GET", "/api/v2/pages/2002", None))
        self.assertEqual(run_cli("api", "PUT", "api/v2/pages/2002/title", "--data", "{}", gateway=gateway).code, 2)
        self.assertEqual(run_cli("api", "GET", "admin/users", gateway=gateway).code, 2)
        self.assertEqual(run_cli("api", "DELETE", "api/v2/pages/2002", "--write", gateway=gateway).code, 2)
        out = run_cli("api", "PUT", "api/v2/pages/2002/title", "--data", '{"status": "current", "title": "T"}', "--write", "--dry-run", gateway=gateway).out
        self.assertIn("Dry run: PUT /api/v2/pages/2002/title; nothing was sent", out)
        self.assertEqual(len(gateway.called("request")), 1)
        files = MemoryFiles({"payload.json": '{"status": "current", "title": "T"}'})
        run_cli("api", "PUT", "api/v2/pages/2002/title", "--data-file", "payload.json", "--write", gateway=gateway, files=files)
        self.assertEqual(gateway.called("request")[-1][3], {"status": "current", "title": "T"})

    def test_api_undoes_what_git_bash_does_to_a_leading_slash(self):
        gateway = FakeGateway()
        environ = {"EXEPATH": "C:\\Program Files\\Git"}
        run_cli("api", "GET", "C:/Program Files/Git/api/v2/pages/2002", gateway=gateway, environ=environ)
        self.assertEqual(gateway.called("request")[0][2], "/api/v2/pages/2002")
        self.assertEqual(run_cli("api", "GET", "D:/somewhere/api/v2/pages", gateway=gateway, environ=environ).code, 2)


if __name__ == "__main__":
    unittest.main()
