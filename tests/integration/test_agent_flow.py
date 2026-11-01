"""The new search and reading, through the real adapters against the mock Confluence: what is sent, what comes back, what the person sees."""
import json
import unittest

from conflu_c_cli.adapters.driven.confluence_mapper import search_hit_from
from conflu_c_cli.domain.errors import UnavailableError
from tests.integration.test_end_to_end import ACCOUNT, EndToEnd
from tests.integration.test_http_and_gateway import GatewayCase

BODY = (
    "<h1>Intro</h1><p>Alpha text.</p><h2>Steps</h2><p>Do this.</p><ul><li>one</li><li>two</li></ul>"
    "<h2>Notes</h2><p>" + "Remember this. " * 40 + "</p>"
)


class SearchGatewayTest(GatewayCase):
    def test_the_search_asks_for_what_a_hit_needs(self):
        self.gw.search('type = page AND text ~ "release"')
        self.assertEqual(self.mock.requests[-1].query["expand"], ["content.ancestors,content.metadata.labels,content.version"])

    def test_a_hit_has_its_path_labels_and_version(self):
        hit = self.gw.search('type = page AND text ~ "ports"').hits[0]
        self.assertEqual((hit.id, hit.path, hit.labels, hit.version), ("2004", "Engineering Home > Architecture", ("adr",), 2))
        top = self.gw.search('type = page AND title ~ "Engineering Home"').hits[0]
        self.assertEqual((top.path, top.labels), ("", ()))  # the root has no path, a page without labels none

    def test_the_server_understands_any_a_phrase_and_a_wildcard(self):
        ids = lambda cql: sorted(hit.id for hit in self.gw.search(cql, limit=25).hits)
        self.mock.page_cap = 10
        self.assertEqual(ids('type = page AND space = "ENG" AND (text ~ "release" OR text ~ "decision")'), ["2002", "2004"])
        self.assertEqual(ids('type = page AND text ~ "\\"just a paragraph\\""'), ["2005"])
        self.assertEqual(ids('type = page AND text ~ "\\"paragraph just\\""'), [])  # a phrase keeps its order
        self.assertEqual(ids('type = page AND text ~ "adapt*"'), ["2004"])
        self.assertEqual(ids('type = page AND text ~ "decision" AND text ~ "\\"ports and adapters\\""'), ["2004"])
        self.assertEqual(ids('type = page AND text ~ "decision release"'), [])  # several words in one clause: all of them

    def test_an_expand_the_server_does_not_know_is_refused(self):
        from conflu_c_cli.domain.errors import RejectedError

        with self.assertRaises(RejectedError):
            self.gw.request("GET", "/rest/api/search?cql=" + 'type%3Dpage' + "&expand=content.nonsense")


class SearchHitMapperTest(unittest.TestCase):
    def test_the_path_comes_from_the_ancestors_else_from_the_breadcrumbs(self):
        item = {"content": {"id": "1", "type": "page", "title": "T", "ancestors": [{"title": "Home"}, "junk", {"title": "Guides & Tips"}]}, "breadcrumbs": [{"label": "ignored"}]}
        self.assertEqual(search_hit_from(item).path, "Home > Guides & Tips")
        fallback = {"content": {"id": "1", "type": "page", "title": "T"}, "breadcrumbs": [{"label": "Home"}, {"label": "Guides &amp; Tips"}, {"nolabel": 1}]}
        self.assertEqual(search_hit_from(fallback).path, "Home > Guides & Tips")
        self.assertEqual(search_hit_from({"content": {"id": "1", "title": "T"}}).path, "")

    def test_labels_are_lower_case_and_once_and_the_version_is_a_number_or_nothing(self):
        item = {"content": {"id": "1", "title": "T", "metadata": {"labels": {"results": [{"name": "ADR"}, {"name": "adr"}, {"name": "Docs"}, {"name": ""}, "junk"]}}, "version": {"number": 4}}}
        hit = search_hit_from(item)
        self.assertEqual((hit.labels, hit.version), (("adr", "docs"), 4))
        for content in ({"id": "1"}, {"id": "1", "version": {}}, {"id": "1", "version": {"number": None}}, {"id": "1", "metadata": {"labels": None}}, {"id": "1", "metadata": "junk"}):
            with self.subTest(content=content):
                hit = search_hit_from({"content": content})
                self.assertEqual((hit.labels, hit.version), ((), None))

    def test_a_version_that_is_there_and_is_no_number_is_a_damaged_answer_and_not_nothing(self):
        for number in ("x", [4], {"n": 4}, True, float("inf"), "9" * 5000):
            with self.subTest(number=repr(number)[:20]), self.assertRaises(UnavailableError):
                search_hit_from({"content": {"id": "1", "version": {"number": number}}})

    def test_an_odd_answer_gives_an_empty_path_not_an_error(self):
        for item in ({}, {"content": None}, {"content": {"ancestors": "junk"}}, {"content": {"ancestors": None}, "breadcrumbs": "junk"}, {"breadcrumbs": [None, 3]}):
            with self.subTest(item=item):
                self.assertEqual(search_hit_from(item).path, "")


