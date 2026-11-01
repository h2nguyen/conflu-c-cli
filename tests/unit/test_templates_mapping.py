"""What the answers of the older REST API (v1) for templates mean: one answer in, domain objects out, and where the next piece of a list starts."""
import unittest

from conflu_c_cli.adapters.driven import rest_templates
from conflu_c_cli.adapters.driven.map_templates import info_from, page_from, template_from
from conflu_c_cli.domain.templates import Template, TemplateInfo


def answer(**changes):
    data = {
        "templateId": "7402",
        "originalTemplate": {"pluginKey": "com.example.plugin", "moduleKey": "release-checklist"},
        "referencingBlueprint": "com.example.plugin:release-blueprint",
        "name": "Release checklist",
        "description": "Steps for every release",
        "space": {"id": 1001, "key": "ENG", "name": "Engineering"},
        "labels": [{"prefix": "global", "name": "release", "id": "1", "label": "release"}, {"prefix": "global", "name": "checklist", "id": "2", "label": "checklist"}],
        "templateType": "page",
        "editorVersion": "v2",
        "body": {"storage": {"value": "<p>Body</p>", "representation": "storage"}},
    }
    data.update(changes)
    return data


def listing(results, start=0, nxt=None, **changes):
    data = {"results": results, "start": start, "limit": 25, "size": len(results), "_links": {"base": "https://example.atlassian.net/wiki", "context": "/wiki"}}
    if nxt is not None:
        data["_links"]["next"] = nxt
    data.update(changes)
    return data


class TemplateAnswerTest(unittest.TestCase):
    def test_a_template_in_a_list_has_no_body(self):
        info = info_from(answer())
        self.assertEqual(info, TemplateInfo("7402", "Release checklist", "page", "Steps for every release", "ENG", ("release", "checklist"), "com.example.plugin:release-blueprint"))
        self.assertNotIn("body", vars(info))

    def test_a_template_that_was_read_has_its_body_in_storage_format(self):
        template = template_from(answer())
        self.assertEqual(template, Template("7402", "Release checklist", "page", "Steps for every release", "ENG", ("release", "checklist"), "com.example.plugin:release-blueprint", "<p>Body</p>"))
        self.assertIsInstance(template, TemplateInfo)

    def test_a_global_template_has_no_space_and_no_blueprint(self):
        info = info_from(answer(space=None, referencingBlueprint=None))
        self.assertEqual((info.space_key, info.blueprint), ("", ""))
        self.assertEqual(info_from({k: v for k, v in answer().items() if k not in ("space", "referencingBlueprint")}).space_key, "")

    def test_the_labels_are_their_names_and_what_is_no_label_is_left_out(self):
        self.assertEqual(info_from(answer(labels=[{"name": "a"}, {"label": "b"}, {}, {"name": ""}, "c", None, 7])).labels, ("a", "b"))
        for labels in (None, "release", {"name": "x"}, 5):
            with self.subTest(labels=labels):
                self.assertEqual(info_from(answer(labels=labels)).labels, ())

    def test_what_the_answer_leaves_out_is_empty_and_not_an_error(self):
        info = info_from({"templateId": "9"})
        self.assertEqual((info.id, info.name, info.type, info.description, info.space_key, info.labels, info.blueprint), ("9", "", "", "", "", (), ""))
        self.assertEqual(template_from({"templateId": "9"}).body, "")

    def test_values_of_the_wrong_type_do_not_break_it(self):
        info = info_from(answer(templateId=7402, name=None, description=5, space="ENG", templateType=["page"]))
        self.assertEqual((info.id, info.name, info.description, info.space_key), ("7402", "", "5", ""))
        self.assertEqual(template_from(answer(body="<p>x</p>")).body, "")
        self.assertEqual(template_from(answer(body={"storage": "<p>x</p>"})).body, "")
        self.assertEqual(template_from(answer(body={"storage": {"value": None}})).body, "")

    def test_an_answer_that_is_no_object_is_a_template_without_an_id(self):
        for data in (None, "x", 3, [], [answer()]):
            with self.subTest(data=data):
                self.assertEqual(info_from(data).id, "")
                self.assertEqual(template_from(data).id, "")


class PieceOfAListTest(unittest.TestCase):
    def test_the_next_piece_starts_where_the_link_says(self):
        page = page_from(listing([answer(), answer(templateId="7403")], start=0, nxt="/rest/api/template/page?spaceKey=ENG&limit=2&start=2"), 0)
        self.assertEqual((len(page.templates), page.start, page.next_start), (2, 0, 2))
        self.assertEqual(page.templates[1].id, "7403")

    def test_the_last_piece_has_no_next(self):
        page = page_from(listing([answer()], start=4), 4)
        self.assertEqual((page.start, page.next_start), (4, None))

    def test_a_link_that_does_not_say_where_goes_on_after_what_came(self):
        for link in ("/rest/api/template/page?spaceKey=ENG", "/rest/api/template/page?start=", "/rest/api/template/page?start=abc", "/rest/api/template/page?start=-5", "/rest/api/template/page?start=\u0662"):
            with self.subTest(link=link):
                page = page_from(listing([answer(), answer()], start=6, nxt=link), 6)
                self.assertEqual(page.next_start, 8)

    def test_a_link_that_would_not_go_on_is_no_next_so_that_a_list_cannot_be_read_for_ever(self):
        for link in ("/rest/api/template/page?start=6", "/rest/api/template/page?start=0", "/rest/api/template/page?start=3"):
            with self.subTest(link=link):
                self.assertIsNone(page_from(listing([answer()], start=6, nxt=link), 6).next_start)

    def test_a_link_that_is_no_text_is_no_link(self):
        for link in (None, 5, ["x"], {}, ""):
            with self.subTest(link=link):
                self.assertIsNone(page_from({"results": [answer()], "start": 0, "_links": {"next": link}}, 0).next_start)

    def test_where_the_piece_started_is_what_the_answer_says_and_else_what_was_asked(self):
        self.assertEqual(page_from(listing([answer()], start=10), 0).start, 10)
        for start in (None, "10", True, 1.5):
            with self.subTest(start=start):
                self.assertEqual(page_from(listing([answer()], start=start), 3).start, 3)

    def test_what_is_no_template_in_the_results_is_left_out(self):
        page = page_from(listing([answer(), "x", None, 5, [answer()]]), 0)
        self.assertEqual([item.id for item in page.templates], ["7402"])
        self.assertEqual(page_from({"results": "x"}, 0).templates, [])
        self.assertEqual(page_from(None, 2).start, 2)


class ReasonsTest(unittest.TestCase):
    def test_every_call_is_v1_and_the_reason_says_what_v2_lacks(self):
        self.assertEqual(sorted(rest_templates.V1_CALLS), ["GET /rest/api/template/blueprint", "GET /rest/api/template/page", "GET /rest/api/template/{contentTemplateId}"])
        for call, reason in rest_templates.V1_CALLS.items():
            with self.subTest(call=call):
                self.assertTrue(reason.startswith("v2 has no templates"))
                self.assertTrue(reason.endswith("."))


if __name__ == "__main__":
    unittest.main()
