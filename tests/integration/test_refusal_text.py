"""What a refusal of Confluence says is printed without the people in it, whatever the policy: through the real adapters and the real program.

A server explains a refusal in free text, and puts people into it: `No user found for alex@example.com (accountId 5b10ac8d82e05b22cc7d4ef5)`. The
message of the error has no e-mail address, no link to a person and no account id (the policy that never prints people changes only whether the answer
itself is kept in `details`), and an answer that is too deep to be scrubbed is an answer that cannot be used.
"""
import json
import unittest
from unittest import mock

from conflu_c_cli.adapters.driven.http_transport import HttpResponse
from conflu_c_cli.domain.errors import ConfigError, ConfluCliError, RejectedError, UnavailableError
from tests.integration.test_end_to_end import EndToEnd
from tests.integration.test_http_and_gateway import MockCase

ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"
OLD_ACCOUNT = "712020:3f2c1a9e-4b7d-4c3e-9a1b-2d3e4f5a6b7c"
EMAIL = "alex@example.com"
SENTENCE = f"No user found for {EMAIL} (accountId {ACCOUNT})"
BODY = {"message": SENTENCE}
PEOPLE = (EMAIL, ACCOUNT, OLD_ACCOUNT)
REFUSALS = (400, 403, 404, 409, 500)  # no retry for any of these: one request, one answer


class RefusalMessageTest(MockCase):
    def refuse(self, status, body=BODY, *, path="/api/v2/pages/2002", **overrides) -> ConfluCliError:
        self.mock.fail_next(path, status, body=body)
        with self.assertRaises(ConfluCliError) as caught:
            self.api(retry=0, **overrides).get_page("2002")
        return caught.exception

    def shown(self, error: ConfluCliError) -> str:
        return error.message + "\n" + error.hint + "\n" + json.dumps(error.details)

    def test_no_message_names_a_person_whatever_the_policy(self):
        for hide in (False, True):
            for status in REFUSALS:
                with self.subTest(hide_users=hide, status=status):
                    error = self.refuse(status, hide_users=hide)
                    self.assertIn("No user found for [email] (accountId [account id])", error.message)
                    for person in PEOPLE:
                        self.assertNotIn(person, error.message + error.hint)

    def test_the_account_id_that_the_policy_left_in_a_sentence_goes_too(self):
        """Under the policy the e-mail address was replaced already and the account id stayed in the sentence."""
        error = self.refuse(404, hide_users=True)
        self.assertEqual(error.message, "Not found: GET /api/v2/pages/2002 - No user found for [email] (accountId [account id])")

    def test_the_older_form_of_an_account_id_and_a_link_to_a_person_go_too(self):
        body = {"message": f"{OLD_ACCOUNT} may not see https://example.atlassian.net/wiki/people/{ACCOUNT}"}
        for hide in (False, True):
            with self.subTest(hide_users=hide):
                error = self.refuse(403, body, hide_users=hide)
                self.assertIn("[account id] may not see [personal link]", error.message)
                self.assertNotIn(ACCOUNT, self.shown(error).replace("[account id]", ""))

    def test_every_shape_of_an_explanation_is_redacted(self):
        shapes = (
            {"errors": [{"status": 400, "title": "Bad", "detail": SENTENCE}]},
            {"errors": [{"status": 400, "title": SENTENCE}]},
            {"errors": [{"message": {"translation": SENTENCE}}]},
            {"errors": [SENTENCE]},
            {"data": {"errors": [{"message": SENTENCE}]}},
            {"data": {"errors": [SENTENCE]}},
            {"reason": SENTENCE},
            {"message": SENTENCE, "reason": SENTENCE},
        )
        for body in shapes:
            for hide in (False, True):
                with self.subTest(body=json.dumps(body)[:50], hide_users=hide):
                    error = self.refuse(400, body, hide_users=hide)
                    self.assertIn("[email]", error.message)
                    self.assertIn("[account id]", error.message)
                    for person in PEOPLE:
                        self.assertNotIn(person, error.message)

    def test_the_credentials_are_still_taken_out(self):
        body = {"message": f"echo {self.mock.token} for {self.mock.email}"}
        for hide in (False, True):
            with self.subTest(hide_users=hide):
                error = self.refuse(400, body, hide_users=hide)
                self.assertNotIn(self.mock.token, self.shown(error))
                self.assertNotIn(self.mock.email, self.shown(error))
                self.assertIn("********", error.message)

    def test_a_refusal_without_words_says_so(self):
        for body in ({}, {"errors": []}, {"message": ""}, {"other": SENTENCE}):
            with self.subTest(body=body):
                self.assertEqual(self.refuse(400, body, hide_users=False).message, "Confluence refused the request (HTTP 400): no explanation")

    def test_a_refusal_with_nothing_to_hide_reads_as_it_did(self):
        error = self.refuse(404, {"message": "Page not found"})
        self.assertEqual(error.message, "Not found: GET /api/v2/pages/2002 - Page not found")
        self.assertEqual(error.hint, "Confluence also answers 404 for what the account may not see.")


