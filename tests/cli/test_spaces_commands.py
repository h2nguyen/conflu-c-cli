"""The commands that name a space (`spaces`, `space`, `use`) with the in-memory Confluence: a personal space is named after its owner, so it comes out without the owner unless people are asked for."""
import dataclasses
import json
import unittest

from conflu_c_cli.adapters.driving.cli.help import mcp_property_names
from conflu_c_cli.adapters.driving.cli.registry import find_command
from conflu_c_cli.domain.model import Space
from conflu_c_cli.domain.privacy import hide_space
from tests.support.cli import run_cli
from tests.support.fakes import ACCOUNT, BASE, FakeGateway, MemoryConfigStore, default_settings

KEY = f"~{ACCOUNT}"
OWNER = (ACCOUNT, "Alex Example", "alex@example.com", "Notes of")  # what nothing that is printed may hold, unless people are shown
PERSONAL_ROW = {
    "id": "1003",
    "key": "[hidden]",
    "name": "[personal space]",
    "type": "personal",
    "status": "current",
    "homepageId": "3501",
    "description": "",
    "created": "2026-09-02T08:00:00.000Z",
    "url": "",
}


def fresh():
    gateway = FakeGateway()
    gateway.spaces[KEY] = Space("1003", KEY, "Alex Example", "personal", "current", "Notes of alex@example.com", "3501", "2026-09-02T08:00:00.000Z", f"{BASE}/spaces/{KEY}/overview")
    return gateway


class DescriptionTest(unittest.TestCase):
    def test_spaces_and_space_have_the_option_and_say_what_they_do_with_a_personal_space(self):
        for name in ("spaces", "space"):
            command = find_command(name)
            with self.subTest(command=name):
                option = next(arg for arg in command.args if arg.names == ("--with-users",))
                self.assertEqual(option.kind, "flag")
                self.assertIn("CONFLUENCE_HIDE_USERS=true", option.help)
                for text in (command.description, command.output):
                    self.assertIn("[hidden]", " ".join(text.split()))
                self.assertIn("[personal space]", command.output)
                self.assertIn("personal space", command.when)
                self.assertIn("--with-users", command.when)
                self.assertFalse(command.writes or command.for_person or command.local)
        text = " ".join(run_cli("help", "use").out.split())
        self.assertIn("[hidden] ([personal space])", text)

    def test_the_examples_use_the_option(self):
        for name, wanted in (("spaces", "conflu spaces --type personal --with-users"), ("space", "conflu space ENG --with-users")):
            self.assertIn(wanted, [example.command for example in find_command(name).examples])

    def test_a_model_can_ask_for_people_with_a_property_that_the_server_may_refuse(self):
        for name in ("spaces", "space"):
            self.assertIn("withUsers", mcp_property_names(find_command(name)).values())

    def test_the_catalog_lists_the_option_and_the_keys_are_unchanged(self):
        catalog = {item["name"]: item for item in run_cli("commands", "--json").json()["commands"]}
        self.assertIn("--with-users", [arg["names"][0] for arg in catalog["spaces"]["arguments"]])
        self.assertIn("--with-users", [arg["names"][0] for arg in catalog["space"]["arguments"]])
        self.assertEqual([arg["names"][0] for arg in catalog["use"]["arguments"]], ["key"])  # `use` prints the masked entry always: there is no option
        row = run_cli("spaces", "--json", gateway=fresh()).json()["spaces"][0]
        self.assertEqual(set(row), set(PERSONAL_ROW))


