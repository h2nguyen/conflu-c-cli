"""The commands `comments` and `comment` on the command line, with the in-memory Confluence: what they print, what they refuse, how they are described."""
import json
import shlex
import unittest

from conflu_c_cli.adapters.driving.cli.help import mcp_property_names, mcp_tool
from conflu_c_cli.adapters.driving.cli.parser import build_parser
from conflu_c_cli.adapters.driving.cli.registry import find_command
from conflu_c_cli.application.settings import Settings
from conflu_c_cli.domain.comments import author_ref
from conflu_c_cli.domain.errors import ConflictError
from conflu_c_cli.domain.model import Comment
from tests.support.cli import run_cli
from tests.support.fakes import ACCOUNT, FakeGateway, MemoryFiles, default_settings
from tests.support.fakes_comments import MENTION, OTHER, SAVED

PAGE = "2004"
SITE = default_settings().wiki_url
MINE = author_ref("secret-token", SITE, ACCOUNT)
THEIRS = author_ref("secret-token", SITE, OTHER)


def fresh() -> FakeGateway:
    gateway = FakeGateway()
    gateway.add_comment_fixtures()
    return gateway


def run(*argv, gateway=None, **options):
    return run_cli(*argv, gateway=gateway or fresh(), **options)


class DescriptionTest(unittest.TestCase):
    def test_what_a_reader_needs_to_choose_the_command_is_there(self):
        for name, group in (("comments", "Read"), ("comment", "Work on a page")):
            command = find_command(name)
            with self.subTest(command=name):
                self.assertEqual(command.group, group)
                self.assertTrue(command.when and command.output and command.json_output and command.examples and command.description)

    def test_the_reader_changes_nothing_and_the_writer_is_declared_for_an_agent(self):
        reader = find_command("comments")
        self.assertFalse(reader.writes or reader.destructive or reader.for_person or reader.local)
        writer = find_command("comment")
        self.assertTrue(writer.writes and writer.destructive)  # --edit replaces the text of a comment
        self.assertFalse(writer.idempotent or writer.for_person or writer.local)  # adding the same comment twice makes two
        self.assertTrue(any("--dry-run" in arg.names for arg in writer.args))

    def test_every_example_is_a_valid_command_line(self):
        for name in ("comments", "comment"):
            command = find_command(name)
            for example in command.examples:
                with self.subTest(example=example.command):
                    words = shlex.split(example.command)
                    self.assertEqual(words[:2], ["conflu", name])
                    build_parser(command).parse_args(words[2:])

    def test_an_argument_that_speaks_of_a_file_says_whether_it_is_one(self):
        """What `conflu mcp` needs to know: the file of `--file` is a path of this computer, the text and the ids are none."""
        arguments = {arg.names[0]: arg for arg in find_command("comment").args}
        self.assertEqual(arguments["--file"].path, "reads a file")
        for name in ("--text", "--get", "--edit", "--resolve", "--reopen", "--reply-to"):
            self.assertTrue(arguments[name].not_a_path, name)
        self.assertTrue(arguments["--force"].overwrites)
        for name in ("comments", "comment"):
            for arg in find_command(name).args:
                text = " ".join([*arg.names, arg.metavar, arg.help]).lower()
                with self.subTest(command=name, arg=arg.names[0]):
                    says = any(word in text for word in ("folder", "file", "path", "directory"))
                    self.assertTrue(not says or arg.not_a_path or arg.path or arg.at_file, f"{arg.names[0]} speaks of a file and says nothing about it")

    def test_the_tool_of_an_agent_names_distinct_properties_and_no_flag_of_its_own_in_the_text(self):
        for name in ("comments", "comment"):
            command = find_command(name)
            names = mcp_property_names(command)
            self.assertEqual(len(names), len(set(names.values())), name)
            tool = mcp_tool(command)
            text = tool["description"] + " ".join(prop["description"] for prop in tool["inputSchema"]["properties"].values())
            for arg in command.args:
                if not arg.positional and not arg.text_only:
                    with self.subTest(command=name, arg=arg.names[0]):
                        self.assertNotIn(f" {arg.names[0]} ", text + " ")
        self.assertEqual({"ifVersion", "ifUnchangedSince", "replyTo", "withUsers", "dryRun", "force"} - set(mcp_property_names(find_command("comment")).values()), set())

    def test_the_catalog_lists_the_new_options(self):
        catalog = run_cli("commands", "--json").json()["commands"]
        comment = next(item for item in catalog if item["name"] == "comment")
        listed = [arg["names"][0] for arg in comment["arguments"]]
        for option in ("--get", "--edit", "--resolve", "--reopen", "--if-version", "--if-unchanged-since", "--force", "--dry-run"):
            self.assertIn(option, listed)
        self.assertTrue(comment["changesData"])
        comments = next(item for item in catalog if item["name"] == "comments")
        for option in ("--since", "--last", "--resolution", "--select", "--list-format"):
            self.assertIn(option, [arg["names"][0] for arg in comments["arguments"]])

    def test_the_help_says_that_the_two_formats_are_two_options(self):
        text = run_cli("help", "comments").out
        self.assertIn("--list-format", text)
        self.assertIn("is how the list is printed", text)
        self.assertIn("STATE", text)  # the long list of states is not the label of the option


