"""The use cases around blog posts, against the fake Confluence: list, read, create and change."""
import unittest
from dataclasses import replace

from conflu_c_cli.domain.blogposts import BlogpostDraft
from conflu_c_cli.domain.drafts import PageChanges
from conflu_c_cli.domain.errors import ConflictError, NotFoundError, UnavailableError, UsageError, ValidationError
from tests.support.fakes import ACCOUNT, BASE, FakeGateway, RecordingDiagnostics, build_app, default_settings


def app_for(gateway=None, **settings):
    gateway = gateway or FakeGateway()
    diagnostics = RecordingDiagnostics()
    return build_app(gateway=gateway, settings=default_settings(**settings), diagnostics=diagnostics), gateway, diagnostics


class ListBlogpostsTest(unittest.TestCase):
    def test_the_current_space_is_the_default_and_the_list_goes_on_with_a_cursor(self):
        app, gateway, _ = app_for(space="ENG")
        first = app.blogposts.list_blogposts.execute(limit=2)
        self.assertEqual(first.space.key, "ENG")
        self.assertEqual([post.id for post in first.blogposts], ["7101", "7102"])
        self.assertEqual(first.next_cursor, "2")
        rest = app.blogposts.list_blogposts.execute(limit=2, cursor=first.next_cursor)
        self.assertEqual(([post.id for post in rest.blogposts], rest.next_cursor), (["7105"], ""))
        self.assertEqual(gateway.called("list_blogposts")[0][1], "1001")  # the id of the space, not its key

    def test_a_space_that_is_named_wins_over_the_current_one(self):
        app, _, _ = app_for(space="ENG")
        result = app.blogposts.list_blogposts.execute(space="DOCS")
        self.assertEqual((result.space.key, [post.id for post in result.blogposts]), ("DOCS", ["7103"]))

    def test_without_a_space_the_whole_site_is_listed_and_all_follows_the_cursor(self):
        app, gateway, _ = app_for()
        result = app.blogposts.list_blogposts.execute(fetch_everything=True)
        self.assertIsNone(result.space)
        self.assertEqual([post.id for post in result.blogposts], ["7101", "7102", "7103", "7105"])
        self.assertEqual(result.next_cursor, "")
        self.assertEqual(gateway.called("list_blogposts")[0][1], "")
        self.assertGreater(len(gateway.called("list_blogposts")), 1)  # the fake hands out two at a time

    def test_the_status_the_title_and_the_order_are_passed_on(self):
        app, _, _ = app_for()
        self.assertEqual([post.id for post in app.blogposts.list_blogposts.execute(status="trashed").blogposts], ["7104"])
        self.assertEqual([post.id for post in app.blogposts.list_blogposts.execute(title="weekly UPDATE").blogposts], ["7102"])
        newest = app.blogposts.list_blogposts.execute(sort="-modified-date", limit=3)
        self.assertEqual(newest.blogposts[0].id, "7101")  # the first of those saved last, 7101 and 7105 on one day, the id decides
        self.assertEqual([post.id for post in app.blogposts.list_blogposts.execute(sort="-id", fetch_everything=True).blogposts], ["7105", "7103", "7102", "7101"])

    def test_an_unknown_space_is_not_found_and_a_bad_key_is_invalid(self):
        app, _, _ = app_for()
        with self.assertRaises(NotFoundError):
            app.blogposts.list_blogposts.execute(space="NOPE")
        with self.assertRaises(ValidationError):
            app.blogposts.list_blogposts.execute(space="../x")

    def test_a_space_that_is_named_and_empty_is_a_mistake_and_not_the_current_space(self):
        app, gateway, _ = app_for(space="ENG")
        for value in ("", "   "):
            with self.subTest(space=value):
                with self.assertRaises(UsageError) as caught:
                    app.blogposts.list_blogposts.execute(space=value)
                self.assertEqual((caught.exception.exit_code, caught.exception.message), (2, "The space is empty."))
                self.assertIn("leave out --space", caught.exception.hint)
        self.assertEqual(gateway.calls, [])  # refused before anything is asked
        self.assertEqual(app.blogposts.list_blogposts.execute().space.key, "ENG")  # none named: the current one

    def test_a_title_that_is_given_and_empty_is_a_mistake_and_not_every_blog_post(self):
        app, gateway, _ = app_for()
        for value in ("", "  "):
            with self.subTest(title=value):
                with self.assertRaises(UsageError) as caught:
                    app.blogposts.list_blogposts.execute(title=value)
                self.assertEqual(caught.exception.message, "The title is empty.")
        self.assertEqual(gateway.calls, [])
        self.assertEqual(len(app.blogposts.list_blogposts.execute(fetch_everything=True).blogposts), 4)

    def test_people_and_addresses_stay_out_of_the_rows(self):
        gateway = FakeGateway()
        gateway.blogposts["7102"] = replace(gateway.blogposts["7102"], title="Mail alex@example.com")
        app, _, _ = app_for(gateway)
        post = app.blogposts.list_blogposts.execute(space="ENG").blogposts[1]
        self.assertEqual(post.title, "Mail [email]")
        self.assertIsNone(post.author)
        self.assertIsNone(post.version.author)