class SpacesTest(unittest.TestCase):
    def test_the_table_has_the_personal_space_masked_and_the_others_as_before(self):
        result = run_cli("spaces", "--all", gateway=fresh())
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(
            result.out.splitlines(),
            [
                "KEY       NAME              TYPE      STATUS   HOMEPAGE",
                "DOCS      Documentation     global    current  3001",
                "ENG       Engineering       global    current  2001",
                "[hidden]  [personal space]  personal  current  3501",
            ],
        )
        self.assertEqual(result.err, "")

    def test_the_json_has_the_same_keys_and_the_masked_values(self):
        data = run_cli("spaces", "--all", "--json", gateway=fresh()).json()
        self.assertEqual((data["count"], data["nextCursor"], data["truncated"]), (3, None, False))
        self.assertEqual([space["key"] for space in data["spaces"]], ["DOCS", "ENG", "[hidden]"])
        self.assertEqual(data["spaces"][2], PERSONAL_ROW)
        self.assertEqual(data["spaces"][1]["description"], "Engineering documentation")
        self.assertEqual(data["spaces"][1]["url"], f"{BASE}/spaces/ENG")

    def test_select_and_format_work_on_the_masked_rows(self):
        gateway = fresh()
        tsv = run_cli("spaces", "--all", "--select", "key,name", "--format", "tsv", gateway=gateway).out.splitlines()
        self.assertEqual(tsv, ["key\tname", "DOCS\tDocumentation", "ENG\tEngineering", "[hidden]\t[personal space]"])
        md = run_cli("spaces", "--type", "personal", "--format", "md", gateway=gateway).out.splitlines()
        self.assertEqual(md, ["| KEY | NAME | TYPE | STATUS | HOMEPAGE |", "| --- | --- | --- | --- | --- |", "| [hidden] | [personal space] | personal | current | 3501 |"])
        picked = run_cli("spaces", "--all", "--select", "id,key,url", "--json", gateway=gateway).json()
        self.assertEqual(picked["spaces"][2], {"id": "1003", "key": "[hidden]", "url": ""})
        self.assertEqual(picked["count"], 3)  # the rest of the document stays

    def test_the_type_filter_lists_the_personal_spaces_without_their_owners(self):
        gateway = fresh()
        data = run_cli("spaces", "--type", "personal", "--json", gateway=gateway).json()
        self.assertEqual((data["count"], data["spaces"]), (1, [PERSONAL_ROW]))
        self.assertEqual(run_cli("spaces", "--type", "global", "--json", gateway=gateway).json()["count"], 2)

    def test_a_search_cannot_find_a_person_by_name(self):
        gateway = fresh()
        for text in ("alex", "Alex Example", ACCOUNT, "~", "notes"):
            with self.subTest(search=text):
                result = run_cli("spaces", "--search", text, "--all", gateway=gateway)
                self.assertEqual((result.code, result.out), (0, "No spaces.\n"))
                self.assertEqual(run_cli("spaces", "--search", text, "--json", gateway=gateway).json()["count"], 0)
        self.assertEqual([space["key"] for space in run_cli("spaces", "--search", "engin", "--json", gateway=gateway).json()["spaces"]], ["ENG"])

    def test_with_users_the_personal_space_is_shown_as_confluence_names_it(self):
        gateway = fresh()
        text = run_cli("spaces", "--type", "personal", "--with-users", gateway=gateway).out.splitlines()
        self.assertEqual(text, ["KEY                        NAME          TYPE      STATUS   HOMEPAGE", f"{KEY}  Alex Example  personal  current  3501"])
        row = run_cli("spaces", "--type", "personal", "--with-users", "--json", gateway=gateway).json()["spaces"][0]
        self.assertEqual((row["key"], row["name"], row["description"], row["url"]), (KEY, "Alex Example", "Notes of alex@example.com", f"{BASE}/spaces/{KEY}/overview"))
        found = run_cli("spaces", "--search", "alex", "--with-users", "--json", gateway=gateway).json()
        self.assertEqual([space["key"] for space in found["spaces"]], [KEY])

    def test_a_piece_of_the_list_says_how_to_go_on_and_the_masked_entry_counts(self):
        gateway = fresh()
        first = run_cli("spaces", "--limit", "1", gateway=gateway)
        self.assertIn("More spaces follow. Continue with --cursor 1, or use --all.", first.err)
        last = run_cli("spaces", "--limit", "1", "--cursor", "2", "--json", gateway=gateway).json()
        self.assertEqual((last["count"], last["nextCursor"], last["spaces"][0]["key"]), (1, None, "[hidden]"))

    def test_the_policy_refuses_with_users_before_anything_is_asked_and_changes_nothing_else(self):
        gateway = fresh()
        policy = default_settings(hide_users=True)
        refused = run_cli("spaces", "--with-users", gateway=gateway, settings=policy)
        self.assertEqual((refused.code, refused.out), (1, ""))
        self.assertIn("CONFLUENCE_HIDE_USERS=true", refused.err)
        self.assertEqual(gateway.calls, [])
        error = run_cli("spaces", "--with-users", "--json", gateway=gateway, settings=policy).error()
        self.assertEqual((error["code"], error["exitCode"]), ("INVALID", 1))
        self.assertEqual(run_cli("spaces", "--all", "--json", gateway=gateway, settings=policy).json(), run_cli("spaces", "--all", "--json", gateway=gateway).json())

    def test_a_bad_filter_is_still_a_usage_error(self):
        self.assertEqual(run_cli("spaces", "--type", "secret", gateway=fresh()).code, 2)