class ListTest(unittest.TestCase):
    def test_the_default_text_shows_who_wrote_a_comment_as_a_pseudonym_and_marks_your_own(self):
        out = run("comments", PAGE).out
        self.assertEqual(
            out.splitlines()[:5],
            [
                f"--- #4100 footer 2026-10-12T09:00:00.000Z  {THEIRS}",
                "Please review the decision.",
                f"    --- #4101 footer 2026-10-13T09:00:00.000Z (reply to #4100)  {MINE} (you)",
                "    Will do.",
                f"--- #4106 footer 2026-10-10T09:00:00.000Z  {MINE} (you)",
            ],
        )
        for hidden in ("Alex", "Example", ACCOUNT, OTHER, "alex@example.com"):
            self.assertNotIn(hidden, out)

    def test_with_users_the_pseudonym_gives_way_to_the_name(self):
        gateway = fresh()
        out = run("comments", PAGE, "--with-users", gateway=gateway).out
        self.assertIn("(reply to #4100)  Alex Example (you)", out)
        self.assertNotIn(MINE, out)
        self.assertIn("alex@example.com", out)

    def test_the_json_has_the_old_keys_and_the_new_ones(self):
        data = run("comments", PAGE, "--inline", "--json").json()
        self.assertEqual(set(data), {"pageId", "total", "count", "since", "comments"})
        self.assertEqual((data["pageId"], data["total"], data["count"], data["since"]), (PAGE, 8, 8, None))
        first = data["comments"][0]
        self.assertEqual(set(first), {"id", "kind", "updated", "parentId", "resolution", "author", "authorRef", "byMe", "body"})
        self.assertEqual((first["id"], first["author"], first["authorRef"], first["byMe"]), ("4100", None, THEIRS, False))
        mine = next(item for item in data["comments"] if item["id"] == "4101")
        self.assertEqual((mine["authorRef"], mine["byMe"], mine["parentId"]), (MINE, True, "4100"))
        inline = next(item for item in data["comments"] if item["id"] == "4105")
        self.assertEqual((inline["kind"], inline["resolution"]), ("inline", "reopened"))
        self.assertEqual(first["body"], {"format": "markdown", "value": "Please review the decision.", "dropped": []})

    def test_with_users_the_json_names_the_author_and_keeps_the_pseudonym(self):
        data = run("comments", PAGE, "--with-users", "--json").json()
        mine = next(item for item in data["comments"] if item["id"] == "4101")
        self.assertEqual(mine["author"], {"accountId": ACCOUNT, "displayName": "Alex Example", "email": "alex@example.com"})
        self.assertEqual(mine["authorRef"], MINE)

    def test_the_text_of_a_comment_is_in_the_format_asked_for_and_never_shows_people_by_default(self):
        data = run("comments", PAGE, "--format", "storage", "--json").json()
        text = next(item for item in data["comments"] if item["id"] == "4106")["body"]
        self.assertEqual(text["format"], "storage")
        self.assertNotIn(ACCOUNT, text["value"])
        self.assertIn('ri:account-id="hidden"', text["value"])

    def test_since_and_last_choose_among_the_comments_and_the_json_says_what_since_meant(self):
        data = run("comments", PAGE, "--inline", "--since", "2d", "--json").json()
        self.assertEqual([item["id"] for item in data["comments"]], ["4101", "4102", "4107"])
        self.assertEqual((data["total"], data["count"], data["since"]), (8, 3, "2026-10-13T08:00:00+00:00"))
        data = run("comments", PAGE, "--inline", "--last", "2", "--json").json()
        self.assertEqual([item["id"] for item in data["comments"]], ["4102", "4107"])
        self.assertEqual(run("comments", PAGE, "--inline", "--since", "2026-10-14", "--last", "1", "--json").json()["comments"][0]["id"], "4107")

    def test_a_resolution_lists_the_inline_conversations_in_that_state(self):
        for state, wanted in (("open", ["4102", "4107"]), ("resolved", ["4103"]), ("reopened", ["4105"]), ("dangling", ["4104"])):
            with self.subTest(state=state):
                data = run("comments", PAGE, "--resolution", state, "--json").json()
                self.assertEqual([item["id"] for item in data["comments"]], wanted)
        self.assertIn("--- #4102 inline [open]", run("comments", PAGE, "--resolution", "open").out)

    def test_an_empty_list_says_why(self):
        self.assertEqual(run("comments", "2003").out, "No comments.\n")
        self.assertEqual(run("comments", PAGE, "--since", "2027-01-01").out, "No comments match the options; the page has 3.\n")
        self.assertEqual(run("comments", PAGE, "--resolution", "dangling", "--since", "2027-01-01").out, "No comments match the options; the page has 1.\n")
        data = run("comments", PAGE, "--since", "2027-01-01", "--json").json()
        self.assertEqual((data["total"], data["count"], data["comments"]), (3, 0, []))

    def test_the_list_may_be_cut_to_some_keys_and_printed_as_a_table(self):
        out = run("comments", PAGE, "--inline", "--select", "id,authorRef,byMe", "--list-format", "tsv").out.splitlines()
        self.assertEqual(out[0], "id\tauthorRef\tbyMe")
        self.assertEqual(out[1], f"4100\t{THEIRS}\tfalse")
        self.assertEqual(out[2], f"4101\t{MINE}\ttrue")
        data = run("comments", PAGE, "--select", "id,byMe", "--json").json()
        self.assertEqual(data["comments"][0], {"id": "4100", "byMe": False})
        self.assertEqual(set(data), {"pageId", "total", "count", "since", "comments"})
        table = run("comments", PAGE, "--list-format", "md").out.splitlines()
        self.assertEqual(table[0], "| ID | KIND | UPDATED | PARENT | RESOLUTION | TEXT |")

    def test_format_is_the_format_of_the_text_and_does_not_print_a_table(self):
        out = run("comments", PAGE, "--format", "text").out
        self.assertTrue(out.startswith("--- #4100 footer"))

    def test_options_that_do_not_make_sense_are_usage_errors(self):
        for argv, hint in (
            (("--since", "yesterday"), "2d, 12h, 1w"),
            (("--since", ""), "2d, 12h, 1w"),
            (("--last", "0"), "--last 3"),
            (("--last", "-2"), "--last 3"),
            (("--last", "many"), "conflu help comments"),
            (("--resolution", "closed"), "conflu help comments"),
        ):
            with self.subTest(argv=argv):
                result = run("comments", PAGE, *argv)
                self.assertEqual(result.code, 2, result.err)
                self.assertIn(hint, result.err)
                self.assertEqual(result.out, "")

    def test_with_users_is_refused_under_the_hide_users_policy_and_the_pseudonym_is_not(self):
        settings = default_settings(hide_users=True)
        refused = run("comments", PAGE, "--with-users", settings=settings)
        self.assertEqual(refused.code, 1)
        self.assertIn("CONFLUENCE_HIDE_USERS", refused.err)
        allowed = run("comments", PAGE, "--json", settings=settings)
        self.assertEqual(allowed.code, 0)
        self.assertEqual({item["author"] for item in map(lambda c: dict(c, author=str(c["author"])), allowed.json()["comments"])}, {"None"})
        self.assertEqual(allowed.json()["comments"][0]["authorRef"], THEIRS)

    def test_without_a_token_the_pseudonym_is_null_and_nothing_else_changes(self):
        data = run("comments", PAGE, "--json", settings=Settings(base_url=default_settings().base_url, email="user@example.com")).json()
        self.assertEqual({item["authorRef"] for item in data["comments"]}, {None})
        self.assertEqual([item["byMe"] for item in data["comments"]], [False, True, True])
        self.assertNotIn(" a-", run("comments", PAGE, settings=Settings(base_url=default_settings().base_url, email="user@example.com")).out)

    def test_a_page_that_does_not_exist_is_exit_code_4_and_a_bad_page_id_is_exit_code_1(self):
        self.assertEqual(run("comments", "999").code, 4)
        self.assertEqual(run("comments", "not-a-page").code, 1)

    def test_a_failing_lookup_of_the_user_does_not_fail_the_list(self):
        from conflu_c_cli.domain.errors import UnavailableError

        gateway = fresh()
        gateway.errors["current_user"] = UnavailableError("Confluence is down.")
        result = run("comments", PAGE, "--json", gateway=gateway)
        self.assertEqual(result.code, 0)
        self.assertEqual({item["byMe"] for item in result.json()["comments"]}, {None})
        self.assertIn("Could not tell which comments are yours", result.err)

    def test_the_comments_of_a_page_as_the_page_command_shows_them_are_as_they_were(self):
        data = run_cli("page", "2002", "--comments", "--json").json()
        self.assertEqual(set(data["comments"][0]), {"id", "kind", "updated", "parentId", "resolution", "author", "body"})
        out = run_cli("page", "2002", "--comments").out
        self.assertIn("--- #4001 footer 2026-10-02T10:00:00.000Z\n", out)


