"""The tasks of pages, the real program against the mock Confluence: the requests that are sent, the filters, the change of a status, privacy, hostile input."""
import time
import unittest

from tests.integration.test_end_to_end import ACCOUNT, EndToEnd
from tests.support.fakes import FakeGateway
from tests.support.fakes_tasks import SAM as FAKE_SAM
from tests.support.mock_base import RequestError
from tests.support.mock_tasks import BLOG_POST, SAM, TasksRoutes

TYPES = ("POST", "/api/v2/content/convert-ids-to-types")
CURRENT = ("GET", "/rest/api/user/current")
PEOPLE = (ACCOUNT, SAM, "Alex Example", "alex@example.com")


class TasksFlow(EndToEnd):
    def setUp(self):
        super().setUp()
        self.area = self.mock.area(TasksRoutes)

    def calls(self):
        """Every request that was made, as (method, path)."""
        return [(item.method, item.path) for item in self.mock.requests]

    def task_requests(self, method=None):
        return [item for item in self.mock.requests if item.path.startswith("/api/v2/tasks") and (method is None or item.method == method)]

    def writes(self):
        return [item for item in self.mock.requests if item.method in ("PUT", "POST", "DELETE") and item.path != TYPES[1]]

    def nothing_unknown(self):
        self.assertEqual((self.mock.unknown_endpoints, self.mock.deprecated_endpoints), ([], []))

    def ids(self, result):
        return [task["id"] for task in result.json()["tasks"]]