class ViewBlogpostTest(unittest.TestCase):
    def setUp(self):
        self.app, self.gateway, self.diagnostics = app_for()

    def view(self, ref="7101", **options):
        return self.app.blogposts.view_blogpost.execute(ref, **options)

    def test_a_blog_post_with_its_labels_as_markdown_without_people(self):
        view = self.view()
        self.assertEqual((view.page.id, view.page.title, view.page.status, view.page.space_key), ("7101", "Release 2026.10 is out", "current", "ENG"))
        self.assertEqual([label.name for label in view.page.labels], ["release", "news"])
        self.assertEqual(view.page.version_number, 3)
        self.assertIsNone(view.page.body)  # the body is in `view.body`
        self.assertEqual(view.body.format, "markdown")
        self.assertIn("# Release 2026.10", view.body.text)
        self.assertIn("@user", view.body.text)
        self.assertIn("[email]", view.body.text)
        self.assertNotIn("alex@example.com", view.body.text)
        self.assertNotIn(ACCOUNT, view.body.text)
        self.assertEqual(set(view.body.dropped), {"mention", "redacted-text"})
        self.assertIsNone(view.page.author)
        self.assertIsNone(view.page.version.author)
        self.assertFalse(view.users_shown)
        self.assertEqual(self.gateway.called("lookup_users"), [])

    def test_the_blog_post_can_be_named_by_the_address_copied_from_the_browser(self):
        for ref in (f"{BASE}/spaces/ENG/blog/2026/10/12/7102/Weekly+update", f"{BASE}/spaces/ENG/blog/2026/10/12/7102", "7102", " 7102 "):
            with self.subTest(ref=ref):
                self.assertEqual(self.view(ref).page.title, "Weekly update")

    def test_comments_are_the_footer_ones_then_the_inline_ones_each_with_its_replies(self):
        view = self.view(with_comments=True)
        self.assertTrue(view.comments_shown)
        self.assertEqual([(item.comment.id, item.comment.kind, item.comment.parent_id) for item in view.comments], [("7151", "footer", ""), ("7152", "footer", "7151"), ("7153", "inline", "")])
        self.assertEqual(view.comments[2].comment.resolution, "open")
        self.assertIn("Great news.", view.comments[0].body.text)
        self.assertTrue(all(item.comment.author is None and item.comment.body == "" for item in view.comments))
        self.assertEqual(self.view().comments, [])
        self.assertEqual(self.gateway.called("list_replies")[0][1:3], ("7151", False))

    def test_with_users_names_the_people_once_and_keeps_the_account_ids_in_storage(self):
        view = self.view(with_users=True, with_comments=True, body_format="storage")
        self.assertIn(ACCOUNT, view.body.text)
        self.assertEqual(view.page.author.display_name, "Alex Example")
        self.assertEqual(view.page.version.author.display_name, "Alex Example")
        self.assertEqual(view.comments[0].comment.author.display_name, "Alex Example")
        self.assertEqual(len(self.gateway.called("lookup_users")), 1)

    def test_a_failed_name_lookup_leaves_the_ids_and_warns(self):
        self.gateway.errors["lookup_users"] = UnavailableError("busy")
        view = self.view(with_users=True)
        self.assertEqual((view.page.author.account_id, view.page.author.display_name), (ACCOUNT, ""))
        self.assertTrue(any("busy" in warning for warning in self.diagnostics.warnings))

    def test_the_policy_forbids_showing_people_before_anything_is_asked(self):
        app, gateway, _ = app_for(hide_users=True)
        with self.assertRaises(ValidationError) as caught:
            app.blogposts.view_blogpost.execute("7101", with_users=True)
        self.assertIn("CONFLUENCE_HIDE_USERS", caught.exception.message)
        self.assertEqual(gateway.calls, [])

    def test_outline_section_and_cut_work_as_they_do_for_a_page(self):
        outline = self.view(outline=True)
        self.assertIsNone(outline.body)
        self.assertEqual([(heading.level, heading.title) for heading in outline.outline], [(1, "Release 2026.10"), (2, "Highlights"), (2, "Known issues")])
        section = self.view(section="highlights").body
        self.assertEqual((section.section, section.text.splitlines()[0]), ("Highlights", "## Highlights"))
        self.assertNotIn("Known issues", section.text)
        cut = self.view(max_chars=60).body
        self.assertTrue(cut.truncated)
        self.assertLess(len(cut.text), cut.total_chars)

    def test_options_that_make_no_sense_together_are_refused_before_anything_is_asked(self):
        for options in ({"outline": True, "no_body": True}, {"body_format": "html"}, {"max_chars": -1}, {"section": "x", "body_format": "text"}, {"outline": True, "section": "x"}):
            options = {("with_body" if key == "no_body" else key): (False if key == "no_body" else value) for key, value in options.items()}
            with self.subTest(options=options):
                with self.assertRaises(UsageError):
                    self.view(**options)
        self.assertEqual(self.gateway.calls, [])

    def test_no_body_reads_the_properties_only(self):
        view = self.view(with_body=False)
        self.assertIsNone(view.body)
        self.assertEqual(self.gateway.called("get_blogpost"), [("get_blogpost", "7101", False)])

    def test_raw_json_loses_the_people(self):
        self.assertNotIn(ACCOUNT, str(self.view(want_raw=True).raw))
        self.assertIn(ACCOUNT, str(self.view(want_raw=True, with_users=True).raw))
        self.assertIsNone(self.view().raw)

    def test_an_id_that_is_a_page_says_so_and_names_the_command_for_it(self):
        with self.assertRaises(NotFoundError) as caught:
            self.view("2002")
        self.assertEqual(caught.exception.message, "2002 is a page, not a blog post.")
        self.assertEqual(caught.exception.hint, "Use `conflu page 2002`.")
        self.assertEqual(caught.exception.details["type"], "page")

    def test_an_id_that_is_another_kind_of_content_says_what_it_is(self):
        self.gateway.content_kinds["4001"] = "footer-comment"
        for content_id, message, hint in (
            ("7001", "7001 is a folder, not a blog post.", "Use `conflu folder 7001`."),
            ("7061", "7061 is a smart link, not a blog post.", "Use `conflu smartlink 7061`."),
            ("4001", "4001 is a footer comment, not a blog post.", "`conflu blogposts --space KEY` lists the blog posts of a space."),
        ):
            with self.subTest(id=content_id):
                with self.assertRaises(NotFoundError) as caught:
                    self.view(content_id)
                self.assertEqual((caught.exception.message, caught.exception.hint, caught.exception.exit_code), (message, hint, 4))

    def test_an_id_that_is_nothing_stays_the_plain_not_found(self):
        with self.assertRaises(NotFoundError) as caught:
            self.view("99999")
        self.assertIn("Not found", caught.exception.message)
        self.assertNotIn("is a", caught.exception.message)

    def test_a_failed_type_lookup_keeps_the_original_error(self):
        self.gateway.errors["content_types"] = UnavailableError("busy")
        with self.assertRaises(NotFoundError) as caught:
            self.view("2002")
        self.assertIn("Not found", caught.exception.message)

    def test_hostile_ids_are_refused_before_any_request(self):
        for ref in ("", "abc", "../2002", "7101/../2002", "7101;7102", "1" * 20, "7101\n7102", "7101\x00", "https://example.atlassian.net/wiki/x/AbCd", "-7101"):
            with self.subTest(ref=ref):
                with self.assertRaises(ValidationError):
                    self.view(ref)
        self.assertEqual(self.gateway.calls, [])


