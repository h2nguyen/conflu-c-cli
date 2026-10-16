"""The commands an agent uses to find and read: search with snippets, page in parts, a page by its title, the path in an export."""
import json
import unittest

from conflu_c_cli.domain.model import SearchHit
from tests.support.cli import run_cli
from tests.support.fakes import ACCOUNT, FakeGateway

BODY = (
    "<h1>Intro</h1><p>Alpha text.</p><h2>Steps</h2><p>Do this.</p><ul><li>one</li><li>two</li></ul>"
    "<h2>Notes</h2><p>" + "Remember this. " * 40 + "</p>"
)


def gateway_with_headings():
    gateway = FakeGateway()
    gateway.pages["2005"].body = BODY
    gateway.page_cap = 10
    return gateway


class SearchCommandTest(unittest.TestCase):
    def test_every_hit_says_where_it_is_how_it_is_tagged_and_which_version_and_the_answer_says_how_it_was_searched(self):
        data = run_cli("search", "release notes", "--json").json()
        self.assertEqual(set(data), {"total", "count", "start", "cql", "match", "relaxed", "terms", "ignored", "notes", "truncated", "hits"})
        self.assertEqual((data["match"], data["relaxed"], data["terms"], data["ignored"]), ("all", False, ["release", "notes"], []))
        hit = data["hits"][0]
        self.assertEqual(set(hit), {"id", "type", "title", "spaceKey", "path", "labels", "version", "url", "excerpt", "snippet", "matched", "lastModified"})
        self.assertEqual((hit["path"], hit["labels"], hit["version"], hit["snippet"], hit["matched"]), ("Engineering Home", ["release", "notes"], 3, None, []))

    def test_a_question_works_and_the_answer_says_what_was_left_out(self):
        result = run_cli("search", "how do I read the release notes?", "--json")
        data = result.json()
        self.assertEqual((data["terms"], data["ignored"]), (["read", "release", "notes"], ["how", "do", "I", "the"]))
        self.assertIn("Left out as filler: how, do, I, the", result.err)

    def test_when_no_page_has_every_word_it_says_so_in_the_json_and_to_the_person(self):
        gateway = FakeGateway()
        gateway.search_handler = lambda cql: [] if " OR " not in cql else gateway.search_hits[:2]
        result = run_cli("search", "alpha beta", "--json", gateway=gateway)
        data = result.json()
        self.assertEqual((data["match"], data["relaxed"], data["total"]), ("any", True, 2))
        self.assertIn("No page holds all of these words (alpha, beta)", result.err)
        strict = run_cli("search", "alpha beta", "--match", "all", gateway=gateway)
        self.assertEqual(strict.out.strip(), "Nothing found.")
        self.assertIn("another language", strict.err)

    def test_snippets_are_in_the_json_and_the_text(self):
        gateway = FakeGateway()
        data = run_cli("search", "release notes", "--snippets", "2", "--json", gateway=gateway).json()
        first = data["hits"][0]
        self.assertEqual(first["matched"], ["release", "notes"])
        self.assertIn("[email]", first["snippet"])
        self.assertNotIn(ACCOUNT, json.dumps(data))
        text = run_cli("search", "release notes", "--snippets", "2", gateway=FakeGateway()).out
        self.assertIn("2002  page  ENG  Release notes", text)
        self.assertIn("    in: Engineering Home", text)
        self.assertIn("    labels: release, notes", text)
        self.assertNotIn("ID  ", text)  # a list, not the table

    def test_the_table_has_a_path_column_when_there_is_a_path_and_not_otherwise(self):
        self.assertEqual(run_cli("search", "x").out.splitlines()[0].split(), ["ID", "TYPE", "SPACE", "TITLE", "MODIFIED", "PATH"])
        gateway = FakeGateway()
        gateway.search_handler = lambda cql: [SearchHit("1", "page", "T", "ENG")]
        self.assertEqual(run_cli("search", "x", gateway=gateway).out.splitlines()[0].split(), ["ID", "TYPE", "SPACE", "TITLE", "MODIFIED"])

    def test_the_options_are_checked(self):
        self.assertEqual(run_cli("search", "x", "--match", "some").code, 2)
        self.assertEqual(run_cli("search", "x", "--snippets", "26").code, 2)
        self.assertEqual(run_cli("search", "x", "--snippets", "-1").code, 2)

    def test_the_raw_answer_has_the_expanded_fields_and_no_people(self):
        raw = json.loads(run_cli("search", "x", "--raw").out)
        self.assertNotIn(ACCOUNT, json.dumps(raw))

    def test_excerpts_and_snippets_together_show_the_snippets_for_a_person_who_may_not_see_excerpts(self):
        result = run_cli("search", "release", "--excerpts", "--snippets", "1")
        self.assertIn("in: Engineering Home", result.out)
        self.assertNotIn("the october notes", result.out)  # the excerpt of the index stays out without --with-users
        self.assertIn("--with-users", result.err)


