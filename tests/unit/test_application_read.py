"""Use cases that read: pages, spaces, search, comments, labels, attachments, export and the setup."""
import json
import unittest
from dataclasses import replace

from conflu_c_cli.application.settings import Settings
from conflu_c_cli.domain.errors import (
    ConfigError,
    NotFoundError,
    UnavailableError,
    UsageError,
    ValidationError,
)
from conflu_c_cli.domain.model import User
from conflu_c_cli.version import __version__
from tests.support.fakes import (
    ACCOUNT,
    BASE,
    FakeGateway,
    MemoryCache,
    MemoryConfigStore,
    MemoryFiles,
    RecordingDiagnostics,
    build_app,
    default_settings,
)


def app_with(gateway=None, files=None, store=None, settings=None, diagnostics=None, environ=None):
    return build_app(gateway=gateway or FakeGateway(), files=files, store=store, settings=settings, diagnostics=diagnostics, environ=environ)


class ViewPageTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.diagnostics = RecordingDiagnostics()
        self.app = app_with(self.gateway, diagnostics=self.diagnostics)

    def test_a_page_as_markdown_without_people(self):
        view = self.app.view_page.execute("2002")
        self.assertEqual(view.page.title, "Release notes")
        self.assertIsNone(view.page.body)  # the body is in `view.body`
        self.assertEqual(view.body.format, "markdown")
        self.assertIn("# Release notes", view.body.text)
        self.assertIn("First", view.body.text)
        self.assertEqual(view.body.dropped, ("macro:toc", "mention", "redacted-text"))
        self.assertNotIn("alex@example.com", view.body.text)
        self.assertNotIn(ACCOUNT, view.body.text)
        self.assertIsNone(view.page.author)
        self.assertIsNone(view.page.version.author)
        self.assertFalse(view.users_shown)

    def test_hidden_e_mail_addresses_are_named_as_a_limit_of_the_markdown_unless_people_are_shown(self):
        self.assertIn("redacted-text", self.app.view_page.execute("2002").body.dropped)
        shown = self.app.view_page.execute("2002", with_users=True).body
        self.assertNotIn("redacted-text", shown.dropped)
        self.assertIn("alex@example.com", shown.text)
        self.assertNotIn("redacted-text", self.app.view_page.execute("2005").body.dropped)

    def test_the_page_can_be_named_by_its_address(self):
        view = self.app.view_page.execute(f"{BASE}/spaces/ENG/pages/2003/Architecture")
        self.assertEqual(view.page.id, "2003")
        self.assertIn("```python", view.body.text)

    def test_storage_format_is_shown_with_the_account_ids_blanked(self):
        view = self.app.view_page.execute("2002", body_format="storage")
        self.assertIn("<h1>Release notes</h1>", view.body.text)
        self.assertNotIn(ACCOUNT, view.body.text)
        self.assertIn('ri:account-id="hidden"', view.body.text)
        self.assertNotIn("alex@example.com", view.body.text)

    def test_with_users_shows_names_and_keeps_account_ids_in_storage(self):
        view = self.app.view_page.execute("2002", body_format="storage", with_users=True)
        self.assertIn(ACCOUNT, view.body.text)
        self.assertEqual(view.page.author.display_name, "Alex Example")
        self.assertEqual(view.page.owner.display_name, "Alex Example")
        self.assertEqual(view.page.version.author.display_name, "Alex Example")
        self.assertTrue(view.users_shown)
        self.assertEqual(len(self.gateway.called("lookup_users")), 1)

    def test_a_failed_name_lookup_leaves_the_ids_and_warns(self):
        self.gateway.errors["lookup_users"] = UnavailableError("busy")
        view = self.app.view_page.execute("2002", with_users=True)
        self.assertEqual(view.page.author.account_id, ACCOUNT)
        self.assertEqual(view.page.author.display_name, "")
        self.assertTrue(any("busy" in warning for warning in self.diagnostics.warnings))

    def test_the_policy_forbids_showing_people(self):
        app = app_with(self.gateway, settings=default_settings(hide_users=True))
        with self.assertRaises(ValidationError) as caught:
            app.view_page.execute("2002", with_users=True)
        self.assertIn("CONFLUENCE_HIDE_USERS", caught.exception.message)
        self.assertEqual(self.gateway.called("get_page"), [])

    def test_plain_text_and_no_body(self):
        text = self.app.view_page.execute("2002", body_format="text").body
        self.assertEqual(text.format, "text")
        self.assertNotIn("**", text.text)
        self.assertNotIn("<", text.text)
        none = self.app.view_page.execute("2002", with_body=False)
        self.assertIsNone(none.body)
        self.assertEqual(self.gateway.called("get_page")[-1], ("get_page", "2002", False))

    def test_unknown_formats_and_pages(self):
        with self.assertRaises(UsageError):
            self.app.view_page.execute("2002", body_format="html")
        with self.assertRaises(NotFoundError):
            self.app.view_page.execute("999")
        with self.assertRaises(ValidationError):
            self.app.view_page.execute("not a page")

    def test_ancestors_and_comments_are_loaded_on_request(self):
        view = self.app.view_page.execute("2004", with_ancestors=True)
        self.assertEqual([(ref.id, ref.title) for ref in view.page.ancestors], [("2001", "Engineering Home"), ("2003", "Architecture")])
        self.assertEqual(self.gateway.called("list_comments"), [])
        view = self.app.view_page.execute("2002", with_comments=True)
        self.assertEqual([(item.comment.id, item.comment.parent_id) for item in view.comments], [("4001", ""), ("4002", "4001")])
        self.assertIn("Looks good.", view.comments[0].body.text)
        self.assertIsNone(view.comments[0].comment.author)
        self.assertEqual(view.comments[0].comment.body, "")

    def test_raw_json_loses_the_people(self):
        raw = self.app.view_page.execute("2002", want_raw=True).raw
        self.assertNotIn(ACCOUNT, str(raw))
        shown = self.app.view_page.execute("2002", want_raw=True, with_users=True).raw
        self.assertIn(ACCOUNT, str(shown))
        self.assertIsNone(self.app.view_page.execute("2002").raw)


class ListPagesTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.app = app_with(self.gateway, settings=default_settings(space="ENG"))

    def test_the_current_space_is_the_default_and_a_page_has_a_cursor(self):
        result = self.app.list_pages.execute(limit=2)
        self.assertEqual(result.space.key, "ENG")
        self.assertEqual([page.id for page in result.pages], ["2001", "2002"])
        self.assertEqual(result.next_cursor, "2")
        rest = self.app.list_pages.execute(limit=2, cursor="2")
        self.assertEqual([page.id for page in rest.pages], ["2003", "2004"])

    def test_all_pages_are_fetched_piece_by_piece(self):
        result = self.app.list_pages.execute(fetch_everything=True)
        self.assertEqual([page.id for page in result.pages], ["2001", "2002", "2003", "2004", "2005"])
        self.assertEqual((result.next_cursor, result.truncated), ("", False))
        self.assertEqual(len(self.gateway.called("list_pages")), 3)

    def test_without_a_space_every_page_of_the_site_is_listed(self):
        app = app_with(self.gateway)
        result = app.list_pages.execute(fetch_everything=True)
        self.assertIsNone(result.space)
        self.assertIn("3001", [page.id for page in result.pages])

    def test_title_sort_root_and_unknown_space(self):
        self.assertEqual([page.id for page in self.app.list_pages.execute(title="release NOTES").pages], ["2002"])
        self.assertEqual([page.id for page in self.app.list_pages.execute(space="ENG", root_only=True).pages], ["2001"])
        self.assertEqual(self.app.list_pages.execute(sort="-id", limit=1).pages[0].id, "2005")
        with self.assertRaises(NotFoundError):
            self.app.list_pages.execute(space="NOPE")
        with self.assertRaises(UsageError):
            app_with(self.gateway).list_pages.execute(root_only=True)

    def test_people_are_not_in_the_list(self):
        self.assertTrue(all(page.author is None and page.owner is None for page in self.app.list_pages.execute().pages))


class TreeAndVersionsTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.app = app_with(self.gateway)

    def test_the_tree_below_a_page_in_reading_order(self):
        result = self.app.tree_pages.execute("2001", depth=3)
        self.assertEqual((result.root.id, result.root.title, result.space_key), ("2001", "Engineering Home", "ENG"))
        self.assertEqual([(node.id, node.depth) for node in result.nodes], [("2003", 1), ("2004", 2), ("2005", 1), ("2002", 1)])
        self.assertFalse(result.truncated)

    def test_the_depth_is_limited(self):
        self.assertEqual([node.id for node in self.app.tree_pages.execute("2001", depth=1).nodes if node.depth > 1], [])
        for depth in (0, 11):
            with self.assertRaises(UsageError):
                self.app.tree_pages.execute("2001", depth=depth)

    def test_versions_newest_first_with_a_cursor(self):
        result = self.app.list_versions.execute("2002", limit=2)
        self.assertEqual([version.number for version in result.versions], [3, 2])
        self.assertEqual(result.next_cursor, "2")
        everything = self.app.list_versions.execute("2002", fetch_everything=True)
        self.assertEqual([version.number for version in everything.versions], [3, 2, 1])
        self.assertTrue(all(version.author is None for version in everything.versions))

    def test_who_saved_a_version_only_on_request(self):
        result = self.app.list_versions.execute("2002", fetch_everything=True, with_users=True)
        self.assertEqual({version.author.display_name for version in result.versions}, {"Alex Example"})
        self.assertTrue(result.users_shown)

    def test_a_page_with_one_version(self):
        self.assertEqual([version.number for version in self.app.list_versions.execute("2003").versions], [1])


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.app = app_with(self.gateway)

    def test_the_query_is_built_from_the_options(self):
        result = self.app.search_content.execute(text="data quality", space="ENG", under="2001")
        self.assertEqual(result.cql, 'type = page AND space = "ENG" AND text ~ "data quality" AND ancestor = 2001')
        self.assertEqual(self.gateway.called("search")[0][1:], (result.cql, 25, 0))

    def test_a_page_address_names_the_ancestor(self):
        result = self.app.search_content.execute(text="x", under=f"{BASE}/spaces/ENG/pages/2003/Architecture")
        self.assertIn("ancestor = 2003", result.cql)

    def test_paging_and_fetching_everything(self):
        first = self.app.search_content.execute(text="x", limit=2)
        self.assertEqual(([hit.id for hit in first.hits], first.total, first.start), (["2002", "2003"], 3, 0))
        second = self.app.search_content.execute(text="x", limit=2, start=2)
        self.assertEqual(([hit.id for hit in second.hits], second.start), (["2004"], 2))
        everything = self.app.search_content.execute(text="x", fetch_everything=True)
        self.assertEqual([hit.id for hit in everything.hits], ["2002", "2003", "2004"])
        self.assertFalse(everything.truncated)

    def test_a_cql_query_replaces_the_options(self):
        result = self.app.search_content.execute(cql="type = page AND creator = currentUser()", text="ignored")
        self.assertEqual(result.cql, "type = page AND creator = currentUser()")

    def test_nothing_to_search_for_is_refused(self):
        with self.assertRaises(ValidationError):
            self.app.search_content.execute()

    def test_people_are_removed_from_hits_and_raw_results(self):
        self.gateway.search_hits[0] = replace(self.gateway.search_hits[0], title="Mail alex@example.com", excerpt="by alex@example.com")
        result = self.app.search_content.execute(text="x", limit=1)
        self.assertNotIn("alex@example.com", repr(result.hits))
        self.assertNotIn(ACCOUNT, str(result.raw_results))

    def test_the_excerpt_is_withheld_unless_people_are_asked_for(self):
        hidden = self.app.search_content.execute(text="x", limit=1)
        self.assertEqual((hidden.hits[0].excerpt, hidden.excerpts_shown), ("", False))
        self.assertEqual([item["excerpt"] for item in hidden.raw_results], [None])
        shown = self.app.search_content.execute(text="x", limit=1, with_users=True)
        self.assertEqual((shown.hits[0].excerpt, shown.excerpts_shown), ("the october notes", True))
        self.assertEqual([item["excerpt"] for item in shown.raw_results], ["the october notes"])
        everything = self.app.search_content.execute(text="x", fetch_everything=True)
        self.assertEqual({hit.excerpt for hit in everything.hits}, {""})

    def test_asking_for_people_is_refused_under_the_policy(self):
        app = app_with(self.gateway, settings=default_settings(hide_users=True))
        with self.assertRaises(ValidationError) as caught:
            app.search_content.execute(text="x", with_users=True)
        self.assertIn("CONFLUENCE_HIDE_USERS", caught.exception.message)
        self.assertEqual(self.gateway.called("search"), [])
        self.assertEqual(app.search_content.execute(text="x", limit=1).hits[0].excerpt, "")  # without the flag it works


class SpacesTest(unittest.TestCase):
    def setUp(self):
        self.app = app_with(FakeGateway(), settings=default_settings(space="ENG"))

    def test_spaces_with_paging_search_and_type(self):
        self.assertEqual([space.key for space in self.app.list_spaces.execute(limit=1).spaces], ["DOCS"])
        self.assertEqual(self.app.list_spaces.execute(limit=1).next_cursor, "1")
        self.assertEqual([space.key for space in self.app.list_spaces.execute(fetch_everything=True).spaces], ["DOCS", "ENG"])
        self.assertEqual([space.key for space in self.app.list_spaces.execute(search="engin").spaces], ["ENG"])
        self.assertEqual(self.app.list_spaces.execute(space_type="personal").spaces, [])
        with self.assertRaises(UsageError):
            self.app.list_spaces.execute(space_type="secret")

    def test_one_space_by_key_or_the_current_one(self):
        self.assertEqual(self.app.show_space.execute("docs").key, "DOCS")
        self.assertEqual(self.app.show_space.execute().key, "ENG")
        with self.assertRaises(UsageError):
            app_with(FakeGateway()).show_space.execute()


class CommentsLabelsAttachmentsTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.app = app_with(self.gateway)

    def test_conversations_with_their_replies(self):
        views = self.app.list_comments.execute("2002")
        self.assertEqual([(view.comment.id, view.comment.parent_id) for view in views], [("4001", ""), ("4002", "4001")])
        self.assertEqual(views[1].body.text, "Thanks!")
        self.assertTrue(all(view.comment.author is None for view in views))

    def test_inline_comments_on_request(self):
        views = self.app.list_comments.execute("2002", inline=True)
        self.assertEqual([view.comment.id for view in views], ["4001", "4002", "4003"])
        self.assertEqual(views[2].comment.kind, "inline")
        self.assertEqual(views[2].comment.resolution, "open")

    def test_comment_authors_with_users_and_the_policy(self):
        views = self.app.list_comments.execute("2002", with_users=True)
        self.assertEqual(views[0].comment.author.display_name, "Alex Example")
        with self.assertRaises(ValidationError):
            app_with(self.gateway, settings=default_settings(hide_users=True)).list_comments.execute("2002", with_users=True)

    def test_comment_format(self):
        self.assertIn("<p>Looks good.</p>", self.app.list_comments.execute("2002", body_format="storage")[0].body.text)
        with self.assertRaises(UsageError):
            self.app.list_comments.execute("2002", body_format="rtf")

    def test_labels(self):
        self.assertEqual([label.name for label in self.app.list_labels.execute("2002")], ["release", "notes"])
        self.assertEqual(self.app.list_labels.execute("2003"), [])

    def test_attachments_with_paging_and_a_name_filter(self):
        result = self.app.list_attachments.execute("2002", limit=1)
        self.assertEqual(([item.id for item in result.attachments], result.next_cursor), (["att5001"], "1"))
        everything = self.app.list_attachments.execute("2002", fetch_everything=True)
        self.assertEqual([item.title for item in everything.attachments], ["diagram.png", "notes.txt"])
        self.assertEqual([item.id for item in self.app.list_attachments.execute("2002", name="notes.txt").attachments], ["att5002"])


class DownloadTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.files = MemoryFiles()
        self.app = app_with(self.gateway, files=self.files)

    def test_one_attachment_by_its_id(self):
        done = self.app.download_attachments.execute("att5001", out_dir="out")
        self.assertEqual([(item.path, item.size, item.action) for item in done], [("out/diagram.png", 10, "downloaded")])
        self.assertEqual(self.files.files["out/diagram.png"], b"PNGDATA123")

    def test_files_of_a_page_by_name_and_all_of_them(self):
        self.app.download_attachments.execute("2002", names=["notes.txt"], out_dir="out")
        self.assertEqual(self.files.files["out/notes.txt"], b"hello notes\n")
        done = self.app.download_attachments.execute("2002", everything=True, out_dir="all")
        self.assertEqual(sorted(item.path for item in done), ["all/diagram.png", "all/notes.txt"])

    def test_a_dry_run_writes_nothing_and_downloads_nothing(self):
        done = self.app.download_attachments.execute("2002", everything=True, out_dir="out", dry_run=True)
        self.assertEqual({item.action for item in done}, {"would download"})
        self.assertEqual((self.files.files, self.gateway.called("download_attachment")), ({}, []))

    def test_an_existing_file_is_kept_unless_forced(self):
        self.files.write_bytes("out/diagram.png", b"mine")
        with self.assertRaises(ValidationError) as caught:
            self.app.download_attachments.execute("att5001", out_dir="out")
        self.assertIn("--force", caught.exception.hint)
        self.assertEqual(self.files.files["out/diagram.png"], b"mine")
        self.app.download_attachments.execute("att5001", out_dir="out", force=True)
        self.assertEqual(self.files.files["out/diagram.png"], b"PNGDATA123")

    def test_nothing_is_written_when_one_of_several_files_exists(self):
        self.files.write_bytes("out/notes.txt", b"mine")
        with self.assertRaises(ValidationError):
            self.app.download_attachments.execute("2002", everything=True, out_dir="out")
        self.assertNotIn("out/diagram.png", self.files.files)

    def test_unknown_names_and_missing_choices(self):
        with self.assertRaises(NotFoundError):
            self.app.download_attachments.execute("2002", names=["missing.txt"])
        with self.assertRaises(UsageError):
            self.app.download_attachments.execute("2002")
        with self.assertRaises(NotFoundError):
            self.app.download_attachments.execute("2003", everything=True)
        with self.assertRaises(NotFoundError):
            self.app.download_attachments.execute("att999")

    def test_a_dangerous_name_is_made_safe(self):
        self.gateway.attachments["2002"][0] = replace(self.gateway.attachments["2002"][0], title="../../evil:name.png")
        done = self.app.download_attachments.execute("att5001", out_dir="out")
        self.assertEqual(done[0].path, "out/evil_name.png")
        self.assertEqual(list(self.files.files), ["out/evil_name.png"])

    def test_attachments_that_would_become_one_file_are_refused_before_anything_is_written(self):
        first, notes = self.gateway.attachments["2002"]
        self.gateway.attachments["2002"] = [first, notes, replace(first, id="att5008", title="DIAGRAM.png")]
        with self.assertRaises(ValidationError) as caught:
            self.app.download_attachments.execute("2002", everything=True, out_dir="out", force=True)
        self.assertIn("same file", caught.exception.message)
        self.assertEqual((self.files.files, self.gateway.called("download_attachment")), ({}, []))

    def test_names_that_collide_once_they_are_made_safe_are_refused_too(self):
        first = self.gateway.attachments["2002"][0]
        self.gateway.attachments["2002"] = [replace(first, id="att5010", title="a:b.txt"), replace(first, id="att5011", title="a_b.txt")]
        with self.assertRaises(ValidationError) as caught:
            self.app.download_attachments.execute("2002", everything=True, out_dir="out")
        self.assertEqual(caught.exception.details["attachments"], ["att5010", "att5011"])
        self.assertEqual(self.files.files, {})

    def test_an_accent_spelled_two_ways_is_one_name(self):
        first = self.gateway.attachments["2002"][0]
        self.gateway.attachments["2002"] = [replace(first, id="att5012", title="caf\u00e9.txt"), replace(first, id="att5013", title="cafe\u0301.txt")]
        with self.assertRaises(ValidationError):
            self.app.download_attachments.execute("2002", everything=True, out_dir="out")

    def test_the_same_attachment_asked_for_twice_is_downloaded_once(self):
        done = self.app.download_attachments.execute("2002", names=["notes.txt", "notes.txt"], out_dir="out")
        self.assertEqual([item.path for item in done], ["out/notes.txt"])
        self.assertEqual(len(self.gateway.called("download_attachment")), 1)

    def test_an_incomplete_download_is_not_written(self):
        self.gateway.attachment_data["att5001"] = b"short"
        with self.assertRaises(UnavailableError):
            self.app.download_attachments.execute("att5001", out_dir="out")
        self.assertEqual(self.files.files, {})


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.files = MemoryFiles()
        self.app = app_with(self.gateway, files=self.files)

    def test_a_space_becomes_files_and_an_index(self):
        result = self.app.export_pages.execute(out_dir="out", space="ENG")
        self.assertEqual(len(result.pages), 5)
        self.assertEqual(result.index_file, "out/index.json")
        text = self.files.text("out/release-notes-2002.md")
        self.assertTrue(text.startswith("---\ntitle: Release notes\npage_id: 2002\nspace: ENG\nparent: 2001\nversion: 3\n"))
        self.assertIn("lossy: macro:toc, mention, redacted-text", text)
        self.assertIn("# Release notes", text)
        self.assertNotIn(ACCOUNT, text)
        self.assertNotIn("alex@example.com", text)

    def test_the_index_has_no_personal_data(self):
        import json

        self.app.export_pages.execute(out_dir="out", space="ENG")
        index = json.loads(self.files.text("out/index.json"))
        self.assertEqual((index["space"], index["format"], index["exportedAt"]), ("ENG", "markdown", "2026-10-15T08:00:00+00:00"))
        self.assertEqual([page["id"] for page in index["pages"]], ["2004", "2003", "2001", "2005", "2002"])  # by title
        self.assertNotIn(ACCOUNT, self.files.text("out/index.json"))
        notes = next(page for page in index["pages"] if page["id"] == "2002")
        self.assertEqual((notes["lossy"], notes["parentId"], notes["version"]), (["macro:toc", "mention", "redacted-text"], "2001", 3))

    def test_a_page_tree_from_a_root(self):
        result = self.app.export_pages.execute(out_dir="out", root="2003")
        self.assertEqual(sorted(page.id for page in result.pages), ["2003", "2004"])
        self.assertEqual(result.root, "2003")

    def test_storage_format_is_written_as_xml_files(self):
        self.app.export_pages.execute(out_dir="out", space="ENG", body_format="storage")
        self.assertIn("<h1>Release notes</h1>", self.files.text("out/release-notes-2002.xml"))
        self.assertNotIn(ACCOUNT, self.files.text("out/release-notes-2002.xml"))

    def test_a_dry_run_writes_nothing(self):
        result = self.app.export_pages.execute(out_dir="out", space="ENG", dry_run=True)
        self.assertEqual((len(result.pages), self.files.files), (5, {}))

    def test_existing_files_are_kept_unless_forced(self):
        self.files.write_text("out/release-notes-2002.md", "mine")
        with self.assertRaises(ValidationError):
            self.app.export_pages.execute(out_dir="out", space="ENG")
        self.assertEqual(self.files.text("out/release-notes-2002.md"), "mine")
        self.app.export_pages.execute(out_dir="out", space="ENG", force=True)
        self.assertIn("# Release notes", self.files.text("out/release-notes-2002.md"))

    def test_what_to_export_must_be_clear(self):
        with self.assertRaises(UsageError):
            self.app.export_pages.execute(out_dir="out")
        with self.assertRaises(UsageError):
            self.app.export_pages.execute(out_dir="out", space="ENG", root="2001")
        with self.assertRaises(UsageError):
            self.app.export_pages.execute(out_dir="out", space="ENG", body_format="pdf")


class SetupTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.store = MemoryConfigStore()
        self.app = app_with(self.gateway, store=self.store)

    def test_the_token_is_saved_stripped_and_removed(self):
        self.app.config.save_token("  abc123token\n")
        self.assertEqual(self.store.values["CONFLUENCE_API_TOKEN"], "abc123token")
        self.assertTrue(self.app.config.remove_token())
        self.assertFalse(self.app.config.remove_token())

    def test_a_bad_token_is_refused(self):
        for token in ("", "  \n", "two words", "line\nbreak"):
            with self.subTest(token=token):
                with self.assertRaises(ValidationError):
                    self.app.config.save_token(token)
        self.assertEqual(self.store.values, {})

    def test_settings_are_checked_when_they_are_set(self):
        self.app.config.set_value("CONFLUENCE_BASE_URL", " https://example.atlassian.net/wiki ")
        self.app.config.set_value("CONFLUENCE_EMAIL", "user@example.com")
        self.app.config.set_value("CONFLUENCE_HIDE_USERS", "true")
        self.assertEqual(self.store.values["CONFLUENCE_BASE_URL"], "https://example.atlassian.net/wiki")
        for name, value in (
            ("CONFLUENCE_BASE_URL", "example.atlassian.net"),
            ("CONFLUENCE_BASE_URL", "https://user:secret@example.atlassian.net/wiki"),
            ("CONFLUENCE_BASE_URL", "https://example.atlassian.net/wiki?x=1"),
            ("CONFLUENCE_EMAIL", "not an address"),
            ("CONFLUENCE_HIDE_USERS", "perhaps"),
        ):
            with self.subTest(name=name, value=value):
                with self.assertRaises((ValidationError, ConfigError)):
                    self.app.config.set_value(name, value)

    def test_a_secret_and_an_unknown_setting_cannot_be_set_this_way(self):
        with self.assertRaises(UsageError) as caught:
            self.app.config.set_value("CONFLUENCE_API_TOKEN", "x")
        self.assertIn("setup-token", caught.exception.hint)
        with self.assertRaises(UsageError):
            self.app.config.set_value("CONFLUENCE_NOPE", "x")
        with self.assertRaises(UsageError):
            self.app.config.unset_value("CONFLUENCE_NOPE")

    def test_entries_show_sources_and_mask_secrets_and_e_mail(self):
        self.store.values.update({"CONFLUENCE_API_TOKEN": "very-secret-token", "CONFLUENCE_EMAIL": "alex@example.com", "CONFLUENCE_SPACE": "ENG"})
        app = app_with(self.gateway, store=self.store, environ={"CONFLUENCE_SPACE": "DOCS"})
        entries = {entry.name: entry for entry in app.config.entries()}
        self.assertEqual(entries["CONFLUENCE_API_TOKEN"].value, "******** (17 characters)")
        self.assertTrue(entries["CONFLUENCE_API_TOKEN"].secret)
        self.assertEqual(entries["CONFLUENCE_EMAIL"].value, "a***@example.com")
        self.assertEqual((entries["CONFLUENCE_SPACE"].value, entries["CONFLUENCE_SPACE"].source), ("DOCS", "environment"))
        self.assertEqual(entries["CONFLUENCE_RETRY"].source, "default")
        self.assertNotIn("very-secret-token", repr(app.config.entries()))

    def test_selecting_a_space_proves_access_first(self):
        self.assertEqual(self.app.config.select_space("eng").key, "ENG")
        self.assertEqual(self.store.values["CONFLUENCE_SPACE"], "ENG")
        with self.assertRaises(NotFoundError):
            self.app.config.select_space("NOPE")
        self.assertEqual(self.store.values["CONFLUENCE_SPACE"], "ENG")
        self.assertTrue(self.app.config.clear_space())
        self.assertFalse(self.app.config.clear_space())

    def test_ping_names_the_user_unless_quiet_or_hidden(self):
        self.assertEqual(self.app.ping.execute().user.display_name, "Alex Example")
        self.assertIsNone(self.app.ping.execute(quiet=True).user)
        self.assertIsNone(app_with(self.gateway, settings=default_settings(hide_users=True)).ping.execute().user)