class AnswerInDetailsTest(MockCase):
    def refuse(self, body=BODY, **overrides) -> RejectedError:
        self.mock.fail_next("/api/v2/pages/2002", 400, body=body)
        with self.assertRaises(RejectedError) as caught:
            self.api(retry=0, **overrides).get_page("2002")
        return caught.exception

    def test_the_answer_is_kept_in_the_details_of_a_refusal_when_people_may_be_shown_and_it_is_redacted_all_the_same(self):
        error = self.refuse(hide_users=False)
        self.assertEqual(error.details["confluence"], {"message": "No user found for [email] (accountId [account id])"})
        self.assertEqual((error.details["status"], error.details["request"]), (400, "GET /api/v2/pages/2002"))
        for person in PEOPLE:
            self.assertNotIn(person, json.dumps(error.details))

    def test_it_is_not_kept_under_the_policy_that_never_prints_people(self):
        error = self.refuse({"message": SENTENCE, "user": {"displayName": "Alex Example", "accountId": ACCOUNT}}, hide_users=True)
        self.assertNotIn("confluence", error.details)
        self.assertEqual(set(error.details), {"status", "request"})
        self.assertNotIn("Alex Example", json.dumps(error.details) + error.message)

    def test_the_structure_of_the_answer_is_what_the_server_sent_and_only_its_text_is_redacted(self):
        body = {"errors": [{"status": 400, "code": "BAD", "detail": SENTENCE}], "extra": {"list": [1, 2.5, None, True, f"also {OLD_ACCOUNT}"]}}
        kept = self.refuse(body, hide_users=False).details["confluence"]
        self.assertEqual(kept["errors"][0]["status"], 400)
        self.assertEqual(kept["errors"][0]["code"], "BAD")
        self.assertEqual(kept["extra"]["list"], [1, 2.5, None, True, "also [account id]"])

    def test_the_other_refusals_never_carried_the_answer(self):
        for status in (403, 404, 409, 500):
            self.mock.fail_next("/api/v2/pages/2002", status, body=BODY)
            with self.subTest(status=status), self.assertRaises(ConfluCliError) as caught:
                self.api(retry=0).get_page("2002")
            self.assertNotIn("confluence", caught.exception.details)

    def test_the_people_that_the_answer_names_are_not_kept_with_their_names(self):
        """The review: a 400 whose body holds `assignedTo: {accountId, displayName, email}` kept the name, because the text redaction finds no name."""
        body = {
            "errors": [{"status": 400, "title": "Bad", "detail": SENTENCE}],
            "task": {
                "id": "7203",
                "assignedTo": {"accountId": ACCOUNT, "displayName": "Alex Example", "email": EMAIL},
                "createdBy": ACCOUNT,
                "owner": {"displayName": "Maria Example"},
                "text": f"Ask {EMAIL}",
            },
        }
        kept = self.refuse(body, hide_users=False).details["confluence"]
        self.assertEqual(kept["task"]["assignedTo"], {"hidden": True})
        self.assertEqual(kept["task"]["owner"], {"hidden": True})  # a user that is only a name is one too
        self.assertEqual(kept["task"]["createdBy"], "[hidden]")
        self.assertEqual((kept["task"]["id"], kept["task"]["text"]), ("7203", "Ask [email]"))  # what is no person stays, its text redacted
        self.assertEqual(kept["errors"], [{"status": 400, "title": "Bad", "detail": "No user found for [email] (accountId [account id])"}])
        for person in (*PEOPLE, "Alex Example", "Maria Example"):
            self.assertNotIn(person, json.dumps(kept))

    def test_under_the_policy_the_answer_is_still_left_out_and_nobody_is_named_anywhere(self):
        body = {"message": SENTENCE, "task": {"assignedTo": {"accountId": ACCOUNT, "displayName": "Alex Example", "email": EMAIL}}}
        error = self.refuse(body, hide_users=True)
        self.assertEqual(set(error.details), {"status", "request"})
        for person in (*PEOPLE, "Alex Example"):
            self.assertNotIn(person, error.message + error.hint + json.dumps(error.details))

    def test_a_person_in_an_answer_that_is_too_deep_to_strip_leaves_the_answer_out_and_not_the_name_in(self):
        with mock.patch("conflu_c_cli.adapters.driven.confluence_rest.strip_users", side_effect=RecursionError):
            error = self.refuse({"message": SENTENCE, "user": {"displayName": "Alex Example"}}, hide_users=False)
        self.assertNotIn("confluence", error.details)
        self.assertNotIn("Alex Example", json.dumps(error.details))


