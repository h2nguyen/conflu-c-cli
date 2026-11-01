"""What the answers of the REST API v2 for tasks mean: one answer in, a domain object out."""
import unittest

from conflu_c_cli.adapters.driven import rest_tasks
from conflu_c_cli.adapters.driven.map_tasks import task_from
from conflu_c_cli.domain.model import User

ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"
OTHER = "5b10ac8d82e05b22cc7d4ea1"


def answer(**changes):
    data = {
        "id": "7202",
        "localId": "2",
        "spaceId": "1001",
        "pageId": "2002",
        "status": "complete",
        "body": {"storage": {"representation": "storage", "value": "<span>Publish the release notes</span>"}},
        "createdBy": ACCOUNT,
        "assignedTo": OTHER,
        "completedBy": OTHER,
        "createdAt": "2026-10-02T09:01:00.000Z",
        "updatedAt": "2026-10-09T12:00:00.000Z",
        "dueAt": "2026-10-10T00:00:00.000Z",
        "completedAt": "2026-10-09T12:00:00.000Z",
    }
    data.update(changes)
    return data


class TaskAnswerTest(unittest.TestCase):
    def test_a_task_of_a_page(self):
        task = task_from(answer())
        self.assertEqual((task.id, task.local_id, task.status, task.space_id, task.page_id, task.blogpost_id), ("7202", "2", "complete", "1001", "2002", ""))
        self.assertEqual(task.body, "<span>Publish the release notes</span>")
        self.assertEqual((task.created, task.updated, task.due, task.completed), ("2026-10-02T09:01:00.000Z", "2026-10-09T12:00:00.000Z", "2026-10-10T00:00:00.000Z", "2026-10-09T12:00:00.000Z"))

    def test_the_people_are_account_ids_and_nothing_more(self):
        task = task_from(answer())
        self.assertEqual((task.created_by, task.assigned_to, task.completed_by), (User(ACCOUNT), User(OTHER), User(OTHER)))
        self.assertEqual((task.created_by.display_name, task.created_by.email), ("", ""))  # a name is a lookup of its own

    def test_a_task_of_a_blog_post_has_no_page(self):
        task = task_from(answer(pageId=None, blogPostId="7290"))
        self.assertEqual((task.page_id, task.blogpost_id), ("", "7290"))

    def test_what_the_answer_leaves_out_is_empty_and_not_an_error(self):
        task = task_from({"id": "7203"})
        self.assertEqual((task.id, task.status, task.space_id, task.page_id, task.body, task.due, task.completed), ("7203", "", "", "", "", "", ""))
        self.assertEqual((task.created_by, task.assigned_to, task.completed_by), (None, None, None))

    def test_an_answer_that_is_no_object_is_a_task_without_an_id(self):
        for data in (None, "task", 7, [], [{"id": "1"}]):
            with self.subTest(data=data):
                self.assertEqual(task_from(data).id, "")

    def test_an_empty_person_is_nobody(self):
        task = task_from(answer(assignedTo="", completedBy=None))
        self.assertEqual((task.assigned_to, task.completed_by), (None, None))

    def test_a_person_that_is_no_text_is_nobody_and_is_not_turned_into_a_text(self):
        task = task_from(answer(createdBy={"accountId": ACCOUNT, "displayName": "Alex Example"}, assignedTo=42, completedBy=["x"]))
        self.assertEqual((task.created_by, task.assigned_to, task.completed_by), (None, None, None))

    def test_values_of_the_wrong_type_do_not_break_it(self):
        task = task_from(answer(id=7202, localId=2, status=None, body="text", dueAt=20261010, completedAt=None))
        self.assertEqual((task.id, task.local_id, task.status, task.body, task.due, task.completed), ("7202", "2", "", "", "20261010", ""))

    def test_a_body_in_another_format_is_no_body_here(self):
        task = task_from(answer(body={"atlas_doc_format": {"representation": "atlas_doc_format", "value": "{}"}}))
        self.assertEqual(task.body, "")

    def test_the_text_of_a_task_is_kept_as_it_came(self):
        text = "<span>Mail alex@example.com &amp; <ac:link><ri:user ri:account-id=\"%s\" /></ac:link></span>" % ACCOUNT
        self.assertEqual(task_from(answer(body={"storage": {"value": text}})).body, text)  # hiding people is the job of the use case


class ReasonsTest(unittest.TestCase):
    def test_v2_does_it_all_so_no_call_is_v1(self):
        self.assertEqual(rest_tasks.V1_CALLS, {})


if __name__ == "__main__":
    unittest.main()
