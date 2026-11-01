"""The use cases of attachments against the in-memory Confluence: the list, one attachment with its versions, saving, reading as text and attaching."""
import base64
import dataclasses
import unittest
from unittest import mock

from conflu_c_cli.application import attachments as attachments_module
from conflu_c_cli.domain.errors import AuthError, ConflictError, NotFoundError, RejectedError, UnavailableError, UsageError, ValidationError
from conflu_c_cli.domain.model import VersionInfo
from tests.support.attachment_data import AGENDA, PLAN, Edition, Fixture
from tests.support.fakes import ACCOUNT, FakeGateway, MemoryConfigStore, MemoryFiles, RecordingDiagnostics, build_app, default_settings
from tests.support.places_attachments import PlacedFiles

CONFIG = "/home/me/.config/conflu-c-cli/config"


class Case(unittest.TestCase):
    """An application over a fake Confluence: page 2004 holds att5101 to att5106, blog post 7102 holds att5111 and att5112."""

    files_class = MemoryFiles

    def setUp(self):
        self.gateway = FakeGateway()
        self.gateway.page_cap = 100
        self.diagnostics = RecordingDiagnostics()
        self.build()

    def build(self, files=None, store=None, **settings):
        self.files = files or MemoryFiles()
        self.app = build_app(gateway=self.gateway, files=self.files, store=store, settings=default_settings(**settings), diagnostics=self.diagnostics)
        self.use = self.app.attachments

    def add(self, identifier, holder, name, data=b"text", media_type="text/plain", *editions, comment=""):
        fixture = Fixture(identifier, holder, name, media_type, editions or (Edition(data, "", False, "2026-10-20T09:00:00.000Z"),), (), comment)
        return self.gateway.add_attachment_fixture(fixture)

    def names(self, calls):
        return [call[0] for call in calls]


class ListTest(Case):
    def test_a_page_is_asked_once_and_nothing_else(self):
        result = self.use.list_attachments.execute("2004")
        self.assertEqual([item.id for item in result.attachments], ["att5101", "att5102", "att5103", "att5104", "att5105", "att5106"])
        self.assertEqual((result.page_id, result.blog_post_id, result.next_cursor), ("2004", "", ""))
        self.assertEqual(self.names(self.gateway.calls), ["list_attachments"])

    def test_the_address_of_a_page_will_do(self):
        result = self.use.list_attachments.execute("https://example.atlassian.net/wiki/spaces/ENG/pages/2004/ADR+0001")
        self.assertEqual(result.page_id, "2004")

    def test_a_blog_post_is_found_when_the_page_is_not(self):
        result = self.use.list_attachments.execute("7102")
        self.assertEqual([item.id for item in result.attachments], ["att5111", "att5112"])
        self.assertEqual((result.page_id, result.blog_post_id), ("", "7102"))
        self.assertEqual(self.names(self.gateway.calls), ["list_attachments", "content_types", "list_blogpost_attachments"])
        self.assertEqual({item.blog_post_id for item in result.attachments}, {"7102"})

    def test_the_address_of_a_blog_post_will_do(self):
        result = self.use.list_attachments.execute("https://example.atlassian.net/wiki/spaces/ENG/blog/2026/10/12/7102/Weekly+update")
        self.assertEqual(result.blog_post_id, "7102")

    def test_a_blog_post_is_pageable_and_asks_what_the_id_is_once(self):
        self.gateway.page_cap = 1
        first = self.use.list_attachments.execute("7102", limit=1)
        self.assertEqual(([item.id for item in first.attachments], first.next_cursor), (["att5111"], "1"))
        self.gateway.calls.clear()
        everything = self.use.list_attachments.execute("7102", fetch_everything=True)
        self.assertEqual([item.id for item in everything.attachments], ["att5111", "att5112"])
        self.assertEqual(self.names(self.gateway.calls), ["list_attachments", "content_types", "list_blogpost_attachments", "list_blogpost_attachments"])

    def test_a_name_filter_works_for_a_blog_post_too(self):
        result = self.use.list_attachments.execute("7102", name="minutes.md")
        self.assertEqual([item.id for item in result.attachments], ["att5112"])

    def test_an_id_that_is_neither_says_what_it_is(self):
        self.gateway.content_kinds["7001"] = "folder"
        with self.assertRaises(NotFoundError) as caught:
            self.use.list_attachments.execute("7001")
        self.assertEqual(caught.exception.exit_code, 4)
        self.assertIn("a folder", caught.exception.hint)
        self.assertIn("conflu folder 7001", caught.exception.hint)

    def test_an_id_that_is_nothing_keeps_the_first_answer(self):
        with self.assertRaises(NotFoundError) as caught:
            self.use.list_attachments.execute("999")
        self.assertIn("pages/999", caught.exception.message)
        self.assertNotIn("is a", caught.exception.hint)

    def test_when_the_type_cannot_be_asked_the_first_answer_stands(self):
        self.gateway.errors["content_types"] = UnavailableError("down")
        with self.assertRaises(NotFoundError):
            self.use.list_attachments.execute("7102")

    def test_an_attachment_is_no_page(self):
        with self.assertRaises(ValidationError) as caught:
            self.use.list_attachments.execute("att5101")
        self.assertIn("conflu attachment att5101", caught.exception.hint)
        self.assertEqual(self.gateway.calls, [])

    def test_names_and_comments_are_redacted_unless_people_are_shown(self):
        self.add("att5301", "2004", "alex@example.com notes.txt", b"x", "text/plain", comment="from alex@example.com")
        shown = {item.id: item for item in self.use.list_attachments.execute("2004").attachments}
        self.assertEqual((shown["att5301"].title, shown["att5301"].comment), ("[email] notes.txt", "from [email]"))
        self.assertEqual(shown["att5301"].download_link, "/download/attachments/2004?version=1&api=v2")  # the address ends in the name: it ends at the id instead
        self.assertEqual(shown["att5101"].download_link, "/download/attachments/2004/plan.txt?version=3&api=v2")  # a name without an address leaves it as it is
        raw = {item.id: item for item in self.use.list_attachments.execute("2004", with_users=True).attachments}
        self.assertEqual((raw["att5301"].title, raw["att5301"].comment), ("alex@example.com notes.txt", "from alex@example.com"))
        self.assertEqual(raw["att5301"].download_link, "/download/attachments/2004/alex@example.com notes.txt?version=1&api=v2")
        self.assertEqual(self.gateway.attachments["2004"][-1].title, "alex@example.com notes.txt")  # what is stored is not touched

    def test_the_type_is_text_that_the_uploader_chose_and_is_redacted_too(self):
        self.add("att5302", "2004", "odd.bin", b"x", "application/x.alex@example.com")
        self.assertEqual({item.id: item.media_type for item in self.use.list_attachments.execute("2004").attachments}["att5302"], "application/[email]")  # the address takes its prefix with it
        self.assertEqual({item.id: item.media_type for item in self.use.list_attachments.execute("2004", with_users=True).attachments}["att5302"], "application/x.alex@example.com")

    def test_the_files_that_a_page_names_have_their_type_redacted_too(self):
        self.add("att5302", "2004", "odd.bin", b"x", "application/x-alex@example.com")
        hidden = {item.id: item.media_type for item in self.app.view_page.execute("2004", with_attachments=True).attachments}
        self.assertEqual((hidden["att5302"], hidden["att5101"]), ("application/[email]", "text/plain"))
        shown = {item.id: item.media_type for item in self.app.view_page.execute("2004", with_attachments=True, with_users=True).attachments}
        self.assertEqual(shown["att5302"], "application/x-alex@example.com")

    def test_people_are_refused_under_the_policy(self):
        self.build(hide_users=True)
        with self.assertRaises(ValidationError) as caught:
            self.use.list_attachments.execute("2004", with_users=True)
        self.assertIn("CONFLUENCE_HIDE_USERS", caught.exception.message)

    def test_the_old_field_of_the_application_still_lists(self):
        self.assertEqual([item.id for item in self.app.list_attachments.execute("2002").attachments], ["att5001", "att5002"])