class CreateBlogpostTest(unittest.TestCase):
    def setUp(self):
        self.app, self.gateway, _ = app_for(space="ENG")
        self.create = self.app.blogposts.create_blogpost

    def test_a_dry_run_proves_the_space_and_sends_nothing(self):
        result = self.create.execute(BlogpostDraft(title="Hello", body="<p>Hi</p>", labels=["News", "weekly", "news"]), dry_run=True)
        self.assertEqual((result.action, result.dry_run, result.blogpost, result.version_from, result.version_to), ("created", True, None, 0, 1))
        self.assertEqual(result.payload, {"spaceId": "1001", "status": "current", "title": "Hello", "body": {"representation": "storage", "value": "<p>Hi</p>"}})
        self.assertEqual(result.labels, ["news", "weekly"])
        self.assertEqual(self.gateway.called("create_blogpost"), [])
        self.assertEqual(self.gateway.called("add_blogpost_labels"), [])
        self.assertEqual(self.gateway.called("get_space"), [("get_space", "ENG")])

    def test_a_blog_post_is_created_with_the_payload_that_the_dry_run_showed_and_its_labels(self):
        draft = BlogpostDraft(title="Hello", body="<p>Hi</p>", labels=["news"])
        shown = self.create.execute(draft, dry_run=True).payload
        result = self.create.execute(draft)
        self.assertEqual(self.gateway.called("create_blogpost"), [("create_blogpost", shown)])
        self.assertEqual((result.action, result.dry_run, result.version_from, result.version_to), ("created", False, 0, 1))
        self.assertEqual(result.blogpost.title, "Hello")
        self.assertEqual(self.gateway.called("add_blogpost_labels"), [("add_blogpost_labels", result.blogpost.id, [{"prefix": "global", "name": "news"}])])
        self.assertEqual([label.name for label in self.gateway.blogposts[result.blogpost.id].labels], ["news"])
        self.assertEqual(self.gateway.content_kinds[result.blogpost.id], "blogpost")

    def test_without_labels_no_label_call_is_made(self):
        self.create.execute(BlogpostDraft(title="Hello"))
        self.assertEqual(self.gateway.called("add_blogpost_labels"), [])

    def test_a_space_is_named_or_current_or_an_error(self):
        self.assertEqual(self.create.execute(BlogpostDraft(space="DOCS", title="T"), dry_run=True).payload["spaceId"], "1002")
        app, gateway, _ = app_for()
        with self.assertRaises(UsageError) as caught:
            app.blogposts.create_blogpost.execute(BlogpostDraft(title="T"))
        self.assertIn("conflu use KEY", caught.exception.hint)
        self.assertEqual(gateway.calls, [])
        with self.assertRaises(NotFoundError):
            self.create.execute(BlogpostDraft(space="NOPE", title="T"))

    def test_a_space_that_is_named_and_empty_is_a_mistake_and_the_blog_post_does_not_go_to_the_current_space(self):
        for dry_run in (False, True):
            for value in ("", "   "):
                with self.subTest(dry_run=dry_run, space=value):
                    with self.assertRaises(UsageError) as caught:
                        self.create.execute(BlogpostDraft(space=value, title="T", labels=["news"]), dry_run=dry_run)  # the current space is ENG here
                    self.assertEqual((caught.exception.exit_code, caught.exception.message), (2, "The space is empty."))
        self.assertEqual(self.gateway.calls, [])

    def test_blog_posts_may_share_a_title_so_no_other_blog_post_is_looked_for(self):
        result = self.create.execute(BlogpostDraft(title="Weekly update"))
        self.assertEqual(result.blogpost.title, "Weekly update")
        self.assertEqual(self.gateway.called("list_blogposts"), [])
        self.assertEqual(self.gateway.called("list_pages"), [])
        titles = [post.title for post in self.gateway.blogposts.values()]
        self.assertEqual(titles.count("Weekly update"), 2)

    def test_a_bad_title_or_label_is_refused_before_the_space_is_asked(self):
        for draft in (BlogpostDraft(title=""), BlogpostDraft(title="two\nlines"), BlogpostDraft(title="x" * 256), BlogpostDraft(title="T", labels=["bad label"]), BlogpostDraft(title="T", labels=["a/b"])):
            with self.subTest(title=draft.title[:12], labels=draft.labels):
                with self.assertRaises(ValidationError):
                    self.create.execute(draft)
        self.assertEqual(self.gateway.calls, [])

    def test_when_the_labels_fail_the_blog_post_is_there_and_the_error_says_so(self):
        self.gateway.errors["add_blogpost_labels"] = UnavailableError("busy", details={"status": 503})
        with self.assertRaises(UnavailableError) as caught:
            self.create.execute(BlogpostDraft(title="Hello", labels=["news"]))
        error = caught.exception
        self.assertIn("The blog post was created (id ", error.message)
        self.assertIn("busy", error.message)
        self.assertEqual(error.exit_code, 7)
        self.assertEqual(error.details["status"], 503)
        created = next(post for post in self.gateway.blogposts.values() if post.title == "Hello")
        self.assertEqual((error.details["blogpostId"], error.details["url"]), (created.id, created.url))
        self.assertNotIn("conflu label", error.hint.replace("`conflu label` works on pages only", ""))


