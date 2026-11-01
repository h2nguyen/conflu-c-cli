"""Comments, the real program against the mock Confluence: the requests that are sent, the conflict guards, the people, hostile input."""
import json
import tempfile
import unittest
from pathlib import Path

from conflu_c_cli.domain.comments import author_ref
from tests.integration.test_end_to_end import ACCOUNT, EndToEnd
from tests.support.mock_comments import OTHER, CommentsRoutes
from tests.support.mock_confluence import MockConfluence

PAGE = "2004"  # the page that `add_fixtures` fills with the comments 4100 to 4107
PEOPLE = (ACCOUNT, OTHER, "alex@example.com", "Alex Example")  # what never shows without --with-users
BARE = frozenset({"/api/v2/users-bulk"})  # a POST that reads


class CommentsFlow(EndToEnd):
    def setUp(self):
        super().setUp()
        self.area = self.mock.area(CommentsRoutes)
        self.area.add_fixtures()

    def writes(self):
        return [item for item in self.mock.requests if item.method != "GET" and item.path not in BARE]

    def stored(self, comment_id):
        return self.mock.comments[comment_id]

    def paths(self, method="GET"):
        return [item.path for item in self.mock.requests if item.method == method]

    def work(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        return Path(folder.name)

    def ok(self, *argv, **options):
        result = self.cli(*argv, **options)
        self.assertEqual(result.code, 0, result.err)
        return result


class ListTest(CommentsFlow):
    def test_the_comments_of_a_page_are_asked_for_in_pieces_with_their_answers_and_the_user_once(self):
        data = self.ok("comments", PAGE, "--inline", "--json").json()
        self.assertEqual(sorted(item["id"] for item in data["comments"]), ["4100", "4101", "4102", "4103", "4104", "4105", "4106", "4107"])
        self.assertEqual((data["total"], data["count"]), (8, 8))
        paths = self.paths()
        self.assertEqual([path for path in paths if path.startswith("/api/v2/pages/")], ["/api/v2/pages/2004/footer-comments", "/api/v2/pages/2004/inline-comments", "/api/v2/pages/2004/inline-comments"])  # the mock gives two at a time
        self.assertEqual(sorted(path for path in paths if path.endswith("/children")), sorted([f"/api/v2/footer-comments/{item}/children" for item in ("4100", "4106")] + [f"/api/v2/inline-comments/{item}/children" for item in ("4102", "4103", "4104", "4105")]))
        self.assertEqual(paths.count("/rest/api/user/current"), 1)
        self.assertEqual(self.writes(), [])

    def test_every_request_of_the_list_asks_for_storage_format_and_the_biggest_pieces(self):
        self.ok("comments", PAGE, "--inline")
        for item in self.mock.requests:
            if item.path.startswith("/api/v2/"):
                with self.subTest(path=item.path):
                    self.assertEqual(item.query["body-format"], ["storage"])
                    self.assertEqual(item.query["limit"], ["100"])
                    self.assertEqual(item.query["sort"], ["created-date"])
                    self.assertNotIn("resolution-status", item.query)

    def test_a_resolution_is_the_filter_of_the_api_and_asks_the_inline_comments_only(self):
        data = self.ok("comments", PAGE, "--resolution", "reopened", "--json").json()
        self.assertEqual([item["id"] for item in data["comments"]], ["4105"])
        asked = [item for item in self.mock.requests if item.path == "/api/v2/pages/2004/inline-comments"]
        self.assertEqual([item.query["resolution-status"] for item in asked], [["reopened"]])
        self.assertEqual([path for path in self.paths() if "footer-comments" in path], [])
        for state, wanted in (("open", ["4102", "4107"]), ("resolved", ["4103"]), ("dangling", ["4104"])):
            with self.subTest(state=state):
                self.assertEqual(sorted(item["id"] for item in self.ok("comments", PAGE, "--resolution", state, "--json").json()["comments"]), wanted)

    def test_since_names_a_date_and_last_the_newest(self):
        self.assertEqual(sorted(item["id"] for item in self.ok("comments", PAGE, "--inline", "--since", "2026-10-13", "--json").json()["comments"]), ["4101", "4102", "4107"])
        self.assertEqual([item["id"] for item in self.ok("comments", PAGE, "--inline", "--last", "1", "--json").json()["comments"]], ["4107"])
        everything = self.ok("comments", PAGE, "--inline", "--since", "5000w", "--json").json()  # a time ago that reaches back before any comment, whatever today is
        self.assertEqual((everything["count"], everything["since"] is not None), (8, True))

    def test_an_edit_makes_a_comment_recent_for_it_is_saved_again(self):
        self.ok("comment", PAGE, "--edit", "4103", "--text", "Fixed, really.")
        data = self.ok("comments", PAGE, "--inline", "--since", "2026-10-15", "--json").json()
        self.assertEqual([item["id"] for item in data["comments"]], ["4103"])
        self.assertEqual(data["comments"][0]["updated"], self.stored("4103")["version"]["createdAt"])

    def test_a_resolution_filter_follows_the_cursor_of_the_answer_and_keeps_asking_for_the_same_state(self):
        for number in range(4):
            self.mock.add_comment(PAGE, f"<p>Open {number}.</p>", kind="inline")
        data = self.ok("comments", PAGE, "--resolution", "open", "--json").json()
        self.assertEqual(len([item for item in data["comments"] if not item["parentId"]]), 5)  # four new ones and 4102
        asked = [item for item in self.mock.requests if item.path == "/api/v2/pages/2004/inline-comments"]
        self.assertEqual(len(asked), 3)  # five roots, two at a time
        self.assertTrue(all(item.query["resolution-status"] == ["open"] for item in asked))
        self.assertIsNone(asked[0].query.get("cursor"))
        self.assertTrue(asked[1].query["cursor"] and asked[2].query["cursor"])

    def test_a_comment_whose_author_is_not_known_has_no_pseudonym_and_no_byme_and_is_no_failure(self):
        self.stored("4100")["authorId"] = None
        data = self.ok("comments", PAGE, "--json").json()
        unknown = next(item for item in data["comments"] if item["id"] == "4100")
        self.assertEqual((unknown["author"], unknown["authorRef"], unknown["byMe"]), (None, None, None))
        self.assertIn("--- #4100 footer", self.ok("comments", PAGE).out)

    def test_the_pseudonym_is_the_keyed_hash_of_the_account_and_stays_the_same_from_run_to_run(self):
        first = self.ok("comments", PAGE, "--json").json()["comments"]
        again = self.ok("comments", PAGE, "--json").json()["comments"]
        self.assertEqual([item["authorRef"] for item in first], [item["authorRef"] for item in again])
        by_id = {item["id"]: item for item in first}
        self.assertEqual(by_id["4101"]["authorRef"], author_ref(self.mock.token, self.mock.base_url, ACCOUNT))
        self.assertEqual(by_id["4100"]["authorRef"], author_ref(self.mock.token, self.mock.base_url, OTHER))
        self.assertEqual((by_id["4100"]["byMe"], by_id["4101"]["byMe"]), (False, True))
        self.assertNotEqual(by_id["4100"]["authorRef"], by_id["4101"]["authorRef"])

    def test_another_site_and_token_give_other_pseudonyms_for_the_same_account(self):
        other = MockConfluence(token="another-token")
        other.start()
        self.addCleanup(other.stop)
        other.area(CommentsRoutes).add_fixtures()
        env = {"CONFLUENCE_BASE_URL": other.base_url, "CONFLUENCE_EMAIL": other.email, "CONFLUENCE_API_TOKEN": "another-token"}
        here = {item["id"]: item["authorRef"] for item in self.ok("comments", PAGE, "--json").json()["comments"]}
        there = {item["id"]: item["authorRef"] for item in self.ok("comments", PAGE, "--json", env=env).json()["comments"]}
        self.assertEqual(set(here), set(there))
        self.assertTrue(all(here[key] != there[key] for key in here))

    def test_no_person_shows_without_with_users_in_any_form_of_the_list(self):
        for argv in (
            ("comments", PAGE, "--inline"),
            ("comments", PAGE, "--inline", "--json"),
            ("comments", PAGE, "--inline", "--format", "storage"),
            ("comments", PAGE, "--inline", "--format", "text", "--json"),
            ("comments", PAGE, "--inline", "--list-format", "tsv"),
            ("comments", PAGE, "--inline", "--select", "id,author,authorRef,byMe,body.value", "--json"),
            ("comment", PAGE, "--get", "4106"),
            ("comment", PAGE, "--get", "4106", "--format", "storage", "--json"),
            ("comment", PAGE, "--get", "4100", "--json"),
        ):
            with self.subTest(argv=argv):
                result = self.ok(*argv)
                for hidden in PEOPLE:
                    self.assertNotIn(hidden, result.out + result.err)
        self.assertEqual([item for item in self.mock.requests if item.path == "/api/v2/users-bulk"], [])

    def test_with_users_asks_for_the_names_once_and_shows_them(self):
        data = self.ok("comments", PAGE, "--with-users", "--json").json()
        lookups = [item for item in self.mock.requests if item.path == "/api/v2/users-bulk"]
        self.assertEqual([item.body for item in lookups], [{"accountIds": sorted([ACCOUNT, OTHER])}])
        mine = next(item for item in data["comments"] if item["id"] == "4101")
        self.assertEqual(mine["author"]["displayName"], "Alex Example")
        self.assertEqual(next(item for item in data["comments"] if item["id"] == "4100")["author"], {"accountId": OTHER, "displayName": "", "email": ""})

    def test_the_hide_users_policy_refuses_with_users_before_any_request_and_keeps_the_pseudonyms(self):
        env = {"CONFLUENCE_HIDE_USERS": "true"}
        refused = self.cli("comments", PAGE, "--with-users", env=env)
        self.assertEqual(refused.code, 1)
        self.assertIn("CONFLUENCE_HIDE_USERS", refused.err)
        self.assertEqual(self.mock.requests, [])
        data = self.ok("comments", PAGE, "--json", env=env).json()
        self.assertTrue(all(item["authorRef"] and item["author"] is None for item in data["comments"]))
        refused_one = self.cli("comment", PAGE, "--get", "4101", "--with-users", env=env)
        self.assertEqual(refused_one.code, 1)

    def test_bad_options_are_refused_before_any_request(self):
        for argv in (("--since", "2d&limit=1"), ("--since", "yesterday"), ("--last", "0"), ("--since", "9" * 40 + "w")):
            with self.subTest(argv=argv):
                result = self.cli("comments", PAGE, *argv)
                self.assertEqual(result.code, 2)
        self.assertEqual(self.mock.requests, [])

    def test_a_page_that_does_not_exist_is_exit_code_4_and_its_comments_are_not_asked_for(self):
        result = self.cli("comments", "9999")
        self.assertEqual(result.code, 4)
        self.assertEqual(self.paths(), ["/api/v2/pages/9999/footer-comments"])

    def test_no_call_is_one_that_the_documents_do_not_know(self):
        self.ok("comments", PAGE, "--inline", "--with-users")
        self.ok("comments", PAGE, "--resolution", "open")
        self.assertEqual((self.mock.unknown_endpoints, self.mock.deprecated_endpoints), ([], []))
        v1 = {call for call in self.mock.used_endpoints if "/rest/api/" in call}
        self.assertEqual(v1, {"GET /rest/api/user/current"})


class GetTest(CommentsFlow):
    def test_a_footer_comment_is_found_by_the_first_request(self):
        data = self.ok("comment", PAGE, "--get", "4100", "--json").json()
        self.assertEqual((data["id"], data["kind"], data["version"], data["parentId"], data["resolution"]), ("4100", "footer", 1, None, None))
        self.assertEqual(self.paths(), ["/api/v2/footer-comments/4100", "/rest/api/user/current"])

    def test_an_inline_comment_is_found_by_the_second_request_after_a_404_of_the_first(self):
        data = self.ok("comment", PAGE, "--get", "4102", "--json").json()
        self.assertEqual((data["kind"], data["resolution"], data["byMe"]), ("inline", "open", True))
        self.assertEqual(self.paths(), ["/api/v2/footer-comments/4102", "/api/v2/inline-comments/4102", "/rest/api/user/current"])
        for item in self.mock.requests[:2]:
            self.assertEqual(item.query, {"body-format": ["storage"]})

    def test_a_reply_names_its_parent_and_every_state_of_an_inline_comment_is_read(self):
        self.assertEqual(self.ok("comment", PAGE, "--get", "4101", "--json").json()["parentId"], "4100")
        for comment_id, state in (("4103", "resolved"), ("4104", "dangling"), ("4105", "reopened")):
            with self.subTest(comment=comment_id):
                self.assertEqual(self.ok("comment", PAGE, "--get", comment_id, "--json").json()["resolution"], state)

    def test_a_comment_of_another_page_or_none_is_exit_code_4_and_costs_two_requests(self):
        for page, comment_id in (("2002", "4102"), (PAGE, "9999")):
            with self.subTest(page=page, comment=comment_id):
                self.mock.requests.clear()
                result = self.cli("comment", page, "--get", comment_id)
                self.assertEqual(result.code, 4)
                self.assertIn(f"No comment {comment_id} on page {page}.", result.err)
                self.assertEqual(self.paths(), [f"/api/v2/footer-comments/{comment_id}", f"/api/v2/inline-comments/{comment_id}"])

    def test_an_id_that_is_not_a_number_never_reaches_the_server(self):
        for text in ("4102/../4100", "4102?x=1", "4102#a", "4102 4100", "../footer-comments", "%2e%2e", "", "٤١٠٢", "9" * 30):
            with self.subTest(text=text):
                self.assertEqual(self.cli("comment", PAGE, "--get", text).code, 1)
        self.assertEqual(self.mock.requests, [])

    def test_a_page_that_is_no_page_never_reaches_the_server_either(self):
        for text in ("2004/../2002", "abc", "", "2004;"):
            with self.subTest(page=text):
                self.assertEqual(self.cli("comment", text, "--get", "4102").code, 1)
        self.assertEqual(self.mock.requests, [])

    def test_the_address_of_the_page_is_as_good_as_its_id(self):
        address = f"{self.mock.base_url}/spaces/ENG/pages/{PAGE}/ADR+0001"
        self.assertEqual(self.ok("comment", address, "--get", "4102", "--json").json()["pageId"], PAGE)

    def test_the_text_is_in_the_format_asked_for_without_the_people_unless_they_are_asked_for(self):
        shown = self.ok("comment", PAGE, "--get", "4106", "--format", "storage", "--json").json()["body"]["value"]
        self.assertIn('ri:account-id="hidden"', shown)
        self.assertNotIn(ACCOUNT, shown)
        with_people = self.ok("comment", PAGE, "--get", "4106", "--format", "storage", "--with-users", "--json").json()["body"]["value"]
        self.assertIn(f'ri:account-id="{ACCOUNT}"', with_people)


class EditTest(CommentsFlow):
    def test_the_text_of_an_inline_comment_is_replaced_and_its_state_is_kept(self):
        result = self.ok("comment", PAGE, "--edit", "4102", "--text", "Still true in 2.1.", "--json").json()
        self.assertEqual((result["action"], result["versionFrom"], result["versionTo"], result["dryRun"]), ("updated", 1, 2, False))
        puts = self.sent("PUT", "/api/v2/")
        self.assertEqual([item.path for item in puts], ["/api/v2/inline-comments/4102"])
        self.assertEqual(puts[0].body, {"version": {"number": 2}, "body": {"representation": "storage", "value": "<p>Still true in 2.1.</p>"}, "resolved": False})
        self.assertEqual(self.writes(), puts)
        shown = self.ok("comment", PAGE, "--get", "4102", "--json").json()
        self.assertEqual((shown["version"], shown["resolution"], shown["body"]["value"]), (2, "open", "Still true in 2.1."))
        self.assertEqual(shown["updated"], result["updated"])

    def test_a_resolved_comment_stays_resolved_when_its_text_changes(self):
        self.ok("comment", PAGE, "--edit", "4103", "--text", "Fixed, really.")
        self.assertEqual(self.sent("PUT", "/api/v2/")[0].body["resolved"], True)
        self.assertEqual(self.stored("4103")["resolutionStatus"], "resolved")

    def test_a_footer_comment_is_replaced_by_the_next_version_and_sends_no_state(self):
        self.ok("comment", PAGE, "--edit", "4101", "--text", "Done.")
        put = self.sent("PUT", "/api/v2/")[0]
        self.assertEqual(put.path, "/api/v2/footer-comments/4101")
        self.assertEqual(put.body, {"version": {"number": 4}, "body": {"representation": "storage", "value": "<p>Done.</p>"}})
        self.assertEqual(self.paths("GET")[:1], ["/api/v2/footer-comments/4101"])  # the comment is read first, and only the footer collection is asked

    def test_the_comment_is_read_first_and_the_dry_run_reads_and_writes_nothing(self):
        result = self.ok("comment", PAGE, "--edit", "4101", "--text", "Done.", "--dry-run", "--json").json()
        self.assertEqual((result["dryRun"], result["action"], result["versionTo"]), (True, "updated", 4))
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.stored("4101")["body"], "<p>Will do.</p>")
        self.assertEqual(self.stored("4101")["version"]["number"], 3)
        self.assertIn("-Will do.", result["diff"])

    def test_the_request_of_the_real_run_is_the_payload_of_the_dry_run(self):
        preview = self.ok("comment", PAGE, "--edit", "4102", "--text", "Changed.", "--dry-run", "--json").json()["payload"]
        self.ok("comment", PAGE, "--edit", "4102", "--text", "Changed.", "--json")
        self.assertEqual([item.body for item in self.sent("PUT", "/api/v2/")], [preview])

    def test_the_same_text_sends_nothing(self):
        for text in ("Will do.", "Will do.\n"):
            result = self.ok("comment", PAGE, "--edit", "4101", "--text", text, "--json").json()
            self.assertEqual((result["action"], result["payload"]), ("unchanged", None))
        self.assertEqual(self.writes(), [])

    def test_the_text_may_come_from_a_file_and_from_standard_input(self):
        path = self.work() / "new.md"
        path.write_text("# Heading\n\nFrom a file.\n", encoding="utf-8")
        self.ok("comment", PAGE, "--edit", "4101", "--file", str(path))
        self.assertIn("<h1>Heading</h1>", self.stored("4101")["body"])
        self.assertIn("<p>From a file.</p>", self.stored("4101")["body"])
        self.ok("comment", PAGE, "--edit", "4101", "--file", "-", stdin="From a pipe.\n")
        self.assertEqual(self.stored("4101")["body"], "<p>From a pipe.</p>")

    def test_a_file_that_is_no_text_is_refused_and_nothing_is_sent(self):
        path = self.work() / "picture.bin"
        path.write_bytes(b"\x89PNG\x00\x01\x02")
        result = self.cli("comment", PAGE, "--edit", "4101", "--file", str(path))
        self.assertEqual(result.code, 1)
        self.assertEqual(self.writes(), [])

    def test_somebody_else_s_comment_is_refused_by_confluence_and_stays_as_it_was(self):
        result = self.cli("comment", PAGE, "--edit", "4100", "--text", "Mine now.")
        self.assertEqual(result.code, 5)
        self.assertIn("HTTP 403", result.err)
        self.assertIn("Only the author of a comment can change its text", result.err)
        self.assertIn("only their own comments", result.err)
        self.assertEqual(self.stored("4100")["body"], "<p>Please review the decision.</p>")
        self.assertEqual(self.stored("4100")["version"]["number"], 1)
        self.assertEqual(len(self.sent("PUT", "/api/v2/")), 1)  # it was tried once: a write is never repeated

    def test_the_dry_run_on_somebody_else_s_comment_warns_and_sends_nothing(self):
        result = self.ok("comment", PAGE, "--edit", "4100", "--text", "Mine now.", "--dry-run")
        self.assertIn("WARNING: Somebody else wrote this comment", result.err)
        self.assertEqual(self.writes(), [])

    def test_a_conflict_of_confluence_is_exit_code_3_and_the_comment_is_not_written(self):
        self.mock.fail_next("/api/v2/footer-comments/4101", 409, method="PUT", body={"errors": [{"status": 409, "title": "Conflict", "detail": "Version conflict"}]})
        result = self.cli("comment", PAGE, "--edit", "4101", "--text", "Done.", "--json")
        self.assertEqual(result.code, 3)
        error = json.loads(result.err.strip().splitlines()[-1])["error"]
        self.assertEqual((error["code"], error["details"]["status"], error["details"]["commentId"]), ("CONFLICT", 409, "4101"))
        self.assertIn("conflu comment 2004 --get 4101", error["hint"])
        self.assertEqual(self.stored("4101")["body"], "<p>Will do.</p>")

    def test_a_404_for_a_comment_that_was_read_is_exit_code_4_with_the_reason_it_may_have(self):
        self.mock.fail_next("/api/v2/footer-comments/4101", 404, method="PUT")
        result = self.cli("comment", PAGE, "--edit", "4101", "--text", "Done.")
        self.assertEqual(result.code, 4)
        self.assertIn("forbidden from updating it", result.err)

    def test_the_version_that_is_sent_is_the_one_that_was_just_read_plus_one(self):
        self.stored("4101")["version"]["number"] = 7  # the comment has been saved a few times since the fixture was written
        self.ok("comment", PAGE, "--edit", "4101", "--text", "Done.")
        self.assertEqual(self.sent("PUT", "/api/v2/")[0].body["version"]["number"], 8)

    def test_the_guards_refuse_a_comment_that_moved_on_before_anything_is_sent(self):
        for option, value in (("--if-version", "2"), ("--if-unchanged-since", "2026-10-12T00:00:00Z")):
            with self.subTest(option=option):
                result = self.cli("comment", PAGE, "--edit", "4101", "--text", "Done.", option, value)
                self.assertEqual(result.code, 3, result.err)
        self.assertEqual(self.writes(), [])

    def test_a_guard_that_holds_reads_the_comment_again_just_before_the_write(self):
        self.ok("comment", PAGE, "--edit", "4101", "--text", "Done.", "--if-version", "3", "--if-unchanged-since", "2026-10-13T09:00:00Z")
        order = [(item.method, item.path) for item in self.mock.requests]
        self.assertEqual(order, [("GET", "/api/v2/footer-comments/4101"), ("GET", "/api/v2/footer-comments/4101"), ("PUT", "/api/v2/footer-comments/4101")])

    def test_what_a_reading_put_in_place_of_an_address_is_refused_even_in_a_dry_run(self):
        for argv in (("--text", "Write to [email]."), ("--text", "See [personal link].", "--dry-run")):
            with self.subTest(argv=argv):
                self.assertEqual(self.cli("comment", PAGE, "--edit", "4101", *argv).code, 1)
        self.assertEqual(self.writes(), [])

    def test_blanked_mentions_in_storage_format_are_refused(self):
        text = '<p>Ask <ac:link><ri:user ri:account-id="hidden" /></ac:link></p>'
        self.assertEqual(self.cli("comment", PAGE, "--edit", "4101", "--format", "storage", "--text", text).code, 1)
        self.assertEqual(self.writes(), [])

    def test_a_mention_is_not_replaced_by_markdown_unless_forced_and_the_real_text_is_what_is_kept_otherwise(self):
        self.assertEqual(self.cli("comment", PAGE, "--edit", "4106", "--text", "Plain.").code, 1)
        self.assertEqual(self.writes(), [])
        self.ok("comment", PAGE, "--edit", "4106", "--text", "Plain.", "--force")
        self.assertEqual(self.stored("4106")["body"], "<p>Plain.</p>")

    def test_a_comment_that_holds_a_mention_is_changed_in_storage_format_with_the_mention_kept(self):
        mention = f'<ac:link><ri:user ri:account-id="{ACCOUNT}" /></ac:link>'
        self.ok("comment", PAGE, "--edit", "4106", "--format", "storage", "--text", f"<p>Ask {mention} instead.</p>")
        self.assertIn(f'ri:account-id="{ACCOUNT}"', self.stored("4106")["body"])

    def test_an_empty_text_and_a_dangling_comment_are_refused_before_a_write(self):
        self.assertEqual(self.cli("comment", PAGE, "--edit", "4101", "--text", "  ").code, 1)
        self.assertEqual(self.cli("comment", PAGE, "--edit", "4104", "--text", "Changed.").code, 1)
        self.assertEqual(self.writes(), [])

    def test_hostile_text_is_stored_as_text_and_never_as_markup(self):
        hostile = "</p><script>alert(1)</script><ac:structured-macro ac:name=\"html\"/> & ]]> <!-- x --> \u202e"
        self.ok("comment", PAGE, "--edit", "4101", "--text", hostile)
        body = self.stored("4101")["body"]
        for markup in ("<script", "<ac:structured-macro", "<!--"):
            self.assertNotIn(markup, body)
        self.assertIn("&lt;script&gt;", body)

    def test_a_long_text_is_sent_whole(self):
        text = " ".join(["word"] * 20000)
        self.ok("comment", PAGE, "--edit", "4101", "--text", text)
        self.assertEqual(self.stored("4101")["body"], f"<p>{text}</p>")

    def test_the_credentials_and_the_people_stay_out_of_what_a_refusal_says(self):
        body = {"errors": [{"status": 403, "title": "Forbidden", "detail": f"{self.mock.token} {self.mock.email} alex@example.com"}]}
        self.mock.fail_next("/api/v2/footer-comments/4101", 403, method="PUT", body=body)
        result = self.cli("comment", PAGE, "--edit", "4101", "--text", "Done.", "--json", env={"CONFLUENCE_HIDE_USERS": "true"})
        self.assertEqual(result.code, 5)
        for secret in (self.mock.token, self.mock.email, "alex@example.com"):
            self.assertNotIn(secret, result.err + result.out)
        self.assertIn("[email]", result.err)

    def test_every_call_is_one_that_the_documents_know_and_the_only_v1_call_is_the_user_of_the_token(self):
        self.ok("comment", PAGE, "--edit", "4102", "--text", "Changed.", "--dry-run")
        self.ok("comment", PAGE, "--edit", "4102", "--text", "Changed.")
        self.assertEqual((self.mock.unknown_endpoints, self.mock.deprecated_endpoints), ([], []))
        self.assertEqual({call for call in self.mock.used_endpoints if "/rest/api/" in call}, {"GET /rest/api/user/current"})
        self.assertIn("PUT /api/v2/inline-comments/{comment-id}", self.mock.used_endpoints)


