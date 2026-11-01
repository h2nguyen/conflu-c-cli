"""A search lists no person unless `--with-users` is given: the search index holds people besides pages (`type = user`), and a personal space is named
after its owner. Without the flag their hits and their raw results are left out, and a hit about a space goes through the personal-space rule."""
import unittest
from dataclasses import replace

from conflu_c_cli.application.search import SearchContent
from conflu_c_cli.domain.errors import ValidationError
from conflu_c_cli.domain.model import SearchHit
from tests.support.fakes import ACCOUNT, FakeGateway, default_settings
from tests.support.people_search import ENGINEERING, OWNER, PAGE, PAGE_OF_THE_OWNER, PERSON, PERSONAL_KEY, PERSONAL_SPACE, PeopleGateway

EVERYTHING = 'type = user AND user.fullname ~ "a*"'


def search(gateway, *, hide_users=False, **options):
    return SearchContent(gateway, default_settings(hide_users=hide_users)).execute(cql=options.pop("cql", EVERYTHING), **options)


def everything_printed(result) -> str:
    """Whatever a command could print of the result: the hits, the raw answer and the notes."""
    return repr(result.hits) + repr(result.raw_results) + repr(result.notes)


class EmptyIndex(PeopleGateway):
    """A search index that finds nothing."""

    def __init__(self) -> None:
        super().__init__()
        self.search_hits = []


class PeopleAreLeftOutTest(unittest.TestCase):
    def test_the_hits_about_people_are_left_out_and_counted_without_a_name(self):
        result = search(PeopleGateway())
        self.assertEqual([hit.type for hit in result.hits], ["page", "space", "space", "page"])
        self.assertNotIn("user", [hit.type for hit in result.hits])
        self.assertEqual(result.total, 5)  # what the search found, people included
        self.assertEqual(result.notes, ["1 hit about people was left out: people are listed only with --with-users. Add it to see them."])
        self.assertNotIn(ACCOUNT, everything_printed(result))

    def test_the_note_counts_and_names_nobody(self):
        many = PeopleGateway(PERSON, replace(PERSON, title="Sam Example"), replace(PERSON, title="Kim Example"), PAGE)
        result = search(many)
        self.assertEqual(result.notes, ["3 hits about people were left out: people are listed only with --with-users. Add it to see them."])
        for name in ("Sam", "Kim", "Alex"):
            self.assertNotIn(name, everything_printed(result))

    def test_only_people_found_means_no_hit_and_no_nothing_found_note(self):
        result = search(PeopleGateway(PERSON, replace(PERSON, title="Sam Example")))
        self.assertEqual((result.hits, result.raw_results, result.total), ([], [], 2))
        self.assertEqual(len(result.notes), 1)
        self.assertIn("2 hits about people were left out", result.notes[0])
        self.assertNotIn("Nothing found", result.notes[0])

    def test_nothing_found_at_all_is_still_nothing_found(self):
        result = search(EmptyIndex())
        self.assertEqual(result.total, 0)
        self.assertEqual(len(result.notes), 1)
        self.assertTrue(result.notes[0].startswith("Nothing found."))

    def test_the_raw_answer_has_no_person_either(self):
        result = search(PeopleGateway())
        self.assertEqual([item["entityType"] for item in result.raw_results], ["content", "space", "space", "content"])
        text = repr(result.raw_results)
        self.assertNotIn(ACCOUNT, text)
        self.assertNotIn(OWNER, text)

    def test_a_complete_read_leaves_the_people_of_every_page_out(self):
        gateway = FakeGateway()  # two hits to an answer
        gateway.search_hits = [PERSON, PAGE, replace(PERSON, title="Sam Example"), PAGE_OF_THE_OWNER, replace(PERSON, title="Kim Example")]
        result = search(gateway, fetch_everything=True)
        self.assertEqual(len(gateway.called("search")), 3)
        self.assertEqual([hit.id for hit in result.hits], ["2002", "9001"])
        self.assertIn("3 hits about people were left out", result.notes[0])

    def test_a_text_search_that_asks_for_every_kind_of_content_leaves_them_out_too(self):
        gateway = PeopleGateway()
        result = SearchContent(gateway, default_settings()).execute(text="alex", content_type="any")
        self.assertNotIn("user", [hit.type for hit in result.hits])
        self.assertTrue(any("left out" in note for note in result.notes))

    def test_the_passages_are_read_for_the_pages_that_are_shown(self):
        gateway = PeopleGateway(PERSON, PERSON, PAGE)  # people first: they must not use up the passages that were asked for
        search(gateway, snippets=1)
        self.assertEqual(gateway.called("list_pages")[0][2], ("2002",))


