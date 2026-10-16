"""Use cases that change things: create, update, move, comment, label, attach, import."""
import unittest

from conflu_c_cli.domain.drafts import PageChanges, PageDraft
from conflu_c_cli.domain.errors import ConflictError, NotFoundError, RejectedError, UsageError, ValidationError
from tests.support.fakes import ACCOUNT, BASE, FakeGateway, MemoryFiles, build_app, default_settings


def app_with(gateway=None, files=None, **settings):
    return build_app(gateway=gateway or FakeGateway(), files=files, settings=default_settings(**settings))


class CreatePageTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.app = app_with(self.gateway)

    def draft(self, **values):
        return PageDraft(**{"space": "ENG", "title": "New page", "body": "<p>Hi</p>", **values})

    def test_a_dry_run_shows_the_payload_and_creates_nothing(self):
        result = self.app.create_page.execute(self.draft(parent="2003", labels=["Draft"]), dry_run=True)
        self.assertEqual(
            result.payload,
            {"spaceId": "1001", "status": "current", "title": "New page", "parentId": "2003", "body": {"representation": "storage", "value": "<p>Hi</p>"}},
        )
        self.assertEqual((result.action, result.dry_run, result.page, result.labels), ("created", True, None, ["draft"]))
        self.assertEqual(self.gateway.called("create_page"), [])

    def test_the_real_run_sends_exactly_that_payload(self):
        preview = self.app.create_page.execute(self.draft(), dry_run=True)
        result = self.app.create_page.execute(self.draft())
        self.assertEqual(self.gateway.called("create_page")[0][1], preview.payload)
        self.assertEqual((result.action, result.page.id, result.version_to), ("created", "20001", 1))
        self.assertEqual(result.page.parent_id, "2001")  # below the home page of the space

    def test_labels_are_added_after_the_page_exists(self):
        result = self.app.create_page.execute(self.draft(labels=["Alpha", "beta", "alpha"]))
        self.assertEqual(self.gateway.called("add_labels")[0][1:], (result.page.id, [{"prefix": "global", "name": "alpha"}, {"prefix": "global", "name": "beta"}]))
        self.assertEqual(result.labels, ["alpha", "beta"])

    def test_a_failure_of_the_labels_names_the_page_that_was_created(self):
        self.gateway.errors["add_labels"] = RejectedError("too many labels", hint="")
        with self.assertRaises(RejectedError) as caught:
            self.app.create_page.execute(self.draft(labels=["a"]))
        self.assertIn("20001", caught.exception.message)
        self.assertEqual(caught.exception.details["pageId"], "20001")
        self.assertIn("conflu label 20001", caught.exception.hint)

    def test_the_parent_may_be_an_address_and_must_exist_in_the_same_space(self):
        result = self.app.create_page.execute(self.draft(parent=f"{BASE}/spaces/ENG/pages/2003/Architecture"), dry_run=True)
        self.assertEqual(result.payload["parentId"], "2003")
        with self.assertRaises(ValidationError) as caught:
            self.app.create_page.execute(self.draft(parent="3001"))
        self.assertIn("not in space ENG", caught.exception.message)
        with self.assertRaises(NotFoundError):
            self.app.create_page.execute(self.draft(parent="999"))

    def test_a_title_that_exists_is_a_conflict(self):
        with self.assertRaises(ConflictError) as caught:
            self.app.create_page.execute(self.draft(title="release NOTES"))
        self.assertEqual(caught.exception.details["pageId"], "2002")
        self.assertIn("conflu update 2002", caught.exception.hint)
        self.assertEqual(self.gateway.called("create_page"), [])

    def test_the_same_title_in_another_space_is_fine(self):
        self.assertEqual(self.app.create_page.execute(self.draft(space="DOCS", title="Release notes"), dry_run=True).payload["spaceId"], "1002")

    def test_the_current_space_is_the_default_and_one_is_required(self):
        app = app_with(self.gateway, space="DOCS")
        self.assertEqual(app.create_page.execute(self.draft(space=""), dry_run=True).payload["spaceId"], "1002")
        with self.assertRaises(UsageError):
            self.app.create_page.execute(self.draft(space=""))
        with self.assertRaises(NotFoundError):
            self.app.create_page.execute(self.draft(space="NOPE"))

    def test_bad_input_is_refused_before_anything_is_sent(self):
        for values in ({"title": " "}, {"title": "x" * 300}, {"labels": ["two words"]}, {"parent": "abc"}):
            with self.subTest(values=values):
                with self.assertRaises(ValidationError):
                    self.app.create_page.execute(self.draft(**values))
        self.assertEqual(self.gateway.called("create_page"), [])


class UpdatePageTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.app = app_with(self.gateway)

    def test_nothing_to_change_is_refused(self):
        with self.assertRaises(ValidationError) as caught:
            self.app.update_page.execute("2005", PageChanges())
        self.assertIn("--title", caught.exception.hint)

    def test_a_title_alone_leaves_the_body_alone(self):
        result = self.app.update_page.execute("2005", PageChanges(title="Renamed"))
        self.assertEqual(self.gateway.called("get_page")[0], ("get_page", "2005", False))
        self.assertEqual(self.gateway.called("update_title")[0][1:], ("2005", {"status": "current", "title": "Renamed"}))
        self.assertEqual(self.gateway.called("update_page"), [])
        self.assertEqual((result.action, result.page.title, result.version_from, result.version_to), ("updated", "Renamed", 1, 2))

    def test_a_body_replaces_with_the_next_version_number(self):
        result = self.app.update_page.execute("2005", PageChanges(body="<p>New text</p>", message="  Rewrote it "))
        sent = self.gateway.called("update_page")[0][2]
        self.assertEqual(sent["version"], {"number": 2, "message": "Rewrote it"})
        self.assertEqual((sent["id"], sent["title"], sent["status"]), ("2005", "Plain page", "current"))
        self.assertEqual(sent["body"], {"representation": "storage", "value": "<p>New text</p>"})
        self.assertEqual((result.version_from, result.version_to, result.page.body), (1, 2, "<p>New text</p>"))

    def test_a_dry_run_shows_the_same_payload_and_sends_nothing(self):
        preview = self.app.update_page.execute("2005", PageChanges(title="T", body="<p>x</p>"), dry_run=True)
        self.assertEqual(self.gateway.called("update_page"), [])
        real = self.app.update_page.execute("2005", PageChanges(title="T", body="<p>x</p>"))
        self.assertEqual(self.gateway.called("update_page")[0][2], preview.payload)
        self.assertEqual((preview.dry_run, preview.version_from, preview.version_to), (True, 1, 2))
        self.assertFalse(real.dry_run)

    def test_markdown_does_not_replace_a_body_it_cannot_express(self):
        with self.assertRaises(ValidationError) as caught:
            self.app.update_page.execute("2002", PageChanges(body="<p>x</p>", from_markdown=True))
        self.assertIn("macro:toc", caught.exception.message)
        self.assertEqual(caught.exception.details["lost"], ["macro:toc", "mention", "redacted-text"])
        self.assertIn("--append", caught.exception.hint)
        self.assertEqual(self.gateway.called("update_page"), [])

    def test_the_guard_is_also_a_guard_for_the_dry_run(self):
        with self.assertRaises(ValidationError):
            self.app.update_page.execute("2002", PageChanges(body="<p>x</p>", from_markdown=True), dry_run=True)

    def test_force_replaces_anyway_and_says_what_was_lost(self):
        result = self.app.update_page.execute("2002", PageChanges(body="<p>x</p>", from_markdown=True), force=True)
        self.assertEqual(result.lost, ("macro:toc", "mention", "redacted-text"))
        self.assertEqual(self.gateway.pages["2002"].body, "<p>x</p>")

    def test_an_address_that_the_markdown_hides_is_not_overwritten_by_the_placeholder(self):
        self.gateway.pages["2005"].body = "<p>Contact alex@example.com.</p>"
        with self.assertRaises(ValidationError) as caught:
            self.app.update_page.execute("2005", PageChanges(body="<p>Contact [email]. And more.</p>", from_markdown=True))
        self.assertIn("redacted-text", caught.exception.message)
        self.assertEqual(self.gateway.pages["2005"].body, "<p>Contact alex@example.com.</p>")

    def test_the_markdown_copy_of_a_page_that_nobody_edited_changes_nothing(self):
        from conflu_c_cli.application.rendering import render_body
        from conflu_c_cli.domain.markdown import markdown_to_storage

        for page_id in ("2002", "2003", "2005"):  # also pages with macros, mentions and an address
            with self.subTest(page=page_id):
                copy = render_body(self.gateway.pages[page_id].body, "markdown", with_users=False).text
                result = self.app.update_page.execute(page_id, PageChanges(body=markdown_to_storage(copy), from_markdown=True))
                self.assertEqual(result.action, "unchanged")
        self.assertEqual(self.gateway.called("update_page"), [])

    def test_storage_replaces_without_the_guard(self):
        result = self.app.update_page.execute("2002", PageChanges(body="<p>x</p>", from_markdown=False))
        self.assertEqual((result.lost, result.version_to), ((), 4))

    def test_append_and_prepend_keep_what_is_there(self):
        self.app.update_page.execute("2002", PageChanges(body="<p>tail</p>", body_mode="append", from_markdown=True))
        self.assertTrue(self.gateway.pages["2002"].body.endswith("\n<p>tail</p>"))
        self.assertIn('ac:name="toc"', self.gateway.pages["2002"].body)
        self.app.update_page.execute("2002", PageChanges(body="<p>head</p>", body_mode="prepend", from_markdown=True))
        self.assertTrue(self.gateway.pages["2002"].body.startswith("<p>head</p>\n<h1>"))

    def test_a_change_that_changes_nothing_is_reported_as_such(self):
        result = self.app.update_page.execute("2005", PageChanges(title="Plain page", body="<p>Just a paragraph &amp; text.</p>"))
        self.assertEqual(result.action, "unchanged")
        self.assertEqual((self.gateway.called("update_page"), self.gateway.called("update_title")), ([], []))

    def test_guards_against_stale_data(self):
        with self.assertRaises(ConflictError) as caught:
            self.app.update_page.execute("2002", PageChanges(title="T"), if_version=2)
        self.assertEqual(caught.exception.exit_code, 3)
        self.assertEqual((self.gateway.called("update_page"), self.gateway.called("update_title")), ([], []))
        self.app.update_page.execute("2002", PageChanges(title="T"), if_version=3)
        with self.assertRaises(ConflictError):
            self.app.update_page.execute("2002", PageChanges(title="U"), if_unchanged_since="2026-10-01T00:00:00Z")
        self.app.update_page.execute("2002", PageChanges(title="U"), if_unchanged_since="2026-10-16T00:00:00Z")

    def test_a_save_in_between_is_the_conflict_the_server_reports(self):
        self.gateway.errors["update_page"] = ConflictError("Confluence reports a conflict (HTTP 409)")
        with self.assertRaises(ConflictError):
            self.app.update_page.execute("2005", PageChanges(body="<p>x</p>"))

    def test_the_status_of_the_page_is_kept_and_an_archived_page_is_not_touched(self):
        self.app.update_page.execute("2005", PageChanges(body="<p>y</p>"))
        self.assertEqual(self.gateway.called("update_page")[0][2]["version"]["number"], 2)  # a published page: the current version plus one
        self.gateway.pages["2005"].status = "draft"
        result = self.app.update_page.execute("2005", PageChanges(body="<p>x</p>"))
        sent = self.gateway.called("update_page")[1][2]
        self.assertEqual((sent["status"], sent["version"]["number"]), ("draft", 1))  # a draft is saved as version 1 (Atlassian's rule)
        self.assertEqual(self.app.update_page.execute("2005", PageChanges(body="<p>z</p>"), dry_run=True).version_to, 1)
        self.gateway.pages["2003"].status = "archived"
        with self.assertRaises(ValidationError):
            self.app.update_page.execute("2003", PageChanges(title="T"))

    def test_a_bad_title_and_an_unknown_page(self):
        with self.assertRaises(ValidationError):
            self.app.update_page.execute("2005", PageChanges(title="  "))
        with self.assertRaises(NotFoundError):
            self.app.update_page.execute("999", PageChanges(title="T"))


class MoveTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.app = app_with(self.gateway)

    def test_append_before_and_after(self):
        result = self.app.move_page.execute("2005", "2003")
        self.assertEqual(result.payload, {"pageId": "2005", "position": "append", "targetId": "2003"})
        self.assertEqual(self.gateway.pages["2005"].parent_id, "2003")
        self.app.move_page.execute("2005", "2002", position="before")
        self.assertEqual(self.gateway.pages["2005"].parent_id, "2001")
        self.assertEqual(self.gateway.called("move_page")[-1][1:], ("2005", "before", "2002"))

    def test_a_dry_run_moves_nothing_but_checks_both_pages(self):
        result = self.app.move_page.execute("2005", "2003", dry_run=True)
        self.assertTrue(result.dry_run)
        self.assertEqual((self.gateway.called("move_page"), self.gateway.pages["2005"].parent_id), ([], "2001"))
        with self.assertRaises(NotFoundError):
            self.app.move_page.execute("2005", "999", dry_run=True)

    def test_bad_requests(self):
        with self.assertRaises(ValidationError):
            self.app.move_page.execute("2005", "2005")
        with self.assertRaises(UsageError):
            self.app.move_page.execute("2005", "2003", position="inside")
        with self.assertRaises(NotFoundError):
            self.app.move_page.execute("999", "2003")


class CommentTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.app = app_with(self.gateway)

    def test_a_markdown_comment_is_sent_as_storage_format(self):
        result = self.app.add_comment.execute("2002", "Reviewed, **no** findings.")
        sent = self.gateway.called("add_comment")[0][1]
        self.assertEqual(sent["pageId"], "2002")
        self.assertEqual(sent["body"]["representation"], "storage")
        self.assertIn("<strong>no</strong>", sent["body"]["value"])
        self.assertEqual((result.comment_id, result.dry_run), ("20001", False))

    def test_a_reply_and_storage_format(self):
        self.app.add_comment.execute("2002", "<p>Thanks</p>", body_format="storage", reply_to="4001")
        self.assertEqual(self.gateway.called("add_comment")[0][1], {"pageId": "2002", "body": {"representation": "storage", "value": "<p>Thanks</p>"}, "parentCommentId": "4001"})

    def test_a_dry_run_proves_the_page_and_sends_nothing(self):
        result = self.app.add_comment.execute("2002", "x", dry_run=True)
        self.assertTrue(result.dry_run)
        self.assertEqual(self.gateway.called("add_comment"), [])
        with self.assertRaises(NotFoundError):
            self.app.add_comment.execute("999", "x", dry_run=True)

    def test_bad_input(self):
        for kwargs in ({"body": "  "}, {"body": "x", "reply_to": "abc"}, {"body": "x", "reply_to": "\u00b2"}, {"body": "x", "reply_to": "\u0661\u0662"}):
            with self.assertRaises(ValidationError):
                self.app.add_comment.execute("2002", **kwargs)
        with self.assertRaises(UsageError):
            self.app.add_comment.execute("2002", "x", body_format="rtf")

    def test_storage_read_without_users_cannot_be_written_back(self):
        blanked = '<p><ac:link><ri:user ri:account-id="hidden" /></ac:link></p>'
        with self.assertRaises(ValidationError) as caught:
            self.app.add_comment.execute("2002", blanked, body_format="storage")
        self.assertIn("--with-users", caught.exception.hint)
        self.assertEqual(self.gateway.called("add_comment"), [])
        real = f'<p><ac:link><ri:user ri:account-id="{ACCOUNT}" /></ac:link></p>'
        self.app.add_comment.execute("2002", real, body_format="storage")


class LabelsTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.app = app_with(self.gateway)

    def test_add_and_remove(self):
        result = self.app.change_labels.execute("2002", add=["Reviewed", "adr"], remove=["notes"])
        self.assertEqual((result.added, result.removed), (["reviewed", "adr"], ["notes"]))
        self.assertEqual([label.name for label in result.labels], ["release", "reviewed", "adr"])
        self.assertEqual(self.gateway.called("add_labels")[0][2], [{"prefix": "global", "name": "reviewed"}, {"prefix": "global", "name": "adr"}])

    def test_what_is_there_already_or_not_there_is_skipped(self):
        result = self.app.change_labels.execute("2002", add=["release", "new"], remove=["absent"])
        self.assertEqual((result.added, result.removed), (["new"], []))
        self.assertEqual(self.gateway.called("remove_label"), [])
        again = self.app.change_labels.execute("2002", add=["release"], remove=[])
        self.assertEqual((again.added, self.gateway.called("add_labels")[-1][2]), ([], [{"prefix": "global", "name": "new"}]))

    def test_a_dry_run_changes_nothing(self):
        result = self.app.change_labels.execute("2002", add=["new"], remove=["notes"], dry_run=True)
        self.assertEqual((result.added, result.removed, result.dry_run), (["new"], ["notes"], True))
        self.assertEqual([label.name for label in result.labels], ["release", "notes"])
        self.assertEqual((self.gateway.called("add_labels"), self.gateway.called("remove_label")), ([], []))

    def test_bad_requests(self):
        for kwargs in ({"add": [], "remove": []}, {"add": ["a"], "remove": ["A"]}, {"add": ["two words"], "remove": []}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValidationError):
                    self.app.change_labels.execute("2002", **kwargs)
        with self.assertRaises(NotFoundError):
            self.app.change_labels.execute("999", add=["a"], remove=[])


class UploadTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.files = MemoryFiles({"in/diagram.png": b"NEWPNG", "in/new.txt": b"fresh", "in/sub/x": b"x"})
        self.app = app_with(self.gateway, self.files)

    def test_files_are_uploaded_under_their_own_names(self):
        result = self.app.upload_attachments.execute("2003", ["in/new.txt", "in/diagram.png"], comment="October", minor=True)
        self.assertEqual([(item.name, item.size, item.action) for item in result.uploads], [("new.txt", 5, "uploaded"), ("diagram.png", 6, "uploaded")])
        self.assertEqual(self.gateway.called("upload_attachment")[0][1:], ("2003", "new.txt", b"fresh", "October", True))
        self.assertEqual(self.gateway.attachment_data[result.uploads[0].attachment.id], b"fresh")

    def test_a_file_the_page_has_becomes_a_new_version(self):
        result = self.app.upload_attachments.execute("2002", ["in/diagram.png"])
        self.assertEqual((result.uploads[0].attachment.id, result.uploads[0].attachment.version), ("att5001", 2))

    def test_a_dry_run_sends_nothing(self):
        result = self.app.upload_attachments.execute("2003", ["in/new.txt"], dry_run=True)
        self.assertEqual((result.dry_run, result.uploads[0].action, result.uploads[0].attachment), (True, "would upload", None))
        self.assertEqual(self.gateway.called("upload_attachment"), [])
        with self.assertRaises(NotFoundError):
            self.app.upload_attachments.execute("999", ["in/new.txt"], dry_run=True)

    def test_a_missing_file_or_a_folder_stops_everything_before_any_upload(self):
        for paths in (["in/new.txt", "in/missing.txt"], ["in/sub"], []):
            with self.subTest(paths=paths):
                with self.assertRaises((ValidationError, UsageError)):
                    self.app.upload_attachments.execute("2003", paths)
        self.assertEqual(self.gateway.called("upload_attachment"), [])


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.files = MemoryFiles()
        self.app = app_with(self.gateway, self.files)

    def put(self, name, text):
        self.files.write_text(name, text)
        return name

    def test_a_new_page_takes_its_title_from_the_heading_and_is_created_in_the_space(self):
        path = self.put("docs/new.md", "# Brand new\n\nSome **text**.\n")
        outcome = self.app.import_markdown.execute(path, space="ENG", parent="2003")
        sent = self.gateway.called("create_page")[0][1]
        self.assertEqual((outcome.action, outcome.page_id, outcome.title), ("created", "20001", "Brand new"))
        self.assertEqual((sent["title"], sent["parentId"], sent["spaceId"]), ("Brand new", "2003", "1001"))
        self.assertNotIn("<h1>", sent["body"]["value"])  # the title is not repeated in the body
        self.assertIn("<strong>text</strong>", sent["body"]["value"])

    def test_front_matter_wins_over_the_options_and_labels_are_added(self):
        path = self.put("docs/new.md", "---\ntitle: From front matter\nspace: DOCS\nparent: 3001\nlabels: Alpha, beta\n---\nBody\n")
        outcome = self.app.import_markdown.execute(path, space="ENG", parent="2003")
        sent = self.gateway.called("create_page")[0][1]
        self.assertEqual((sent["spaceId"], sent["parentId"], outcome.title), ("1002", "3001", "From front matter"))
        self.assertEqual([item["name"] for item in self.gateway.called("add_labels")[0][2]], ["alpha", "beta"])

    def test_a_page_with_that_title_is_updated_not_duplicated(self):
        path = self.put("docs/plain.md", "---\ntitle: Plain page\n---\nCompletely new text.\n")
        outcome = self.app.import_markdown.execute(path, space="ENG")
        self.assertEqual((outcome.action, outcome.page_id), ("updated", "2005"))
        self.assertEqual(self.gateway.called("create_page"), [])
        sent = self.gateway.called("update_page")[0][2]
        self.assertEqual(sent["version"], {"number": 2, "message": "Imported from plain.md"})
        self.assertEqual(self.gateway.pages["2005"].body, "<p>Completely new text.</p>")

    def test_a_page_id_in_the_front_matter_updates_that_page_and_may_rename_it(self):
        path = self.put("docs/x.md", "---\npage_id: 2005\ntitle: Renamed by import\nmessage: Synced\n---\nText\n")
        outcome = self.app.import_markdown.execute(path)
        self.assertEqual((outcome.action, outcome.page_id, self.gateway.pages["2005"].title), ("updated", "2005", "Renamed by import"))
        self.assertEqual(self.gateway.called("update_page")[0][2]["version"]["message"], "Synced")

    def test_a_page_that_markdown_cannot_express_is_not_overwritten_without_force(self):
        path = self.put("docs/x.md", "---\npage_id: 2002\n---\nReplacement\n")
        with self.assertRaises(ValidationError) as caught:
            self.app.import_markdown.execute(path)
        self.assertIn("macro:toc", caught.exception.message)
        outcome = self.app.import_markdown.execute(path, force=True)
        self.assertEqual((outcome.action, outcome.lost), ("updated", ("macro:toc", "mention", "redacted-text")))

    def test_the_same_file_twice_changes_nothing_the_second_time(self):
        path = self.put("docs/same.md", "---\ntitle: Plain page\n---\nJust a paragraph & text.\n")
        outcome = self.app.import_markdown.execute(path, space="ENG")
        self.assertEqual(outcome.action, "unchanged")
        self.assertEqual(self.gateway.called("update_page"), [])

    def test_labels_are_added_to_an_updated_page_too(self):
        path = self.put("docs/x.md", "---\npage_id: 2005\nlabels: reviewed\n---\nNew text\n")
        outcome = self.app.import_markdown.execute(path)
        self.assertEqual([label.name for label in self.gateway.pages["2005"].labels], ["reviewed"])
        self.assertEqual(outcome.labels, ("reviewed",))

    def test_a_new_label_alone_makes_the_import_an_update_and_a_dry_run_says_so(self):
        path = self.put("docs/same.md", "---\ntitle: Plain page\nlabels: later\n---\nJust a paragraph & text.\n")
        dry = self.app.import_markdown.execute(path, space="ENG", dry_run=True)
        self.assertEqual((dry.action, dry.labels, dry.payload), ("updated", ("later",), None))
        self.assertEqual(self.gateway.called("add_labels"), [])
        real = self.app.import_markdown.execute(path, space="ENG")
        self.assertEqual((real.action, real.labels), ("updated", ("later",)))
        self.assertEqual([label.name for label in self.gateway.pages["2005"].labels], ["later"])
        again = self.app.import_markdown.execute(path, space="ENG")
        self.assertEqual((again.action, again.labels), ("unchanged", ()))  # now the page is as the file says

    def test_a_bad_label_is_refused_before_the_page_is_changed(self):
        path = self.put("docs/x.md", "---\npage_id: 2005\nlabels: two words\n---\nNew text\n")
        with self.assertRaises(ValidationError):
            self.app.import_markdown.execute(path)
        self.assertEqual(self.gateway.called("update_page"), [])

    def test_labels_that_fail_after_the_update_say_that_the_page_was_updated(self):
        self.gateway.errors["add_labels"] = RejectedError("Confluence refused the label")
        path = self.put("docs/x.md", "---\npage_id: 2005\nlabels: reviewed\n---\nNew text\n")
        with self.assertRaises(RejectedError) as caught:
            self.app.import_markdown.execute(path)
        self.assertIn("The page was updated (id 2005)", caught.exception.message)
        self.assertIn("conflu label 2005 --add", caught.exception.hint)
        self.assertEqual(self.gateway.pages["2005"].body, "<p>New text</p>")

    def test_a_dry_run_writes_nothing(self):
        path = self.put("docs/new.md", "# Brand new\n\nText\n")
        created = self.app.import_markdown.execute(path, space="ENG", dry_run=True)
        updated = self.app.import_markdown.execute(self.put("docs/plain.md", "---\ntitle: Plain page\n---\nOther\n"), space="ENG", dry_run=True)
        self.assertEqual((created.action, created.dry_run, updated.action), ("created", True, "updated"))
        self.assertIsNotNone(created.payload)
        for name in ("create_page", "update_page", "add_labels"):
            self.assertEqual(self.gateway.called(name), [], name)

    def test_what_is_missing_is_explained(self):
        for text, expected in (("No title here\n", "no title"), ("# Title\nText\n", "no space")):
            with self.subTest(expected=expected):
                with self.assertRaises(ValidationError) as caught:
                    self.app.import_markdown.execute(self.put("docs/bad.md", text))
                self.assertIn(expected, caught.exception.message)
        with self.assertRaises(ValidationError):
            self.app.import_markdown.execute("docs/absent.md")
        with self.assertRaises(ValidationError):
            self.app.import_markdown.execute(self.put("docs/broken.md", "---\ntitle: T\nno end"))

    def test_the_current_space_is_the_last_default(self):
        app = app_with(self.gateway, self.files, space="DOCS")
        outcome = app.import_markdown.execute(self.put("docs/new.md", "# New in docs\n"))
        self.assertEqual(self.gateway.called("create_page")[0][1]["spaceId"], "1002")
        self.assertEqual(outcome.action, "created")


class ImportDirectoryTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.files = MemoryFiles(
            {
                "docs/a.md": "# Alpha\n\nText\n",
                "docs/b.md": "No title at all\n",
                "docs/c.md": "# Gamma\n\nText\n",
                "docs/notes.txt": "ignored",
                "docs/sub/d.md": "# Nested\n",
            }
        )
        self.app = app_with(self.gateway, self.files)

    def test_files_are_imported_in_name_order_until_the_first_failure(self):
        batch = self.app.import_markdown_directory.execute("docs", space="ENG")
        self.assertEqual([(item.file, item.action) for item in batch.outcomes], [("docs/a.md", "created"), ("docs/b.md", "failed")])
        self.assertIn("no title", batch.first_error.message)
        self.assertEqual(batch.count("created"), 1)

    def test_with_continue_on_error_the_rest_is_imported_and_the_first_error_is_kept(self):
        batch = self.app.import_markdown_directory.execute("docs", space="ENG", continue_on_error=True)
        self.assertEqual([item.action for item in batch.outcomes], ["created", "failed", "created"])
        self.assertEqual((batch.count("failed"), batch.first_error.exit_code), (1, 1))
        self.assertEqual([call[1]["title"] for call in self.gateway.called("create_page")], ["Alpha", "Gamma"])

    def test_a_dry_run_changes_nothing(self):
        batch = self.app.import_markdown_directory.execute("docs", space="ENG", dry_run=True, continue_on_error=True)
        self.assertTrue(all(item.dry_run for item in batch.outcomes))
        self.assertEqual(self.gateway.called("create_page"), [])

    def test_a_folder_must_exist_and_hold_markdown(self):
        with self.assertRaises(ValidationError):
            self.app.import_markdown_directory.execute("nowhere")
        self.files.write_text("empty/readme.txt", "x")
        with self.assertRaises(ValidationError):
            self.app.import_markdown_directory.execute("empty")


if __name__ == "__main__":
    unittest.main()