class PageInPartsTest(unittest.TestCase):
    def test_the_outline_as_text(self):
        result = run_cli("page", "2005", "--outline", gateway=gateway_with_headings())
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("Outline (read one part with --section TITLE or --section NUMBER):", result.out)
        lines = [line for line in result.out.splitlines() if "characters)" in line]
        self.assertEqual([line.split("(")[0].split() for line in lines], [["1.", "Intro"], ["2.", "Steps"], ["3.", "Notes"]])
        self.assertGreater(len(lines[1]) - len(lines[1].lstrip()), 0)
        self.assertNotIn("Alpha text", result.out)  # no body

    def test_the_outline_as_json(self):
        data = run_cli("page", "2005", "--outline", "--json", gateway=gateway_with_headings()).json()
        self.assertIsNone(data["body"])
        self.assertEqual([(e["index"], e["level"], e["title"]) for e in data["outline"]], [(1, 1, "Intro"), (2, 2, "Steps"), (3, 2, "Notes")])
        self.assertEqual(set(data["outline"][0]), {"index", "level", "title", "chars"})
        self.assertNotIn("outline", run_cli("page", "2005", "--json", gateway=gateway_with_headings()).json())

    def test_a_section_as_json_text_and_body_only(self):
        gateway = gateway_with_headings()
        data = run_cli("page", "2005", "--section", "steps", "--json", gateway=gateway).json()
        self.assertEqual((data["body"]["section"], data["body"]["truncated"], data["body"]["totalChars"]), ("Steps", False, None))
        self.assertTrue(data["body"]["value"].startswith("## Steps"))
        self.assertFalse(data["body"]["value"].endswith("\n"))
        self.assertIn("Section:", run_cli("page", "2005", "--section", "2", gateway=gateway).out)
        only = run_cli("page", "2005", "--section", "Steps", "--body-only", gateway=gateway)
        self.assertEqual(only.out, data["body"]["value"] + "\n")

    def test_a_cut_text_says_so_in_the_json_and_to_the_person(self):
        gateway = gateway_with_headings()
        data = run_cli("page", "2005", "--max-chars", "100", "--json", gateway=gateway).json()
        self.assertEqual((data["body"]["truncated"], data["body"]["section"]), (True, None))
        self.assertGreater(data["body"]["totalChars"], 100)
        self.assertLessEqual(len(data["body"]["value"]), 101)
        result = run_cli("page", "2005", "--max-chars", "100", gateway=gateway)
        self.assertIn("The text was cut:", result.err)
        self.assertIn("--outline", result.err)
        self.assertEqual(run_cli("page", "2005", "--max-chars", "100000", gateway=gateway).err.count("The text was cut"), 0)

    def test_what_does_not_fit_together_is_a_usage_error(self):
        gateway = gateway_with_headings()
        for argv in (
            ("--outline", "--body-only"),
            ("--outline", "--section", "Steps"),
            ("--raw", "--outline"),
            ("--raw", "--section", "Steps"),
            ("--raw", "--max-chars", "10"),
            ("--outline", "--format", "storage"),
            ("--section", "Steps", "--format", "text"),
            ("--max-chars", "50", "--format", "storage"),
            ("--outline", "--no-body"),
            ("--max-chars", "-5"),
        ):
            with self.subTest(argv=argv):
                self.assertEqual(run_cli("page", "2005", *argv, gateway=gateway).code, 2, argv)

    def test_an_unknown_section_is_an_input_error_that_lists_the_headings(self):
        result = run_cli("page", "2005", "--section", "nothing", "--json", gateway=gateway_with_headings())
        self.assertEqual(result.code, 1)
        self.assertIn("1. Intro", result.error()["hint"])


class FollowALinkCommandTest(unittest.TestCase):
    def test_a_page_by_its_title_and_the_tree_below_it(self):
        gateway = FakeGateway()
        self.assertEqual(run_cli("page", "page:ENG/Architecture", "--no-body", "--json", gateway=gateway).json()["id"], "2003")
        self.assertEqual(run_cli("page", "page:Architecture", "--space", "ENG", "--no-body", "--json", gateway=gateway).json()["id"], "2003")
        tree = run_cli("tree", "page:ENG/Architecture", "--depth", "1", "--json", gateway=gateway).json()
        self.assertEqual((tree["root"]["id"], [node["id"] for node in tree["nodes"]]), ("2003", ["2004"]))

    def test_a_missing_title_is_exit_code_4(self):
        result = run_cli("page", "page:ENG/No such page", "--json")
        self.assertEqual(result.code, 4)
        self.assertIn("conflu search", result.error()["hint"])


class ExportPathCommandTest(unittest.TestCase):
    def test_the_json_of_an_export_has_the_path(self):
        data = run_cli("export", "--space", "ENG", "--out", "out", "--json").json()
        paths = {page["id"]: page["path"] for page in data["pages"]}
        self.assertEqual((paths["2001"], paths["2004"]), (None, "Engineering Home > Architecture"))
        self.assertEqual(set(data["pages"][0]), {"id", "title", "parentId", "path", "file", "version", "updated", "lossy"})


if __name__ == "__main__":
    unittest.main()