class GetTest(unittest.TestCase):
    def test_one_comment_with_its_version_and_whose_it_is(self):
        out = run("comment", PAGE, "--get", "4102").out
        self.assertEqual(out, f"--- #4102 inline [open] 2026-10-14T09:00:00.000Z (version 1)  {MINE} (you)\nIs this still true?\n")

    def test_a_reply_says_what_it_answers(self):
        out = run("comment", PAGE, "--get", "4101").out
        self.assertEqual(out.splitlines()[0], f"    --- #4101 footer 2026-10-13T09:00:00.000Z (reply to #4100) (version 3)  {MINE} (you)")

    def test_the_json(self):
        data = run("comment", PAGE, "--get", "4105", "--json").json()
        self.assertEqual(set(data), {"pageId", "id", "kind", "updated", "version", "parentId", "resolution", "author", "authorRef", "byMe", "body"})
        self.assertEqual((data["pageId"], data["id"], data["kind"], data["version"], data["resolution"], data["parentId"]), (PAGE, "4105", "inline", 4, "reopened", None))
        self.assertEqual((data["author"], data["authorRef"], data["byMe"]), (None, MINE, True))

    def test_the_author_only_with_users(self):
        data = run("comment", PAGE, "--get", "4101", "--with-users", "--json").json()
        self.assertEqual(data["author"]["displayName"], "Alex Example")
        self.assertIn("Alex Example (you)", run("comment", PAGE, "--get", "4101", "--with-users").out)
        self.assertIsNone(run("comment", PAGE, "--get", "4101", "--json").json()["author"])

    def test_the_format_of_the_text(self):
        for fmt in ("markdown", "text", "storage"):
            with self.subTest(format=fmt):
                data = run("comment", PAGE, "--get", "4106", "--format", fmt, "--json").json()
                self.assertEqual(data["body"]["format"], fmt)
                self.assertNotIn(ACCOUNT, data["body"]["value"])
        self.assertEqual(run("comment", PAGE, "--get", "4106", "--format", "storage", "--with-users", "--json").json()["body"]["value"].count(ACCOUNT), 1)

    def test_a_comment_that_is_not_on_the_page_or_does_not_exist_is_exit_code_4(self):
        for page, comment_id in (("2002", "4102"), (PAGE, "9999")):
            result = run("comment", page, "--get", comment_id)
            self.assertEqual(result.code, 4)
            self.assertIn(f"No comment {comment_id} on page {page}.", result.err)
        error = run("comment", PAGE, "--get", "9999", "--json").error()
        self.assertEqual((error["code"], error["exitCode"], error["details"]["commentId"]), ("NOT_FOUND", 4, "9999"))

    def test_an_id_that_is_no_number_is_exit_code_1_before_any_request(self):
        gateway = fresh()
        result = run("comment", PAGE, "--get", "4102/../4100", gateway=gateway)
        self.assertEqual(result.code, 1)
        self.assertIn("A comment id is a number", result.err)
        self.assertEqual(gateway.calls, [])

    def test_with_users_is_refused_under_the_policy(self):
        self.assertEqual(run("comment", PAGE, "--get", "4101", "--with-users", settings=default_settings(hide_users=True)).code, 1)