class SpaceTest(unittest.TestCase):
    def test_a_personal_space_has_no_key_no_name_no_description_and_no_address(self):
        result = run_cli("space", KEY, gateway=fresh())
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(
            result.out.splitlines(),
            ["[hidden]", "Name:      [personal space]", "Type:      personal", "Status:    current", "Id:        1003", "Home page: 3501", "Created:   2026-09-02T08:00:00.000Z"],
        )

    def test_the_json_has_the_same_keys_and_the_masked_values(self):
        self.assertEqual(run_cli("space", KEY, "--json", gateway=fresh()).json(), PERSONAL_ROW)

    def test_with_users_it_is_shown_as_confluence_names_it(self):
        gateway = fresh()
        text = run_cli("space", KEY, "--with-users", gateway=gateway).out
        self.assertTrue(text.startswith(f"{KEY}\nName:      Alex Example\n"))
        self.assertTrue(text.endswith("\nNotes of alex@example.com\n"))
        data = run_cli("space", KEY, "--with-users", "--json", gateway=gateway).json()
        self.assertEqual((data["key"], data["name"], data["description"], data["url"]), (KEY, "Alex Example", "Notes of alex@example.com", f"{BASE}/spaces/{KEY}/overview"))

    def test_the_current_space_is_masked_when_it_is_a_personal_space(self):
        gateway = fresh()
        self.assertEqual(run_cli("space", "--json", gateway=gateway, settings=default_settings(space=KEY)).json(), PERSONAL_ROW)
        self.assertEqual(run_cli("space", "--json", gateway=gateway, settings=default_settings(space="DOCS")).json()["key"], "DOCS")

    def test_any_other_space_is_what_it_was_and_still_loses_its_addresses(self):
        gateway = fresh()
        shown = run_cli("space", "ENG", gateway=gateway).out
        self.assertTrue(shown.startswith("ENG\nName:      Engineering\n"))
        self.assertIn("Engineering documentation", shown)
        gateway.spaces["ENG"] = dataclasses.replace(gateway.spaces["ENG"], name="Team of alex@example.com", description="Mail alex@example.com")
        data = run_cli("space", "ENG", "--json", gateway=gateway).json()
        self.assertEqual((data["name"], data["description"]), ("Team of [email]", "Mail [email]"))
        self.assertEqual(run_cli("space", "ENG", "--with-users", "--json", gateway=gateway).json()["name"], "Team of alex@example.com")

    def test_the_policy_refuses_with_users_before_anything_is_asked(self):
        gateway = fresh()
        policy = default_settings(hide_users=True)
        refused = run_cli("space", KEY, "--with-users", gateway=gateway, settings=policy)
        self.assertEqual((refused.code, refused.out), (1, ""))
        self.assertIn("CONFLUENCE_HIDE_USERS=true", refused.err)
        self.assertEqual(gateway.calls, [])
        self.assertEqual(run_cli("space", KEY, "--json", gateway=gateway, settings=policy).json(), PERSONAL_ROW)

    def test_what_is_wrong_with_the_command_line(self):
        gateway = fresh()
        self.assertEqual(run_cli("space", gateway=gateway).code, 2)  # no key and no current space
        self.assertEqual(run_cli("space", "~nobody", gateway=gateway).code, 4)
        self.assertEqual(run_cli("space", "../x", gateway=gateway).code, 1)


