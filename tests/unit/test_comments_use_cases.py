"""The use cases around comments against the in-memory Confluence: the list with its filters, one comment, a change of the text and the resolution of an inline comment."""
import dataclasses
import unittest

from conflu_c_cli.domain.comments import author_ref
from conflu_c_cli.domain.errors import AuthError, ConflictError, NotFoundError, UnavailableError, UsageError, ValidationError
from conflu_c_cli.domain.model import Comment, User
from tests.support.fakes import ACCOUNT, ALEX, BASE, FakeGateway, RecordingDiagnostics, build_app, default_settings
from tests.support.fakes_comments import MENTION, OTHER, SAVED

PAGE = "2004"  # the page that `add_comment_fixtures` fills
TOKEN = "secret-token"
SITE = default_settings().wiki_url


def fresh() -> FakeGateway:
    gateway = FakeGateway()
    gateway.add_comment_fixtures()
    return gateway


def app_for(gateway=None, **settings):
    gateway = gateway or fresh()
    diagnostics = RecordingDiagnostics()
    return build_app(gateway=gateway, settings=default_settings(**settings), diagnostics=diagnostics), gateway, diagnostics


def ids(found) -> list[str]:
    return [view.comment.id for view in found.comments]


class Racing(FakeGateway):
    """Somebody else saves the comment between the first read of it and the write: the second read already shows the new version."""

    def get_comment(self, comment_id):
        if len(self.called("get_comment")) == 1:
            page_id, index, comment = self._find_comment(comment_id)
            self.comments[page_id][index] = dataclasses.replace(comment, version=comment.version + 1, updated="2026-10-15T09:00:00.000Z")
        return super().get_comment(comment_id)