class ShowTest(Case):
    def test_the_properties_of_one_attachment(self):
        view = self.use.show.execute("att5101")
        item = view.attachment
        self.assertEqual((item.id, item.title, item.version, item.page_id, item.comment), ("att5101", "plan.txt", 3, "2004", "The plan for the October release"))
        self.assertEqual((view.versions, view.labels, view.users_shown), (None, None, False))
        self.assertEqual(self.names(self.gateway.calls), ["get_attachment"])

    def test_an_attachment_of_a_blog_post_says_so(self):
        item = self.use.show.execute("att5111").attachment
        self.assertEqual((item.page_id, item.blog_post_id), ("", "7102"))

    def test_it_must_be_an_attachment_id(self):
        for text in ("2004", "plan.txt", "", "att"):
            with self.subTest(text=text):
                with self.assertRaises(ValidationError) as caught:
                    self.use.show.execute(text)
                self.assertIn("att123456", caught.exception.hint)
        self.assertEqual(self.gateway.calls, [])

    def test_an_unknown_attachment_is_not_found(self):
        with self.assertRaises(NotFoundError):
            self.use.show.execute("att999")

    def test_the_versions_come_newest_first_with_the_size_of_each(self):
        view = self.use.show.execute("att5101", versions=True)
        self.assertEqual([(row.version.number, row.version.message, row.size) for row in view.versions], [(3, "", len(PLAN[2].data)), (2, "Added the contact", len(PLAN[1].data)), (1, "First draft", len(PLAN[0].data))])
        self.assertEqual(self.names(self.gateway.calls).count("get_attachment_version"), 2)  # the size of the newest is the one that the attachment says
        self.assertEqual((view.next_cursor, view.sizes_left_out), ("", 0))

    def test_the_versions_are_paged_with_a_cursor_or_all_at_once(self):
        self.gateway.page_cap = 2
        first = self.use.show.execute("att5101", versions=True, limit=2)
        self.assertEqual(([row.version.number for row in first.versions], first.next_cursor), ([3, 2], "2"))
        second = self.use.show.execute("att5101", versions=True, limit=2, cursor="2")
        self.assertEqual(([row.version.number for row in second.versions], second.next_cursor), ([1], ""))
        everything = self.use.show.execute("att5101", versions=True, fetch_everything=True)
        self.assertEqual([row.version.number for row in everything.versions], [3, 2, 1])

    def test_the_size_of_a_version_that_cannot_be_read_is_not_known(self):
        del self.gateway.attachment_version_data[("att5101", 2)]
        view = self.use.show.execute("att5101", versions=True)
        self.assertEqual([(row.version.number, row.size is None) for row in view.versions], [(3, False), (2, True), (1, False)])

    def test_the_size_is_asked_for_a_limited_number_of_versions_and_the_rest_is_said(self):
        editions = [Edition(f"version {number}".encode(), "", False, f"2026-10-20T09:{number % 60:02d}:00.000Z") for number in range(1, 61)]
        self.add("att5400", "2004", "long.txt", b"", "text/plain", *editions)
        self.gateway.calls.clear()
        view = self.use.show.execute("att5400", versions=True, fetch_everything=True)
        self.assertEqual(len(view.versions), 60)
        self.assertEqual(self.names(self.gateway.calls).count("get_attachment_version"), attachments_module.SIZE_LOOKUPS)
        self.assertEqual(view.sizes_left_out, 60 - 1 - attachments_module.SIZE_LOOKUPS)  # the newest costs nothing
        self.assertEqual(sum(row.size is None for row in view.versions), view.sizes_left_out)

    def test_who_saved_a_version_is_left_out_unless_people_are_shown(self):
        hidden = self.use.show.execute("att5101", versions=True)
        self.assertEqual({row.version.author for row in hidden.versions}, {None})
        self.assertNotIn("lookup_users", self.names(self.gateway.calls))
        shown = self.use.show.execute("att5101", versions=True, with_users=True)
        self.assertEqual({row.version.author.account_id for row in shown.versions}, {ACCOUNT})
        self.assertEqual({row.version.author.display_name for row in shown.versions}, {"Alex Example"})
        self.assertEqual(self.names(self.gateway.calls).count("lookup_users"), 1)
        self.assertTrue(shown.users_shown)

    def test_a_message_is_redacted_unless_people_are_shown(self):
        self.gateway.attachment_versions["att5101"][1] = VersionInfo(2, "2026-10-07T09:30:00.000Z", "Sent to alex@example.com", False)
        hidden = self.use.show.execute("att5101", versions=True)
        self.assertEqual([row.version.message for row in hidden.versions if row.version.number == 2], ["Sent to [email]"])
        shown = self.use.show.execute("att5101", versions=True, with_users=True)
        self.assertEqual([row.version.message for row in shown.versions if row.version.number == 2], ["Sent to alex@example.com"])

    def test_the_labels(self):
        view = self.use.show.execute("att5101", labels=True)
        self.assertEqual([label.name for label in view.labels], ["draft", "plan"])
        self.assertIsNone(view.versions)
        self.assertEqual(self.use.show.execute("att5111", labels=True).labels, [])

    def test_the_labels_are_read_in_full_whatever_the_page_size(self):
        self.gateway.page_cap = 1
        self.assertEqual([label.name for label in self.use.show.execute("att5101", labels=True).labels], ["draft", "plan"])

    def test_the_name_and_the_comment_are_redacted_unless_people_are_shown(self):
        self.add("att5301", "2004", "alex@example.com.txt", comment="by alex@example.com")
        hidden = self.use.show.execute("att5301").attachment
        self.assertEqual((hidden.title, hidden.comment), ("[email]", "by [email]"))  # the address takes the rest of the name with it
        self.assertEqual(hidden.download_link, "/download/attachments/2004?version=1&api=v2")  # the address of the file ends in its name
        shown = self.use.show.execute("att5301", with_users=True).attachment
        self.assertEqual((shown.title, shown.download_link), ("alex@example.com.txt", "/download/attachments/2004/alex@example.com.txt?version=1&api=v2"))

    def test_people_are_refused_under_the_policy(self):
        self.build(hide_users=True)
        with self.assertRaises(ValidationError):
            self.use.show.execute("att5101", versions=True, with_users=True)
        self.assertEqual(self.gateway.calls, [])


class DownloadTest(Case):
    def test_one_attachment_by_its_id_and_the_old_field_does_the_same(self):
        done = self.use.download.execute("att5101", out_dir="out")
        self.assertEqual([(item.path, item.size, item.action, item.attachment.version) for item in done], [("out/plan.txt", len(PLAN[2].data), "downloaded", 3)])
        self.assertEqual(self.files.files["out/plan.txt"], PLAN[2].data)
        again = self.app.download_attachments.execute("att5001", out_dir="old")
        self.assertEqual([item.path for item in again], ["old/diagram.png"])

    def test_the_newest_file_of_a_page_is_the_one_call_that_the_download_always_made(self):
        self.use.download.execute("att5101", out_dir="out")
        self.assertEqual(self.names(self.gateway.calls), ["get_attachment", "download_attachment"])

    def test_a_version_of_one_attachment(self):
        done = self.use.download.execute("att5101", out_dir="out", version=2)
        self.assertEqual(self.files.files["out/plan.txt"], PLAN[1].data)
        self.assertEqual((done[0].size, done[0].attachment.version), (len(PLAN[1].data), 2))
        self.assertIn(("fetch_attachment", "att5101", 2), self.gateway.calls)

    def test_a_version_by_name_from_a_page_and_from_a_blog_post(self):
        self.use.download.execute("2004", names=["plan.txt"], out_dir="page", version=1)
        self.assertEqual(self.files.files["page/plan.txt"], PLAN[0].data)
        self.use.download.execute("7102", names=["agenda.txt"], out_dir="blog", version=1)
        self.assertEqual(self.files.files["blog/agenda.txt"], AGENDA[0].data)

    def test_the_newest_version_may_be_named_too(self):
        self.use.download.execute("att5101", out_dir="out", version=3)
        self.assertEqual(self.files.files["out/plan.txt"], PLAN[2].data)

    def test_a_version_that_does_not_exist_is_not_found_and_says_where_to_look(self):
        for number in (4, 99):
            with self.subTest(version=number):
                with self.assertRaises(NotFoundError) as caught:
                    self.use.download.execute("att5101", out_dir="out", version=number)
                self.assertEqual(caught.exception.exit_code, 4)
                self.assertIn("has no version", caught.exception.message)
                self.assertIn("conflu attachment att5101 --versions", caught.exception.hint)
        self.assertEqual(self.files.files, {})
        self.assertNotIn("get_attachment_version", self.names(self.gateway.calls))  # a number past the newest costs no request

    def test_a_version_that_the_list_names_and_cannot_be_read_is_not_found_too(self):
        del self.gateway.attachment_version_data[("att5101", 2)]
        with self.assertRaises(NotFoundError) as caught:
            self.use.download.execute("att5101", out_dir="out", version=2)
        self.assertEqual(caught.exception.details["version"], 2)

    def test_a_version_needs_exactly_one_attachment(self):
        for choice in ({"everything": True}, {"names": ["plan.txt", "spec.docx"]}):
            with self.subTest(choice=choice):
                with self.assertRaises(UsageError) as caught:
                    self.use.download.execute("2004", out_dir="out", version=2, **choice)
                self.assertIn("exactly one", caught.exception.message)
        with self.assertRaises(UsageError):
            self.use.download.execute("att5101", out_dir="out", version=-1)
        self.assertEqual(self.gateway.calls, [])

    def test_an_attachment_id_and_a_choice_among_the_attachments_of_a_page_exclude_each_other(self):
        for choice in ({"everything": True}, {"names": ["plan.txt"]}):
            with self.subTest(choice=choice):
                with self.assertRaises(UsageError):
                    self.use.download.execute("att5101", out_dir="out", **choice)
        self.assertEqual(self.files.files, {})

    def test_the_files_of_a_blog_post_by_name_and_all_of_them(self):
        done = self.use.download.execute("7102", names=["minutes.md"], out_dir="blog")
        self.assertEqual([item.path for item in done], ["blog/minutes.md"])
        self.assertEqual(self.files.files["blog/minutes.md"], b"# Minutes\n\nDecisions were made.\n")
        done = self.use.download.execute("7102", everything=True, out_dir="all")
        self.assertEqual(sorted(item.path for item in done), ["all/agenda.txt", "all/minutes.md"])
        self.assertEqual(self.files.files["all/agenda.txt"], AGENDA[1].data)
        self.assertEqual(self.gateway.called("fetch_attachment")[0][1:], ("att5112", 0))
        self.assertIn(("fetch_attachment", "att5111", 0), self.gateway.calls)

    def test_a_blog_post_without_attachments_or_a_name_that_is_not_there(self):
        self.gateway.attachments["7102"] = []
        with self.assertRaises(NotFoundError) as caught:
            self.use.download.execute("7102", everything=True)
        self.assertIn("Blog post 7102 has no attachments", caught.exception.message)
        with self.assertRaises(NotFoundError) as caught:
            self.use.download.execute("2004", names=["missing.txt"])
        self.assertIn("Page 2004 has no attachment named missing.txt", caught.exception.message)

    def test_the_id_of_a_folder_is_no_holder_of_files(self):
        self.gateway.content_kinds["7001"] = "folder"
        with self.assertRaises(NotFoundError) as caught:
            self.use.download.execute("7001", everything=True)
        self.assertIn("a folder", caught.exception.hint)

    def test_a_dry_run_asks_for_no_file_and_writes_nothing(self):
        done = self.use.download.execute("2004", everything=True, out_dir="out", dry_run=True)
        self.assertEqual({item.action for item in done}, {"would download"})
        self.assertEqual(self.files.files, {})
        self.assertEqual(self.gateway.called("download_attachment") + self.gateway.called("fetch_attachment"), [])

    def test_a_file_over_the_limit_is_refused_by_its_size_before_anything_is_fetched(self):
        with self.assertRaises(ValidationError) as caught:
            self.use.download.execute("2004", everything=True, out_dir="out", max_bytes=100)
        self.assertIn("spec.docx", caught.exception.message)
        self.assertIn("--max-bytes 100", caught.exception.message)
        self.assertIn("budget.xlsx", caught.exception.message)
        self.assertNotIn("plan.txt", caught.exception.message)  # 59 bytes is within the limit
        self.assertEqual(sorted(entry["attachmentId"] for entry in caught.exception.details["attachments"]), ["att5102", "att5103", "att5104"])
        self.assertEqual((self.files.files, self.gateway.called("download_attachment")), ({}, []))

    def test_a_dry_run_is_refused_for_the_same_reason(self):
        with self.assertRaises(ValidationError):
            self.use.download.execute("att5102", out_dir="out", max_bytes=100, dry_run=True)

    def test_the_size_of_the_version_is_the_size_that_counts(self):
        self.use.download.execute("att5101", out_dir="out", max_bytes=len(PLAN[0].data), version=1)  # version 1 is small
        with self.assertRaises(ValidationError):
            self.use.download.execute("att5101", out_dir="two", max_bytes=len(PLAN[0].data))  # the newest is not
        self.assertEqual(sorted(self.files.files), ["out/plan.txt"])

    def test_the_limit_must_be_a_positive_number(self):
        with self.assertRaises(UsageError):
            self.use.download.execute("att5101", out_dir="out", max_bytes=-5)

    def test_a_size_that_the_metadata_understates_is_found_out_after_the_download(self):
        self.gateway.attachments["2004"][0] = dataclasses.replace(self.gateway.attachments["2004"][0], size=0)
        with self.assertRaises(ValidationError) as caught:
            self.use.download.execute("att5101", out_dir="out", max_bytes=10)
        self.assertIn("nothing was written", caught.exception.message)
        self.assertEqual(self.files.files, {})

    def test_an_incomplete_download_is_not_written(self):
        self.gateway.attachment_data["att5101"] = b"short"
        with self.assertRaises(UnavailableError) as caught:
            self.use.download.execute("att5101", out_dir="out")
        self.assertIn("arrived incomplete", caught.exception.message)
        self.assertEqual(self.files.files, {})

    def test_a_file_that_is_there_is_never_replaced_without_force(self):
        self.files.files["out/plan.txt"] = b"mine"
        with self.assertRaises(ValidationError) as caught:
            self.use.download.execute("att5101", out_dir="out")
        self.assertIn("--force", caught.exception.hint)
        self.assertEqual(self.files.files["out/plan.txt"], b"mine")
        self.use.download.execute("att5101", out_dir="out", force=True)
        self.assertEqual(self.files.files["out/plan.txt"], PLAN[2].data)

    def test_a_file_that_appears_while_the_download_runs_is_left_as_it_is(self):
        files = self.files

        class Racing(FakeGateway):
            def download_attachment(self, attachment):
                files.files["out/plan.txt"] = b"somebody else was faster"
                return super().download_attachment(attachment)

        self.gateway = Racing()
        self.build(files=files)
        with self.assertRaises(ValidationError) as caught:
            self.use.download.execute("att5101", out_dir="out")
        self.assertIn("appeared in out while the download ran", caught.exception.message)
        self.assertEqual(files.files["out/plan.txt"], b"somebody else was faster")
        self.assertEqual(files.writes, [])

    def test_a_run_that_fails_after_it_wrote_says_what_was_written(self):
        class Failing(FakeGateway):
            def download_attachment(self, attachment):
                if attachment.id == "att5103":
                    raise UnavailableError("Confluence answered with a server error (HTTP 503).", hint="Try again in a moment.", details={"status": 503})
                return super().download_attachment(attachment)

        self.gateway = Failing()
        self.gateway.page_cap = 100
        self.build()
        with self.assertRaises(UnavailableError) as caught:
            self.use.download.execute("2004", everything=True, out_dir="out")
        error = caught.exception
        self.assertEqual(sorted(self.files.files), ["out/plan.txt", "out/spec.docx"])
        self.assertIn("2 of the 6 files were written to out before that: plan.txt, spec.docx", error.message)
        self.assertIn("--force", error.hint)
        self.assertEqual([entry["attachmentId"] for entry in error.details["written"]], ["att5101", "att5102"])
        self.assertEqual((error.details["failed"], error.details["status"]), ({"attachmentId": "att5103"}, 503))

    def test_a_first_failure_is_the_error_as_it_is(self):
        self.gateway.errors["download_attachment"] = UnavailableError("down", hint="later")
        with self.assertRaises(UnavailableError) as caught:
            self.use.download.execute("att5101", out_dir="out")
        self.assertEqual((caught.exception.message, caught.exception.hint), ("down", "later"))

    def test_a_write_that_fails_on_a_path_that_long_says_why(self):
        class Refusing(MemoryFiles):
            def write_bytes(self, path, data):
                raise ValidationError(f"Cannot write {path}: No such file or directory", details={"path": path})

        self.build(files=Refusing())
        long_folder = "f" * 240
        with self.assertRaises(ValidationError) as caught:
            self.use.download.execute("att5101", out_dir=long_folder)
        self.assertIn("260", caught.exception.hint)
        self.assertIn("--out", caught.exception.hint)
        self.assertEqual(caught.exception.details["path"], f"{long_folder}/plan.txt")
        with self.assertRaises(ValidationError) as short:
            self.use.download.execute("att5101", out_dir="out")
        self.assertEqual(short.exception.hint, "")  # a short path is not the reason

    def test_an_out_that_is_a_file_or_a_name_that_is_a_folder_is_refused_whatever_force_says(self):
        self.files.files["out"] = b"a file"
        with self.assertRaises(ValidationError) as caught:
            self.use.download.execute("att5101", out_dir="out", force=True)
        self.assertIn("is a file, not a folder", caught.exception.message)
        self.files.files.clear()
        self.files.files["out/plan.txt/inside"] = b"x"  # plan.txt is a folder here
        with self.assertRaises(ValidationError) as caught:
            self.use.download.execute("att5101", out_dir="out", force=True)
        self.assertIn("plan.txt is a folder", caught.exception.message)
        self.assertEqual(list(self.files.files), ["out/plan.txt/inside"])

    def test_the_names_that_attachments_have_are_made_safe_and_two_that_clash_are_refused(self):
        self.gateway.attachments["2004"][0] = dataclasses.replace(self.gateway.attachments["2004"][0], title="../../evil:name.txt")
        done = self.use.download.execute("att5101", out_dir="out")
        self.assertEqual(done[0].path, "out/evil_name.txt")
        first = self.gateway.attachments["2004"]
        self.gateway.attachments["2004"] = [dataclasses.replace(first[0], id="att5410", title="a:b.txt"), dataclasses.replace(first[0], id="att5411", title="a_b.txt")]
        with self.assertRaises(ValidationError) as caught:
            self.use.download.execute("2004", everything=True, out_dir="two")
        self.assertEqual(caught.exception.details["attachments"], ["att5410", "att5411"])

    def test_the_same_attachment_asked_for_twice_is_downloaded_once(self):
        done = self.use.download.execute("2004", names=["plan.txt", "plan.txt"], out_dir="out")
        self.assertEqual(len(done), 1)

    def test_people_are_refused_under_the_policy_also_here(self):
        self.build(hide_users=True)
        with self.assertRaises(ValidationError):
            self.use.download.execute("att5101", out_dir="out", with_users=True)
        self.assertEqual(self.gateway.calls, [])


