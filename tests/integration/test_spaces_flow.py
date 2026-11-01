"""A personal space is named after its owner: `spaces`, `space` and `use` against the mock Confluence, through the real adapters."""
import json
import unittest

from tests.integration.test_end_to_end import ACCOUNT, EndToEnd

KEY = f"~{ACCOUNT}"
OWNER = (ACCOUNT, "Alex Example", "alex@example.com", "Notes of")  # what nothing that is printed may hold, unless people are shown
STRICT = {"CONFLUENCE_HIDE_USERS": "true"}


class PersonalSpaceFlow(EndToEnd):
    def setUp(self):
        super().setUp()
        self.space_id = self.mock.add_space(KEY, "Alex Example", "personal")
        self.mock.spaces[self.space_id]["description"] = "Notes of alex@example.com"

    def asked(self):
        return [(item.method, item.path) for item in self.mock.requests]

    def row(self, *argv, **kwargs):
        result = self.cli(*argv, "--json", **kwargs)
        self.assertEqual(result.code, 0, result.err)
        return next(space for space in result.json()["spaces"] if space["id"] == self.space_id)


class SpacesTest(PersonalSpaceFlow):
    def test_the_list_has_the_personal_space_masked_and_the_others_as_they_were(self):
        data = self.cli("spaces", "--all", "--json").json()
        self.assertEqual([space["key"] for space in data["spaces"]], ["ENG", "DOCS", "[hidden]"])
        self.assertEqual((data["count"], data["nextCursor"], data["truncated"]), (3, None, False))
        masked = data["spaces"][2]
        self.assertEqual(
            (masked["id"], masked["key"], masked["name"], masked["type"], masked["status"], masked["description"], masked["url"]),
            (self.space_id, "[hidden]", "[personal space]", "personal", "current", "", ""),
        )
        self.assertTrue(masked["homepageId"] and masked["created"])  # they name nobody
        self.assertEqual(data["spaces"][0]["name"], "Engineering")
        self.assertEqual(data["spaces"][0]["url"], f"{self.mock.base_url}/spaces/ENG")

    def test_confluence_is_asked_in_the_usual_way(self):
        self.cli("spaces", "--type", "personal", "--all")
        first = self.mock.requests[0]
        self.assertEqual((first.method, first.path), ("GET", "/api/v2/spaces"))
        self.assertEqual(first.query["type"], ["personal"])
        self.assertEqual(self.mock.unknown_endpoints, [])

    def test_the_text_table_and_the_selection_work_on_the_masked_row(self):
        text = self.cli("spaces", "--type", "personal").out.splitlines()
        self.assertEqual(text[0].split(), ["KEY", "NAME", "TYPE", "STATUS", "HOMEPAGE"])
        self.assertEqual(text[1].split()[:5], ["[hidden]", "[personal", "space]", "personal", "current"])
        tsv = self.cli("spaces", "--all", "--select", "key,name", "--format", "tsv").out.splitlines()
        self.assertEqual(tsv, ["key\tname", "ENG\tEngineering", "DOCS\tDocumentation", "[hidden]\t[personal space]"])

    def test_a_search_cannot_find_a_person_and_reads_the_whole_list_to_say_so(self):
        for text in ("alex", "Alex Example", ACCOUNT, "notes"):
            with self.subTest(search=text):
                data = self.cli("spaces", "--search", text, "--json").json()
                self.assertEqual((data["count"], data["spaces"]), (0, []))
        found = self.cli("spaces", "--search", "alex", "--with-users", "--json").json()
        self.assertEqual([space["key"] for space in found["spaces"]], [KEY])
        self.assertEqual([space["key"] for space in self.cli("spaces", "--search", "doc", "--json").json()["spaces"]], ["DOCS"])

    def test_with_users_the_space_is_shown_as_confluence_names_it(self):
        row = self.row("spaces", "--type", "personal", "--with-users")
        self.assertEqual((row["key"], row["name"], row["description"]), (KEY, "Alex Example", "Notes of alex@example.com"))
        self.assertTrue(row["url"].endswith(f"/spaces/{KEY}"))
        text = self.cli("spaces", "--type", "personal", "--with-users").out
        self.assertIn(KEY, text)
        self.assertIn("Alex Example", text)

    def test_the_masked_entry_goes_through_the_pieces_of_the_list_like_any_other(self):
        first = self.cli("spaces", "--limit", "2", "--json").json()
        self.assertEqual(([space["key"] for space in first["spaces"]], first["nextCursor"]), (["ENG", "DOCS"], "2"))
        last = self.cli("spaces", "--limit", "2", "--cursor", first["nextCursor"], "--json").json()
        self.assertEqual(([space["key"] for space in last["spaces"]], last["nextCursor"]), (["[hidden]"], None))
        self.assertIn("More spaces follow. Continue with --cursor 2", self.cli("spaces", "--limit", "2").err)

    def test_an_archived_personal_space_and_one_that_has_a_plain_key_are_masked_too(self):
        self.mock.spaces[self.space_id]["status"] = "archived"
        other = self.mock.add_space("ALEX", "Alex Example's notes", "personal")  # typed `personal`, and no `~` in the key
        archived = self.cli("spaces", "--status", "archived", "--json").json()["spaces"]
        self.assertEqual([(space["key"], space["name"], space["status"]) for space in archived], [("[hidden]", "[personal space]", "archived")])
        current = self.cli("spaces", "--all", "--json").json()["spaces"]
        self.assertEqual([space["key"] for space in current if space["id"] == other], ["[hidden]"])

    def test_a_name_that_holds_an_address_is_redacted_as_before_for_any_other_space(self):
        self.mock.spaces["1001"]["name"] = "Team of alex@example.com"
        data = self.cli("spaces", "--all", "--json").json()
        self.assertEqual(data["spaces"][0]["name"], "Team of [email]")
        self.assertEqual(self.cli("spaces", "--search", "alex", "--all", "--json").json()["count"], 0)
        self.assertEqual(self.cli("spaces", "--search", "team", "--all", "--json").json()["count"], 1)

    def test_what_the_mock_marks_in_every_free_text_does_not_come_out(self):
        self.mock.taint = True
        for argv in (("spaces", "--all"), ("spaces", "--all", "--json"), ("spaces", "--type", "personal"), ("space", KEY), ("space", "ENG", "--json")):
            with self.subTest(argv=argv):
                result = self.cli(*argv)
                self.assertEqual(result.code, 0, result.err)
                for part in OWNER:
                    self.assertNotIn(part, result.out + result.err)
        shown = self.cli("spaces", "--type", "personal", "--with-users").out
        self.assertIn("alex@example.com", shown)  # the mark is there where people are shown: the check above is no empty one

    def test_a_name_cannot_move_the_cursor_of_the_terminal(self):
        self.mock.spaces[self.space_id]["name"] = "Alex\x1b[2J Example"
        text = self.cli("spaces", "--type", "personal", "--with-users").out
        self.assertNotIn("\x1b", text)
        self.assertIn("Alex[2J Example", text)