class DoctorTest(unittest.TestCase):
    def checks(self, settings=None, gateway=None, files=None):
        app = app_with(gateway or FakeGateway(), files=files or MemoryFiles({"memory://config": "x"}), settings=settings)
        return {check.name: check for check in app.doctor.execute()}

    def test_a_good_setup_is_all_ok(self):
        checks = self.checks(default_settings(space="ENG"))
        self.assertTrue(all(check.status == "ok" for check in checks.values()), checks)
        self.assertEqual(checks["connection"].detail, "reachable, the credentials are accepted")
        self.assertEqual(checks["space"].detail, "ENG is accessible")
        self.assertNotIn("secret-token", repr(checks))

    def test_what_is_missing_fails_and_the_connection_is_skipped(self):
        checks = self.checks(Settings())
        self.assertEqual([checks[name].status for name in ("base url", "email", "token")], ["fail"] * 3)
        self.assertEqual(checks["connection"].status, "warn")
        for name in ("base url", "email", "token"):
            self.assertIn("conflu", checks[name].hint)

    def test_the_address_is_checked(self):
        cases = {
            "https://example.atlassian.net": ("ok", "used as https://example.atlassian.net/wiki"),
            "http://example.atlassian.net/wiki": ("fail", "plain http"),
            "http://127.0.0.1:8080/wiki": ("ok", "on this computer"),
            "ftp://example": ("fail", "http:// or https://"),
            "https://wiki.example.com/wiki": ("warn", "not an atlassian.net address"),
            "https://api.atlassian.com/ex/confluence/0a1b-2c3d": ("ok", "used as https://api.atlassian.com/ex/confluence/0a1b-2c3d/wiki"),
            "https://user:pw@example.atlassian.net/wiki": ("fail", "user name or password"),
        }
        for url, (status, text) in cases.items():
            with self.subTest(url=url):
                check = self.checks(default_settings(base_url=url))["base url"]
                self.assertEqual(check.status, status)
                self.assertIn(text, check.detail)
        allowed = self.checks(default_settings(base_url="http://example.com/wiki", allow_http=True))["base url"]
        self.assertEqual(allowed.status, "warn")

    def test_a_custom_domain_is_a_warning_with_the_way_out_and_does_not_stop_the_other_checks(self):
        checks = self.checks(default_settings(base_url="https://wiki.example.org/wiki"))
        self.assertEqual(checks["base url"].status, "warn")
        for text in ("https://wiki.example.org/_edge/tenant_info", "https://api.atlassian.com/ex/confluence/CLOUD_ID", "401 or 403"):
            self.assertIn(text, checks["base url"].hint)
        self.assertEqual(checks["connection"].status, "ok")  # a warning is advice; the connection is still tried

    def test_tls_findings(self):
        self.assertIn("strict X.509 checks are off", self.checks()["tls"].detail)
        self.assertIn("strict X.509 checks on", self.checks(default_settings(tls_strict=True))["tls"].detail)
        self.assertEqual(self.checks(default_settings(insecure=True))["tls"].status, "warn")
        self.assertEqual(self.checks(default_settings(ca_bundle="/missing.pem"))["tls"].status, "fail")
        ok = self.checks(default_settings(ca_bundle="/ca.pem"), files=MemoryFiles({"memory://config": "x", "/ca.pem": "pem"}))["tls"]
        self.assertEqual(ok.status, "ok")
        self.assertIn("system certificate store plus", ok.detail)

    def test_a_rejected_login_is_the_finding(self):
        gateway = FakeGateway()
        from conflu_c_cli.domain.errors import AuthError

        gateway.errors["current_user"] = AuthError("Confluence did not accept the credentials (HTTP 401).", hint="Check CONFLUENCE_EMAIL.")
        check = self.checks(gateway=gateway)["connection"]
        self.assertEqual((check.status, check.hint), ("fail", "Check CONFLUENCE_EMAIL."))

    def test_unreadable_spaces_and_a_bad_current_space(self):
        gateway = FakeGateway()
        from conflu_c_cli.domain.errors import AuthError

        gateway.errors["list_spaces"] = AuthError("refused")
        checks = self.checks(default_settings(space="NOPE"), gateway)
        self.assertEqual(checks["spaces"].status, "warn")
        self.assertIn("read:space:confluence", checks["spaces"].hint)
        self.assertEqual(checks["space"].status, "fail")
        self.assertEqual(self.checks()["space"].status, "warn")
        self.assertEqual(checks["api"].status, "warn")  # v1 answered (the current user), v2 did not (the spaces)
        self.assertIn("v1 answers and v2 does not", checks["api"].detail)
        self.assertIn("Data Center", checks["api"].hint)

    def test_the_api_check_says_which_apis_answer_and_what_the_cli_is_written_for(self):
        check = self.checks()["api"]
        self.assertEqual(check.status, "ok")
        for text in ("REST API v2 and v1 answer", "2026-10-30", "v2 2.0.0", "v1 1.0.0"):
            self.assertIn(text, check.detail)
        skipped = self.checks(Settings())
        self.assertNotIn("api", skipped)  # it is an online check: nothing to say until the configuration is fixed

    def test_privacy_is_reported(self):
        self.assertIn("never printed", self.checks(default_settings(hide_users=True))["privacy"].detail)

    def test_a_missing_config_file_is_a_warning(self):
        check = self.checks(files=MemoryFiles())["config file"]
        self.assertEqual(check.status, "warn")


def configured(**values):
    """Settings as they come from the configuration, the environment and the profile."""
    return Settings.from_mapping({"CONFLUENCE_BASE_URL": BASE, "CONFLUENCE_EMAIL": "user@example.com", "CONFLUENCE_API_TOKEN": "secret-token", **values})


ONLINE = ["connection", "spaces", "api", "space"]
LOCAL = ["runtime", "config file", "base url", "email", "token", "tls"]


