"""The use cases around looking up people, against the fake Confluence: refused unless people are asked for, the search, its paging, the lookup."""
import unittest
from unittest import mock

from conflu_c_cli.domain.errors import UsageError, ValidationError
from conflu_c_cli.domain.model import User
from conflu_c_cli.domain.users import PeoplePage, Person
from tests.support.fakes import ACCOUNT, ALEX, FakeGateway, RecordingDiagnostics, build_app, default_settings


def sams(count):
    return [User(f"5b10ac8d82e05b22cc7d4f{number:02d}", f"Sam Example {number}", f"sam{number}@example.com") for number in range(1, count + 1)]


def fresh(extra=(), **settings):
    """The people of the fake are those that this test names, and Alex, who owns the token: other areas put people of their own into the fixtures."""
    gateway = FakeGateway()
    gateway.users = {ACCOUNT: ALEX, **{user.account_id: user for user in extra}}
    return build_app(gateway=gateway, settings=default_settings(**settings), diagnostics=RecordingDiagnostics()), gateway


class PrivacyTest(unittest.TestCase):
    """The one place where people are the point asks for the same permission as every other command: the person asks, and the policy allows."""

    def test_nothing_is_asked_of_confluence_unless_people_are_asked_for(self):
        app, gateway = fresh()
        with self.assertRaises(UsageError) as caught:
            app.users.search.execute("alex")
        self.assertIn("`conflu users search` lists people", caught.exception.message)
        self.assertIn("--with-users", caught.exception.hint)
        with self.assertRaises(UsageError) as caught:
            app.users.lookup.execute(ACCOUNT)
        self.assertIn("`conflu users lookup` lists people", caught.exception.message)
        self.assertEqual(gateway.calls, [])

    def test_the_policy_refuses_both_whatever_is_asked_and_nothing_is_sent(self):
        app, gateway = fresh(hide_users=True)
        for execute in (lambda **kw: app.users.search.execute("alex", **kw), lambda **kw: app.users.lookup.execute(ACCOUNT, **kw)):
            for options in ({"with_users": True}, {"with_users": False}, {}):
                with self.subTest(options=options), self.assertRaises(ValidationError) as caught:
                    execute(**options)
                self.assertIn("CONFLUENCE_HIDE_USERS=true", caught.exception.message)
                self.assertIn("Unset CONFLUENCE_HIDE_USERS", caught.exception.hint)
        self.assertEqual(gateway.calls, [])

    def test_the_refusal_comes_before_the_text_is_looked_at(self):
        app, gateway = fresh()
        with self.assertRaises(UsageError) as caught:
            app.users.search.execute("", limit=0)  # no text and a bad limit: the first thing to say is that people are shown on request only
        self.assertIn("lists people", caught.exception.message)
        with self.assertRaises(UsageError) as caught:
            app.users.lookup.execute("not an id at all!")
        self.assertIn("lists people", caught.exception.message)
        self.assertEqual(gateway.calls, [])