class UpdateBlogpostTest(unittest.TestCase):
    def setUp(self):
        self.app, self.gateway, _ = app_for()
        self.update = self.app.blogposts.update_blogpost

    def test_a_new_title_sends_the_body_along_and_the_next_version(self):
        result = self.update.execute("7102", PageChanges(title="Weekly update (week 42)"))
        body = "<p>Nothing to report this week.</p>"
        self.assertEqual(result.payload, {"id": "7102", "status": "current", "title": "Weekly update (week 42)", "body": {"representation": "storage", "value": body}, "version": {"number": 2}})
        self.assertEqual((result.action, result.dry_run, result.version_from, result.version_to), ("updated", False, 1, 2))
        self.assertEqual(self.gateway.called("update_blogpost"), [("update_blogpost", "7102", result.payload)])
        self.assertEqual(self.gateway.blogposts["7102"].title, "Weekly update (week 42)")
        self.assertEqual(self.gateway.blogposts["7102"].body, body)

    def test_a_dry_run_reads_and_sends_nothing(self):
        result = self.update.execute("7102", PageChanges(title="New"), dry_run=True)
        self.assertEqual((result.action, result.dry_run, result.version_from, result.version_to), ("updated", True, 1, 2))
        self.assertEqual(self.gateway.called("update_blogpost"), [])
        self.assertEqual(self.gateway.blogposts["7102"].title, "Weekly update")
        self.assertEqual(self.gateway.called("get_blogpost"), [("get_blogpost", "7102", True)])

    def test_the_same_title_and_the_same_body_is_unchanged_and_nothing_is_sent(self):
        for changes in (PageChanges(title="Weekly update"), PageChanges(title="  Weekly update  ")):
            result = self.update.execute("7102", changes)
            self.assertEqual((result.action, result.payload, result.version_from, result.version_to), ("unchanged", None, 1, 1))
        result = self.update.execute("7102", PageChanges(body="<p>Nothing to report this week.</p>", from_markdown=True))
        self.assertEqual(result.action, "unchanged")  # the Markdown says what the page says
        self.assertEqual(self.gateway.called("update_blogpost"), [])

    def test_text_is_put_behind_or_in_front_of_the_body(self):
        appended = self.update.execute("7102", PageChanges(body="<p>More.</p>", body_mode="append", from_markdown=True, message="  Added more "))
        self.assertEqual(appended.payload["body"]["value"], "<p>Nothing to report this week.</p>\n<p>More.</p>")
        self.assertEqual(appended.payload["version"], {"number": 2, "message": "Added more"})
        prepended = self.update.execute("7102", PageChanges(body="<p>First.</p>", body_mode="prepend"))
        self.assertEqual(prepended.payload["body"]["value"], "<p>First.</p>\n<p>Nothing to report this week.</p>\n<p>More.</p>")
        self.assertEqual(prepended.version_to, 3)

    def test_a_replacement_from_markdown_is_refused_when_the_blog_post_holds_what_markdown_cannot_say(self):
        with self.assertRaises(ValidationError) as caught:
            self.update.execute("7101", PageChanges(body="<p>New.</p>", from_markdown=True))
        error = caught.exception
        self.assertIn("would lose what Markdown cannot say", error.message)
        self.assertEqual(set(error.details["lost"]), {"mention", "redacted-text"})
        self.assertIn("--force", error.hint)
        self.assertEqual(self.gateway.called("update_blogpost"), [])
        forced = self.update.execute("7101", PageChanges(body="<p>New.</p>", from_markdown=True), force=True)
        self.assertEqual(set(forced.lost), {"mention", "redacted-text"})
        self.assertEqual(forced.payload["body"]["value"], "<p>New.</p>")
        self.assertEqual(self.gateway.blogposts["7101"].version_number, 4)

    def test_a_replacement_in_storage_format_needs_no_force(self):
        result = self.update.execute("7101", PageChanges(body="<p>Raw.</p>"))
        self.assertEqual((result.lost, result.payload["body"]["value"]), ((), "<p>Raw.</p>"))

    def test_a_replacement_from_markdown_of_a_simple_blog_post_is_fine(self):
        result = self.update.execute("7102", PageChanges(body="<p>Quiet week.</p>", from_markdown=True))
        self.assertEqual((result.action, result.lost), ("updated", ()))

    def test_the_version_that_was_read_is_checked_before_anything_is_sent(self):
        with self.assertRaises(ConflictError) as caught:
            self.update.execute("7101", PageChanges(title="T"), if_version=2)
        self.assertEqual(caught.exception.exit_code, 3)
        self.assertEqual(caught.exception.message, "Blog post 7101 is at version 3, not 2.")
        self.assertEqual(self.gateway.called("update_blogpost"), [])
        self.assertEqual(self.update.execute("7101", PageChanges(title="T"), if_version=3).version_to, 4)

    def test_the_time_that_was_read_is_checked_before_anything_is_sent(self):
        with self.assertRaises(ConflictError) as caught:
            self.update.execute("7101", PageChanges(title="T"), if_unchanged_since="2026-10-14T09:00:00Z")
        self.assertIn("Blog post 7101 changed in Confluence", caught.exception.message)
        self.assertEqual(self.gateway.called("update_blogpost"), [])
        self.assertEqual(self.update.execute("7101", PageChanges(title="T"), if_unchanged_since="2026-10-14T10:00:00Z").action, "updated")

    def test_the_time_is_checked_in_a_dry_run_too(self):
        with self.assertRaises(ConflictError):
            self.update.execute("7101", PageChanges(title="T"), if_unchanged_since="2026-10-14T09:00:00Z", dry_run=True)

    def test_an_empty_time_is_no_guard_and_no_time_either_it_is_an_error_that_names_the_option(self):
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run):
                with self.assertRaises(ValidationError) as caught:
                    self.update.execute("7101", PageChanges(title="T"), if_unchanged_since="", dry_run=dry_run)
                self.assertEqual((caught.exception.exit_code, caught.exception.code), (1, "INVALID"))
                self.assertIn("--if-unchanged-since", caught.exception.message)
                self.assertIn("Not an ISO 8601 timestamp: ''", caught.exception.message)
        self.assertEqual(self.gateway.calls, [])  # refused before anything is asked, so nothing is sent

    def test_a_time_that_cannot_be_read_is_refused_before_the_blog_post_is_read(self):
        for text in ("yesterday", " ", "2026-13-45"):
            with self.subTest(text=text):
                with self.assertRaises(ValidationError) as caught:
                    self.update.execute("7101", PageChanges(title="T"), if_unchanged_since=text)
                self.assertIn("--if-unchanged-since", caught.exception.message)
        self.assertEqual(self.gateway.calls, [])

    def test_no_guard_given_is_no_guard(self):
        self.assertEqual(self.update.execute("7102", PageChanges(title="T"), dry_run=True).action, "updated")
        self.assertEqual(self.update.execute("7102", PageChanges(title="T"), if_unchanged_since=None, dry_run=True).action, "updated")

    def test_a_trashed_blog_post_is_not_changed(self):
        with self.assertRaises(ValidationError) as caught:
            self.update.execute("7104", PageChanges(title="T"))
        self.assertEqual(caught.exception.message, "Blog post 7104 is trashed and is not changed.")

    def test_a_draft_stays_a_draft_and_is_version_one(self):
        self.gateway.blogposts["7102"].status = "draft"
        result = self.update.execute("7102", PageChanges(title="Draft title"), dry_run=True)
        self.assertEqual((result.payload["status"], result.payload["version"]["number"], result.version_to), ("draft", 1, 1))

    def test_nothing_to_change_is_an_error(self):
        with self.assertRaises(ValidationError) as caught:
            self.update.execute("7102", PageChanges())
        self.assertIn("No changes given", caught.exception.message)
        self.assertEqual(self.gateway.calls, [])

    def test_a_bad_title_is_refused(self):
        with self.assertRaises(ValidationError):
            self.update.execute("7102", PageChanges(title="two\nlines"))
        self.assertEqual(self.gateway.called("update_blogpost"), [])

    def test_an_id_that_is_a_page_or_does_not_exist_is_not_found(self):
        with self.assertRaises(NotFoundError) as caught:
            self.update.execute("2002", PageChanges(title="T"))
        self.assertEqual(caught.exception.message, "2002 is a page, not a blog post.")
        with self.assertRaises(NotFoundError):
            self.update.execute("99999", PageChanges(title="T"))

    def test_the_address_of_the_blog_post_names_it_and_a_hostile_id_is_refused(self):
        self.assertEqual(self.update.execute(f"{BASE}/spaces/ENG/blog/2026/10/12/7102/Weekly+update", PageChanges(title="T")).blogpost.id, "7102")
        for ref in ("", "../7102", "7102 7101", "x" * 3):
            with self.assertRaises(ValidationError):
                self.update.execute(ref, PageChanges(title="T"))

    def test_a_version_that_moved_meanwhile_is_the_conflict_of_confluence(self):
        self.gateway.errors["update_blogpost"] = ConflictError("Confluence reports a conflict (HTTP 409).")
        with self.assertRaises(ConflictError):
            self.update.execute("7102", PageChanges(title="T"))