class EditTest(unittest.TestCase):
    def test_the_text_of_a_comment_is_replaced(self):
        gateway = fresh()
        result = run("comment", PAGE, "--edit", "4101", "--text", "Done.", gateway=gateway)
        self.assertEqual((result.code, result.out), (0, "Edited comment 4101 of page 2004 (version 3 -> 4)\n"))
        self.assertEqual(gateway.called("update_comment")[0][1:3], ("4101", "footer"))
        self.assertEqual(gateway.comments[PAGE][1].body, "<p>Done.</p>")
        self.assertEqual(run("comment", PAGE, "--get", "4101", gateway=gateway).out.splitlines()[1], "    Done.")  # an answer is indented below the comment it answers

    def test_the_dry_run_shows_the_diff_and_the_payload_and_sends_nothing(self):
        gateway = fresh()
        out = run("comment", PAGE, "--edit", "4101", "--text", "Done.", "--dry-run", gateway=gateway).out
        self.assertIn("Dry run: comment 4101 of page 2004 would go from version 3 to 4; nothing was sent", out)
        self.assertIn("--- current\n+++ new", out)
        self.assertIn("-Will do.\n+Done.", out)
        self.assertIn("Would send:", out)
        self.assertIn('"number": 4', out)
        self.assertIn('"value": "<p>Done.</p>"', out)
        self.assertEqual(gateway.called("update_comment"), [])

    def test_the_json_of_a_dry_run_and_of_the_real_run_carry_the_same_payload(self):
        gateway = fresh()
        preview = run("comment", PAGE, "--edit", "4102", "--text", "Changed.", "--dry-run", "--json", gateway=gateway).json()
        real = run("comment", PAGE, "--edit", "4102", "--text", "Changed.", "--json", gateway=gateway).json()
        self.assertEqual(set(real), {"action", "dryRun", "pageId", "commentId", "kind", "versionFrom", "versionTo", "updated", "resolution", "byMe", "diff", "lost", "warnings", "payload", "payloadRedacted"})
        self.assertEqual((preview["action"], preview["dryRun"], real["dryRun"]), ("updated", True, False))
        self.assertEqual(preview["payload"], real["payload"])
        self.assertEqual(real["payload"], {"version": {"number": 2}, "body": {"representation": "storage", "value": "<p>Changed.</p>"}, "resolved": False})
        self.assertEqual((real["versionFrom"], real["versionTo"], real["updated"], real["payloadRedacted"]), (1, 2, SAVED, False))
        self.assertEqual((preview["byMe"], real["byMe"]), (True, None))
        self.assertIn("-Is this still true?", real["diff"])
        self.assertEqual(gateway.called("update_comment")[0][3], real["payload"])

    def test_a_text_that_is_the_comment_s_own_is_unchanged_and_sends_nothing(self):
        gateway = fresh()
        result = run("comment", PAGE, "--edit", "4101", "--text", "Will do.", gateway=gateway)
        self.assertEqual((result.code, result.out), (0, "Comment 4101 of page 2004 has this text already; nothing was sent\n"))
        data = run("comment", PAGE, "--edit", "4101", "--text", "Will do.", "--json", "--dry-run", gateway=gateway).json()
        self.assertEqual((data["action"], data["payload"], data["versionFrom"], data["versionTo"], data["diff"]), ("unchanged", None, 3, 3, None))
        self.assertEqual(gateway.called("update_comment"), [])

    def test_the_text_may_come_from_a_file_or_from_standard_input(self):
        gateway = fresh()
        files = MemoryFiles({"new.md": "From a file.\n"})
        self.assertEqual(run("comment", PAGE, "--edit", "4101", "--file", "new.md", gateway=gateway, files=files).code, 0)
        self.assertEqual(gateway.comments[PAGE][1].body, "<p>From a file.</p>")
        self.assertEqual(run("comment", PAGE, "--edit", "4101", "--file", "-", gateway=gateway, stdin="From a pipe.\n").code, 0)
        self.assertEqual(gateway.comments[PAGE][1].body, "<p>From a pipe.</p>")

    def test_storage_format_is_sent_as_it_is(self):
        gateway = fresh()
        run("comment", PAGE, "--edit", "4106", "--format", "storage", "--text", f"<p>Ask {MENTION}.</p>", gateway=gateway)
        self.assertEqual(next(item.body for item in gateway.comments[PAGE] if item.id == "4106"), f"<p>Ask {MENTION}.</p>")

    def test_what_a_reading_put_in_place_of_an_address_is_refused_with_exit_code_1(self):
        gateway = fresh()
        for text in ("Write to [email].", "See [personal link]."):
            result = run("comment", PAGE, "--edit", "4101", "--text", text, gateway=gateway)
            self.assertEqual(result.code, 1)
            self.assertIn("overwrite the real one", result.err)
        self.assertEqual(gateway.called("update_comment"), [])
        self.assertEqual(run("comment", PAGE, "--edit", "4101", "--text", "Write to [email].", "--dry-run", gateway=gateway).code, 1)

    def test_replacing_a_comment_with_a_mention_by_markdown_needs_force(self):
        gateway = fresh()
        refused = run("comment", PAGE, "--edit", "4106", "--text", "Plain words.", gateway=gateway)
        self.assertEqual(refused.code, 1)
        self.assertIn("--force", refused.err)
        self.assertEqual(gateway.called("update_comment"), [])
        data = run("comment", PAGE, "--edit", "4106", "--text", "Plain words.", "--force", "--json", gateway=gateway).json()
        self.assertEqual(data["lost"], ["mention", "redacted-text"])
        text = run("comment", PAGE, "--edit", "4106", "--text", "Plain words, again.", "--force", "--dry-run", gateway=fresh()).out
        self.assertIn("This replaces what Markdown cannot say and drops: mention, redacted-text.", text)

    def test_the_real_run_warns_about_what_was_lost(self):
        out = run("comment", PAGE, "--edit", "4106", "--text", "Plain words.", "--force").out
        self.assertIn("Warning: dropped what Markdown cannot say: mention, redacted-text.", out)

    def test_an_empty_text_is_exit_code_1_and_no_text_at_all_is_a_usage_error(self):
        empty = run("comment", PAGE, "--edit", "4101", "--text", "  ")
        self.assertEqual(empty.code, 1)
        self.assertIn("neither deletes a comment nor empties one", empty.err)
        none = run("comment", PAGE, "--edit", "4101")
        self.assertEqual(none.code, 2)
        self.assertIn("--edit needs the new text", none.err)

    def test_somebody_else_s_comment_is_refused_by_confluence_with_exit_code_5(self):
        result = run("comment", PAGE, "--edit", "4100", "--text", "Mine now.")
        self.assertEqual(result.code, 5)
        self.assertIn("HTTP 403", result.err)
        self.assertIn("only their own comments", result.err)
        error = run("comment", PAGE, "--edit", "4100", "--text", "Mine now.", "--json").error()
        self.assertEqual((error["code"], error["exitCode"], error["details"]["status"]), ("AUTH", 5, 403))

    def test_the_dry_run_warns_about_somebody_else_s_comment_before_anything_is_sent(self):
        gateway = fresh()
        result = run("comment", PAGE, "--edit", "4100", "--text", "Mine now.", "--dry-run", gateway=gateway)
        self.assertEqual(result.code, 0)
        self.assertIn("WARNING: Somebody else wrote this comment", result.err)
        data = run("comment", PAGE, "--edit", "4100", "--text", "Mine now.", "--dry-run", "--json", gateway=gateway).json()
        self.assertEqual((data["byMe"], len(data["warnings"])), (False, 1))
        self.assertEqual(gateway.called("update_comment"), [])

    def test_a_comment_that_changed_is_a_conflict_with_exit_code_3_and_nothing_is_written(self):
        gateway = fresh()
        for option, value in (("--if-version", "2"), ("--if-unchanged-since", "2026-10-12T00:00:00Z")):
            with self.subTest(option=option):
                result = run("comment", PAGE, "--edit", "4101", "--text", "Done.", option, value, gateway=gateway)
                self.assertEqual(result.code, 3, result.err)
                self.assertIn("conflu comment 2004 --get 4101", result.err)
        error = run("comment", PAGE, "--edit", "4101", "--text", "Done.", "--if-version", "2", "--json", gateway=gateway).error()
        self.assertEqual((error["code"], error["details"]), ("CONFLICT", {"pageId": PAGE, "commentId": "4101", "version": 3, "expected": 2}))
        self.assertEqual(gateway.called("update_comment"), [])

    def test_a_guard_that_holds_lets_the_change_through(self):
        gateway = fresh()
        result = run("comment", PAGE, "--edit", "4101", "--text", "Done.", "--if-version", "3", "--if-unchanged-since", "2026-10-13T09:00:00Z", gateway=gateway)
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(len(gateway.called("update_comment")), 1)

    def test_a_conflict_that_confluence_reports_is_exit_code_3_as_well(self):
        gateway = fresh()
        gateway.errors["update_comment"] = ConflictError("Confluence reports a conflict (HTTP 409): Version conflict.", details={"status": 409})
        result = run("comment", PAGE, "--edit", "4101", "--text", "Done.", gateway=gateway)
        self.assertEqual(result.code, 3)
        self.assertIn("Read it again with `conflu comment 2004 --get 4101`", result.err)

    def test_the_guards_must_be_valid(self):
        self.assertEqual(run("comment", PAGE, "--edit", "4101", "--text", "Done.", "--if-version", "0").code, 2)
        self.assertEqual(run("comment", PAGE, "--edit", "4101", "--text", "Done.", "--if-version", "x").code, 2)
        self.assertEqual(run("comment", PAGE, "--edit", "4101", "--text", "Done.", "--if-unchanged-since", "last week").code, 1)
        gateway = fresh()
        for argv in (("--edit", "4101", "--text", "Done."), ("--resolve", "4102")):
            result = run("comment", PAGE, *argv, "--if-unchanged-since", "", gateway=gateway)  # a guard that is empty must not mean "no guard"
            self.assertEqual(result.code, 1)
            self.assertIn("--if-unchanged-since is empty", result.err)
        self.assertEqual(gateway.calls, [])

    def test_a_dangling_comment_is_exit_code_1_with_the_way_to_add_a_new_one(self):
        result = run("comment", PAGE, "--edit", "4104", "--text", "Changed.")
        self.assertEqual(result.code, 1)
        self.assertIn("dangling", result.err)
        self.assertIn("conflu comment 2004 --text", result.err)

    def test_a_comment_of_another_page_is_exit_code_4(self):
        self.assertEqual(run("comment", "2002", "--edit", "4102", "--text", "Done.").code, 4)

    def test_hostile_text_is_stored_as_text(self):
        gateway = fresh()
        hostile = "</p><script>alert(1)</script><ac:structured-macro ac:name=\"html\"/> & ]]> <!-- x -->"
        self.assertEqual(run("comment", PAGE, "--edit", "4101", "--text", hostile, gateway=gateway).code, 0)
        body = gateway.comments[PAGE][1].body
        self.assertNotIn("<script", body)
        self.assertNotIn("<ac:structured-macro", body)
        self.assertNotIn("<!--", body)
        self.assertIn("&lt;script&gt;", body)


