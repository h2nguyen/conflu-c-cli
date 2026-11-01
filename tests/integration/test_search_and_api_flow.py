"""The new ways to give a search and a raw call their input, through the real adapters against the mock Confluence: several words, a query file,
`--phrase`, `--param`, `--select` and `--format`, and the envelope of a real answer."""
import json
import unittest

from tests.integration.test_end_to_end import ACCOUNT, EndToEnd


class SearchInputFlowTest(EndToEnd):
    def write_bytes(self, name, data):
        path = self.root / "in" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_several_words_a_quoted_text_and_a_file_find_the_same_pages(self):
        quoted = self.cli("search", "october notes", "--space", "ENG", "--json")
        self.assertEqual(quoted.code, 0, quoted.err)
        words = self.cli("search", "october", "notes", "--space", "ENG", "--json")
        in_a_file = self.cli("search", f"@{self.write_bytes('text.txt', 'october notes'.encode('utf-16'))}", "--space", "ENG", "--json")
        self.assertEqual(words.json(), quoted.json())
        self.assertEqual(in_a_file.json(), quoted.json())
        self.assertGreaterEqual(quoted.json()["count"], 1)

    def test_a_cql_file_and_standard_input_run_the_query(self):
        path = self.write_bytes("query.cql", 'type = page AND space = "ENG" AND title ~ "Release"\r\n'.encode("utf-16"))
        from_file = self.cli("search", "--cql", f"@{path}", "--json")
        self.assertEqual(from_file.code, 0, from_file.err)
        self.assertEqual(from_file.json()["cql"], 'type = page AND space = "ENG" AND title ~ "Release"')
        self.assertEqual([hit["title"] for hit in from_file.json()["hits"]], ["Release notes"])
        piped = self.cli("search", "--cql", "-", "--json", stdin='type = page AND space = "ENG" AND title ~ "Release"')
        self.assertEqual(piped.json()["hits"], from_file.json()["hits"])

    def test_a_phrase_without_a_double_quote_is_searched_as_a_phrase(self):
        result = self.cli("search", "--phrase", "release notes", "--space", "ENG", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(result.json()["terms"], ['"release notes"'])
        self.assertIn('\\"release notes\\"', result.json()["cql"])
        self.assertEqual([hit["title"] for hit in result.json()["hits"]], ["Release notes"])

    def test_select_and_format_on_real_answers(self):
        picked = self.cli("pages", "--space", "ENG", "--all", "--select", "id,title", "--json").json()
        self.assertEqual(picked["count"], 5)
        self.assertEqual(set(picked["pages"][0]), {"id", "title"})
        tsv = self.cli("pages", "--space", "ENG", "--all", "--select", "id,title", "--format", "tsv")
        self.assertEqual(tsv.out.splitlines()[0], "id\ttitle")
        self.assertEqual(len(tsv.out.splitlines()), 6)
        tree = self.cli("tree", "2001", "--select", "id,depth", "--format", "md")
        self.assertEqual(tree.out.splitlines()[:2], ["| id | depth |", "| --- | --- |"])
        spaces = self.cli("spaces", "--all", "--format", "tsv")
        self.assertEqual(spaces.out.splitlines()[0], "KEY\tNAME\tTYPE\tSTATUS\tHOMEPAGE")


class RawCallFlowTest(EndToEnd):
    def test_param_adds_the_query_parameters_of_a_real_call(self):
        result = self.cli("api", "GET", "api/v2/pages", "--param", "limit=1", "--param", "sort=id", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(len(result.json()["results"]), 1)
        sent = [item for item in self.mock.requests if item.path.endswith("/api/v2/pages")][-1]
        self.assertEqual(sent.query, {"limit": ["1"], "sort": ["id"]})

    def test_a_value_with_an_ampersand_and_blanks_reaches_the_server_as_one_value(self):
        cql = 'type = page AND title ~ "Plain & simple"'
        self.cli("api", "GET", "rest/api/search", "--param", f"cql={cql}", "--param", "limit=1", "--json")
        sent = [item for item in self.mock.requests if item.path.endswith("/rest/api/search")][-1]
        self.assertEqual(sent.query["cql"], [cql])
        self.assertEqual(sent.query["limit"], ["1"])

    def test_the_json_dry_run_sends_nothing(self):
        before = len(self.mock.requests)
        result = self.cli("api", "PUT", "api/v2/pages/2005/title", "--data", '{"status": "current", "title": "Never"}', "--write", "--dry-run", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(json.loads(result.out)["dryRun"], True)
        self.assertEqual(len(self.mock.requests), before)
        self.assertEqual(self.mock.pages["2005"]["title"], "Plain page")

    def test_the_envelope_of_a_real_answer_and_of_a_real_refusal(self):
        ok = self.cli("api", "GET", "api/v2/pages/2005", "--json-envelope")
        self.assertEqual((ok.code, ok.json()["ok"], ok.json()["data"]["id"]), (0, True, "2005"))
        self.assertEqual(len(ok.out.splitlines()), 1)
        refused = self.cli("api", "GET", "api/v2/pages/999", "--json-envelope")
        self.assertEqual(refused.code, 4)
        self.assertEqual((refused.json()["ok"], refused.json()["error"]["code"]), (False, "NOT_FOUND"))
        self.assertEqual(len(refused.out.splitlines()), 1)
        self.assertIn("Not found", refused.err)

    def test_the_envelope_of_the_real_program_as_a_child_process(self):
        done = self.child("pages", "--space", "ENG", "--limit", "1", "--json-envelope")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(done.json()["data"]["count"], 1)
        failed = self.child("page", "999", "--json-envelope")
        self.assertEqual(failed.code, 4)
        self.assertEqual(failed.json()["error"]["exitCode"], 4)

    def test_a_dot_segment_in_any_spelling_leaves_the_server_unasked(self):
        before = len(self.mock.requests)
        for path in ("api/v2/pages/.%2e/spaces", "api/v2/pages/%2e./spaces", "api/v2/pages/%2E%2E/spaces", "api/v2/pages/..;x/spaces", "api/v2/pages/..#x"):
            with self.subTest(path=path):
                result = self.cli("api", "GET", path)
                self.assertEqual(result.code, 2, result.err)
                self.assertIn("The path must not contain `..`", result.err)
        self.assertEqual(len(self.mock.requests), before)


class PeopleInSearchFlowTest(EndToEnd):
    """The search index lists people besides pages, through the real mapper and the mock: without --with-users nobody is listed."""

    PEOPLE = 'type = user AND user.fullname ~ "a*"'

    def test_a_search_for_people_lists_nobody_and_says_how_many_hits_were_left_out(self):
        result = self.cli("search", "--cql", self.PEOPLE, "--all", "--json")
        self.assertEqual(result.code, 0, result.err)
        data = result.json()
        self.assertEqual((data["hits"], data["count"], data["total"]), ([], 0, 1))
        self.assertTrue(data["notes"][0].startswith("1 hit about people was left out"), data["notes"])
        for text in (ACCOUNT, "Alex", "alex@example.com"):
            self.assertNotIn(text, result.out + result.err)
        raw = self.cli("search", "--cql", self.PEOPLE, "--all", "--raw")
        self.assertEqual(json.loads(raw.out)["results"], [])
        for text in (ACCOUNT, "Alex"):
            self.assertNotIn(text, raw.out + raw.err)

    def test_with_users_the_people_are_listed(self):
        data = self.cli("search", "--cql", self.PEOPLE, "--all", "--with-users", "--json").json()
        self.assertEqual([(hit["type"], hit["title"]) for hit in data["hits"]], [("user", "Alex Example")])
        self.assertIn(ACCOUNT, data["hits"][0]["url"])
        self.assertEqual(data["notes"], [])
        raw = json.loads(self.cli("search", "--cql", self.PEOPLE, "--all", "--with-users", "--raw").out)
        self.assertEqual(raw["results"][0]["user"]["accountId"], ACCOUNT)

    def test_a_wildcard_that_matches_nobody_finds_nothing_at_all(self):
        data = self.cli("search", "--cql", 'type = user AND user.fullname ~ "zz*"', "--json").json()
        self.assertEqual((data["total"], data["hits"]), (0, []))
        self.assertTrue(data["notes"][0].startswith("Nothing found."))

    def test_under_the_policy_the_flag_is_refused_and_the_people_stay_out_without_it(self):
        strict = {"CONFLUENCE_HIDE_USERS": "true"}
        refused = self.cli("search", "--cql", self.PEOPLE, "--with-users", env=strict)
        self.assertEqual(refused.code, 1)
        self.assertIn("CONFLUENCE_HIDE_USERS", refused.err)
        result = self.cli("search", "--cql", self.PEOPLE, "--json", env=strict)
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("CONFLUENCE_HIDE_USERS=true keeps people out", result.json()["notes"][0])
        self.assertNotIn("Alex", result.out)

    def test_a_personal_space_comes_out_without_the_name_of_its_owner(self):
        personal = f"~{ACCOUNT}"
        self.mock.add_space(personal, "Alex Example", "personal")
        query = "type = space AND space.type = personal"
        data = self.cli("search", "--cql", query, "--all", "--json").json()
        self.assertEqual([(hit["type"], hit["spaceKey"], hit["title"], hit["url"]) for hit in data["hits"]], [("space", "[hidden]", "[personal space]", "")])
        raw = self.cli("search", "--cql", query, "--all", "--raw")
        for text in (ACCOUNT, "Alex"):
            self.assertNotIn(text, raw.out + self.cli("search", "--cql", query, "--all", "--json").out)
        item = json.loads(raw.out)["results"][0]
        self.assertEqual((item["title"], item["url"], item["resultGlobalContainer"]), ("[personal space]", "", {"title": "[personal space]", "displayUrl": ""}))
        shown = self.cli("search", "--cql", query, "--all", "--with-users", "--json").json()["hits"][0]
        self.assertEqual((shown["spaceKey"], shown["title"]), (personal, "Alex Example"))

    def test_the_other_spaces_are_listed_as_they_are(self):
        data = self.cli("search", "--cql", "type = space", "--all", "--json").json()
        self.assertEqual(sorted(hit["spaceKey"] for hit in data["hits"]), ["DOCS", "ENG"])
        self.assertEqual({hit["type"] for hit in data["hits"]}, {"space"})


class FileLimitFlowTest(EndToEnd):
    """A file that is longer than the limit is refused after one byte beyond it, by the real file system adapter."""

    def test_a_query_file_of_a_megabyte_and_one_byte_is_refused_and_nothing_is_asked(self):
        before = len(self.mock.requests)
        path = self.root / "query.txt"
        path.write_bytes(b"type = page" + b" " * (1024 * 1024 - 11))
        self.assertEqual(self.cli("search", "--cql", f"@{path}", "--json").code, 0)
        path.write_bytes(b"type = page" + b" " * (1024 * 1024 - 10))
        refused = self.cli("search", "--cql", f"@{path}")
        self.assertEqual(refused.code, 2)
        self.assertIn("at most 1,048,576 bytes", refused.err)
        self.assertEqual(len([item for item in self.mock.requests[before:] if item.path.endswith("/search")]), 1)

    def test_a_text_file_over_the_limit_is_refused_by_every_way_to_read_it(self):
        path = self.root / "big.md"
        path.write_bytes(b"# Big\n\n" + b"word " * 3_400_000)  # a little over 16 MiB
        before = len(self.mock.requests)
        for argv in (("comment", "2005", "--file", str(path)), ("update", "2005", "--file", str(path)), ("import-md", str(path), "--space", "ENG"), ("convert", str(path))):
            with self.subTest(argv=argv[0]):
                result = self.cli(*argv)
                self.assertEqual(result.code, 2, result.err)
                self.assertIn("at most 16,777,216 bytes", result.err)
        self.assertEqual([item.target for item in self.mock.requests[before:] if item.method in ("POST", "PUT")], [])

    def test_a_pipe_over_the_limit_is_refused_by_the_real_program(self):
        done = self.child("search", "-", stdin="x" * (1024 * 1024 + 1))
        self.assertEqual(done.code, 2)
        self.assertIn("Standard input holds more than 1,048,576 bytes", done.err)


if __name__ == "__main__":
    unittest.main()
