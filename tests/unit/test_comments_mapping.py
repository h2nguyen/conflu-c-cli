"""What the answers of the REST API v2 for one comment mean, and what the calls of the comment area send: one answer in, domain objects out; one call in, its request out."""
import unittest

from conflu_c_cli.adapters.driven import map_comments as mapping
from conflu_c_cli.adapters.driven.rest_comments import KINDS, V1_CALLS, RestComments
from conflu_c_cli.adapters.driven.rest_support import next_cursor
from conflu_c_cli.domain.comments import CommentRecord
from conflu_c_cli.domain.errors import AuthError, NotFoundError
from conflu_c_cli.domain.model import Comment, User

ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"
ANSWER = {
    "id": "4102",
    "status": "current",
    "title": "Re: ADR 0001",
    "pageId": "2004",
    "parentCommentId": "4101",
    "version": {"number": 3, "createdAt": "2026-10-14T09:00:00.000Z", "message": "", "minorEdit": False, "authorId": ACCOUNT},
    "resolutionStatus": "reopened",
    "body": {"storage": {"representation": "storage", "value": "<p>Is this still true?</p>"}},
    "_links": {"webui": "/spaces/ENG/pages/2004#comment-4102"},
}


class AnswerTest(unittest.TestCase):
    def test_an_inline_comment_with_everything_the_answer_says(self):
        self.assertEqual(
            mapping.comment_of(ANSWER, "inline"),
            Comment("4102", "inline", "2026-10-14T09:00:00.000Z", "<p>Is this still true?</p>", 3, User(ACCOUNT), "4101", "reopened"),
        )

    def test_the_kind_is_the_collection_that_was_asked_not_something_the_answer_says(self):
        self.assertEqual(mapping.comment_of(ANSWER, "footer").kind, "footer")

    def test_the_time_is_the_one_of_the_current_version_so_it_is_when_the_comment_was_saved(self):
        self.assertEqual(mapping.comment_of({"id": "1", "version": {"number": 2, "createdAt": "2026-10-15T08:30:00.000Z"}}, "footer").updated, "2026-10-15T08:30:00.000Z")

    def test_what_the_answer_leaves_out_is_empty_and_not_an_error(self):
        comment = mapping.comment_of({"id": 4001}, "footer")
        self.assertEqual(comment, Comment("4001", "footer", "", "", 1, None, "", ""))

    def test_a_top_level_comment_has_no_parent_and_a_footer_comment_no_resolution(self):
        comment = mapping.comment_of({"id": "1", "parentCommentId": None, "resolutionStatus": None}, "footer")
        self.assertEqual((comment.parent_id, comment.resolution), ("", ""))

    def test_an_answer_of_the_wrong_shape_gives_an_empty_comment_and_not_a_crash(self):
        for data in (None, [], "text", 5, {"id": "1", "version": "x", "body": ["y"]}):
            with self.subTest(data=data):
                comment = mapping.comment_of(data, "inline")
                self.assertEqual((comment.kind, comment.body, comment.version, comment.author), ("inline", "", 1, None))

    def test_a_record_names_the_page_the_comment_is_on(self):
        self.assertEqual(mapping.record_of(ANSWER, "inline"), CommentRecord(mapping.comment_of(ANSWER, "inline"), "2004"))
        self.assertEqual(mapping.record_of({**ANSWER, "pageId": 2004}, "inline").page_id, "2004")

    def test_a_comment_on_a_blog_post_or_an_attachment_is_on_no_page(self):
        for data in ({"id": "1", "blogPostId": "9"}, {"id": "1", "pageId": None, "attachmentId": "att1"}, {"id": "1"}, None):
            with self.subTest(data=data):
                self.assertEqual(mapping.record_of(data, "footer").page_id, "")