class SpaceTest(PersonalSpaceFlow):
    def test_a_personal_space_has_no_key_no_name_no_description_and_no_address(self):
        result = self.cli("space", KEY)
        self.assertEqual(result.code, 0, result.err)
        lines = result.out.splitlines()
        self.assertEqual((lines[0], lines[1], lines[2]), ("[hidden]", "Name:      [personal space]", "Type:      personal"))
        self.assertNotIn("Address", result.out)
        for part in OWNER:
            self.assertNotIn(part, result.out + result.err)
        self.assertEqual(self.asked()[0], ("GET", "/api/v2/spaces"))
        self.assertEqual(self.mock.requests[0].query["keys"], [KEY])  # Confluence is asked by the key that was typed

    def test_the_json_has_the_same_keys(self):
        data = self.cli("space", KEY, "--json").json()
        self.assertEqual(set(data), {"id", "key", "name", "type", "status", "homepageId", "description", "created", "url"})
        self.assertEqual((data["id"], data["key"], data["name"], data["description"], data["url"]), (self.space_id, "[hidden]", "[personal space]", "", ""))

    def test_with_users_it_is_shown_as_confluence_names_it(self):
        data = self.cli("space", KEY, "--with-users", "--json").json()
        self.assertEqual((data["key"], data["name"], data["description"]), (KEY, "Alex Example", "Notes of alex@example.com"))
        text = self.cli("space", KEY, "--with-users").out
        self.assertTrue(text.startswith(f"{KEY}\nName:      Alex Example\n"))

    def test_the_current_space_that_is_personal_is_masked(self):
        data = self.cli("space", "--json", env={"CONFLUENCE_SPACE": KEY}).json()
        self.assertEqual((data["key"], data["name"]), ("[hidden]", "[personal space]"))

    def test_any_other_space_is_what_it_was(self):
        data = self.cli("space", "ENG", "--json").json()
        self.assertEqual((data["key"], data["name"], data["description"]), ("ENG", "Engineering", "Engineering documentation"))
        self.assertEqual(self.cli("space", "NOPE").code, 4)


