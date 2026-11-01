"""The labels used in a space, against the in-memory Confluence: the use case, what an answer of the REST API means, and the call that asks for them."""
import unittest

from conflu_c_cli.adapters.driven import map_labels as mapping
from conflu_c_cli.adapters.driven.rest_labels import V1_CALLS, RestLabels
from conflu_c_cli.adapters.driven.rest_support import next_cursor
from conflu_c_cli.application.paging import MAX_ITEMS, PAGE_SIZE
from conflu_c_cli.domain.errors import NotFoundError, ValidationError
from conflu_c_cli.domain.model import Label
from tests.support.fakes import FakeGateway, build_app


def app_for(gateway=None):
    gateway = gateway or FakeGateway()
    return build_app(gateway=gateway), gateway


class SpaceLabelsTest(unittest.TestCase):
    """The default pages of the fake: `release` and `notes` on 2002, `adr` on 2004, both in the space ENG; the space DOCS has none."""

    def setUp(self):
        self.app, self.gateway = app_for()

    def labels(self, key="ENG", **options):
        return self.app.labels.in_space.execute(key, **options)

    def test_the_labels_of_the_content_of_a_space_come_by_name_a_piece_at_a_time(self):
        result = self.labels()
        self.assertEqual([label.name for label in result.labels], ["adr", "notes"])
        self.assertEqual((result.space.key, result.space.id, result.next_cursor, result.truncated), ("ENG", "1001", "2", False))

    def test_the_cursor_of_a_piece_continues_where_it_stopped_and_the_last_piece_has_none(self):
        result = self.labels(cursor="2")
        self.assertEqual(([label.name for label in result.labels], result.next_cursor), (["release"], ""))

    def test_all_reads_every_piece_in_the_biggest_size_and_ignores_limit_and_cursor(self):
        result = self.labels(fetch_everything=True, limit=1, cursor="2")
        self.assertEqual([label.name for label in result.labels], ["adr", "notes", "release"])
        self.assertEqual((result.next_cursor, result.truncated), ("", False))
        self.assertEqual([call[2:] for call in self.gateway.called("list_space_labels")], [(PAGE_SIZE, ""), (PAGE_SIZE, "2")])

    def test_the_limit_is_the_size_of_the_piece_that_is_asked_for(self):
        self.labels(limit=7)
        self.assertEqual(self.gateway.called("list_space_labels"), [("list_space_labels", "1001", 7, "")])

    def test_the_space_is_looked_up_by_its_key_whatever_the_case(self):
        self.assertEqual(self.labels("eng").space.key, "ENG")
        self.assertEqual(self.gateway.called("get_space"), [("get_space", "eng")])

    def test_a_space_that_has_no_labels_in_use_is_an_empty_list(self):
        result = self.labels("DOCS")
        self.assertEqual((result.labels, result.next_cursor, result.space.id), ([], "", "1002"))

    def test_a_space_that_does_not_exist_is_not_found_and_the_labels_are_not_asked_for(self):
        with self.assertRaises(NotFoundError):
            self.labels("NOPE")
        self.assertEqual(self.gateway.called("list_space_labels"), [])

    def test_what_is_no_space_key_is_refused_before_any_request(self):
        for key in ("", "   ", "E N G", "ENG/../x", "ENG?x=1", "-ENG", "ENG\nDOCS"):
            with self.subTest(key=key):
                with self.assertRaises(ValidationError):
                    self.labels(key)
        self.assertEqual(self.gateway.calls, [])

    def test_a_label_that_many_pages_carry_is_listed_once(self):
        self.gateway.pages["2003"].labels.append(Label("notes"))
        self.assertEqual([label.name for label in self.labels(fetch_everything=True).labels], ["adr", "notes", "release"])

    def test_the_same_name_with_two_prefixes_is_two_labels(self):
        self.gateway.pages["2003"].labels.append(Label("notes", "team"))
        found = self.labels(fetch_everything=True).labels
        self.assertEqual([(label.name, label.prefix) for label in found], [("adr", "global"), ("notes", "global"), ("notes", "team"), ("release", "global")])

    def test_a_list_that_never_ends_is_cut_and_says_so(self):
        self.gateway.page_cap = 5000
        self.gateway.pages["2005"].labels = [Label(f"label{number:05d}") for number in range(MAX_ITEMS + 100)]
        result = self.labels(fetch_everything=True)
        self.assertEqual((len(result.labels), result.truncated, result.next_cursor), (MAX_ITEMS, True, ""))

    def test_a_failure_of_confluence_passes_unchanged(self):
        self.gateway.errors["list_space_labels"] = NotFoundError("Not found: GET /api/v2/spaces/1001/content/labels", details={"status": 404})
        with self.assertRaises(NotFoundError):
            self.labels()