class SearchTest(unittest.TestCase):
    def test_the_people_whose_name_holds_the_text(self):
        app, gateway = fresh(sams(3))
        result = app.users.search.execute("sam", with_users=True, limit=25)
        self.assertEqual([person.display_name for person in result.people], ["Sam Example 1", "Sam Example 2"])  # the fake hands out two at a time
        self.assertEqual((result.query, result.total, result.start), ("sam", 3, 0))
        self.assertEqual(result.people[0], Person("5b10ac8d82e05b22cc7d4f01", "Sam Example 1", "sam1@example.com", "atlassian"))
        self.assertEqual(gateway.called("search_people"), [("search_people", 'user.fullname ~ "sam"', 25, 0)])
        self.assertEqual(result.cql, 'user.fullname ~ "sam"')

    def test_the_text_is_normalized_and_the_case_does_not_matter(self):
        app, _ = fresh()
        result = app.users.search.execute("  ALEX \t Example  ", with_users=True)
        self.assertEqual((result.query, [person.account_id for person in result.people]), ("ALEX Example", [ACCOUNT]))

    def test_nobody_found_is_an_empty_answer_and_not_an_error(self):
        app, _ = fresh()
        result = app.users.search.execute("nobody of this name", with_users=True)
        self.assertEqual((result.people, result.total, result.next_start, result.truncated), ([], 0, None, False))

    def test_the_next_request_goes_on_where_this_one_stopped(self):
        app, gateway = fresh(sams(4))  # Alex and four Sams: five people whose name holds "example"
        everyone = lambda **options: app.users.search.execute("example", with_users=True, **options)  # noqa: E731
        first = everyone(limit=25)
        self.assertEqual(([person.display_name for person in first.people], first.total, first.next_start), (["Alex Example", "Sam Example 1"], 5, 2))
        second = everyone(limit=25, start=first.next_start)
        self.assertEqual(([person.display_name for person in second.people], second.next_start), (["Sam Example 2", "Sam Example 3"], 4))
        last = everyone(limit=25, start=second.next_start)
        self.assertEqual(([person.display_name for person in last.people], last.next_start, last.start), (["Sam Example 4"], None, 4))
        self.assertEqual([call[3] for call in gateway.called("search_people")], [0, 2, 4])

    def test_every_person_when_all_are_asked_for(self):
        app, gateway = fresh(sams(4))
        result = app.users.search.execute("example", with_users=True, fetch_everything=True)
        self.assertEqual((len(result.people), result.total, result.start, result.truncated, result.next_start), (5, 5, 0, False, None))
        self.assertEqual([call[3] for call in gateway.called("search_people")], [0, 2, 4])  # a request after the other, from the start
        self.assertEqual({call[2] for call in gateway.called("search_people")}, {50})  # in pieces of its own size, whatever limit and start say

    def test_a_search_that_finds_more_than_anybody_can_use_is_cut_and_says_so(self):
        app, _ = fresh(sams(6))
        with mock.patch("conflu_c_cli.application.users.MAX_PEOPLE", 3):
            result = app.users.search.execute("example", with_users=True, fetch_everything=True)
        self.assertTrue(result.truncated)
        self.assertEqual((len(result.people), result.total), (4, 7))

    def test_the_next_page_starts_after_everything_the_answer_held_also_what_names_nobody(self):
        class Mixed(FakeGateway):
            """Six results, of which every second names nobody: they are in the answer, so the next page starts after them."""

            def search_people(self, cql, *, limit=25, start=0):
                self._enter("search_people", cql, limit, start)
                raw = [Person("a1", "A1"), None, Person("a3", "A3"), None, Person("a5", "A5"), None]
                shown = raw[start : start + 2]
                return PeoplePage([item for item in shown if item], len(raw), start, limit, len(shown))

        gateway = Mixed()
        result = build_app(gateway=gateway).users.search.execute("a", with_users=True, fetch_everything=True)
        self.assertEqual([person.account_id for person in result.people], ["a1", "a3", "a5"])
        self.assertEqual([call[3] for call in gateway.called("search_people")], [0, 2, 4])
        page = build_app(gateway=gateway).users.search.execute("a", with_users=True, limit=2, start=0)
        self.assertEqual((len(page.people), page.next_start), (1, 2))

    def test_an_answer_that_ends_early_ends_the_search_and_a_person_twice_is_one_person(self):
        class Confused(FakeGateway):
            def search_people(self, cql, *, limit=25, start=0):
                self._enter("search_people", cql, limit, start)
                if start == 0:
                    return PeoplePage([Person("a1", "A1"), Person("a1", "A1 again")], total=10, start=0, limit=limit, size=2)
                return PeoplePage([], total=10, start=start, limit=limit, size=0)  # it says there are more, and gives none

        gateway = Confused()
        result = build_app(gateway=gateway).users.search.execute("a", with_users=True, fetch_everything=True)
        self.assertEqual([(person.account_id, person.display_name) for person in result.people], [("a1", "A1 again")])
        self.assertEqual(len(gateway.called("search_people")), 2)
        self.assertIsNone(result.next_start)

    def test_a_text_that_is_a_quote_or_a_backslash_stays_a_text(self):
        odd = User("5b10ac8d82e05b22cc7d4f77", 'Quinn "Q" Back\\slash', "")
        app, gateway = fresh([odd])
        found = app.users.search.execute('"Q" Back\\slash', with_users=True)
        self.assertEqual([person.account_id for person in found.people], [odd.account_id])
        self.assertEqual(found.cql, r'user.fullname ~ "\"Q\" Back\\slash"')
        self.assertEqual(gateway.called("search_people")[0][1], r'user.fullname ~ "\"Q\" Back\\slash"')

    def test_a_text_that_tries_to_leave_the_string_finds_nobody_and_is_no_other_query(self):
        app, gateway = fresh()
        for hostile in ('a" OR user = "b', 'x" OR user.accountid = "5b10ac8d82e05b22cc7d4ef5', '\\" OR "1"="1', '" OR "'):
            with self.subTest(text=hostile):
                result = app.users.search.execute(hostile, with_users=True)  # the fake refuses a query that is more than one comparison, as Confluence does
                self.assertEqual(result.people, [])
                self.assertEqual(result.total, 0)

    def test_the_bounds_of_the_options(self):
        app, gateway = fresh()
        for options in ({"limit": 0}, {"limit": 251}, {"limit": -1}, {"start": -1}):
            with self.subTest(options=options), self.assertRaises(UsageError):
                app.users.search.execute("alex", with_users=True, **options)
        self.assertEqual(app.users.search.execute("alex", with_users=True, limit=250).total, 1)
        self.assertEqual(app.users.search.execute("alex", with_users=True, limit=1).total, 1)
        self.assertEqual(len(gateway.called("search_people")), 2)

    def test_nothing_to_search_for_is_a_usage_error_before_anything_is_asked(self):
        app, gateway = fresh()
        for text in ("", "   "):
            with self.subTest(text=text), self.assertRaises(UsageError):
                app.users.search.execute(text, with_users=True)
        self.assertEqual(gateway.calls, [])


