"""The whole program: the real adapters against the mock Confluence, in this process and as a child process."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from conflu_c_cli.adapters.driving.cli.main import run
from conflu_c_cli.bootstrap import create_application
from tests.support.mock_confluence import MockConfluence

ROOT = Path(__file__).resolve().parents[2]
ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"


@dataclass
class Result:
    code: int
    out: str
    err: str

    def json(self):
        return json.loads(self.out)


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.mock = MockConfluence()
        self.mock.start()
        self.addCleanup(self.mock.stop)
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name)
        self.config = self.root / "config" / "conflu-c-cli" / "config"
        self.env = {
            "CONFLUENCE_CONFIG_FILE": str(self.config),
            "HOME": str(self.root),
            "CONFLUENCE_BASE_URL": self.mock.base_url,
            "CONFLUENCE_EMAIL": self.mock.email,
            "CONFLUENCE_API_TOKEN": self.mock.token,
        }

    def cli(self, *argv, stdin="", env=None, replace_env=False):
        """In this process, through the real composition root."""
        environ = dict(env or {}) if replace_env else {**self.env, **(env or {})}
        out, err = io.StringIO(), io.StringIO()
        code = run(
            list(argv),
            app_factory=lambda diagnostics: create_application(diagnostics, environ),
            environ=environ,
            stdout=out,
            stderr=err,
            stdin=io.StringIO(stdin),
        )
        return Result(code, out.getvalue(), err.getvalue())

    def child(self, *argv, stdin=None, env=None):
        """As a separate program, the way a shell or an agent starts it."""
        base = {key: value for key, value in os.environ.items() if not key.startswith(("CONFLUENCE_", "PYTHON"))}
        done = subprocess.run(
            [sys.executable, "-I", "-X", "utf8", str(ROOT / "conflu.py"), *argv],
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**base, **self.env, **(env or {})},
            timeout=60,
        )
        return Result(done.returncode, done.stdout, done.stderr)

    def sent(self, method, prefix):
        return [item for item in self.mock.requests if item.method == method and item.path.startswith(prefix)]


class SetupFlowTest(EndToEnd):
    def test_a_new_user_configures_and_checks_the_setup(self):
        bare = dict(replace_env=True)
        file_env = {"CONFLUENCE_CONFIG_FILE": str(self.config), "HOME": str(self.root)}
        for name, value in (("CONFLUENCE_BASE_URL", self.mock.base_url), ("CONFLUENCE_EMAIL", self.mock.email)):
            self.assertEqual(self.cli("config", "set", name, value, env=file_env, **bare).code, 0)
        token = self.cli("setup-token", "--stdin", stdin=self.mock.token + "\n", env=file_env, **bare)
        self.assertEqual(token.code, 0, token.err)
        self.assertNotIn(self.mock.token, token.out + token.err)
        self.assertEqual(self.cli("use", "ENG", env=file_env, **bare).out, "Current space: ENG (Engineering)\n")
        stored = self.config.read_text(encoding="utf-8")
        self.assertIn(f"CONFLUENCE_API_TOKEN={self.mock.token}", stored)
        self.assertIn("CONFLUENCE_SPACE=ENG", stored)
        if os.name != "nt":
            self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        shown = self.cli("config", "show", env=file_env, **bare).out
        self.assertNotIn(self.mock.token, shown)
        self.assertNotIn(self.mock.email, shown)
        self.assertIn("********", shown)
        ping = self.cli("ping", env=file_env, **bare)
        self.assertEqual(ping.out, f"OK: connected to {self.mock.base_url} as Alex Example\n")
        report = self.cli("doctor", "--json", env=file_env, **bare).json()
        self.assertEqual({check["name"]: check["status"] for check in report["checks"]}, {
            "runtime": "ok", "config file": "ok", "base url": "ok", "email": "ok", "token": "ok", "tls": "ok",
            "connection": "ok", "spaces": "ok", "space": "ok", "privacy": "ok",
        })
        self.assertTrue(report["ok"])
        self.assertEqual(self.cli("pages", "--limit", "1", "--json", env=file_env, **bare).json()["space"], "ENG")  # the current space

    def test_a_wrong_token_is_exit_code_5_with_the_command_that_fixes_it(self):
        result = self.cli("ping", env={"CONFLUENCE_API_TOKEN": "not-the-token"})
        self.assertEqual(result.code, 5)
        self.assertIn("conflu setup-token", result.err)
        self.assertNotIn("not-the-token", result.err)
        doctor = self.cli("doctor", env={"CONFLUENCE_API_TOKEN": "not-the-token"})
        self.assertEqual(doctor.code, 1)
        self.assertIn("[FAIL] connection", doctor.out)

    def test_doctor_names_what_is_missing(self):
        result = self.cli("doctor", env={"CONFLUENCE_EMAIL": "", "CONFLUENCE_API_TOKEN": ""})
        self.assertEqual(result.code, 1)
        self.assertIn("[FAIL] email", result.out)
        self.assertIn("[FAIL] token", result.out)
        self.assertEqual(self.mock.requests, [])


class ReadingFlowTest(EndToEnd):
    def test_pages_are_listed_across_server_side_pages(self):
        data = self.cli("pages", "--space", "ENG", "--all", "--json").json()
        self.assertEqual([page["id"] for page in data["pages"]], ["2001", "2002", "2003", "2004", "2005"])
        self.assertGreater(len(self.sent("GET", "/api/v2/spaces/1001/pages")), 2)  # the mock hands out two at a time

    def test_a_page_as_a_person_and_as_a_program_reads_it(self):
        text = self.cli("page", "2002").out
        self.assertIn("# Release notes", text)
        self.assertNotIn(ACCOUNT, text)
        self.assertNotIn("alex@example.com", text)
        data = self.cli("page", "2002", "--json", "--comments", "--ancestors").json()
        self.assertEqual(data["body"]["dropped"], ["macro:toc", "mention", "redacted-text"])
        self.assertEqual([item["id"] for item in data["comments"]], ["4001", "4002"])
        self.assertEqual([item["title"] for item in data["ancestors"]], ["Engineering Home"])
        self.assertEqual(data["version"]["number"], 3)
        self.assertIsNone(data["author"])
        named = self.cli("page", "2002", "--json", "--with-users").json()
        self.assertEqual(named["author"]["displayName"], "Alex Example")

    def test_search_the_tree_versions_comments_labels_attachments_and_spaces(self):
        found = self.cli("search", "release", "--space", "ENG", "--json").json()
        self.assertEqual([hit["id"] for hit in found["hits"]], ["2002"])
        self.assertEqual(found["hits"][0]["title"], "Release notes")
        self.assertEqual(self.cli("tree", "2001", "--json").json()["count"], 4)
        self.assertEqual([item["number"] for item in self.cli("versions", "2002", "--all", "--json").json()["versions"]], [3, 2, 1])
        self.assertEqual(self.cli("comments", "2002", "--inline", "--json").json()["count"], 3)
        self.assertEqual(sorted(label["name"] for label in self.cli("labels", "2002", "--json").json()["labels"]), ["notes", "release"])
        self.assertEqual([item["title"] for item in self.cli("attachments", "2002", "--all", "--json").json()["attachments"]], ["diagram.png", "notes.txt"])
        self.assertEqual([space["key"] for space in self.cli("spaces", "--all", "--json").json()["spaces"]], ["ENG", "DOCS"])
        self.assertEqual(self.cli("space", "ENG", "--json").json()["homepageId"], "2001")

    def test_search_keeps_people_out_of_the_excerpts_unless_asked(self):
        hidden = self.cli("search", "release", "--space", "ENG", "--json").json()["hits"][0]
        self.assertIsNone(hidden["excerpt"])
        shown = self.cli("search", "release", "--space", "ENG", "--with-users", "--json").json()["hits"][0]
        self.assertIn("alex@example.com", shown["excerpt"] + self.mock.pages["2002"]["versions"][-1]["body"])  # the text is the page's own
        self.assertTrue(shown["excerpt"])
        self.assertNotIn("@@@", shown["excerpt"])
        refused = self.cli("search", "release", "--with-users", env={"CONFLUENCE_HIDE_USERS": "true"})
        self.assertEqual(refused.code, 1)

    def test_attachments_are_downloaded_through_the_media_service_and_never_overwrite(self):
        out = self.root / "files"
        result = self.cli("download", "2002", "--all", "--out", str(out), "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual((out / "diagram.png").read_bytes(), b"PNGDATA123")
        self.assertEqual((out / "notes.txt").read_bytes(), b"hello notes\n")
        self.assertTrue(self.mock.media_requests)
        self.assertTrue(all("authorization" not in request.headers for request in self.mock.media_requests))
        again = self.cli("download", "att5001", "--out", str(out))
        self.assertEqual(again.code, 1)
        self.assertIn("--force", again.err)
        self.assertEqual(self.cli("download", "att5001", "--out", str(out), "--force").code, 0)

    def test_unicode_survives_the_trip(self):
        created = self.cli("create", "--space", "ENG", "--title", "Übersicht ✓ 日本語", "--body", "Grüße — naïve café ✓", "--json").json()
        shown = self.cli("page", created["pageId"], "--json").json()
        self.assertEqual(shown["title"], "Übersicht ✓ 日本語")
        self.assertEqual(shown["body"]["value"], "Grüße — naïve café ✓")

    def test_a_missing_page_is_exit_code_4(self):
        self.assertEqual(self.cli("page", "999").code, 4)
        error = json.loads(self.cli("page", "999", "--json").err)["error"]
        self.assertEqual((error["code"], error["exitCode"]), ("NOT_FOUND", 4))


class WritingFlowTest(EndToEnd):
    def test_create_update_comment_label_attach_move(self):
        created = self.cli("create", "--space", "ENG", "--title", "Meeting notes", "--body", "# Agenda\n\n- one\n- two", "--labels", "meeting, Weekly", "--json").json()
        page_id = created["pageId"]
        self.assertEqual((created["action"], created["versionTo"], created["labels"]), ("created", 1, ["meeting", "weekly"]))
        self.assertEqual(self.mock.pages[page_id]["labels"], ["meeting", "weekly"])
        stored = self.mock.pages[page_id]["versions"][-1]["body"]
        self.assertIn("<h1>Agenda</h1>", stored)
        self.assertIn("<li>one</li>", stored)

        updated = self.cli("update", page_id, "--body", "More notes.", "--append", "--message", "Added notes", "--if-version", "1", "--json").json()
        self.assertEqual((updated["action"], updated["versionFrom"], updated["versionTo"]), ("updated", 1, 2))
        self.assertTrue(self.mock.pages[page_id]["versions"][-1]["body"].endswith("<p>More notes.</p>"))
        self.assertEqual(self.mock.pages[page_id]["versions"][-1]["message"], "Added notes")

        self.assertEqual(self.cli("update", page_id, "--title", "Meeting notes 2026-10-15").code, 0)
        self.assertEqual(self.mock.pages[page_id]["title"], "Meeting notes 2026-10-15")
        self.assertIn("<h1>Agenda</h1>", self.mock.pages[page_id]["versions"][-1]["body"])  # a title alone leaves the body

        comment = self.cli("comment", page_id, "--text", "Looks **good**.", "--json").json()
        self.assertTrue(comment["commentId"])
        self.assertEqual(sorted(self.cli("label", page_id, "--add", "reviewed", "--remove", "meeting", "--json").json()["labels"]), ["reviewed", "weekly"])

        report = self.root / "report.txt"
        report.write_text("first", encoding="utf-8")
        self.assertEqual(self.cli("attach", page_id, str(report), "--json").json()["files"][0]["version"], 1)
        report.write_text("second", encoding="utf-8")
        self.assertEqual(self.cli("attach", page_id, str(report), "--json").json()["files"][0]["version"], 2)
        self.assertEqual(self.sent("PUT", f"/rest/api/content/{page_id}/child/attachment")[0].headers["x-atlassian-token"], "nocheck")

        self.assertEqual(self.cli("move", page_id, "--to", "2003").code, 0)
        self.assertEqual(self.mock.pages[page_id]["parentId"], "2003")

    def test_a_dry_run_sends_no_write(self):
        before = len(self.mock.requests)
        for argv in (
            ("create", "--space", "ENG", "--title", "Never", "--body", "x", "--dry-run"),
            ("update", "2005", "--body", "x", "--dry-run"),
            ("update", "2005", "--title", "Never", "--dry-run"),
            ("comment", "2005", "--text", "x", "--dry-run"),
            ("label", "2005", "--add", "never", "--dry-run"),
            ("move", "2005", "--to", "2003", "--dry-run"),
            ("import-md", str(self.write_file("never.md", "# Never\n")), "--space", "ENG", "--dry-run"),
        ):
            with self.subTest(argv=argv):
                self.assertEqual(self.cli(*argv).code, 0)
        written = [item for item in self.mock.requests[before:] if item.method in ("POST", "PUT", "DELETE")]
        self.assertEqual([item.target for item in written], [])
        self.assertEqual(self.mock.pages["2005"]["versions"][-1]["body"], "<p>Just a paragraph &amp; text.</p>")

    def write_file(self, name, text):
        path = self.root / "in" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_a_page_somebody_else_saved_in_between_is_exit_code_3(self):
        self.assertEqual(self.cli("update", "2002", "--title", "T", "--if-version", "2").code, 3)
        self.mock.fail_next("/api/v2/pages/2005", 409, method="PUT", body={"errors": [{"status": 409, "code": "CONFLICT", "title": "Version conflict"}]})
        result = self.cli("update", "2005", "--body", "x")
        self.assertEqual(result.code, 3)
        self.assertIn("Version conflict", result.err)
        self.assertEqual(self.cli("create", "--space", "ENG", "--title", "Plain page").code, 3)  # the title is taken

    def test_the_server_refusing_a_write_is_exit_code_6_with_its_reason(self):
        self.mock.fail_next("/api/v2/pages", 400, method="POST", body={"errors": [{"status": 400, "title": "Bad", "detail": "The space is read-only"}]})
        result = self.cli("create", "--space", "ENG", "--title", "Refused")
        self.assertEqual(result.code, 6)
        self.assertIn("The space is read-only", result.err)

    def test_markdown_never_replaces_what_it_cannot_say_unless_forced(self):
        refused = self.cli("update", "2002", "--body", "Replacement")
        self.assertEqual(refused.code, 1)
        self.assertIn("macro:toc", refused.err)
        self.assertEqual(len(self.mock.pages["2002"]["versions"]), 3)
        self.assertEqual(self.cli("update", "2002", "--body", "Replacement", "--force").code, 0)
        self.assertEqual(len(self.mock.pages["2002"]["versions"]), 4)

    def test_storage_read_without_users_cannot_be_written_back(self):
        blanked = self.cli("page", "2002", "--format", "storage", "--json").json()["body"]["value"]
        self.assertIn('ri:account-id="hidden"', blanked)
        result = self.cli("update", "2002", "--format", "storage", "--body", blanked)
        self.assertEqual(result.code, 1)
        self.assertIn("--with-users", result.err)
        faithful = self.cli("page", "2002", "--format", "storage", "--with-users", "--json").json()["body"]["value"]
        self.assertEqual(faithful, self.mock.pages["2002"]["versions"][-1]["body"])
        self.assertEqual(self.cli("update", "2002", "--format", "storage", "--body", faithful + "<p>Added.</p>").code, 0)

    def test_the_raw_api_is_read_free_and_guarded(self):
        self.assertEqual(self.cli("api", "GET", "api/v2/pages/2002").json()["title"], "Release notes")
        self.assertEqual(self.cli("api", "GET", "rest/api/user/current").json()["displayName"], "Alex Example")
        found = self.cli("api", "GET", 'rest/api/search?cql=type=page AND space="ENG" AND text ~ "release"')  # the guide shows this one
        self.assertEqual((found.code, [item["content"]["id"] for item in found.json()["results"]]), (0, ["2002"]), found.err)
        self.assertEqual(self.cli("api", "GET", "api/v2/pages/2002\nX-Evil: 1").code, 2)
        self.assertEqual(self.cli("api", "PUT", "api/v2/pages/2005/title", "--data", '{"status": "current", "title": "X"}').code, 2)
        done = self.cli("api", "PUT", "api/v2/pages/2005/title", "--data", '{"status": "current", "title": "Raw title"}', "--write")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(self.mock.pages["2005"]["title"], "Raw title")
        self.assertEqual(self.cli("api", "DELETE", "api/v2/pages/2005", "--write").code, 2)
        self.assertEqual([item for item in self.mock.requests if item.method == "DELETE"], [])


class ImportExportFlowTest(EndToEnd):
    def test_an_unedited_export_is_a_no_op_to_import(self):
        out = self.root / "mirror"
        exported = self.cli("export", "--space", "ENG", "--out", str(out), "--json")
        self.assertEqual(exported.code, 0, exported.err)
        data = exported.json()
        self.assertEqual(data["count"], 5)
        index = json.loads((out / "index.json").read_text(encoding="utf-8"))
        self.assertEqual({page["id"] for page in index["pages"]}, {"2001", "2002", "2003", "2004", "2005"})
        text = (out / "release-notes-2002.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\ntitle: Release notes\npage_id: 2002\nspace: ENG\n"))
        self.assertNotIn(ACCOUNT, text + json.dumps(index))
        self.assertNotIn("alex@example.com", text)
        before = {page_id: len(record["versions"]) for page_id, record in self.mock.pages.items()}
        again = self.cli("import-md-dir", str(out), "--json")
        self.assertEqual(again.code, 0, again.err)
        report = again.json()
        self.assertEqual((report["unchanged"], report["updated"], report["created"], report["failed"]), (5, 0, 0, 0))
        self.assertEqual({page_id: len(record["versions"]) for page_id, record in self.mock.pages.items()}, before)

    def test_a_title_with_two_spaces_survives_an_export_and_an_import_unrenamed(self):
        self.mock.pages["2005"]["title"] = "Plain  page"  # Confluence keeps such a title as it is
        out = self.root / "mirror"
        self.assertEqual(self.cli("export", "--space", "ENG", "--out", str(out)).code, 0)
        self.assertIn("title: Plain  page\n", (out / "plain-page-2005.md").read_text(encoding="utf-8"))
        report = self.cli("import-md-dir", str(out), "--json").json()
        self.assertEqual((report["unchanged"], report["updated"], report["failed"]), (5, 0, 0))
        self.assertEqual(self.mock.pages["2005"]["title"], "Plain  page")

    def test_a_title_that_export_had_to_redact_is_never_written_back_as_the_new_title(self):
        self.mock.pages["2005"]["title"] = "Notes for alex@example.com"
        out = self.root / "mirror"
        self.assertEqual(self.cli("export", "--space", "ENG", "--out", str(out)).code, 0)
        names = sorted(path.name for path in out.glob("*.md"))
        self.assertTrue(all("alex" not in name and "example" not in name for name in names), names)  # not in a file name either
        self.assertIn("title: Notes for [email]\n", "".join(path.read_text(encoding="utf-8") for path in out.glob("*.md")))
        result = self.cli("import-md-dir", str(out), "--continue-on-error", "--json")
        self.assertEqual(result.code, 1)
        report = result.json()
        self.assertEqual((report["unchanged"], report["updated"], report["failed"]), (4, 0, 1))
        failed = next(item for item in report["outcomes"] if item["action"] == "failed")
        self.assertIn("[email]", failed["message"])
        self.assertEqual(self.mock.pages["2005"]["title"], "Notes for alex@example.com")  # not renamed
        self.assertEqual([item for item in self.mock.requests if item.method in ("PUT", "POST")], [])

    def test_an_edited_export_updates_a_plain_page_and_protects_a_page_with_constructs(self):
        out = self.root / "mirror"
        self.cli("export", "--space", "ENG", "--out", str(out))
        plain = out / "plain-page-2005.md"
        plain.write_text(plain.read_text(encoding="utf-8").rstrip() + "\n\nA new paragraph.\n", encoding="utf-8")
        rich = out / "release-notes-2002.md"
        rich.write_text(rich.read_text(encoding="utf-8").rstrip() + "\n\nAn edit.\n", encoding="utf-8")
        result = self.cli("import-md-dir", str(out), "--continue-on-error", "--json")
        self.assertEqual(result.code, 1)  # the page with macros is protected
        report = result.json()
        self.assertEqual((report["updated"], report["unchanged"], report["failed"]), (1, 3, 1))
        failed = next(item for item in report["outcomes"] if item["action"] == "failed")
        self.assertIn("macro:toc", failed["message"])
        self.assertIn("<p>A new paragraph.</p>", self.mock.pages["2005"]["versions"][-1]["body"])
        self.assertEqual(self.mock.pages["2005"]["versions"][-1]["message"], "Imported from plain-page-2005.md")
        self.assertEqual(len(self.mock.pages["2002"]["versions"]), 3)
        forced = self.cli("import-md", str(rich), "--force", "--json")
        self.assertEqual(forced.code, 0, forced.err)
        self.assertEqual(forced.json()["lost"], ["macro:toc", "mention", "redacted-text"])

    def test_new_pages_are_created_from_markdown_files_and_found_again_by_their_title(self):
        folder = self.root / "docs"
        folder.mkdir()
        (folder / "one.md").write_text("---\ntitle: First imported page\nlabels: imported, docs\n---\nHello\n\n| a | b |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
        (folder / "two.md").write_text("# Second imported page\n\n```python\nprint('hi')\n```\n", encoding="utf-8")
        first = self.cli("import-md-dir", str(folder), "--space", "ENG", "--parent", "2003", "--json")
        self.assertEqual(first.code, 0, first.err)
        report = first.json()
        self.assertEqual((report["created"], report["failed"]), (2, 0))
        titles = {record["title"]: record for record in self.mock.pages.values()}
        self.assertEqual(titles["First imported page"]["parentId"], "2003")
        self.assertEqual(sorted(titles["First imported page"]["labels"]), ["docs", "imported"])
        self.assertIn("<table>", titles["First imported page"]["versions"][-1]["body"])
        self.assertIn('ac:name="code"', titles["Second imported page"]["versions"][-1]["body"])
        again = self.cli("import-md-dir", str(folder), "--space", "ENG", "--json").json()
        self.assertEqual((again["created"], again["unchanged"]), (0, 2))
        (folder / "two.md").write_text("# Second imported page\n\nChanged.\n", encoding="utf-8")
        changed = self.cli("import-md-dir", str(folder), "--space", "ENG", "--json").json()
        self.assertEqual((changed["updated"], changed["unchanged"]), (1, 1))
        self.assertEqual(len([r for r in self.mock.pages.values() if r["title"] == "Second imported page"]), 1)

    def test_a_page_tree_is_exported_in_storage_format_too(self):
        out = self.root / "tree"
        result = self.cli("export", "--page", "2003", "--format", "storage", "--out", str(out), "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(sorted(path.name for path in out.iterdir()), ["adr-0001-2004.xml", "architecture-2003.xml", "index.json"])
        self.assertIn("ac:plain-text-body", (out / "architecture-2003.xml").read_text(encoding="utf-8"))
        refused = self.cli("export", "--page", "2003", "--out", str(out))
        self.assertEqual(refused.code, 1)
        self.assertEqual(self.cli("export", "--page", "2003", "--out", str(out), "--force").code, 0)


class ProgramTest(EndToEnd):
    """A real child process: the launcher, the console encoding, exit codes and pipes."""

    def test_a_page_with_unicode_comes_out_as_utf_8_with_plain_line_ends(self):
        self.cli("create", "--space", "ENG", "--title", "Café ✓", "--body", "Zwölf Boxkämpfer ✓")
        found = self.cli("pages", "--space", "ENG", "--title", "Café ✓", "--json").json()
        page_id = found["pages"][0]["id"]
        done = self.child("page", page_id)
        self.assertEqual(done.code, 0, done.err)
        self.assertIn("Café ✓", done.out)
        self.assertIn("Zwölf Boxkämpfer ✓", done.out)
        self.assertNotIn("\r", done.out)

    def test_exit_codes_and_json_errors_of_the_real_program(self):
        self.assertEqual(self.child("version").out, f"conflu-c-cli {(ROOT / 'VERSION').read_text().strip()}\n")
        self.assertEqual(self.child("page", "999").code, 4)
        self.assertEqual(self.child("nope").code, 2)
        self.assertEqual(self.child("ping", env={"CONFLUENCE_API_TOKEN": "wrong"}).code, 5)
        error = json.loads(self.child("page", "999", "--json").err)["error"]
        self.assertEqual(error["code"], "NOT_FOUND")

    def test_the_token_comes_in_through_standard_input_only(self):
        env = {key: "" for key in ("CONFLUENCE_API_TOKEN",)}
        saved = self.child("setup-token", "--stdin", stdin="child-token-123\n", env={**env, "CONFLUENCE_CONFIG_FILE": str(self.config)})
        self.assertEqual(saved.code, 0, saved.err)
        self.assertIn("CONFLUENCE_API_TOKEN=child-token-123", self.config.read_text(encoding="utf-8"))
        self.assertNotIn("child-token-123", saved.out + saved.err)

    def test_a_reader_that_goes_away_early_is_not_a_traceback(self):
        process = subprocess.Popen(
            [sys.executable, "-I", "-X", "utf8", str(ROOT / "conflu.py"), "help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**{key: value for key, value in os.environ.items() if not key.startswith("PYTHON")}, **self.env},
        )
        process.stdout.read(10)
        process.stdout.close()
        error = process.stderr.read().decode("utf-8", "replace")
        process.stderr.close()
        process.wait(timeout=30)
        self.assertNotIn("Traceback", error)

    def test_the_documentation_is_readable_from_the_source_tree(self):
        done = self.child("how-to")
        self.assertEqual(done.code, 0, done.err)
        self.assertIn("readme", done.out)
        self.assertIn("name: conflu-c-cli", self.child("skill").out)
        self.assertIn("## [", self.child("changelog").out)


if __name__ == "__main__":
    unittest.main()
