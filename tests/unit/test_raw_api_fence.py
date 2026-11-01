"""The fence of `conflu api`: the path of a raw call stays below the API root, however a segment of two dots is written.

A server, or a proxy in front of it, that collapses dot segments would turn `api/v2/pages/.%2e/spaces` into `api/v2/spaces` and `api/v2/.%2e/x` into `x`:
the fence has to see every spelling that such a server reads as `..`."""
import itertools
import unittest

from conflu_c_cli.application.extras import RawApi
from conflu_c_cli.domain.errors import UsageError
from tests.support.cli import run_cli
from tests.support.fakes import FakeGateway, default_settings

# A dot is written `.` or `%2e` (also `%2E`); two of them make a segment that leaves its folder.
DOTS = sorted({"".join(pair) for pair in itertools.product((".", "%2e", "%2E"), repeat=2)})
PLACES = (
    "api/v2/pages/{dots}",
    "api/v2/pages/{dots}/x",
    "api/v2/{dots}/spaces",
    "api/{dots}/{dots}/admin/users",
    "rest/api/{dots}",
    "rest/api/search/{dots}/{dots}/x",
    "/api/v2/pages/{dots}/spaces",
    "api/v2/pages/{dots}?limit=1",
    "api/v2/pages/{dots}#fragment",
    "api/v2/pages/{dots}/x#a/b?c",
    "api/v2/pages/{dots};jsessionid=1/spaces",
    "api/v2/pages/{dots};/spaces",
)


def raw_api():
    gateway = FakeGateway()
    return RawApi(gateway, default_settings()), gateway


class EverySpellingOfTwoDotsIsRefusedTest(unittest.TestCase):
    def test_a_segment_of_two_dots_in_any_spelling_and_at_any_place(self):
        api, gateway = raw_api()
        checked = 0
        for dots in DOTS:
            for place in PLACES:
                path = place.format(dots=dots)
                with self.subTest(path=path):
                    with self.assertRaises(UsageError) as caught:
                        api.execute("GET", path)
                    self.assertEqual(caught.exception.exit_code, 2)
                    self.assertIn("`..`", caught.exception.message)
                    checked += 1
        self.assertEqual(checked, len(DOTS) * len(PLACES))
        self.assertEqual(gateway.called("request"), [])

    def test_the_forms_that_the_review_found(self):
        api, gateway = raw_api()
        for path in ("api/v2/pages/.%2e/spaces", "api/v2/pages/%2e./spaces", "api/v2/.%2e/.%2e/admin", "api/v2/pages/%2E./x", "api/v2/pages/.%2E/x"):
            with self.subTest(path=path), self.assertRaises(UsageError):
                api.execute("GET", path)
        self.assertEqual(gateway.called("request"), [])

    def test_the_old_forms_are_still_refused(self):
        api, gateway = raw_api()
        for path in ("api/../admin", "api/v2/%2e%2e/admin", "api/v2/%2E%2E/admin", "api/v2/a%2e%2eb", "api/v2/pages%2f1", "api/v2/pages%2F1", "api/v2/x%5cy", "api/v2/x%5Cy", "api\\v2\\x"):
            with self.subTest(path=path), self.assertRaises(UsageError):
                api.execute("GET", path)
        self.assertEqual(gateway.called("request"), [])

    def test_writing_and_a_dry_run_are_fenced_alike(self):
        api, gateway = raw_api()
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run), self.assertRaises(UsageError):
                api.execute("PUT", "api/v2/pages/.%2e/title", '{"title": "T"}', write=True, dry_run=dry_run)
        self.assertEqual(gateway.called("request"), [])

    def test_a_fragment_does_not_hide_a_dot_segment_from_the_fence(self):
        """The request leaves out the fragment, so what stands before it is what is sent: `pages/..#x` is `pages/..`."""
        api, gateway = raw_api()
        for path in ("api/v2/pages/..#x", "api/v2/pages/.%2e#x", "api/v2/pages/%2e%2e#a?b=c", "api/v2/pages/..#/x"):
            with self.subTest(path=path), self.assertRaises(UsageError):
                api.execute("GET", path)
        self.assertEqual(gateway.called("request"), [])


class WhatIsNotADotSegmentIsAccepted(unittest.TestCase):
    def test_names_that_hold_dots_and_a_query_that_holds_them(self):
        api, gateway = raw_api()
        for path in (
            "api/v2/pages/...",
            "api/v2/pages/a..b",
            "api/v2/pages/..x",
            "api/v2/pages/x..",
            "api/v2/pages/.hidden",
            "api/v2/pages/%2ex",
            "api/v2/pages/x%2e",
            "api/v2/pages/a.b.c",
            "api/v2/pages?cursor=../x",
            "api/v2/pages?cursor=%2e%2e%2fx",
            "api/v2/pages?a=1#..",
            "rest/api/search?cql=title ~ \"..\"",
        ):
            with self.subTest(path=path):
                self.assertFalse(api.execute("GET", path).dry_run)
        self.assertEqual(len(gateway.called("request")), 12)

    def test_the_message_says_how_the_dots_may_be_written(self):
        api, _ = raw_api()
        with self.assertRaises(UsageError) as caught:
            api.execute("GET", "api/v2/pages/.%2e/x")
        self.assertIn("`%2e%2e` and `.%2e` too", caught.exception.message)


class TheFenceOnTheCommandLineTest(unittest.TestCase):
    def test_a_path_with_a_dot_segment_is_exit_code_2_and_nothing_is_sent(self):
        for path in ("api/v2/pages/.%2e/spaces", "api/v2/pages/%2e./spaces", "api/v2/pages/%2E%2E/spaces", "api/v2/pages/..#x"):
            for extra in ((), ("--dry-run",), ("--json",)):
                with self.subTest(path=path, extra=extra):
                    gateway = FakeGateway()
                    result = run_cli("api", "GET", path, *extra, gateway=gateway)
                    self.assertEqual(result.code, 2, result.err)
                    self.assertIn("The path must not contain `..`", result.err)
                    self.assertEqual((result.out, gateway.called("request")), ("", []))

    def test_the_parameters_are_no_part_of_the_path(self):
        gateway = FakeGateway()
        result = run_cli("api", "GET", "api/v2/pages", "--param", "cursor=../x", "--param", "title=..", gateway=gateway)
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(len(gateway.called("request")), 1)

    def test_a_git_bash_path_that_is_undone_is_still_fenced(self):
        gateway = FakeGateway()
        environ = {"EXEPATH": "C:\\Program Files\\Git"}
        result = run_cli("api", "GET", "C:/Program Files/Git/api/v2/pages/.%2e/spaces", gateway=gateway, environ=environ)
        self.assertEqual(result.code, 2)
        self.assertEqual(gateway.called("request"), [])


if __name__ == "__main__":
    unittest.main()