class RedactedNamesTest(Case):
    """What Confluence says a file is called is data that somebody typed, and it can be an e-mail address: the name is printed, and the file is saved,
    redacted unless people are shown. The attachment is still looked for by its real name and its id."""

    ADDRESS = "alex@example.com"

    def setUp(self):
        super().setUp()
        self.add("att5301", "2004", "alex@example.com-cv.txt", b"cv data", "text/plain")

    def change(self, attachment_id, **fields):
        items = self.gateway.attachments["2004"]
        position = next(index for index, item in enumerate(items) if item.id == attachment_id)
        items[position] = dataclasses.replace(items[position], **fields)

    def said(self, error):
        return f"{error.message} {error.hint}"

    def test_the_name_and_the_path_are_redacted_and_the_file_is_saved_under_the_name_that_is_printed(self):
        done = self.use.download.execute("att5301", out_dir="out")
        self.assertEqual([(item.attachment.title, item.path, item.action) for item in done], [("[email]", "out/[email]", "downloaded")])
        self.assertEqual(self.files.files, {"out/[email]": b"cv data"})
        planned = self.use.download.execute("att5301", out_dir="elsewhere", dry_run=True)
        self.assertEqual([(item.attachment.title, item.path, item.action) for item in planned], [("[email]", "elsewhere/[email]", "would download")])
        self.assertEqual(sorted(self.files.files), ["out/[email]"])

    def test_with_people_the_file_has_its_own_name(self):
        done = self.use.download.execute("att5301", out_dir="out", with_users=True)
        self.assertEqual([(item.attachment.title, item.path) for item in done], [("alex@example.com-cv.txt", "out/alex@example.com-cv.txt")])
        self.assertEqual(self.files.files, {"out/alex@example.com-cv.txt": b"cv data"})

    def test_the_file_is_asked_for_by_its_id_whatever_it_is_called_here(self):
        self.use.download.execute("att5301", out_dir="out")
        self.assertEqual(self.gateway.called("download_attachment"), [("download_attachment", "att5301")])

    def test_a_name_is_looked_for_by_what_it_really_is_and_a_redacted_one_says_how_to_choose_instead(self):
        done = self.use.download.execute("2004", names=["alex@example.com-cv.txt"], out_dir="out")
        self.assertEqual(done[0].path, "out/[email]")
        with self.assertRaises(NotFoundError) as caught:
            self.use.download.execute("2004", names=["[email]"], out_dir="more")
        self.assertIn("by its id", caught.exception.hint)
        with self.assertRaises(NotFoundError) as plain:
            self.use.download.execute("2004", names=["nothing.txt"], out_dir="more")
        self.assertEqual(plain.exception.hint, "`conflu attachments PAGE` lists the names.")

    def test_no_message_that_names_the_file_repeats_the_address(self):
        refusals = {
            "larger than its size allows": (ValidationError, lambda **more: self.use.download.execute("att5301", out_dir="o", max_bytes=3, **more)),
            "no such version": (NotFoundError, lambda **more: self.use.download.execute("att5301", out_dir="o", version=9, **more)),
            "text is larger than its size allows": (ValidationError, lambda **more: self.use.read_text.execute("att5301", max_bytes=3, **more)),
            "text of no such version": (NotFoundError, lambda **more: self.use.read_text.execute("att5301", version=9, **more)),
        }
        for what, (kind, run) in refusals.items():
            with self.subTest(what=what):
                with self.assertRaises(kind) as hidden:
                    run()
                self.assertIn("[email]", hidden.exception.message)
                self.assertNotIn("alex", self.said(hidden.exception).lower())
                with self.assertRaises(kind) as shown:
                    run(with_users=True)
                self.assertIn(self.ADDRESS, shown.exception.message)
        self.change("att5301", size=0)  # what Confluence says of the size is a claim: these are found out when the file is there
        with self.assertRaises(ValidationError) as late:
            self.use.download.execute("att5301", out_dir="o", max_bytes=3)
        self.assertIn("[email] is 7 B, more than --max-bytes 3", late.exception.message)
        self.assertNotIn("alex", self.said(late.exception).lower())
        self.change("att5301", size=99)
        with self.assertRaises(UnavailableError) as incomplete:
            self.use.download.execute("att5301", out_dir="o")
        self.assertIn("[email] arrived incomplete (7 of 99 bytes)", incomplete.exception.message)
        self.assertNotIn("alex", self.said(incomplete.exception).lower())
        self.assertEqual(self.files.files, {})

    def test_the_reason_is_not_the_name_either_when_a_text_is_larger_than_it_was_said_to_be(self):
        self.change("att5301", size=1)
        self.gateway.attachment_data["att5301"] = b"x" * 500
        with self.assertRaises(ValidationError) as caught:
            self.use.read_text.execute("att5301", max_bytes=100)
        self.assertIn("[email] arrived with 500 B, more than --max-bytes 100 (100 B)", caught.exception.message)
        self.assertNotIn("alex", self.said(caught.exception).lower())

    def test_two_names_that_become_one_when_they_are_redacted_are_refused_and_the_hint_says_what_helps(self):
        self.add("att5302", "2004", "bob@example.com-cv.txt", b"other cv", "text/plain")
        with self.assertRaises(ValidationError) as caught:
            self.use.download.execute("2004", names=["alex@example.com-cv.txt", "bob@example.com-cv.txt"], out_dir="out")
        error = caught.exception
        self.assertIn("[email] and [email] would be saved as the same file ([email]); nothing was downloaded.", error.message)
        self.assertIn("by id", error.hint)
        self.assertIn("--with-users", error.hint)
        self.assertNotIn("example.com", self.said(error))
        self.assertEqual((error.details["attachments"], error.details["file"]), (["att5301", "att5302"], "[email]"))
        self.assertEqual(self.files.files, {})
        done = self.use.download.execute("2004", names=["alex@example.com-cv.txt", "bob@example.com-cv.txt"], out_dir="own", with_users=True)
        self.assertEqual([item.path for item in done], ["own/alex@example.com-cv.txt", "own/bob@example.com-cv.txt"])

    def test_under_the_policy_the_hint_does_not_offer_what_is_refused(self):
        self.build(hide_users=True)
        self.add("att5302", "2004", "bob@example.com-cv.txt", b"other cv", "text/plain")
        with self.assertRaises(ValidationError) as caught:
            self.use.download.execute("2004", names=["alex@example.com-cv.txt", "bob@example.com-cv.txt"], out_dir="out")
        self.assertIn("by id", caught.exception.hint)
        self.assertNotIn("--with-users", caught.exception.hint)

    def test_two_names_that_clash_for_another_reason_keep_the_old_hint(self):
        first = self.gateway.attachments["2004"]
        self.gateway.attachments["2004"] = [dataclasses.replace(first[0], id="att5410", title="a:b.txt"), dataclasses.replace(first[0], id="att5411", title="a_b.txt")]
        with self.assertRaises(ValidationError) as caught:
            self.use.download.execute("2004", everything=True, out_dir="two")
        self.assertEqual(caught.exception.hint, "Download them one at a time with --name, each into its own --out folder.")

    def test_a_run_that_stops_after_it_wrote_names_the_files_it_wrote_redacted(self):
        class Failing(FakeGateway):
            def download_attachment(self, attachment):
                if attachment.id == "att5102":
                    raise UnavailableError("Confluence answered with a server error (HTTP 503).", hint="Try again in a moment.")
                return super().download_attachment(attachment)

        self.gateway = Failing()
        self.gateway.page_cap = 100
        self.build()
        self.add("att5301", "2004", "alex@example.com-cv.txt", b"cv data", "text/plain")
        items = self.gateway.attachments["2004"]
        items.insert(0, items.pop())  # the file with the address in its name comes first
        with self.assertRaises(UnavailableError) as caught:
            self.use.download.execute("2004", everything=True, out_dir="out")
        self.assertIn("2 of the 7 files were written to out before that: [email], plan.txt.", caught.exception.message)
        self.assertNotIn("alex", self.said(caught.exception).lower())
        self.assertEqual(sorted(self.files.files), ["out/[email]", "out/plan.txt"])
        self.assertEqual([entry["path"] for entry in caught.exception.details["written"]], ["out/[email]", "out/plan.txt"])