class ResolveTest(CommentsFlow):
    def test_an_open_comment_is_resolved_with_its_own_text_and_read_again_as_resolved(self):
        result = self.ok("comment", PAGE, "--resolve", "4102", "--json").json()
        self.assertEqual((result["action"], result["versionFrom"], result["versionTo"], result["resolution"]), ("resolved", 1, 2, "resolved"))
        put = self.sent("PUT", "/api/v2/")[0]
        self.assertEqual(put.path, "/api/v2/inline-comments/4102")
        self.assertEqual(put.body, {"version": {"number": 2}, "body": {"representation": "storage", "value": "<p>Is this still true?</p>"}, "resolved": True})
        self.assertEqual(self.ok("comment", PAGE, "--get", "4102", "--json").json()["resolution"], "resolved")
        self.assertEqual(self.stored("4102")["body"], "<p>Is this still true?</p>")

    def test_a_resolved_comment_is_reopened(self):
        result = self.ok("comment", PAGE, "--reopen", "4103", "--json").json()
        self.assertEqual((result["action"], result["resolution"]), ("reopened", "reopened"))
        self.assertIs(self.sent("PUT", "/api/v2/")[0].body["resolved"], False)
        self.assertEqual(self.stored("4103")["resolutionStatus"], "reopened")

    def test_a_comment_that_is_in_the_state_sends_nothing(self):
        for argv in (("--resolve", "4103"), ("--reopen", "4102"), ("--reopen", "4105")):
            with self.subTest(argv=argv):
                self.assertEqual(self.ok("comment", PAGE, *argv, "--json").json()["action"], "unchanged")
        self.assertEqual(self.writes(), [])

    def test_the_dry_run_sends_nothing_and_its_payload_is_the_one_of_the_real_run(self):
        preview = self.ok("comment", PAGE, "--resolve", "4102", "--dry-run", "--json").json()
        self.assertEqual((preview["dryRun"], preview["action"]), (True, "resolved"))
        self.assertEqual(self.writes(), [])
        self.ok("comment", PAGE, "--resolve", "4102")
        self.assertEqual([item.body for item in self.sent("PUT", "/api/v2/")], [preview["payload"]])

    def test_a_footer_comment_is_a_usage_error_and_a_dangling_one_is_refused_and_nothing_is_sent(self):
        self.assertEqual(self.cli("comment", PAGE, "--resolve", "4100").code, 2)
        self.assertEqual(self.cli("comment", PAGE, "--reopen", "4104").code, 1)
        self.assertEqual(self.writes(), [])

    def test_somebody_else_s_inline_comment_is_sent_back_with_its_own_text(self):
        self.ok("comment", PAGE, "--resolve", "4107")
        self.assertEqual(self.stored("4107")["resolutionStatus"], "resolved")
        self.assertEqual(self.stored("4107")["body"], "<p>Yes, it is.</p>")

    def test_the_text_that_goes_back_is_shown_without_the_people_and_sent_with_them(self):
        body = f'<p>Ask <ac:link><ri:user ri:account-id="{ACCOUNT}" /></ac:link> or write to alex@example.com.</p>'
        self.mock.comments["4195"] = {**self.stored("4102"), "id": "4195", "body": body}
        preview = self.ok("comment", PAGE, "--resolve", "4195", "--dry-run", "--json")
        data = preview.json()
        self.assertTrue(data["payloadRedacted"])
        for hidden in (ACCOUNT, "alex@example.com"):
            self.assertNotIn(hidden, preview.out + preview.err)
        self.ok("comment", PAGE, "--resolve", "4195")
        self.assertEqual(self.sent("PUT", "/api/v2/")[0].body["body"]["value"], body)

    def test_with_users_the_request_is_shown_as_it_is_and_the_policy_refuses_that_before_any_request(self):
        body = f'<p>Ask <ac:link><ri:user ri:account-id="{ACCOUNT}" /></ac:link> or write to alex@example.com.</p>'
        self.mock.comments["4195"] = {**self.stored("4102"), "id": "4195", "body": body}
        data = self.ok("comment", PAGE, "--resolve", "4195", "--dry-run", "--with-users", "--json").json()
        self.assertEqual((data["payloadRedacted"], data["payload"]["body"]["value"]), (False, body))
        self.assertEqual(self.writes(), [])
        self.mock.requests.clear()
        refused = self.cli("comment", PAGE, "--resolve", "4195", "--with-users", env={"CONFLUENCE_HIDE_USERS": "true"})
        self.assertEqual(refused.code, 1)
        self.assertIn("CONFLUENCE_HIDE_USERS", refused.err)
        for hidden in (ACCOUNT, "alex@example.com"):
            self.assertNotIn(hidden, refused.out + refused.err)
        self.assertEqual(self.mock.requests, [])

    def test_the_guards_refuse_a_comment_that_moved_on(self):
        self.assertEqual(self.cli("comment", PAGE, "--resolve", "4102", "--if-version", "2").code, 3)
        self.assertEqual(self.cli("comment", PAGE, "--resolve", "4102", "--if-unchanged-since", "2026-10-13T00:00:00Z").code, 3)
        self.assertEqual(self.writes(), [])
        self.ok("comment", PAGE, "--resolve", "4102", "--if-version", "1", "--if-unchanged-since", "2026-10-14T09:00:00Z")
        self.assertEqual(len(self.sent("PUT", "/api/v2/")), 1)

    def test_a_conflict_of_confluence_is_exit_code_3(self):
        self.mock.fail_next("/api/v2/inline-comments/4102", 409, method="PUT")
        self.assertEqual(self.cli("comment", PAGE, "--resolve", "4102").code, 3)
        self.assertEqual(self.stored("4102")["resolutionStatus"], "open")


