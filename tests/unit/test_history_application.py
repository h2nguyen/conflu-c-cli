"""The use cases around earlier versions of a page, against the fake Confluence: read a version, several pages, the diff and the restore."""
import unittest

from conflu_c_cli.application.pages import MissingPage, PageView
from conflu_c_cli.domain.errors import ConflictError, NotFoundError, UnavailableError, UsageError, ValidationError
from conflu_c_cli.domain.model import Attachment, User, VersionInfo
from tests.support.fakes import ACCOUNT, BASE, FakeGateway, RecordingDiagnostics, build_app, default_settings
from tests.support.fakes_history import SECOND_BODY


def app_for(gateway=None, **settings):
    gateway = gateway or FakeGateway()
    diagnostics = RecordingDiagnostics()
    return build_app(gateway=gateway, settings=default_settings(**settings), diagnostics=diagnostics), gateway, diagnostics


class ReadAVersionTest(unittest.TestCase):
    def setUp(self):
        self.app, self.gateway, _ = app_for()

    def view(self, ref="2002", **options):
        return self.app.view_page.execute(ref, **options)

    def test_an_earlier_version_has_its_own_title_body_and_version(self):
        view = self.view(version=1)
        self.assertEqual((view.page.id, view.page.title, view.page.version_number, view.current_version), ("2002", "Release notes (draft)", 1, 3))
        self.assertIn("Draft.", view.body.text)
        self.assertNotIn("Contact", view.body.text)
        self.assertEqual((view.page.version.message, view.page.updated), ("Created", "2026-10-01T08:00:00.000Z"))
        self.assertIsNone(view.page.body)

    def test_what_belongs_to_the_page_and_not_to_a_version_is_the_page_s_now(self):
        view = self.view(version=1)
        self.assertEqual([label.name for label in view.page.labels], ["release", "notes"])
        self.assertTrue(view.labels_shown)

    def test_two_requests_are_made_the_current_page_without_a_body_and_the_version_with_it(self):
        self.view(version=2)
        self.assertEqual(self.gateway.called("get_page"), [("get_page", "2002", False)])
        self.assertEqual(self.gateway.called("get_page_version"), [("get_page_version", "2002", 2, True)])

    def test_the_current_version_asked_for_by_its_number_says_that_it_is_the_current_one(self):
        view = self.view(version=3)
        self.assertEqual((view.page.version_number, view.current_version), (3, 3))
        self.assertIn("Second", view.body.text)

    def test_an_ordinary_read_says_nothing_about_versions(self):
        view = self.view()
        self.assertEqual(view.current_version, 0)
        self.assertEqual(self.gateway.called("get_page_version"), [])

    def test_a_version_above_the_newest_is_not_found_and_costs_no_version_request(self):
        with self.assertRaises(NotFoundError) as caught:
            self.view(version=9)
        error = caught.exception
        self.assertEqual(error.message, "Page 2002 has no version 9.")
        self.assertEqual(error.hint, "The page is at version 3. `conflu versions 2002` lists the versions it has.")
        self.assertEqual((error.details["version"], error.details["currentVersion"], error.exit_code), (9, 3, 4))
        self.assertEqual(self.gateway.called("get_page_version"), [])

    def test_a_version_that_was_removed_is_not_found_with_the_same_hint(self):
        history = self.gateway.versions["2002"]
        self.gateway.versions["2002"] = [item for item in history if item.number != 2]
        with self.assertRaises(NotFoundError) as caught:
            self.view(version=2)
        self.assertEqual(caught.exception.message, "Page 2002 has no version 2.")
        self.assertIn("conflu versions 2002", caught.exception.hint)
        self.assertEqual(len(self.gateway.called("get_page_version")), 1)

    def test_a_page_that_does_not_exist_is_the_plain_not_found(self):
        with self.assertRaises(NotFoundError) as caught:
            self.view("999", version=1)
        self.assertIn("Not found: GET /api/v2/pages/999", caught.exception.message)
        self.assertNotIn("has no version", caught.exception.message)

    def test_a_version_number_below_one_is_a_usage_error_before_any_request(self):
        for number in (0, -1):
            with self.subTest(number=number):
                with self.assertRaises(UsageError):
                    self.view(version=number)
        self.assertEqual(self.gateway.calls, [])

    def test_comments_and_ancestors_are_those_of_now_so_they_are_refused_with_a_version(self):
        for options in ({"with_comments": True}, {"with_ancestors": True}):
            with self.subTest(options=options):
                with self.assertRaises(UsageError) as caught:
                    self.view(version=1, **options)
                self.assertIn("--comments", caught.exception.hint)
        self.assertEqual(self.gateway.calls, [])

    def test_people_are_hidden_in_an_earlier_version_as_in_the_current_one(self):
        view = self.view(version=2)
        self.assertIn("@user", view.body.text)
        self.assertNotIn(ACCOUNT, view.body.text)
        self.assertIsNone(view.page.author)
        self.assertIsNone(view.page.version.author)
        storage = self.view(version=2, body_format="storage")
        self.assertNotIn(ACCOUNT, storage.body.text)
        self.assertIn('ri:account-id="hidden"', storage.body.text)

    def test_with_users_names_the_people_of_that_version(self):
        view = self.view(version=2, with_users=True, body_format="storage")
        self.assertIn(ACCOUNT, view.body.text)
        self.assertEqual(view.page.version.author.display_name, "Alex Example")

    def test_the_raw_answer_of_a_version_loses_the_people(self):
        raw = self.view(version=2, want_raw=True).raw
        self.assertEqual(raw["version"]["number"], 2)
        self.assertNotIn(ACCOUNT, str(raw))

    def test_a_version_without_a_body_and_the_parts_of_a_version(self):
        self.assertIsNone(self.view(version=1, with_body=False).body)
        self.assertEqual(self.gateway.called("get_page_version")[-1], ("get_page_version", "2002", 1, False))
        outline = self.view(version=3, outline=True)
        self.assertEqual([heading.title for heading in outline.outline], ["Release notes"])
        self.assertEqual(self.view(version=3, section="release").body.section, "Release notes")
        self.assertTrue(self.view(version=3, max_chars=10).body.truncated)

    def test_the_policy_forbids_people_before_anything_is_asked(self):
        app, gateway, _ = app_for(hide_users=True)
        with self.assertRaises(ValidationError):
            app.view_page.execute("2002", version=1, with_users=True)
        self.assertEqual(gateway.calls, [])


