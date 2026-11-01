"""What the page of a proxy that answers a WRITE means for the person: the change may have been made all the same, so the hint says to look before repeating
it; for a read it still says to try again."""
from tests.integration import test_properties_flow as flow
from tests.integration.test_unreadable_answers import PROXY_PAGE, _Answer


class UnreadableAnswerHintTest(flow.PropertiesFlow):
    def answered(self, method, pattern):
        answer = _Answer(self.mock, method, pattern, PROXY_PAGE, 200, "text/html")
        self.mock.extensions.insert(0, answer)  # asked before the routes of the mock
        return answer

    def assert_look_first(self, result):
        self.assertEqual((result.code, result.out), (7, ""), result.err)
        self.assertIn("the change may have been made all the same", result.err)
        self.assertIn("before you repeat it", result.err)
        self.assertNotIn("then try again", result.err)

    def test_a_comment_whose_answer_is_a_proxy_page_says_to_look_before_it_is_repeated(self):
        answer = self.answered("POST", r"/api/v2/footer-comments")
        self.assert_look_first(self.cli("comment", "2002", "--text", "hello once"))
        self.assertEqual(answer.hits, 1)

    def test_an_upload_whose_answer_is_a_proxy_page_says_it_too(self):
        target = self.root / "report.txt"
        target.write_text("text", encoding="utf-8")
        self.answered("PUT", r"/rest/api/content/2002/child/attachment")
        self.assert_look_first(self.cli("attach", "2002", str(target)))

    def test_the_property_and_the_task_say_it_too(self):
        self.answered("POST", r"/api/v2/pages/2002/properties")
        self.assert_look_first(self.cli("property-set", "2002", "--key", "zz.new", "--value", "1"))
        self.answered("PUT", r"/api/v2/tasks/7203")
        self.assert_look_first(self.cli("task", "7203", "--complete"))

    def test_the_raw_call_that_writes_says_it_too(self):
        self.answered("POST", r"/api/v2/footer-comments")
        result = self.cli("api", "POST", "api/v2/footer-comments", "--data", '{"pageId":"2002","body":{"representation":"storage","value":"<p>x</p>"}}', "--write")
        self.assert_look_first(result)

    def test_a_read_answered_by_a_proxy_page_still_says_to_try_again(self):
        self.answered("GET", r"/api/v2/pages/2002")
        result = self.cli("page", "2002")
        self.assertEqual(result.code, 7, result.err)
        self.assertIn("then try again", result.err)
        self.assertNotIn("may have been made", result.err)
