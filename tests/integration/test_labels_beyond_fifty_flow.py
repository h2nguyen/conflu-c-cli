"""A page with more labels than one answer holds is shown with all of them; when the call that reads the rest is refused or fails, the page is shown
with the labels it has and a warning says so, as 1.0.0 showed the page (it asked for no more) instead of failing as a whole."""
from tests.integration.test_end_to_end import EndToEnd


class LabelsBeyondFiftyFlow(EndToEnd):
    def setUp(self):
        super().setUp()
        self.mock.page_cap = 100
        self.names = tuple(f"label-{number:03d}" for number in range(60))
        self.page_id = self.mock.add_page("ENG", "Many labels", labels=self.names)

    def labels_of(self, result):
        return sorted(item for item in result.json()["labels"])

    def test_every_label_is_read_when_the_second_call_works(self):
        result = self.cli("page", self.page_id, "--json", "--no-body")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.labels_of(result), sorted(self.names))
        self.assertNotIn("labels of the page are shown", result.err)

    def test_the_page_is_shown_with_its_fifty_labels_when_the_second_call_is_refused_or_fails(self):
        for status in (403, 404, 429, 500):
            with self.subTest(status=status):
                self.mock.fail_next(f"/api/v2/pages/{self.page_id}/labels", status, times=4)  # the retries of a 429 or a 500 are failures too
                result = self.cli("page", self.page_id, "--json", "--no-body")
                self.assertEqual(result.code, 0, result.err)
                self.assertEqual(len(result.json()["labels"]), 50)
                self.assertIn("Only the first 50 labels of the page are shown: the rest could not be read", result.err)
                self.assertIn(f"conflu labels {self.page_id}", result.err)
                self.mock._failures.clear()

    def test_the_text_output_says_it_too_and_the_exit_code_stays_zero(self):
        self.mock.fail_next(f"/api/v2/pages/{self.page_id}/labels", 403)
        result = self.cli("page", self.page_id, "--no-body")
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("Only the first 50 labels", result.err)
        self.assertIn("Labels:", result.out)

    def test_an_earlier_version_carries_the_warning_of_the_current_page(self):
        self.mock.fail_next(f"/api/v2/pages/{self.page_id}/labels", 403)
        result = self.cli("page", self.page_id, "--version", "1", "--json", "--no-body")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(len(result.json()["labels"]), 50)
        self.assertIn("Only the first 50 labels", result.err)

    def test_a_page_of_the_first_call_is_not_blamed_when_the_page_itself_is_refused(self):
        self.mock.fail_next(f"/api/v2/pages/{self.page_id}", 403, method="GET")
        result = self.cli("page", self.page_id, "--json")
        self.assertEqual(result.code, 5, result.err)