class PageLabelsTest(unittest.TestCase):
    """What was there before the space: the labels of one page, and adding and removing them. They stay as they were."""

    def setUp(self):
        self.app, self.gateway = app_for()

    def test_the_labels_of_a_page_are_listed_whole(self):
        self.assertEqual([label.name for label in self.app.list_labels.execute("2002")], ["release", "notes"])

    def test_labels_are_added_and_removed_in_one_call_and_the_ones_that_are_there_or_not_are_skipped(self):
        result = self.app.change_labels.execute("2002", add=["Reviewed", "notes"], remove=["release", "absent"])
        self.assertEqual((result.added, result.removed), (["reviewed"], ["release"]))
        self.assertEqual([label.name for label in result.labels], ["notes", "reviewed"])
        self.assertEqual(result.payload, {"add": [{"prefix": "global", "name": "reviewed"}], "remove": ["release"]})

    def test_the_dry_run_sends_nothing(self):
        result = self.app.change_labels.execute("2002", add=["reviewed"], remove=["notes"], dry_run=True)
        self.assertEqual((result.dry_run, result.added, result.removed), (True, ["reviewed"], ["notes"]))
        self.assertEqual((self.gateway.called("add_labels"), self.gateway.called("remove_label")), ([], []))

    def test_nothing_to_add_or_remove_and_a_label_in_both_are_refused(self):
        with self.assertRaises(ValidationError):
            self.app.change_labels.execute("2002", add=[], remove=[])
        with self.assertRaises(ValidationError) as caught:
            self.app.change_labels.execute("2002", add=["x"], remove=["x"])
        self.assertIn("is in --add and in --remove", caught.exception.message)


class AnswerTest(unittest.TestCase):
    def test_the_labels_of_an_answer_with_their_prefix(self):
        data = {"results": [{"id": "1", "name": "adr", "prefix": "global"}, {"id": "2", "name": "mine", "prefix": "my"}]}
        self.assertEqual(mapping.labels_of(data), [Label("adr", "global"), Label("mine", "my")])

    def test_a_label_without_a_prefix_is_a_global_one(self):
        self.assertEqual(mapping.labels_of({"results": [{"name": "adr"}]}), [Label("adr", "global")])

    def test_what_is_no_label_is_left_out_and_an_answer_of_the_wrong_shape_is_an_empty_list(self):
        self.assertEqual(mapping.labels_of({"results": [{"id": "1"}, {"name": ""}, {"name": None}, "text", 5, None, {"name": "ok"}]}), [Label("ok", "global")])
        for data in (None, [], "text", 5, {}, {"results": "x"}, {"results": None}):
            with self.subTest(data=data):
                self.assertEqual(mapping.labels_of(data), [])


class Recorder(RestLabels):
    """The mixin without a server: it keeps what it is asked to send and answers what the test has queued."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.sent = []

    def _call(self, method, path, body=None, **options):
        self.sent.append((method, path, body))
        return self.answers.pop(0)

    @staticmethod
    def _next_cursor(data):
        return next_cursor(data)


class RestCallTest(unittest.TestCase):
    def test_the_labels_of_the_content_of_a_space_are_asked_for_by_name_with_the_cursor_of_the_piece(self):
        rest = Recorder({"results": [{"name": "adr", "prefix": "global"}], "_links": {"next": "/wiki/api/v2/spaces/1001/content/labels?cursor=abc"}})
        chunk = rest.list_space_labels("1001", limit=25, cursor="x y")
        self.assertEqual(rest.sent, [("GET", "/api/v2/spaces/1001/content/labels?sort=name&limit=25&cursor=x%20y", None)])
        self.assertEqual(([label.name for label in chunk.items], chunk.cursor), (["adr"], "abc"))

    def test_the_last_piece_has_no_cursor(self):
        rest = Recorder({"results": []})
        chunk = rest.list_space_labels("1001")
        self.assertEqual(rest.sent[0][1], "/api/v2/spaces/1001/content/labels?sort=name&limit=25")
        self.assertEqual((chunk.items, chunk.cursor), ([], ""))

    def test_the_space_id_is_quoted_so_that_it_cannot_change_the_path(self):
        rest = Recorder({"results": []})
        rest.list_space_labels("1001/../x")
        self.assertTrue(rest.sent[0][1].startswith("/api/v2/spaces/1001%2F..%2Fx/content/labels?"))

    def test_this_area_calls_no_v1_api_of_its_own(self):
        self.assertEqual(V1_CALLS, {})


if __name__ == "__main__":
    unittest.main()