class AttachmentsTest(unittest.TestCase):
    def setUp(self):
        self.app, self.gateway, _ = app_for()

    def test_the_files_of_the_page_are_shown_with_one_request_when_asked_for(self):
        view = self.app.view_page.execute("2002", with_attachments=True)
        self.assertEqual([(item.id, item.title, item.media_type, item.size) for item in view.attachments], [("att5001", "diagram.png", "image/png", 10), ("att5002", "notes.txt", "text/plain", 12)])
        self.assertEqual(len(self.gateway.called("list_attachments")), 1)

    def test_without_the_option_the_files_are_not_read_and_the_view_has_none(self):
        view = self.app.view_page.execute("2002")
        self.assertIsNone(view.attachments)
        self.assertEqual(self.gateway.called("list_attachments"), [])

    def test_a_page_without_files_has_an_empty_list_which_is_not_none(self):
        view = self.app.view_page.execute("2003", with_attachments=True)
        self.assertEqual(view.attachments, ())

    def test_every_chunk_of_the_list_is_read(self):
        for index in range(3, 6):
            self.gateway.attachments["2002"].append(Attachment(f"att60{index}", f"file{index}.txt", "text/plain", index, "2026-10-04T08:00:00.000Z", 1, "2002"))
        view = self.app.view_page.execute("2002", with_attachments=True)
        self.assertEqual(len(view.attachments), 5)
        self.assertGreater(len(self.gateway.called("list_attachments")), 1)  # the fake hands out two at a time

    def test_a_file_name_with_an_e_mail_address_is_hidden_unless_people_are_shown(self):
        self.gateway.attachments["2002"].append(Attachment("att7000", "report-alex@example.com.pdf", "application/pdf", 5, "2026-10-04T08:00:00.000Z", 1, "2002"))
        names = [item.title for item in self.app.view_page.execute("2002", with_attachments=True).attachments]
        self.assertEqual(names[-1], "[email]")  # the redaction takes the whole word, so the extension goes with the address
        self.assertFalse(any("alex@example.com" in name for name in names))
        shown = [item.title for item in self.app.view_page.execute("2002", with_attachments=True, with_users=True).attachments]
        self.assertIn("report-alex@example.com.pdf", shown)

    def test_an_earlier_version_can_show_the_files_too(self):
        view = self.app.view_page.execute("2002", version=1, with_attachments=True)
        self.assertEqual(len(view.attachments), 2)


