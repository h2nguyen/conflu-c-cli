"""Labels, the real program against the mock Confluence: the labels used in a space, a piece at a time and all of them, and the labels of a page as they were."""
import json
import unittest

from tests.integration.test_end_to_end import EndToEnd


class LabelsFlow(EndToEnd):
    def writes(self):
        return [item for item in self.mock.requests if item.method != "GET"]

    def paths(self):
        return [(item.method, item.path) for item in self.mock.requests]

    def of_space(self, space_id="1001"):
        return [item for item in self.mock.requests if item.path == f"/api/v2/spaces/{space_id}/content/labels"]

    def ok(self, *argv, **options):
        result = self.cli(*argv, **options)
        self.assertEqual(result.code, 0, result.err)
        return result


class SpaceLabelsTest(LabelsFlow):
    def test_the_labels_of_the_content_of_a_space_are_asked_for_by_name_after_the_space_is_looked_up(self):
        data = self.ok("labels", "--space", "ENG", "--json").json()
        self.assertEqual([item["name"] for item in data["labels"]], ["adr", "notes"])
        self.assertEqual((data["space"], data["spaceId"], data["count"], data["nextCursor"], data["truncated"]), ("ENG", "1001", 2, "2", False))
        self.assertEqual([path for _, path in self.paths()], ["/api/v2/spaces", "/api/v2/spaces/1001/content/labels"])
        self.assertEqual(self.mock.requests[0].query["keys"], ["ENG"])
        self.assertEqual(self.of_space()[0].query, {"sort": ["name"], "limit": ["25"]})
        self.assertEqual(self.writes(), [])

    def test_the_cursor_of_one_piece_asks_for_the_next_and_the_last_piece_has_none(self):
        first = self.ok("labels", "--space", "ENG", "--json").json()
        second = self.ok("labels", "--space", "ENG", "--cursor", first["nextCursor"], "--json").json()
        self.assertEqual(([item["name"] for item in second["labels"]], second["nextCursor"]), (["release"], None))
        self.assertEqual(self.of_space()[1].query["cursor"], ["2"])

    def test_all_reads_every_piece_in_the_biggest_size_and_follows_the_cursor_of_the_answer(self):
        data = self.ok("labels", "--space", "ENG", "--all", "--json").json()
        self.assertEqual([item["name"] for item in data["labels"]], ["adr", "notes", "release"])
        self.assertEqual((data["count"], data["nextCursor"], data["truncated"]), (3, None, False))
        asked = self.of_space()
        self.assertEqual([item.query.get("cursor") for item in asked], [None, ["2"]])
        self.assertEqual({tuple(item.query["limit"]) for item in asked}, {("100",)})

    def test_a_small_piece_is_a_small_piece_whatever_the_server_would_give(self):
        seen, cursor = [], None
        while True:
            argv = ["labels", "--space", "ENG", "--limit", "1", "--json"] + (["--cursor", cursor] if cursor else [])
            data = self.ok(*argv).json()
            seen += [item["name"] for item in data["labels"]]
            cursor = data["nextCursor"]
            if not cursor:
                break
        self.assertEqual(seen, ["adr", "notes", "release"])

    def test_the_text_says_how_to_go_on(self):
        result = self.ok("labels", "--space", "ENG")
        self.assertEqual(result.out, "NAME   PREFIX\nadr    global\nnotes  global\n")
        self.assertIn("More labels follow. Continue with --cursor 2, or use --all.", result.err)
        done = self.ok("labels", "--space", "ENG", "--all")
        self.assertEqual(done.err, "")

    def test_a_space_of_its_own_with_its_own_labels(self):
        self.mock.add_space("OPS", "Operations")
        self.mock.add_page("OPS", "Runbook", "<p>Steps.</p>", labels=("Ops", "runbook"))
        self.mock.add_page("OPS", "Checklist", "<p>Checks.</p>", labels=("runbook", "checklist"))
        data = self.ok("labels", "--space", "OPS", "--all", "--json").json()
        self.assertEqual([item["name"] for item in data["labels"]], ["checklist", "ops", "runbook"])
        self.assertEqual({item["prefix"] for item in data["labels"]}, {"global"})
        engineering = self.ok("labels", "--space", "ENG", "--all", "--json").json()
        self.assertNotIn("runbook", [item["name"] for item in engineering["labels"]])  # what is used elsewhere is not listed here

    def test_a_label_that_was_just_added_to_a_page_is_one_of_the_space(self):
        self.ok("label", "2003", "--add", "Fresh")
        data = self.ok("labels", "--space", "ENG", "--all", "--json").json()
        self.assertIn("fresh", [item["name"] for item in data["labels"]])
        self.ok("label", "2003", "--remove", "fresh")
        self.assertNotIn("fresh", [item["name"] for item in self.ok("labels", "--space", "ENG", "--all", "--json").json()["labels"]])

    def test_a_space_without_labels_is_an_empty_list_and_the_key_may_be_in_any_case(self):
        data = self.ok("labels", "--space", "docs", "--json").json()
        self.assertEqual((data["space"], data["count"], data["labels"], data["nextCursor"]), ("DOCS", 0, [], None))
        self.assertEqual(self.ok("labels", "--space", "DOCS").out, "No labels.\n")

    def test_the_labels_may_be_cut_to_some_keys_and_printed_as_a_table(self):
        self.assertEqual(self.ok("labels", "--space", "ENG", "--all", "--select", "name", "--format", "tsv").out, "name\nadr\nnotes\nrelease\n")
        self.assertEqual(self.ok("labels", "--space", "ENG", "--all", "--select", "name", "--json").json()["labels"], [{"name": "adr"}, {"name": "notes"}, {"name": "release"}])

    def test_a_space_that_does_not_exist_is_exit_code_4_and_the_labels_are_not_asked_for(self):
        result = self.cli("labels", "--space", "NOPE")
        self.assertEqual(result.code, 4)
        self.assertEqual([path for _, path in self.paths()], ["/api/v2/spaces"])
        self.assertEqual(self.cli("labels", "--space", "nope").code, 4)
        self.assertEqual([path for _, path in self.paths()], ["/api/v2/spaces"] * 3)  # a key in lower case is asked for as written and then in capitals
        self.assertEqual(self.of_space(), [])

    def test_what_is_no_space_key_or_limit_never_reaches_the_server(self):
        for argv in (("--space", "ENG/../x"), ("--space", "E N G"), ("--space", ""), ("--space", "ENG?limit=1"), ("--space", "ENG", "--limit", "0"), ("--space", "ENG", "--limit", "251"), ()):
            with self.subTest(argv=argv):
                self.assertNotEqual(self.cli("labels", *argv).code, 0)
        self.assertEqual(self.mock.requests, [])

    def test_no_prefix_is_asked_for_and_the_credentials_and_people_play_no_part(self):
        self.ok("labels", "--space", "ENG", "--all", env={"CONFLUENCE_HIDE_USERS": "true"})
        for item in self.of_space():
            self.assertNotIn("prefix", item.query)
        self.assertEqual([item for item in self.mock.requests if "users" in item.path or item.path.startswith("/rest/")], [])

    def test_a_refusal_of_confluence_is_reported_with_its_exit_code(self):
        self.mock.fail_next("/api/v2/spaces/1001/content/labels", 403)
        result = self.cli("labels", "--space", "ENG", "--json")
        self.assertEqual(result.code, 5)
        self.assertEqual(json.loads(result.err.strip().splitlines()[-1])["error"]["code"], "AUTH")

    def test_every_call_is_one_that_the_documents_know_and_none_is_to_the_v1_api(self):
        self.ok("labels", "--space", "ENG", "--all")
        self.ok("labels", "2002")
        self.assertEqual((self.mock.unknown_endpoints, self.mock.deprecated_endpoints), ([], []))
        self.assertEqual({call for call in self.mock.used_endpoints if "/rest/api/" in call}, set())
        self.assertIn("GET /api/v2/spaces/{id}/content/labels", self.mock.used_endpoints)
        self.assertNotIn("GET /api/v2/spaces/{id}/labels", self.mock.used_endpoints)  # those are the labels of the space itself


