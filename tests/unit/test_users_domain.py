"""Looking up people, the rules and the calls: what a name becomes in CQL (and why nothing in it can change the query), the account ids, and how the adapter asks and reads."""
import random
import re
import unittest
import urllib.parse

from conflu_c_cli.adapters.driven import map_users
from conflu_c_cli.adapters.driven.rest_users import V1_CALLS, RestUsers
from conflu_c_cli.domain.errors import UsageError, ValidationError
from conflu_c_cli.domain.users import MAX_ACCOUNT_IDS, MAX_QUERY, PeoplePage, Person, parse_account_ids, search_query

ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"
# What a search for people may be: one comparison of the field with one CQL string. Written here on its own, so that it does not trust the code it checks.
ONE_COMPARISON = re.compile(r'user\.fullname ~ "((?:\\.|[^"\\])*)"')


def text_of(cql):
    """The text that the CQL string holds, read back the way CQL reads a string; None when the query is anything but that one comparison."""
    found = ONE_COMPARISON.fullmatch(cql)
    return None if found is None else re.sub(r"\\(.)", r"\1", found.group(1))


class SearchQueryTest(unittest.TestCase):
    def test_a_name_is_one_comparison_with_the_name_in_quotes(self):
        self.assertEqual(search_query("alex"), 'user.fullname ~ "alex"')
        self.assertEqual(search_query("Alex Example"), 'user.fullname ~ "Alex Example"')

    def test_blanks_are_one_blank_and_the_ends_are_cut(self):
        self.assertEqual(search_query("  Alex \t\n  Example\r\n"), 'user.fullname ~ "Alex Example"')

    def test_a_double_quote_and_a_backslash_are_escaped_so_that_they_stay_text(self):
        self.assertEqual(search_query('say "hi"'), r'user.fullname ~ "say \"hi\""')
        self.assertEqual(search_query("a\\b"), r'user.fullname ~ "a\\b"')
        self.assertEqual(search_query('\\"'), r'user.fullname ~ "\\\""')
        self.assertEqual(search_query("end\\"), r'user.fullname ~ "end\\"')

    def test_a_text_that_tries_to_leave_the_string_finds_nobody_of_that_name_and_changes_no_other_part_of_the_query(self):
        for hostile in (
            'a" OR user = "b',
            '" OR 1=1 OR "',
            'x\\" OR user.accountid = "5b10ac8d82e05b22cc7d4ef5',
            'alex" AND user.userkey ~ "*',
            '\\',
            '"',
            '""',
            'a\\\\" OR "b',
            ') OR (user.fullname ~ "',
        ):
            with self.subTest(text=hostile):
                cql = search_query(hostile)
                self.assertEqual(text_of(cql), " ".join(hostile.split()))  # the whole of it is the text of one comparison
                self.assertTrue(cql.startswith('user.fullname ~ "') and cql.endswith('"'))

    def test_the_escape_holds_for_texts_of_every_shape(self):
        generator = random.Random(2026)
        alphabet = ['"', "\\", " ", "a", "B", "~", "*", "?", "(", ")", "OR", "AND", "=", "\n", "\t", "\x00", "\x07", "\x7f", "é", "日", ":", "'", ","]
        for _ in range(500):
            text = "".join(generator.choice(alphabet) for _ in range(generator.randint(1, 24)))
            if not text.split():
                continue
            with self.subTest(text=text):
                cql = search_query(text)
                self.assertIsNotNone(text_of(cql))
                self.assertFalse(re.search(r"[\x00-\x1f\x7f]", cql), "no control character reaches the query")

    def test_a_control_character_is_a_blank(self):
        self.assertEqual(search_query("a\x00b"), 'user.fullname ~ "a b"')
        self.assertEqual(search_query("a\x07\x7fb"), 'user.fullname ~ "a  b"')

    def test_the_text_that_is_not_ascii_is_kept(self):
        self.assertEqual(search_query("Zoë Müller 日本"), 'user.fullname ~ "Zoë Müller 日本"')

    def test_nothing_to_search_for_is_a_usage_error(self):
        for text in ("", "   ", "\n\t", None):
            with self.subTest(text=text), self.assertRaises(UsageError) as caught:
                search_query(text)
            self.assertIn("conflu users search", caught.exception.hint)

    def test_a_text_that_is_too_long_for_a_name_is_refused(self):
        self.assertEqual(text_of(search_query("a" * MAX_QUERY)), "a" * MAX_QUERY)
        with self.assertRaises(ValidationError) as caught:
            search_query("a" * (MAX_QUERY + 1))
        self.assertIn(str(MAX_QUERY), caught.exception.hint)