class FindCommentsTest(unittest.TestCase):
    def setUp(self):
        self.app, self.gateway, self.diagnostics = app_for()

    def find(self, ref=PAGE, **options):
        return self.app.comments.find.execute(ref, **options)

    def test_the_footer_comments_come_as_conversations_each_root_followed_by_its_answers(self):
        found = self.find()
        self.assertEqual(ids(found), ["4100", "4101", "4106"])
        self.assertEqual([view.comment.parent_id for view in found.comments], ["", "4100", ""])
        self.assertEqual((found.page_id, found.total, found.since), (PAGE, 3, ""))

    def test_inline_adds_the_inline_conversations_behind_the_footer_ones(self):
        found = self.find(inline=True)
        self.assertEqual(ids(found), ["4100", "4101", "4106", "4102", "4107", "4103", "4104", "4105"])
        self.assertEqual(found.total, 8)

    def test_a_page_without_comments_is_an_empty_list_that_asks_nothing_about_the_user(self):
        found = self.find("2003")
        self.assertEqual((found.comments, found.total), ([], 0))
        self.assertEqual(self.gateway.called("current_user"), [])

    def test_every_comment_says_whether_it_is_yours_and_has_the_pseudonym_of_its_author(self):
        found = self.find(inline=True)
        by_id = {view.comment.id: view for view in found.comments}
        self.assertEqual((by_id["4100"].by_me, by_id["4101"].by_me, by_id["4107"].by_me), (False, True, False))
        mine, other = author_ref(TOKEN, SITE, ACCOUNT), author_ref(TOKEN, SITE, OTHER)
        self.assertEqual((by_id["4101"].author_ref, by_id["4100"].author_ref), (mine, other))
        self.assertNotEqual(mine, other)

    def test_the_user_of_the_token_is_asked_for_once_whatever_the_number_of_comments(self):
        self.find(inline=True)
        self.assertEqual(len(self.gateway.called("current_user")), 1)

    def test_without_a_token_there_is_no_pseudonym_and_the_comments_are_still_told_apart_by_byme(self):
        app, _, _ = app_for(api_token="")
        found = app.comments.find.execute(PAGE)
        self.assertEqual({view.author_ref for view in found.comments}, {None})
        self.assertEqual([view.by_me for view in found.comments], [False, True, True])

    def test_another_token_gives_another_pseudonym_and_the_same_token_the_same_one(self):
        first = [view.author_ref for view in self.find().comments]
        self.assertEqual(first, [view.author_ref for view in self.find().comments])
        other, _, _ = app_for(api_token="another-token")
        self.assertNotEqual(first, [view.author_ref for view in other.comments.find.execute(PAGE).comments])

    def test_when_the_user_cannot_be_read_byme_is_not_known_and_a_warning_says_so(self):
        self.gateway.errors["current_user"] = UnavailableError("Confluence is down.")
        found = self.find()
        self.assertEqual({view.by_me for view in found.comments}, {None})
        self.assertEqual(len(ids(found)), 3)
        self.assertEqual(self.diagnostics.warnings, ["Could not tell which comments are yours: Confluence is down."])

    def test_the_authors_and_the_people_in_the_text_stay_hidden_unless_people_are_asked_for(self):
        found = self.find()
        self.assertEqual({view.comment.author for view in found.comments}, {None})
        text = next(view for view in found.comments if view.comment.id == "4106").body.text
        self.assertIn("@user", text)
        self.assertIn("[email]", text)
        self.assertNotIn(ACCOUNT, text + "".join(view.body.text for view in found.comments))
        self.assertEqual(self.gateway.called("lookup_users"), [])

    def test_with_users_the_authors_are_named_and_the_mentions_are_shown(self):
        self.gateway.users = {ACCOUNT: ALEX}  # the other author is unknown to the lookup: only the id is there
        found = self.find(with_users=True)
        by_id = {view.comment.id: view for view in found.comments}
        self.assertEqual(by_id["4101"].comment.author.display_name, "Alex Example")
        self.assertEqual(by_id["4100"].comment.author, User(OTHER))
        self.assertIn("alex@example.com", by_id["4106"].body.text)
        self.assertEqual(self.gateway.called("lookup_users"), [("lookup_users", tuple(sorted({ACCOUNT, OTHER})))])

    def test_the_hide_users_policy_refuses_with_users_before_asking_confluence_anything(self):
        app, gateway, _ = app_for(hide_users=True)
        with self.assertRaises(ValidationError) as caught:
            app.comments.find.execute(PAGE, with_users=True)
        self.assertIn("CONFLUENCE_HIDE_USERS", caught.exception.message)
        self.assertEqual(gateway.calls, [])
        found = app.comments.find.execute(PAGE)  # the pseudonym and byMe are no people: they stay
        self.assertTrue(all(view.author_ref for view in found.comments))

    def test_a_relative_since_counts_back_from_now_and_keeps_what_was_saved_since(self):
        found = self.find(inline=True, since="2d")
        self.assertEqual(ids(found), ["4101", "4102", "4107"])
        self.assertEqual((found.total, found.since), (8, "2026-10-13T08:00:00+00:00"))

    def test_a_date_and_a_time_are_taken_as_they_are(self):
        self.assertEqual(ids(self.find(inline=True, since="2026-10-14")), ["4102", "4107"])
        self.assertEqual(ids(self.find(inline=True, since="2026-10-14T09:30:00Z")), ["4107"])
        self.assertEqual(ids(self.find(inline=True, since="2026-10-14T11:30:00+02:00")), ["4107"])  # 09:30 UTC
        self.assertEqual(ids(self.find(inline=True, since="2026-10-14T10:30:00+02:00")), ["4102", "4107"])  # 08:30 UTC
        self.assertEqual(ids(self.find(inline=True, since="2027-01-01")), [])

    def test_last_keeps_the_newest_comments_in_their_places(self):
        self.assertEqual(ids(self.find(inline=True, last=2)), ["4102", "4107"])
        self.assertEqual(ids(self.find(inline=True, last=1)), ["4107"])
        self.assertEqual(ids(self.find(inline=True, last=50)), ids(self.find(inline=True)))

    def test_last_looks_at_what_since_lets_through(self):
        self.assertEqual(ids(self.find(inline=True, since="2026-10-12", last=3)), ["4101", "4102", "4107"])
        self.assertEqual(ids(self.find(inline=True, since="2026-10-12", last=2)), ["4102", "4107"])

    def test_the_time_of_a_comment_is_when_it_was_saved_so_an_edit_makes_an_old_comment_recent(self):
        self.assertEqual(ids(self.find(inline=True, last=1)), ["4107"])
        self.app.comments.edit.execute(PAGE, "4103", "Fixed, really.")  # saved at SAVED, 2026-10-15T08:30
        self.assertEqual(ids(self.find(inline=True, last=1)), ["4103"])
        self.assertEqual(ids(self.find(inline=True, since="2026-10-15")), ["4103"])

    def test_a_resolution_asks_for_the_inline_conversations_in_that_state_with_their_answers(self):
        self.assertEqual(ids(self.find(resolution="open")), ["4102", "4107"])
        self.assertEqual(ids(self.find(resolution="resolved")), ["4103"])
        self.assertEqual(ids(self.find(resolution="dangling")), ["4104"])
        self.assertEqual(ids(self.find(resolution="reopened")), ["4105"])

    def test_a_resolution_leaves_the_footer_comments_out_and_does_not_ask_for_them(self):
        found = self.find(resolution="open", inline=True)
        self.assertEqual({view.comment.kind for view in found.comments}, {"inline"})
        self.assertEqual(self.gateway.called("list_comments"), [])
        self.assertEqual(self.gateway.called("list_inline_comments")[0][2], "open")

    def test_since_and_last_work_with_a_resolution(self):
        self.assertEqual(ids(self.find(resolution="open", last=1)), ["4107"])
        self.assertEqual(ids(self.find(resolution="resolved", since="2026-10-14")), [])

    def test_what_is_not_a_resolution_an_amount_or_a_time_is_a_usage_error_before_any_request(self):
        for options in ({"resolution": "closed"}, {"last": -1}, {"since": "yesterday"}, {"since": "2d 3h"}, {"since": ""}, {"since": "   "}):
            with self.subTest(options=options):
                with self.assertRaises(UsageError):
                    self.find(**options)
        self.assertEqual(self.gateway.calls, [])

    def test_a_since_that_is_given_and_empty_is_an_error_that_names_the_option_and_never_no_time(self):
        for value in ("", "   "):
            with self.subTest(since=value):
                with self.assertRaises(UsageError) as caught:
                    self.find(since=value)
                self.assertIn("--since", caught.exception.message)
        self.assertEqual(self.gateway.calls, [])
        self.assertEqual(len(ids(self.find(since=None))), 3)  # not given: everything

    def test_a_resolution_that_is_given_and_empty_is_an_error_that_names_the_option_and_never_no_filter(self):
        for value in ("", "closed", "x" * 5000):
            with self.subTest(resolution=value[:20]):
                with self.assertRaises(UsageError) as caught:
                    self.find(resolution=value)
                self.assertIn("--resolution", caught.exception.message)
                self.assertLess(len(caught.exception.message), 120)
                self.assertIn("open, resolved, reopened, dangling", caught.exception.hint)
        self.assertEqual(self.gateway.calls, [])
        self.assertEqual(ids(self.find(resolution=None)), ["4100", "4101", "4106"])  # not given: the footer comments, as without the option

    def test_a_format_of_the_text_that_does_not_exist_is_refused(self):
        with self.assertRaises(UsageError):
            self.find(body_format="html")

    def test_the_text_may_be_asked_for_as_storage_format_without_the_people_in_it(self):
        text = next(view for view in self.find(body_format="storage").comments if view.comment.id == "4106").body.text
        self.assertIn('ri:account-id="hidden"', text)
        self.assertNotIn(ACCOUNT, text)
        self.assertIn("[email]", text)

    def test_a_page_that_does_not_exist_is_not_found(self):
        with self.assertRaises(NotFoundError):
            self.find("999")

    def test_the_address_of_a_page_is_as_good_as_its_id(self):
        self.assertEqual(ids(self.find(f"{BASE}/spaces/ENG/pages/{PAGE}/ADR+0001")), ["4100", "4101", "4106"])


