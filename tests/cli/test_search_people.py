"""`conflu search` on the command line lists no person without `--with-users`: not the hits, not the raw answer, not the name of a personal space."""
import json
import unittest

from tests.support.cli import run_cli
from tests.support.fakes import ACCOUNT, default_settings
from tests.support.people_search import OWNER, PAGE, PERSON, PERSONAL_KEY, PeopleGateway

QUERY = 'type = user AND user.fullname ~ "a*"'


class PeopleInTheAnswerTest(unittest.TestCase):
    def search(self, *argv, gateway=None, **options):
        return run_cli("search", "--cql", QUERY, *argv, gateway=gateway or PeopleGateway(), **options)

    def test_the_json_has_no_person_and_says_how_many_hits_were_left_out(self):
        result = self.search("--json")
        self.assertEqual(result.code, 0, result.err)
        data = result.json()
        self.assertEqual([hit["type"] for hit in data["hits"]], ["page", "space", "space", "page"])
        self.assertEqual((data["total"], data["count"]), (5, 4))
        self.assertEqual(data["notes"], ["1 hit about people was left out: people are listed only with --with-users. Add it to see them."])
        self.assertNotIn(ACCOUNT, result.out)
        self.assertNotIn(OWNER, result.out)
        self.assertIn("1 hit about people was left out", result.err)  # the person at the terminal reads it too

    def test_the_text_has_no_person_and_no_personal_space_key_or_name(self):
        for argv in ((), ("--format", "tsv"), ("--snippets", "2"), ("--select", "id,type,title,spaceKey")):
            with self.subTest(argv=argv):
                result = self.search(*argv)
                self.assertEqual(result.code, 0, result.err)
                self.assertNotIn(ACCOUNT, result.out + result.err)
                self.assertNotIn(OWNER, result.out + result.err)
                self.assertNotIn(PERSONAL_KEY, result.out + result.err)
                self.assertNotIn("user", result.out.split())

    def test_a_personal_space_is_listed_as_what_it_is_without_its_owner(self):
        result = self.search("--json", "--select", "type,title,spaceKey,url")
        spaces = [hit for hit in result.json()["hits"] if hit["type"] == "space"]
        self.assertEqual(
            spaces,
            [{"type": "space", "title": "[personal space]", "spaceKey": "[hidden]", "url": ""}, {"type": "space", "title": "Engineering", "spaceKey": "ENG", "url": spaces[1]["url"]}],
        )
        self.assertIn("/spaces/ENG", spaces[1]["url"])

    def test_the_raw_answer_has_no_person_and_no_personal_space_name(self):
        result = self.search("--raw")
        self.assertEqual(result.code, 0, result.err)
        raw = json.loads(result.out)
        self.assertEqual(raw["total"], 5)
        self.assertEqual([item["entityType"] for item in raw["results"]], ["content", "space", "space", "content"])
        for text in (ACCOUNT, OWNER, PERSONAL_KEY):
            self.assertNotIn(text, result.out)
        self.assertIn("[personal space]", result.out)

    def test_the_text_of_a_search_for_every_kind_of_content_leaves_people_out_too(self):
        result = run_cli("search", "alex", "--type", "any", "--json", gateway=PeopleGateway())
        self.assertEqual(result.code, 0, result.err)
        self.assertNotIn("user", [hit["type"] for hit in result.json()["hits"]])
        self.assertNotIn(OWNER, result.out)

    def test_when_every_hit_was_a_person_nothing_is_listed_and_the_note_says_why(self):
        result = self.search(gateway=PeopleGateway(PERSON, PERSON))
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(result.out, "Nothing found.\n")
        self.assertIn("2 hits about people were left out", result.err)
        self.assertNotIn("Nothing found. The pages may be written", result.err)


class WithUsersTest(unittest.TestCase):
    def test_with_users_the_people_are_listed_as_they_were(self):
        result = run_cli("search", "--cql", QUERY, "--with-users", "--json", gateway=PeopleGateway())
        self.assertEqual(result.code, 0, result.err)
        data = result.json()
        self.assertEqual([hit["type"] for hit in data["hits"]], ["user", "page", "space", "space", "page"])
        self.assertEqual(data["notes"], [])
        self.assertEqual(data["hits"][0]["title"], OWNER)
        self.assertIn(ACCOUNT, data["hits"][0]["url"])
        raw = json.loads(run_cli("search", "--cql", QUERY, "--with-users", "--raw", gateway=PeopleGateway()).out)
        self.assertEqual(raw["results"][0]["user"]["accountId"], ACCOUNT)

    def test_with_users_a_personal_space_is_named(self):
        data = run_cli("search", "--cql", QUERY, "--with-users", "--json", gateway=PeopleGateway()).json()
        personal = next(hit for hit in data["hits"] if hit["type"] == "space" and hit["spaceKey"] != "ENG")
        self.assertEqual((personal["spaceKey"], personal["title"]), (PERSONAL_KEY, OWNER))


class UnderThePolicyTest(unittest.TestCase):
    STRICT = default_settings(hide_users=True)

    def test_with_users_is_refused_as_before(self):
        for extra in ((), ("--raw",), ("--json",)):
            with self.subTest(extra=extra):
                result = run_cli("search", "--cql", QUERY, "--with-users", *extra, gateway=PeopleGateway(), settings=self.STRICT)
                self.assertEqual(result.code, 1)
                self.assertIn("CONFLUENCE_HIDE_USERS", result.err)
                self.assertEqual(result.out, "")

    def test_without_it_no_person_is_listed_and_the_note_names_the_policy(self):
        result = run_cli("search", "--cql", QUERY, "--json", gateway=PeopleGateway(), settings=self.STRICT)
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(result.json()["notes"], ["1 hit about people was left out: CONFLUENCE_HIDE_USERS=true keeps people out of every answer."])
        self.assertNotIn(OWNER, result.out)
        self.assertNotIn(ACCOUNT, result.out)

    def test_the_agent_profile_keeps_them_out_as_well(self):
        result = run_cli("search", "--cql", QUERY, "--json", gateway=PeopleGateway(), environ={"CONFLUENCE_PROFILE": "agent"}, settings=default_settings(hide_users=True))
        self.assertNotIn(ACCOUNT, result.out)
        self.assertEqual(result.json()["count"], 4)


class OrdinarySearchesAreUnchangedTest(unittest.TestCase):
    def test_a_search_for_pages_has_no_note_and_the_same_hits(self):
        gateway = PeopleGateway(PAGE)
        result = run_cli("search", "release", "--json", gateway=gateway)
        self.assertEqual(result.json()["notes"], [])
        self.assertEqual([hit["id"] for hit in result.json()["hits"]], ["2002"])
        self.assertEqual(result.err, "")


if __name__ == "__main__":
    unittest.main()
