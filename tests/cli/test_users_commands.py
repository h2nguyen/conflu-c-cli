"""The command `users` (search and lookup) on the command line, with the in-memory Confluence: what it prints, what it refuses, how it is described."""
import re
import unittest

from conflu_c_cli.adapters.driving.cli.help import mcp_tool, render_command_help
from conflu_c_cli.adapters.driving.cli.parser import build_parser
from conflu_c_cli.adapters.driving.cli.registry import find_command
from conflu_c_cli.domain.errors import UnavailableError
from conflu_c_cli.domain.model import User
from tests.support.cli import run_cli
from tests.support.fakes import ACCOUNT, ALEX, FakeGateway, MemoryFiles, default_settings

SAM = "5b10ac8d82e05b22cc7d4ef6"
ODD = "5b10ac8d82e05b22cc7d4f77"
ONE_COMPARISON = re.compile(r'user\.fullname ~ "((?:\\.|[^"\\])*)"')  # a search for people: one comparison with one CQL string


def fresh(*more):
    """Alex, who owns the token, and the people this test names: other areas put people of their own into the fixtures."""
    gateway = FakeGateway()
    gateway.users = {ACCOUNT: ALEX, **{user.account_id: user for user in more}}
    return gateway


def sam():
    return User(SAM, "Sam Example", "")  # no e-mail address: the person keeps it private


class DescriptionTest(unittest.TestCase):
    def test_it_is_a_command_of_the_group_of_the_people_that_only_reads(self):
        command = find_command("users")
        self.assertEqual(command.group, "Access and people")
        self.assertFalse(command.writes or command.for_person or command.local or command.destructive or command.idempotent)
        self.assertTrue(command.json_output and command.output and command.when and command.examples and command.notes)

    def test_the_arguments(self):
        args = {arg.dest: arg for arg in find_command("users").args}
        self.assertEqual(list(args), ["action", "text", "limit", "start", "all", "with_users", "select", "format"])
        self.assertEqual((args["action"].choices, args["action"].required, args["action"].positional), (("search", "lookup"), True, True))
        self.assertEqual((args["text"].kind, args["text"].required, args["text"].at_file), ("words", True, True))  # the name may be `@FILE`
        self.assertEqual(args["with_users"].kind, "flag")
        self.assertFalse(args["with_users"].required)  # the refusal is the use case's, which says how to allow it

    def test_the_examples_parse_and_show_the_file_form(self):
        command = find_command("users")
        for example in command.examples:
            with self.subTest(example=example.command):
                build_parser(command).parse_args(example.command.split(" ", 2)[2].replace("'", "").split())
        self.assertTrue(any("'@name.txt'" in example.command for example in command.examples))

    def test_the_help_says_that_both_need_with_users_and_that_the_policy_refuses_them(self):
        text = " ".join(render_command_help(find_command("users")).split())
        self.assertIn("Both show people, so both need --with-users and are refused when CONFLUENCE_HIDE_USERS=true", text)
        self.assertIn("a name with a double quote or a backslash stays a text", text)
        self.assertIn("Without --with-users nothing is sent at all.", text)
        self.assertIn("GET /rest/api/search/user", text)
        self.assertIn("POST /api/v2/users-bulk", text)

    def test_the_tool_for_an_agent(self):
        tool = mcp_tool(find_command("users"))
        self.assertEqual(tool["inputSchema"]["required"], ["action", "text"])
        self.assertEqual(set(tool["inputSchema"]["properties"]), {"action", "text", "limit", "start", "all", "withUsers", "select"})  # --format shapes text: not offered
        self.assertEqual(tool["inputSchema"]["properties"]["action"]["enum"], ["search", "lookup"])
        self.assertTrue(tool["annotations"]["readOnlyHint"])
        self.assertIn("When to use:", tool["description"])