class GetCommentTest(unittest.TestCase):
    def setUp(self):
        self.app, self.gateway, _ = app_for()

    def get(self, comment_id, ref=PAGE, **options):
        return self.app.comments.get.execute(ref, comment_id, **options)

    def test_a_footer_comment(self):
        view = self.get("4101")
        comment = view.comment
        self.assertEqual((comment.id, comment.kind, comment.version, comment.updated, comment.parent_id), ("4101", "footer", 3, "2026-10-13T09:00:00.000Z", "4100"))
        self.assertEqual((view.body.text, view.by_me, comment.author), ("Will do.", True, None))
        self.assertEqual(view.author_ref, author_ref(TOKEN, SITE, ACCOUNT))

    def test_an_inline_comment_has_its_resolution(self):
        for comment_id, state in (("4102", "open"), ("4103", "resolved"), ("4104", "dangling"), ("4105", "reopened")):
            with self.subTest(comment=comment_id):
                self.assertEqual(self.get(comment_id).comment.resolution, state)

    def test_somebody_else_s_comment_is_not_yours(self):
        self.assertIs(self.get("4100").by_me, False)

    def test_with_users_the_author_is_named(self):
        self.assertEqual(self.get("4101", with_users=True).comment.author.display_name, "Alex Example")
        self.assertIsNone(self.get("4101").comment.author)

    def test_the_text_in_every_format_without_the_people(self):
        self.assertIn("@user", self.get("4106").body.text)
        self.assertIn("[email]", self.get("4106").body.text)
        self.assertIn('ri:account-id="hidden"', self.get("4106", body_format="storage").body.text)
        text = self.get("4106", body_format="text").body.text
        self.assertNotIn("alex@example.com", text)
        self.assertNotIn(ACCOUNT, text)

    def test_a_comment_of_another_page_is_as_good_as_none_and_is_not_told_apart(self):
        with self.assertRaises(NotFoundError) as caught:
            self.get("4102", ref="2002")
        error = caught.exception
        self.assertEqual(error.message, "No comment 4102 on page 2002.")
        self.assertEqual((error.details["pageId"], error.details["commentId"]), ("2002", "4102"))
        self.assertIn("conflu comments 2002 --inline --json", error.hint)

    def test_an_id_that_does_not_exist_is_not_found_and_names_the_page(self):
        with self.assertRaises(NotFoundError) as caught:
            self.get("9999")
        self.assertEqual(caught.exception.message, "No comment 9999 on page 2004.")
        self.assertEqual(caught.exception.exit_code, 4)

    def test_what_is_no_comment_id_is_refused_before_any_request(self):
        for text in ("", "abc", "4102/../4100", "4102 4100", "-1", "4102?x=1"):
            with self.subTest(text=text):
                with self.assertRaises(ValidationError):
                    self.get(text)
        self.assertEqual(self.gateway.calls, [])

    def test_an_empty_id_is_an_error_that_names_the_option_before_any_request(self):
        for text in ("", "   "):
            with self.assertRaises(ValidationError) as caught:
                self.get(text)
            self.assertEqual(caught.exception.message, "--get is empty: it needs the id of a comment.")
        self.assertEqual(self.gateway.calls, [])

    def test_the_hide_users_policy_refuses_with_users(self):
        app, gateway, _ = app_for(hide_users=True)
        with self.assertRaises(ValidationError):
            app.comments.get.execute(PAGE, "4101", with_users=True)
        self.assertEqual(gateway.calls, [])

    def test_the_default_comments_of_the_fake_are_readable_too(self):
        app, _, _ = app_for(FakeGateway())
        self.assertEqual(app.comments.get.execute("2002", "4003").comment.resolution, "open")