class PartialRunTest(Case):
    """A run that stops after it wrote some of its files says which, whatever stopped it: a new run meets those files (`exists already`)."""

    def failing(self, error, on="att5103", **options):
        class Failing(FakeGateway):
            def download_attachment(self, attachment):
                if attachment.id == on:
                    raise error
                return super().download_attachment(attachment)

        self.gateway = Failing()
        self.gateway.page_cap = 100
        self.build(**options)

    def test_whatever_stops_the_run_after_files_were_written_the_error_says_which(self):
        unforeseen = (
            ValueError("Port out of range 0-65535"), RecursionError("maximum recursion depth exceeded"), TypeError("not what was meant"),
            OSError(24, "Too many open files"), MemoryError(), KeyError("location"),
        )
        for error in unforeseen:
            with self.subTest(error=type(error).__name__):
                self.failing(error)
                with self.assertRaises(UnavailableError) as caught:
                    self.use.download.execute("2004", everything=True, out_dir="out")
                shown = caught.exception
                self.assertEqual(sorted(self.files.files), ["out/plan.txt", "out/spec.docx"])
                self.assertIn(f"The download of budget.xlsx stopped with an unexpected {type(error).__name__}.", shown.message)
                self.assertIn("2 of the 6 files were written to out before that: plan.txt, spec.docx.", shown.message)
                if str(error):
                    self.assertNotIn(str(error), shown.message + shown.hint)  # what the exception says may hold an address: its class is enough
                self.assertIn("--force", shown.hint)
                self.assertEqual([entry["attachmentId"] for entry in shown.details["written"]], ["att5101", "att5102"])
                self.assertEqual(shown.details["failed"], {"attachmentId": "att5103"})
                self.assertEqual((shown.exit_code, shown.code), (7, "UNAVAILABLE"))
                self.assertIs(type(shown.__cause__), type(error))

    def test_the_error_of_the_cli_keeps_its_kind_and_gets_the_same_summary(self):
        self.failing(NotFoundError("Not found: GET /rest/api/content/2004/child/attachment/att5103/download", hint="Check the id."))
        with self.assertRaises(NotFoundError) as caught:
            self.use.download.execute("2004", everything=True, out_dir="out")
        self.assertIn("2 of the 6 files were written", caught.exception.message)
        self.assertEqual(caught.exception.exit_code, 4)

    def test_a_failure_of_the_first_file_is_the_failure_as_it_is(self):
        self.failing(ValueError("boom"), on="att5101")
        with self.assertRaises(ValueError):
            self.use.download.execute("2004", everything=True, out_dir="out")
        self.assertEqual(self.files.files, {})

    def test_an_interruption_by_the_person_is_never_taken_for_a_failure(self):
        for interruption in (KeyboardInterrupt(), SystemExit(3)):
            with self.subTest(error=type(interruption).__name__):
                self.failing(interruption)
                with self.assertRaises(type(interruption)):
                    self.use.download.execute("2004", everything=True, out_dir="out")
                self.assertEqual(sorted(self.files.files), ["out/plan.txt", "out/spec.docx"])  # what was written stays, and nothing half written

    def test_a_write_that_fails_in_a_way_that_nobody_foresaw_says_what_was_written_too(self):
        class Breaking(MemoryFiles):
            def write_bytes(self, path, data):
                if path.endswith("budget.xlsx"):
                    raise OSError(28, "No space left on device")
                super().write_bytes(path, data)

        self.build(files=Breaking())
        with self.assertRaises(UnavailableError) as caught:
            self.use.download.execute("2004", everything=True, out_dir="out")
        self.assertIn("The download of budget.xlsx stopped with an unexpected OSError.", caught.exception.message)
        self.assertIn("2 of the 6 files were written to out before that: plan.txt, spec.docx.", caught.exception.message)
        self.assertEqual(sorted(self.files.files), ["out/plan.txt", "out/spec.docx"])


class ArrivedSizeTest(Case):
    """What Confluence says of the size of a file is a claim, and the limit is checked against it before anything is fetched. What arrives is what
    counts: a file that is longer than the limit is refused, whatever was said, and nothing of it is decoded."""

    def lying(self, said=1, sent=5000, attachment_id="att5101"):
        items = self.gateway.attachments["2004"]
        position = next(index for index, item in enumerate(items) if item.id == attachment_id)
        items[position] = dataclasses.replace(items[position], size=said)
        self.gateway.attachment_data[attachment_id] = b"x" * sent

    def test_a_text_that_is_longer_than_the_limit_is_refused_and_nothing_is_decoded(self):
        self.lying()
        with mock.patch.object(attachments_module, "text_of", side_effect=AssertionError("something was decoded")):
            with mock.patch.object(attachments_module, "redact_people", side_effect=AssertionError("something was redacted")):
                with self.assertRaises(ValidationError) as caught:
                    self.use.read_text.execute("att5101", max_bytes=100)
        error = caught.exception
        self.assertEqual((error.exit_code, error.code), (1, "INVALID"))
        self.assertIn("plan.txt arrived with 4.9 KB, more than --max-bytes 100 (100 B); nothing was read from it.", error.message)
        self.assertIn("--max-bytes", error.hint)
        self.assertEqual(error.details, {"attachmentId": "att5101", "size": 5000, "maxBytes": 100})

    def test_the_limit_that_text_has_without_max_bytes_counts_the_same_way(self):
        self.lying()
        with mock.patch.object(attachments_module, "TEXT_MAX_BYTES", 100):
            with mock.patch.object(attachments_module, "text_of", side_effect=AssertionError("something was decoded")):
                with self.assertRaises(ValidationError) as caught:
                    self.use.read_text.execute("att5101")
        self.assertIn("more than the limit of 100 B that --text reads; nothing was read from it.", caught.exception.message)
        self.assertIn("conflu download", caught.exception.hint)

    def test_one_file_that_lies_stops_the_whole_run_and_nothing_is_shown_of_the_others(self):
        self.lying(attachment_id="att5105")
        with self.assertRaises(ValidationError) as caught:
            self.use.read_text.execute("2004", names=["plan.txt", "contacts.csv"], max_bytes=500)
        self.assertIn("contacts.csv arrived with", caught.exception.message)

    def test_a_file_of_exactly_the_limit_is_read(self):
        self.lying(said=100, sent=100)
        result = self.use.read_text.execute("att5101", max_bytes=100)
        self.assertEqual((result.files[0].action, result.files[0].text), ("read", "x" * 100))
        self.lying(said=100, sent=101)
        with self.assertRaises(ValidationError):
            self.use.read_text.execute("att5101", max_bytes=100)

    def test_the_limit_is_given_to_the_adapter_so_that_it_can_stop_reading_at_it(self):
        self.use.read_text.execute("2004", names=["plan.txt", "contacts.csv"])
        self.assertEqual(self.gateway.limits_asked, [("att5101", attachments_module.TEXT_MAX_BYTES), ("att5105", attachments_module.TEXT_MAX_BYTES)])
        self.gateway.limits_asked.clear()
        self.use.read_text.execute("att5101", max_bytes=77, version=2)
        self.assertEqual(self.gateway.limits_asked, [("att5101", 77)])
        self.gateway.limits_asked.clear()
        self.use.download.execute("att5101", out_dir="out", max_bytes=1000, version=1)
        self.use.download.execute("att5101", out_dir="two")
        self.assertEqual(self.gateway.limits_asked, [("att5101", 1000), ("att5101", 0)])  # saving has no limit of its own

    def test_a_download_that_is_longer_than_max_bytes_is_refused_when_the_adapter_did_not_stop_it(self):
        self.lying()
        with self.assertRaises(ValidationError) as caught:
            self.use.download.execute("att5101", out_dir="out", max_bytes=100)
        self.assertIn("nothing was written for it", caught.exception.message)
        self.assertEqual(self.files.files, {})