class RedirectTextTest(MockCase):
    def test_a_redirect_to_a_link_to_a_person_does_not_name_the_person(self):
        self.mock.fail_next("/api/v2/spaces", 302, headers={"Location": f"/wiki/people/{ACCOUNT}"})
        with self.assertRaises(ConfigError) as caught:
            self.api().list_spaces()
        self.assertIn("redirect (HTTP 302) to [personal link]", caught.exception.message)
        self.assertNotIn(ACCOUNT, caught.exception.message)

    def test_a_redirect_to_a_login_page_says_where(self):
        self.mock.fail_next("/api/v2/spaces", 302, headers={"Location": "https://login.example.com/sso"})
        with self.assertRaises(ConfigError) as caught:
            self.api().list_spaces()
        self.assertIn("redirect (HTTP 302) to login.example.com/sso instead of data", caught.exception.message)


class TooDeepToScrubTest(MockCase):
    """An answer nested deeper than the scrubbing reads (about 490 levels where a comprehension takes a frame) is a damaged answer."""

    def test_a_scrub_that_runs_out_of_stack_is_an_unavailable_error(self):
        for target in ("_without_secrets", "strip_users"):
            with self.subTest(target=target):
                gateway = self.api(hide_users=True)
                with mock.patch(f"conflu_c_cli.adapters.driven.confluence_rest.{target}", side_effect=RecursionError):
                    with self.assertRaises(UnavailableError) as caught:
                        gateway._raise_for_status(HttpResponse(404, {}, b""), {"message": SENTENCE}, "GET", "/api/v2/pages/2002?x=1")
                self.assertEqual(caught.exception.exit_code, 7)
                self.assertIn("HTTP 404", caught.exception.message)
                self.assertIn("nests arrays or objects too deeply", caught.exception.message)
                self.assertEqual(caught.exception.details, {"status": 404, "request": "GET /api/v2/pages/2002"})  # no query: it may hold a token
                self.assertNotIn(SENTENCE, caught.exception.message)

    def test_an_answer_too_deep_to_copy_for_the_details_is_left_out_of_them(self):
        gateway = self.api(hide_users=False)
        with mock.patch("conflu_c_cli.adapters.driven.confluence_rest.redact_error_value", side_effect=RecursionError):
            with self.assertRaises(RejectedError) as caught:
                gateway._raise_for_status(HttpResponse(400, {}, b""), {"message": SENTENCE}, "GET", "/api/v2/pages/2002")
        self.assertIn("No user found for [email] (accountId [account id])", caught.exception.message)
        self.assertNotIn("confluence", caught.exception.details)

    def test_the_status_of_an_answer_that_went_well_is_never_scrubbed(self):
        gateway = self.api(hide_users=True)
        with mock.patch("conflu_c_cli.adapters.driven.confluence_rest._without_secrets", side_effect=AssertionError("scrubbed")):
            gateway._raise_for_status(HttpResponse(200, {}, b"{}"), {"anything": [1]}, "GET", "/api/v2/spaces")