class DoctorRunTest(unittest.TestCase):
    """`--quick`, `--cached AGE`, the privacy check and the launcher: what the use case does, without the command line."""

    def run_doctor(self, gateway=None, *, cache=None, runtime=None, options=None, files=None, **setting_values):
        app = build_app(
            gateway=gateway or FakeGateway(),
            files=files or MemoryFiles({"memory://config": "x"}),
            settings=configured(**setting_values),
            cache=cache,
            runtime=runtime,
        )
        run = app.doctor.run(**(options or {}))
        return run, {check.name: check for check in run.checks}

    def test_the_full_run_has_the_checks_in_this_order(self):
        run, checks = self.run_doctor(CONFLUENCE_SPACE="ENG")
        self.assertEqual(list(checks), [*LOCAL, *ONLINE, "privacy"])
        self.assertEqual((run.cached, run.cached_at), (False, ""))

    def test_quick_asks_twice_at_most_and_leaves_out_the_current_space(self):
        gateway = FakeGateway()
        run, checks = self.run_doctor(gateway, options={"quick": True}, CONFLUENCE_SPACE="ENG")
        self.assertEqual([call[0] for call in gateway.calls], ["current_user", "list_spaces"])  # v1, then v2
        self.assertEqual(list(checks), [*LOCAL, "connection", "spaces", "api", "privacy"])
        self.assertEqual(checks["api"].status, "ok")
        self.assertFalse(run.cached)

    def test_quick_leaves_the_space_check_out_when_there_is_no_current_space_too(self):
        gateway = FakeGateway()
        _, checks = self.run_doctor(gateway, options={"quick": True})
        self.assertEqual(len(gateway.calls), 2)
        self.assertNotIn("space", checks)

    def test_quick_still_stops_at_a_login_that_fails(self):
        gateway = FakeGateway()
        gateway.errors["current_user"] = NotFoundError("gone")
        run, checks = self.run_doctor(gateway, options={"quick": True})
        self.assertEqual(checks["connection"].status, "fail")
        self.assertEqual(len(gateway.calls), 1)
        self.assertNotIn("spaces", checks)

    def test_a_second_run_with_cached_asks_nothing_and_says_when_the_first_one_was(self):
        cache, gateway = MemoryCache(), FakeGateway()
        first, _ = self.run_doctor(gateway, cache=cache, options={"cached_for": 600}, CONFLUENCE_SPACE="ENG")
        self.assertFalse(first.cached)
        asked = len(gateway.calls)
        self.assertGreater(asked, 0)
        second, checks = self.run_doctor(gateway, cache=cache, options={"cached_for": 600}, CONFLUENCE_SPACE="ENG")
        self.assertTrue(second.cached)
        self.assertEqual(second.cached_at, "2026-10-15T08:00:00+00:00")  # the time of the fake clock
        self.assertEqual(len(gateway.calls), asked)
        self.assertEqual(list(checks), [*LOCAL, *ONLINE, "privacy"])
        self.assertEqual([check.status for check in second.checks], [check.status for check in first.checks])

    def test_the_local_checks_are_made_again_whatever_is_reused(self):
        cache = MemoryCache()
        self.run_doctor(cache=cache, options={"cached_for": 600})
        run, checks = self.run_doctor(cache=cache, options={"cached_for": 600}, files=MemoryFiles(), CONFLUENCE_HIDE_USERS="true")
        self.assertTrue(run.cached)
        self.assertEqual(checks["config file"].status, "warn")  # this run has no config file
        self.assertIn("never printed", checks["privacy"].detail)

    def test_nothing_is_reused_without_cached(self):
        cache, gateway = MemoryCache(), FakeGateway()
        self.run_doctor(gateway, cache=cache)
        asked = len(gateway.calls)
        for options in ({}, {"cached_for": 0}, {"cached_for": 0.0}):
            with self.subTest(options=options):
                run, _ = self.run_doctor(gateway, cache=cache, options=options)
                self.assertFalse(run.cached)
        self.assertEqual(len(gateway.calls), asked * 4)

    def test_a_run_that_is_older_than_the_age_is_not_reused(self):
        cache, gateway = MemoryCache(), FakeGateway()
        self.run_doctor(gateway, cache=cache)
        ((key, _),) = cache.values.items()
        cache.ages[key] = 599.0
        young, _ = self.run_doctor(gateway, cache=cache, options={"cached_for": 600})
        self.assertTrue(young.cached)
        cache.ages[key] = 601.0
        old, _ = self.run_doctor(gateway, cache=cache, options={"cached_for": 600})
        self.assertFalse(old.cached)
        again, _ = self.run_doctor(gateway, cache=cache, options={"cached_for": 600})  # the run that was just made is new
        self.assertTrue(again.cached)

    def test_a_run_with_a_failure_is_never_remembered(self):
        cache, gateway = MemoryCache(), FakeGateway()
        gateway.errors["get_space"] = NotFoundError("gone")
        run, checks = self.run_doctor(gateway, cache=cache, options={"cached_for": 600}, CONFLUENCE_SPACE="NOPE")
        self.assertEqual(checks["space"].status, "fail")
        self.assertEqual(cache.values, {})
        again, _ = self.run_doctor(gateway, cache=cache, options={"cached_for": 600}, CONFLUENCE_SPACE="NOPE")
        self.assertFalse(again.cached)

    def test_a_failed_connection_is_not_remembered_either(self):
        cache, gateway = MemoryCache(), FakeGateway()
        gateway.errors["current_user"] = NotFoundError("gone")
        self.run_doctor(gateway, cache=cache)
        self.assertEqual(cache.values, {})

    def test_the_local_failures_stop_before_anything_is_asked_or_remembered(self):
        cache, gateway = MemoryCache(), FakeGateway()
        run, checks = self.run_doctor(gateway, cache=cache, options={"cached_for": 600}, CONFLUENCE_API_TOKEN="")
        self.assertEqual((checks["token"].status, checks["connection"].status), ("fail", "warn"))
        self.assertEqual((gateway.calls, cache.values, run.cached), ([], {}, False))

    def test_quick_and_full_runs_are_kept_apart(self):
        cache, gateway = MemoryCache(), FakeGateway()
        self.run_doctor(gateway, cache=cache, options={"quick": True})
        full, _ = self.run_doctor(gateway, cache=cache, options={"cached_for": 600})
        self.assertFalse(full.cached)
        quick, _ = self.run_doctor(gateway, cache=cache, options={"quick": True, "cached_for": 600})
        self.assertTrue(quick.cached)

    def test_a_run_is_not_reused_for_another_site_account_token_or_space(self):
        cache, gateway = MemoryCache(), FakeGateway()
        self.run_doctor(gateway, cache=cache, options={"cached_for": 600}, CONFLUENCE_SPACE="ENG")
        for name, value in (
            ("CONFLUENCE_BASE_URL", "https://wiki.example.com/wiki"),
            ("CONFLUENCE_EMAIL", "other@example.com"),
            ("CONFLUENCE_API_TOKEN", "another-token"),
            ("CONFLUENCE_SPACE", "DOCS"),
            ("CONFLUENCE_INSECURE", "true"),
        ):
            with self.subTest(name=name):
                run, _ = self.run_doctor(gateway, cache=cache, options={"cached_for": 600}, **{"CONFLUENCE_SPACE": "ENG", name: value})
                self.assertFalse(run.cached)
        same, _ = self.run_doctor(gateway, cache=cache, options={"cached_for": 600}, CONFLUENCE_SPACE="ENG")
        self.assertTrue(same.cached)

    def test_the_cache_holds_the_checks_and_nothing_else(self):
        cache = MemoryCache()
        self.run_doctor(cache=cache, CONFLUENCE_SPACE="ENG")
        ((namespace, key), text) = next(iter(cache.values.items()))
        self.assertEqual(namespace, "doctor")
        record = json.loads(text)
        self.assertEqual(set(record), {"at", "checks"})
        self.assertEqual([check["name"] for check in record["checks"]], ONLINE)
        for secret in ("secret-token", "user@example.com", "Alex Example", ACCOUNT):
            self.assertNotIn(secret, text + key)  # not the token, not the account, not a person, not even as part of the name of the record
        self.assertRegex(key, r"^[0-9a-f]{16}$")

    def test_a_record_that_cannot_be_read_is_ignored(self):
        for damaged in (
            "not json",
            "[" * 100000,  # nests deeper than the decoder reads: a RecursionError, not a crash
            "[]",
            "{}",
            '{"at": "x", "checks": [{"nope": 1}]}',
            '{"at": "x", "checks": 5}',
            '{"at": "x", "checks": []}',
            '{"at": "x", "checks": ["connection"]}',
            '{"at": "x", "checks": [{"name": "connection", "status": "bogus", "detail": "", "hint": ""}]}',
            '{"at": "x", "checks": [{"name": "connection", "status": "fail", "detail": "refused", "hint": ""}]}',  # a run with a failure is never kept
        ):
            cache, gateway = MemoryCache(), FakeGateway()
            self.run_doctor(gateway, cache=cache)
            ((key, _),) = cache.values.items()
            cache.values[key] = damaged
            with self.subTest(damaged=damaged[:60]):
                run, _ = self.run_doctor(gateway, cache=cache, options={"cached_for": 600})
                self.assertFalse(run.cached)

    def test_without_a_cache_cached_is_ignored(self):
        gateway = FakeGateway()
        self.run_doctor(gateway, options={"cached_for": 600})
        run, _ = self.run_doctor(gateway, options={"cached_for": 600})
        self.assertFalse(run.cached)
        self.assertEqual(len(gateway.called("current_user")), 2)

    def test_execute_is_the_list_of_checks(self):
        app = build_app(files=MemoryFiles({"memory://config": "x"}))
        self.assertEqual([check.name for check in app.doctor.execute(quick=True)], [*LOCAL, "connection", "spaces", "api", "privacy"])

    # -- privacy ---------------------------------------------------------------------------------

    def test_privacy_is_ok_when_people_are_hidden_and_names_the_profile_that_did_it(self):
        _, plain = self.run_doctor(CONFLUENCE_HIDE_USERS="true")
        self.assertEqual(plain["privacy"].status, "ok")
        self.assertNotIn("profile", plain["privacy"].detail)
        _, by_profile = self.run_doctor(CONFLUENCE_PROFILE="agent")
        self.assertEqual(by_profile["privacy"].status, "ok")
        self.assertIn("(profile agent)", by_profile["privacy"].detail)

    def test_privacy_is_a_warning_under_the_profile_when_people_can_still_be_shown(self):
        _, checks = self.run_doctor(CONFLUENCE_PROFILE="agent", CONFLUENCE_HIDE_USERS="false")
        self.assertEqual(checks["privacy"].status, "warn")
        self.assertIn("CONFLUENCE_HIDE_USERS is set to false", checks["privacy"].detail)
        self.assertIn("conflu config unset CONFLUENCE_HIDE_USERS", checks["privacy"].hint)

    def test_privacy_is_ok_as_it_was_without_a_profile_and_without_the_policy(self):
        run, checks = self.run_doctor()
        self.assertEqual(checks["privacy"].status, "ok")
        self.assertIn("people can be shown", checks["privacy"].detail)
        self.assertFalse(any(check.status == "fail" for check in run.checks))

    def test_strict_privacy_fails_whenever_people_can_be_shown(self):
        for values in ({}, {"CONFLUENCE_PROFILE": "agent", "CONFLUENCE_HIDE_USERS": "false"}):
            with self.subTest(values=values):
                run, checks = self.run_doctor(options={"strict_privacy": True}, **values)
                self.assertEqual(checks["privacy"].status, "fail")
                self.assertIn("CONFLUENCE_HIDE_USERS=true", checks["privacy"].hint)
                self.assertIn("CONFLUENCE_PROFILE=agent", checks["privacy"].hint)
        for values in ({"CONFLUENCE_HIDE_USERS": "true"}, {"CONFLUENCE_PROFILE": "agent"}):
            with self.subTest(values=values):
                _, checks = self.run_doctor(options={"strict_privacy": True}, **values)
                self.assertEqual(checks["privacy"].status, "ok")

    def test_strict_privacy_is_checked_even_when_the_configuration_is_broken(self):
        _, checks = self.run_doctor(options={"strict_privacy": True}, CONFLUENCE_API_TOKEN="")
        self.assertEqual((checks["token"].status, checks["privacy"].status), ("fail", "fail"))

    # -- the launcher ----------------------------------------------------------------------------

    def test_the_launcher_check_is_there_only_when_the_runtime_says(self):
        _, silent = self.run_doctor()
        self.assertNotIn("launcher", silent)

    def test_the_launcher_that_is_found_is_named(self):
        gateway = FakeGateway()
        run, checks = self.run_doctor(gateway, runtime={"version": "1.0.0", "python": "3.13", "launcher": "/opt/tools/bin/conflu"})
        self.assertEqual(checks["launcher"].status, "ok")
        self.assertIn("/opt/tools/bin/conflu", checks["launcher"].detail)
        self.assertEqual(list(checks)[: len(LOCAL) + 1], [*LOCAL, "launcher"])  # after the local checks, before the online ones

    def test_a_launcher_that_is_not_on_the_path_is_a_warning_that_says_how_this_run_started_and_what_to_do(self):
        gateway = FakeGateway()
        facts = {"version": "1.0.0", "python": "3.13", "launcher": "", "program": "/work/conflu-c-cli/conflu.py", "install_script": "/work/conflu-c-cli/install.py"}
        run, checks = self.run_doctor(gateway, runtime=facts)
        check = checks["launcher"]
        self.assertEqual(check.status, "warn")
        self.assertIn("`conflu` is not found on the PATH of this shell", check.detail)
        self.assertIn("/work/conflu-c-cli/conflu.py", check.detail)
        self.assertIn('python "/work/conflu-c-cli/install.py" --bin-dir DIR', check.hint)
        self.assertIn("add the folder of the launcher to the PATH", check.hint)
        self.assertGreater(len(gateway.calls), 0)  # a warning does not stop the online checks
        self.assertFalse(any(item.status == "fail" for item in run.checks))  # and does not fail the doctor

    def test_without_an_installer_the_hint_points_to_the_source_folder(self):
        facts = {"version": "1.0.0", "python": "3.13", "launcher": "", "program": "", "install_script": ""}
        _, checks = self.run_doctor(runtime=facts)
        self.assertIn("python install.py --bin-dir DIR, run in the source folder of conflu-c-cli", checks["launcher"].hint)
        self.assertNotIn("this run was started as", checks["launcher"].detail)

    def test_the_launcher_check_asks_nothing_of_confluence(self):
        gateway = FakeGateway()
        app = build_app(gateway=gateway, runtime={"version": "1.0.0", "python": "3.13", "launcher": ""})
        self.assertEqual(app.doctor._launcher().status, "warn")
        self.assertEqual(gateway.calls, [])

    def test_a_program_is_told_to_run_python_and_not_a_launcher_and_why(self):
        """`cmd.exe` splits the command line before `conflu.cmd` runs: an argument with a quote in it can run a second command, whatever the batch file does."""
        entry = "/work/conflu-c-cli/conflu.py"
        for launcher in ("", "C:/tools/bin/conflu.cmd", "C:/tools/bin/conflu.BAT"):
            with self.subTest(launcher=launcher):
                facts = {"version": "1.0.0", "python": "3.13", "launcher": launcher, "program": "", "install_script": "", "entry": entry}
                _, checks = self.run_doctor(runtime=facts)
                hint = checks["launcher"].hint
                self.assertIn(f'a program that starts commands from an argument list (an agent harness) should not run a launcher but `python "{entry}" ARGS`', hint)
                self.assertIn("cmd.exe splits the command line before `conflu.cmd` runs", hint)
                self.assertIn("run a second command", hint)
                self.assertIn("The launchers are for people at a shell.", hint)
                self.assertEqual(checks["launcher"].status, "ok" if launcher else "warn")  # advice, not a failure

    def test_a_launcher_that_is_no_batch_file_needs_no_such_advice(self):
        facts = {"version": "1.0.0", "python": "3.13", "launcher": "/opt/tools/bin/conflu", "program": "", "install_script": "", "entry": "/work/conflu.py"}
        _, checks = self.run_doctor(runtime=facts)
        self.assertEqual((checks["launcher"].status, checks["launcher"].hint), ("ok", ""))

    def test_without_the_entry_the_advice_names_the_install_folder(self):
        facts = {"version": "1.0.0", "python": "3.13", "launcher": "", "program": "", "install_script": ""}
        _, checks = self.run_doctor(runtime=facts)
        self.assertIn('`python "<install folder>\\conflu.py" ARGS`', checks["launcher"].hint)

    def test_the_advice_keeps_what_the_hint_said_before(self):
        facts = {"version": "1.0.0", "python": "3.13", "launcher": "", "program": "", "install_script": "/work/conflu-c-cli/install.py", "entry": "/work/conflu-c-cli/conflu.py"}
        _, checks = self.run_doctor(runtime=facts)
        self.assertIn('python "/work/conflu-c-cli/install.py" --bin-dir DIR', checks["launcher"].hint)
        self.assertIn("add the folder of the launcher to the PATH", checks["launcher"].hint)

    # -- an address with credentials ------------------------------------------------------------

    def test_an_address_with_credentials_fails_and_is_never_repeated(self):
        for address in (
            "https://" + "alex:s3cr3tpw" + "@example.atlassian.net/wiki",
            "https://" + "alex" + "@example.atlassian.net/wiki",
            "https://" + "alex:pa/s3cr3tpw" + "@example.atlassian.net/wiki",
            "https://" + "alex:pa?s3cr3tpw" + "@example.atlassian.net/wiki",
            "https://example.atlassian.net/wiki/" + "alex:s3cr3tpw" + "@x",
        ):
            with self.subTest(address=address.replace("s3cr3tpw", "<secret>")):
                run, checks = self.run_doctor(CONFLUENCE_BASE_URL=address)
                check = checks["base url"]
                self.assertEqual(check.status, "fail")
                self.assertIn("user name or password", check.detail)
                self.assertNotIn("s3cr3tpw", repr(run.checks))
                self.assertNotIn("alex", check.detail + check.hint)


