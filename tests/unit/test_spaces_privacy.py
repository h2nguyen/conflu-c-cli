"""A personal space is named after its owner: how a space is masked when people are not shown (`privacy.hide_space`), and what `ListSpaces` and `ShowSpace` make of it."""
import dataclasses
import unittest

from conflu_c_cli.domain.errors import NotFoundError, ValidationError
from conflu_c_cli.domain.model import Space
from conflu_c_cli.domain.privacy import HIDDEN, PERSONAL_SPACE, hide_space, is_personal_space
from tests.support.fakes import ACCOUNT, BASE, FakeGateway, build_app, default_settings

KEY = f"~{ACCOUNT}"
OWNER = ("alex example", ACCOUNT.lower(), "alex@example.com", f"/spaces/{KEY}")  # what nothing that is printed may hold


def personal(**changes) -> Space:
    space = Space("1003", KEY, "Alex Example", "personal", "current", "Notes of alex@example.com", "3501", "2026-09-02T08:00:00.000Z", f"{BASE}/spaces/{KEY}/overview")
    return dataclasses.replace(space, **changes)


def app_with(*spaces: Space, **settings):
    gateway = FakeGateway()
    for space in spaces:
        gateway.spaces[space.key] = space
    return build_app(gateway=gateway, settings=default_settings(**settings)), gateway


class IsPersonalTest(unittest.TestCase):
    def test_by_the_type_or_by_the_key(self):
        self.assertTrue(is_personal_space("ENG", "personal"))
        self.assertTrue(is_personal_space(KEY, "global"))
        self.assertTrue(is_personal_space(KEY))
        self.assertTrue(is_personal_space("~alexe", ""))

    def test_a_space_of_a_team_is_none(self):
        for key, space_type in (("ENG", "global"), ("ENG", ""), ("DOCS", "knowledge_base"), ("E~G", "collaboration"), ("", ""), (None, None)):
            with self.subTest(key=key, type=space_type):
                self.assertFalse(is_personal_space(key, space_type))

    def test_the_markers_are_what_the_documents_say(self):
        self.assertEqual((HIDDEN, PERSONAL_SPACE), ("[hidden]", "[personal space]"))


class HideSpaceTest(unittest.TestCase):
    def test_a_personal_space_has_no_key_no_name_no_description_and_no_address(self):
        shown = hide_space(personal())
        self.assertEqual((shown.key, shown.name, shown.description, shown.url), ("[hidden]", "[personal space]", "", ""))

    def test_what_names_nobody_stays(self):
        shown = hide_space(personal())
        self.assertEqual((shown.id, shown.type, shown.status, shown.homepage_id, shown.created), ("1003", "personal", "current", "3501", "2026-09-02T08:00:00.000Z"))
        self.assertEqual(shown, dataclasses.replace(personal(), key=HIDDEN, name=PERSONAL_SPACE, description="", url=""))

    def test_nothing_of_the_owner_is_left(self):
        text = repr(hide_space(personal())).lower()
        for part in OWNER:
            self.assertNotIn(part, text)

    def test_a_space_is_personal_by_its_type_alone_or_by_its_key_alone(self):
        self.assertEqual(hide_space(personal(key="ENG")).key, HIDDEN)
        self.assertEqual(hide_space(personal(type="")).name, PERSONAL_SPACE)
        self.assertEqual(hide_space(personal(type="global")).name, PERSONAL_SPACE)

    def test_the_space_that_was_given_is_not_changed(self):
        space = personal()
        hide_space(space)
        self.assertEqual(space, personal())

    def test_any_other_space_keeps_its_key_and_loses_the_addresses_in_its_name_and_description(self):
        team = Space("1001", "ENG", "Team of alex@example.com", "global", "current", f"Mail alex@example.com or see {BASE}/people/{ACCOUNT}", "2001", "2026-09-01T08:00:00.000Z", f"{BASE}/spaces/ENG")
        shown = hide_space(team)
        self.assertEqual((shown.key, shown.name, shown.description), ("ENG", "Team of [email]", "Mail [email] or see [personal link]"))
        self.assertEqual((shown.id, shown.type, shown.status, shown.homepage_id, shown.created, shown.url), ("1001", "global", "current", "2001", "2026-09-01T08:00:00.000Z", f"{BASE}/spaces/ENG"))

    def test_a_space_with_nothing_to_redact_comes_out_as_it_went_in(self):
        plain = Space("1002", "DOCS", "Documentation", "global", "current", "", "3001", "2026-09-01T08:00:00.000Z", f"{BASE}/spaces/DOCS")
        self.assertEqual(hide_space(plain), plain)

    def test_the_name_of_a_space_has_its_addresses_and_personal_links_redacted_and_an_empty_name_stays_empty(self):
        """What the watches carried a copy of (`domain/watches.py: space_title`) until the three commands were made to use this one rule."""
        for name, expected in (("Engineering", "Engineering"), ("Team of alex@example.com", "Team of [email]"), (f"Notes {BASE}/people/{ACCOUNT}", "Notes [personal link]"), ("", "")):
            with self.subTest(name=name):
                self.assertEqual(hide_space(Space("1001", "ENG", name, "global", "current")).name, expected)

    def test_a_personal_space_is_one_by_the_type_or_by_a_key_that_starts_with_a_tilde_whatever_the_key_looks_like(self):
        for key, space_type in (("~alexe", "personal"), ("~alexe", ""), (KEY, "personal"), (KEY, ""), ("ENG", "personal")):
            with self.subTest(key=key, type=space_type):
                shown = hide_space(Space("1003", key, "Alex Example", space_type, "current"))
                self.assertEqual((shown.key, shown.name), (HIDDEN, PERSONAL_SPACE))

    def test_hiding_twice_is_hiding_once(self):
        for space in (personal(), personal(type=""), Space("1001", "ENG", "Team of alex@example.com", "global", "current")):
            with self.subTest(key=space.key):
                self.assertEqual(hide_space(hide_space(space)), hide_space(space))