class RefusalTest(unittest.TestCase):
    def test_without_with_users_it_is_a_usage_error_and_nothing_is_asked(self):
        for argv in (("users", "search", "alex"), ("users", "lookup", ACCOUNT), ("users", "search", "alex", "--json")):
            gateway = fresh()
            result = run_cli(*argv, gateway=gateway)
            with self.subTest(argv=argv):
                self.assertEqual((result.code, result.out), (2, ""))
                self.assertIn("lists people", result.err)
                self.assertIn("Add --with-users", result.err)
                self.assertEqual(gateway.calls, [])

    def test_under_the_policy_it_is_refused_whatever_is_asked_and_the_hint_says_how_to_allow_it(self):
        settings = default_settings(hide_users=True)
        for argv in (("users", "search", "alex", "--with-users"), ("users", "lookup", ACCOUNT, "--with-users"), ("users", "search", "alex")):
            gateway = fresh()
            result = run_cli(*argv, gateway=gateway, settings=settings)
            with self.subTest(argv=argv):
                self.assertEqual((result.code, result.out), (1, ""))
                self.assertIn("CONFLUENCE_HIDE_USERS=true", result.err)
                self.assertIn("Unset CONFLUENCE_HIDE_USERS", result.err)
                self.assertEqual(gateway.calls, [])

    def test_the_refusal_is_there_before_a_file_is_read(self):
        files = MemoryFiles()
        gateway = fresh()
        result = run_cli("users", "search", "@missing.txt", gateway=gateway, files=files)
        self.assertEqual(result.code, 2)
        self.assertIn("lists people", result.err)
        self.assertNotIn("missing.txt", result.err)
        policy = run_cli("users", "lookup", "@missing.txt", "--with-users", gateway=gateway, files=files, settings=default_settings(hide_users=True))
        self.assertEqual(policy.code, 1)
        self.assertEqual(gateway.calls, [])

    def test_the_refusal_as_json_has_the_shape_of_every_error(self):
        error = run_cli("users", "search", "alex", "--json", gateway=fresh()).error()
        self.assertEqual((error["code"], error["exitCode"]), ("USAGE", 2))
        self.assertIn("--with-users", error["hint"])
        policy = run_cli("users", "search", "alex", "--with-users", "--json", gateway=fresh(), settings=default_settings(hide_users=True)).error()
        self.assertEqual((policy["code"], policy["exitCode"]), ("INVALID", 1))

    def test_the_options_of_the_other_commands_that_show_people_do_not_apply_here(self):
        self.assertEqual(run_cli("users", "search", "alex", "--with-users", "--user", ACCOUNT, gateway=fresh()).code, 2)
        self.assertEqual(run_cli("users", "list", "--with-users", gateway=fresh()).code, 2)  # only search and lookup
        self.assertEqual(run_cli("users", "--with-users", gateway=fresh()).code, 2)  # an action and a text are needed


