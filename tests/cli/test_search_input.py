"""What `conflu search` accepts as its input: several words without quotes, `@FILE` and `-` for the text and for the CQL, `--phrase`, and what the
usage errors say about Windows PowerShell 5.1 (which removes the double quotes inside an argument)."""
import unittest

from conflu_c_cli.adapters.driving.cli.help import catalog, mcp_tools
from conflu_c_cli.adapters.driving.cli.parser import usage_hint
from conflu_c_cli.adapters.driving.cli.registry import all_commands, find_command
from conflu_c_cli.version import __version__
from tests.support.cli import run_cli
from tests.support.encodings import ENCODINGS
from tests.support.fakes import FakeGateway, MemoryFiles, default_settings

WORDS_CQL = 'type = page AND space = "ENG" AND text ~ "story points reference"'


class SeveralWordsTest(unittest.TestCase):
    def search(self, *argv, **options):
        gateway = FakeGateway()
        result = run_cli("search", *argv, gateway=gateway, **options)
        return result, gateway

    def test_several_words_need_no_quotes(self):
        result, gateway = self.search("story", "points", "reference", "--space", "ENG", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(gateway.called("search")[0][1], WORDS_CQL)
        self.assertEqual(result.json()["terms"], ["story", "points", "reference"])

    def test_one_quoted_text_is_the_same_search(self):
        for argv in (("story points reference", "--space", "ENG"), ("--space", "ENG", "story points reference"), ("--space", "ENG", "story", "points", "reference")):
            with self.subTest(argv=argv):
                result, gateway = self.search(*argv)
                self.assertEqual(result.code, 0, result.err)
                self.assertEqual(gateway.called("search")[0][1], WORDS_CQL)

    def test_a_quoted_phrase_among_the_words_stays_together(self):
        _, gateway = self.search('"SSO group"', "roles", "--space", "ENG")
        self.assertEqual(gateway.called("search")[0][1], 'type = page AND space = "ENG" AND text ~ "roles" AND text ~ "\\"SSO group\\""')

    def test_no_words_is_the_same_as_before(self):
        self.assertEqual(self.search()[0].code, 1)  # nothing to search for
        result, gateway = self.search("--space", "ENG", "--label", "adr", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(result.json()["terms"], [])
        self.assertEqual(gateway.called("search")[0][1], 'type = page AND space = "ENG" AND label = "adr" ORDER BY lastmodified DESC')

    def test_the_usage_shows_that_several_words_may_follow(self):
        self.assertIn("Usage: conflu search [TEXT...] [--phrase TEXT]", run_cli("help", "search").out)

    def test_words_that_are_split_by_an_option_are_a_usage_error_that_names_the_powershell_cause(self):
        result, gateway = self.search("story", "--space", "ENG", "points")
        self.assertEqual(result.code, 2)
        self.assertIn("unrecognized arguments: points", result.err)
        self.assertIn("Windows PowerShell 5.1 removed them", result.err)
        for way in ("'@query.txt'", "`-` for standard input", "--phrase 'exact words'", 'write each double quote as \\"'):
            self.assertIn(way, result.err)
        self.assertEqual(gateway.called("search"), [])

    def test_the_catalog_and_the_tool_description_know_the_kinds(self):
        entry = next(item for item in catalog(all_commands(), __version__)["commands"] if item["name"] == "search")
        kinds = {arg["names"][0]: arg["kind"] for arg in entry["arguments"]}
        self.assertEqual((kinds["text"], kinds["--phrase"], kinds["--cql"]), ("words", "repeat", "str"))
        tool = next(item for item in mcp_tools(all_commands(), __version__)["tools"] if item["name"] == "conflu_search")
        properties = tool["inputSchema"]["properties"]
        self.assertEqual(properties["text"]["type"], "string")
        self.assertEqual((properties["phrase"]["type"], properties["phrase"]["items"]), ("array", {"type": "string"}))
        self.assertNotIn("format", properties)  # a table for a person: a call for a model asks for JSON
        self.assertIn("select", properties)

    def test_the_words_as_they_came_stay_available_to_a_command_that_needs_them(self):
        from conflu_c_cli.adapters.driving.cli.parser import build_parser

        namespace = build_parser(find_command("search")).parse_args(["a b", "c"])
        self.assertEqual((namespace.text, namespace.text_words), ("a b c", ["a b", "c"]))
        self.assertEqual(build_parser(find_command("search")).parse_args([]).text_words, [])


class QueryFilesTest(unittest.TestCase):
    def run_file(self, *argv, data=b"", name="query.txt", **options):
        self.gateway = FakeGateway()
        files = MemoryFiles()
        files.write_bytes(name, data)
        return run_cli(*argv, gateway=self.gateway, files=files, **options)

    def test_the_text_from_a_file_in_any_encoding(self):
        for label, encode in ENCODINGS.items():
            with self.subTest(label):
                result = self.run_file("search", "@query.txt", "--space", "ENG", "--json", data=encode("story points reference\r\n"))
                self.assertEqual(result.code, 0, result.err)
                self.assertEqual(self.gateway.called("search")[0][1], WORDS_CQL)

    def test_a_text_with_double_quotes_survives_in_a_file(self):
        result = self.run_file("search", "@query.txt", "--space", "ENG", "--json", data='"SSO group" roles'.encode("utf-16"))
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(result.json()["terms"], ['"SSO group"', "roles"])

    def test_the_cql_from_a_file_is_used_as_it_is(self):
        cql = 'type = page AND space = "ENG" AND title ~ "Größe"'
        for label, encode in ENCODINGS.items():
            if label == "Windows-1252":
                continue  # the text of a CQL query is the one the file holds: Windows-1252 has the same letters
            with self.subTest(label):
                result = self.run_file("search", "--cql", "@query.txt", "--json", data=encode(cql))
                self.assertEqual(result.code, 0, result.err)
                self.assertEqual(result.json()["cql"], cql)
        result = self.run_file("search", "--cql", "@query.txt", "--json", data=ENCODINGS["Windows-1252"](cql + "\r\n"))
        self.assertEqual(result.json()["cql"], cql)

    def test_the_cql_and_the_text_from_standard_input(self):
        cql = run_cli("search", "--cql", "-", "--json", gateway=FakeGateway(), stdin=b"\xef\xbb\xbftype = page AND label = \"adr\"\r\n")
        self.assertEqual(cql.code, 0, cql.err)
        self.assertEqual(cql.json()["cql"], 'type = page AND label = "adr"')
        text = run_cli("search", "-", "--space", "ENG", "--json", gateway=FakeGateway(), stdin="story points reference\r\n".encode("utf-16"))
        self.assertEqual(text.json()["terms"], ["story", "points", "reference"])
        self.assertEqual(run_cli("search", "@-", "--json", gateway=FakeGateway(), stdin="roles").json()["terms"], ["roles"])
        self.assertEqual(run_cli("search", "--cql", "@-", "--json", gateway=FakeGateway(), stdin="type = page").json()["cql"], "type = page")

    def test_a_file_name_with_a_blank_works_when_it_is_quoted(self):
        result = self.run_file("search", "@my query.txt", "--space", "ENG", "--json", name="my query.txt", data=b"story points reference")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.gateway.called("search")[0][1], WORDS_CQL)

    def test_a_text_that_starts_with_an_at_sign_and_names_no_file_is_searched_for_as_text_with_a_warning(self):
        for text in ("@alex", "@example.com", "@alex smith"):
            with self.subTest(text=text):
                gateway = FakeGateway()
                result = run_cli("search", text, "--json", gateway=gateway, files=MemoryFiles())
                self.assertEqual(result.code, 0, result.err)  # as in 1.0.0: the text is what is searched for
                self.assertIn(f'text ~ "{text.split()[0]}', gateway.called("search")[0][1])
                self.assertIn("starts with @ and no file of that name was found", result.err)
                self.assertIn("searched for as text", result.err)
                self.assertEqual(result.json()["cql"], gateway.called("search")[0][1])

    def test_the_warning_for_a_text_without_a_file_is_not_hidden_by_the_agent_profile(self):
        result = run_cli("search", "@alex", gateway=FakeGateway(), files=MemoryFiles(), settings=default_settings(profile="agent"))
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("starts with @ and no file of that name was found", result.err)

    def test_a_text_that_starts_with_an_at_sign_is_read_from_the_file_when_there_is_one_and_says_so(self):
        result = self.run_file("search", "@query.txt", "--space", "ENG", "--json", data=b"story points reference")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.gateway.called("search")[0][1], WORDS_CQL)
        self.assertIn("was read from the file query.txt", result.err)
        self.assertIn("put a space in front of it or use --phrase", result.err)

    def test_a_space_in_front_searches_for_the_text_even_when_a_file_of_that_name_is_there(self):
        result = self.run_file("search", " @query.txt", "--json", data=b"story points reference")
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("query.txt", self.gateway.called("search")[0][1])
        self.assertNotIn("story points reference", self.gateway.called("search")[0][1])
        self.assertNotIn("was read from the file", result.err)

    def test_a_cql_that_starts_with_an_at_sign_and_a_missing_file_stay_an_error(self):
        gateway = FakeGateway()
        result = run_cli("search", "--cql", "@alex", gateway=gateway, files=MemoryFiles())
        self.assertEqual(result.code, 1)
        self.assertIn("alex", result.err)
        self.assertIn("put a space in front", result.err)
        self.assertEqual(gateway.calls, [])

    def test_a_literal_at_sign_is_searched_for_with_a_space_in_front_or_as_a_phrase(self):
        gateway = FakeGateway()
        run_cli("search", " @alex", gateway=gateway, files=MemoryFiles())
        run_cli("search", "--phrase", "@alex", gateway=gateway, files=MemoryFiles())
        self.assertEqual(len(gateway.called("search")), 2)
        self.assertIn("alex", gateway.called("search")[0][1])
        self.assertIn('"@alex"', gateway.called("search")[1][1])

    def test_an_empty_file_or_input_is_an_error_that_names_it(self):
        for argv, data, stdin, named in (
            (("search", "@query.txt"), b"", "", "query.txt"),
            (("search", "--cql", "@query.txt"), b"  \r\n", "", "query.txt"),
            (("search", "-"), b"", b"", "standard input"),
            (("search", "--cql", "-"), b"", b"\n", "standard input"),
        ):
            with self.subTest(argv=argv):
                result = self.run_file(*argv, data=data, stdin=stdin)
                self.assertEqual(result.code, 2, result.err)
                self.assertIn("is empty", result.err)
                self.assertIn(named, result.err)
                self.assertEqual(self.gateway.called("search"), [])

    def test_a_query_file_is_read_up_to_a_megabyte_and_no_further(self):
        query = b"type = page"
        exactly = query + b" " * (1024 * 1024 - len(query))
        self.assertEqual(self.run_file("search", "--cql", "@query.txt", "--json", data=exactly).code, 0)
        result = self.run_file("search", "--cql", "@query.txt", data=exactly + b" ")
        self.assertEqual(result.code, 2)
        self.assertIn("at most 1,048,576 bytes", result.err)
        self.assertEqual(self.gateway.called("search"), [])

    def test_a_query_file_that_is_no_text_and_one_that_is_missing_are_refused(self):
        result = self.run_file("search", "--cql", "@query.txt", data=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
        self.assertEqual(result.code, 1)
        self.assertIn("query.txt is not text", result.err)
        missing = run_cli("search", "--cql", "@missing.txt", files=MemoryFiles())
        self.assertEqual(missing.code, 1)
        self.assertIn("missing.txt", missing.err)
        self.assertIn("starts with @", missing.err)

    def test_the_file_forms_are_marked_for_a_server_that_must_not_read_files_for_a_model(self):
        search = find_command("search")
        self.assertEqual({arg.names[0] for arg in search.args if arg.at_file}, {"text", "--cql"})


class PhraseTest(unittest.TestCase):
    def search(self, *argv):
        gateway = FakeGateway()
        result = run_cli("search", *argv, gateway=gateway)
        return result, gateway

    def test_a_phrase_is_quoted_for_the_person_and_stays_together(self):
        result, gateway = self.search("--phrase", "retention policy", "--space", "ENG", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(gateway.called("search")[0][1], 'type = page AND space = "ENG" AND text ~ "\\"retention policy\\""')
        self.assertEqual(result.json()["terms"], ['"retention policy"'])

    def test_phrases_and_words_work_together_and_the_phrases_come_first(self):
        result, gateway = self.search("roles", "--phrase", "SSO group", "--phrase", "access request", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(result.json()["terms"], ['"SSO group"', '"access request"', "roles"])
        self.assertIn('text ~ "roles"', gateway.called("search")[0][1])

    def test_a_single_word_phrase_is_kept_even_when_it_is_filler(self):
        result, _ = self.search("--phrase", "the", "--json")
        self.assertEqual(result.json()["terms"], ["the"])

    def test_the_blanks_of_a_phrase_are_made_single(self):
        result, _ = self.search("--phrase", "  retention   policy ", "--json")
        self.assertEqual(result.json()["terms"], ['"retention policy"'])

    def test_a_double_quote_or_a_control_character_in_a_phrase_is_a_usage_error(self):
        for phrase in ('say "this"', "\u201cquoted\u201d", "\u00abquoted\u00bb", "line\nbreak", "tab\there", "bell\x07", "c1\x9b"):
            with self.subTest(phrase=phrase):
                result, gateway = self.search("--phrase", phrase)
                self.assertEqual(result.code, 2)
                self.assertIn("--phrase must not contain a double quote or a control character", result.err)
                self.assertEqual(gateway.called("search"), [])

    def test_an_empty_phrase_is_a_usage_error(self):
        for phrase in ("", "   "):
            with self.subTest(phrase=phrase):
                result, _ = self.search("--phrase", phrase)
                self.assertEqual(result.code, 2)
                self.assertIn("--phrase needs the words", result.err)

    def test_a_phrase_cannot_go_with_a_cql_query(self):
        result, gateway = self.search("--phrase", "retention policy", "--cql", "type = page")
        self.assertEqual(result.code, 2)
        self.assertIn("--phrase cannot be combined with --cql", result.err)
        self.assertEqual(gateway.called("search"), [])

    def test_a_single_quote_is_no_problem(self):
        result, _ = self.search("--phrase", "it's here", "--json")
        self.assertEqual(result.json()["terms"], ['"it\'s here"'])


class UsageHintTest(unittest.TestCase):
    def test_an_option_of_another_command_is_named_with_that_command(self):
        result = run_cli("pages", "--label", "adr")
        self.assertEqual(result.code, 2)
        self.assertIn("`--label` is not an option of `conflu pages`", result.err)
        self.assertIn("`conflu search`", result.err)
        self.assertNotIn("PowerShell", result.err)

    def test_an_option_of_the_list_commands_is_found_where_it_exists(self):
        hint = usage_hint(find_command("page"), "unrecognized arguments: --select id")
        self.assertIn("`--select` is not an option of `conflu page`", hint)
        named = [name for name in ("pages", "versions", "spaces", "search", "comments", "labels", "attachments", "tree") if f"`conflu {name}`" in hint]
        self.assertTrue(1 <= len(named) <= 3, hint)  # at most three are named
        self.assertTrue(hint.endswith(" has it."))

    def test_a_stray_word_after_a_command_that_takes_no_query_says_nothing_about_quotes(self):
        for argv in (("versions", "2002", "2003"), ("labels", "2002", "stray"), ("pages", "stray")):
            with self.subTest(argv=argv):
                result = run_cli(*argv)
                self.assertEqual(result.code, 2)
                self.assertNotIn("PowerShell", result.err)

    def test_a_stray_option_after_a_search_does_not_blame_the_quotes(self):
        hint = usage_hint(find_command("search"), "unrecognized arguments: --nope")
        self.assertNotIn("PowerShell", hint)
        self.assertTrue(hint.startswith("Run `conflu help search`"))

    def test_other_usage_errors_keep_their_plain_hint(self):
        self.assertEqual(usage_hint(find_command("search"), "argument --limit: expected one argument"), "Run `conflu help search` for the usage and examples.")


if __name__ == "__main__":
    unittest.main()