class AddTest(CommentsFlow):
    """Adding a comment is what it was: the new modes did not change the requests."""

    def test_a_comment_is_added_with_its_parent_and_can_be_read_back_as_the_user_s_own(self):
        data = self.ok("comment", "2002", "--text", "Reviewed.", "--reply-to", "4001", "--json").json()
        post = self.sent("POST", "/api/v2/footer-comments")[0]
        self.assertEqual(post.body, {"parentCommentId": "4001", "body": {"representation": "storage", "value": "<p>Reviewed.</p>"}})  # a reply names its parent, not the page
        shown = self.ok("comment", "2002", "--get", data["commentId"], "--json").json()
        self.assertEqual((shown["kind"], shown["parentId"], shown["byMe"], shown["version"]), ("footer", "4001", True, 1))
        self.assertEqual(self.sent("GET", "/api/v2/footer-comments/4001")[0].path, "/api/v2/footer-comments/4001")  # the parent was read before the reply was sent

    def test_a_reply_to_a_comment_of_another_page_is_refused_before_anything_is_sent(self):
        refused = self.cli("comment", "2003", "--text", "Reviewed.", "--reply-to", "4001")
        self.assertEqual(refused.code, 4)
        self.assertIn("No comment 4001 on page 2003", refused.err)
        self.assertEqual(self.writes(), [])

    def test_the_dry_run_sends_nothing(self):
        self.ok("comment", "2002", "--text", "Reviewed.", "--dry-run")
        self.assertEqual(self.writes(), [])

    def test_an_empty_parent_is_an_error_and_never_a_comment_of_its_own_and_nothing_reaches_the_server(self):
        for argv in (("--reply-to", ""), ("--reply-to", "", "--dry-run"), ("--reply-to", "  ")):
            with self.subTest(argv=argv):
                refused = self.cli("comment", "2002", "--text", "Reviewed.", *argv)
                self.assertEqual(refused.code, 1)
                self.assertIn("--reply-to is empty", refused.err)
        self.assertEqual(self.mock.requests, [])  # not even a read
        self.ok("comment", "2002", "--text", "Reviewed.")  # not given: a comment of its own
        self.assertEqual(self.sent("POST", "/api/v2/footer-comments")[0].body["pageId"], "2002")


