"""`conflu doctor --quick` and `--cached` through the real adapters: the requests that the mock sees, and the cache folder on disk."""
import json
import re
import unittest

from tests.integration.test_end_to_end import EndToEnd


class DoctorCacheTest(EndToEnd):
    def setUp(self):
        super().setUp()
        self.env["XDG_CACHE_HOME"] = ""  # an empty variable is no variable: the cache is below HOME, which is this test's folder, whatever the machine sets

    def cache_files(self):
        folder = self.root / ".cache" / "conflu-c-cli"
        return sorted(folder.iterdir()) if folder.is_dir() else []

    def requests_since(self, start):
        return [item.target for item in self.mock.requests[start:]]

    def test_quick_asks_the_current_user_and_the_spaces_and_nothing_else(self):
        result = self.cli("doctor", "--quick", "--json", env={"CONFLUENCE_SPACE": "ENG"})
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.requests_since(0), ["GET /rest/api/user/current", "GET /api/v2/spaces"])  # v1, then v2
        names = [check["name"] for check in result.json()["checks"]]
        self.assertEqual(names[-4:], ["connection", "spaces", "api", "privacy"])
        self.assertNotIn("space", names)

    def test_the_full_run_asks_for_the_current_space_too(self):
        result = self.cli("doctor", "--json", env={"CONFLUENCE_SPACE": "ENG"})
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(len(self.mock.requests), 3)
        self.assertIn("space", [check["name"] for check in result.json()["checks"]])

    def test_a_second_cached_run_sends_no_request_and_says_when_the_first_one_was(self):
        first = self.cli("doctor", "--cached", "10m", "--json")
        self.assertEqual((first.code, first.json()["cached"], first.json()["cachedAt"]), (0, False, None))
        asked = len(self.mock.requests)
        self.assertGreater(asked, 0)
        second = self.cli("doctor", "--cached", "10m", "--json")
        self.assertEqual(len(self.mock.requests), asked)  # not one request
        report = second.json()
        self.assertTrue(report["cached"])
        self.assertRegex(report["cachedAt"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")
        self.assertEqual({check["name"] for check in report["checks"]} >= {"connection", "spaces", "api", "space", "privacy"}, True)
        text = self.cli("doctor", "--cached", "10m")
        self.assertRegex(text.out, r"\(the online checks are from a run at \d{4}-\d\d-\d\dT[\d:+]+: nothing was asked of Confluence\)")
        self.assertEqual(len(self.mock.requests), asked)

    def test_the_cache_holds_the_checks_and_not_the_token(self):
        self.cli("doctor", "--json")
        (path,) = self.cache_files()
        self.assertRegex(path.name, r"^doctor-[0-9a-f]{16}\.json$")
        text = path.read_text(encoding="utf-8")
        for secret in (self.mock.token, self.mock.email, "Alex Example", "5b10ac8d82e05b22cc7d4ef5"):
            self.assertNotIn(secret, text + path.name)
        record = json.loads(text)
        self.assertEqual(set(record), {"at", "checks"})
        self.assertEqual([check["name"] for check in record["checks"]], ["connection", "spaces", "api", "space"])

    def test_a_run_with_a_failure_is_not_remembered(self):
        result = self.cli("doctor", "--cached", "10m", env={"CONFLUENCE_API_TOKEN": "not-the-token"})
        self.assertEqual(result.code, 1)
        self.assertEqual(self.cache_files(), [])
        asked = len(self.mock.requests)
        self.cli("doctor", "--cached", "10m", env={"CONFLUENCE_API_TOKEN": "not-the-token"})
        self.assertGreater(len(self.mock.requests), asked)

    def test_another_token_is_not_given_the_answer_of_this_one(self):
        self.cli("doctor", "--cached", "10m")
        asked = len(self.mock.requests)
        other = self.cli("doctor", "--cached", "10m", "--json", env={"CONFLUENCE_API_TOKEN": "not-the-token"})
        self.assertFalse(other.json()["cached"])
        self.assertEqual(other.code, 1)
        self.assertGreater(len(self.mock.requests), asked)

    def test_the_cache_lives_where_xdg_cache_home_says(self):
        folder = self.root / "xdg-cache" / "conflu-c-cli"
        self.cli("doctor", "--json", env={"XDG_CACHE_HOME": str(self.root / "xdg-cache")})
        self.assertEqual(len(list(folder.glob("doctor-*.json"))), 1)
        self.assertEqual(self.cache_files(), [])  # and not in the home folder

    def test_a_cache_that_cannot_be_written_does_not_get_in_the_way(self):
        blocker = self.root / "a-file"
        blocker.write_text("not a folder")
        result = self.cli("doctor", "--cached", "10m", "--json", env={"XDG_CACHE_HOME": str(blocker)})
        self.assertEqual(result.code, 0, result.err)
        again = self.cli("doctor", "--cached", "10m", "--json", env={"XDG_CACHE_HOME": str(blocker)})
        self.assertEqual((again.code, again.json()["cached"]), (0, False))  # there is nothing to reuse, and no error either

    def test_a_damaged_cache_file_is_ignored(self):
        self.cli("doctor", "--json")
        (path,) = self.cache_files()
        path.write_bytes(b"\xff\xfe damaged")
        asked = len(self.mock.requests)
        result = self.cli("doctor", "--cached", "10m", "--json")
        self.assertEqual((result.code, result.json()["cached"]), (0, False))
        self.assertGreater(len(self.mock.requests), asked)
        self.assertTrue(json.loads(path.read_text(encoding="utf-8")))  # and the next run replaced it

    def test_the_cached_form_is_the_same_command_as_a_child_process_runs(self):
        first = self.child("doctor", "--quick", "--cached", "10m", "--json")
        self.assertEqual(first.code, 0, first.err)
        asked = len(self.mock.requests)
        second = self.child("doctor", "--quick", "--cached", "10m", "--json")
        self.assertTrue(second.json()["cached"])
        self.assertEqual(len(self.mock.requests), asked)
        self.assertRegex(second.json()["cachedAt"], re.compile(r"^\d{4}-"))


if __name__ == "__main__":
    unittest.main()