class OwnFolderTest(Case):
    """The folder that holds the configuration of the CLI is never written into: a file with the name of the configuration would replace it."""

    FOLDER = "/home/me/.config/conflu-c-cli"

    def setUp(self):
        super().setUp()
        self.setup_files()

    def setup_files(self, **options):
        files = PlacedFiles({CONFIG: "CONFLUENCE_API_TOKEN=secret-token\n"}, **options)
        self.build(files=files, store=MemoryConfigStore(path=CONFIG))

    def refused(self, out, **options):
        with self.assertRaises(UsageError) as caught:
            self.use.download.execute("att5101", out_dir=out, **options)
        self.assertEqual(caught.exception.exit_code, 2)
        self.assertIn("--out", caught.exception.hint)
        self.assertEqual(self.gateway.called("download_attachment"), [])
        self.assertEqual(self.files.files, {CONFIG: b"CONFLUENCE_API_TOKEN=secret-token\n"})

    def test_the_folder_by_its_path(self):
        self.refused(self.FOLDER)
        self.refused(self.FOLDER + "/")

    def test_a_dry_run_and_force_are_no_exception(self):
        self.refused(self.FOLDER, dry_run=True)
        self.refused(self.FOLDER, force=True)
        self.refused(self.FOLDER, force=True, dry_run=True)

    def test_the_folder_by_a_path_that_goes_through_dots(self):
        self.refused(self.FOLDER + "/../conflu-c-cli")
        self.refused("/home/me/./.config/../.config/conflu-c-cli")
        self.refused("../home/me/.config/conflu-c-cli")  # relative to the working folder, /work

    def test_the_folder_by_a_link_to_it(self):
        self.setup_files(links={"/work/shortcut": self.FOLDER})
        self.refused("shortcut")
        self.refused("/work/shortcut/")

    def test_the_folder_by_another_spelling_of_its_name_where_names_ignore_case(self):
        self.setup_files(ignore_case=True)
        self.refused("/HOME/me/.CONFIG/Conflu-C-CLI")

    def test_what_is_next_to_it_or_below_it_is_no_risk_and_is_allowed(self):
        for out in ("/home/me/.config", "/home/me/.config/conflu-c-cli-notes", self.FOLDER + "/downloads", "/home/me", "downloads"):
            with self.subTest(out=out):
                done = self.use.download.execute("att5101", out_dir=out, force=True)
                self.assertEqual(len(done), 1)

    def test_the_configuration_itself_is_never_replaced_by_an_attachment_named_like_it(self):
        self.gateway.attachments["2004"][0] = dataclasses.replace(self.gateway.attachments["2004"][0], title="config")
        self.refused(self.FOLDER, force=True)
        self.assertEqual(self.files.files[CONFIG], b"CONFLUENCE_API_TOKEN=secret-token\n")


class TextTest(Case):
    def test_a_text_file_is_read_with_its_properties(self):
        result = self.use.read_text.execute("att5101")
        (entry,) = result.files
        self.assertEqual((entry.kind, entry.action, entry.hint, entry.truncated), ("text", "read", "", False))
        self.assertEqual(entry.text, PLAN[2].data.decode())
        self.assertEqual((entry.total_chars, entry.attachment.id, result.dry_run), (len(entry.text), "att5101", False))

    def test_documents_are_read_as_their_text_and_the_others_get_a_hint(self):
        by_id = {entry.attachment.id: entry for entry in self.use.read_text.execute("2004", everything=True).files}
        self.assertEqual({key: (entry.kind, entry.action) for key, entry in by_id.items()}, {
            "att5101": ("text", "read"), "att5102": ("document", "read"), "att5103": ("document", "read"), "att5104": ("document", "read"),
            "att5105": ("text", "read"), "att5106": ("document", "not text"),
        })
        self.assertIn("# Specification", by_id["att5102"].text)
        self.assertIn("Hardware\t1200", by_id["att5103"].text)
        self.assertIn("## Slide 1", by_id["att5104"].text)

    def test_a_picture_is_not_shown_as_text_and_the_hint_points_to_the_plain_download(self):
        (entry,) = self.use.read_text.execute("att5001").files
        self.assertEqual((entry.kind, entry.action, entry.text, entry.total_chars), ("other", "not text", None, None))
        self.assertIn("image/png", entry.hint)
        self.assertIn("conflu download att5001", entry.hint)
        self.assertEqual(self.gateway.called("download_attachment"), [])  # the bytes of a picture are never fetched

    def test_the_type_in_the_hint_of_a_file_that_is_no_text_is_redacted_unless_people_are_shown(self):
        self.add("att5302", "2004", "odd.bin", b"x", "application/x-alex@example.com")
        (hidden,) = self.use.read_text.execute("att5302").files
        self.assertIn("Not shown as text (application/[email]). Save it with `conflu download att5302`", hidden.hint)
        self.assertNotIn("alex", hidden.hint)
        self.assertEqual(hidden.attachment.media_type, "application/[email]")  # the hint and the field of the entry say the same
        (shown,) = self.use.read_text.execute("att5302", with_users=True).files
        self.assertIn("Not shown as text (application/x-alex@example.com).", shown.hint)

    def test_a_damaged_document_is_an_entry_with_a_hint_and_not_a_failure_of_the_run(self):
        result = self.use.read_text.execute("2004", names=["broken.docx", "plan.txt"])
        broken, fine = result.files
        self.assertEqual((broken.action, broken.text), ("not text", None))
        self.assertIn("no Office Open XML document", broken.hint)
        self.assertIn("conflu download att5106", broken.hint)
        self.assertNotIn("this is no document", broken.hint)  # never what the file holds
        self.assertEqual(fine.action, "read")

    def test_a_reader_that_fails_unexpectedly_costs_that_file_and_not_the_run(self):
        real = attachments_module.text_of

        def breaks_on_one(data, reading):
            if data.startswith(b"Release plan\n\nFinal"):
                raise RuntimeError("secret detail of the content")
            return real(data, reading)

        with mock.patch.object(attachments_module, "text_of", breaks_on_one):
            plan, spec = self.use.read_text.execute("2004", names=["plan.txt", "spec.docx"]).files
        self.assertEqual((plan.action, spec.action), ("not text", "read"))
        self.assertIn("RuntimeError", plan.hint)
        self.assertNotIn("secret detail", plan.hint)
        self.assertEqual(len(self.diagnostics.debugs), 1)
        self.assertNotIn("secret detail", self.diagnostics.debugs[0])

    def test_a_binary_file_that_says_it_is_text_is_a_hint_too(self):
        self.add("att5500", "2004", "fake.txt", b"PK\x03\x04\x00\x00\x00binary")
        (entry,) = self.use.read_text.execute("att5500").files
        self.assertEqual((entry.action, entry.text), ("not text", None))
        self.assertIn("binary", entry.hint)

    def test_a_file_without_text_says_so(self):
        self.add("att5501", "2004", "empty.txt", b"  \n")
        (entry,) = self.use.read_text.execute("att5501").files
        self.assertEqual((entry.action, entry.text, entry.total_chars, entry.hint), ("read", "  \n", 3, "The file holds no text."))

    def test_the_text_is_cut_at_the_end_of_a_paragraph_and_says_how_long_it_was(self):
        text = b"first paragraph here\n\nsecond paragraph is longer than the rest\n\nthird"
        self.add("att5502", "2004", "long.txt", text)
        (entry,) = self.use.read_text.execute("att5502", max_chars=45).files
        self.assertEqual((entry.text, entry.truncated, entry.total_chars), ("first paragraph here\n\nsecond paragraph is", True, len(text)))

    def test_the_limit_must_be_a_positive_number(self):
        with self.assertRaises(UsageError):
            self.use.read_text.execute("att5101", max_chars=0)
        with self.assertRaises(UsageError):
            self.use.read_text.execute("att5101", max_bytes=-1)

    def test_addresses_are_taken_out_before_the_cut_so_that_none_is_cut_in_half(self):
        self.add("att5503", "2004", "address.txt", b"Mail to alex@example.com today")
        (entry,) = self.use.read_text.execute("att5503", max_chars=14).files
        self.assertEqual(entry.text, "Mail to")  # cut before the address was taken out it would have ended in "alex@e"
        self.assertEqual((entry.truncated, entry.total_chars), (True, len("Mail to [email] today")))

    def test_people_are_shown_only_when_asked_for(self):
        (hidden,) = self.use.read_text.execute("att5105").files
        self.assertIn("[email]", hidden.text)
        self.assertNotIn("alex@example.com", hidden.text)
        (shown,) = self.use.read_text.execute("att5105", with_users=True).files
        self.assertIn("alex@example.com", shown.text)
        self.assertEqual(shown.attachment.title, "contacts.csv")

    def test_the_name_in_the_answer_is_redacted_too(self):
        self.add("att5504", "2004", "alex@example.com.txt", b"x")
        (entry,) = self.use.read_text.execute("att5504").files
        self.assertEqual(entry.attachment.title, "[email]")
        (entry,) = self.use.read_text.execute("att5504", with_users=True).files
        self.assertEqual(entry.attachment.title, "alex@example.com.txt")

    def test_people_are_refused_under_the_policy(self):
        self.build(hide_users=True)
        with self.assertRaises(ValidationError):
            self.use.read_text.execute("att5101", with_users=True)
        self.assertEqual(self.gateway.calls, [])

    def test_what_a_terminal_would_obey_is_taken_out_of_the_text(self):
        hostile = "plain\x1b[31m red \x1b]0;a title\x07and \u202egnp\u200b hidden " + "".join(chr(0xE0000 + ord(letter)) for letter in "ignore") + "\x01 end\n"
        self.add("att5505", "2004", "hostile.txt", hostile.encode("utf-8"))
        (entry,) = self.use.read_text.execute("att5505").files
        self.assertEqual(entry.text, "plain red and gnp hidden \ufffd end\n")
        for char in ("\x1b", "\x07", "\u202e", "\u200b", chr(0xE0069)):
            self.assertNotIn(char, entry.text)

    def test_a_version_of_a_file_is_read(self):
        (entry,) = self.use.read_text.execute("att5101", version=1).files
        self.assertEqual((entry.text, entry.attachment.version), (PLAN[0].data.decode(), 1))
        self.assertIn(("fetch_attachment", "att5101", 1), self.gateway.calls)

    def test_a_dry_run_fetches_nothing(self):
        result = self.use.read_text.execute("2004", everything=True, dry_run=True)
        self.assertTrue(result.dry_run)
        self.assertEqual([(entry.attachment.id, entry.action) for entry in result.files], [
            ("att5101", "would read"), ("att5102", "would read"), ("att5103", "would read"), ("att5104", "would read"), ("att5105", "would read"), ("att5106", "would read"),
        ])
        self.assertEqual({entry.text for entry in result.files}, {None})
        self.assertEqual(self.gateway.called("download_attachment") + self.gateway.called("fetch_attachment"), [])

    def test_a_file_over_the_limit_is_refused_before_anything_is_fetched(self):
        with self.assertRaises(ValidationError) as caught:
            self.use.read_text.execute("2004", everything=True, max_bytes=100)
        self.assertIn("spec.docx", caught.exception.message)
        self.assertEqual(self.gateway.called("download_attachment") + self.gateway.called("fetch_attachment"), [])

    def test_without_a_limit_of_its_own_the_text_of_a_huge_file_is_not_read(self):
        self.gateway.attachments["2004"][0] = dataclasses.replace(self.gateway.attachments["2004"][0], size=attachments_module.TEXT_MAX_BYTES + 1)
        with self.assertRaises(ValidationError) as caught:
            self.use.read_text.execute("att5101")
        self.assertIn("25.0 MB that --text reads", caught.exception.message)
        self.assertIn("conflu download", caught.exception.hint)
        self.assertEqual(len(self.use.read_text.execute("att5101", max_bytes=attachments_module.TEXT_MAX_BYTES + 1, dry_run=True).files), 1)

    def test_a_dry_run_says_what_the_limit_would_refuse(self):
        (entry,) = self.use.read_text.execute("att5102", max_bytes=100, dry_run=True).files
        self.assertEqual(entry.action, "too large")

    def test_a_picture_over_the_limit_is_no_problem_because_it_is_not_read(self):
        self.gateway.attachments["2002"][0] = dataclasses.replace(self.gateway.attachments["2002"][0], size=10**9)
        (entry,) = self.use.read_text.execute("att5001", max_bytes=100).files
        self.assertEqual(entry.action, "not text")

    def test_the_text_of_a_blog_post_attachment(self):
        (entry,) = self.use.read_text.execute("7102", names=["minutes.md"]).files
        self.assertEqual(entry.text, "# Minutes\n\nDecisions were made.\n")


