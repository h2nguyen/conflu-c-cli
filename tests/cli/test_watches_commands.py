"""The commands `watching` and `watch` on the command line, with the in-memory Confluence: what they print, what they refuse, how they are described."""
import dataclasses
import json
import unittest

from conflu_c_cli.adapters.driving.cli.help import mcp_tool, render_command_help
from conflu_c_cli.adapters.driving.cli.parser import build_parser
from conflu_c_cli.adapters.driving.cli.registry import all_commands, find_command
from conflu_c_cli.domain.errors import RejectedError, UnavailableError
from conflu_c_cli.domain.model import Space
from tests.support.cli import run_cli
from tests.support.fakes import ACCOUNT, BASE, FakeGateway, default_settings

BLOG_POST = "7561"


def fresh():
    gateway = FakeGateway()
    gateway.content_kinds[BLOG_POST] = "blogpost"
    return gateway


class DescriptionTest(unittest.TestCase):
    def test_both_are_in_the_group_of_the_people_and_say_what_they_do(self):
        for name in ("watching", "watch"):
            command = find_command(name)
            with self.subTest(command=name):
                self.assertEqual(command.group, "Access and people")
                self.assertTrue(command.when and command.output and command.json_output and command.examples and command.notes)
                self.assertFalse(command.for_person or command.local or command.destructive)

    def test_watching_reads_and_watch_changes_your_own_watch_and_can_be_repeated(self):
        self.assertFalse(find_command("watching").writes)
        watch = find_command("watch")
        self.assertTrue(watch.writes and watch.idempotent)
        self.assertFalse(watch.destructive)  # it takes off a setting of your own, no content: see the notes
        self.assertTrue(any("--dry-run" in arg.names for arg in watch.args))

    def test_there_is_no_option_that_names_another_person(self):
        for name in ("watching", "watch"):
            dests = {arg.dest for arg in find_command(name).args}
            with self.subTest(command=name):
                self.assertFalse(dests & {"user", "users", "account", "account_id", "accountid", "username", "for_user", "who", "with_users", "key"})
        self.assertEqual({arg.dest for arg in find_command("watch").args}, {"ref", "space", "remove", "dry_run"})
        self.assertEqual({arg.dest for arg in find_command("watching").args}, {"ref", "space"})

    def test_the_examples_say_what_they_do_and_parse(self):
        for name in ("watching", "watch"):
            for example in find_command(name).examples:
                with self.subTest(example=example.command):
                    build_parser(find_command(name)).parse_args(example.command.split()[2:])

    def test_the_help_says_that_it_is_only_your_own_watch(self):
        text = " ".join(render_command_help(find_command("watch")).split())
        self.assertIn("your own watch only, never somebody else's", text)
        self.assertIn("there is no option to name another person", text)
        self.assertIn("removes that and no content", text)
        self.assertIn("preview with --dry-run", text.lower())
        self.assertIn("cannot remove anybody else's watch", text)

    def test_an_agent_is_told_how_far_it_goes(self):
        annotations = mcp_tool(find_command("watch"))["annotations"]
        self.assertEqual((annotations["readOnlyHint"], annotations["destructiveHint"], annotations["idempotentHint"]), (False, False, True))
        self.assertTrue(mcp_tool(find_command("watching"))["annotations"]["readOnlyHint"])
        description = mcp_tool(find_command("watch"))["description"]
        self.assertIn("Changes Confluence. Run it with dryRun first", description)
        properties = mcp_tool(find_command("watch"))["inputSchema"]["properties"]
        self.assertEqual(set(properties), {"page", "space", "remove", "dryRun"})

    def test_the_commands_are_listed_in_the_catalog(self):
        catalog = {item["name"]: item for item in run_cli("commands", "--json").json()["commands"]}
        self.assertEqual([arg["names"][0] for arg in catalog["watch"]["arguments"]], ["ref", "--space", "--remove", "--dry-run"])
        self.assertTrue(catalog["watch"]["changesData"] and not catalog["watching"]["changesData"])
        self.assertIn("confirmed", catalog["watch"]["jsonOutput"])
        self.assertEqual([item.name for item in all_commands() if item.name in ("watching", "watch")], ["watching", "watch"])