class ResolveTest(unittest.TestCase):
    def test_an_open_comment_is_resolved_and_a_resolved_one_reopened(self):
        gateway = fresh()
        self.assertEqual(run("comment", PAGE, "--resolve", "4102", gateway=gateway).out, "Resolved comment 4102 of page 2004 (version 1 -> 2)\n")
        self.assertEqual(run("comment", PAGE, "--reopen", "4103", gateway=gateway).out, "Reopened comment 4103 of page 2004 (version 2 -> 3)\n")
        states = {comment.id: comment.resolution for comment in gateway.comments[PAGE]}
        self.assertEqual((states["4102"], states["4103"]), ("resolved", "reopened"))

    def test_the_comment_keeps_its_text(self):
        gateway = fresh()
        run("comment", PAGE, "--resolve", "4102", gateway=gateway)
        self.assertEqual(gateway.called("update_comment")[0][3]["body"]["value"], "<p>Is this still true?</p>")
        self.assertEqual(gateway.comments[PAGE][2].body, "<p>Is this still true?</p>")

    def test_a_comment_that_is_in_the_state_is_unchanged_and_nothing_is_sent(self):
        gateway = fresh()
        self.assertEqual(run("comment", PAGE, "--resolve", "4103", gateway=gateway).out, "Comment 4103 of page 2004 is resolved already; nothing was sent\n")
        self.assertEqual(run("comment", PAGE, "--reopen", "4102", gateway=gateway).out, "Comment 4102 of page 2004 is open already; nothing was sent\n")
        self.assertEqual(gateway.called("update_comment"), [])

    def test_the_dry_run_sends_nothing(self):
        gateway = fresh()
        out = run("comment", PAGE, "--resolve", "4102", "--dry-run", gateway=gateway).out
        self.assertIn("Dry run: comment 4102 of page 2004 would be resolved (version 1 -> 2); nothing was sent", out)
        self.assertIn('"resolved": true', out)
        self.assertEqual(gateway.called("update_comment"), [])

    def test_the_json(self):
        data = run("comment", PAGE, "--reopen", "4103", "--json").json()
        self.assertEqual((data["action"], data["kind"], data["versionFrom"], data["versionTo"], data["resolution"], data["diff"], data["byMe"]), ("reopened", "inline", 2, 3, "reopened", None, None))
        self.assertEqual(data["payload"], {"version": {"number": 3}, "body": {"representation": "storage", "value": "<p>Fixed already.</p>"}, "resolved": False})
        self.assertFalse(data["payloadRedacted"])

    def test_the_text_that_goes_back_is_shown_without_the_people_in_it_and_the_json_says_so(self):
        gateway = fresh()
        body = f"<p>Ask {MENTION} or write to alex@example.com.</p>"
        gateway.comments[PAGE].append(Comment("4191", "inline", "2026-10-11T09:00:00.000Z", body, 1, gateway.user, "", "open"))
        preview = run("comment", PAGE, "--resolve", "4191", "--dry-run", "--json", gateway=gateway).json()
        self.assertTrue(preview["payloadRedacted"])
        shown = preview["payload"]["body"]["value"]
        self.assertNotIn(ACCOUNT, shown)
        self.assertNotIn("alex@example.com", shown)
        self.assertIn('ri:account-id="hidden"', shown)
        text = run("comment", PAGE, "--resolve", "4191", "--dry-run", gateway=gateway).out
        self.assertNotIn(ACCOUNT, text)
        self.assertIn("shown without the people and addresses in it", text)
        run("comment", PAGE, "--resolve", "4191", gateway=gateway)
        self.assertEqual(gateway.called("update_comment")[0][3]["body"]["value"], body)  # what is sent is the comment as it is

    def test_with_users_the_request_is_shown_as_it_is_and_the_policy_refuses_that(self):
        gateway = fresh()
        body = f"<p>Ask {MENTION} or write to alex@example.com.</p>"
        gateway.comments[PAGE].append(Comment("4191", "inline", "2026-10-11T09:00:00.000Z", body, 1, gateway.user, "", "open"))
        data = run("comment", PAGE, "--resolve", "4191", "--dry-run", "--with-users", "--json", gateway=gateway).json()
        self.assertFalse(data["payloadRedacted"])
        self.assertEqual(data["payload"]["body"]["value"], body)
        text = run("comment", PAGE, "--reopen", "4103", "--dry-run", "--with-users", gateway=gateway).out
        self.assertNotIn("shown without the people", text)
        refused_gateway = fresh()
        refused = run("comment", PAGE, "--resolve", "4102", "--with-users", settings=default_settings(hide_users=True), gateway=refused_gateway)
        self.assertEqual(refused.code, 1)
        self.assertIn("CONFLUENCE_HIDE_USERS", refused.err)
        self.assertEqual(refused_gateway.calls, [])

    def test_a_footer_comment_is_a_usage_error_with_the_way_to_answer_it(self):
        result = run("comment", PAGE, "--resolve", "4100")
        self.assertEqual(result.code, 2)
        self.assertIn("only an inline comment can be resolved", result.err)
        self.assertIn("--reply-to 4100", result.err)
        self.assertEqual(run("comment", PAGE, "--reopen", "4100").code, 2)

    def test_a_dangling_comment_is_exit_code_1(self):
        self.assertEqual(run("comment", PAGE, "--resolve", "4104").code, 1)
        self.assertEqual(run("comment", PAGE, "--reopen", "4104").code, 1)

    def test_a_comment_of_another_page_or_none_is_exit_code_4(self):
        self.assertEqual(run("comment", "2002", "--resolve", "4102").code, 4)
        self.assertEqual(run("comment", PAGE, "--resolve", "9999").code, 4)

    def test_the_guards_work_for_a_resolution_too(self):
        gateway = fresh()
        self.assertEqual(run("comment", PAGE, "--resolve", "4102", "--if-version", "2", gateway=gateway).code, 3)
        self.assertEqual(run("comment", PAGE, "--resolve", "4102", "--if-unchanged-since", "2026-10-13T00:00:00Z", gateway=gateway).code, 3)
        self.assertEqual(gateway.called("update_comment"), [])
        self.assertEqual(run("comment", PAGE, "--resolve", "4102", "--if-version", "1", gateway=gateway).code, 0)

    def test_somebody_else_s_inline_comment_is_resolved_with_its_own_text_unchanged(self):
        self.assertEqual(run("comment", PAGE, "--resolve", "4107").code, 0)


