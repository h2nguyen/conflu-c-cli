"""The templates of a space, the real program against the mock Confluence: the v1 requests that are sent, paging with a start, privacy, hostile input."""
import time
import unittest

from tests.integration.test_end_to_end import ACCOUNT, EndToEnd
from tests.support.fakes import FakeGateway
from tests.support.mock_templates import TemplatesRoutes

BLUEPRINT = "7408a0b1-c2d3-4e5f-8a6b-7c8d9e0f1a2b"
PEOPLE = (ACCOUNT, "Alex Example", "alex@example.com")
SPACES = ("GET", "/api/v2/spaces")


class TemplatesFlow(EndToEnd):
    def setUp(self):
        super().setUp()
        self.area = self.mock.area(TemplatesRoutes)

    def calls(self):
        """Every request that was made, as (method, path)."""
        return [(item.method, item.path) for item in self.mock.requests]

    def template_requests(self):
        return [item for item in self.mock.requests if item.path.startswith("/rest/api/template")]

    def nothing_unknown(self):
        self.assertEqual((self.mock.unknown_endpoints, self.mock.deprecated_endpoints), ([], []))

    def ids(self, result):
        return [item["id"] for item in result.json()["templates"]]


class ListTest(TemplatesFlow):
    def test_the_global_page_templates_are_one_get_of_the_page_list_with_a_start_and_a_limit_and_no_space(self):
        result = self.cli("templates", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.calls(), [("GET", "/rest/api/template/page")])
        self.assertEqual(self.template_requests()[0].query, {"start": ["0"], "limit": ["25"]})
        self.assertEqual((self.ids(result), result.json()["space"], result.json()["nextStart"]), (["7401"], None, None))
        self.assertEqual(self.mock.used_endpoints, ["GET /rest/api/template/page"])
        self.nothing_unknown()

    def test_the_templates_of_a_space_ask_for_the_space_first_and_send_its_key_as_the_space_writes_it(self):
        result = self.cli("templates", "--space", "eng", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.calls(), [SPACES, SPACES, ("GET", "/rest/api/template/page")])  # `eng` is not a key: `ENG` is, and the second request finds it
        self.assertEqual(self.template_requests()[0].query["spaceKey"], ["ENG"])
        self.assertEqual((self.ids(result), result.json()["space"], result.json()["nextStart"]), (["7404", "7403"], "ENG", 2))  # the mock gives two at a time
        self.mock.requests.clear()
        self.assertEqual(self.cli("templates", "--space", "DOCS", "--json").code, 0)
        self.assertEqual(self.calls(), [SPACES, ("GET", "/rest/api/template/page")])

    def test_the_templates_that_blueprints_provide_are_the_other_list(self):
        result = self.cli("templates", "--blueprints", "--space", "ENG", "--json")
        self.assertEqual(self.calls()[-1], ("GET", "/rest/api/template/blueprint"))
        self.assertEqual((self.ids(result), result.json()["blueprints"], result.json()["templates"][0]["type"]), ([BLUEPRINT], True, "blueprint"))
        self.assertEqual(self.mock.used_endpoints[-1], "GET /rest/api/template/blueprint")

    def test_a_piece_is_asked_for_with_start_and_limit_and_the_next_start_comes_from_the_link_of_the_answer(self):
        first = self.cli("templates", "--space", "ENG", "--limit", "1", "--json")
        self.assertEqual((self.ids(first), first.json()["nextStart"]), (["7404"], 1))
        second = self.cli("templates", "--space", "ENG", "--limit", "1", "--start", "1", "--json")
        self.assertEqual((self.ids(second), second.json()["start"], second.json()["nextStart"]), (["7403"], 1, 2))
        self.assertEqual(self.template_requests()[-1].query["start"], ["1"])
        last = self.cli("templates", "--space", "ENG", "--start", "2", "--json")
        self.assertEqual((self.ids(last), last.json()["nextStart"]), (["7402"], None))

    def test_all_of_them_follow_the_links_in_pieces_of_a_hundred(self):
        result = self.cli("templates", "--space", "ENG", "--all", "--json")
        self.assertEqual(self.ids(result), ["7404", "7403", "7402"])
        requests = self.template_requests()
        self.assertEqual(([item.query["start"][0] for item in requests], {item.query["limit"][0] for item in requests}), (["0", "2"], {"100"}))
        self.assertEqual((result.json()["start"], result.json()["nextStart"], result.json()["truncated"]), (0, None, False))

    def test_a_long_list_is_read_to_its_end(self):
        for number in range(130):
            self.area.add_template(f"Template {number:03d}", "<p>x</p>", space_key="DOCS", template_id=f"9{number:03d}")
        result = self.cli("templates", "--space", "DOCS", "--all", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(len(self.ids(result)), 131)  # and the template of the space that was there already
        self.assertEqual([item.query["start"][0] for item in self.template_requests()][:3], ["0", "2", "4"])

    def test_a_list_that_does_not_go_on_is_not_read_for_ever(self):
        looping = {"results": [], "start": 0, "limit": 2, "size": 0, "_links": {"next": "/rest/api/template/page?start=0"}}
        self.mock.fail_next("/rest/api/template/page", 200, times=50, method="GET", body={**looping, "results": [{"templateId": "1", "name": "Same", "templateType": "page", "labels": []}]})
        result = self.cli("templates", "--all", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(len(self.template_requests()), 1)
        self.mock.requests.clear()
        self.mock.fail_next("/rest/api/template/page", 200, times=50, method="GET", body={**looping, "results": [{"templateId": "1", "name": "Same", "templateType": "page", "labels": []}], "_links": {"next": "/rest/api/template/page?start=abc"}})
        self.assertEqual(self.cli("templates", "--all", "--json").code, 0)
        self.assertLessEqual(len(self.template_requests()), 60)

    def test_what_is_refused_is_refused_before_any_template_is_asked_for(self):
        self.assertEqual(self.cli("templates", "--space", "NOPE").code, 4)
        self.assertEqual(self.cli("templates", "--space", "E N G").code, 1)
        self.assertEqual(self.cli("templates", "--start", "-1").code, 2)
        self.assertEqual(self.cli("templates", "--limit", "0").code, 2)
        self.assertEqual(self.template_requests(), [])

    def test_the_server_refusing_the_space_is_exit_code_5_and_says_none_of_its_words(self):
        self.mock.taint = True
        self.mock.fail_next("/rest/api/template/page", 403, method="GET", body={"statusCode": 403, "message": "alex@example.com may not see it"})
        result = self.cli("templates", "--space", "ENG")
        self.assertEqual((result.code, result.out), (5, ""))
        self.assertIn("the space ENG", result.err)
        for text in PEOPLE:
            self.assertNotIn(text, result.err)

    def test_what_the_server_refuses_is_an_exit_code(self):
        for status, code in ((401, 5), (404, 4), (429, 7), (500, 7), (400, 6)):
            self.mock.fail_next("/rest/api/template/page", status, method="GET", body={"message": "Not this time"})
            with self.subTest(status=status):
                self.assertEqual(self.cli("templates", env={"CONFLUENCE_RETRY": "0"}).code, code)

    def test_credentials_that_are_not_accepted_are_not_reported_as_a_lack_of_permission(self):
        for argv, prefix in ((("templates",), "/rest/api/template/page"), (("template", "7402"), "/rest/api/template/7402")):
            self.mock.fail_next(prefix, 401, method="GET", body={"statusCode": 401, "message": "alex@example.com"})
            result = self.cli(*argv)
            with self.subTest(argv=argv):
                self.assertEqual((result.code, result.out), (5, ""))
                self.assertIn("did not accept the credentials", result.err)
                self.assertNotIn("HTTP 403", result.err)
                self.assertNotIn("alex@example.com", result.err)

    def test_the_text_that_the_mock_marked_does_not_get_through_and_nobody_is_named(self):
        self.mock.taint = True
        for argv in (("templates", "--all"), ("templates", "--all", "--json"), ("templates", "--blueprints", "--all", "--format", "tsv"), ("templates", "--space", "ENG", "--all", "--json")):
            result = self.cli(*argv)
            with self.subTest(argv=argv):
                self.assertEqual(result.code, 0, result.err)
                for text in PEOPLE:
                    self.assertNotIn(text, result.out + result.err)
        self.assertIn("[email]", self.cli("templates", "--all").out)

    def test_names_that_are_made_of_controls_or_addresses_cannot_move_the_cursor_or_add_a_row(self):
        self.area.add_template("Evil\u001b[2J\u0007 name\nsecond line", "<p>x</p>", description="Write to alex@example.com\n7499 fake row\u009b", labels=("alex@example.com", "tab\tlabel"))
        result = self.cli("templates", "--all")
        self.assertEqual(result.code, 0, result.err)
        self.assertNotIn("\x1b", result.out)
        self.assertNotIn("\x9b", result.out)
        self.assertNotIn("alex@example.com", result.out)
        self.assertEqual(len(result.out.splitlines()), 3)  # the header and the two global templates
        data = self.cli("templates", "--all", "--json")
        self.assertEqual(data.code, 0, data.err)
        self.assertNotIn("alex@example.com", data.out)
        self.assertNotIn("\x9b", data.out)


class ShowTest(TemplatesFlow):
    def test_a_template_is_one_get_with_its_body_in_storage_format(self):
        result = self.cli("template", "7402", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.calls(), [("GET", "/rest/api/template/7402")])
        self.assertEqual(self.mock.requests[0].query, {"expand": ["body.storage"]})
        data = result.json()
        self.assertEqual((data["id"], data["name"], data["type"], data["spaceKey"], data["labels"], data["variables"]), ("7402", "Release checklist", "page", "ENG", ["release", "checklist"], ["version"]))
        self.assertEqual(data["body"], {"format": "markdown", "value": "## Release\n\n- Update the notes\n- Tag", "dropped": ["html:at:var"]})
        self.assertEqual(self.mock.used_endpoints, ["GET /rest/api/template/{contentTemplateId}"])
        self.nothing_unknown()

    def test_a_blueprint_template_is_read_by_its_id_and_the_id_is_one_path_segment(self):
        result = self.cli("template", BLUEPRINT, "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.calls(), [("GET", f"/rest/api/template/{BLUEPRINT}")])
        data = result.json()
        self.assertEqual((data["type"], data["spaceKey"], data["blueprint"].endswith("retrospectives-blueprint")), ("blueprint", "ENG", True))

    def test_the_source_is_what_confluence_keeps_with_the_people_blanked(self):
        result = self.cli("template", "7403", "--format", "storage")
        self.assertEqual(result.code, 0, result.err)
        self.assertIn('<ri:user ri:account-id="hidden" />', result.out)
        for text in PEOPLE:
            self.assertNotIn(text, result.out + result.err)

    def test_the_variables_come_from_the_storage_format_whatever_the_format_shown(self):
        for fmt in ("markdown", "text", "storage"):
            data = self.cli("template", "7404", "--format", fmt, "--json").json()
            with self.subTest(fmt=fmt):
                self.assertEqual((data["variables"], data["variablesComplete"]), (["title", "Tom & Jerry"], True))

    def test_the_text_that_the_mock_marked_does_not_get_through_and_nobody_is_named(self):
        self.mock.taint = True
        for argv in (("template", "7403"), ("template", "7403", "--json"), ("template", "7403", "--format", "storage"), ("template", "7403", "--format", "text"), ("template", "7402", "--json")):
            result = self.cli(*argv)
            with self.subTest(argv=argv):
                self.assertEqual(result.code, 0, result.err)
                for text in PEOPLE:
                    self.assertNotIn(text, result.out + result.err)
        self.assertIn("[email]", self.cli("template", "7403", "--format", "storage").out)

    def test_a_template_that_is_not_there_is_exit_code_5_with_what_is_known_and_no_word_of_the_server(self):
        self.mock.taint = True
        result = self.cli("template", "99999")
        self.assertEqual((result.code, result.out), (5, ""))
        self.assertIn("there is no template 99999, or this account may not see it", result.err)
        for text in PEOPLE:
            self.assertNotIn(text, result.err)
        self.assertEqual(self.calls(), [("GET", "/rest/api/template/99999")])

    def test_an_id_that_could_change_the_path_or_the_query_is_refused_before_any_request(self):
        for text in ("page", "blueprint", "7402/../7403", "7402?expand=body", "7402#x", "%2e%2e", "7402 7403", "../x", "", "a" * 200, "7402\n7403"):
            with self.subTest(text=text[:20]):
                self.assertIn(self.cli("template", text).code, (1, 2))
        self.assertEqual(self.mock.requests, [])

    def test_the_body_alone_can_start_a_page_through_a_file_and_one_with_a_blanked_mention_cannot(self):
        path = self.root / "body.xml"
        path.write_text(self.cli("template", "7402", "--format", "storage", "--body-only").out, encoding="utf-8")
        created = self.cli("create", "--space", "ENG", "--title", "Release 2026.11", "--file", str(path), "--format", "storage", "--json")
        self.assertEqual(created.code, 0, created.err)
        self.assertIn('<at:var at:name="version" />', self.mock.pages[created.json()["pageId"]]["versions"][-1]["body"])  # the variables are in the page as the template had them
        path.write_text(self.cli("template", "7403", "--format", "storage", "--body-only").out, encoding="utf-8")
        refused = self.cli("create", "--space", "ENG", "--title", "Incident", "--file", str(path), "--format", "storage")
        self.assertEqual(refused.code, 1)  # its mention was blanked, and a page must not be written with a mention that names nobody
        self.assertIn("mentions whose account ids were hidden", refused.err)

    def test_a_format_that_is_unknown_is_refused_before_any_request(self):
        self.assertEqual(self.cli("template", "7402", "--format", "html").code, 2)
        self.assertEqual(self.mock.requests, [])

    def test_a_body_with_broken_tags_is_read_quickly_and_says_that_its_variables_may_be_incomplete(self):
        template_id = self.area.add_template("Broken", '<at:var at:name="ok"/>' + "<at:var " * 50_000)
        result = self.cli("template", template_id, "--format", "storage", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual((result.json()["variables"], result.json()["variablesComplete"]), (["ok"], False))

    def test_a_body_of_tags_that_never_end_is_converted_in_a_moment_in_every_format(self):
        started = time.perf_counter()
        template_id = self.area.add_template("Broken", "Intro " + "<p <a <b " * 20_000 + ' <at:var at:name="late"/>')
        for fmt in ("markdown", "text", "storage"):
            result = self.cli("template", template_id, "--format", fmt, "--json")
            with self.subTest(fmt=fmt):
                self.assertEqual(result.code, 0, result.err)
                self.assertIn("Intro", result.json()["body"]["value"])
        self.assertLess(time.perf_counter() - started, 20)

    def test_a_body_with_a_great_many_variables_lists_the_first_ones_and_says_so(self):
        template_id = self.area.add_template("Many", "".join(f'<at:var at:name="v{number}"/>' for number in range(3000)))
        data = self.cli("template", template_id, "--format", "storage", "--json").json()
        self.assertEqual((len(data["variables"]), data["variables"][0], data["variablesComplete"]), (200, "v0", False))

    def test_a_variable_in_a_cdata_section_or_a_comment_is_no_variable_in_any_format(self):
        body = (
            '<p><at:var at:name="real"/></p><ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA[<at:var at:name="in.code"/>]]></ac:plain-text-body>'
            '</ac:structured-macro><!-- <at:var at:name="in.comment"/> -->'
        )
        template_id = self.area.add_template("Notes", body)
        for fmt in ("markdown", "text", "storage"):
            data = self.cli("template", template_id, "--format", fmt, "--json").json()
            with self.subTest(fmt=fmt):
                self.assertEqual((data["variables"], data["variablesComplete"]), (["real"], True))
        text = self.cli("template", template_id).out
        self.assertRegex(text, r"Variables:\s+real\n")
        self.assertNotIn("in.code", text.split("Variables:")[1].splitlines()[0])

    def test_a_body_nested_too_deeply_to_convert_is_refused_with_the_way_to_read_it_anyway(self):
        template_id = self.area.add_template("Nested", "<div>" * 200 + '<at:var at:name="deep"/>' + "</div>" * 200)
        refused = self.cli("template", template_id)
        self.assertEqual((refused.code, refused.out), (1, ""))
        self.assertIn("--format storage", refused.err)
        source = self.cli("template", template_id, "--format", "storage", "--json")
        self.assertEqual((source.code, source.json()["variables"]), (0, ["deep"]))

    def test_a_template_that_the_server_describes_with_the_wrong_types_is_shown_as_far_as_it_makes_sense(self):
        self.mock.fail_next("/rest/api/template/7402", 200, method="GET", body={"templateId": 7402, "name": None, "labels": "x", "body": "text", "space": "ENG"})
        result = self.cli("template", "7402", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual((result.json()["id"], result.json()["name"], result.json()["labels"], result.json()["spaceKey"]), ("7402", "", [], None))

    def test_an_answer_without_an_id_is_an_error_and_not_an_empty_template(self):
        self.mock.fail_next("/rest/api/template/7402", 200, method="GET", body={"name": "x"})
        result = self.cli("template", "7402")
        self.assertEqual(result.code, 7)
        self.assertIn("not with template 7402", result.err)

    def test_nothing_is_ever_written(self):
        for argv in (("templates", "--all"), ("templates", "--blueprints", "--all"), ("template", "7402"), ("template", BLUEPRINT, "--format", "storage")):
            self.cli(*argv)
        self.assertEqual({item.method for item in self.mock.requests}, {"GET"})


class FixturesTest(unittest.TestCase):
    """The fake and the mock hold the same templates, so that what a test shows against one holds against the other."""

    def test_the_mock_and_the_fake_agree(self):
        from tests.support.mock_confluence import MockConfluence

        mock = MockConfluence()
        try:
            area = mock.area(TemplatesRoutes)
            fake = FakeGateway()
            self.assertEqual(sorted(area.templates), sorted(fake.templates))
            for template_id, template in fake.templates.items():
                with self.subTest(template=template_id):
                    shown = area.templates[template_id]
                    self.assertEqual(
                        (shown["name"], shown["templateType"], shown["spaceKey"], shown["description"], tuple(shown["labels"]), shown["blueprint"], shown["body"]),
                        (template.name, template.type, template.space_key, template.description, template.labels, template.blueprint, template.body),
                    )
        finally:
            mock.stop()


if __name__ == "__main__":
    unittest.main()
