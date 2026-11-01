"""Looking up people, the real program against the mock Confluence: the requests that are sent, the escaping of a name, privacy, failures."""
import re
import unittest

from tests.integration.test_end_to_end import ACCOUNT, EndToEnd

SAM = "5b10ac8d82e05b22cc7d4ef6"
ODD = "5b10ac8d82e05b22cc7d4f77"
SEARCH = ("GET", "/rest/api/search/user")
LOOKUP = ("POST", "/api/v2/users-bulk")
ONE_COMPARISON = re.compile(r'user\.fullname ~ "((?:\\.|[^"\\])*)"')  # a search for people: one comparison with one CQL string


class UsersFlow(EndToEnd):
    def setUp(self):
        super().setUp()
        alex = self.mock.users[ACCOUNT]
        self.mock.users.clear()  # the people of this mock are those that a test names, and Alex, who owns the token: other areas add people of their own
        self.mock.users[ACCOUNT] = alex

    def add_person(self, account_id, display_name, email="", account_type=None):
        person = {"accountId": account_id, "displayName": display_name, "publicName": display_name, "email": email}
        if account_type:
            person["accountType"] = account_type
        self.mock.users[account_id] = person

    def add_sams(self, count):
        for number in range(1, count + 1):
            self.add_person(f"5b10ac8d82e05b22cc7d4f{number:02d}", f"Sam Example {number}", f"sam{number}@example.com")

    def calls(self):
        return [(item.method, item.path) for item in self.mock.requests]

    def nothing_unknown(self):
        self.assertEqual((self.mock.unknown_endpoints, self.mock.deprecated_endpoints), ([], []))