class PersonalSpacesTest(unittest.TestCase):
    def test_a_hit_about_a_personal_space_has_no_key_no_name_and_no_address(self):
        hit = next(hit for hit in search(PeopleGateway()).hits if hit.type == "space" and hit.space_key != "ENG")
        self.assertEqual((hit.space_key, hit.title, hit.url), ("[hidden]", "[personal space]", ""))
        self.assertEqual((hit.excerpt, hit.path), ("", ""))

    def test_a_hit_about_another_space_is_as_it_was(self):
        hit = next(hit for hit in search(PeopleGateway()).hits if hit.space_key == "ENG" and hit.type == "space")
        self.assertEqual((hit.title, hit.url), ("Engineering", ENGINEERING.url))

    def test_the_name_of_a_space_is_redacted_like_any_text(self):
        hit = search(PeopleGateway(replace(ENGINEERING, title="Docs of alex@example.com"))).hits[0]
        self.assertEqual(hit.title, "Docs of [email]")

    def test_a_page_of_the_owner_has_no_personal_space_key_and_no_address_with_it(self):
        hit = next(hit for hit in search(PeopleGateway()).hits if hit.id == "9001")
        self.assertEqual(hit.space_key, "[hidden]")
        self.assertNotIn(PERSONAL_KEY, hit.url)
        self.assertNotIn(ACCOUNT, repr(hit))

    def test_the_raw_result_of_a_personal_space_has_no_name_key_or_address(self):
        items = {item["entityType"] + str(item.get("space", {}).get("key", "")): item for item in search(PeopleGateway()).raw_results}
        personal = next(item for key, item in items.items() if key.startswith("space[hidden]"))
        self.assertEqual((personal["title"], personal["url"]), ("[personal space]", ""))
        self.assertEqual(personal["resultGlobalContainer"], {"title": "[personal space]", "displayUrl": ""})
        self.assertEqual((personal["space"]["key"], personal["space"]["name"]), ("[hidden]", "[personal space]"))
        engineering = items["spaceENG"]
        self.assertEqual((engineering["title"], engineering["resultGlobalContainer"]["title"]), ("Engineering", "Engineering"))

    def test_the_raw_result_of_a_page_in_a_personal_space_does_not_name_the_space(self):
        item = next(item for item in search(PeopleGateway()).raw_results if item.get("content", {}).get("id") == "9001")
        self.assertEqual(item["resultGlobalContainer"], {"title": "[personal space]", "displayUrl": ""})
        self.assertNotIn(OWNER, repr(item))
        self.assertNotIn(ACCOUNT, repr(item))
        ordinary = next(item for item in search(PeopleGateway()).raw_results if item.get("content", {}).get("id") == "2002")
        self.assertEqual(ordinary["resultGlobalContainer"], {"title": "Engineering", "displayUrl": "/spaces/ENG"})

    def test_the_excerpt_of_every_raw_result_is_left_out(self):
        self.assertEqual({item["excerpt"] for item in search(PeopleGateway()).raw_results}, {None})


class WithUsersChangesNothingTest(unittest.TestCase):
    def test_with_users_the_hits_are_all_there_as_they_were(self):
        gateway = PeopleGateway()
        result = search(gateway, with_users=True)
        self.assertEqual(result.hits, gateway.search_hits)
        self.assertEqual(result.notes, [])
        self.assertEqual(len(result.raw_results), 5)
        person = next(item for item in result.raw_results if item["entityType"] == "user")
        self.assertEqual(person["user"]["accountId"], ACCOUNT)
        self.assertTrue(result.excerpts_shown)

    def test_with_users_a_personal_space_is_named(self):
        hit = next(hit for hit in search(PeopleGateway(), with_users=True).hits if hit.type == "space" and hit.space_key != "ENG")
        self.assertEqual((hit.space_key, hit.title), (PERSONAL_KEY, OWNER))
        self.assertEqual(hit.url, PERSONAL_SPACE.url)


class ThePolicyTest(unittest.TestCase):
    def test_with_users_is_refused_under_the_policy_as_before(self):
        gateway = PeopleGateway()
        with self.assertRaises(ValidationError) as caught:
            search(gateway, hide_users=True, with_users=True)
        self.assertIn("CONFLUENCE_HIDE_USERS", caught.exception.message)
        self.assertEqual(gateway.called("search"), [])

    def test_without_it_the_policy_leaves_the_people_out_and_says_so_without_advising_what_it_forbids(self):
        result = search(PeopleGateway(), hide_users=True)
        self.assertNotIn("user", [hit.type for hit in result.hits])
        self.assertEqual(result.notes, ["1 hit about people was left out: CONFLUENCE_HIDE_USERS=true keeps people out of every answer."])
        self.assertNotIn("Add it", result.notes[0])


class WhatIsNotAPersonTest(unittest.TestCase):
    def test_a_page_whose_title_says_user_and_a_hit_of_another_type_stay(self):
        titled = SearchHit("1", "page", "user", "ENG", "", "", "")
        for kind in ("page", "blogpost", "attachment", "comment", "space"):
            with self.subTest(kind=kind):
                self.assertEqual(len(search(PeopleGateway(replace(titled, type=kind))).hits), 1)

    def test_a_raw_result_whose_content_is_a_user_is_a_person_too(self):
        class Gateway(PeopleGateway):
            def search(self, cql, *, limit=25, start=0):
                page = super().search(cql, limit=limit, start=start)
                page.raw_results = [{"content": {"type": "user", "title": OWNER}, "title": OWNER, "entityType": "content"}, *page.raw_results[1:]]
                return page

        result = search(Gateway())
        self.assertNotIn(OWNER, repr([item for item in result.raw_results if item["entityType"] == "content" and "user" in repr(item)]))
        self.assertEqual(len(result.raw_results), 4)


if __name__ == "__main__":
    unittest.main()