class AccountIdsTest(unittest.TestCase):
    def test_ids_are_separated_by_blanks_commas_or_semicolons_and_come_once_in_the_order_given(self):
        self.assertEqual(parse_account_ids(f"{ACCOUNT}, 5b10ac8d82e05b22cc7d4ef6;\n{ACCOUNT}\t5b10ac8d82e05b22cc7d4ef7"), [ACCOUNT, "5b10ac8d82e05b22cc7d4ef6", "5b10ac8d82e05b22cc7d4ef7"])

    def test_the_two_shapes_of_an_account_id(self):
        self.assertEqual(parse_account_ids("557058:00000000-0000-4000-8000-000000000001"), ["557058:00000000-0000-4000-8000-000000000001"])
        self.assertEqual(parse_account_ids("5b10ac8d82e05b22cc7d4ef5"), [ACCOUNT])

    def test_nothing_given_is_a_usage_error(self):
        for text in ("", "  ", ",;,", None):
            with self.subTest(text=text), self.assertRaises(UsageError):
                parse_account_ids(text)

    def test_what_is_not_an_account_id_is_refused_and_named(self):
        for bad in ('a"b', "a b\"c", "x/../y", "-leading", "a" * 129, "id=1", "ä", "a'b", "<script>", "$(x)"):
            with self.subTest(text=bad), self.assertRaises(ValidationError) as caught:
                parse_account_ids(f"{ACCOUNT} {bad}")
            self.assertIn("Not an account id", caught.exception.message)

    def test_at_most_250_different_ids_can_be_asked_at_a_time(self):
        ids = [f"id{number:04d}" for number in range(MAX_ACCOUNT_IDS)]
        self.assertEqual(parse_account_ids(" ".join(ids)), ids)
        self.assertEqual(parse_account_ids(" ".join(ids + ids)), ids)  # the same ids twice are the same 250
        with self.assertRaises(UsageError) as caught:
            parse_account_ids(" ".join(ids + ["one-more"]))
        self.assertIn("251 account ids", caught.exception.message)
        self.assertEqual(MAX_ACCOUNT_IDS, 250)  # what the document says the bulk lookup takes


class MappingTest(unittest.TestCase):
    def test_a_person_as_the_bulk_lookup_describes_one(self):
        item = {"accountId": ACCOUNT, "displayName": "Alex Example", "publicName": "alex", "email": "alex@example.com", "accountType": "atlassian", "accountStatus": "active"}
        self.assertEqual(map_users.person_from(item), Person(ACCOUNT, "Alex Example", "alex@example.com", "atlassian"))

    def test_the_public_name_stands_in_for_a_name_that_is_not_given(self):
        for item in ({"accountId": ACCOUNT, "displayName": None, "publicName": "alex"}, {"accountId": ACCOUNT, "publicName": "alex"}, {"accountId": ACCOUNT, "displayName": "", "publicName": "alex"}):
            with self.subTest(item=item):
                self.assertEqual(map_users.person_from(item), Person(ACCOUNT, "alex", "", ""))

    def test_what_is_not_said_is_empty_and_never_the_text_none(self):
        person = map_users.person_from({"accountId": ACCOUNT, "email": None, "accountType": None, "displayName": None, "publicName": None})
        self.assertEqual(person, Person(ACCOUNT, "", "", ""))

    def test_what_names_nobody_is_no_person(self):
        for item in (None, [], "x", {}, {"displayName": "No id"}, {"accountId": ""}, {"accountId": None}):
            with self.subTest(item=item):
                self.assertIsNone(map_users.person_from(item))

    def test_a_result_of_the_search_is_a_person_in_its_user(self):
        result = {"user": {"accountId": ACCOUNT, "displayName": "Alex Example", "email": "alex@example.com", "accountType": "atlassian", "type": "known"}, "title": "Alex Example", "url": "/people/x"}
        self.assertEqual(map_users.person_from_result(result), Person(ACCOUNT, "Alex Example", "alex@example.com", "atlassian"))

    def test_a_result_that_is_no_user_is_no_person(self):
        for result in ({"content": {"id": "1"}}, {"user": None}, {"user": {"type": "anonymous"}}, "x", None):
            with self.subTest(result=result):
                self.assertIsNone(map_users.person_from_result(result))


class Probe(RestUsers):
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def _call(self, method, path, body=None, **kwargs):
        self.calls.append((method, path, body))
        return self.answers.pop(0)


def query_of(path):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(path).query, keep_blank_values=True)