class ListSpacesTest(unittest.TestCase):
    def test_a_personal_space_comes_out_masked_and_the_others_as_before(self):
        app, _ = app_with(personal())
        listed = app.list_spaces.execute(fetch_everything=True)
        self.assertEqual([(space.key, space.name, space.type) for space in listed.spaces], [("DOCS", "Documentation", "global"), ("ENG", "Engineering", "global"), ("[hidden]", "[personal space]", "personal")])
        self.assertEqual(listed.spaces[2], hide_space(personal()))
        self.assertEqual(listed.spaces[1].description, "Engineering documentation")

    def test_with_people_a_space_is_shown_as_confluence_answers(self):
        app, gateway = app_with(personal())
        gateway.spaces["ENG"] = dataclasses.replace(gateway.spaces["ENG"], name="Team of alex@example.com")
        shown = app.list_spaces.execute(fetch_everything=True, with_users=True).spaces
        self.assertEqual(shown[2], personal())
        self.assertEqual(shown[1].name, "Team of alex@example.com")  # the names stay as they are where people are shown
        hidden = app.list_spaces.execute(fetch_everything=True).spaces
        self.assertEqual(hidden[1].name, "Team of [email]")

    def test_a_search_cannot_find_what_is_not_shown(self):
        app, _ = app_with(personal())
        for text in ("alex", "ALEX", "example", "5b10", ACCOUNT, "~", "~5b10", "notes"):
            with self.subTest(search=text):
                self.assertEqual(app.list_spaces.execute(search=text).spaces, [])
        with_users = app.list_spaces.execute(search="alex", with_users=True).spaces
        self.assertEqual([space.key for space in with_users], [KEY])
        self.assertEqual([space.key for space in app.list_spaces.execute(search="~5b10", with_users=True).spaces], [KEY])

    def test_a_search_finds_what_is_shown_the_name_of_a_team_and_the_mask_itself(self):
        app, gateway = app_with(personal())
        self.assertEqual([space.key for space in app.list_spaces.execute(search="engin").spaces], ["ENG"])
        self.assertEqual([space.key for space in app.list_spaces.execute(search="docs").spaces], ["DOCS"])
        self.assertEqual([space.key for space in app.list_spaces.execute(search="personal space").spaces], ["[hidden]"])  # it looks at what is printed
        gateway.spaces["ENG"] = dataclasses.replace(gateway.spaces["ENG"], name="Team of alex@example.com")
        self.assertEqual([space.key for space in app.list_spaces.execute(search="alex").spaces], [])  # the address is redacted: it cannot be found either
        self.assertEqual([space.key for space in app.list_spaces.execute(search="team").spaces], ["ENG"])
        self.assertEqual([space.key for space in app.list_spaces.execute(search="alex", with_users=True).spaces], ["ENG", KEY])

    def test_the_filters_of_confluence_still_apply_and_a_personal_space_is_masked_in_them_too(self):
        app, gateway = app_with(personal(), personal(id="1004", key="~archived", name="Sam Example", status="archived"))
        self.assertEqual([(space.key, space.name) for space in app.list_spaces.execute(space_type="personal", fetch_everything=True).spaces], [("[hidden]", "[personal space]")])
        self.assertEqual([(space.key, space.status) for space in app.list_spaces.execute(status="archived", fetch_everything=True).spaces], [("[hidden]", "archived")])
        self.assertEqual(app.list_spaces.execute(space_type="global", fetch_everything=True).spaces[0].key, "DOCS")
        self.assertIn(("list_spaces", "personal", "current", 100, ""), gateway.calls)

    def test_the_masking_changes_neither_the_count_nor_the_cursor_nor_the_cut(self):
        app, _ = app_with(personal())
        first = app.list_spaces.execute(limit=1)
        self.assertEqual(([space.key for space in first.spaces], first.next_cursor, first.truncated), (["DOCS"], "1", False))
        last = app.list_spaces.execute(limit=1, cursor="2")
        self.assertEqual(([(space.key, space.name) for space in last.spaces], last.next_cursor), ([("[hidden]", "[personal space]")], ""))
        everything = app.list_spaces.execute(fetch_everything=True)
        self.assertEqual((len(everything.spaces), everything.next_cursor, everything.truncated), (3, "", False))
        searched = app.list_spaces.execute(search="e")
        self.assertEqual((len(searched.spaces), searched.next_cursor, searched.truncated), (3, "", False))  # the three of them have an `e` in what is printed, the masked one too

    def test_the_policy_refuses_people_before_anything_is_asked_and_changes_nothing_else(self):
        app, gateway = app_with(personal(), hide_users=True)
        with self.assertRaises(ValidationError) as caught:
            app.list_spaces.execute(with_users=True)
        self.assertIn("CONFLUENCE_HIDE_USERS=true", caught.exception.message)
        self.assertEqual(gateway.calls, [])
        plain, _ = app_with(personal())
        self.assertEqual(app.list_spaces.execute(fetch_everything=True), plain.list_spaces.execute(fetch_everything=True))