class UploadTest(Case):
    def setUp(self):
        super().setUp()
        self.setup_files({"in/new.txt": "fresh", "in/plan.txt": "a new plan\n", "in/diagram.png": b"PNG..."})

    def setup_files(self, files, **options):
        self.build(files=PlacedFiles(files, **options), store=MemoryConfigStore(path=CONFIG))

    def sent(self):
        return self.gateway.called("upload_attachment")

    def test_files_are_uploaded_under_their_own_names_and_a_new_name_replaces_nothing(self):
        result = self.use.upload.execute("2003", ["in/new.txt", "in/diagram.png"], comment="October", minor=True)
        self.assertEqual([(item.name, item.size, item.action, item.replaces) for item in result.uploads], [("new.txt", 5, "uploaded", None), ("diagram.png", 6, "uploaded", None)])
        self.assertEqual(self.sent()[0][1:], ("2003", "new.txt", b"fresh", "October", True))
        self.assertEqual((result.comment, result.minor, result.dry_run), ("October", True, False))
        self.assertTrue(all(item.attachment and item.attachment.version == 1 for item in result.uploads))

    def test_a_file_with_the_name_of_an_attachment_becomes_its_new_version_and_the_result_says_which(self):
        result = self.use.upload.execute("2004", ["in/plan.txt"])
        (upload,) = result.uploads
        self.assertEqual((upload.replaces.id, upload.replaces.version, upload.attachment.id, upload.attachment.version), ("att5101", 3, "att5101", 4))
        self.assertEqual(self.gateway.attachment_data["att5101"], b"a new plan\n")

    def test_the_page_and_the_names_are_read_before_anything_is_written(self):
        self.use.upload.execute("2004", ["in/plan.txt", "in/new.txt"])
        calls = self.names(self.gateway.calls)
        self.assertEqual(calls, ["list_attachments", "upload_attachment", "upload_attachment"])  # one read serves both files
        self.assertEqual([call[2] for call in self.gateway.called("list_attachments")], [""])  # the list of the page, not one call for each name

    def test_one_file_is_looked_for_by_its_name(self):
        self.use.upload.execute("2004", ["in/plan.txt"])
        self.assertEqual([call[2] for call in self.gateway.called("list_attachments")], ["plan.txt"])

    def test_a_dry_run_reads_the_same_and_sends_nothing(self):
        result = self.use.upload.execute("2004", ["in/plan.txt", "in/new.txt"], dry_run=True)
        self.assertTrue(result.dry_run)
        self.assertEqual([(item.action, item.attachment, item.replaces and item.replaces.id) for item in result.uploads], [("would upload", None, "att5101"), ("would upload", None, None)])
        self.assertEqual(self.sent(), [])
        self.assertEqual(self.names(self.gateway.calls), ["list_attachments"])

    def test_a_page_that_is_not_there_is_not_found_in_a_dry_run_and_in_a_real_run(self):
        for dry_run in (True, False):
            with self.assertRaises(NotFoundError):
                self.use.upload.execute("999", ["in/new.txt"], dry_run=dry_run)
        self.assertEqual(self.sent(), [])

    def test_a_blog_post_is_no_page_and_the_error_says_what_it_is(self):
        with self.assertRaises(NotFoundError) as caught:
            self.use.upload.execute("7102", ["in/new.txt"])
        self.assertIn("a blog post", caught.exception.hint)
        self.assertEqual(self.sent(), [])

    def test_a_missing_file_a_folder_or_a_name_that_is_empty_stops_everything_before_any_request(self):
        for paths in (["in/missing.txt"], ["in/new.txt", "in"], ["in/new.txt", "in/missing.txt"], ["/"]):
            with self.subTest(paths=paths):
                with self.assertRaises(ValidationError):
                    self.use.upload.execute("2003", paths)
        with self.assertRaises(UsageError):
            self.use.upload.execute("2003", [])
        self.assertEqual(self.gateway.calls, [])

    def test_two_files_of_one_name_are_refused_because_the_second_would_only_be_a_new_version_of_the_first(self):
        self.setup_files({"a/report.txt": "one", "b/Report.TXT": "two"})
        with self.assertRaises(ValidationError) as caught:
            self.use.upload.execute("2003", ["a/report.txt", "b/Report.TXT"])
        self.assertIn("both called", caught.exception.message)
        self.assertEqual(self.gateway.calls, [])

    def test_the_version_that_was_read_is_guarded(self):
        result = self.use.upload.execute("2004", ["in/plan.txt"], if_version=3)
        self.assertEqual(result.uploads[0].attachment.version, 4)
        with self.assertRaises(ConflictError) as caught:
            self.use.upload.execute("2004", ["in/plan.txt"], if_version=3)  # it is at 4 now
        self.assertEqual(caught.exception.exit_code, 3)
        self.assertEqual(len(self.sent()), 1)

    def test_a_dry_run_keeps_the_guards(self):
        with self.assertRaises(ConflictError):
            self.use.upload.execute("2004", ["in/plan.txt"], if_version=2, dry_run=True)
        self.assertEqual(self.sent(), [])

    def test_zero_says_that_the_file_must_be_new(self):
        self.use.upload.execute("2004", ["in/new.txt"], if_version=0)
        with self.assertRaises(ConflictError):
            self.use.upload.execute("2004", ["in/plan.txt"], if_version=0)
        self.assertEqual(len(self.sent()), 1)

    def test_a_version_for_a_file_that_is_not_there_is_a_conflict(self):
        with self.assertRaises(ConflictError):
            self.use.upload.execute("2004", ["in/new.txt"], if_version=1)

    def test_a_version_names_one_attachment_so_it_needs_one_file(self):
        with self.assertRaises(UsageError):
            self.use.upload.execute("2004", ["in/plan.txt", "in/new.txt"], if_version=3)
        with self.assertRaises(UsageError):
            self.use.upload.execute("2004", ["in/plan.txt"], if_version=-1)
        self.assertEqual(self.gateway.calls, [])

    def test_a_file_is_not_attached_over_what_was_saved_after_the_time_the_person_read_it(self):
        with self.assertRaises(ConflictError):
            self.use.upload.execute("2004", ["in/plan.txt"], if_unchanged_since="2026-10-09T13:00:00Z")
        self.assertEqual(self.sent(), [])
        self.use.upload.execute("2004", ["in/plan.txt", "in/new.txt"], if_unchanged_since="2026-10-09T14:00:00Z")  # the very moment is no change
        self.assertEqual(len(self.sent()), 2)

    def test_a_new_file_replaces_nothing_so_the_time_does_not_matter_and_a_bad_time_is_refused_first(self):
        self.use.upload.execute("2004", ["in/new.txt"], if_unchanged_since="2001-01-01T00:00:00Z")
        with self.assertRaises(ValidationError):
            self.use.upload.execute("2004", ["in/plan.txt"], if_unchanged_since="yesterday")
        self.assertEqual(len(self.sent()), 1)
        self.assertEqual(self.names(self.gateway.calls).count("list_attachments"), 1)  # the bad time was refused before the page was read

    def test_an_empty_guard_time_is_an_error_that_names_the_option_and_never_means_no_guard(self):
        for value in ("", "   "):
            for dry_run in (False, True):
                with self.subTest(value=value, dry_run=dry_run):
                    with self.assertRaises(ValidationError) as caught:
                        self.use.upload.execute("2004", ["in/plan.txt"], if_unchanged_since=value, dry_run=dry_run)
                    self.assertEqual(caught.exception.exit_code, 1)
                    self.assertIn("--if-unchanged-since", caught.exception.message)
        self.assertEqual(self.gateway.calls, [])  # refused before anything was asked, so nothing could have been sent
        self.use.upload.execute("2004", ["in/plan.txt"], if_unchanged_since=None)  # absent is no guard
        self.assertEqual(len(self.sent()), 1)

    def test_a_guard_is_looked_at_again_just_before_each_later_file_goes(self):
        class Racing(FakeGateway):
            def upload_attachment(self, page_id, filename, data, *, comment="", minor=False):
                result = super().upload_attachment(page_id, filename, data, comment=comment, minor=minor)
                items = self.attachments["2004"]
                for index, item in enumerate(items):
                    if item.title == "spec.docx":  # somebody saves the next file while the first one is on its way
                        items[index] = dataclasses.replace(item, updated="2026-10-11T00:00:00.000Z", version=item.version + 1)
                return result

        self.gateway = Racing()
        self.gateway.page_cap = 100
        self.setup_files({"in/plan.txt": "a new plan\n", "in/spec.docx": "a new specification"})
        with self.assertRaises(ConflictError) as caught:
            self.use.upload.execute("2004", ["in/plan.txt", "in/spec.docx"], if_unchanged_since="2026-10-10T00:00:00Z")
        self.assertEqual(caught.exception.exit_code, 3)
        self.assertEqual([call[2] for call in self.sent()], ["plan.txt"])  # the first went, the second was stopped
        self.assertEqual(self.names(self.gateway.calls).count("list_attachments"), 2)  # one read for both files, one more for the second just before it goes

    def test_without_a_guard_the_names_are_read_once(self):
        self.use.upload.execute("2004", ["in/plan.txt", "in/new.txt"])
        self.assertEqual(self.names(self.gateway.calls).count("list_attachments"), 1)

    def test_the_old_field_of_the_application_uploads_as_it_did(self):
        result = self.app.upload_attachments.execute("2003", ["in/new.txt"], comment="old")
        self.assertEqual(result.uploads[0].attachment.version, 1)