class PageLabelsTest(LabelsFlow):
    """The labels of a page, and adding and removing them: as they were."""

    def test_the_labels_of_a_page_are_asked_for_whole_and_printed_as_before(self):
        result = self.ok("labels", "2002")
        self.assertEqual(result.out, "NAME     PREFIX\nnotes    global\nrelease  global\n")  # the mock gives the labels of a page by name
        self.assertEqual(self.paths(), [("GET", "/api/v2/pages/2002/labels")])
        self.assertEqual(self.mock.requests[0].query, {"limit": ["250"]})
        self.assertEqual(self.ok("labels", "2002", "--json").out, '{"pageId":"2002","labels":[{"name":"notes","prefix":"global"},{"name":"release","prefix":"global"}]}\n')

    def test_a_page_that_does_not_exist_is_exit_code_4(self):
        self.assertEqual(self.cli("labels", "9999").code, 4)

    def test_labels_are_added_and_removed_with_the_calls_that_v2_lacks(self):
        data = self.ok("label", "2002", "--add", "Reviewed", "--remove", "notes", "--json").json()
        self.assertEqual((data["added"], data["removed"], data["labels"]), (["reviewed"], ["notes"], ["release", "reviewed"]))
        self.assertEqual([(item.method, item.path) for item in self.writes()], [("POST", "/rest/api/content/2002/label"), ("DELETE", "/rest/api/content/2002/label/notes")])
        self.assertEqual(self.writes()[0].body, [{"prefix": "global", "name": "reviewed"}])
        self.assertEqual(self.mock.pages["2002"]["labels"], ["release", "reviewed"])

    def test_the_dry_run_reads_and_sends_nothing(self):
        out = self.ok("label", "2002", "--add", "reviewed,adr", "--remove", "notes", "--dry-run").out
        self.assertEqual(out, "Dry run (nothing was sent): page 2002: would add: reviewed, adr; would remove: notes\nLabels: notes, release\n")
        self.assertEqual(self.writes(), [])

    def test_an_option_that_names_no_label_is_an_error_that_names_it_and_nothing_reaches_the_server(self):
        for argv, option in (
            (("--add", "", "--remove", "notes"), "--add"),
            (("--add", "reviewed", "--remove", ""), "--remove"),
            (("--add", " , ", "--dry-run"), "--add"),
            (("--remove", ",", "--dry-run"), "--remove"),
        ):
            with self.subTest(argv=argv):
                result = self.cli("label", "2002", *argv)
                self.assertEqual(result.code, 1)
                self.assertIn(f"{option} is empty", result.err.splitlines()[0])
                self.assertEqual(result.out, "")
        self.assertEqual(self.mock.requests, [])  # not even a read of the page
        self.assertEqual(self.mock.pages["2002"]["labels"], ["release", "notes"])

    def test_the_v1_calls_are_the_ones_that_are_explained(self):
        self.ok("label", "2002", "--add", "reviewed", "--remove", "notes")
        self.assertEqual({call for call in self.mock.used_endpoints if "/rest/api/" in call}, {"POST /rest/api/content/{id}/label", "DELETE /rest/api/content/{id}/label/{label}"})
        self.assertEqual((self.mock.unknown_endpoints, self.mock.deprecated_endpoints), ([], []))


if __name__ == "__main__":
    unittest.main()