class ShowSpaceTest(unittest.TestCase):
    def test_a_personal_space_comes_out_masked_and_confluence_is_asked_by_the_key_that_was_typed(self):
        app, gateway = app_with(personal())
        shown = app.show_space.execute(KEY)
        self.assertEqual(shown, hide_space(personal()))
        self.assertEqual(gateway.calls, [("get_space", KEY)])

    def test_with_people_it_is_shown_as_confluence_answers(self):
        app, _ = app_with(personal())
        self.assertEqual(app.show_space.execute(KEY, with_users=True), personal())

    def test_any_other_space_is_what_it_was(self):
        app, gateway = app_with(personal())
        gateway.spaces["ENG"] = dataclasses.replace(gateway.spaces["ENG"], name="Team of alex@example.com", description="Mail alex@example.com")
        shown = app.show_space.execute("ENG")
        self.assertEqual((shown.key, shown.name, shown.description), ("ENG", "Team of [email]", "Mail [email]"))
        self.assertEqual(app.show_space.execute("ENG", with_users=True).name, "Team of alex@example.com")

    def test_the_current_space_is_masked_when_it_is_a_personal_space(self):
        app, _ = app_with(personal(), space=KEY)
        self.assertEqual(app.show_space.execute().key, HIDDEN)
        self.assertEqual(app.show_space.execute("ENG").key, "ENG")

    def test_the_policy_refuses_people_before_anything_is_asked(self):
        app, gateway = app_with(personal(), hide_users=True)
        with self.assertRaises(ValidationError):
            app.show_space.execute(KEY, with_users=True)
        self.assertEqual(gateway.calls, [])
        self.assertEqual(app.show_space.execute(KEY).name, PERSONAL_SPACE)

    def test_a_space_that_is_not_there_is_not_found_and_a_bad_key_is_invalid(self):
        app, _ = app_with(personal())
        with self.assertRaises(NotFoundError):
            app.show_space.execute("~nobody")
        with self.assertRaises(ValidationError):
            app.show_space.execute("../x")


if __name__ == "__main__":
    unittest.main()