class LookupTest(unittest.TestCase):
    def test_the_people_come_in_the_order_the_ids_were_given(self):
        app, gateway = fresh(sams(2))
        ids = ["5b10ac8d82e05b22cc7d4f02", ACCOUNT, "5b10ac8d82e05b22cc7d4f01"]
        result = app.users.lookup.execute(" ".join(ids), with_users=True)
        self.assertEqual([person.account_id for person in result.people], ids)
        self.assertEqual((result.requested, result.not_found), (3, []))
        self.assertEqual(gateway.called("lookup_people"), [("lookup_people", tuple(ids))])

    def test_an_id_that_is_not_described_is_not_an_error_and_is_listed(self):
        app, _ = fresh()
        result = app.users.lookup.execute(f"unknown-1, {ACCOUNT} unknown-2", with_users=True)
        self.assertEqual(([person.account_id for person in result.people], result.not_found, result.requested), ([ACCOUNT], ["unknown-1", "unknown-2"], 3))

    def test_nobody_described_is_an_empty_answer(self):
        app, _ = fresh()
        result = app.users.lookup.execute("unknown-1", with_users=True)
        self.assertEqual((result.people, result.not_found, result.requested), ([], ["unknown-1"], 1))

    def test_an_id_given_twice_is_asked_once(self):
        app, gateway = fresh()
        result = app.users.lookup.execute(f"{ACCOUNT} {ACCOUNT},{ACCOUNT}", with_users=True)
        self.assertEqual((len(result.people), result.requested), (1, 1))
        self.assertEqual(gateway.called("lookup_people"), [("lookup_people", (ACCOUNT,))])

    def test_what_is_no_account_id_is_refused_before_anything_is_asked(self):
        app, gateway = fresh()
        for text in ('a" OR "b', "x/../y", "not an id!", ""):
            with self.subTest(text=text), self.assertRaises((ValidationError, UsageError)):
                app.users.lookup.execute(text, with_users=True)
        self.assertEqual(gateway.calls, [])

    def test_more_than_250_ids_are_a_usage_error_before_anything_is_asked(self):
        app, gateway = fresh()
        with self.assertRaises(UsageError) as caught:
            app.users.lookup.execute(" ".join(f"id{number}" for number in range(251)), with_users=True)
        self.assertIn("at most 250", caught.exception.message)
        self.assertEqual(gateway.calls, [])
        self.assertEqual(app.users.lookup.execute(" ".join(f"id{number}" for number in range(250)), with_users=True).requested, 250)


if __name__ == "__main__":
    unittest.main()