class WatchingTest(unittest.TestCase):
    def test_a_page_you_do_not_watch(self):
        result = run_cli("watching", "2002", gateway=fresh())
        self.assertEqual((result.code, result.out), (0, "You do not watch the page [2002].\n"))

    def test_a_page_you_watch_by_its_address(self):
        gateway = fresh()
        gateway.watching.add(("content", "2002"))
        result = run_cli("watching", f"{BASE}/spaces/ENG/pages/2002/Release+notes", gateway=gateway)
        self.assertEqual(result.out, "You watch the page [2002].\n")

    def test_a_blog_post_is_named_as_one(self):
        gateway = fresh()
        gateway.watching.add(("content", BLOG_POST))
        self.assertEqual(run_cli("watching", BLOG_POST, gateway=gateway).out, f"You watch the blog post [{BLOG_POST}].\n")

    def test_a_space_with_its_name(self):
        gateway = fresh()
        gateway.watching.add(("space", "ENG"))
        self.assertEqual(run_cli("watching", "--space", "ENG", gateway=gateway).out, "You watch the space ENG (Engineering).\n")
        self.assertEqual(run_cli("watching", "--space", "DOCS", gateway=gateway).out, "You do not watch the space DOCS (Documentation).\n")

    def test_the_json_for_content(self):
        gateway = fresh()
        gateway.watching.add(("content", "2002"))
        data = run_cli("watching", "2002", "--json", gateway=gateway).json()
        self.assertEqual(list(data), ["target", "watching"])
        self.assertEqual(data, {"target": {"id": "2002", "type": "page", "key": None, "title": None}, "watching": True})

    def test_the_json_for_a_space(self):
        data = run_cli("watching", "--space", "ENG", "--json", gateway=fresh()).json()
        self.assertEqual(data, {"target": {"id": "1001", "type": "space", "key": "ENG", "title": "Engineering"}, "watching": False})

    def test_the_current_space_is_what_a_read_assumes(self):
        gateway = fresh()
        gateway.watching.add(("space", "DOCS"))
        result = run_cli("watching", gateway=gateway, settings=default_settings(space="DOCS"))
        self.assertEqual(result.out, "You watch the space DOCS (Documentation).\n")
        nothing = run_cli("watching", gateway=gateway)
        self.assertEqual(nothing.code, 2)
        self.assertIn("run `conflu use KEY`", nothing.err)

    def test_a_page_and_a_space_together_are_a_usage_error(self):
        result = run_cli("watching", "2002", "--space", "ENG", gateway=fresh())
        self.assertEqual((result.code, result.out), (2, ""))
        self.assertIn("not both", result.err)

    def test_what_is_not_there_is_not_found_and_what_is_no_id_is_invalid(self):
        self.assertEqual(run_cli("watching", "99999", gateway=fresh()).code, 4)
        self.assertEqual(run_cli("watching", "--space", "NOSUCH", gateway=fresh()).code, 4)
        invalid = run_cli("watching", "../x", gateway=fresh())
        self.assertEqual(invalid.code, 1)
        self.assertIn("--space KEY", invalid.err)
        error = run_cli("watching", "99999", "--json", gateway=fresh()).error()
        self.assertEqual((error["code"], error["exitCode"], error["details"]), ("NOT_FOUND", 4, {"id": "99999"}))

    def test_the_failure_of_the_question_is_an_error_and_not_an_answer(self):
        gateway = fresh()
        gateway.errors["watch_status"] = UnavailableError("Cannot reach Confluence.", hint="Check the VPN.")
        result = run_cli("watching", "2002", gateway=gateway)
        self.assertEqual((result.code, result.out), (7, ""))
        self.assertIn("Check the VPN.", result.err)

    def test_no_person_is_in_the_answer(self):
        gateway = fresh()
        gateway.watching.add(("content", "2002"))
        for argv in (("watching", "2002"), ("watching", "2002", "--json"), ("watching", "--space", "ENG", "--json")):
            result = run_cli(*argv, gateway=gateway)
            with self.subTest(argv=argv):
                self.assertNotIn(ACCOUNT, result.out + result.err)
                self.assertNotIn("Alex", result.out + result.err)
                self.assertNotIn("alex@example.com", result.out + result.err)

    def test_a_personal_space_is_printed_as_it_is_everywhere_neither_its_key_nor_the_name_of_its_owner(self):
        """It is keyed by the account id of its owner and named after them: `[hidden]` and `[personal space]`, as `conflu spaces` prints it."""
        gateway = fresh()
        gateway.spaces["~alexe"] = Space("1003", "~alexe", "Alex Example", "personal", "current")
        self.assertEqual(run_cli("watching", "--space", "~alexe", gateway=gateway).out, "You do not watch the space [hidden] ([personal space]).\n")
        data = run_cli("watching", "--space", "~alexe", "--json", gateway=gateway).json()
        self.assertEqual(data["target"], {"id": "1003", "type": "space", "key": "[hidden]", "title": "[personal space]"})
        for argv in (("watch", "--space", "~alexe", "--dry-run"), ("watch", "--space", "~alexe", "--json"), ("watch", "--space", "~alexe", "--remove"), ("watching", "--space", "~alexe")):
            result = run_cli(*argv, gateway=gateway)
            with self.subTest(argv=argv):
                self.assertEqual(result.code, 0, result.err)
                self.assertNotIn("Alex", result.out + result.err)
                self.assertNotIn("~alexe", result.out + result.err)
        self.assertEqual(gateway.watching, set())  # the last of them took the watch off: the calls named the real key all along

    def test_the_privacy_policy_does_not_stand_in_the_way_because_no_person_is_shown(self):
        settings = default_settings(hide_users=True)
        self.assertEqual(run_cli("watching", "2002", gateway=fresh(), settings=settings).code, 0)
        self.assertEqual(run_cli("watch", "2002", "--dry-run", gateway=fresh(), settings=settings).code, 0)

    def test_the_envelope(self):
        data = run_cli("watching", "2002", "--json-envelope", gateway=fresh()).json()
        self.assertEqual((data["ok"], data["data"]["watching"]), (True, False))