class ModeTest(unittest.TestCase):
    """The modes exclude each other, and an option that belongs to some of them is refused for the others: a usage error that names the clash."""

    def refused(self, *argv, says):
        gateway = fresh()
        result = run("comment", PAGE, *argv, gateway=gateway)
        self.assertEqual(result.code, 2, result.err)
        self.assertIn(says, result.err)
        self.assertEqual(gateway.calls, [])  # no request was made
        self.assertEqual(result.out, "")

    def test_the_modes_cannot_be_combined(self):
        self.refused("--get", "4101", "--edit", "4102", "--text", "x", says="--get and --edit cannot be combined")
        self.refused("--resolve", "4102", "--reopen", "4103", says="--resolve and --reopen cannot be combined")
        self.refused("--edit", "4101", "--resolve", "4102", "--text", "x", says="--edit and --resolve cannot be combined")
        self.refused("--get", "4101", "--edit", "4102", "--resolve", "4103", "--reopen", "4105", says="--get and --edit and --resolve and --reopen cannot be combined")

    def test_a_mode_that_shows_or_resolves_takes_no_text(self):
        for mode in ("--get", "--resolve", "--reopen"):
            self.refused(mode, "4102", "--text", "x", says=f"{mode} cannot be combined with --text or --file")
            self.refused(mode, "4102", "--file", "x.md", says=f"{mode} cannot be combined with --text or --file")

    def test_adding_and_editing_need_a_text(self):
        self.refused(says="Nothing to do.")
        self.refused("--edit", "4101", says="--edit needs the new text.")
        self.refused("--reply-to", "4100", says="Nothing to do.")

    def test_a_text_and_a_file_are_two_ways_to_say_the_same_thing(self):
        self.refused("--text", "x", "--file", "x.md", says="Use either the comment text or its file, not both.")
        self.refused("--edit", "4101", "--text", "x", "--file", "x.md", says="Use either the comment text or its file, not both.")

    def test_an_option_that_belongs_to_another_mode_is_refused(self):
        self.refused("--get", "4101", "--reply-to", "4100", says="--reply-to applies to adding a comment")
        self.refused("--edit", "4101", "--text", "x", "--reply-to", "4100", says="--reply-to applies to adding a comment")
        self.refused("--edit", "4101", "--text", "x", "--with-users", says="--with-users applies to --get, --resolve and --reopen")
        self.refused("--text", "x", "--with-users", says="--with-users applies to --get, --resolve and --reopen")
        self.refused("--get", "4101", "--dry-run", says="--dry-run applies to adding a comment, --edit, --resolve and --reopen")
        self.refused("--text", "x", "--if-version", "1", says="--if-version applies to --edit, --resolve and --reopen")
        self.refused("--get", "4101", "--if-unchanged-since", "2026-10-13T00:00:00Z", says="--if-unchanged-since applies to --edit, --resolve and --reopen")
        self.refused("--resolve", "4102", "--force", says="--force applies to --edit")
        self.refused("--text", "x", "--force", says="--force applies to --edit")
        self.refused("--resolve", "4102", "--format", "storage", says="--format applies to adding a comment, --edit and --get")

    def test_the_text_format_shows_a_comment_and_cannot_write_one(self):
        self.refused("--text", "x", "--format", "text", says="--format text shows a comment")
        self.refused("--edit", "4101", "--text", "x", "--format", "text", says="--format text shows a comment")

    def test_each_refusal_says_what_to_do(self):
        result = run("comment", PAGE, "--get", "4101", "--reply-to", "4100")
        self.assertIn("Leave --reply-to out, or use adding a comment.", result.err)
        self.assertIn("--get ID to read one", run("comment", PAGE).err)