class UploadReadsTheAttachmentsOnceTest(Case):
    """`attach` asks for the attachments of the page once for all its files (1.0.0 asked for none), and a read that is refused does not stop an upload
    that no guard depends on: it only leaves it open which files become new versions."""

    def setUp(self):
        super().setUp()
        self.paths = [f"in/file-{number}.txt" for number in range(8)]
        self.setup_files({path: f"text {index}" for index, path in enumerate(self.paths)})

    def setup_files(self, files):
        self.build(files=PlacedFiles(files), store=MemoryConfigStore(path=CONFIG))

    def sent(self):
        return self.gateway.called("upload_attachment")

    def test_eight_files_cost_one_read_and_eight_uploads(self):
        self.use.upload.execute("2003", self.paths)
        self.assertEqual(self.names(self.gateway.calls), ["list_attachments"] + ["upload_attachment"] * 8)

    def test_the_list_of_a_big_page_is_read_in_pieces_until_every_name_is_found(self):
        titles = [item.title for item in self.gateway.attachments["2004"]]
        ids = [item.id for item in self.gateway.attachments["2004"]]
        self.gateway.page_cap = 2
        self.setup_files({f"in/{titles[-1]}": "x", f"in/{titles[-2]}": "y"})
        result = self.use.upload.execute("2004", [f"in/{titles[-1]}", f"in/{titles[-2]}"], dry_run=True)
        self.assertEqual([item.replaces.id for item in result.uploads], [ids[-1], ids[-2]])
        self.assertEqual(self.names(self.gateway.calls), ["list_attachments"] * 3)  # six attachments, two to a piece, the two names are in the last piece

    def test_a_name_that_is_not_in_the_pieces_that_were_read_is_asked_for_by_itself(self):
        titles = [item.title for item in self.gateway.attachments["2004"]]
        ids = [item.id for item in self.gateway.attachments["2004"]]
        self.gateway.page_cap = 2
        self.setup_files({f"in/{titles[-1]}": "x", "in/new.txt": "y"})
        with mock.patch.object(attachments_module, "LISTING_CALLS", 1):
            result = self.use.upload.execute("2004", [f"in/{titles[-1]}", "in/new.txt"], dry_run=True)
        self.assertEqual([item.replaces and item.replaces.id for item in result.uploads], [ids[-1], None])  # the answer is right although the list was not read to its end
        self.assertEqual([call[2] for call in self.gateway.called("list_attachments")], ["", titles[-1], "new.txt"])

    def test_a_read_that_is_refused_for_want_of_permission_does_not_stop_an_upload_that_no_guard_depends_on(self):
        self.gateway.errors["list_attachments"] = AuthError("Confluence refused this request (HTTP 403).", details={"status": 403})
        for paths in (self.paths[:2], self.paths[:1]):  # several files read the list of the page, one file asks for its name
            with self.subTest(files=len(paths)):
                self.gateway.calls.clear()
                self.diagnostics.warnings.clear()
                result = self.use.upload.execute("2003", paths)
                self.assertEqual([call[2] for call in self.sent()], [path.rpartition("/")[2] for path in paths])
                self.assertEqual([(item.checked, item.replaces, item.action) for item in result.uploads], [(False, None, "uploaded")] * len(paths))
                (warning,) = self.diagnostics.warnings
                self.assertIn("Could not read the attachments of page 2003", warning)
                self.assertIn("the files are sent anyway", warning)
                self.assertIn("not known which of them become new versions", warning)

    def test_any_other_failure_of_the_read_stops_the_command_before_anything_is_sent_in_a_dry_run_too(self):
        failures = (
            AuthError("Confluence did not accept the credentials (HTTP 401).", details={"status": 401}),
            AuthError("A refusal without a status."),
            UnavailableError("Confluence answered with a server error (HTTP 500).", details={"status": 500}),
            UnavailableError("Confluence answered HTTP 200 with something that is not JSON (text/html)."),
            RejectedError("HTTP 400"),
        )
        for error in failures:
            for dry_run in (False, True):
                with self.subTest(error=error.message[:40], dry_run=dry_run):
                    self.gateway.errors["list_attachments"] = error
                    with self.assertRaises(type(error)):
                        self.use.upload.execute("2003", self.paths[:2], dry_run=dry_run)
                    self.assertEqual(self.sent(), [])
                    self.assertEqual(self.diagnostics.warnings, [])

    def test_a_dry_run_says_what_it_could_not_check(self):
        self.gateway.errors["list_attachments"] = AuthError("Confluence refused this request (HTTP 403).", details={"status": 403})
        result = self.use.upload.execute("2003", self.paths[:1], dry_run=True)
        self.assertEqual(self.sent(), [])
        self.assertEqual([(item.checked, item.action) for item in result.uploads], [(False, "would upload")])
        self.assertIn("the files would be sent", self.diagnostics.warnings[0])

    def test_a_guard_needs_the_read_and_a_refused_read_stops_the_command(self):
        self.gateway.errors["list_attachments"] = AuthError("Confluence refused this request (HTTP 403).", details={"status": 403})
        for options in ({"if_version": 3}, {"if_unchanged_since": "2026-10-10T00:00:00Z"}):
            with self.subTest(options=options):
                with self.assertRaises(AuthError):
                    self.use.upload.execute("2003", self.paths[:1], **options)
                self.assertEqual(self.sent(), [])
        self.assertEqual(self.diagnostics.warnings, [])

    def test_a_page_that_is_not_there_is_not_found_whatever_the_guards_and_the_id_is_asked_about_once(self):
        for paths in (self.paths[:1], self.paths[:2]):
            with self.subTest(files=len(paths)):
                self.gateway.calls.clear()
                with self.assertRaises(NotFoundError):
                    self.use.upload.execute("999", paths)
                self.assertEqual(self.sent(), [])
                self.assertEqual(self.names(self.gateway.calls).count("content_types"), 1)

    def test_a_run_that_could_read_the_page_marks_every_file_as_checked(self):
        result = self.use.upload.execute("2004", ["in/file-0.txt"])
        self.assertTrue(all(item.checked for item in result.uploads))
        self.assertEqual(self.diagnostics.warnings, [])


class PartialUploadTest(Case):
    """A run that stops after it uploaded some of its files says which, whatever stopped it: they are on the page, and the same command run again
    would give each of them another version."""

    def failing_at(self, name, error):
        class Failing(FakeGateway):
            def upload_attachment(self, page_id, filename, data, *, comment="", minor=False):
                if filename == name:
                    raise error
                return super().upload_attachment(page_id, filename, data, comment=comment, minor=minor)

        self.gateway = Failing()
        self.gateway.page_cap = 100
        self.build(files=PlacedFiles({"in/a.txt": "first", "in/b.txt": "second", "in/c.txt": "third"}), store=MemoryConfigStore(path=CONFIG))

    def run_three(self, **options):
        return self.use.upload.execute("2003", ["in/a.txt", "in/b.txt", "in/c.txt"], **options)

    def test_an_error_of_confluence_after_files_were_uploaded_says_which_and_keeps_its_kind(self):
        self.failing_at("b.txt", UnavailableError("Cannot reach Confluence (TimeoutError: timed out).", hint="Check the network.", details={"status": 0}))
        with self.assertRaises(UnavailableError) as caught:
            self.run_three()
        error = caught.exception
        self.assertEqual((error.exit_code, error.code), (7, "UNAVAILABLE"))
        self.assertEqual(
            error.message, "Cannot reach Confluence (TimeoutError: timed out). 1 of the 3 files were uploaded to page 2003 before that: a.txt."
        )
        self.assertTrue(error.hint.startswith("Check the network. "))
        self.assertIn("do not run the same command as it is", error.hint)
        self.assertIn("`conflu attachments 2003`", error.hint)
        self.assertIn("the files that are left: b.txt, c.txt.", error.hint)
        (stored,) = self.gateway.attachments["2003"]
        self.assertEqual(error.details["uploaded"], [{"path": "in/a.txt", "name": "a.txt", "size": 5, "attachmentId": stored.id, "version": 1}])
        self.assertEqual((error.details["failed"], error.details["status"]), ({"path": "in/b.txt", "name": "b.txt"}, 0))  # what the error had stays
        self.assertEqual([call[2] for call in self.gateway.called("upload_attachment")], ["a.txt"])

    def test_a_failure_of_the_first_file_is_the_error_as_it_is(self):
        self.failing_at("a.txt", UnavailableError("down", hint="later"))
        with self.assertRaises(UnavailableError) as caught:
            self.run_three()
        self.assertEqual((caught.exception.message, caught.exception.hint, caught.exception.details), ("down", "later", {}))

    def test_the_last_file_that_fails_is_named_as_failed_and_not_as_left_behind(self):
        self.failing_at("c.txt", UnavailableError("down"))
        with self.assertRaises(UnavailableError) as caught:
            self.run_three()
        self.assertIn("2 of the 3 files were uploaded to page 2003 before that: a.txt, b.txt.", caught.exception.message)
        self.assertIn("the files that are left: c.txt.", caught.exception.hint)
        self.assertEqual([entry["name"] for entry in caught.exception.details["uploaded"]], ["a.txt", "b.txt"])

    def test_whatever_else_stops_the_run_after_files_were_uploaded_the_error_says_which(self):
        for error in (ValueError("a text that may hold alex@example.com"), RecursionError("depth"), OSError(24, "Too many open files"), MemoryError(), KeyError("location")):
            with self.subTest(error=type(error).__name__):
                self.failing_at("b.txt", error)
                with self.assertRaises(UnavailableError) as caught:
                    self.run_three()
                shown = caught.exception
                self.assertEqual((shown.exit_code, shown.code), (7, "UNAVAILABLE"))
                self.assertIn(f"The upload of b.txt stopped with an unexpected {type(error).__name__}. 1 of the 3 files were uploaded to page 2003 before that: a.txt.", shown.message)
                self.assertNotIn("alex", shown.message + shown.hint)  # the kind of the error is enough: what it says may hold anything
                self.assertEqual([entry["name"] for entry in shown.details["uploaded"]], ["a.txt"])
                self.assertIs(type(shown.__cause__), type(error))

    def test_an_unforeseen_stop_of_the_first_file_is_left_as_it_is(self):
        self.failing_at("a.txt", ValueError("boom"))
        with self.assertRaises(ValueError):
            self.run_three()

    def test_an_interruption_by_the_person_is_never_taken_for_a_failure(self):
        for interruption in (KeyboardInterrupt(), SystemExit(3)):
            with self.subTest(error=type(interruption).__name__):
                self.failing_at("b.txt", interruption)
                with self.assertRaises(type(interruption)):
                    self.run_three()
                self.assertEqual([call[2] for call in self.gateway.called("upload_attachment")], ["a.txt"])

    def test_a_file_that_cannot_be_read_any_more_stops_the_run_with_the_same_summary(self):
        gateway = self.gateway

        class Vanishing(PlacedFiles):
            def read_bytes(self, path):
                if path == "in/b.txt" and gateway.called("upload_attachment"):  # a.txt has gone: now b.txt is not there any more
                    raise ValidationError("Cannot read in/b.txt: No such file or directory")
                return super().read_bytes(path)

        self.build(files=Vanishing({"in/a.txt": "first", "in/b.txt": "second"}), store=MemoryConfigStore(path=CONFIG))
        with self.assertRaises(ValidationError) as caught:
            self.use.upload.execute("2003", ["in/a.txt", "in/b.txt"])
        self.assertIn("Cannot read in/b.txt: No such file or directory 1 of the 2 files were uploaded to page 2003 before that: a.txt.", caught.exception.message)
        self.assertEqual([call[2] for call in self.gateway.called("upload_attachment")], ["a.txt"])

    def test_a_guard_that_stops_a_later_file_says_which_files_went_and_keeps_exit_code_3(self):
        class Racing(FakeGateway):
            def upload_attachment(self, page_id, filename, data, *, comment="", minor=False):
                result = super().upload_attachment(page_id, filename, data, comment=comment, minor=minor)
                items = self.attachments["2004"]
                for index, item in enumerate(items):
                    if item.title == "spec.docx":  # somebody saves the next file while the first one is on its way
                        items[index] = dataclasses.replace(item, updated="2026-10-11T00:00:00.000Z", version=item.version + 1)
                return result

        self.gateway = Racing()
        self.gateway.page_cap = 100
        self.build(files=PlacedFiles({"in/plan.txt": "a new plan\n", "in/spec.docx": "a new specification"}), store=MemoryConfigStore(path=CONFIG))
        with self.assertRaises(ConflictError) as caught:
            self.use.upload.execute("2004", ["in/plan.txt", "in/spec.docx"], if_unchanged_since="2026-10-10T00:00:00Z")
        error = caught.exception
        self.assertEqual(error.exit_code, 3)
        self.assertIn("changed in Confluence", error.message)
        self.assertIn("1 of the 2 files were uploaded to page 2004 before that: plan.txt.", error.message)
        self.assertEqual([(entry["name"], entry["attachmentId"], entry["version"]) for entry in error.details["uploaded"]], [("plan.txt", "att5101", 4)])
        self.assertEqual((error.details["failed"]["name"], error.details["since"][:10]), ("spec.docx", "2026-10-10"))  # the details of the conflict stay