class SearchRequestTest(unittest.TestCase):
    def test_the_search_is_a_get_with_the_query_the_limit_and_the_start(self):
        probe = Probe([{"results": [], "totalSize": 0, "size": 0}])
        probe.search_people('user.fullname ~ "alex"', limit=25, start=50)
        method, path, body = probe.calls[0]
        self.assertEqual((method, body), ("GET", None))
        self.assertTrue(path.startswith("/rest/api/search/user?"))
        self.assertEqual(query_of(path), {"cql": ['user.fullname ~ "alex"'], "limit": ["25"], "start": ["50"]})

    def test_the_query_survives_the_address_with_every_character_that_the_address_would_change(self):
        for text in ('a" OR user = "b', "a&b=c", "100% sure", "a+b", "a#b", "a b", "日本", "a\\b", "x?y"):
            with self.subTest(text=text):
                cql = search_query(text)
                probe = Probe([{"results": []}])
                probe.search_people(cql)
                self.assertEqual(query_of(probe.calls[0][1])["cql"], [cql])

    def test_the_people_of_an_answer_with_what_the_answer_says_about_the_rest(self):
        answer = {
            "results": [
                {"user": {"accountId": ACCOUNT, "displayName": "Alex Example", "email": "alex@example.com", "accountType": "atlassian"}},
                {"title": "a result that is no person"},
                {"user": {"accountId": "5b10ac8d82e05b22cc7d4ef6", "publicName": "Sam"}},
            ],
            "start": 10,
            "limit": 25,
            "size": 3,
            "totalSize": 41,
        }
        page = Probe([answer]).search_people("cql", limit=25, start=10)
        self.assertEqual([person.account_id for person in page.people], [ACCOUNT, "5b10ac8d82e05b22cc7d4ef6"])
        self.assertEqual((page.total, page.start, page.limit, page.size), (41, 10, 25, 3))  # the size counts the result that is no person: the next page starts after it

    def test_an_answer_that_does_not_give_the_total_says_what_it_shows_to_exist(self):
        for total in (None, "41", True, 4.5):
            with self.subTest(total=total):
                answer = {"results": [{"user": {"accountId": ACCOUNT}}], "size": 1, "totalSize": total}
                self.assertEqual(Probe([answer]).search_people("cql", start=20).total, 21)

    def test_an_answer_that_is_not_an_object_is_an_empty_page(self):
        for answer in ({}, [], None, "x"):
            with self.subTest(answer=answer):
                page = Probe([answer]).search_people("cql")
                self.assertEqual((page.people, page.total, page.size), ([], 0, 0))

    def test_the_only_call_is_the_search_of_v1_and_it_says_why(self):
        self.assertEqual(list(V1_CALLS), ["GET /rest/api/search/user"])
        reason = V1_CALLS["GET /rest/api/search/user"]
        self.assertIn("v2 has no search for people", reason)
        self.assertTrue(reason.endswith("."))


class LookupRequestTest(unittest.TestCase):
    def test_the_ids_go_in_one_post_to_v2_in_the_order_given(self):
        answer = {"results": [{"accountId": "b", "displayName": "B"}, {"accountId": "a", "displayName": "A"}]}
        people = Probe([answer]).lookup_people(["a", "b"])
        probe = Probe([answer])
        probe.lookup_people(["a", "b", "a"])
        self.assertEqual(probe.calls, [("POST", "/api/v2/users-bulk", {"accountIds": ["a", "b"]})])
        self.assertEqual([person.account_id for person in people], ["b", "a"])  # as the answer has them: the use case puts them in the order asked

    def test_more_than_the_call_takes_goes_in_several_requests(self):
        ids = [f"id{number:04d}" for number in range(600)]
        probe = Probe([{"results": [{"accountId": item}]} for item in ("x", "y", "z")])
        found = probe.lookup_people(ids + ids[:10])
        self.assertEqual([len(body["accountIds"]) for _, _, body in probe.calls], [250, 250, 100])
        self.assertEqual([item for _, _, body in probe.calls for item in body["accountIds"]], ids)
        self.assertEqual([person.account_id for person in found], ["x", "y", "z"])

    def test_what_names_nobody_is_left_out(self):
        answer = {"results": [{"displayName": "No id"}, {"accountId": ACCOUNT, "displayName": "Alex Example"}, "x", None]}
        self.assertEqual([person.account_id for person in Probe([answer]).lookup_people([ACCOUNT])], [ACCOUNT])

    def test_nothing_asked_sends_nothing(self):
        probe = Probe([])
        self.assertEqual(probe.lookup_people([]), [])
        self.assertEqual(probe.calls, [])


class PeoplePageTest(unittest.TestCase):
    def test_a_page_is_data(self):
        page = PeoplePage([Person(ACCOUNT)], total=3, start=1, limit=25, size=1)
        self.assertEqual((page.total, page.start, page.limit, page.size), (3, 1, 25, 1))


if __name__ == "__main__":
    unittest.main()