class EmptyOptionTest(CommentsFlow):
    """An option that is given with an empty value is an error that names it, and nothing reaches the server: not a write, and not a read."""

    def test_every_option_that_names_a_comment_a_time_or_a_state_refuses_an_empty_value(self):
        for argv, option in (
            (("comment", PAGE, "--get", ""), "--get"),
            (("comment", PAGE, "--edit", "", "--text", "x"), "--edit"),
            (("comment", PAGE, "--edit", "", "--text", "x", "--dry-run"), "--edit"),
            (("comment", PAGE, "--resolve", ""), "--resolve"),
            (("comment", PAGE, "--reopen", "", "--dry-run"), "--reopen"),
            (("comment", PAGE, "--edit", "4101", "--text", "x", "--if-unchanged-since", ""), "--if-unchanged-since"),
            (("comment", PAGE, "--resolve", "4102", "--if-unchanged-since", "", "--dry-run"), "--if-unchanged-since"),
            (("comment", PAGE, "--file", ""), "--file"),
            (("comments", PAGE, "--since", ""), "--since"),
            (("comments", PAGE, "--resolution", ""), "--resolution"),
        ):
            with self.subTest(argv=argv):
                result = self.cli(*argv)
                self.assertIn(result.code, (1, 2))
                self.assertIn(option, result.err.splitlines()[0])
                self.assertEqual(result.out, "")
        self.assertEqual(self.mock.requests, [])


if __name__ == "__main__":
    unittest.main()