class UseTest(unittest.TestCase):
    def test_a_personal_space_is_printed_without_its_owner_and_saved_under_the_key_that_was_typed(self):
        store = MemoryConfigStore()
        result = run_cli("use", KEY, gateway=fresh(), store=store)
        self.assertEqual((result.code, result.out), (0, "Current space: [hidden] ([personal space])\n"))
        self.assertEqual(store.values["CONFLUENCE_SPACE"], KEY)
        self.assertEqual(run_cli("current", settings=default_settings(space=KEY)).out, "[hidden]\n")  # the setting keeps the key, and `current` prints no personal key either

    def test_the_json(self):
        store = MemoryConfigStore()
        self.assertEqual(run_cli("use", KEY, "--json", gateway=fresh(), store=store).json(), {"space": "[hidden]", "name": "[personal space]"})
        self.assertEqual(store.values["CONFLUENCE_SPACE"], KEY)
        wrapped = run_cli("use", KEY, "--json-envelope", gateway=fresh(), store=store).json()
        self.assertEqual((wrapped["ok"], wrapped["data"]), (True, {"space": "[hidden]", "name": "[personal space]"}))

    def test_any_other_space_is_what_it_was_and_still_loses_its_addresses(self):
        gateway = fresh()
        store = MemoryConfigStore()
        self.assertEqual(run_cli("use", "eng", gateway=gateway, store=store).out, "Current space: ENG (Engineering)\n")
        gateway.spaces["ENG"] = dataclasses.replace(gateway.spaces["ENG"], name="Team of alex@example.com")
        self.assertEqual(run_cli("use", "ENG", gateway=gateway, store=store).out, "Current space: ENG (Team of [email])\n")
        self.assertEqual(run_cli("use", "ENG", "--json", gateway=gateway, store=store).json(), {"space": "ENG", "name": "Team of [email]"})

    def test_a_space_that_is_not_there_is_not_found_and_saves_nothing(self):
        store = MemoryConfigStore()
        self.assertEqual(run_cli("use", "~nobody", gateway=fresh(), store=store).code, 4)
        self.assertNotIn("CONFLUENCE_SPACE", store.values)

    def test_the_note_about_the_variable_does_not_name_the_space(self):
        result = run_cli("use", KEY, gateway=fresh(), environ={"CONFLUENCE_SPACE": "DOCS"})
        self.assertIn("CONFLUENCE_SPACE is also set in the environment", result.err)
        self.assertNotIn(ACCOUNT, result.out + result.err)