class ReadSeveralPagesTest(unittest.TestCase):
    def setUp(self):
        self.app, self.gateway, self.diagnostics = app_for()

    def many(self, *refs, **options):
        return self.app.view_page.execute_many(list(refs), **options)

    def test_the_pages_come_in_the_order_given_with_one_request_for_all_of_them(self):
        self.gateway.page_cap = 1000
        result = self.many("2003", "2002", "2005")
        self.assertEqual([view.page.id for view in result.pages], ["2003", "2002", "2005"])
        self.assertTrue(all(isinstance(entry, PageView) for entry in result.entries))
        self.assertEqual(result.errors, [])
        self.assertEqual(self.gateway.called("get_pages"), [("get_pages", ("2003", "2002", "2005"), True, 250, "")])
        self.assertEqual(self.gateway.called("get_page"), [])

    def test_the_answer_is_followed_when_it_does_not_fit_in_one_piece(self):
        result = self.many("2001", "2002", "2003", "2004", "2005")
        self.assertEqual([view.page.id for view in result.pages], ["2001", "2002", "2003", "2004", "2005"])
        self.assertEqual(len(self.gateway.called("get_pages")), 3)  # the fake hands out two at a time

    def test_each_page_is_what_a_read_of_it_alone_shows_except_for_the_labels(self):
        several = {view.page.id: view for view in self.many("2002", "2003").pages}
        alone = self.app.view_page.execute("2002")
        self.assertEqual(several["2002"].body, alone.body)
        self.assertEqual(several["2002"].page.version, alone.page.version)
        self.assertEqual(several["2002"].page.title, alone.page.title)
        self.assertEqual([label.name for label in alone.page.labels], ["release", "notes"])
        self.assertEqual(several["2002"].page.labels, [])
        self.assertFalse(several["2002"].labels_shown)
        self.assertTrue(alone.labels_shown)

    def test_a_page_that_is_not_there_is_an_entry_and_the_others_are_still_read(self):
        result = self.many("2002", "999", "2003")
        self.assertEqual([view.page.id for view in result.pages], ["2002", "2003"])
        self.assertEqual(len(result.errors), 1)
        missing = result.errors[0]
        self.assertEqual((missing.ref, missing.code, missing.exit_code), ("999", "NOT_FOUND", 4))
        self.assertIn("999", missing.message)
        self.assertEqual([type(entry) for entry in result.entries], [PageView, MissingPage, PageView])  # in the order of the refs
        self.assertEqual(self.gateway.called("get_page"), [("get_page", "999", True)])  # asked on its own: not found is Confluence's answer to that page

    def test_a_page_that_the_list_leaves_out_but_that_exists_is_read_on_its_own(self):
        self.gateway.pages["2003"].status = "trashed"
        result = self.many("2002", "2003")
        self.assertEqual([view.page.id for view in result.pages], ["2002", "2003"])
        self.assertEqual(result.errors, [])
        self.assertEqual(self.gateway.called("get_page"), [("get_page", "2003", True)])

    def test_an_archived_page_comes_with_the_list(self):
        self.gateway.pages["2005"].status = "archived"
        result = self.many("2002", "2005")
        self.assertEqual([(view.page.id, view.page.status) for view in result.pages], [("2002", "current"), ("2005", "archived")])
        self.assertEqual(self.gateway.called("get_page"), [])

    def test_the_same_page_given_twice_or_in_two_forms_is_shown_once(self):
        result = self.many("2002", f"{BASE}/spaces/ENG/pages/2002/Release+notes", "2003", "2002")
        self.assertEqual([view.page.id for view in result.pages], ["2002", "2003"])
        self.assertEqual(self.gateway.called("get_pages")[0][1], ("2002", "2003"))

    def test_a_page_named_by_its_title_is_found_first_and_read_with_the_others(self):
        result = self.many("page:ENG/Architecture", "2002")
        self.assertEqual([view.page.id for view in result.pages], ["2003", "2002"])
        self.assertEqual(self.gateway.called("get_pages")[0][1], ("2003", "2002"))
        self.assertEqual(len(self.gateway.called("list_pages")), 1)

    def test_a_title_that_names_no_page_is_an_entry_with_the_text_as_it_was_given(self):
        result = self.many("page:ENG/No such page", "2002")
        self.assertEqual([view.page.id for view in result.pages], ["2002"])
        self.assertEqual((result.errors[0].ref, result.errors[0].code), ("page:ENG/No such page", "NOT_FOUND"))
        self.assertEqual(result.entries[0], result.errors[0])

    def test_an_ambiguous_title_is_refused_for_the_whole_call(self):
        self.gateway.pages["2005"].title = "Architecture"
        with self.assertRaises(ValidationError):
            self.many("page:ENG/Architecture", "2002")
        self.assertEqual(self.gateway.called("get_pages"), [])

    def test_something_that_is_no_id_is_refused_for_the_whole_call_before_any_request(self):
        for bad in ("abc", "", "2002;2003", "../2002", "1" * 20, "page:", "2002\n2003"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    self.many("2002", bad)
        self.assertEqual(self.gateway.calls, [])

    def test_nothing_given_is_a_usage_error(self):
        with self.assertRaises(UsageError):
            self.app.view_page.execute_many([])

    def test_the_pages_are_asked_for_250_at_a_time(self):
        self.gateway.page_cap = 1000
        refs = [str(number) for number in range(2001, 2006)] + [str(number) for number in range(90000, 90295)]
        result = self.many(*refs, with_body=False)
        self.assertEqual([len(call[1]) for call in self.gateway.called("get_pages")], [250, 50])
        self.assertEqual(len(result.pages), 5)
        self.assertEqual(len(result.errors), 295)
        self.assertTrue(all(call[2] is False for call in self.gateway.called("get_pages")))  # no body asked for

    def test_the_options_that_shape_a_body_apply_to_every_page(self):
        outlines = self.many("2002", "2003", outline=True).pages
        self.assertTrue(all(view.body is None and view.outline is not None for view in outlines))
        self.assertEqual([heading.title for heading in outlines[0].outline], ["Release notes"])
        cut = self.many("2002", "2003", max_chars=12).pages
        self.assertTrue(all(view.body.truncated or len(view.body.text) <= 12 for view in cut))
        none = self.many("2002", "2003", with_body=False)
        self.assertTrue(all(view.body is None for view in none.pages))
        self.assertEqual(self.gateway.called("get_pages")[-1][2], False)

    def test_a_section_that_a_page_lacks_is_an_entry_for_that_page_only(self):
        result = self.many("2002", "2003", section="release notes")
        self.assertEqual([view.page.id for view in result.pages], ["2002"])
        missing = result.errors[0]
        self.assertEqual((missing.ref, missing.code, missing.exit_code), ("2003", "INVALID", 1))
        self.assertIn("no headings", missing.message)

    def test_comments_ancestors_and_files_are_read_for_each_page(self):
        result = self.many("2002", "2004", with_comments=True, with_ancestors=True, with_attachments=True)
        self.assertEqual([view.page.id for view in result.pages], ["2002", "2004"])
        self.assertEqual([item[1] for item in self.gateway.called("list_ancestors")], ["2002", "2004"])
        self.assertEqual([item[1] for item in self.gateway.called("list_comments") if not item[2]], ["2002", "2004"])
        self.assertEqual([ref.id for ref in result.pages[1].page.ancestors], ["2001", "2003"])
        self.assertEqual(len(result.pages[0].attachments), 2)
        self.assertEqual([len(view.attachments) for view in result.pages], [len(self.gateway.attachments[page_id]) for page_id in ("2002", "2004")])  # each page its own files
        self.assertEqual(len(result.pages[0].comments), 2)

    def test_people_are_named_once_for_all_the_pages(self):
        result = self.many("2002", "2003", "2004", with_users=True)
        self.assertTrue(all(view.users_shown for view in result.pages))
        self.assertEqual(result.pages[0].page.author.display_name, "Alex Example")
        self.assertEqual(result.pages[2].page.author.display_name, "Alex Example")
        self.assertEqual(len(self.gateway.called("lookup_users")), 1)

    def test_people_are_hidden_in_every_page_by_default(self):
        for view in self.many("2002", "2003").pages:
            self.assertIsNone(view.page.author)
            self.assertNotIn(ACCOUNT, view.body.text)
            self.assertNotIn("alex@example.com", view.body.text)
        self.assertEqual(self.gateway.called("lookup_users"), [])

    def test_the_policy_forbids_people_before_anything_is_asked(self):
        app, gateway, _ = app_for(hide_users=True)
        with self.assertRaises(ValidationError):
            app.view_page.execute_many(["2002", "2003"], with_users=True)
        self.assertEqual(gateway.calls, [])

    def test_a_version_and_the_raw_answer_are_for_one_page(self):
        with self.assertRaises(UsageError) as caught:
            self.many("2002", "2003", version=1)
        self.assertIn("--version", caught.exception.message)
        with self.assertRaises(UsageError) as caught:
            self.many("2002", "2003", want_raw=True)
        self.assertIn("--raw", caught.exception.message)
        self.assertEqual(self.gateway.calls, [])

    def test_options_that_make_no_sense_together_are_refused_before_anything_is_asked(self):
        for options in ({"outline": True, "with_body": False}, {"section": "x", "body_format": "storage"}, {"body_format": "html"}):
            with self.subTest(options=options):
                with self.assertRaises(UsageError):
                    self.many("2002", "2003", **options)
        self.assertEqual(self.gateway.calls, [])

    def test_a_failure_of_the_list_is_the_failure_of_the_call(self):
        self.gateway.errors["get_pages"] = UnavailableError("busy")
        with self.assertRaises(UnavailableError):
            self.many("2002", "2003")


class DiffTest(unittest.TestCase):
    def setUp(self):
        self.app, self.gateway, _ = app_for()
        self.diff = self.app.history.diff_versions

    def test_by_default_the_current_version_is_compared_with_the_one_before(self):
        result = self.diff.execute("2002")
        self.assertEqual((result.from_side.number, result.to_side.number, result.to_side.current, result.from_side.current), (2, 3, True, False))
        self.assertEqual(result.page_id, "2002")
        self.assertEqual(result.title, "Release notes")
        text = result.difference.text
        self.assertTrue(text.startswith("--- version 2\t2026-10-05T10:00:00.000Z\n+++ version 3 (current)\t2026-10-10T09:00:00.000Z\n"))
        self.assertIn("-Contact @user.", text)
        self.assertIn("+Contact @user or write to [email].", text)
        self.assertIn("+- Second", text)
        self.assertEqual((result.difference.added, result.difference.removed, result.difference.identical), (2, 1, False))
        self.assertFalse(result.source_identical)
        self.assertEqual(result.note, "")

    def test_the_current_page_is_read_once_with_its_body_and_only_the_other_version_is_asked_for(self):
        self.diff.execute("2002")
        self.assertEqual(self.gateway.called("get_page"), [("get_page", "2002", True)])
        self.assertEqual(self.gateway.called("get_page_version"), [("get_page_version", "2002", 2, True)])

    def test_the_two_versions_can_be_named_and_need_not_be_the_neighbours(self):
        result = self.diff.execute("2002", from_version=1, to_version=2)
        self.assertEqual((result.from_side.number, result.to_side.number, result.to_side.current), (1, 2, False))
        self.assertEqual((result.from_side.title, result.to_side.title), ("Release notes (draft)", "Release notes"))
        self.assertIn("-Draft.", result.difference.text)
        self.assertEqual(len(self.gateway.called("get_page_version")), 2)
        self.assertEqual(self.gateway.called("get_page"), [("get_page", "2002", True)])
        later = self.diff.execute("2002", from_version=1)
        self.assertEqual((later.from_side.number, later.to_side.number), (1, 3))

    def test_it_can_go_the_other_way(self):
        result = self.diff.execute("2002", from_version=3, to_version=1)
        self.assertEqual((result.from_side.current, result.to_side.current), (True, False))
        self.assertIn("-Contact @user or write to [email].", result.difference.text)
        self.assertIn("+Draft.", result.difference.text)

    def test_a_version_compared_with_itself_says_so(self):
        result = self.diff.execute("2002", from_version=2, to_version=2)
        self.assertEqual((result.difference.text, result.difference.identical), ("", True))
        self.assertEqual(result.note, "Version 2 is compared with itself.")

    def test_a_page_with_one_version_has_nothing_to_compare(self):
        result = self.diff.execute("2005")
        self.assertIsNone(result.from_side)
        self.assertEqual((result.to_side.number, result.difference.identical, result.difference.text), (1, True, ""))
        self.assertEqual(result.note, "Page 2005 has one version only: there is nothing to compare.")
        self.assertEqual(self.gateway.called("get_page_version"), [])

    def test_the_first_version_of_a_page_that_has_more_has_nothing_before_it(self):
        result = self.diff.execute("2002", to_version=1)  # the page has three versions: it is not "one version only"
        self.assertIsNone(result.from_side)
        self.assertEqual((result.to_side.number, result.to_side.current), (1, False))
        self.assertNotIn("one version only", result.note)
        self.assertEqual(
            result.note,
            "Version 1 is the first version of page 2002: nothing came before it, so there is nothing to compare. `--from 1` compares it with the current version.",
        )
        self.assertEqual((result.identical, result.source_identical, result.difference.text, result.nothing_before), (False, False, "", True))
        self.assertEqual((result.difference.added, result.difference.removed), (0, 0))

    def test_a_page_with_one_version_is_the_page_whose_newest_version_is_the_first(self):
        result = self.diff.execute("2005", to_version=1)
        self.assertEqual(result.note, "Page 2005 has one version only: there is nothing to compare.")
        self.assertEqual((result.identical, result.nothing_before), (True, False))
        self.assertEqual(self.gateway.called("get_page_version"), [])

    def test_the_first_version_can_still_be_compared_with_a_later_one_when_that_is_named(self):
        result = self.diff.execute("2002", from_version=1)
        self.assertEqual((result.from_side.number, result.to_side.number, result.identical, result.nothing_before), (1, 3, False, False))
        self.assertIn("-Draft.", result.difference.text)

    def test_versions_that_read_the_same_say_so_and_name_what_the_markdown_cannot_show(self):
        self.gateway.version_bodies[("2002", 1)] = "<h1>Release notes</h1><p>Same.</p>"
        self.gateway.version_bodies[("2002", 2)] = '<h1>Release notes</h1><p>Same.</p><ac:structured-macro ac:name="toc" ac:schema-version="1" />'
        result = self.diff.execute("2002", from_version=1, to_version=2)
        self.assertTrue(result.difference.identical)
        self.assertEqual(result.difference.text, "")
        self.assertFalse(result.source_identical)
        self.assertEqual(result.dropped, ("macro:toc",))
        self.assertEqual(result.note, "Versions 1 and 2 read the same as Markdown.")

    def test_versions_with_the_same_storage_format_are_the_same_in_every_way(self):
        self.gateway.version_bodies[("2002", 1)] = self.gateway.version_bodies[("2002", 2)]
        result = self.diff.execute("2002", from_version=1, to_version=2)
        self.assertTrue(result.source_identical)

    def test_what_is_dropped_is_the_union_of_both_versions(self):
        result = self.diff.execute("2002")
        self.assertEqual(result.dropped, ("macro:toc", "mention", "redacted-text"))

    def test_people_are_not_in_the_diff_nor_in_the_messages(self):
        self.gateway.versions["2002"][1] = VersionInfo(2, "2026-10-05T10:00:00.000Z", "Mail alex@example.com", False, User(ACCOUNT, "Alex Example"))
        self.gateway.pages["2002"].title = "Notes of alex@example.com"
        result = self.diff.execute("2002")
        everything = repr(result)
        self.assertNotIn("alex@example.com", everything)
        self.assertNotIn(ACCOUNT, everything)
        self.assertNotIn("Alex Example", everything)
        self.assertEqual((result.from_side.message, result.title), ("Mail [email]", "Notes of [email]"))

    def test_the_versions_that_the_page_does_not_have_are_not_found_with_where_to_look(self):
        for options in ({"from_version": 9}, {"to_version": 9}, {"from_version": 9, "to_version": 2}):
            with self.subTest(options=options):
                with self.assertRaises(NotFoundError) as caught:
                    self.diff.execute("2002", **options)
                self.assertEqual(caught.exception.message, "Page 2002 has no version 9.")
                self.assertIn("conflu versions 2002", caught.exception.hint)

    def test_a_removed_version_is_not_found_too(self):
        self.gateway.versions["2002"] = [item for item in self.gateway.versions["2002"] if item.number != 2]
        with self.assertRaises(NotFoundError) as caught:
            self.diff.execute("2002")
        self.assertEqual(caught.exception.message, "Page 2002 has no version 2.")

    def test_wrong_numbers_and_sizes_are_usage_errors_before_any_request(self):
        for options in ({"from_version": 0}, {"to_version": 0}, {"from_version": -1}, {"context": -1}, {"context": 5000}, {"max_chars": -1}):
            with self.subTest(options=options):
                with self.assertRaises(UsageError):
                    self.diff.execute("2002", **options)
        self.assertEqual(self.gateway.calls, [])

    def test_the_diff_can_be_cut_and_says_how_long_it_was(self):
        result = self.diff.execute("2002", from_version=1, max_chars=60)
        self.assertTrue(result.difference.truncated)
        self.assertLessEqual(len(result.difference.text), 60)
        self.assertGreater(result.difference.total_chars, 60)

    def test_the_context_is_given_to_the_diff(self):
        none = self.diff.execute("2002", context=0).difference.text
        self.assertFalse(any(line.startswith(" ") for line in none.splitlines()))

    def test_hostile_ids_are_refused_before_any_request(self):
        for ref in ("", "abc", "../2002", "2002/../2003", "1" * 20):
            with self.assertRaises(ValidationError):
                self.diff.execute(ref)
        self.assertEqual(self.gateway.calls, [])

    def test_a_page_that_does_not_exist_is_the_plain_not_found(self):
        with self.assertRaises(NotFoundError) as caught:
            self.diff.execute("999")
        self.assertIn("Not found: GET /api/v2/pages/999", caught.exception.message)


class RestoreTest(unittest.TestCase):
    def setUp(self):
        self.app, self.gateway, self.diagnostics = app_for()
        self.restore = self.app.history.restore_version

    def test_a_dry_run_reads_the_page_and_the_version_and_sends_nothing(self):
        result = self.restore.execute("2002", 2, dry_run=True)
        self.assertEqual((result.dry_run, result.restored_version, result.version_from, result.version_to), (True, 2, 3, 4))
        self.assertEqual(result.payload, {"operationKey": "restore", "params": {"versionNumber": 2, "message": "Restored version 2", "restoreTitle": False}})
        self.assertEqual((result.page_id, result.title), ("2002", "Release notes"))
        self.assertEqual(self.gateway.called("restore_page_version"), [])
        self.assertEqual(self.gateway.pages["2002"].version_number, 3)
        self.assertEqual(self.gateway.called("get_page"), [("get_page", "2002", True)])
        self.assertEqual(self.gateway.called("get_page_version"), [("get_page_version", "2002", 2, True)])

    def test_the_summary_counts_the_lines_that_the_restored_text_adds_and_takes(self):
        result = self.restore.execute("2002", 1, dry_run=True)
        self.assertEqual((result.added, result.removed), (1, 4))
        near = self.restore.execute("2002", 2, dry_run=True)
        self.assertEqual((near.added, near.removed), (1, 2))  # one line is rewritten, one is taken away

    def test_the_restore_sends_the_payload_of_the_dry_run_and_reads_the_page_back(self):
        shown = self.restore.execute("2002", 2, dry_run=True).payload
        result = self.restore.execute("2002", 2)
        self.assertEqual(self.gateway.called("restore_page_version"), [("restore_page_version", "2002", shown)])
        self.assertEqual((result.dry_run, result.version_from, result.version_to, result.restored_version), (False, 3, 4, 2))
        self.assertEqual(self.gateway.called("get_page")[-1], ("get_page", "2002", False))  # read back, without the body
        self.assertEqual(self.diagnostics.warnings, [])

    def test_the_body_comes_back_as_it_was_nothing_went_through_markdown(self):
        self.restore.execute("2002", 2)
        self.assertEqual(self.gateway.pages["2002"].body, SECOND_BODY)  # the mention, byte for byte
        self.assertIn(ACCOUNT, self.gateway.pages["2002"].body)
        self.assertIn("alex@example.com", self.gateway.version_bodies[("2002", 3)])  # version 3 is still there, with its e-mail address and its macro
        self.assertIn("toc", self.gateway.version_bodies[("2002", 3)])

    def test_the_old_title_comes_back_only_when_asked_for(self):
        self.restore.execute("2002", 1)
        self.assertEqual(self.gateway.pages["2002"].title, "Release notes")
        result = self.restore.execute("2002", 1, restore_title=True)
        self.assertEqual((result.title, self.gateway.pages["2002"].title), ("Release notes (draft)", "Release notes (draft)"))
        self.assertEqual(result.payload["params"]["restoreTitle"], True)

    def test_the_message_defaults_to_the_version_and_can_be_given(self):
        self.assertEqual(self.restore.execute("2002", 1, dry_run=True).payload["params"]["message"], "Restored version 1")
        self.assertEqual(self.restore.execute("2002", 1, message="  Back to the draft ", dry_run=True).payload["params"]["message"], "Back to the draft")
        self.assertEqual(self.restore.execute("2002", 1, message="   ", dry_run=True).payload["params"]["message"], "Restored version 1")

    def test_a_restore_makes_a_new_version_and_loses_none(self):
        self.restore.execute("2002", 1)
        numbers = [item.number for item in self.gateway.list_versions("2002", limit=25).items]
        self.assertEqual(numbers, [4, 3])  # the fake hands out two at a time: the newest and the one it covered
        self.assertEqual(self.gateway.list_versions("2002", limit=25, cursor="2").items[0].number, 2)

    def test_the_version_that_is_the_current_one_is_a_usage_error_with_a_hint(self):
        with self.assertRaises(UsageError) as caught:
            self.restore.execute("2002", 3)
        self.assertIn("nothing to restore", caught.exception.message)
        self.assertIn("conflu versions 2002", caught.exception.hint)
        self.assertEqual(caught.exception.exit_code, 2)
        self.assertEqual(self.gateway.called("restore_page_version"), [])

    def test_a_version_that_does_not_exist_is_not_found_with_where_to_look(self):
        for number in (9, 4):
            with self.subTest(number=number):
                with self.assertRaises(NotFoundError) as caught:
                    self.restore.execute("2002", number)
                self.assertEqual(caught.exception.message, f"Page 2002 has no version {number}.")
                self.assertIn("The page is at version 3", caught.exception.hint)
        self.assertEqual(self.gateway.called("restore_page_version"), [])

    def test_a_version_number_that_is_none_is_a_usage_error_before_any_request(self):
        for number in (0, -2):
            with self.assertRaises(UsageError):
                self.restore.execute("2002", number)
        self.assertEqual(self.gateway.calls, [])

    def test_the_version_that_was_read_is_checked_before_the_restore(self):
        with self.assertRaises(ConflictError) as caught:
            self.restore.execute("2002", 1, if_version=2)
        self.assertEqual((caught.exception.exit_code, caught.exception.message), (3, "Page 2002 is at version 3, not 2."))
        self.assertEqual(self.gateway.called("restore_page_version"), [])
        self.assertEqual(self.restore.execute("2002", 1, if_version=3).version_to, 4)

    def test_the_time_that_was_read_is_checked_before_the_restore(self):
        with self.assertRaises(ConflictError):
            self.restore.execute("2002", 1, if_unchanged_since="2026-10-09T00:00:00Z")
        self.assertEqual(self.gateway.called("restore_page_version"), [])
        self.assertEqual(self.restore.execute("2002", 1, if_unchanged_since="2026-10-10T09:00:00Z").version_to, 4)

    def test_the_guards_also_hold_in_a_dry_run(self):
        with self.assertRaises(ConflictError):
            self.restore.execute("2002", 1, if_version=1, dry_run=True)
        with self.assertRaises(ConflictError):
            self.restore.execute("2002", 1, if_unchanged_since="2026-10-09T00:00:00Z", dry_run=True)

    def test_an_empty_time_is_no_guard_and_no_time_either_it_is_an_error_that_names_the_option(self):
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run):
                with self.assertRaises(ValidationError) as caught:
                    self.restore.execute("2002", 1, if_unchanged_since="", dry_run=dry_run)
                self.assertEqual((caught.exception.exit_code, caught.exception.code), (1, "INVALID"))
                self.assertIn("--if-unchanged-since", caught.exception.message)
                self.assertIn("Not an ISO 8601 timestamp: ''", caught.exception.message)
                self.assertIn("Example:", caught.exception.hint)
        self.assertEqual(self.gateway.calls, [])  # refused before anything is asked, so nothing is sent

    def test_a_time_that_cannot_be_read_is_refused_before_the_page_is_read(self):
        for text in ("yesterday", " ", "2026-13-45", "10.10.2026"):
            with self.subTest(text=text):
                with self.assertRaises(ValidationError) as caught:
                    self.restore.execute("2002", 1, if_unchanged_since=text)
                self.assertIn("--if-unchanged-since", caught.exception.message)
        self.assertEqual(self.gateway.calls, [])

    def test_no_guard_given_is_no_guard(self):
        self.assertEqual(self.restore.execute("2002", 1, dry_run=True).version_to, 4)
        self.assertEqual(self.restore.execute("2002", 1, if_unchanged_since=None, dry_run=True).version_to, 4)

    def test_a_page_that_is_not_current_is_not_restored(self):
        for status in ("archived", "trashed", "draft"):
            with self.subTest(status=status):
                self.gateway.pages["2005"].status = status
                with self.assertRaises(ValidationError) as caught:
                    self.restore.execute("2005", 1)
                self.assertIn(f"Page 2005 is {status} and is not restored", caught.exception.message)
        self.assertEqual(self.gateway.called("restore_page_version"), [])

    def test_hostile_ids_are_refused_before_any_request(self):
        for ref in ("", "abc", "../2002", "2002 2003", "1" * 20):
            with self.assertRaises(ValidationError):
                self.restore.execute(ref, 1)
        self.assertEqual(self.gateway.calls, [])

    def test_a_page_that_does_not_exist_is_the_plain_not_found(self):
        with self.assertRaises(NotFoundError) as caught:
            self.restore.execute("999", 1)
        self.assertIn("Not found: GET /api/v2/pages/999", caught.exception.message)

    def test_the_title_of_the_result_is_redacted(self):
        self.gateway.pages["2002"].title = "Notes of alex@example.com"
        self.assertEqual(self.restore.execute("2002", 1, dry_run=True).title, "Notes of [email]")

    def test_when_the_page_cannot_be_read_back_the_restore_still_counts_and_a_warning_says_so(self):
        gateway = ReadBackFails()
        app, _, diagnostics = app_for(gateway)
        result = app.history.restore_version.execute("2002", 1)
        self.assertEqual((result.version_from, result.version_to), (3, 4))
        self.assertEqual(gateway.pages["2002"].version_number, 4)
        self.assertEqual(len(diagnostics.warnings), 1)
        self.assertIn("could not be read back", diagnostics.warnings[0])
        self.assertIn("busy", diagnostics.warnings[0])

    def test_when_somebody_saved_meanwhile_the_version_reached_is_reported_with_a_warning(self):
        gateway = SavedMeanwhile()
        app, _, diagnostics = app_for(gateway)
        result = app.history.restore_version.execute("2002", 1)
        self.assertEqual((result.version_from, result.version_to), (3, 5))
        self.assertEqual(len(diagnostics.warnings), 1)
        self.assertIn("version 5 now, not 4", diagnostics.warnings[0])

    def test_a_failure_of_the_restore_itself_is_the_failure_of_the_call(self):
        self.gateway.errors["restore_page_version"] = UnavailableError("busy")
        with self.assertRaises(UnavailableError):
            self.restore.execute("2002", 1)
        self.assertEqual(self.gateway.pages["2002"].version_number, 3)


class ReadBackFails(FakeGateway):
    def get_page(self, page_id, *, with_body=True):
        if not with_body and self.called("restore_page_version"):
            raise UnavailableError("busy")
        return super().get_page(page_id, with_body=with_body)


class SavedMeanwhile(FakeGateway):
    def restore_page_version(self, page_id, payload):
        page = self._page(page_id)
        self._save_version(page, page.version_number + 1, "saved by somebody else")  # between the read and the restore
        return super().restore_page_version(page_id, payload)


if __name__ == "__main__":
    unittest.main()