class EditCommentTest(unittest.TestCase):
    def setUp(self):
        self.app, self.gateway, self.diagnostics = app_for()

    def edit(self, comment_id, text, ref=PAGE, **options):
        return self.app.comments.edit.execute(ref, comment_id, text, **options)

    def sent(self):
        return self.gateway.called("update_comment")

    def stored(self, comment_id):
        return self.gateway._find_comment(comment_id)[2]

    def test_a_footer_comment_is_replaced_and_the_next_version_is_sent(self):
        change = self.edit("4101", "Done.")
        self.assertEqual((change.action, change.kind, change.version_from, change.version_to, change.dry_run), ("updated", "footer", 3, 4, False))
        self.assertEqual(change.payload, {"version": {"number": 4}, "body": {"representation": "storage", "value": "<p>Done.</p>"}})
        self.assertEqual(self.sent(), [("update_comment", "4101", "footer", change.payload)])
        self.assertEqual(self.stored("4101").body, "<p>Done.</p>")
        self.assertEqual(change.updated, SAVED)

    def test_the_diff_shows_the_old_and_the_new_text_as_markdown(self):
        change = self.edit("4101", "Done.")
        self.assertEqual(change.diff.splitlines()[:2], ["--- current", "+++ new"])
        self.assertIn("-Will do.", change.diff)
        self.assertIn("+Done.", change.diff)

    def test_an_inline_comment_keeps_its_state_whatever_it_is(self):
        for comment_id, resolved in (("4102", False), ("4105", False)):
            with self.subTest(comment=comment_id):
                change = self.edit(comment_id, "Changed.")
                self.assertIs(change.payload["resolved"], resolved)
                self.assertEqual(change.resolution, self.stored(comment_id).resolution)
        self.assertEqual(self.stored("4102").resolution, "open")
        self.assertEqual(self.stored("4105").resolution, "reopened")

    def test_a_resolved_comment_stays_resolved_when_its_text_changes(self):
        change = self.edit("4103", "Fixed, really.")
        self.assertIs(change.payload["resolved"], True)
        self.assertEqual((change.resolution, self.stored("4103").resolution), ("resolved", "resolved"))

    def test_a_footer_comment_sends_no_state(self):
        self.assertNotIn("resolved", self.edit("4101", "Done.").payload)

    def test_the_dry_run_sends_nothing_and_shows_what_would_be_sent(self):
        change = self.edit("4101", "Done.", dry_run=True)
        self.assertEqual((change.action, change.dry_run, change.version_from, change.version_to, change.by_me), ("updated", True, 3, 4, True))
        self.assertEqual(self.sent(), [])
        self.assertEqual(self.stored("4101").body, "<p>Will do.</p>")
        self.assertEqual(change.payload["body"]["value"], "<p>Done.</p>")
        self.assertEqual(change.warnings, [])

    def test_the_dry_run_warns_about_somebody_else_s_comment_and_still_sends_nothing(self):
        change = self.edit("4100", "Mine now.", dry_run=True)
        self.assertIs(change.by_me, False)
        self.assertEqual(len(change.warnings), 1)
        self.assertIn("Somebody else wrote this comment", change.warnings[0])
        self.assertEqual(self.sent(), [])

    def test_the_same_text_changes_nothing_and_sends_nothing(self):
        for text in ("Will do.", "Will do.\n", "Will do.\r\n\r\n"):
            with self.subTest(text=text):
                change = self.edit("4101", text)
                self.assertEqual((change.action, change.payload, change.version_from, change.version_to), ("unchanged", None, 3, 3))
        self.assertEqual(self.sent(), [])

    def test_the_same_text_in_storage_format_changes_nothing_either(self):
        self.assertEqual(self.edit("4101", "<p>Will do.</p>", body_format="storage").action, "unchanged")
        self.assertEqual(self.sent(), [])

    def test_the_dry_run_of_an_unchanged_text_says_so(self):
        change = self.edit("4101", "Will do.", dry_run=True)
        self.assertEqual((change.action, change.dry_run), ("unchanged", True))

    def test_what_a_reading_put_in_place_of_an_address_or_a_link_is_refused_and_nothing_is_sent(self):
        for text in ("Write to [email].", "See [personal link] for details.", "[email] and [personal link]"):
            with self.subTest(text=text):
                with self.assertRaises(ValidationError) as caught:
                    self.edit("4101", text)
                self.assertIn("overwrite the real one", caught.exception.message)
        with self.assertRaises(ValidationError):
            self.edit("4101", "Write to [email].", dry_run=True)
        self.assertEqual(self.sent(), [])

    def test_a_stand_in_that_the_comment_holds_already_is_not_refused(self):
        self.gateway.comments[PAGE].append(Comment("4190", "footer", "2026-10-11T09:00:00.000Z", "<p>The text says [email] on purpose.</p>", 1, self.gateway.user))
        self.assertEqual(self.edit("4190", "It still says [email] on purpose, but kinder.").action, "updated")

    def test_storage_format_with_blanked_mentions_is_refused(self):
        text = '<p>Ask <ac:link><ri:user ri:account-id="hidden" /></ac:link></p>'
        with self.assertRaises(ValidationError) as caught:
            self.edit("4101", text, body_format="storage")
        self.assertIn("account ids were hidden", caught.exception.message)
        self.assertEqual(self.sent(), [])

    def test_replacing_a_comment_that_holds_a_mention_with_markdown_is_refused_unless_forced(self):
        with self.assertRaises(ValidationError) as caught:
            self.edit("4106", "Plain words.")
        self.assertIn("mention", caught.exception.message)
        self.assertIn("mention", caught.exception.details["lost"])
        self.assertIn("--force", caught.exception.hint)
        self.assertEqual(self.sent(), [])
        change = self.edit("4106", "Plain words.", force=True)
        self.assertEqual((change.action, change.lost), ("updated", ("mention", "redacted-text")))
        self.assertEqual(self.stored("4106").body, "<p>Plain words.</p>")

    def test_the_dry_run_names_what_a_forced_replacement_loses(self):
        change = self.edit("4106", "Plain words.", force=True, dry_run=True)
        self.assertEqual(change.lost, ("mention", "redacted-text"))
        self.assertEqual(self.sent(), [])

    def test_storage_format_loses_nothing_and_needs_no_force(self):
        change = self.edit("4106", f"<p>Ask {MENTION} again.</p>", body_format="storage")
        self.assertEqual((change.action, change.lost), ("updated", ()))
        self.assertIn("ri:account-id", self.stored("4106").body)

    def test_an_empty_text_is_refused_for_a_comment_is_never_emptied(self):
        for text in ("", "   ", "\n\n"):
            with self.subTest(text=text):
                with self.assertRaises(ValidationError) as caught:
                    self.edit("4101", text)
                self.assertIn("neither deletes a comment nor empties one", caught.exception.hint)
        self.assertEqual(self.gateway.calls, [])

    def test_a_format_that_cannot_be_written_is_a_usage_error(self):
        for fmt in ("text", "html"):
            with self.assertRaises(UsageError):
                self.edit("4101", "Done.", body_format=fmt)

    def test_a_comment_of_another_page_or_none_is_not_found_and_nothing_is_sent(self):
        for ref, comment_id in (("2002", "4101"), (PAGE, "9999")):
            with self.assertRaises(NotFoundError):
                self.edit(comment_id, "Done.", ref=ref)
        self.assertEqual(self.sent(), [])

    def test_what_is_no_comment_id_is_refused_before_any_request(self):
        with self.assertRaises(ValidationError):
            self.edit("4101/../4100", "Done.")
        self.assertEqual(self.gateway.calls, [])

    def test_an_empty_id_is_an_error_that_names_the_option_before_any_request(self):
        for text in ("", "   "):
            with self.assertRaises(ValidationError) as caught:
                self.edit(text, "Done.")
            self.assertEqual(caught.exception.message, "--edit is empty: it needs the id of a comment.")
        self.assertEqual(self.gateway.calls, [])

    def test_a_dangling_comment_cannot_be_changed(self):
        with self.assertRaises(ValidationError) as caught:
            self.edit("4104", "Changed.")
        self.assertIn("dangling", caught.exception.message)
        self.assertIn("conflu comment 2004 --text", caught.exception.hint)
        self.assertEqual(self.sent(), [])

    def test_a_comment_saved_after_the_time_is_a_conflict_and_nothing_is_sent(self):
        with self.assertRaises(ConflictError) as caught:
            self.edit("4101", "Done.", if_unchanged_since="2026-10-12T08:00:00Z")
        self.assertEqual(caught.exception.exit_code, 3)
        self.assertEqual(caught.exception.details["commentId"], "4101")
        self.assertEqual(self.sent(), [])

    def test_a_comment_not_saved_after_the_time_is_changed(self):
        self.assertEqual(self.edit("4101", "Done.", if_unchanged_since="2026-10-13T09:00:00Z").action, "updated")

    def test_a_time_that_is_no_time_is_refused_before_any_request_and_a_guard_that_is_empty_is_not_dropped(self):
        for value in ("yesterday", "", "   "):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    self.edit("4101", "Done.", if_unchanged_since=value)
                with self.assertRaises(ValidationError):
                    self.app.comments.resolution.execute(PAGE, "4102", resolved=True, if_unchanged_since=value)
        self.assertEqual(self.gateway.calls, [])

    def test_an_empty_guard_names_the_option(self):
        for value in ("", "   "):
            with self.assertRaises(ValidationError) as caught:
                self.edit("4101", "Done.", if_unchanged_since=value)
            self.assertEqual(caught.exception.message, "--if-unchanged-since is empty: it needs a time.")
            self.assertIn("leave the option out", caught.exception.hint)
        self.assertEqual(self.gateway.calls, [])

    def test_the_guard_reads_the_comment_again_just_before_the_write(self):
        gateway = Racing()
        gateway.add_comment_fixtures()
        app, gateway, _ = app_for(gateway)
        with self.assertRaises(ConflictError) as caught:
            app.comments.edit.execute(PAGE, "4102", "Changed.", if_unchanged_since="2026-10-14T09:00:00Z")
        self.assertEqual(caught.exception.details["updated"], "2026-10-15T09:00:00+00:00")
        self.assertEqual(len(gateway.called("get_comment")), 2)
        self.assertEqual(gateway.called("update_comment"), [])

    def test_without_a_guard_the_comment_is_read_once_and_the_version_number_is_the_guard(self):
        self.edit("4101", "Done.")
        self.assertEqual(len(self.gateway.called("get_comment")), 1)

    def test_the_expected_version_is_checked_and_the_wrong_one_is_a_conflict(self):
        self.assertEqual(self.edit("4101", "Done.", if_version=3).action, "updated")
        with self.assertRaises(ConflictError) as caught:
            self.edit("4101", "Again.", if_version=3)  # it is at version 4 now
        self.assertEqual(caught.exception.details, {"pageId": PAGE, "commentId": "4101", "version": 4, "expected": 3})
        self.assertEqual(len(self.sent()), 1)

    def test_the_expected_version_is_checked_again_just_before_the_write(self):
        gateway = Racing()
        gateway.add_comment_fixtures()
        app, gateway, _ = app_for(gateway)
        with self.assertRaises(ConflictError) as caught:
            app.comments.edit.execute(PAGE, "4102", "Changed.", if_version=1)
        self.assertEqual((caught.exception.details["version"], caught.exception.details["expected"]), (2, 1))
        self.assertEqual(gateway.called("update_comment"), [])

    def test_a_version_below_one_is_a_usage_error_before_any_request(self):
        for number in (0, -3):
            with self.assertRaises(UsageError):
                self.edit("4101", "Done.", if_version=number)
        self.assertEqual(self.gateway.calls, [])

    def test_the_dry_run_checks_the_guards_too(self):
        with self.assertRaises(ConflictError):
            self.edit("4101", "Done.", if_version=1, dry_run=True)
        self.assertEqual(self.sent(), [])

    def test_a_conflict_that_confluence_reports_stays_a_conflict_and_says_what_to_do(self):
        self.gateway.errors["update_comment"] = ConflictError("Confluence reports a conflict (HTTP 409): Version conflict.", details={"status": 409})
        with self.assertRaises(ConflictError) as caught:
            self.edit("4101", "Done.")
        error = caught.exception
        self.assertEqual(error.exit_code, 3)
        self.assertEqual(error.message, "Confluence reports a conflict (HTTP 409): Version conflict.")
        self.assertEqual(error.details, {"status": 409, "pageId": PAGE, "commentId": "4101"})
        self.assertIn("conflu comment 2004 --get 4101", error.hint)

    def test_somebody_else_s_comment_is_refused_by_confluence_with_its_message_and_a_hint(self):
        with self.assertRaises(AuthError) as caught:
            self.edit("4100", "Mine now.")
        error = caught.exception
        self.assertEqual(error.exit_code, 5)
        self.assertIn("HTTP 403", error.message)
        self.assertIn("only their own comments", error.hint)
        self.assertIn("--reply-to", error.hint)
        self.assertEqual(self.stored("4100").body, "<p>Please review the decision.</p>")

    def test_a_refusal_of_the_credentials_has_no_hint_about_whose_comment_it_is(self):
        self.gateway.errors["update_comment"] = AuthError("Confluence did not accept the credentials (HTTP 401).", hint="Check the token.", details={"status": 401})
        with self.assertRaises(AuthError) as caught:
            self.edit("4101", "Done.")
        self.assertEqual(caught.exception.hint, "Check the token.")

    def test_a_404_for_a_comment_that_was_read_a_moment_ago_is_a_refusal_and_says_so(self):
        self.gateway.errors["update_comment"] = NotFoundError("Not found: PUT /api/v2/footer-comments/4101", hint="Confluence also answers 404 for what the account may not see.", details={"status": 404})
        with self.assertRaises(NotFoundError) as caught:
            self.edit("4101", "Done.")
        self.assertEqual(caught.exception.exit_code, 4)
        self.assertIn("forbidden from updating it", caught.exception.hint)
        self.assertEqual(caught.exception.details, {"status": 404})

    def test_any_other_failure_passes_unchanged(self):
        self.gateway.errors["update_comment"] = UnavailableError("Confluence is down.")
        with self.assertRaises(UnavailableError):
            self.edit("4101", "Done.")