class ListTest(TasksFlow):
    def test_the_list_is_one_get_of_the_tasks_with_the_text_in_storage_format_and_the_limit(self):
        result = self.cli("tasks", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.calls(), [("GET", "/api/v2/tasks")])
        self.assertEqual(self.task_requests()[0].query, {"body-format": ["storage"], "limit": ["25"]})
        self.assertEqual((self.ids(result), result.json()["nextCursor"]), (["7201", "7202"], "2"))  # the mock gives two at a time
        self.assertEqual(self.mock.used_endpoints, ["GET /api/v2/tasks"])
        self.nothing_unknown()

    def test_the_cursor_that_was_given_back_is_the_next_piece(self):
        result = self.cli("tasks", "--cursor", "2", "--json")
        self.assertEqual(self.task_requests()[0].query["cursor"], ["2"])
        self.assertEqual((self.ids(result), result.json()["nextCursor"]), (["7203", "7204"], "4"))

    def test_all_of_them_follow_the_cursors_in_pieces_of_a_hundred(self):
        result = self.cli("tasks", "--all", "--json")
        self.assertEqual(self.ids(result), ["7201", "7202", "7203", "7204", "7205", "7206"])
        cursors = [item.query.get("cursor", [""])[0] for item in self.task_requests()]
        self.assertEqual(cursors, ["", "2", "4"])
        self.assertEqual({item.query["limit"][0] for item in self.task_requests()}, {"100"})
        self.assertEqual((result.json()["nextCursor"], result.json()["truncated"]), (None, False))

    def test_a_space_is_found_by_its_key_and_its_id_is_the_filter(self):
        result = self.cli("tasks", "--space", "eng", "--all", "--json")
        self.assertEqual(self.ids(result), ["7201", "7202", "7203", "7204", "7205"])
        self.assertEqual(self.calls()[0], ("GET", "/api/v2/spaces"))
        self.assertEqual(self.mock.requests[0].query["keys"], ["eng"])
        self.assertTrue(all(item.query["space-id"] == ["1001"] for item in self.task_requests()))
        self.assertEqual(result.json()["space"], "ENG")

    def test_a_page_is_asked_what_it_is_and_a_blog_post_goes_into_its_own_filter(self):
        page = self.cli("tasks", "--page", "2002", "--json")
        self.assertEqual(self.calls(), [TYPES, ("GET", "/api/v2/tasks")])
        self.assertEqual(self.mock.requests[0].body, {"contentIds": ["2002"]})
        self.assertEqual((self.ids(page), self.task_requests()[0].query["page-id"], "blogpost-id" in self.task_requests()[0].query), (["7201", "7202"], ["2002"], False))
        self.mock.requests.clear()
        post = self.cli("tasks", "--page", BLOG_POST, "--json")
        self.assertEqual((self.ids(post), self.task_requests()[0].query["blogpost-id"], "page-id" in self.task_requests()[0].query), (["7205"], [BLOG_POST], False))
        self.assertEqual(post.json()["tasks"][0]["blogPostId"], BLOG_POST)

    def test_the_address_of_a_page_names_it(self):
        self.cli("tasks", "--page", f"{self.mock.base_url}/spaces/ENG/pages/2003/Architecture", "--json")
        self.assertEqual(self.task_requests()[0].query["page-id"], ["2003"])

    def test_a_status_and_a_range_of_due_days_are_the_parameters_of_the_document(self):
        result = self.cli("tasks", "--status", "incomplete", "--due-after", "2026-10-20", "--due-before", "2026-10-25", "--all", "--json")
        self.assertEqual(result.code, 0, result.err)
        query = self.task_requests()[0].query
        self.assertEqual((query["status"], query["due-at-from"], query["due-at-to"]), (["incomplete"], ["1792454400000"], ["1792886400000"]))
        self.assertEqual(self.ids(result), ["7201", "7205"])  # due exactly at the start of each of the two days: both ends are in

    def test_a_task_without_a_due_date_is_in_no_range(self):
        self.assertNotIn("7204", self.ids(self.cli("tasks", "--due-after", "1970-01-01", "--all", "--json")))
        self.assertNotIn("7204", self.ids(self.cli("tasks", "--due-before", "9999-12-31", "--all", "--json")))
        self.assertIn("7204", self.ids(self.cli("tasks", "--all", "--json")))

    def test_mine_asks_who_the_token_belongs_to_and_sends_that_account_without_printing_it(self):
        result = self.cli("tasks", "--mine", "--all", "--json")
        self.assertEqual(self.ids(result), ["7201", "7203", "7205"])
        self.assertEqual(self.calls()[0], CURRENT)
        self.assertTrue(all(item.query["assigned-to"] == [ACCOUNT] and "created-by" not in item.query for item in self.task_requests()))
        for text in PEOPLE:
            self.assertNotIn(text, result.out + result.err)
        self.assertIn("GET /rest/api/user/current", self.mock.used_endpoints)

    def test_created_by_me_is_the_other_filter_and_both_together_ask_once(self):
        self.assertEqual(self.ids(self.cli("tasks", "--created-by-me", "--all", "--json")), ["7201", "7202", "7204", "7205"])
        self.assertTrue(all(item.query["created-by"] == [ACCOUNT] for item in self.task_requests()))
        self.mock.requests.clear()
        both = self.cli("tasks", "--mine", "--created-by-me", "--status", "incomplete", "--all", "--json")
        self.assertEqual(self.ids(both), ["7201", "7205"])
        self.assertEqual(self.calls().count(CURRENT), 1)

    def test_the_text_of_a_task_is_plain_without_the_mention_and_the_address(self):
        text = self.cli("tasks", "--all").out
        self.assertIn("Check the numbers with @user", text)
        self.assertIn("Mail [email] about the plan", text)
        self.assertIn("Announce the release", text)

    def test_what_is_refused_is_refused_before_any_request(self):
        for argv, code in ((("--due-before", "2026-02-30"), 2), (("--due-after", "2026-11-01", "--due-before", "2026-10-01"), 2), (("--status", "done"), 2), (("--limit", "0"), 2), (("--page", "2002/../1"), 1), (("--space", "E N G"), 1)):
            with self.subTest(argv=argv):
                self.assertEqual(self.cli("tasks", *argv).code, code)
        self.assertEqual(self.mock.requests, [])

    def test_a_space_a_page_or_content_that_is_not_there_is_not_found_or_refused_and_no_task_is_asked_for(self):
        self.assertEqual(self.cli("tasks", "--space", "NOPE").code, 4)
        self.assertEqual(self.cli("tasks", "--page", "99999").code, 4)
        folder = self.cli("tasks", "--page", "7001")
        self.assertEqual(folder.code, 1)
        self.assertIn("a folder", folder.err)
        self.assertEqual(self.task_requests(), [])

    def test_a_cursor_cannot_change_the_path_or_the_other_parameters(self):
        result = self.cli("tasks", "--cursor", "../../x?limit=1&status=complete#y")
        self.assertEqual(result.code, 6)  # the mock refuses a cursor that is no number, and says so
        (request,) = self.task_requests()
        self.assertEqual(request.path, "/api/v2/tasks")
        self.assertEqual(request.query, {"body-format": ["storage"], "cursor": ["../../x?limit=1&status=complete#y"], "limit": ["25"]})

    def test_the_ids_are_the_task_id_parameter_and_nothing_else_is_asked(self):
        result = self.cli("tasks", "--task", "7203", "--task", "7201", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.calls(), [("GET", "/api/v2/tasks")])
        self.assertEqual(self.task_requests()[0].query, {"body-format": ["storage"], "task-id": ["7203,7201"], "limit": ["25"]})
        data = result.json()
        self.assertEqual((self.ids(result), data["count"], data["nextCursor"], data["space"], data["truncated"]), (["7201", "7203"], 2, None, None, False))
        self.assertEqual(self.mock.used_endpoints, ["GET /api/v2/tasks"])
        self.nothing_unknown()

    def test_one_task_is_read_by_its_id_with_a_read_and_nothing_else(self):
        result = self.cli("tasks", "--task", "7202", "--json")
        (task,) = result.json()["tasks"]
        self.assertEqual((task["id"], task["status"], task["text"], task["pageId"]), ("7202", "complete", "Publish the release notes", "2002"))
        self.assertEqual([item.method for item in self.mock.requests], ["GET"])
        self.assertEqual(self.writes(), [])

    def test_an_id_that_is_given_twice_or_with_zeros_is_sent_once(self):
        self.cli("tasks", "--task", "7201", "--task", " 7201", "--task", "07201", "--json")
        self.assertEqual(self.task_requests()[0].query["task-id"], ["7201"])

    def test_an_id_that_no_task_has_is_not_in_the_list_and_is_no_error(self):
        both = self.cli("tasks", "--task", "7288", "--task", "7201", "--json")
        self.assertEqual((both.code, self.ids(both)), (0, ["7201"]))
        none = self.cli("tasks", "--task", "7288", "--json")
        self.assertEqual((none.code, none.json()["count"], none.json()["tasks"]), (0, 0, []))
        self.assertEqual(self.cli("tasks", "--task", "7288").out, "No tasks.\n")

    def test_the_ids_go_with_the_other_filters_and_each_of_them_has_to_hold(self):
        result = self.cli("tasks", "--task", "7201", "--task", "7202", "--task", "7203", "--status", "incomplete", "--page", "2002", "--json")
        self.assertEqual(self.ids(result), ["7201"])
        query = self.task_requests()[-1].query
        self.assertEqual((query["task-id"], query["status"], query["page-id"]), (["7201,7202,7203"], ["incomplete"], ["2002"]))

    def test_the_ids_are_listed_in_pieces_and_every_piece_asks_for_the_same_ids(self):
        every = ("--task", "7201", "--task", "7202", "--task", "7203")
        first = self.cli("tasks", *every, "--json")
        self.assertEqual((self.ids(first), first.json()["nextCursor"]), (["7201", "7202"], "2"))
        self.mock.requests.clear()
        everything = self.cli("tasks", *every, "--all", "--json")
        self.assertEqual(self.ids(everything), ["7201", "7202", "7203"])
        self.assertEqual(len(self.task_requests()), 2)
        self.assertTrue(all(item.query["task-id"] == ["7201,7202,7203"] for item in self.task_requests()))  # the cursor does not take the filter away

    def test_250_ids_go_in_one_request_and_251_are_refused_before_any_request(self):
        many = [item for number in range(8000, 8251) for item in ("--task", str(number))]
        refused = self.cli("tasks", *many)
        self.assertEqual((refused.code, refused.out), (2, ""))
        self.assertEqual(self.mock.requests, [])
        allowed = self.cli("tasks", *many[:-2], "--json")
        self.assertEqual((allowed.code, allowed.json()["count"]), (0, 0))
        (request,) = self.task_requests()
        self.assertEqual(len(request.query["task-id"][0].split(",")), 250)
        self.nothing_unknown()

    def test_an_id_that_is_wrong_is_refused_before_any_request(self):
        for text in ("abc", "0", "7201,7202", "-1", "9223372036854775808", "7201;x", "../7201"):
            with self.subTest(text=text):
                self.assertEqual(self.cli("tasks", "--task", text).code, 2)
        self.assertEqual(self.mock.requests, [])

    def test_what_the_mock_does_not_allow_in_the_ids_it_refuses_as_the_document_says(self):
        too_many = ",".join(str(number) for number in range(8000, 8251))
        for value in (too_many, "1,x", "9223372036854775808", "-1", "1,,2"):
            result = self.cli("api", "GET", "api/v2/tasks", "--param", f"task-id={value}")
            with self.subTest(value=value[:30]):
                self.assertEqual(result.code, 6, result.err)
        self.assertEqual(self.cli("api", "GET", "api/v2/tasks", "--param", "task-id=" + ",".join(str(number) for number in range(8000, 8250)), "--json").code, 0)

    def test_a_task_that_is_nested_too_deeply_to_convert_or_full_of_controls_does_not_stop_the_list(self):
        self.area.add_task("", storage="<div>" * 200 + "x" + "</div>" * 200, task_id="7290")
        self.area.add_task("", storage="<span>ok\x1b[2J\u202e\x07 done</span>", task_id="7289")
        result = self.cli("tasks", "--all")
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("nests too deeply", result.out)
        self.assertNotIn("\x1b", result.out)
        self.assertIn("Update the docs home", result.out)
        data = self.cli("tasks", "--all", "--json")
        self.assertEqual(data.code, 0, data.err)
        texts = {task["id"]: task["text"] for task in data.json()["tasks"]}
        self.assertIn("nests too deeply", texts["7290"])

    def test_a_task_text_made_of_tags_that_never_end_is_converted_in_a_moment(self):
        started = time.perf_counter()
        self.area.add_task("", storage="<span>Before " + "<p <a <b " * 20_000 + " after</span>", task_id="7290")
        result = self.cli("tasks", "--all", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("Before", {task["id"]: task["text"] for task in result.json()["tasks"]}["7290"])
        self.assertLess(time.perf_counter() - started, 20)

    def test_an_answer_that_is_not_what_the_document_says_is_an_empty_list_and_not_a_crash(self):
        for body in ({"results": "x"}, {"results": [None, 5, "x", {"id": 5}]}, {"results": {}}):
            self.mock.fail_next("/api/v2/tasks", 200, method="GET", body=body)
            result = self.cli("tasks", "--json")
            with self.subTest(body=body):
                self.assertEqual(result.code, 0, result.err)
                self.assertLessEqual(result.json()["count"], 1)

    def test_an_answer_that_is_no_object_at_all_is_exit_code_7_and_not_a_list_that_looks_empty(self):
        for body in ([], "text", 5, True, [{"results": []}]):
            self.mock.fail_next("/api/v2/tasks", 200, method="GET", body=body)
            result = self.cli("tasks", "--json")
            with self.subTest(body=body):
                self.assertEqual((result.code, result.out), (7, ""))
                self.assertIn("where a JSON object was expected", result.err)

    def test_what_the_server_refuses_is_an_exit_code(self):
        for status, code in ((401, 5), (403, 5), (404, 4), (429, 7), (500, 7), (503, 7), (400, 6)):
            self.mock.fail_next("/api/v2/tasks", status, method="GET", body={"errors": [{"status": status, "title": "No", "detail": "Not this time"}]})
            with self.subTest(status=status):
                self.assertEqual(self.cli("tasks", env={"CONFLUENCE_RETRY": "0"}).code, code)  # a read is tried again after 429 and 503: not here

    def test_a_read_that_is_refused_once_with_429_is_tried_again(self):
        self.mock.fail_next("/api/v2/tasks", 429, method="GET", headers={"Retry-After": "0"})
        result = self.cli("tasks", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(len(self.task_requests()), 2)

    def test_a_cursor_that_never_ends_stops_after_the_one_that_repeats(self):
        looping = {"results": [{"id": "1", "status": "incomplete", "pageId": "2002", "body": {"storage": {"value": "<span>Again</span>"}}}], "_links": {"next": "/wiki/api/v2/tasks?cursor=2"}}
        self.mock.fail_next("/api/v2/tasks", 200, times=50, method="GET", body=looping)
        result = self.cli("tasks", "--all", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(len(self.task_requests()), 2)  # the first piece, and the one that its cursor names: that one names the same cursor again
        self.assertEqual(result.json()["count"], 2)


class PrivacyTest(TasksFlow):
    def test_nobody_is_named_unless_the_people_are_asked_for(self):
        for argv in (("tasks", "--all"), ("tasks", "--all", "--json"), ("tasks", "--mine", "--all"), ("task", "7202"), ("task", "7202", "--json"), ("task", "7202", "--complete", "--dry-run", "--json")):
            result = self.cli(*argv)
            with self.subTest(argv=argv):
                self.assertEqual(result.code, 0, result.err)
                for text in PEOPLE:
                    self.assertNotIn(text, result.out + result.err)
        self.assertEqual([item for item in self.mock.requests if item.path == "/api/v2/users-bulk"], [])

    def test_the_people_are_looked_up_once_for_all_the_tasks_and_named_when_asked_for(self):
        result = self.cli("tasks", "--all", "--with-users", "--json")
        self.assertEqual(result.code, 0, result.err)
        (lookup,) = [item for item in self.mock.requests if item.path == "/api/v2/users-bulk"]
        self.assertEqual(lookup.body, {"accountIds": sorted([ACCOUNT, SAM])})
        by_id = {task["id"]: task for task in result.json()["tasks"]}
        self.assertEqual(by_id["7201"]["assignedTo"], {"accountId": ACCOUNT, "displayName": "Alex Example", "email": "alex@example.com"})
        self.assertEqual(by_id["7202"]["assignedTo"], {"accountId": SAM, "displayName": "", "email": ""})  # the mock does not describe the second person
        self.assertEqual(by_id["7202"]["completedBy"]["accountId"], SAM)
        self.assertEqual(by_id["7201"]["text"], f"Check the numbers with @<{ACCOUNT}>")

    def test_the_policy_that_hides_people_refuses_before_any_request_and_still_lists_the_tasks(self):
        strict = {"CONFLUENCE_HIDE_USERS": "true"}
        refused = self.cli("tasks", "--with-users", env=strict)
        self.assertEqual((refused.code, refused.out), (1, ""))
        self.assertEqual(self.mock.requests, [])
        self.assertEqual(self.cli("tasks", "--all", "--json", env=strict).code, 0)

    def test_what_the_mock_adds_to_every_text_does_not_get_through(self):
        self.mock.taint = True
        for argv in (("tasks", "--all"), ("tasks", "--all", "--json"), ("tasks", "--all", "--format", "tsv"), ("task", "7204"), ("task", "7204", "--json"), ("task", "7204", "--complete", "--json")):
            result = self.cli(*argv)
            with self.subTest(argv=argv):
                self.assertEqual(result.code, 0, result.err)
                self.assertNotIn("alex@example.com", result.out + result.err)
                self.assertNotIn("Alex Example", result.out + result.err)
        self.assertIn("[email]", self.cli("task", "7204").out)

    def test_an_error_does_not_name_a_person_either(self):
        self.mock.taint = True
        result = self.cli("task", "99999")
        self.assertEqual(result.code, 4)
        for text in PEOPLE:
            self.assertNotIn(text, result.err)

    def test_what_the_mock_adds_to_every_text_does_not_get_through_when_the_tasks_are_asked_for_by_id(self):
        self.mock.taint = True
        for argv in (("--task", "7204"), ("--task", "7201", "--task", "7204", "--json"), ("--task", "7204", "--format", "tsv"), ("--task", "7202", "--mine", "--task", "7203")):
            result = self.cli("tasks", *argv)
            with self.subTest(argv=argv):
                self.assertEqual(result.code, 0, result.err)
                for text in PEOPLE:
                    self.assertNotIn(text, result.out + result.err)
        self.assertIn("[email]", self.cli("tasks", "--task", "7204").out)
        shown = self.cli("tasks", "--task", "7201", "--with-users", "--json")
        self.assertEqual(shown.json()["tasks"][0]["assignedTo"]["accountId"], ACCOUNT)

    def test_the_policy_that_hides_people_still_reads_the_tasks_by_id_and_refuses_the_people(self):
        strict = {"CONFLUENCE_HIDE_USERS": "true"}
        self.assertEqual(self.cli("tasks", "--task", "7201", "--json", env=strict).code, 0)
        self.mock.requests.clear()
        refused = self.cli("tasks", "--task", "7201", "--with-users", env=strict)
        self.assertEqual((refused.code, refused.out), (1, ""))
        self.assertEqual(self.mock.requests, [])


class ShowTest(TasksFlow):
    def test_one_task_is_one_get_with_the_text_in_storage_format(self):
        result = self.cli("task", "7201", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.calls(), [("GET", "/api/v2/tasks/7201")])
        self.assertEqual(self.mock.requests[0].query, {"body-format": ["storage"]})
        data = result.json()
        self.assertEqual((data["id"], data["status"], data["pageId"], data["text"], data["dueAt"]), ("7201", "incomplete", "2002", "Check the numbers with @user", "2026-10-20T00:00:00.000Z"))
        self.nothing_unknown()

    def test_a_task_that_is_not_there_is_not_found(self):
        result = self.cli("task", "99999")
        self.assertEqual((result.code, result.out), (4, ""))
        self.assertEqual(self.calls(), [("GET", "/api/v2/tasks/99999")])

    def test_an_id_that_is_wrong_is_refused_before_any_request(self):
        for text in ("abc", "7201;x", "7201/../7202", "-1", "", "9" * 25):
            with self.subTest(text=text):
                self.assertIn(self.cli("task", text).code, (1, 2))
        self.assertEqual(self.mock.requests, [])

    def test_an_answer_without_an_id_is_an_error_and_not_a_task_that_looks_empty(self):
        self.mock.fail_next("/api/v2/tasks/7201", 200, method="GET", body={"status": "complete"})
        result = self.cli("task", "7201")
        self.assertEqual(result.code, 7)
        self.assertIn("not with task 7201", result.err)


class ChangeTest(TasksFlow):
    def test_a_change_is_the_task_read_the_status_put_and_the_task_read_again(self):
        result = self.cli("task", "7201", "--complete", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.calls(), [("GET", "/api/v2/tasks/7201"), ("PUT", "/api/v2/tasks/7201"), ("GET", "/api/v2/tasks/7201")])
        data = result.json()
        self.assertEqual((data["action"], data["dryRun"], data["readBack"], data["statusFrom"], data["statusTo"], data["task"]["status"]), ("completed", False, True, "incomplete", "complete", "complete"))
        self.assertEqual(self.area.tasks["7201"]["status"], "complete")
        self.assertEqual(self.area.changes, [("7201", "complete")])
        self.assertIn("PUT /api/v2/tasks/{id}", self.mock.used_endpoints)
        self.nothing_unknown()

    def test_the_request_carries_the_status_and_nothing_else(self):
        self.cli("task", "7201", "--complete")
        (put,) = self.writes()
        self.assertEqual((put.method, put.path, put.query), ("PUT", "/api/v2/tasks/7201", {"body-format": ["storage"]}))
        self.assertEqual(put.body, {"status": "complete"})
        self.assertEqual(put.raw, b'{"status": "complete"}')
        self.assertEqual(put.headers.get("content-type"), "application/json")

    def test_a_task_goes_back_with_reopen_and_its_completion_goes_with_it(self):
        self.cli("task", "7202", "--reopen")
        (put,) = self.writes()
        self.assertEqual(put.body, {"status": "incomplete"})
        task = self.area.tasks["7202"]
        self.assertEqual((task["status"], task["completedAt"], task["completedBy"]), ("incomplete", "", ""))

    def test_completing_a_task_sets_when_it_was_done_and_by_whom_and_none_of_it_is_named(self):
        done = self.cli("task", "7201", "--complete", "--json").json()
        self.assertTrue(done["task"]["completedAt"])
        self.assertEqual((self.area.tasks["7201"]["completedBy"], done["task"]["completedBy"]), (ACCOUNT, None))

    def test_a_dry_run_reads_the_task_and_sends_nothing(self):
        result = self.cli("task", "7201", "--complete", "--dry-run", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.calls(), [("GET", "/api/v2/tasks/7201")])
        self.assertEqual((self.writes(), self.area.changes, self.area.tasks["7201"]["status"]), ([], [], "incomplete"))
        data = result.json()
        self.assertEqual((data["action"], data["dryRun"], data["readBack"], data["payload"]), ("completed", True, False, {"status": "complete"}))

    def test_what_the_dry_run_showed_is_what_was_sent(self):
        preview = self.cli("task", "7203", "--complete", "--dry-run", "--json").json()["payload"]
        self.cli("task", "7203", "--complete")
        (put,) = self.writes()
        self.assertEqual(put.body, preview)

    def test_a_task_that_is_in_the_state_asked_for_is_left_alone_dry_run_or_not(self):
        for extra in ((), ("--dry-run",)):
            self.mock.requests.clear()
            result = self.cli("task", "7202", "--complete", *extra, "--json")
            with self.subTest(extra=extra):
                self.assertEqual((result.json()["action"], result.json()["payload"]), ("unchanged", None))
                self.assertEqual(self.calls(), [("GET", "/api/v2/tasks/7202")])
        self.assertEqual(self.area.changes, [])

    def test_the_same_change_twice_is_one_change(self):
        self.cli("task", "7201", "--complete")
        again = self.cli("task", "7201", "--complete", "--json")
        self.assertEqual(again.json()["action"], "unchanged")
        self.assertEqual(self.area.changes, [("7201", "complete")])

    def test_a_task_that_is_not_there_is_not_found_and_nothing_is_sent(self):
        self.assertEqual(self.cli("task", "99999", "--complete").code, 4)
        self.assertEqual(self.writes(), [])

    def test_a_refusal_of_the_change_is_an_exit_code_and_leaves_the_task_as_it_was(self):
        for status, code in ((403, 5), (404, 4), (400, 6), (500, 7), (409, 3)):
            self.mock.fail_next("/api/v2/tasks/7201", status, method="PUT", body={"errors": [{"status": status, "title": "No", "detail": "Not this time"}]})
            with self.subTest(status=status):
                self.assertEqual(self.cli("task", "7201", "--complete").code, code)
        self.assertEqual((self.area.tasks["7201"]["status"], self.area.changes), ("incomplete", []))

    def test_a_change_that_cannot_be_read_back_is_still_a_change_with_exit_code_0_and_a_warning(self):
        self.area.read_back_fails = True
        result = self.cli("task", "7201", "--complete")
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("Completed task 7201", result.out)
        self.assertIn("could not be read back", result.err)
        self.assertEqual(self.area.tasks["7201"]["status"], "complete")
        self.area.read_back_fails = True
        data = self.cli("task", "7201", "--reopen", "--json").json()
        self.assertEqual((data["action"], data["readBack"], len(data["notes"])), ("reopened", False, 1))

    def test_a_read_back_that_is_refused_is_a_note_and_the_one_after_it_is_not_refused(self):
        self.area.read_back_refusal = RequestError(403, "Forbidden", "No access to this task now", code="FORBIDDEN")
        first = self.cli("task", "7201", "--complete", "--json")
        self.assertEqual(first.code, 0, first.err)
        data = first.json()
        self.assertEqual((data["action"], data["readBack"], len(data["notes"])), ("completed", False, 1))
        self.assertIn("could not be read back", data["notes"][0])
        self.assertIsNone(self.area.read_back_refusal)  # used up by that read
        second = self.cli("task", "7201", "--reopen", "--json").json()
        self.assertEqual((second["action"], second["readBack"], second["notes"]), ("reopened", True, []))

    def test_both_flags_together_or_a_dry_run_alone_ask_for_nothing(self):
        self.assertEqual(self.cli("task", "7201", "--complete", "--reopen").code, 2)
        self.assertEqual(self.cli("task", "7201", "--dry-run").code, 2)
        self.assertEqual(self.mock.requests, [])

    def test_the_only_thing_that_is_ever_written_is_the_status_of_one_task(self):
        for argv in (("task", "7201", "--complete"), ("task", "7202", "--reopen"), ("task", "7201", "--complete", "--dry-run"), ("tasks", "--mine", "--all"), ("tasks", "--page", "2002", "--with-users"), ("task", "7203")):
            self.cli(*argv)
        self.assertEqual({(item.method, item.path) for item in self.mock.requests if item.method != "GET" and item.path != TYPES[1] and item.path != "/api/v2/users-bulk"}, {("PUT", "/api/v2/tasks/7201"), ("PUT", "/api/v2/tasks/7202")})
        self.assertEqual({item.method for item in self.mock.requests} - {"GET", "POST", "PUT"}, set())
        self.assertEqual({item.body["status"] for item in self.mock.requests if item.method == "PUT" and item.path.startswith("/api/v2/tasks/")}, {"complete", "incomplete"})
        self.assertTrue(all(set(item.body) == {"status"} for item in self.mock.requests if item.method == "PUT"))


class FixturesTest(unittest.TestCase):
    """The fake and the mock hold the same tasks, so that what a test shows against one holds against the other."""

    def test_the_mock_and_the_fake_agree(self):
        from tests.support.mock_confluence import MockConfluence

        mock = MockConfluence()
        try:
            area = mock.area(TasksRoutes)
            fake = FakeGateway()
            self.assertEqual(sorted(area.tasks), sorted(fake.tasks))
            for task_id, task in fake.tasks.items():
                with self.subTest(task=task_id):
                    shown = area.tasks[task_id]
                    self.assertEqual(
                        (shown["status"], shown["pageId"], shown["blogPostId"], shown["spaceId"], shown["dueAt"], shown["createdBy"] == (task.created_by.account_id if task.created_by else ""),
                         shown["assignedTo"] == (task.assigned_to.account_id if task.assigned_to else "")),
                        (task.status, task.page_id, task.blogpost_id, task.space_id, task.due, True, True),
                    )
            self.assertEqual(FAKE_SAM.account_id, SAM)
            self.assertEqual(mock.content_kinds[BLOG_POST], fake.content_kinds[BLOG_POST])
        finally:
            mock.stop()


if __name__ == "__main__":
    unittest.main()