class SearchTest(unittest.TestCase):
    def test_the_people_as_a_table_with_the_e_mail_address_only_where_there_is_one(self):
        gateway = fresh(sam())
        result = run_cli("users", "search", "example", "--with-users", gateway=gateway)
        self.assertEqual(result.code, 0, result.err)
        lines = result.out.splitlines()
        self.assertEqual(lines[0].split(), ["ACCOUNT", "ID", "NAME", "EMAIL", "TYPE"])
        self.assertEqual(lines[1].split(), [ACCOUNT, "Alex", "Example", "alex@example.com", "atlassian"])
        self.assertEqual(lines[2].split(), [SAM, "Sam", "Example", "atlassian"])  # no e-mail address: the column is empty

    def test_several_words_need_no_quotes_and_the_case_does_not_matter(self):
        result = run_cli("users", "search", "ALEX", "example", "--with-users", "--json", gateway=fresh(sam()))
        data = result.json()
        self.assertEqual((data["query"], data["total"], [item["accountId"] for item in data["users"]]), ("ALEX example", 1, [ACCOUNT]))

    def test_the_json(self):
        data = run_cli("users", "search", "alex", "--with-users", "--json", gateway=fresh(sam())).json()
        self.assertEqual(list(data), ["query", "cql", "total", "count", "start", "nextStart", "truncated", "users"])
        self.assertEqual(
            data,
            {
                "query": "alex",
                "cql": 'user.fullname ~ "alex"',
                "total": 1,
                "count": 1,
                "start": 0,
                "nextStart": None,
                "truncated": False,
                "users": [{"accountId": ACCOUNT, "displayName": "Alex Example", "email": "alex@example.com", "accountType": "atlassian"}],
            },
        )

    def test_what_confluence_does_not_say_is_null(self):
        gateway = fresh(sam())
        gateway.account_types[SAM] = ""
        users = run_cli("users", "search", "sam", "--with-users", "--json", gateway=gateway).json()["users"]
        self.assertEqual(users, [{"accountId": SAM, "displayName": "Sam Example", "email": None, "accountType": None}])

    def test_an_account_that_is_not_an_atlassian_one_says_so(self):
        gateway = fresh(User(ODD, "Build Bot", ""))
        gateway.account_types[ODD] = "app"
        self.assertEqual(run_cli("users", "search", "bot", "--with-users", "--json", gateway=gateway).json()["users"][0]["accountType"], "app")

    def test_nobody_found_is_an_answer(self):
        text = run_cli("users", "search", "zzz", "--with-users", gateway=fresh())
        self.assertEqual((text.code, text.out), (0, "No people found.\n"))
        data = run_cli("users", "search", "zzz", "--with-users", "--json", gateway=fresh()).json()
        self.assertEqual((data["count"], data["total"], data["users"], data["nextStart"]), (0, 0, [], None))

    def test_a_search_goes_on_with_start_and_says_where(self):
        gateway = fresh(*[User(f"5b10ac8d82e05b22cc7d4f{number:02d}", f"Sam Example {number}", "") for number in range(1, 5)])
        first = run_cli("users", "search", "example", "--with-users", "--json", gateway=gateway).json()
        self.assertEqual((first["count"], first["total"], first["nextStart"]), (2, 5, 2))
        second = run_cli("users", "search", "example", "--with-users", "--start", str(first["nextStart"]), "--json", gateway=gateway).json()
        self.assertEqual((second["start"], second["count"], second["nextStart"]), (2, 2, 4))
        text = run_cli("users", "search", "example", "--with-users", gateway=gateway)
        self.assertIn("5 people fit, 2 shown so far. Continue with --start 2, or use --all.", text.err)
        self.assertNotIn("Continue with", run_cli("users", "search", "example", "--with-users", "--json", gateway=gateway).err)  # a note for a person is no part of the JSON

    def test_all_fetches_every_person(self):
        gateway = fresh(*[User(f"5b10ac8d82e05b22cc7d4f{number:02d}", f"Sam Example {number}", "") for number in range(1, 5)])
        data = run_cli("users", "search", "example", "--with-users", "--all", "--json", gateway=gateway).json()
        self.assertEqual((data["count"], data["total"], data["nextStart"], data["truncated"]), (5, 5, None, False))
        self.assertEqual(len(gateway.called("search_people")), 3)

    def test_select_and_format(self):
        gateway = fresh(sam())
        tsv = run_cli("users", "search", "example", "--with-users", "--select", "accountId,displayName", "--format", "tsv", gateway=gateway).out
        self.assertEqual(tsv.splitlines(), ["accountId\tdisplayName", f"{ACCOUNT}\tAlex Example", f"{SAM}\tSam Example"])
        md = run_cli("users", "search", "example", "--with-users", "--format", "md", gateway=gateway).out
        self.assertEqual(md.splitlines()[0], "| ACCOUNT ID | NAME | EMAIL | TYPE |")
        data = run_cli("users", "search", "example", "--with-users", "--select", "accountId", "--json", gateway=gateway).json()
        self.assertEqual(data["users"], [{"accountId": ACCOUNT}, {"accountId": SAM}])
        self.assertEqual(data["total"], 2)  # the rest of the document stays
        self.assertEqual(run_cli("users", "search", "example", "--with-users", "--select", "nope", gateway=gateway).code, 2)
        self.assertEqual(run_cli("users", "search", "example", "--with-users", "--json", "--format", "tsv", gateway=gateway).code, 2)

    def test_the_bounds_of_the_options(self):
        for option, value in (("--limit", "0"), ("--limit", "251"), ("--limit", "-3"), ("--start", "-1")):
            with self.subTest(option=option, value=value):
                result = run_cli("users", "search", "alex", "--with-users", option, value, gateway=fresh())
                self.assertEqual((result.code, result.out), (2, ""))
        self.assertEqual(run_cli("users", "search", "alex", "--with-users", "--limit", "250", gateway=fresh()).code, 0)

    def test_a_double_quote_and_a_backslash_in_the_name_stay_a_text(self):
        gateway = fresh(User(ODD, 'Quinn "Q" Back\\slash', ""))
        result = run_cli("users", "search", '"Q" Back\\slash', "--with-users", "--json", gateway=gateway)
        data = result.json()
        self.assertEqual([item["accountId"] for item in data["users"]], [ODD])
        self.assertEqual(data["cql"], r'user.fullname ~ "\"Q\" Back\\slash"')
        self.assertEqual(data["query"], '"Q" Back\\slash')

    def test_a_name_that_tries_to_change_the_query_finds_nobody(self):
        gateway = fresh(User(ODD, "Other Person", ""))
        for hostile in ('x" OR user.fullname ~ "', 'x" OR user.accountid = "' + ACCOUNT, '*" OR "1"="1', "\\"):
            with self.subTest(text=hostile):
                data = run_cli("users", "search", hostile, "--with-users", "--json", gateway=gateway).json()
                self.assertEqual((data["count"], data["users"]), (0, []))
                self.assertIsNotNone(ONE_COMPARISON.fullmatch(data["cql"]), data["cql"])  # one comparison, whatever the name holds

    def test_the_name_in_a_file_or_on_standard_input(self):
        gateway = fresh(User(ODD, 'Quinn "Q" Back\\slash', ""))
        files = MemoryFiles({"name.txt": '"Q" Back\\slash\n'})
        from_file = run_cli("users", "search", "@name.txt", "--with-users", "--json", gateway=gateway, files=files)
        self.assertEqual([item["accountId"] for item in from_file.json()["users"]], [ODD])
        from_pipe = run_cli("users", "search", "-", "--with-users", "--json", gateway=gateway, stdin='"Q" Back\\slash\n')
        self.assertEqual([item["accountId"] for item in from_pipe.json()["users"]], [ODD])
        utf16 = MemoryFiles({"name.txt": '"Q" Back\\slash'.encode("utf-16")})  # what PowerShell 5.1 writes with `>`
        self.assertEqual([item["accountId"] for item in run_cli("users", "search", "@name.txt", "--with-users", "--json", gateway=gateway, files=utf16).json()["users"]], [ODD])

    def test_a_name_file_that_is_empty_or_missing_is_an_error_that_asks_nothing(self):
        gateway = fresh()
        empty = run_cli("users", "search", "@empty.txt", "--with-users", gateway=gateway, files=MemoryFiles({"empty.txt": "  \n"}))
        self.assertEqual(empty.code, 2)
        self.assertIn("is empty", empty.err)
        missing = run_cli("users", "search", "@missing.txt", "--with-users", gateway=gateway, files=MemoryFiles())
        self.assertNotEqual(missing.code, 0)
        self.assertEqual(gateway.calls, [])

    def test_a_search_that_fails_is_an_error(self):
        gateway = fresh()
        gateway.errors["search_people"] = UnavailableError("Cannot reach Confluence.", hint="Check the VPN.")
        result = run_cli("users", "search", "alex", "--with-users", gateway=gateway)
        self.assertEqual((result.code, result.out), (7, ""))
        self.assertIn("Check the VPN.", result.err)

    def test_the_envelope(self):
        data = run_cli("users", "search", "alex", "--with-users", "--json-envelope", gateway=fresh()).json()
        self.assertEqual((data["ok"], data["data"]["count"]), (True, 1))