class RefusalOfTheProgramTest(EndToEnd):
    """The program as a person or an agent runs it: the text of the error and its JSON have nobody in them."""

    def refused(self, *argv, status=404, body=BODY, env=None):
        self.mock.fail_next("/api/v2/pages/2002", status, body=body)
        return self.cli(*argv, env=env)

    def test_the_text_of_the_error_names_nobody(self):
        for policy in ({}, {"CONFLUENCE_HIDE_USERS": "true"}, {"CONFLUENCE_PROFILE": "agent"}):
            with self.subTest(policy=policy):
                result = self.refused("page", "2002", env=policy)
                self.assertEqual(result.code, 4)
                self.assertIn("No user found for [email] (accountId [account id])", result.err)
                for person in PEOPLE:
                    self.assertNotIn(person, result.out + result.err)

    def test_the_json_of_the_error_names_nobody_and_the_policy_drops_the_answer(self):
        for policy, kept in (({}, True), ({"CONFLUENCE_HIDE_USERS": "true"}, False), ({"CONFLUENCE_PROFILE": "agent"}, False)):
            with self.subTest(policy=policy):
                result = self.refused("page", "2002", "--json", status=400, env=policy)
                self.assertEqual(result.code, 6, result.err)
                error = json.loads(result.err.strip().splitlines()[-1])["error"]
                self.assertIn("[account id]", error["message"])
                self.assertEqual("confluence" in error.get("details", {}), kept)
                for person in PEOPLE:
                    self.assertNotIn(person, result.out + result.err)

    def test_an_explanation_without_people_is_printed_as_it_is(self):
        result = self.refused("page", "2002", status=403, body={"message": "Permission denied: the space is closed"})
        self.assertEqual(result.code, 5)
        self.assertIn("Permission denied: the space is closed", result.err)

    def test_a_refused_change_of_a_task_does_not_name_who_the_task_is_assigned_to(self):
        """The review's case: `task 7203 --complete --json`, the PUT answered with HTTP 400 and a body that names the assignee."""
        body = {"errors": [{"status": 400, "title": "Bad", "detail": SENTENCE}], "task": {"assignedTo": {"accountId": ACCOUNT, "displayName": "Alex Example", "email": EMAIL}}}
        for policy, kept in (({}, True), ({"CONFLUENCE_HIDE_USERS": "true"}, False), ({"CONFLUENCE_PROFILE": "agent"}, False)):
            self.mock.fail_next("/api/v2/tasks/7203", 400, method="PUT", body=body)
            result = self.cli("task", "7203", "--complete", "--json", env=policy)
            with self.subTest(policy=policy):
                self.assertEqual((result.code, result.out), (6, ""), result.err)
                error = json.loads(result.err.strip().splitlines()[-1])["error"]
                self.assertEqual("confluence" in error["details"], kept)
                if kept:
                    self.assertEqual(error["details"]["confluence"]["task"]["assignedTo"], {"hidden": True})
                for person in (*PEOPLE, "Alex Example"):
                    self.assertNotIn(person, result.out + result.err)


if __name__ == "__main__":
    unittest.main()