class ConfigEntriesTest(unittest.TestCase):
    """`conflu config show`: where each value comes from, and what a profile sets."""

    def entries(self, stored=None, environ=None, **values):
        stored = dict(stored or {})
        app = build_app(settings=configured(**{**stored, **dict(environ or {}), **values}), store=MemoryConfigStore(stored), environ=environ)
        return {entry.name: entry for entry in app.config.entries()}

    def test_what_the_profile_sets_is_listed_with_the_source_profile(self):
        entries = self.entries({"CONFLUENCE_PROFILE": "agent"})
        self.assertEqual((entries["CONFLUENCE_PROFILE"].value, entries["CONFLUENCE_PROFILE"].source), ("agent", "config file"))
        self.assertEqual((entries["CONFLUENCE_HIDE_USERS"].value, entries["CONFLUENCE_HIDE_USERS"].source), ("true", "profile"))
        self.assertEqual((entries["CONFLUENCE_OUTPUT"].value, entries["CONFLUENCE_OUTPUT"].source), ("json", "profile"))

    def test_a_setting_of_the_person_is_shown_as_such_even_when_it_is_false(self):
        entries = self.entries({"CONFLUENCE_PROFILE": "agent", "CONFLUENCE_HIDE_USERS": "false", "CONFLUENCE_OUTPUT": "text"})
        self.assertEqual((entries["CONFLUENCE_HIDE_USERS"].value, entries["CONFLUENCE_HIDE_USERS"].source), ("false", "config file"))
        self.assertEqual((entries["CONFLUENCE_OUTPUT"].value, entries["CONFLUENCE_OUTPUT"].source), ("text", "config file"))

    def test_the_environment_wins_and_is_named(self):
        entries = self.entries({"CONFLUENCE_PROFILE": "agent"}, environ={"CONFLUENCE_HIDE_USERS": "false"})
        self.assertEqual((entries["CONFLUENCE_HIDE_USERS"].value, entries["CONFLUENCE_HIDE_USERS"].source), ("false", "environment"))
        from_environment = self.entries(environ={"CONFLUENCE_PROFILE": "agent"})
        self.assertEqual((from_environment["CONFLUENCE_PROFILE"].source, from_environment["CONFLUENCE_HIDE_USERS"].source), ("environment", "profile"))

    def test_an_empty_value_counts_as_not_set_so_the_profile_still_applies(self):
        entries = self.entries({"CONFLUENCE_PROFILE": "agent", "CONFLUENCE_HIDE_USERS": ""})
        self.assertEqual((entries["CONFLUENCE_HIDE_USERS"].value, entries["CONFLUENCE_HIDE_USERS"].source), ("true", "profile"))

    def test_without_a_profile_the_sources_are_what_they_were(self):
        entries = self.entries({"CONFLUENCE_SPACE": "ENG"})
        self.assertEqual({entry.source for name, entry in entries.items() if name != "CONFLUENCE_SPACE"}, {"default"})
        self.assertEqual(entries["CONFLUENCE_SPACE"].source, "config file")

    def test_an_address_with_credentials_is_shown_without_them(self):
        for address, shown in (
            ("https://" + "alex:s3cr3tpw" + "@example.atlassian.net/wiki", "https://********@example.atlassian.net/wiki"),
            ("https://" + "alex:pa/s3cr3tpw" + "@example.atlassian.net/wiki", "(not shown: it holds an @ after the host name)"),
        ):
            for place in ("config file", "environment"):
                with self.subTest(place=place, shown=shown):
                    entries = self.entries({"CONFLUENCE_BASE_URL": address} if place == "config file" else None, environ={"CONFLUENCE_BASE_URL": address} if place == "environment" else None)
                    entry = entries["CONFLUENCE_BASE_URL"]
                    self.assertEqual((entry.value, entry.source), (shown, place))
                    self.assertNotIn("s3cr3tpw", repr(list(entries.values())))


class RawApiTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.app = app_with(self.gateway)

    def test_get_is_free_and_the_path_is_kept(self):
        result = self.app.raw_api.execute("get", "api/v2/pages/2002")
        self.assertEqual(self.gateway.called("request")[0][1:], ("GET", "/api/v2/pages/2002", None))
        self.assertTrue(result.response["ok"])

    def test_both_api_roots_and_a_leading_slash_are_accepted(self):
        for path in ("/api/v2/pages", "rest/api/search?cql=type=page", "/rest/api/user/current"):
            self.assertFalse(self.app.raw_api.execute("GET", path).dry_run)

    def test_other_paths_hosts_and_traversal_are_refused(self):
        for path in ("", "  ", "admin/users", "https://evil.example.com/api/v2/pages", "//evil.example.com/api/x", "api/../admin", "api/v2/%2e%2e/admin", "api\\v2\\x", "plugins/x", "api/v2/pages/1\r\nX-Evil: 1", "api/v2/pages/1\x00"):
            with self.subTest(path=path):
                with self.assertRaises(UsageError):
                    self.app.raw_api.execute("GET", path)
        self.assertEqual(self.gateway.called("request"), [])

    def test_writing_needs_confirmation_and_a_body(self):
        with self.assertRaises(UsageError) as caught:
            self.app.raw_api.execute("PUT", "api/v2/pages/1/title", '{"a": 1}')
        self.assertIn("--write", caught.exception.hint)
        with self.assertRaises(UsageError):
            self.app.raw_api.execute("POST", "api/v2/pages", "", write=True)
        with self.assertRaises(UsageError):
            self.app.raw_api.execute("DELETE", "api/v2/pages/1", write=True)
        with self.assertRaises(ValidationError) as caught:
            self.app.raw_api.execute("POST", "api/v2/pages", "{nope", write=True)
        self.assertIn("--data-file", caught.exception.hint)

    def test_a_dry_run_sends_nothing(self):
        result = self.app.raw_api.execute("PUT", "api/v2/pages/1/title", '{"status": "current", "title": "T"}', write=True, dry_run=True)
        self.assertEqual((result.dry_run, result.body), (True, {"status": "current", "title": "T"}))
        self.assertEqual(self.gateway.called("request"), [])

    def test_the_policy_removes_people_from_the_answer(self):
        app = app_with(self.gateway, settings=default_settings(hide_users=True))
        self.assertEqual(app.raw_api.execute("GET", "api/v2/pages/1").response["user"], {"hidden": True})
        shown = self.app.raw_api.execute("GET", "api/v2/pages/1").response
        self.assertEqual(shown["user"]["accountId"], ACCOUNT)


class ConvertAndSkillTest(unittest.TestCase):
    def setUp(self):
        self.files = MemoryFiles()
        self.app = app_with(FakeGateway(), files=self.files)

    def test_markdown_to_storage_drops_front_matter(self):
        result = self.app.convert_text.execute("---\ntitle: T\n---\n# Hello\n\nSome **bold** text.\n")
        self.assertEqual(result.source, "markdown")
        self.assertIn("<h1>Hello</h1>", result.text)
        self.assertIn("<strong>bold</strong>", result.text)
        self.assertNotIn("title", result.text)

    def test_storage_to_markdown_names_what_is_lost(self):
        result = self.app.convert_text.execute('<p>See <ac:structured-macro ac:name="toc" /></p>', "storage")
        self.assertEqual(result.dropped, ("macro:toc",))
        with self.assertRaises(UsageError):
            self.app.convert_text.execute("x", "rtf")

    def test_the_skill_is_installed_replaced_only_when_asked_and_previewed(self):
        installed = self.app.install_skill.execute(".github/skills")
        self.assertEqual((installed.action, installed.path), ("installed", ".github/skills/conflu-c-cli/SKILL.md"))
        self.assertEqual(self.app.install_skill.execute(".github/skills").action, "unchanged")
        self.files.write_text(installed.path, "my own version")
        with self.assertRaises(ValidationError) as caught:
            self.app.install_skill.execute(".github/skills")
        self.assertIn("--force", caught.exception.hint)
        self.assertEqual(self.app.install_skill.execute(".github/skills", force=True).action, "replaced")
        self.files.write_text(installed.path, "my own version")
        preview = self.app.install_skill.execute(".github/skills", force=True, dry_run=True)
        self.assertEqual((preview.action, self.files.text(installed.path)), ("replaced", "my own version"))

    def test_docs_are_read_through_the_port(self):
        self.assertEqual([topic.name for topic in self.app.read_docs.topics()], ["daily-workflow", "exit-codes"])
        self.assertIn("Overview", self.app.read_docs.readme())
        self.assertIn(f"## [{__version__}]", self.app.read_docs.changelog())


if __name__ == "__main__":
    unittest.main()