class UpdatePrivacyTest(unittest.TestCase):
    """What is printed of a change does not name the people in the body; what is sent has them, so that a mention survives."""

    def setUp(self):
        self.app, self.gateway, _ = app_for()
        self.update = self.app.blogposts.update_blogpost

    def test_the_payload_that_is_printed_has_the_people_blanked_and_the_one_that_is_sent_does_not(self):
        result = self.update.execute("7101", PageChanges(title="Release 2026.10 is out!"))
        sent = self.gateway.called("update_blogpost")[0][2]
        self.assertIn(ACCOUNT, sent["body"]["value"])
        self.assertIn("alex@example.com", sent["body"]["value"])
        shown = str(result.payload)
        self.assertNotIn(ACCOUNT, shown)
        self.assertNotIn("alex@example.com", shown)
        self.assertIn('ri:account-id="hidden"', shown)
        self.assertIn("[email]", shown)
        self.assertTrue(result.redacted)
        self.assertEqual((result.payload["id"], result.payload["title"], result.payload["version"]), (sent["id"], sent["title"], sent["version"]))
        self.assertEqual(self.gateway.blogposts["7101"].body, sent["body"]["value"])  # Confluence got the mention, not the blank

    def test_a_dry_run_prints_the_same_copy(self):
        result = self.update.execute("7101", PageChanges(body="<p>Added.</p>", body_mode="append"), dry_run=True)
        self.assertTrue(result.redacted)
        self.assertNotIn(ACCOUNT, str(result.payload))
        self.assertIn("<p>Added.</p>", result.payload["body"]["value"])
        self.assertEqual(self.gateway.called("update_blogpost"), [])

    def test_with_users_prints_exactly_what_is_sent(self):
        result = self.update.execute("7101", PageChanges(title="T"), dry_run=True, with_users=True)
        self.assertFalse(result.redacted)
        self.assertIn(ACCOUNT, result.payload["body"]["value"])
        self.assertIn("alex@example.com", result.payload["body"]["value"])
        self.assertEqual(result.blogpost.title, "Release 2026.10 is out")
        real = self.update.execute("7101", PageChanges(title="T2"), with_users=True)
        self.assertEqual(real.payload, self.gateway.called("update_blogpost")[0][2])

    def test_the_policy_forbids_people_before_anything_is_asked(self):
        app, gateway, _ = app_for(hide_users=True)
        with self.assertRaises(ValidationError) as caught:
            app.blogposts.update_blogpost.execute("7101", PageChanges(title="T"), with_users=True)
        self.assertIn("CONFLUENCE_HIDE_USERS", caught.exception.message)
        self.assertEqual(gateway.calls, [])
        self.assertFalse(app.blogposts.update_blogpost.execute("7101", PageChanges(title="T"), dry_run=True).payload["body"]["value"].count(ACCOUNT))

    def test_a_blog_post_without_people_has_nothing_to_blank(self):
        result = self.update.execute("7102", PageChanges(title="New"), dry_run=True)
        self.assertFalse(result.redacted)
        self.assertEqual(result.payload["title"], "New")

    def test_the_title_and_the_address_of_the_result_name_nobody(self):
        self.gateway.blogposts["7102"].title = "Notes of alex@example.com"
        self.gateway.blogposts["7102"].url = f"{BASE}/spaces/ENG/blog/2026/10/12/7102/Notes+of+alex%40example.com"
        for changes in (PageChanges(body="<p>x</p>"), PageChanges(title="Notes of alex@example.com")):
            result = self.update.execute("7102", changes, dry_run=True)
            with self.subTest(action=result.action):
                self.assertEqual(result.blogpost.title, "Notes of [email]")
                self.assertEqual(result.blogpost.url, f"{BASE}/spaces/ENG/blog/2026/10/12/7102")
        shown = self.update.execute("7102", PageChanges(body="<p>x</p>"), dry_run=True, with_users=True)
        self.assertEqual((shown.blogpost.title, shown.blogpost.url.endswith("%40example.com")), ("Notes of alex@example.com", True))