class Recorder(RestComments):
    """The mixin without a server: it keeps what it is asked to send and answers what the test has queued."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.sent = []

    def _call(self, method, path, body=None, **options):
        self.sent.append((method, path, body))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    @staticmethod
    def _next_cursor(data):
        return next_cursor(data)


def missing(path="/api/v2/footer-comments/4102"):
    return NotFoundError(f"Not found: GET {path}", details={"status": 404})


class RestCallsTest(unittest.TestCase):
    def test_a_footer_comment_is_asked_for_first_with_its_text_in_storage_format(self):
        rest = Recorder(ANSWER)
        record = rest.get_comment("4102")
        self.assertEqual(rest.sent, [("GET", "/api/v2/footer-comments/4102?body-format=storage", None)])
        self.assertEqual((record.comment.kind, record.page_id), ("footer", "2004"))

    def test_a_404_sends_the_question_on_to_the_inline_comments(self):
        rest = Recorder(missing(), ANSWER)
        record = rest.get_comment("4102")
        self.assertEqual([path for _, path, _ in rest.sent], ["/api/v2/footer-comments/4102?body-format=storage", "/api/v2/inline-comments/4102?body-format=storage"])
        self.assertEqual(record.comment.kind, "inline")

    def test_a_404_from_both_is_the_answer_and_it_names_the_id(self):
        rest = Recorder(missing(), missing("/api/v2/inline-comments/4102"))
        with self.assertRaises(NotFoundError) as caught:
            rest.get_comment("4102")
        self.assertEqual(caught.exception.message, "No comment with the id 4102.")
        self.assertEqual(caught.exception.details, {"status": 404, "commentId": "4102"})
        self.assertEqual(len(rest.sent), 2)

    def test_any_other_failure_stops_the_search_at_once(self):
        rest = Recorder(AuthError("Confluence refused this request (HTTP 403).", details={"status": 403}))
        with self.assertRaises(AuthError):
            rest.get_comment("4102")
        self.assertEqual(len(rest.sent), 1)

    def test_an_id_is_quoted_so_that_it_cannot_change_the_path(self):
        rest = Recorder(ANSWER)
        rest.get_comment("4102/../../pages/1")
        self.assertEqual(rest.sent[0][1], "/api/v2/footer-comments/4102%2F..%2F..%2Fpages%2F1?body-format=storage")

    def test_a_change_is_a_put_to_the_collection_of_its_kind_with_the_payload_as_it_is(self):
        payload = {"version": {"number": 4}, "body": {"representation": "storage", "value": "<p>x</p>"}, "resolved": True}
        for kind in KINDS:
            with self.subTest(kind=kind):
                rest = Recorder(ANSWER)
                comment = rest.update_comment("4102", kind, payload)
                self.assertEqual(rest.sent, [("PUT", f"/api/v2/{kind}-comments/4102", payload)])
                self.assertEqual(comment.kind, kind)
                self.assertEqual(comment.version, 3)

    def test_a_kind_that_is_none_of_the_two_is_a_mistake_of_the_program_and_sends_nothing(self):
        rest = Recorder(ANSWER)
        for kind in ("", "page", "footer-comments", "../x"):
            with self.assertRaises(ValueError):
                rest.update_comment("4102", kind, {})
        self.assertEqual(rest.sent, [])

    def test_the_inline_comments_of_a_page_may_be_asked_for_by_resolution(self):
        rest = Recorder({"results": [ANSWER], "_links": {"next": "/wiki/api/v2/pages/2004/inline-comments?cursor=abc"}})
        chunk = rest.list_inline_comments("2004", resolution="open", limit=100, cursor="x y")
        self.assertEqual(rest.sent, [("GET", "/api/v2/pages/2004/inline-comments?body-format=storage&resolution-status=open&sort=created-date&limit=100&cursor=x%20y", None)])
        self.assertEqual(([item.id for item in chunk.items], chunk.cursor, chunk.items[0].kind), (["4102"], "abc", "inline"))

    def test_without_a_resolution_there_is_no_filter(self):
        rest = Recorder({"results": []})
        chunk = rest.list_inline_comments("2004")
        self.assertEqual(rest.sent[0][1], "/api/v2/pages/2004/inline-comments?body-format=storage&sort=created-date&limit=50")
        self.assertEqual((chunk.items, chunk.cursor), ([], ""))

    def test_the_page_id_of_a_list_is_quoted_too(self):
        rest = Recorder({"results": []})
        rest.list_inline_comments("2004/../x")
        self.assertTrue(rest.sent[0][1].startswith("/api/v2/pages/2004%2F..%2Fx/inline-comments?"))

    def test_this_area_calls_no_v1_api_of_its_own(self):
        self.assertEqual(V1_CALLS, {})


if __name__ == "__main__":
    unittest.main()