class ResolveCommentTest(unittest.TestCase):
    def setUp(self):
        self.app, self.gateway, _ = app_for()

    def resolve(self, comment_id, ref=PAGE, resolved=True, **options):
        return self.app.comments.resolution.execute(ref, comment_id, resolved=resolved, **options)

    def sent(self):
        return self.gateway.called("update_comment")

    def stored(self, comment_id):
        return self.gateway._find_comment(comment_id)[2]

    def test_an_open_comment_is_resolved_with_its_own_text_unchanged(self):
        change = self.resolve("4102")
        self.assertEqual((change.action, change.kind, change.version_from, change.version_to, change.resolution), ("resolved", "inline", 1, 2, "resolved"))
        self.assertEqual(change.payload, {"version": {"number": 2}, "body": {"representation": "storage", "value": "<p>Is this still true?</p>"}, "resolved": True})
        self.assertEqual(self.sent(), [("update_comment", "4102", "inline", change.payload)])
        self.assertEqual((self.stored("4102").resolution, self.stored("4102").body), ("resolved", "<p>Is this still true?</p>"))

    def test_a_resolved_comment_is_reopened(self):
        change = self.resolve("4103", resolved=False)
        self.assertEqual((change.action, change.version_from, change.version_to, change.resolution), ("reopened", 2, 3, "reopened"))
        self.assertIs(change.payload["resolved"], False)
        self.assertEqual(self.stored("4103").resolution, "reopened")

    def test_a_comment_that_is_in_the_state_changes_nothing_and_sends_nothing(self):
        for comment_id, resolved, state in (("4103", True, "resolved"), ("4102", False, "open"), ("4105", False, "reopened")):
            with self.subTest(comment=comment_id, resolved=resolved):
                change = self.resolve(comment_id, resolved=resolved)
                self.assertEqual((change.action, change.payload, change.version_from, change.version_to, change.resolution), ("unchanged", None, change.version_from, change.version_from, state))
        self.assertEqual(self.sent(), [])

    def test_the_dry_run_sends_nothing_and_shows_the_payload_of_the_real_run(self):
        preview = self.resolve("4102", dry_run=True)
        self.assertEqual((preview.action, preview.dry_run, preview.version_to), ("resolved", True, 2))
        self.assertEqual(self.sent(), [])
        real = self.resolve("4102")
        self.assertEqual(real.payload, preview.payload)

    def test_the_request_that_is_shown_leaves_out_the_people_in_the_text_and_the_one_that_is_sent_does_not(self):
        body = f"<p>Ask {MENTION} or write to alex@example.com.</p>"
        self.gateway.comments[PAGE].append(Comment("4191", "inline", "2026-10-11T09:00:00.000Z", body, 1, self.gateway.user, "", "open"))
        preview = self.resolve("4191", dry_run=True)
        self.assertTrue(preview.redacted)
        self.assertIn('ri:account-id="hidden"', preview.payload["body"]["value"])
        self.assertNotIn("alex@example.com", preview.payload["body"]["value"])
        self.assertNotIn(ACCOUNT, str(preview.payload))
        self.assertEqual(self.sent(), [])
        real = self.resolve("4191")
        self.assertTrue(real.redacted)
        self.assertNotIn(ACCOUNT, str(real.payload))
        self.assertEqual(self.sent()[0][3]["body"]["value"], body)  # what is sent is the comment as it is
        self.assertEqual(self.stored("4191").body, body)

    def test_a_text_without_people_is_not_marked_as_redacted(self):
        self.assertFalse(self.resolve("4102", dry_run=True).redacted)
        self.assertFalse(self.resolve("4102").redacted)

    def test_with_users_the_request_is_shown_as_it_is(self):
        body = f"<p>Ask {MENTION} or write to alex@example.com.</p>"
        self.gateway.comments[PAGE].append(Comment("4191", "inline", "2026-10-11T09:00:00.000Z", body, 1, self.gateway.user, "", "open"))
        change = self.resolve("4191", dry_run=True, with_users=True)
        self.assertFalse(change.redacted)
        self.assertEqual(change.payload["body"]["value"], body)

    def test_the_hide_users_policy_refuses_with_users_before_any_request(self):
        app, gateway, _ = app_for(hide_users=True)
        with self.assertRaises(ValidationError) as caught:
            app.comments.resolution.execute(PAGE, "4102", resolved=True, with_users=True)
        self.assertIn("CONFLUENCE_HIDE_USERS", caught.exception.message)
        self.assertEqual(gateway.calls, [])
        self.assertEqual(app.comments.resolution.execute(PAGE, "4102", resolved=True, dry_run=True).action, "resolved")  # without --with-users it is no refusal

    def test_somebody_else_s_inline_comment_is_sent_back_with_its_own_text_so_no_text_of_theirs_is_changed(self):
        self.assertEqual(self.resolve("4107").action, "resolved")

    def test_a_footer_comment_is_a_usage_error_that_says_how_to_answer_it(self):
        with self.assertRaises(UsageError) as caught:
            self.resolve("4100")
        self.assertIn("only an inline comment can be resolved", caught.exception.message)
        self.assertIn("--reply-to 4100", caught.exception.hint)
        with self.assertRaises(UsageError) as caught:
            self.resolve("4100", resolved=False)
        self.assertIn("reopened", caught.exception.message)
        self.assertEqual(self.sent(), [])

    def test_a_dangling_comment_cannot_be_resolved_or_reopened(self):
        for resolved in (True, False):
            with self.assertRaises(ValidationError) as caught:
                self.resolve("4104", resolved=resolved)
            self.assertIn("dangling", caught.exception.message)
        self.assertEqual(self.sent(), [])

    def test_a_comment_of_another_page_is_not_found(self):
        with self.assertRaises(NotFoundError):
            self.resolve("4102", ref="2002")

    def test_what_is_no_comment_id_is_refused_before_any_request(self):
        with self.assertRaises(ValidationError):
            self.resolve("../4102")
        self.assertEqual(self.gateway.calls, [])

    def test_an_empty_id_is_an_error_that_names_the_option_that_was_used_before_any_request(self):
        for text in ("", "   "):
            with self.assertRaises(ValidationError) as caught:
                self.resolve(text, resolved=True)
            self.assertEqual(caught.exception.message, "--resolve is empty: it needs the id of a comment.")
            with self.assertRaises(ValidationError) as caught:
                self.resolve(text, resolved=False)
            self.assertEqual(caught.exception.message, "--reopen is empty: it needs the id of a comment.")
        self.assertEqual(self.gateway.calls, [])

    def test_the_guards_refuse_a_comment_that_has_moved_on_and_send_nothing(self):
        with self.assertRaises(ConflictError):
            self.resolve("4102", if_version=2)
        with self.assertRaises(ConflictError):
            self.resolve("4102", if_unchanged_since="2026-10-13T00:00:00Z")
        self.assertEqual(self.resolve("4102", if_version=1, if_unchanged_since="2026-10-14T09:00:00Z").action, "resolved")
        self.assertEqual(len(self.sent()), 1)

    def test_the_guard_reads_the_comment_again_just_before_the_write(self):
        gateway = Racing()
        gateway.add_comment_fixtures()
        app, gateway, _ = app_for(gateway)
        with self.assertRaises(ConflictError):
            app.comments.resolution.execute(PAGE, "4102", resolved=True, if_unchanged_since="2026-10-14T09:00:00Z")
        self.assertEqual(len(gateway.called("get_comment")), 2)
        self.assertEqual(gateway.called("update_comment"), [])

    def test_a_comment_that_somebody_resolved_meanwhile_is_left_alone(self):
        class Resolving(FakeGateway):
            def get_comment(self, comment_id):
                if len(self.called("get_comment")) == 1:
                    page_id, index, comment = self._find_comment(comment_id)
                    self.comments[page_id][index] = dataclasses.replace(comment, resolution="resolved")  # the same version: only the guard that is asked for can see it
                return super().get_comment(comment_id)

        gateway = Resolving()
        gateway.add_comment_fixtures()
        app, gateway, _ = app_for(gateway)
        change = app.comments.resolution.execute(PAGE, "4102", resolved=True, if_version=1)
        self.assertEqual((change.action, change.payload), ("unchanged", None))
        self.assertEqual(gateway.called("update_comment"), [])

    def test_a_conflict_a_refusal_and_a_missing_comment_from_confluence_get_a_hint(self):
        self.gateway.errors["update_comment"] = ConflictError("Confluence reports a conflict (HTTP 409).", details={"status": 409})
        with self.assertRaises(ConflictError) as caught:
            self.resolve("4102")
        self.assertIn("conflu comment 2004 --get 4102", caught.exception.hint)
        self.gateway.errors["update_comment"] = AuthError("Confluence refused this request (HTTP 403).", details={"status": 403})
        with self.assertRaises(AuthError) as caught:
            self.resolve("4102")
        self.assertIn("only their own comments", caught.exception.hint)