class AddressesAndTitlesTest(unittest.TestCase):
    """The title in a list, in a reading and in what a creation answers is redacted, and the address leaves it out when it holds an address of a person."""

    def setUp(self):
        self.gateway = FakeGateway()
        self.gateway.blogposts["7102"].title = "Mail alex@example.com"
        self.gateway.blogposts["7102"].url = f"{BASE}/spaces/ENG/blog/2026/10/12/7102/Mail+alex%40example.com"
        self.app, _, _ = app_for(self.gateway)

    def test_a_list_names_nobody(self):
        post = self.app.blogposts.list_blogposts.execute(space="ENG").blogposts[1]
        self.assertEqual((post.title, post.url), ("Mail [email]", f"{BASE}/spaces/ENG/blog/2026/10/12/7102"))
        plain = self.app.blogposts.list_blogposts.execute(space="ENG").blogposts[0]
        self.assertEqual(plain.url, f"{BASE}/spaces/ENG/blog/2026/10/12/7101/Release+2026.10+is+out")  # an address without a person is as it is

    def test_a_reading_names_nobody_unless_people_are_shown(self):
        view = self.app.blogposts.view_blogpost.execute("7102")
        self.assertEqual((view.page.title, view.page.url), ("Mail [email]", f"{BASE}/spaces/ENG/blog/2026/10/12/7102"))
        shown = self.app.blogposts.view_blogpost.execute("7102", with_users=True)
        self.assertEqual((shown.page.title, shown.page.url.endswith("Mail+alex%40example.com")), ("Mail alex@example.com", True))

    def test_what_a_creation_answers_names_nobody(self):
        original = self.gateway.create_blogpost

        def create(payload):
            post = original(payload)
            self.gateway.blogposts[post.id].url = f"{BASE}/spaces/ENG/blog/2026/10/15/{post.id}/Mail+alex%40example.com"
            return self.gateway.blogposts[post.id]

        self.gateway.create_blogpost = create
        result = self.app.blogposts.create_blogpost.execute(BlogpostDraft(space="ENG", title="Mail alex@example.com"))
        self.assertEqual(result.blogpost.title, "Mail [email]")
        self.assertEqual(result.blogpost.url, f"{BASE}/spaces/ENG/blog/2026/10/15/{result.blogpost.id}")
        self.assertEqual(self.gateway.called("create_blogpost")[0][1]["title"], "Mail alex@example.com")  # the title that was asked for is created as it is


if __name__ == "__main__":
    unittest.main()