class UseTest(PersonalSpaceFlow):
    def test_a_personal_space_is_printed_masked_and_saved_under_the_key_that_was_typed(self):
        result = self.cli("use", KEY)
        self.assertEqual((result.code, result.out), (0, "Current space: [hidden] ([personal space])\n"))
        self.assertRegex(self.config.read_text(encoding="utf-8"), rf"(?m)^CONFLUENCE_SPACE='?{KEY}'?$")  # the file quotes a value that starts with ~
        self.assertEqual(self.cli("current").out, "[hidden]\n")  # the file keeps the key, and `current` prints no personal key either
        data = self.cli("space", "--json").json()  # and the saved key is what the other commands use
        self.assertEqual((data["key"], data["id"]), ("[hidden]", self.space_id))

    def test_the_json(self):
        self.assertEqual(self.cli("use", KEY, "--json").json(), {"space": "[hidden]", "name": "[personal space]"})

    def test_any_other_space_is_what_it_was_and_loses_the_address_of_its_name(self):
        self.assertEqual(self.cli("use", "ENG").out, "Current space: ENG (Engineering)\n")
        self.mock.spaces["1001"]["name"] = "Team of alex@example.com"
        self.assertEqual(self.cli("use", "ENG").out, "Current space: ENG (Team of [email])\n")

    def test_the_mock_marks_do_not_come_out_of_it(self):
        self.mock.taint = True
        for argv in (("use", KEY), ("use", KEY, "--json"), ("use", "ENG")):
            result = self.cli(*argv)
            for part in OWNER:
                self.assertNotIn(part, result.out + result.err)


class PolicyTest(PersonalSpaceFlow):
    def test_with_users_is_refused_before_anything_is_asked_and_the_counts_are_the_same(self):
        for argv in (("spaces", "--with-users"), ("spaces", "--type", "personal", "--with-users", "--json"), ("space", KEY, "--with-users")):
            with self.subTest(argv=argv):
                result = self.cli(*argv, env=STRICT)
                self.assertEqual((result.code, result.out), (1, ""))
                self.assertIn("CONFLUENCE_HIDE_USERS=true", result.err)
                for part in OWNER:
                    self.assertNotIn(part, result.err)
        self.assertEqual(self.mock.requests, [])
        self.assertEqual(self.cli("spaces", "--all", "--json", env=STRICT).json(), self.cli("spaces", "--all", "--json").json())

    def test_the_agent_profile_makes_json_and_hides_people(self):
        shown = self.cli("spaces", "--all", env={"CONFLUENCE_PROFILE": "agent"})
        self.assertEqual(shown.code, 0, shown.err)
        keys = [space["key"] for space in json.loads(shown.out)["spaces"]]
        self.assertEqual(keys, ["ENG", "DOCS", "[hidden]"])
        refused = self.cli("spaces", "--all", "--with-users", env={"CONFLUENCE_PROFILE": "agent"})
        self.assertEqual(refused.code, 1)
        allowed = self.cli("spaces", "--type", "personal", "--with-users", "--json", env={"CONFLUENCE_PROFILE": "agent", "CONFLUENCE_HIDE_USERS": "false"})
        self.assertEqual(json.loads(allowed.out)["spaces"][0]["key"], KEY)


class AsAProgramTest(PersonalSpaceFlow):
    def test_as_a_separate_program(self):
        result = self.child("spaces", "--type", "personal", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(json.loads(result.out)["spaces"][0]["key"], "[hidden]")
        self.assertEqual(self.child("space", KEY, "--json").json()["name"], "[personal space]")
        self.assertEqual(self.child("use", KEY).out, "Current space: [hidden] ([personal space])\n")
        self.assertEqual(self.child("spaces", "--with-users", env=STRICT).code, 1)


if __name__ == "__main__":
    unittest.main()