class AddCommentTest(unittest.TestCase):
    """Adding stays as it was: the new use cases did not touch it."""

    def setUp(self):
        self.app, self.gateway, _ = app_for()

    def test_a_comment_is_added_as_storage_format_with_its_parent(self):
        result = self.app.add_comment.execute(PAGE, "Looks fine.", reply_to="4100")
        # the document: the page is given for a comment on a page and the parent for a reply, not both
        self.assertEqual(result.payload, {"parentCommentId": "4100", "body": {"representation": "storage", "value": "<p>Looks fine.</p>"}})
        self.assertFalse(result.dry_run)
        self.assertTrue(result.comment_id)
        self.assertEqual(self.gateway.comments[PAGE][-1].parent_id, "4100")  # the reply is on the page of its parent

    def test_a_reply_reads_its_parent_first_and_the_parent_must_be_on_the_page(self):
        self.app.add_comment.execute(PAGE, "Looks fine.", reply_to="4100", dry_run=True)
        self.assertEqual(self.gateway.called("get_comment"), [("get_comment", "4100")])
        self.assertEqual(self.gateway.called("add_comment"), [])
        with self.assertRaises(NotFoundError) as caught:
            self.app.add_comment.execute("2002", "Looks fine.", reply_to="4100")  # a comment of page 2004
        self.assertIn("No comment 4100 on page 2002", caught.exception.message)
        with self.assertRaises(NotFoundError):
            self.app.add_comment.execute(PAGE, "Looks fine.", reply_to="9999", dry_run=True)
        self.assertEqual(self.gateway.called("add_comment"), [])

    def test_the_dry_run_checks_the_page_and_sends_nothing(self):
        result = self.app.add_comment.execute(PAGE, "Looks fine.", dry_run=True)
        self.assertEqual((result.dry_run, result.comment_id), (True, ""))
        self.assertEqual(self.gateway.called("add_comment"), [])
        with self.assertRaises(NotFoundError):
            self.app.add_comment.execute("999", "Looks fine.", dry_run=True)

    def test_an_empty_text_and_a_parent_that_is_no_id_are_refused(self):
        with self.assertRaises(ValidationError):
            self.app.add_comment.execute(PAGE, "  ")
        with self.assertRaises(ValidationError):
            self.app.add_comment.execute(PAGE, "Text", reply_to="4100/../1")
        self.assertEqual(self.gateway.called("add_comment"), [])

    def test_a_parent_that_is_given_and_empty_is_an_error_that_names_the_option_and_never_a_comment_of_its_own(self):
        for value in ("", "   "):
            for dry_run in (False, True):
                with self.subTest(reply_to=value, dry_run=dry_run):
                    with self.assertRaises(ValidationError) as caught:
                        self.app.add_comment.execute(PAGE, "Looks fine.", reply_to=value, dry_run=dry_run)
                    self.assertEqual(caught.exception.message, "--reply-to is empty: it needs the id of a comment.")
                    self.assertIn("Leave --reply-to out", caught.exception.hint)
        self.assertEqual(self.gateway.calls, [])  # nothing was read and nothing was sent
        own = self.app.add_comment.execute(PAGE, "Looks fine.", reply_to=None)  # not given: a comment of its own
        self.assertEqual(own.payload["pageId"], PAGE)
        self.assertNotIn("parentCommentId", own.payload)


if __name__ == "__main__":
    unittest.main()