class EmptyOptionTest(unittest.TestCase):
    """An option that is given with an empty value (`--reply-to "$ID"` with an empty variable) is an error that names the option, never "not given":
    nothing is sent and nothing is read, also in a dry run. A comment of its own is what an absent `--reply-to` means, and an empty one must not be that."""

    def refused(self, command, *argv, option, code):
        gateway = fresh()
        result = run(command, PAGE, *argv, gateway=gateway)
        self.assertEqual(result.code, code, result.err)
        self.assertIn(option, result.err.splitlines()[0])  # the message itself names it, not only the hint
        self.assertEqual(result.out, "")
        self.assertEqual(gateway.calls, [])
        return result

    def test_reply_to(self):
        self.refused("comment", "--text", "hi", "--reply-to", "", option="--reply-to", code=1)
        self.refused("comment", "--text", "hi", "--reply-to", "", "--dry-run", option="--reply-to", code=1)
        self.refused("comment", "--text", "hi", "--reply-to", "  ", option="--reply-to", code=1)
        error = run("comment", PAGE, "--text", "hi", "--reply-to", "", "--json", gateway=fresh()).error()
        self.assertEqual((error["code"], error["exitCode"]), ("INVALID", 1))
        self.assertIn("--reply-to", error["message"])
        gateway = fresh()
        self.assertEqual(run("comment", PAGE, "--text", "hi", gateway=gateway).code, 0)  # not given: a comment of its own
        self.assertNotIn("parentCommentId", gateway.called("add_comment")[0][1])

    def test_get(self):
        self.refused("comment", "--get", "", option="--get", code=1)
        self.refused("comment", "--get", "", "--json", option="--get", code=1)

    def test_edit(self):
        self.refused("comment", "--edit", "", "--text", "x", option="--edit", code=1)
        self.refused("comment", "--edit", "", "--text", "x", "--dry-run", option="--edit", code=1)

    def test_resolve(self):
        self.refused("comment", "--resolve", "", option="--resolve", code=1)
        self.refused("comment", "--resolve", "", "--dry-run", option="--resolve", code=1)

    def test_reopen(self):
        self.refused("comment", "--reopen", "", option="--reopen", code=1)
        self.refused("comment", "--reopen", "", "--dry-run", option="--reopen", code=1)

    def test_since(self):
        self.refused("comments", "--since", "", option="--since", code=2)
        self.refused("comments", "--since", "  ", "--inline", option="--since", code=2)

    def test_resolution(self):
        self.refused("comments", "--resolution", "", option="--resolution", code=2)
        self.refused("comments", "--resolution", "", "--inline", option="--resolution", code=2)

    def test_if_unchanged_since(self):
        self.refused("comment", "--edit", "4101", "--text", "x", "--if-unchanged-since", "", option="--if-unchanged-since", code=1)
        self.refused("comment", "--resolve", "4102", "--if-unchanged-since", "", "--dry-run", option="--if-unchanged-since", code=1)

    def test_if_version(self):
        self.refused("comment", "--edit", "4101", "--text", "x", "--if-version", "", option="--if-version", code=2)

    def test_text(self):
        for argv in (("--text", ""), ("--text", "  ")):
            gateway = fresh()
            result = run("comment", PAGE, *argv, gateway=gateway)
            self.assertEqual(result.code, 1)
            self.assertIn("The comment is empty.", result.err)
            self.assertIn("--text", result.err)  # the hint names the options that give the text
            self.assertEqual(gateway.calls, [])
        gateway = fresh()
        result = run("comment", PAGE, "--edit", "4101", "--text", "", gateway=gateway)
        self.assertEqual(result.code, 1)
        self.assertIn("The new text of the comment is empty.", result.err)
        self.assertEqual(gateway.calls, [])

    def test_file(self):
        self.refused("comment", "--file", "", option="--file", code=1)
        self.refused("comment", "--edit", "4101", "--file", "", option="--file", code=1)
        self.refused("comment", "--edit", "4101", "--file", "  ", "--dry-run", option="--file", code=1)

    def test_every_other_option_of_the_two_commands_that_takes_a_value_refuses_an_empty_one(self):
        for command, option in (("comments", "--last"), ("comments", "--list-format"), ("comments", "--format"), ("comment", "--format")):
            argv = ("--get", "4101") if command == "comment" else ()
            with self.subTest(option=option):
                self.refused(command, *argv, option, "", option=option, code=2)