class SearchTest(UsersFlow):
    def test_the_search_is_one_v1_get_with_the_query_the_limit_and_the_start(self):
        result = self.cli("users", "search", "alex", "--with-users", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.calls(), [SEARCH])
        self.assertEqual(self.mock.requests[0].query, {"cql": ['user.fullname ~ "alex"'], "limit": ["25"], "start": ["0"]})
        self.assertEqual(
            result.json(),
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
        self.assertIn("GET /rest/api/search/user", self.mock.used_endpoints)
        self.nothing_unknown()

    def test_a_person_has_what_confluence_says_and_nothing_else(self):
        self.add_person(SAM, "Sam Example", "", "app")
        users = self.cli("users", "search", "example", "--with-users", "--json").json()["users"]
        self.assertEqual([set(item) for item in users], [{"accountId", "displayName", "email", "accountType"}] * 2)
        self.assertEqual(users[1], {"accountId": SAM, "displayName": "Sam Example", "email": None, "accountType": "app"})
        text = self.cli("users", "search", "example", "--with-users").out
        self.assertIn(f"{ACCOUNT}  Alex Example  alex@example.com  atlassian", text)
        self.assertNotIn("profilePicture", text)

    def test_the_search_goes_on_with_start_and_a_limit_the_server_may_cut(self):
        self.add_sams(4)  # five people fit; the mock hands out two at a time
        first = self.cli("users", "search", "example", "--with-users", "--limit", "250", "--json").json()
        self.assertEqual((first["count"], first["total"], first["nextStart"]), (2, 5, 2))
        self.assertEqual(self.mock.requests[0].query["limit"], ["250"])
        third = self.cli("users", "search", "example", "--with-users", "--start", "4", "--limit", "1", "--json").json()
        self.assertEqual((third["start"], third["count"], third["nextStart"], third["users"][0]["displayName"]), (4, 1, None, "Sam Example 4"))
        self.assertEqual([item.query["start"] for item in self.mock.requests], [["0"], ["4"]])

    def test_all_goes_through_every_piece(self):
        self.add_sams(4)
        data = self.cli("users", "search", "example", "--with-users", "--all", "--json").json()
        self.assertEqual((data["count"], data["total"], data["nextStart"], data["truncated"]), (5, 5, None, False))
        self.assertEqual([(item.query["start"], item.query["limit"]) for item in self.mock.requests], [(["0"], ["50"]), (["2"], ["50"]), (["4"], ["50"])])
        self.assertEqual(len({item["accountId"] for item in data["users"]}), 5)

    def test_a_double_quote_and_a_backslash_in_the_name_stay_a_text(self):
        self.add_person(ODD, 'Quinn "Q" Back\\slash')
        result = self.cli("users", "search", '"Q" Back\\slash', "--with-users", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.mock.requests[0].query["cql"], [r'user.fullname ~ "\"Q\" Back\\slash"'])
        self.assertEqual([item["accountId"] for item in result.json()["users"]], [ODD])

    def test_a_name_that_tries_to_leave_the_string_finds_nobody_and_the_server_reads_it_as_one_comparison(self):
        self.add_person(ODD, "Other Person")
        for hostile in ('x" OR user.fullname ~ "', f'x" OR user.accountid = "{ACCOUNT}', '*" OR "1"="1', "\\", '"', 'a\\" OR "b'):
            with self.subTest(text=hostile):
                result = self.cli("users", "search", hostile, "--with-users", "--json")
                self.assertEqual(result.code, 0, result.err)  # the mock refuses (HTTP 400) a query that is more than one comparison
                self.assertEqual(result.json()["users"], [])
                (cql,) = self.mock.requests[-1].query["cql"]
                self.assertIsNotNone(ONE_COMPARISON.fullmatch(cql), cql)
        self.assertTrue(all(item.path == SEARCH[1] for item in self.mock.requests))

    def test_the_name_in_a_file_in_every_encoding_a_shell_writes_or_on_standard_input(self):
        self.add_person(ODD, 'Quinn "Q" Back\\slash')
        for name, content in (("utf8.txt", '"Q" Back\\slash\n'.encode("utf-8")), ("utf16.txt", '"Q" Back\\slash'.encode("utf-16")), ("bom.txt", b"\xef\xbb\xbf" + '"Q" Back\\slash'.encode("utf-8"))):
            path = self.root / name
            path.write_bytes(content)
            with self.subTest(file=name):
                result = self.cli("users", "search", f"@{path}", "--with-users", "--json")
                self.assertEqual([item["accountId"] for item in result.json()["users"]], [ODD], result.err)
        piped = self.cli("users", "search", "-", "--with-users", "--json", stdin='"Q" Back\\slash\n')
        self.assertEqual([item["accountId"] for item in piped.json()["users"]], [ODD])

    def test_nothing_is_sent_for_a_name_that_is_nothing_or_too_long(self):
        for argv in (("users", "search", "   ", "--with-users"), ("users", "search", "a" * 257, "--with-users"), ("users", "search", "alex", "--with-users", "--limit", "0")):
            with self.subTest(argv=argv):
                self.assertNotEqual(self.cli(*argv).code, 0)
        self.assertEqual(self.mock.requests, [])

    def test_a_search_that_is_refused_or_fails_is_an_error(self):
        self.mock.fail_next("/rest/api/search/user", 403, body={"message": "No permission"})
        self.assertEqual(self.cli("users", "search", "alex", "--with-users").code, 5)
        self.mock.fail_next("/rest/api/search/user", 400, body={"message": "Could not parse cql"})
        refused = self.cli("users", "search", "alex", "--with-users")
        self.assertEqual(refused.code, 6)
        self.assertIn("Could not parse cql", refused.err)
        self.mock.fail_next("/rest/api/search/user", 500)
        self.assertEqual(self.cli("users", "search", "alex", "--with-users").code, 7)
        self.assertEqual(self.cli("users", "search", "alex", "--with-users", env={"CONFLUENCE_API_TOKEN": "wrong-token"}).code, 5)

    def test_select_and_format(self):
        self.add_sams(1)
        tsv = self.cli("users", "search", "example", "--with-users", "--select", "accountId,email", "--format", "tsv").out
        self.assertEqual(tsv.splitlines(), ["accountId\temail", f"{ACCOUNT}\talex@example.com", "5b10ac8d82e05b22cc7d4f01\tsam1@example.com"])


class LookupTest(UsersFlow):
    def test_the_lookup_is_one_v2_post_with_the_ids_and_nothing_of_v1(self):
        self.add_person(SAM, "Sam Example", "sam@example.com", "app")
        result = self.cli("users", "lookup", SAM, ACCOUNT, "--with-users", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.calls(), [LOOKUP])
        self.assertEqual(self.mock.requests[0].body, {"accountIds": [SAM, ACCOUNT]})
        data = result.json()
        self.assertEqual((data["requested"], data["count"], data["notFound"]), (2, 2, []))
        self.assertEqual([item["accountId"] for item in data["users"]], [SAM, ACCOUNT])  # in the order asked
        self.assertEqual(data["users"][0], {"accountId": SAM, "displayName": "Sam Example", "email": "sam@example.com", "accountType": "app"})
        self.assertEqual(self.mock.used_endpoints, ["POST /api/v2/users-bulk"])
        self.nothing_unknown()

    def test_an_id_that_is_not_described_is_left_out_and_named(self):
        result = self.cli("users", "lookup", f"{ACCOUNT},unknown-id", "--with-users")
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("Alex Example", result.out)
        self.assertIn("Confluence describes nobody for: unknown-id.", result.err)
        data = self.cli("users", "lookup", "unknown-id", "--with-users", "--json").json()
        self.assertEqual((data["count"], data["notFound"], data["users"]), (0, ["unknown-id"], []))

    def test_the_ids_in_a_file_or_on_standard_input(self):
        path = self.root / "ids.txt"
        path.write_text(f"{ACCOUNT}\n", encoding="utf-8")
        from_file = self.cli("users", "lookup", f"@{path}", "--with-users", "--json")
        self.assertEqual([item["accountId"] for item in from_file.json()["users"]], [ACCOUNT])
        piped = self.cli("users", "lookup", "-", "--with-users", "--json", stdin=f"{ACCOUNT}\r\nunknown-id\r\n")
        self.assertEqual(piped.json()["notFound"], ["unknown-id"])

    def test_the_most_the_call_takes_and_nothing_sent_for_more_or_for_what_is_no_id(self):
        ids = [f"id{number}" for number in range(250)]
        self.assertEqual(self.cli("users", "lookup", *ids, "--with-users").code, 0)
        self.assertEqual(len(self.mock.requests[0].body["accountIds"]), 250)
        before = len(self.mock.requests)
        self.assertEqual(self.cli("users", "lookup", *ids, "one-more", "--with-users").code, 2)
        self.assertEqual(self.cli("users", "lookup", 'a" OR "b', "--with-users").code, 1)
        self.assertEqual(self.cli("users", "lookup", "x/../y", "--with-users").code, 1)
        self.assertEqual(len(self.mock.requests), before)

    def test_a_lookup_that_is_refused_or_fails_is_an_error(self):
        self.mock.fail_next("/api/v2/users-bulk", 403, method="POST", body={"errors": [{"status": 403, "title": "Forbidden", "detail": "No permission"}]})
        self.assertEqual(self.cli("users", "lookup", ACCOUNT, "--with-users").code, 5)
        self.mock.fail_next("/api/v2/users-bulk", 400, method="POST", body={"errors": [{"status": 400, "title": "Bad", "detail": "accountIds invalid"}]})
        self.assertEqual(self.cli("users", "lookup", ACCOUNT, "--with-users").code, 6)
        self.mock.fail_next("/api/v2/users-bulk", 503, times=1, method="POST")
        self.assertEqual(self.cli("users", "lookup", ACCOUNT, "--with-users").code, 7)  # a write is never repeated, and a lookup is a POST as well


class PrivacyTest(UsersFlow):
    def test_without_with_users_nothing_is_sent_and_nothing_is_shown(self):
        for argv in (("users", "search", "alex"), ("users", "lookup", ACCOUNT), ("users", "search", "alex", "--json"), ("users", "lookup", "@missing.txt")):
            with self.subTest(argv=argv):
                result = self.cli(*argv)
                self.assertEqual((result.code, result.out), (2, ""))
                self.assertNotIn("alex@example.com", result.err)
        self.assertEqual(self.mock.requests, [])

    def test_under_the_policy_it_is_refused_whatever_is_asked(self):
        env = {"CONFLUENCE_HIDE_USERS": "true"}
        for argv in (("users", "search", "alex", "--with-users"), ("users", "lookup", ACCOUNT, "--with-users"), ("users", "search", "alex")):
            with self.subTest(argv=argv):
                result = self.cli(*argv, env=env)
                self.assertEqual((result.code, result.out), (1, ""))
                self.assertIn("CONFLUENCE_HIDE_USERS=true", result.err)
        self.assertEqual(self.mock.requests, [])
        error = self.cli("users", "search", "alex", "--with-users", "--json", env=env)
        self.assertIn("CONFLUENCE_HIDE_USERS=true", error.err)

    def test_the_agent_profile_hides_people_so_the_command_is_refused_there_too(self):
        result = self.cli("users", "search", "alex", "--with-users", env={"CONFLUENCE_PROFILE": "agent"})
        self.assertEqual(result.code, 1)
        self.assertEqual(self.mock.requests, [])
        allowed = self.cli("users", "search", "alex", "--with-users", env={"CONFLUENCE_PROFILE": "agent", "CONFLUENCE_HIDE_USERS": "false"})
        self.assertEqual(allowed.code, 0, allowed.err)  # a person who says so may

    def test_no_other_command_shows_more_because_of_this_one(self):
        """The people that `users` shows are not shown by the commands that hide them: the output of the page commands has none."""
        self.cli("users", "search", "alex", "--with-users")
        page = self.cli("page", "2002", "--no-body")
        self.assertNotIn("Alex Example", page.out)
        self.assertNotIn(ACCOUNT, page.out)

    def test_a_server_that_refuses_is_scrubbed_under_the_policy_and_not_otherwise(self):
        body = {"message": "No permission for alex@example.com"}
        self.mock.fail_next("/rest/api/search/user", 403, body=body)
        shown = self.cli("users", "search", "alex", "--with-users")
        self.assertNotIn("alex@example.com", shown.err)  # the words of a server in an error are redacted whatever is asked for: an error has no `--with-users`
        self.assertIn("No permission for [email]", shown.err)
        self.assertEqual(self.cli("users", "search", "alex", "--with-users", env={"CONFLUENCE_HIDE_USERS": "true"}).out, "")


class WholeProgramTest(UsersFlow):
    def test_as_a_separate_program(self):
        found = self.child("users", "search", "alex", "--with-users", "--json")
        self.assertEqual(found.code, 0, found.err)
        self.assertEqual(found.json()["users"][0]["accountId"], ACCOUNT)
        looked_up = self.child("users", "lookup", ACCOUNT, "--with-users")
        self.assertIn("Alex Example", looked_up.out)
        refused = self.child("users", "search", "alex")
        self.assertEqual(refused.code, 2)


if __name__ == "__main__":
    unittest.main()