class NoOwnerByDefaultTest(unittest.TestCase):
    INVOCATIONS = (
        ("spaces",),
        ("spaces", "--all"),
        ("spaces", "--all", "--json"),
        ("spaces", "--type", "personal"),
        ("spaces", "--type", "personal", "--json"),
        ("spaces", "--all", "--select", "key,name,description,url", "--format", "tsv"),
        ("spaces", "--all", "--format", "md"),
        ("spaces", "--search", "alex", "--all"),
        ("spaces", "--limit", "1", "--cursor", "2"),
        ("space", KEY),
        ("space", KEY, "--json"),
        ("space",),
        ("use", KEY),
        ("use", KEY, "--json"),
    )

    def test_no_account_id_no_name_no_address_and_no_description_without_with_users(self):
        gateway = fresh()
        settings = {"default": None, "policy": default_settings(hide_users=True), "personal current space": default_settings(space=KEY)}
        for label, chosen in settings.items():
            for argv in self.INVOCATIONS:
                if argv == ("space",) and label != "personal current space":
                    continue  # it asks for a current space, and only that setting has one
                with self.subTest(argv=argv, settings=label):
                    result = run_cli(*argv, gateway=gateway, settings=chosen, store=MemoryConfigStore())
                    self.assertEqual(result.code, 0, result.err)
                    for part in OWNER:
                        self.assertNotIn(part, result.out + result.err)

    def test_the_owner_is_there_with_with_users_so_the_scan_above_is_not_empty(self):
        gateway = fresh()
        text = run_cli("spaces", "--all", "--with-users", gateway=gateway).out + run_cli("space", KEY, "--with-users", gateway=gateway).out
        for part in (ACCOUNT, "Alex Example", "alex@example.com", "Notes of"):
            self.assertIn(part, text)

    def test_the_commands_only_read(self):
        gateway = fresh()
        for argv in self.INVOCATIONS:
            if argv != ("space",):
                run_cli(*argv, gateway=gateway)
        self.assertLessEqual({call[0] for call in gateway.calls}, {"list_spaces", "get_space"})
        self.assertTrue(gateway.calls)
        self.assertEqual(json.loads(run_cli("spaces", "--all", "--json", gateway=gateway).out)["count"], 3)


def printed_by_every_command(gateway, key, settings=None):
    """The key and the name of one space as each command that names a space prints them (in JSON): {command: (key, name)}."""

    def run(*argv):
        return run_cli(*argv, "--json", gateway=gateway, settings=settings, store=MemoryConfigStore()).json()

    def of_target(document):
        return document["target"]["key"], document["target"]["title"]

    listed = next(row for row in run("spaces", "--all")["spaces"] if row["id"] == gateway.spaces[key].id)
    shown = run("space", key)
    used = run("use", key)
    return {
        "spaces": (listed["key"], listed["name"]),
        "space": (shown["key"], shown["name"]),
        "use": (used["space"], used["name"]),
        "permissions --space": of_target(run("permissions", "--space", key)),
        "space-access": of_target(run("space-access", key)),
        "watching --space": of_target(run("watching", "--space", key)),
        "watch --space": of_target(run("watch", "--space", key, "--dry-run")),
    }


class OneRuleTest(unittest.TestCase):
    """The commands that name a space print it as one function says (`privacy.hide_space`), so that they cannot drift apart."""

    def test_a_personal_space_is_the_same_hidden_entry_in_every_command(self):
        gateway = fresh()
        expected = hide_space(gateway.spaces[KEY])
        self.assertEqual((expected.key, expected.name), ("[hidden]", "[personal space]"))
        for label, settings in (("default", None), ("policy", default_settings(hide_users=True))):
            for command, printed in printed_by_every_command(gateway, KEY, settings).items():
                with self.subTest(command=command, settings=label):
                    self.assertEqual(printed, (expected.key, expected.name))

    def test_any_other_space_is_the_same_redacted_entry_in_every_command(self):
        gateway = fresh()
        gateway.spaces["ENG"] = dataclasses.replace(gateway.spaces["ENG"], name="Team of alex@example.com")
        expected = hide_space(gateway.spaces["ENG"])
        self.assertEqual((expected.key, expected.name), ("ENG", "Team of [email]"))
        for command, printed in printed_by_every_command(gateway, "ENG").items():
            with self.subTest(command=command):
                self.assertEqual(printed, (expected.key, expected.name))

    def test_with_users_the_commands_that_have_the_option_agree_on_what_they_show(self):
        gateway = fresh()
        listed = next(row for row in run_cli("spaces", "--all", "--with-users", "--json", gateway=gateway).json()["spaces"] if row["id"] == "1003")
        shown = run_cli("space", KEY, "--with-users", "--json", gateway=gateway).json()
        target = run_cli("space-access", KEY, "--with-users", "--json", gateway=gateway).json()["target"]
        self.assertEqual({(listed["key"], listed["name"]), (shown["key"], shown["name"]), (target["key"], target["title"])}, {(KEY, "Alex Example")})


if __name__ == "__main__":
    unittest.main()