class AddTest(unittest.TestCase):
    """Adding a comment works as before: the modes did not change it."""

    def test_a_comment_is_added_and_an_answer_names_its_parent(self):
        gateway = FakeGateway()
        out = run_cli("comment", "2002", "--text", "Reviewed.", "--reply-to", "4001", gateway=gateway).out
        self.assertEqual(out, "Commented on page 2002 (comment 20001)\n")
        self.assertEqual(gateway.called("add_comment")[0][1]["parentCommentId"], "4001")

    def test_the_dry_run_checks_the_page_and_sends_nothing(self):
        gateway = FakeGateway()
        out = run_cli("comment", "2002", "--text", "Reviewed.", "--dry-run", gateway=gateway).out
        self.assertIn("Dry run: page 2002 exists; nothing was sent", out)
        self.assertEqual(gateway.called("add_comment"), [])

    def test_the_json_has_the_keys_it_had(self):
        data = run_cli("comment", "2002", "--text", "Reviewed.", "--json").json()
        self.assertEqual(set(data), {"pageId", "dryRun", "commentId", "payload"})
        self.assertEqual(json.dumps(data["payload"], sort_keys=True), json.dumps({"pageId": "2002", "body": {"representation": "storage", "value": "<p>Reviewed.</p>"}}, sort_keys=True))

    def test_a_dry_run_names_the_changes_only_where_the_text_is_added(self):
        self.assertEqual(run_cli("comment", "2002", "--text", "x", "--dry-run", "--json").json()["commentId"], None)


if __name__ == "__main__":
    unittest.main()