class AgentFlowTest(EndToEnd):
    def test_a_question_finds_the_page_and_the_passage_names_no_one(self):
        result = self.cli("search", "what are the release notes?", "--space", "ENG", "--snippets", "2", "--json")
        self.assertEqual(result.code, 0, result.err)
        data = result.json()
        self.assertEqual((data["terms"], data["ignored"], data["match"], data["relaxed"]), (["release", "notes"], ["what", "are", "the"], "all", False))
        first = data["hits"][0]
        self.assertEqual((first["id"], first["path"], first["version"], first["labels"]), ("2002", "Engineering Home", 3, ["release", "notes"]))
        self.assertIn("[email]", first["snippet"])
        self.assertNotIn("alex@example.com", json.dumps(data))
        self.assertNotIn(ACCOUNT, json.dumps(data))
        self.assertEqual(first["matched"], ["release", "notes"])

    def test_when_no_page_has_every_word_the_server_is_asked_again_for_any(self):
        data = self.cli("search", "release zzznothing", "--space", "ENG", "--json").json()
        self.assertEqual((data["relaxed"], data["match"], [hit["id"] for hit in data["hits"]]), (True, "any", ["2002"]))
        self.assertIn(' OR ', data["cql"])
        strict = self.cli("search", "release zzznothing", "--space", "ENG", "--match", "all", "--json").json()
        self.assertEqual((strict["total"], strict["relaxed"]), (0, False))
        self.assertTrue(any("Nothing found" in note for note in strict["notes"]))

    def test_a_phrase_is_searched_as_a_phrase(self):
        found = self.cli("search", '"just a paragraph"', "--space", "ENG", "--json").json()
        self.assertEqual([hit["id"] for hit in found["hits"]], ["2005"])
        self.assertEqual(self.cli("search", '"paragraph just"', "--space", "ENG", "--match", "all", "--json").json()["total"], 0)

    def test_a_long_page_is_read_in_parts(self):
        self.mock.pages["2005"]["versions"][-1]["body"] = BODY
        outline = self.cli("page", "2005", "--outline", "--json").json()
        self.assertEqual([entry["title"] for entry in outline["outline"]], ["Intro", "Steps", "Notes"])
        whole = self.cli("page", "2005", "--json").json()["body"]["value"]
        self.assertEqual(outline["outline"][0]["chars"], len(whole))  # the first heading holds the page
        part = self.cli("page", "2005", "--section", "steps", "--json").json()["body"]
        self.assertEqual((part["section"], part["value"]), ("Steps", "## Steps\n\nDo this.\n\n- one\n- two"))
        cut = self.cli("page", "2005", "--max-chars", "120", "--json").json()["body"]
        self.assertEqual((cut["truncated"], cut["totalChars"]), (True, len(whole)))
        self.assertTrue(whole.startswith(cut["value"]))

    def test_a_link_is_followed_by_its_title(self):
        by_title = self.cli("page", "page:ENG/Architecture", "--no-body", "--json")
        self.assertEqual((by_title.code, by_title.json()["id"]), (0, "2003"), by_title.err)
        self.assertEqual(self.cli("page", "page:Architecture", "--space", "ENG", "--no-body", "--json").json()["id"], "2003")
        tree = self.cli("tree", "page:ENG/Architecture", "--depth", "1", "--json").json()
        self.assertEqual([node["id"] for node in tree["nodes"]], ["2004"])
        missing = self.cli("page", "page:ENG/No such page", "--json")
        self.assertEqual(missing.code, 4)

    def test_a_mirror_says_where_every_page_lives_so_that_a_search_of_the_files_shows_it(self):
        out = self.root / "mirror"
        self.assertEqual(self.cli("export", "--space", "ENG", "--out", str(out)).code, 0)
        adr = (out / "adr-0001-2004.md").read_text(encoding="utf-8")
        self.assertIn("\npath: Engineering Home > Architecture\n", adr)
        hits = [path.name for path in out.glob("*.md") if "path: Engineering Home" in path.read_text(encoding="utf-8")]
        self.assertEqual(len(hits), 4)  # every page but the home page itself
        again = self.cli("import-md-dir", str(out), "--json").json()
        self.assertEqual((again["unchanged"], again["updated"], again["failed"]), (5, 0, 0))

    def test_the_tool_descriptions_come_out_of_a_separate_program_as_json(self):
        done = self.child("commands", "--format", "mcp", "--only", "all")
        self.assertEqual(done.code, 0, done.err)
        tools = {tool["name"]: tool for tool in json.loads(done.out)["tools"]}
        self.assertIn("conflu_search", tools)
        self.assertIn("conflu_update", tools)
        self.assertNotIn("conflu_setup_token", tools)
        self.assertEqual(tools["conflu_page"]["inputSchema"]["required"], ["page"])


if __name__ == "__main__":
    unittest.main()