class WatchTest(unittest.TestCase):
    def test_start_and_the_same_again_and_stop(self):
        gateway = fresh()
        self.assertEqual(run_cli("watch", "2002", gateway=gateway).out, "Now watching the page [2002].\n")
        self.assertEqual(gateway.watching, {("content", "2002")})
        self.assertEqual(run_cli("watch", "2002", gateway=gateway).out, "Nothing to change: you watch the page [2002] already.\n")
        self.assertEqual(run_cli("watch", "2002", "--remove", gateway=gateway).out, "Stopped watching the page [2002].\n")
        self.assertEqual(gateway.watching, set())
        self.assertEqual(run_cli("watch", "2002", "--remove", gateway=gateway).out, "Nothing to change: you do not watch the page [2002].\n")
        self.assertEqual(len(gateway.called("change_watch")), 2)

    def test_a_space(self):
        gateway = fresh()
        self.assertEqual(run_cli("watch", "--space", "ENG", gateway=gateway).out, "Now watching the space ENG (Engineering).\n")
        self.assertEqual(run_cli("watch", "--space", "ENG", "--remove", gateway=gateway).out, "Stopped watching the space ENG (Engineering).\n")

    def test_the_dry_run_says_what_it_would_do_and_sends_nothing(self):
        gateway = fresh()
        result = run_cli("watch", "2002", "--dry-run", gateway=gateway)
        self.assertEqual(
            result.out,
            "Dry run: you would start watching the page [2002]; nothing was sent\nCall: POST /rest/api/user/watch/content/{contentId}\n",
        )
        self.assertEqual((gateway.watching, gateway.called("change_watch")), (set(), []))
        gateway.watching.add(("space", "ENG"))
        stop = run_cli("watch", "--space", "ENG", "--remove", "--dry-run", gateway=gateway)
        self.assertEqual(stop.out, "Dry run: you would stop watching the space ENG (Engineering); nothing was sent\nCall: DELETE /rest/api/user/watch/space/{spaceKey}\n")
        self.assertEqual(gateway.watching, {("space", "ENG")})

    def test_the_dry_run_of_what_is_as_asked_already_says_so(self):
        gateway = fresh()
        gateway.watching.add(("content", "2002"))
        self.assertEqual(run_cli("watch", "2002", "--dry-run", gateway=gateway).out, "Nothing to change: you watch the page [2002] already.\n")

    def test_the_json_of_a_change(self):
        gateway = fresh()
        data = run_cli("watch", "2002", "--json", gateway=gateway).json()
        self.assertEqual(
            list(data), ["action", "dryRun", "target", "wasWatching", "watching", "confirmed", "call", "message"]
        )
        self.assertEqual(
            data,
            {
                "action": "watched",
                "dryRun": False,
                "target": {"id": "2002", "type": "page", "key": None, "title": None},
                "wasWatching": False,
                "watching": True,
                "confirmed": True,
                "call": "POST /rest/api/user/watch/content/{contentId}",
                "message": None,
            },
        )

    def test_the_json_of_a_dry_run_a_stop_and_a_change_that_was_not_needed(self):
        gateway = fresh()
        dry = run_cli("watch", "--space", "ENG", "--dry-run", "--json", gateway=gateway).json()
        self.assertEqual((dry["action"], dry["dryRun"], dry["wasWatching"], dry["watching"], dry["confirmed"], dry["call"]), ("watched", True, False, False, None, "POST /rest/api/user/watch/space/{spaceKey}"))
        self.assertEqual(dry["target"], {"id": "1001", "type": "space", "key": "ENG", "title": "Engineering"})
        run_cli("watch", "2002", gateway=gateway)
        stop = run_cli("watch", "2002", "--remove", "--json", gateway=gateway).json()
        self.assertEqual((stop["action"], stop["wasWatching"], stop["watching"], stop["confirmed"], stop["call"]), ("unwatched", True, False, True, "DELETE /rest/api/user/watch/content/{contentId}"))
        again = run_cli("watch", "2002", "--remove", "--json", gateway=gateway).json()
        self.assertEqual((again["action"], again["wasWatching"], again["watching"], again["confirmed"], again["call"], again["message"]), ("unchanged", False, False, None, None, None))

    def test_a_read_back_that_fails_is_exit_code_0_with_a_warning_and_the_json_says_so(self):
        class ReadBackFails(FakeGateway):
            def change_watch(self, change):
                super().change_watch(change)
                self.errors["watch_status"] = UnavailableError("Confluence answered with a server error (HTTP 500).")

        gateway = ReadBackFails()
        result = run_cli("watch", "2002", "--json", gateway=gateway)
        self.assertEqual(result.code, 0, result.err)
        data = result.json()
        self.assertEqual((data["action"], data["watching"], data["confirmed"]), ("watched", None, None))
        self.assertIn("The watch was added, but reading the watch status afterwards failed", data["message"])
        self.assertIn("WARNING: The watch was added", result.err)
        self.assertEqual(gateway.watching, {("content", "2002")})
        text = run_cli("watch", "2003", gateway=ReadBackFails())
        self.assertEqual(text.code, 0)
        self.assertEqual(text.out, "Now watching the page [2003]. The change was made, but reading the status back failed (see the warning).\n")
        self.assertIn("Check it with `conflu watching 2003`", text.err)

    def test_a_change_that_is_not_shown_afterwards_is_reported_and_is_no_failure(self):
        class Ignores(FakeGateway):
            def change_watch(self, change):
                self._enter("change_watch", change)

        result = run_cli("watch", "2002", gateway=Ignores())
        self.assertEqual(result.code, 0)
        self.assertEqual(result.out, "Now watching the page [2002]. Confluence does not show the change yet (see the warning).\n")
        self.assertIn("still says that you do not watch it", result.err)

    def test_a_write_that_is_refused_is_an_error(self):
        gateway = fresh()
        gateway.errors["change_watch"] = RejectedError("Confluence refused the request (HTTP 400): no")
        result = run_cli("watch", "2002", gateway=gateway)
        self.assertEqual((result.code, result.out), (6, ""))
        self.assertEqual(gateway.watching, set())

    def test_a_change_names_what_it_changes(self):
        gateway = fresh()
        for argv in (("watch",), ("watch", "--remove"), ("watch", "--dry-run")):
            with self.subTest(argv=argv):
                result = run_cli(*argv, gateway=gateway, settings=default_settings(space="ENG"))  # the current space is not assumed for a change
                self.assertEqual(result.code, 2)
                self.assertIn("never assumes the current space", result.err)
        self.assertEqual(run_cli("watch", "2002", "--space", "ENG", gateway=gateway).code, 2)
        self.assertEqual((gateway.watching, gateway.called("change_watch")), (set(), []))

    def test_what_is_not_there_is_not_found_and_nothing_is_written(self):
        gateway = fresh()
        self.assertEqual(run_cli("watch", "99999", gateway=gateway).code, 4)
        self.assertEqual(run_cli("watch", "--space", "NOSUCH", gateway=gateway).code, 4)
        self.assertEqual(run_cli("watch", "2002/../1", gateway=gateway).code, 1)
        self.assertEqual(gateway.called("change_watch"), [])

    def test_there_is_no_option_for_another_person(self):
        for option in ("--user", "--account-id", "--for", "--with-users"):
            with self.subTest(option=option):
                result = run_cli("watch", "2002", option, ACCOUNT, gateway=fresh())
                self.assertEqual((result.code, result.out), (2, ""))

    def test_no_person_is_in_the_answer(self):
        gateway = fresh()
        for argv in (("watch", "2002"), ("watch", "2002", "--json"), ("watch", "--space", "ENG", "--dry-run", "--json"), ("watch", "2002", "--remove", "--json")):
            result = run_cli(*argv, gateway=gateway)
            with self.subTest(argv=argv):
                self.assertNotIn(ACCOUNT, result.out + result.err)
                self.assertNotIn("Alex", result.out + result.err)

    def test_the_title_of_a_space_is_redacted_like_every_title(self):
        gateway = fresh()
        gateway.spaces["ENG"] = dataclasses.replace(gateway.spaces["ENG"], name="Team of alex@example.com")
        data = json.loads(run_cli("watch", "--space", "ENG", "--dry-run", "--json", gateway=gateway).out)
        self.assertEqual(data["target"]["title"], "Team of [email]")
        self.assertNotIn("alex@example.com", run_cli("watching", "--space", "ENG", gateway=gateway).out)


if __name__ == "__main__":
    unittest.main()