class SwappingFiles(PlacedFiles):
    """Files of which one holds the token as soon as it has been searched for it: what the search saw is not what the upload would send. It is told
    by the end of the search and not by the number of reads, which the size of a file, the search and the upload make in an order of their own."""

    def __init__(self, files, swap, **options):
        super().__init__(files, **options)
        self.swap = swap
        self.searched = False

    def read_pieces(self, path, size):
        yield from super().read_pieces(path, size)
        if path == self.swap:
            self.searched = True  # the search of that file is over, and it found nothing

    def read_bytes(self, path):
        if path == self.swap and self.searched:
            return b"now it holds secret-token"
        return super().read_bytes(path)


class GuardTest(Case):
    """What is never attached: the configuration of the CLI, and any file that holds its token. Nothing is sent, in a dry run too."""

    def setUp(self):
        super().setUp()
        self.setup_files()

    def setup_files(self, extra=None, **options):
        files = {CONFIG: "CONFLUENCE_EMAIL=user@example.com\nCONFLUENCE_API_TOKEN=secret-token\n", "/work/notes.txt": "plain notes", **(extra or {})}
        self.build(files=PlacedFiles(files, **options), store=MemoryConfigStore(path=CONFIG))

    def refused(self, *paths, **options):
        for dry_run in (False, True):
            with self.subTest(paths=paths, dry_run=dry_run):
                with self.assertRaises(UsageError) as caught:
                    self.use.upload.execute("2003", list(paths), dry_run=dry_run, **options)
                self.assertEqual(caught.exception.exit_code, 2)
                self.assertNotIn("secret-token", caught.exception.message + caught.exception.hint + str(caught.exception.details))
                self.assertIn("Nothing was sent", caught.exception.hint)
                self.assertEqual(self.gateway.calls, [])

    def test_the_configuration_by_its_path(self):
        self.refused(CONFIG)

    def test_the_configuration_by_dots_and_by_a_relative_path(self):
        self.refused("/work/../home/me/.config/conflu-c-cli/config")
        self.refused("../home/me/.config/conflu-c-cli/../conflu-c-cli/config")
        self.refused("/home/me/./.config/conflu-c-cli/./config")

    def test_the_configuration_by_a_link(self):
        self.setup_files(links={"/work/innocent.txt": CONFIG, "/work/folder": "/home/me/.config/conflu-c-cli"})
        self.refused("innocent.txt")
        self.refused("folder/config")

    def test_the_configuration_by_another_spelling_of_its_name_where_names_ignore_case(self):
        self.setup_files(ignore_case=True)
        self.refused("/Home/Me/.Config/conflu-c-cli/CONFIG")

    def test_the_configuration_among_other_files(self):
        self.refused("/work/notes.txt", CONFIG)
        self.assertEqual(self.gateway.calls, [])

    def test_a_file_with_the_name_of_the_configuration_that_is_another_file_is_no_problem(self):
        self.setup_files({"/work/config": "just a file named config"})
        result = self.use.upload.execute("2003", ["config"])
        self.assertEqual(result.uploads[0].name, "config")

    def test_a_copy_of_the_settings_holds_the_token(self):
        self.setup_files({"/work/backup.txt": "CONFLUENCE_API_TOKEN=secret-token\n"})
        self.refused("/work/backup.txt")

    def test_the_token_in_every_encoding_a_file_may_have(self):
        header = base64.b64encode(b"user@example.com:secret-token")
        forms = {
            "utf8": b"log: token=secret-token end",
            "utf16": "log: token=secret-token end".encode("utf-16"),
            "utf16le": "log: token=secret-token end".encode("utf-16-le"),
            "utf16be": "log: token=secret-token end".encode("utf-16-be"),
            "header": b"GET /wiki/api/v2/pages HTTP/1.1\r\nAuthorization: Basic " + header + b"\r\n\r\n",
            "header16": ("Authorization: Basic " + header.decode()).encode("utf-16"),
        }
        for label, data in forms.items():
            with self.subTest(label):
                self.setup_files({"/work/leak.bin": data})
                self.refused("/work/leak.bin")

    def test_the_token_is_found_wherever_a_piece_of_the_file_ends(self):
        for piece in (1, 2, 3, 7, 11):
            with self.subTest(piece=piece):
                self.setup_files({"/work/leak.txt": "x" * 20 + "secret-token" + "y" * 20}, piece=piece)
                self.refused("/work/leak.txt")

    def test_the_file_is_read_piece_by_piece_where_the_file_system_can_do_that(self):
        self.setup_files({"/work/a.txt": "one", "/work/b.txt": "two"})
        self.use.upload.execute("2003", ["a.txt", "b.txt"], dry_run=True)
        self.assertEqual(self.files.pieces_read, ["a.txt", "b.txt"])

    def test_a_file_system_that_cannot_do_that_is_read_whole(self):
        self.build(files=MemoryFiles({"a.txt": "token secret-token", "b.txt": "fine"}))
        with self.assertRaises(UsageError):
            self.use.upload.execute("2003", ["a.txt"], dry_run=True)
        self.assertEqual(len(self.use.upload.execute("2003", ["b.txt"], dry_run=True).uploads), 1)

    def test_a_file_that_is_too_large_to_be_searched_is_refused_and_not_read(self):
        self.setup_files({"/work/big.bin": b"x" * 100})
        with mock.patch.object(attachments_module, "SCAN_LIMIT", 50):
            with self.assertRaises(ValidationError) as caught:
                self.use.upload.execute("2003", ["big.bin"])
        self.assertIn("is not attached", caught.exception.message)
        self.assertEqual((self.gateway.calls, self.files.pieces_read), ([], []))

    def test_a_file_that_changes_between_the_search_and_the_upload_is_looked_at_again(self):
        self.build(files=SwappingFiles({"/work/leaky.txt": "clean when searched"}, "leaky.txt"), store=MemoryConfigStore(path=CONFIG))
        with self.assertRaises(UsageError) as caught:
            self.use.upload.execute("2003", ["leaky.txt"])
        self.assertIn("holds the API token", caught.exception.message)
        self.assertIn("Nothing was sent", caught.exception.hint)
        self.assertEqual(self.gateway.called("upload_attachment"), [])
        self.assertTrue(self.files.searched)  # the search found nothing: it was the read of the upload that found the token

    def test_a_file_that_changes_to_hold_the_token_after_an_earlier_one_went_is_not_sent_and_the_error_says_what_was(self):
        self.build(files=SwappingFiles({"/work/a.txt": "clean", "/work/b.txt": "clean when searched"}, "b.txt"), store=MemoryConfigStore(path=CONFIG))
        with self.assertRaises(UsageError) as caught:
            self.use.upload.execute("2003", ["a.txt", "b.txt"])
        error = caught.exception
        self.assertEqual(error.exit_code, 2)
        self.assertIn("b.txt holds the API token of this CLI.", error.message)
        self.assertIn("1 of the 2 files were uploaded to page 2003 before that: a.txt.", error.message)
        self.assertTrue(error.hint.startswith("This file was not sent."))  # not "Nothing was sent": a.txt was
        self.assertNotIn("Nothing was sent", error.hint)
        self.assertNotIn("secret-token", error.message + error.hint + str(error.details))
        self.assertEqual([call[2] for call in self.gateway.called("upload_attachment")], ["a.txt"])

    def test_the_message_names_the_file_and_never_shows_the_token(self):
        self.setup_files({"/work/backup.txt": "CONFLUENCE_API_TOKEN=secret-token\n"})
        with self.assertRaises(UsageError) as caught:
            self.use.upload.execute("2003", ["/work/backup.txt"])
        self.assertIn("/work/backup.txt holds the API token of this CLI", caught.exception.message)
        self.assertIn("conflu setup-token", caught.exception.hint)

    def test_a_name_in_a_message_cannot_move_the_cursor(self):
        self.setup_files({"/work/\x1b[2Jbackup.txt": "secret-token"})
        with self.assertRaises(UsageError) as caught:
            self.use.upload.execute("2003", ["/work/\x1b[2Jbackup.txt"])
        self.assertNotIn("\x1b", caught.exception.message)

    def test_a_short_token_is_no_reason_to_refuse_files(self):
        self.build(files=PlacedFiles({"/work/a.txt": "abc"}), store=MemoryConfigStore(path=CONFIG), api_token="abc")
        self.assertEqual(len(self.use.upload.execute("2003", ["a.txt"]).uploads), 1)

    def test_without_a_token_nothing_is_searched(self):
        self.build(files=PlacedFiles({"/work/a.txt": "abc"}), store=MemoryConfigStore(path=CONFIG), api_token="")
        self.use.upload.execute("2003", ["a.txt"])
        self.assertEqual(self.files.pieces_read, [])

    def test_a_dry_run_of_a_clean_file_is_not_refused(self):
        result = self.use.upload.execute("2003", ["notes.txt"], dry_run=True)
        self.assertEqual((result.uploads[0].action, result.dry_run), ("would upload", True))
        self.assertEqual(self.gateway.called("upload_attachment"), [])


if __name__ == "__main__":
    unittest.main()
