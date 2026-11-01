"""Watching a page or a space, the real program against the mock Confluence: the requests that are sent, the read-back, hostile input, privacy."""
import json
import unittest

from tests.integration.test_end_to_end import ACCOUNT, EndToEnd
from tests.support.mock_watches import WatchesRoutes

BLOG_POST = "7561"  # content of a kind that no other fixture has, registered where this test needs it
TYPES = ("POST", "/api/v2/content/convert-ids-to-types")


class WatchesFlow(EndToEnd):
    def setUp(self):
        super().setUp()
        self.area = self.mock.area(WatchesRoutes)
        self.mock.content_kinds[BLOG_POST] = "blogpost"

    def calls(self):
        """Every request that was made, as (method, path)."""
        return [(item.method, item.path) for item in self.mock.requests]

    def writes(self):
        return [item for item in self.mock.requests if item.method in ("POST", "DELETE") and item.path.startswith("/rest/api/user/watch/")]

    def nothing_unknown(self):
        self.assertEqual((self.mock.unknown_endpoints, self.mock.deprecated_endpoints), ([], []))


class StatusTest(WatchesFlow):
    def test_the_status_of_a_page_is_the_type_of_the_id_and_one_v1_get_that_names_no_person(self):
        result = self.cli("watching", "2002", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(result.json(), {"target": {"id": "2002", "type": "page", "key": None, "title": None}, "watching": False})
        self.assertEqual(self.calls(), [TYPES, ("GET", "/rest/api/user/watch/content/2002")])
        self.assertEqual(self.mock.requests[0].body, {"contentIds": ["2002"]})
        self.assertEqual(self.mock.requests[1].query, {})  # no accountId, no username, no key: the answer is about the owner of the token
        self.assertIn("GET /rest/api/user/watch/content/{contentId}", self.mock.used_endpoints)
        self.nothing_unknown()

    def test_a_watch_that_is_there_is_shown(self):
        self.area.watching.add(("content", "2002"))
        self.assertEqual(self.cli("watching", "2002").out, "You watch the page [2002].\n")
        self.assertTrue(self.cli("watching", "2002", "--json").json()["watching"])

    def test_a_space_is_asked_by_its_key(self):
        self.area.watching.add(("space", "ENG"))
        space_id = next(item["id"] for item in self.mock.spaces.values() if item["key"] == "ENG")
        result = self.cli("watching", "--space", "eng", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(result.json(), {"target": {"id": space_id, "type": "space", "key": "ENG", "title": "Engineering"}, "watching": True})
        self.assertIn(("GET", "/rest/api/user/watch/space/ENG"), self.calls())
        self.assertEqual(self.cli("watching", "--space", "DOCS").out, "You do not watch the space DOCS (Documentation).\n")

    def test_the_address_of_a_page_and_other_kinds_of_content(self):
        self.assertEqual(self.cli("watching", f"{self.mock.base_url}/spaces/ENG/pages/2002/Release+notes").out, "You do not watch the page [2002].\n")
        data = self.cli("watching", BLOG_POST, "--json").json()
        self.assertEqual((data["target"]["type"], data["watching"]), ("blogpost", False))

    def test_the_current_space_is_what_a_read_assumes(self):
        self.area.watching.add(("space", "DOCS"))
        result = self.cli("watching", env={"CONFLUENCE_SPACE": "DOCS"})
        self.assertEqual(result.out, "You watch the space DOCS (Documentation).\n")
        self.assertEqual(self.cli("watching").code, 2)

    def test_what_is_not_there_is_not_found(self):
        content = self.cli("watching", "99999", "--json")
        self.assertEqual(content.code, 4)
        self.assertEqual(self.calls(), [TYPES])  # the watch of what is not there is not asked
        space = self.cli("watching", "--space", "NOSUCH")
        self.assertEqual(space.code, 4)
        self.assertEqual([path for _, path in self.calls() if path.startswith("/rest/")], [])

    def test_an_answer_that_does_not_say_is_an_error_and_not_a_no(self):
        self.mock.fail_next("/rest/api/user/watch/content/2002", 200, method="GET", body={"watching": "yes"})
        result = self.cli("watching", "2002")
        self.assertEqual((result.code, result.out), (7, ""))
        self.assertIn("did not say whether you watch content 2002", result.err)

    def test_the_server_that_refuses_is_an_error(self):
        self.mock.fail_next("/rest/api/user/watch/content/2002", 403, method="GET", body={"message": "No permission"})
        self.assertEqual(self.cli("watching", "2002").code, 5)
        wrong = self.cli("watching", "2002", env={"CONFLUENCE_API_TOKEN": "wrong-token"})
        self.assertEqual(wrong.code, 5)


class ChangeTest(WatchesFlow):
    def test_a_watch_is_the_type_the_status_a_post_and_the_status_again_in_this_order(self):
        result = self.cli("watch", "2002", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(
            self.calls(),
            [TYPES, ("GET", "/rest/api/user/watch/content/2002"), ("POST", "/rest/api/user/watch/content/2002"), ("GET", "/rest/api/user/watch/content/2002")],
        )
        self.assertEqual(self.area.watching, {("content", "2002")})
        data = result.json()
        self.assertEqual((data["action"], data["wasWatching"], data["watching"], data["confirmed"], data["message"]), ("watched", False, True, True, None))
        self.assertEqual(data["call"], "POST /rest/api/user/watch/content/{contentId}")
        self.nothing_unknown()

    def test_the_write_has_the_header_the_document_asks_for_and_no_body_no_query_and_no_person(self):
        self.cli("watch", "2002")
        (post,) = self.writes()
        self.assertEqual(post.headers.get("x-atlassian-token"), "no-check")
        self.assertEqual((post.raw, post.body, post.query), (b"", None, {}))
        self.assertNotIn("content-type", post.headers)  # there is no body to describe

    def test_the_dry_run_reads_and_sends_nothing_and_names_the_call_the_real_run_makes(self):
        dry = self.cli("watch", "2002", "--dry-run", "--json")
        self.assertEqual(dry.code, 0, dry.err)
        self.assertEqual((self.writes(), self.area.written, self.area.watching), ([], 0, set()))
        self.assertEqual(self.calls(), [TYPES, ("GET", "/rest/api/user/watch/content/2002")])  # the target was read, nothing more
        preview = dry.json()
        self.assertEqual((preview["action"], preview["dryRun"], preview["confirmed"]), ("watched", True, None))
        self.cli("watch", "2002", "--json")
        (post,) = self.writes()
        method, template = preview["call"].split(" ", 1)
        self.assertEqual((method, template.replace("{contentId}", "2002")), (post.method, post.path))  # what the dry run said is what was sent

    def test_the_same_request_again_changes_nothing_and_sends_nothing(self):
        self.cli("watch", "2002")
        before = len(self.mock.requests)
        again = self.cli("watch", "2002", "--json")
        self.assertEqual(again.json()["action"], "unchanged")
        self.assertEqual(again.json()["call"], None)
        self.assertEqual(self.calls()[before:], [TYPES, ("GET", "/rest/api/user/watch/content/2002")])
        self.assertEqual(self.area.written, 1)

    def test_stopping_is_a_delete_of_your_own_watch_and_only_when_there_is_one(self):
        self.area.watching.update({("content", "2002"), ("content", "2003"), ("space", "ENG")})
        result = self.cli("watch", "2002", "--remove", "--json")
        self.assertEqual(result.code, 0, result.err)
        (delete,) = self.writes()
        self.assertEqual((delete.method, delete.path, delete.query, delete.headers.get("x-atlassian-token")), ("DELETE", "/rest/api/user/watch/content/2002", {}, "no-check"))
        self.assertEqual(self.area.watching, {("content", "2003"), ("space", "ENG")})  # nothing else was touched
        data = result.json()
        self.assertEqual((data["action"], data["wasWatching"], data["watching"], data["confirmed"], data["call"]), ("unwatched", True, False, True, "DELETE /rest/api/user/watch/content/{contentId}"))
        again = self.cli("watch", "2002", "--remove")
        self.assertEqual(again.out, "Nothing to change: you do not watch the page [2002].\n")
        self.assertEqual(len(self.writes()), 1)

    def test_the_dry_run_of_a_stop_sends_no_delete(self):
        self.area.watching.add(("content", "2002"))
        dry = self.cli("watch", "2002", "--remove", "--dry-run")
        self.assertEqual(dry.out, "Dry run: you would stop watching the page [2002]; nothing was sent\nCall: DELETE /rest/api/user/watch/content/{contentId}\n")
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.area.watching, {("content", "2002")})

    def test_a_space_is_watched_and_left_by_its_key(self):
        started = self.cli("watch", "--space", "eng")
        self.assertEqual(started.out, "Now watching the space ENG (Engineering).\n")
        self.assertEqual(self.area.watching, {("space", "ENG")})
        stopped = self.cli("watch", "--space", "ENG", "--remove")
        self.assertEqual(stopped.out, "Stopped watching the space ENG (Engineering).\n")
        self.assertEqual([(item.method, item.path) for item in self.writes()], [("POST", "/rest/api/user/watch/space/ENG"), ("DELETE", "/rest/api/user/watch/space/ENG")])
        self.assertEqual(self.area.watching, set())
        self.nothing_unknown()

    def test_a_blog_post_or_any_content_by_its_id_or_address(self):
        self.assertEqual(self.cli("watch", BLOG_POST).out, f"Now watching the blog post [{BLOG_POST}].\n")
        self.assertEqual(self.cli("watch", f"{self.mock.base_url}/spaces/ENG/pages/2003/Architecture").out, "Now watching the page [2003].\n")
        self.assertEqual(self.area.watching, {("content", BLOG_POST), ("content", "2003")})

    def test_the_header_is_what_the_server_asks_for_it_refuses_a_write_without_it(self):
        refused = self.cli("api", "POST", "rest/api/user/watch/content/2002", "--data", "{}", "--write")
        self.assertEqual(refused.code, 5, refused.err)
        self.assertIn("XSRF check failed", refused.err)
        self.assertEqual(self.area.watching, set())
        self.cli("watch", "2002")
        self.assertEqual(self.area.watching, {("content", "2002")})

    def test_a_read_back_that_fails_is_no_failure_and_what_was_said_is_true(self):
        self.area.read_back_fails = True
        result = self.cli("watch", "2002", "--json")
        self.assertEqual(result.code, 0, result.err)
        data = result.json()  # standard output is the JSON and only that
        self.assertEqual((data["action"], data["watching"], data["confirmed"]), ("watched", None, None))
        self.assertIn("The watch was added, but reading the watch status afterwards failed", data["message"])
        self.assertIn("Check it with `conflu watching 2002`", data["message"])
        self.assertIn("WARNING: The watch was added", result.err)
        self.assertEqual(self.area.watching, {("content", "2002")})  # it was made
        self.assertTrue(self.cli("watching", "2002", "--json").json()["watching"])  # and the command the message names shows it
        text = self.cli("watch", "2003")
        self.assertEqual(text.out, "Now watching the page [2003]. The change was made, but reading the status back failed (see the warning).\n")

    def test_a_write_that_the_server_refuses_is_an_error_that_is_not_read_back_and_not_tried_again(self):
        self.mock.fail_next("/rest/api/user/watch/content/2002", 403, method="POST", body={"message": "No permission"})
        result = self.cli("watch", "2002")
        self.assertEqual((result.code, result.out), (5, ""))
        self.assertEqual(self.area.watching, set())
        self.assertEqual(self.calls()[-1], ("POST", "/rest/api/user/watch/content/2002"))  # no read after it
        self.mock.fail_next("/rest/api/user/watch/content/2003", 503, times=3, method="POST")
        failed = self.cli("watch", "2003")
        self.assertEqual(failed.code, 7)
        self.assertEqual(len([item for item in self.mock.requests if item.method == "POST" and item.path == "/rest/api/user/watch/content/2003"]), 1)  # a write is never repeated

    def test_what_is_not_there_is_not_found_and_nothing_is_written(self):
        self.assertEqual(self.cli("watch", "99999").code, 4)
        self.assertEqual(self.cli("watch", "--space", "NOSUCH").code, 4)
        self.assertEqual((self.writes(), self.area.written), ([], 0))

    def test_a_change_names_what_it_changes_the_current_space_is_not_assumed(self):
        result = self.cli("watch", env={"CONFLUENCE_SPACE": "ENG"})
        self.assertEqual(result.code, 2)
        self.assertEqual(self.cli("watch", "2002", "--space", "ENG").code, 2)
        self.assertEqual(self.mock.requests, [])


class HostileInputTest(WatchesFlow):
    def test_what_is_no_id_and_no_key_sends_nothing_at_all(self):
        for argv in (
            ("watch", "../x"),
            ("watch", "2002/../1"),
            ("watch", "2002?accountId=5b10ac8d82e05b22cc7d4ef6"),
            ("watch", "2002#x"),
            ("watch", "2002 2003"),
            ("watch", "--space", "../x"),
            ("watch", "--space", "ENG/../DOCS"),
            ("watch", "--space", "ENG?accountId=x"),
            ("watch", "--space", "ENG%2F..%2F"),
            ("watching", "../x"),
            ("watching", "--space", "a b"),
        ):
            with self.subTest(argv=argv):
                result = self.cli(*argv)
                self.assertEqual(result.code, 1, result.err)
        self.assertEqual(self.mock.requests, [])

    def test_the_options_that_would_name_somebody_else_are_unknown(self):
        for option in ("--user", "--account-id", "--username", "--for"):
            with self.subTest(option=option):
                self.assertEqual(self.cli("watch", "2002", option, ACCOUNT).code, 2)
        self.assertEqual(self.mock.requests, [])


class PrivacyTest(WatchesFlow):
    def test_no_person_is_in_what_is_printed_or_in_what_is_asked(self):
        outputs = []
        for argv in (("watching", "2002"), ("watch", "2002"), ("watch", "2002", "--json"), ("watching", "--space", "ENG", "--json"), ("watch", "--space", "ENG", "--dry-run"), ("watch", "2002", "--remove", "--json")):
            result = self.cli(*argv)
            self.assertEqual(result.code, 0, result.err)
            outputs.append(result.out + result.err)
        text = "\n".join(outputs)
        for secret in (ACCOUNT, "Alex Example", "alex@example.com", self.mock.email):
            self.assertNotIn(secret, text)
        for item in self.mock.requests:
            self.assertFalse({"accountId", "username", "key"} & set(item.query), item.target)  # nothing names a person
            self.assertNotIn(ACCOUNT, json.dumps(item.body) if item.body else "")

    def test_the_name_of_a_space_is_redacted_like_every_title(self):
        next(item for item in self.mock.spaces.values() if item["key"] == "ENG")["name"] = "Team of alex@example.com"
        for argv in (("watching", "--space", "ENG"), ("watch", "--space", "ENG", "--dry-run"), ("watch", "--space", "ENG", "--json")):
            with self.subTest(argv=argv):
                result = self.cli(*argv)
                self.assertNotIn("alex@example.com", result.out + result.err)
                self.assertIn("Team of [email]", result.out)

    def test_a_personal_space_is_printed_as_it_is_everywhere_neither_its_key_nor_the_name_of_its_owner(self):
        space_id = self.mock.add_space("~alexe", "Alex Example", "personal")
        for argv in (("watching", "--space", "~alexe", "--json"), ("watch", "--space", "~alexe", "--dry-run", "--json"), ("watch", "--space", "~alexe", "--json"), ("watch", "--space", "~alexe", "--remove")):
            with self.subTest(argv=argv):
                result = self.cli(*argv)
                self.assertEqual(result.code, 0, result.err)
                self.assertNotIn("Alex Example", result.out + result.err)
                self.assertNotIn("~alexe", result.out + result.err)
        data = self.cli("watching", "--space", "~alexe", "--json").json()
        self.assertEqual(data["target"], {"id": space_id, "type": "space", "key": "[hidden]", "title": "[personal space]"})
        self.assertIn(("GET", "/rest/api/user/watch/space/~alexe"), self.calls())  # what is printed is hidden; what is called is the real key

    def test_the_policy_that_hides_people_does_not_stop_a_command_that_shows_none(self):
        env = {"CONFLUENCE_HIDE_USERS": "true"}
        self.assertEqual(self.cli("watching", "2002", env=env).code, 0)
        self.assertEqual(self.cli("watch", "2002", env=env).out, "Now watching the page [2002].\n")
        self.assertEqual(self.cli("watch", "2002", "--remove", env=env).code, 0)

    def test_a_refusal_of_the_server_is_scrubbed_of_people_under_the_policy(self):
        body = {"message": "No permission for alex@example.com", "data": {"authorized": False, "valid": True, "errors": [], "successful": False}}
        self.mock.fail_next("/rest/api/user/watch/content/2002", 403, method="GET", body=body)
        hidden = self.cli("watching", "2002", env={"CONFLUENCE_HIDE_USERS": "true"})
        self.assertEqual(hidden.code, 5)
        self.assertNotIn("alex@example.com", hidden.err)
        self.assertIn("[email]", hidden.err)


class WholeProgramTest(WatchesFlow):
    def test_as_a_separate_program(self):
        started = self.child("watch", "2002", "--json")
        self.assertEqual(started.code, 0, started.err)
        self.assertEqual(started.json()["action"], "watched")
        shown = self.child("watching", "2002")
        self.assertEqual(shown.out, "You watch the page [2002].\n")
        stopped = self.child("watch", "2002", "--remove")
        self.assertEqual(stopped.out, "Stopped watching the page [2002].\n")
        self.assertEqual(self.area.watching, set())


if __name__ == "__main__":
    unittest.main()