class LookupTest(unittest.TestCase):
    def test_the_people_behind_the_ids_in_the_order_given(self):
        result = run_cli("users", "lookup", SAM, ACCOUNT, "--with-users", gateway=fresh(sam()))
        self.assertEqual(result.code, 0, result.err)
        lines = result.out.splitlines()
        self.assertEqual([line.split()[0] for line in lines[1:]], [SAM, ACCOUNT])

    def test_the_json(self):
        data = run_cli("users", "lookup", f"{ACCOUNT},{SAM}", "unknown-id", "--with-users", "--json", gateway=fresh(sam())).json()
        self.assertEqual(list(data), ["requested", "count", "notFound", "users"])
        self.assertEqual((data["requested"], data["count"], data["notFound"]), (3, 2, ["unknown-id"]))
        self.assertEqual(data["users"][1], {"accountId": SAM, "displayName": "Sam Example", "email": None, "accountType": "atlassian"})

    def test_an_id_that_is_not_described_is_not_an_error_and_a_note_says_so_to_a_person_only(self):
        text = run_cli("users", "lookup", ACCOUNT, "unknown-id", "--with-users", gateway=fresh())
        self.assertEqual(text.code, 0)
        self.assertIn("Confluence describes nobody for: unknown-id.", text.err)
        as_json = run_cli("users", "lookup", ACCOUNT, "unknown-id", "--with-users", "--json", gateway=fresh())
        self.assertEqual((as_json.code, as_json.err), (0, ""))
        nobody = run_cli("users", "lookup", "unknown-id", "--with-users", gateway=fresh())
        self.assertEqual((nobody.code, nobody.out), (0, "No people found.\n"))

    def test_the_ids_in_a_file_one_to_a_line_or_on_standard_input(self):
        gateway = fresh(sam())
        files = MemoryFiles({"ids.txt": f"{ACCOUNT}\n{SAM}\n"})
        data = run_cli("users", "lookup", "@ids.txt", "--with-users", "--json", gateway=gateway, files=files).json()
        self.assertEqual([item["accountId"] for item in data["users"]], [ACCOUNT, SAM])
        piped = run_cli("users", "lookup", "-", "--with-users", "--json", gateway=gateway, stdin=f"{SAM}\r\n{ACCOUNT}\r\n").json()
        self.assertEqual([item["accountId"] for item in piped["users"]], [SAM, ACCOUNT])

    def test_what_is_no_account_id_and_too_many_ids_are_refused_before_anything_is_asked(self):
        gateway = fresh()
        invalid = run_cli("users", "lookup", 'a"b', "--with-users", gateway=gateway)
        self.assertEqual(invalid.code, 1)
        self.assertIn("Not an account id", invalid.err)
        many = run_cli("users", "lookup", *[f"id{number}" for number in range(251)], "--with-users", gateway=gateway)
        self.assertEqual(many.code, 2)
        self.assertIn("at most 250", many.err)
        self.assertEqual(gateway.calls, [])
        self.assertEqual(run_cli("users", "lookup", *[f"id{number}" for number in range(250)], "--with-users", gateway=gateway).code, 0)

    def test_the_options_of_the_search_do_not_apply_to_a_lookup(self):
        for option in (("--limit", "5"), ("--start", "1"), ("--all",)):
            gateway = fresh()
            result = run_cli("users", "lookup", ACCOUNT, "--with-users", *option, gateway=gateway)
            with self.subTest(option=option):
                self.assertEqual((result.code, result.out), (2, ""))
                self.assertIn("applies to the search", result.err)
                self.assertEqual(gateway.calls, [])

    def test_select_and_format(self):
        tsv = run_cli("users", "lookup", ACCOUNT, "--with-users", "--select", "displayName,email", "--format", "tsv", gateway=fresh()).out
        self.assertEqual(tsv.splitlines(), ["displayName\temail", "Alex Example\talex@example.com"])


if __name__ == "__main__":
    unittest.main()
