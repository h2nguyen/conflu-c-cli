"""The commands of the blog post area on the command line, with the in-memory Confluence: what they print, what they refuse, how they are described."""
import json
import unittest

from conflu_c_cli.adapters.driving.cli.registry import all_commands, find_command
from conflu_c_cli.adapters.driving.cli.spec import READS_FILE
from conflu_c_cli.domain.errors import UnavailableError
from tests.support.cli import run_cli
from tests.support.fakes import ACCOUNT, BASE, FakeGateway, MemoryFiles, default_settings

COMMANDS = ("blogposts", "blogpost", "blogpost-create", "blogpost-update")
ROW_KEYS = ["id", "title", "status", "spaceId", "version", "created", "updated", "url"]


def roomy():
    """The fake hands out two at a time; here a whole list fits in one piece."""
    gateway = FakeGateway()
    gateway.page_cap = 100
    return gateway


class DescriptionTest(unittest.TestCase):
    def test_the_commands_are_in_the_blog_post_group_and_say_what_they_do(self):
        self.assertEqual({command.name for command in all_commands() if command.group == "Blog posts"}, set(COMMANDS))
        for name in COMMANDS:
            command = find_command(name)
            with self.subTest(command=name):
                self.assertTrue(command.when and command.output and command.json_output and command.examples and command.description)

    def test_the_readers_change_nothing_and_the_writers_say_what_they_do_to_what_exists(self):
        for name in ("blogposts", "blogpost"):
            command = find_command(name)
            self.assertFalse(command.writes or command.destructive or command.for_person or command.local, name)
        create, update = find_command("blogpost-create"), find_command("blogpost-update")
        self.assertTrue(create.writes and not create.destructive and not create.idempotent)  # another blog post each time, and nothing is replaced
        self.assertTrue(update.writes and update.destructive and not update.idempotent)  # it replaces a body; --append twice appends twice
        for command in (create, update):
            self.assertTrue(any("--dry-run" in arg.names for arg in command.args), command.name)

    def test_what_names_a_file_says_so_and_what_only_speaks_of_one_says_it_is_none(self):
        for name in ("blogpost-create", "blogpost-update"):
            args = {arg.names[0]: arg for arg in find_command(name).args}
            self.assertEqual(args["--file"].path, READS_FILE, name)
            self.assertTrue(args["--body"].not_a_path, name)
        self.assertTrue(next(arg for arg in find_command("blogpost-update").args if arg.names[0] == "--force").overwrites)
        for name in COMMANDS:
            for arg in find_command(name).args:
                if arg.kind in ("str", "list", "words", "repeat"):
                    text = " ".join([*arg.names, arg.metavar, arg.help]).lower()
                    says = any(word in text.replace("--file", "") for word in (" file", "path", "directory", "folder"))
                    with self.subTest(command=name, arg=arg.names[0]):
                        self.assertTrue(not says or arg.path or arg.at_file or arg.not_a_path, f"{arg.names[0]} of {name} speaks of a file or a path and says nothing")

    def test_the_update_can_show_people_and_the_others_cannot_name_any(self):
        self.assertIn("--with-users", [arg.names[0] for arg in find_command("blogpost-update").args])
        self.assertIn("--with-users", [arg.names[0] for arg in find_command("blogpost").args])
        for name in ("blogposts", "blogpost-create"):
            self.assertNotIn("--with-users", [arg.names[0] for arg in find_command(name).args], name)

    def test_the_catalog_lists_them_with_their_options(self):
        catalog = {item["name"]: item for item in run_cli("commands", "--json").json()["commands"]}
        self.assertEqual([arg["names"][0] for arg in catalog["blogposts"]["arguments"]][:5], ["--space", "--title", "--status", "--sort", "--desc"])
        self.assertTrue(catalog["blogpost-create"]["changesData"] and catalog["blogpost-update"]["changesData"])
        self.assertFalse(catalog["blogpost"]["changesData"])
        self.assertIn("payloadRedacted", catalog["blogpost-update"]["jsonOutput"])

    def test_the_help_of_each_has_its_examples(self):
        for name in COMMANDS:
            result = run_cli("help", name)
            with self.subTest(command=name):
                self.assertEqual(result.code, 0, result.err)
                self.assertIn(f"conflu {name}", result.out)
                self.assertIn("Examples", result.out)


class ListTest(unittest.TestCase):
    def test_the_blog_posts_of_a_space_as_a_table(self):
        result = run_cli("blogposts", "--space", "ENG", "--limit", "10", gateway=roomy())
        self.assertEqual(result.code, 0, result.err)
        lines = result.out.splitlines()
        self.assertEqual(lines[0].split(), ["ID", "TITLE", "STATUS", "VERSION", "CREATED"])
        self.assertEqual([line.split()[0] for line in lines[1:]], ["7101", "7102", "7105"])
        self.assertIn("Release 2026.10 is out", lines[1])
        self.assertEqual(result.err, "")  # nothing follows

    def test_the_json_has_the_rows_of_a_list(self):
        data = run_cli("blogposts", "--space", "ENG", "--limit", "10", "--json", gateway=roomy()).json()
        self.assertEqual(list(data), ["space", "count", "nextCursor", "truncated", "blogposts"])
        self.assertEqual((data["space"], data["count"], data["nextCursor"], data["truncated"]), ("ENG", 3, None, False))
        self.assertEqual(list(data["blogposts"][0]), ROW_KEYS)
        self.assertEqual(data["blogposts"][0]["url"], f"{BASE}/spaces/ENG/blog/2026/10/12/7101/Release+2026.10+is+out")
        self.assertNotIn(ACCOUNT, json.dumps(data))

    def test_a_cursor_continues_and_says_so_on_stderr(self):
        first = run_cli("blogposts", "--space", "ENG", "--limit", "2", "--json").json()
        self.assertEqual((first["count"], first["nextCursor"]), (2, "2"))
        text = run_cli("blogposts", "--space", "ENG", "--limit", "2")
        self.assertIn("More blog posts follow. Continue with --cursor 2, or use --all.", text.err)
        rest = run_cli("blogposts", "--space", "ENG", "--limit", "2", "--cursor", first["nextCursor"], "--json").json()
        self.assertEqual(([row["id"] for row in rest["blogposts"]], rest["nextCursor"]), (["7105"], None))

    def test_all_follows_the_cursor_and_ignores_the_limit(self):
        data = run_cli("blogposts", "--space", "ENG", "--all", "--limit", "1", "--json").json()
        self.assertEqual([row["id"] for row in data["blogposts"]], ["7101", "7102", "7105"])
        self.assertIsNone(data["nextCursor"])

    def test_the_whole_site_and_the_current_space(self):
        whole = run_cli("blogposts", "--all", "--json").json()
        self.assertEqual((whole["space"], [row["id"] for row in whole["blogposts"]]), (None, ["7101", "7102", "7103", "7105"]))
        current = run_cli("blogposts", "--json", settings=default_settings(space="DOCS")).json()
        self.assertEqual((current["space"], [row["id"] for row in current["blogposts"]]), ("DOCS", ["7103"]))
        named = run_cli("blogposts", "--space", "ENG", "--json", settings=default_settings(space="DOCS")).json()
        self.assertEqual(named["space"], "ENG")

    def test_the_title_the_status_and_the_order(self):
        data = run_cli("blogposts", "--space", "ENG", "--title", "weekly update", "--json").json()
        self.assertEqual([row["id"] for row in data["blogposts"]], ["7102"])
        trashed = run_cli("blogposts", "--space", "ENG", "--status", "trashed", "--json").json()
        self.assertEqual([(row["id"], row["status"]) for row in trashed["blogposts"]], [("7104", "trashed")])
        newest = run_cli("blogposts", "--space", "ENG", "--sort", "id", "--desc", "--all", "--json").json()
        self.assertEqual([row["id"] for row in newest["blogposts"]], ["7105", "7102", "7101"])

    def test_select_and_format_shape_the_text(self):
        tsv = run_cli("blogposts", "--space", "ENG", "--all", "--select", "id,title", "--format", "tsv").out
        self.assertEqual(tsv.splitlines()[:2], ["id\ttitle", "7101\tRelease 2026.10 is out"])
        md = run_cli("blogposts", "--space", "ENG", "--all", "--format", "md").out
        self.assertTrue(md.startswith("| ID | TITLE | STATUS | VERSION | CREATED |"))
        selected = run_cli("blogposts", "--space", "ENG", "--all", "--select", "id,version", "--json").json()
        self.assertEqual(selected["blogposts"][0], {"id": "7101", "version": 3})
        wrong = run_cli("blogposts", "--space", "ENG", "--select", "nope")
        self.assertEqual(wrong.code, 2)

    def test_an_empty_list_says_so(self):
        self.assertEqual(run_cli("blogposts", "--space", "ENG", "--title", "No such post").out, "No blog posts.\n")
        self.assertEqual(run_cli("blogposts", "--space", "ENG", "--title", "No such post", "--json").json()["blogposts"], [])

    def test_wrong_input_is_refused(self):
        for argv, code in (
            (("blogposts", "--desc"), 2),
            (("blogposts", "--limit", "0"), 2),
            (("blogposts", "--limit", "251"), 2),
            (("blogposts", "--status", "archived"), 2),
            (("blogposts", "--sort", "title"), 2),
            (("blogposts", "--space", "../x"), 1),
            (("blogposts", "--space", "NOPE"), 4),
        ):
            with self.subTest(argv=argv):
                self.assertEqual(run_cli(*argv).code, code)

    def test_an_empty_space_or_title_is_a_mistake_and_not_the_current_space_or_every_blog_post(self):
        for argv, message in (
            (("blogposts", "--space", ""), "The space is empty."),
            (("blogposts", "--space", "  "), "The space is empty."),
            (("blogposts", "--title", ""), "The title is empty."),
        ):
            with self.subTest(argv=argv):
                gateway = FakeGateway()
                result = run_cli(*argv, gateway=gateway, settings=default_settings(space="DOCS"))
                self.assertEqual(result.code, 2, result.err)
                self.assertIn(message, result.err)
                self.assertEqual(gateway.calls, [])  # nothing was asked
        self.assertEqual(run_cli("blogposts", "--json", settings=default_settings(space="DOCS")).json()["space"], "DOCS")  # none named: the current space

    def test_titles_and_addresses_name_nobody(self):
        gateway = FakeGateway()
        gateway.blogposts["7102"].title = "Mail alex@example.com"
        gateway.blogposts["7102"].url = f"{BASE}/spaces/ENG/blog/2026/10/12/7102/Mail+alex%40example.com"
        out = run_cli("blogposts", "--space", "ENG", "--all", "--json", gateway=gateway).out
        self.assertIn("Mail [email]", out)
        self.assertNotIn("alex", out)
        self.assertNotIn("example.com/", out.replace("example.atlassian.net", ""))


class ReadTest(unittest.TestCase):
    def test_a_blog_post_as_text(self):
        result = run_cli("blogpost", "7101")
        self.assertEqual(result.code, 0, result.err)
        lines = result.out.splitlines()
        self.assertEqual(lines[0], "Release 2026.10 is out  [7101]")
        self.assertEqual(lines[1], f"{BASE}/spaces/ENG/blog/2026/10/12/7101/Release+2026.10+is+out")
        self.assertIn("Space:   ENG", lines)
        self.assertIn("Status:  current", lines)
        self.assertIn("Version: 3", lines)
        self.assertIn("Labels:  release, news", lines)
        self.assertIn("# Release 2026.10", lines)
        self.assertIn("Thanks to @user and write to [email].", result.out)
        self.assertIn("Comments: show them with --comments", lines)
        self.assertNotIn(ACCOUNT, result.out)
        self.assertNotIn("alex@example.com", result.out)
        self.assertIn("The Markdown cannot show: mention, redacted-text.", result.err)
        self.assertNotIn("Author", result.out)

    def test_a_blog_post_as_json(self):
        data = run_cli("blogpost", "7101", "--json").json()
        self.assertEqual(
            list(data), ["id", "title", "status", "spaceId", "spaceKey", "url", "version", "created", "updated", "labels", "author", "body"]
        )
        self.assertEqual((data["id"], data["spaceKey"], data["labels"], data["author"]), ("7101", "ENG", ["release", "news"], None))
        self.assertEqual(data["version"], {"number": 3, "created": "2026-10-14T10:00:00.000Z", "message": "Added the known issues", "minorEdit": False, "author": None})
        self.assertEqual(list(data["body"]), ["format", "value", "dropped", "section", "truncated", "totalChars"])
        self.assertEqual(data["body"]["dropped"], ["mention", "redacted-text"])
        self.assertNotIn(ACCOUNT, json.dumps(data))

    def test_the_comments_come_with_their_replies(self):
        data = run_cli("blogpost", "7101", "--comments", "--json").json()
        self.assertEqual([(item["id"], item["kind"], item["parentId"], item["resolution"]) for item in data["comments"]], [("7151", "footer", None, None), ("7152", "footer", "7151", None), ("7153", "inline", None, "open")])
        self.assertEqual(data["comments"][0]["body"]["value"], "Great news.")
        text = run_cli("blogpost", "7101", "--comments").out
        self.assertIn("Comments: 3", text)
        self.assertIn("Check this number.", text)
        self.assertNotIn(ACCOUNT, text)

    def test_outline_section_and_cut(self):
        outline = run_cli("blogpost", "7101", "--outline").out
        self.assertIn("Outline (read one part with --section TITLE or --section NUMBER):", outline)
        self.assertIn("   2.   Highlights", outline)
        self.assertNotIn("Thanks to", outline)
        as_json = run_cli("blogpost", "7101", "--outline", "--json").json()
        self.assertEqual([(item["index"], item["level"], item["title"]) for item in as_json["outline"]], [(1, 1, "Release 2026.10"), (2, 2, "Highlights"), (3, 2, "Known issues")])
        self.assertIsNone(as_json["body"])
        section = run_cli("blogpost", "7101", "--section", "known", "--json").json()
        self.assertEqual((section["body"]["section"], section["body"]["value"]), ("Known issues", "## Known issues\n\nNone so far.\n\n> [!NOTE]\n> Upgrade notes follow."))
        cut = run_cli("blogpost", "7101", "--max-chars", "40")
        self.assertIn("The text was cut:", cut.err)
        self.assertTrue(run_cli("blogpost", "7101", "--max-chars", "40", "--json").json()["body"]["truncated"])

    def test_the_body_alone_and_the_formats(self):
        body = run_cli("blogpost", "7101", "--body-only")
        self.assertTrue(body.out.startswith("# Release 2026.10\n"))
        self.assertNotIn("[7101]", body.out)
        storage = run_cli("blogpost", "7101", "--body-only", "--format", "storage").out
        self.assertIn('ri:account-id="hidden"', storage)
        self.assertNotIn(ACCOUNT, storage)
        self.assertNotIn("<h1>", run_cli("blogpost", "7101", "--body-only", "--format", "text").out)
        self.assertIsNone(run_cli("blogpost", "7101", "--no-body", "--json").json()["body"])

    def test_raw_is_confluences_own_answer_without_people(self):
        raw = json.loads(run_cli("blogpost", "7101", "--raw").out)
        self.assertEqual(raw["id"], "7101")
        self.assertNotIn(ACCOUNT, json.dumps(raw))
        self.assertIn(ACCOUNT, run_cli("blogpost", "7101", "--raw", "--with-users").out)

    def test_with_users_names_the_people(self):
        text = run_cli("blogpost", "7101", "--with-users").out
        self.assertIn("Author:   Alex Example", text)
        self.assertIn("Saved by: Alex Example", text)
        data = run_cli("blogpost", "7101", "--with-users", "--json").json()
        self.assertEqual(data["author"]["displayName"], "Alex Example")
        refused = run_cli("blogpost", "7101", "--with-users", settings=default_settings(hide_users=True))
        self.assertEqual(refused.code, 1)
        self.assertIn("CONFLUENCE_HIDE_USERS", refused.err)

    def test_the_address_names_it(self):
        for ref in (f"{BASE}/spaces/ENG/blog/2026/10/12/7102/Weekly+update", "7102"):
            self.assertEqual(run_cli("blogpost", ref, "--json").json()["id"], "7102")

    def test_options_that_make_no_sense_together_are_refused(self):
        for argv in (
            ("blogpost", "7101", "--body-only", "--raw"),
            ("blogpost", "7101", "--body-only", "--comments"),
            ("blogpost", "7101", "--body-only", "--outline"),
            ("blogpost", "7101", "--raw", "--outline"),
            ("blogpost", "7101", "--raw", "--section", "x"),
            ("blogpost", "7101", "--raw", "--comments"),
            ("blogpost", "7101", "--outline", "--section", "x"),
            ("blogpost", "7101", "--outline", "--no-body"),
            ("blogpost", "7101", "--outline", "--format", "storage"),
            ("blogpost", "7101", "--max-chars", "-1"),
            ("blogpost", "7101", "--format", "html"),
        ):
            with self.subTest(argv=argv):
                self.assertEqual(run_cli(*argv).code, 2)

    def test_raw_with_the_comments_is_refused_before_anything_is_asked(self):
        gateway = FakeGateway()
        result = run_cli("blogpost", "7101", "--raw", "--comments", gateway=gateway)
        self.assertEqual(result.code, 2)
        self.assertIn("--raw prints Confluence's own JSON of the blog post, which has no comments.", result.err)
        self.assertEqual(gateway.calls, [])
        self.assertEqual(run_cli("blogpost", "7101", "--raw").code, 0)  # without the comments it is what it was

    def test_what_is_no_blog_post_says_what_it_is(self):
        page = run_cli("blogpost", "2002")
        self.assertEqual(page.code, 4)
        self.assertIn("2002 is a page, not a blog post.", page.err)
        self.assertIn("Use `conflu page 2002`.", page.err)
        folder = run_cli("blogpost", "7001")
        self.assertEqual(folder.code, 4)
        self.assertIn("7001 is a folder, not a blog post.", folder.err)
        self.assertIn("Use `conflu folder 7001`.", folder.err)
        self.assertEqual(run_cli("blogpost", "99999").code, 4)

    def test_hostile_ids_are_refused_before_anything_is_asked(self):
        for ref in ("", "abc", "../7101", "7101;7102", "7101 7102", "-7101", "1" * 20, "7101\n7102"):
            with self.subTest(ref=ref):
                gateway = FakeGateway()
                result = run_cli("blogpost", ref, gateway=gateway)
                self.assertIn(result.code, (1, 2))
                self.assertEqual(gateway.calls, [])

    def test_the_exit_code_of_a_failure_is_in_the_error_object_with_json(self):
        error = run_cli("blogpost", "99999", "--json").error()
        self.assertEqual((error["code"], error["exitCode"]), ("NOT_FOUND", 4))


class CreateTest(unittest.TestCase):
    def test_a_dry_run_shows_the_payload_and_sends_nothing(self):
        gateway = FakeGateway()
        result = run_cli("blogpost-create", "--space", "ENG", "--title", "Release 2026.11 is out", "--body", "Hello **world**", "--labels", "release,News", "--dry-run", gateway=gateway)
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("Dry run: a blog post would be created; nothing was sent", result.out)
        self.assertIn('"spaceId": "1001"', result.out)
        self.assertIn("<p>Hello <strong>world</strong></p>", result.out)
        self.assertIn("Labels it would add: release, news", result.out)
        self.assertEqual(gateway.called("create_blogpost"), [])
        self.assertEqual(gateway.called("add_blogpost_labels"), [])

    def test_the_json_of_a_dry_run_and_of_the_real_run(self):
        gateway = FakeGateway()
        argv = ("blogpost-create", "--space", "ENG", "--title", "Release 2026.11 is out", "--body", "Hello", "--labels", "release")
        dry = run_cli(*argv, "--dry-run", "--json", gateway=gateway).json()
        self.assertEqual(list(dry), ["action", "dryRun", "blogpostId", "title", "url", "versionFrom", "versionTo", "lost", "labels", "payload"])
        self.assertEqual((dry["action"], dry["dryRun"], dry["blogpostId"], dry["url"], dry["versionFrom"], dry["versionTo"]), ("created", True, None, None, None, 1))
        real = run_cli(*argv, "--json", gateway=gateway).json()
        self.assertEqual((real["dryRun"], real["labels"], real["payload"]), (False, ["release"], dry["payload"]))  # the request is the one of the dry run
        self.assertEqual(gateway.called("create_blogpost"), [("create_blogpost", dry["payload"])])
        self.assertEqual(gateway.blogposts[real["blogpostId"]].title, "Release 2026.11 is out")
        self.assertEqual([label.name for label in gateway.blogposts[real["blogpostId"]].labels], ["release"])

    def test_the_text_of_the_real_run_names_the_id_and_the_labels(self):
        result = run_cli("blogpost-create", "--space", "ENG", "--title", "Weekly update", "--body", "Hi", "--labels", "a,b")
        self.assertEqual(result.code, 0, result.err)
        first, second = result.out.splitlines()
        self.assertRegex(first, r"^Created blog post 2000\d: Weekly update with the labels a, b$")
        self.assertTrue(second.startswith(BASE))

    def test_the_body_comes_from_a_file_or_standard_input_as_markdown_or_storage(self):
        files = MemoryFiles({"post.md": "# Heading\n\nText.\n", "post.xml": "<p>Raw.</p>"})
        markdown = run_cli("blogpost-create", "--space", "ENG", "--title", "T", "--file", "post.md", "--dry-run", "--json", files=files).json()
        self.assertEqual(markdown["payload"]["body"]["value"], "<h1>Heading</h1>\n<p>Text.</p>")
        storage = run_cli("blogpost-create", "--space", "ENG", "--title", "T", "--file", "post.xml", "--format", "storage", "--dry-run", "--json", files=files).json()
        self.assertEqual(storage["payload"]["body"]["value"], "<p>Raw.</p>")
        piped = run_cli("blogpost-create", "--space", "ENG", "--title", "T", "--file", "-", "--dry-run", "--json", stdin="From a pipe.\n").json()
        self.assertEqual(piped["payload"]["body"]["value"], "<p>From a pipe.</p>")

    def test_a_post_without_a_body_is_fine(self):
        data = run_cli("blogpost-create", "--space", "ENG", "--title", "Only a title", "--dry-run", "--json").json()
        self.assertEqual(data["payload"]["body"], {"representation": "storage", "value": ""})

    def test_a_blog_post_may_have_a_title_that_exists(self):
        gateway = FakeGateway()
        result = run_cli("blogpost-create", "--space", "ENG", "--title", "Weekly update", "--body", "Again", "--json", gateway=gateway)
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual([post.title for post in gateway.blogposts.values()].count("Weekly update"), 2)

    def test_the_current_space_is_the_default(self):
        gateway = FakeGateway()
        data = run_cli("blogpost-create", "--title", "T", "--dry-run", "--json", settings=default_settings(space="DOCS"), gateway=gateway).json()
        self.assertEqual(data["payload"]["spaceId"], "1002")
        none = run_cli("blogpost-create", "--title", "T", "--dry-run")
        self.assertEqual(none.code, 2)
        self.assertIn("conflu use KEY", none.err)

    def test_an_empty_space_is_a_mistake_and_the_blog_post_is_not_made_in_the_current_space(self):
        for extra in ((), ("--dry-run",)):
            for value in ("", "  "):
                with self.subTest(dry_run=bool(extra), space=value):
                    gateway = FakeGateway()
                    result = run_cli("blogpost-create", "--space", value, "--title", "T", "--body", "x", *extra, gateway=gateway, settings=default_settings(space="DOCS"))
                    self.assertEqual(result.code, 2, result.err)
                    self.assertIn("The space is empty.", result.err)
                    self.assertEqual(gateway.calls, [])
                    self.assertNotIn("T", [post.title for post in gateway.blogposts.values()])

    def test_wrong_input_is_refused_before_anything_is_sent(self):
        for argv, code in (
            (("blogpost-create", "--space", "ENG"), 2),  # no title
            (("blogpost-create", "--space", "ENG", "--title", ""), 1),
            (("blogpost-create", "--space", "ENG", "--title", "two\nlines"), 1),
            (("blogpost-create", "--space", "ENG", "--title", "x" * 256), 1),
            (("blogpost-create", "--space", "ENG", "--title", "T", "--labels", "bad label"), 1),
            (("blogpost-create", "--space", "ENG", "--title", "T", "--body", "a", "--file", "post.md"), 2),
            (("blogpost-create", "--space", "ENG", "--title", "T", "--format", "html"), 2),
            (("blogpost-create", "--space", "../x", "--title", "T"), 1),
            (("blogpost-create", "--space", "NOPE", "--title", "T"), 4),
        ):
            with self.subTest(argv=argv):
                gateway = FakeGateway()
                result = run_cli(*argv, gateway=gateway, files=MemoryFiles({"post.md": "x"}))
                self.assertEqual(result.code, code, result.err)
                self.assertEqual(gateway.called("create_blogpost"), [])

    def test_a_body_with_blanked_mentions_is_refused(self):
        storage = run_cli("blogpost", "7101", "--body-only", "--format", "storage").out
        refused = run_cli("blogpost-create", "--space", "ENG", "--title", "Copy", "--body", storage, "--format", "storage")
        self.assertEqual(refused.code, 1)
        self.assertIn("hidden", refused.err)

    def test_the_title_in_the_answer_names_nobody(self):
        out = run_cli("blogpost-create", "--space", "ENG", "--title", "Notes of alex@example.com", "--body", "x", "--dry-run", "--json").json()
        self.assertEqual(out["title"], "Notes of [email]")
        text = run_cli("blogpost-create", "--space", "ENG", "--title", "Notes of alex@example.com", "--body", "x")
        self.assertIn("Notes of [email]", text.out)
        self.assertNotIn("alex@example.com", text.out)

    def test_when_the_labels_fail_the_error_names_the_blog_post_that_is_there(self):
        gateway = FakeGateway()
        gateway.errors["add_blogpost_labels"] = UnavailableError("busy")
        result = run_cli("blogpost-create", "--space", "ENG", "--title", "T", "--body", "x", "--labels", "a", "--json", gateway=gateway)
        self.assertEqual(result.code, 7)
        error = result.error()
        self.assertIn("The blog post was created (id ", error["message"])
        self.assertIn("blogpostId", error["details"])


class UpdateTest(unittest.TestCase):
    def test_a_dry_run_shows_what_would_go(self):
        gateway = FakeGateway()
        result = run_cli("blogpost-update", "7102", "--title", "Weekly update (week 42)", "--dry-run", gateway=gateway)
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("Dry run: blog post 7102 'Weekly update' would go from version 1 to 2; nothing was sent", result.out)
        self.assertIn('"title": "Weekly update (week 42)"', result.out)
        self.assertEqual(gateway.called("update_blogpost"), [])
        self.assertNotIn("without the people", result.out)  # nothing in this body to hide

    def test_the_json_of_a_change(self):
        gateway = FakeGateway()
        data = run_cli("blogpost-update", "7102", "--body", "More.", "--append", "--message", "Added more", "--if-version", "1", "--json", gateway=gateway).json()
        self.assertEqual(
            list(data), ["action", "dryRun", "blogpostId", "title", "url", "versionFrom", "versionTo", "lost", "labels", "payload", "payloadRedacted"]
        )
        self.assertEqual((data["action"], data["blogpostId"], data["versionFrom"], data["versionTo"], data["payloadRedacted"]), ("updated", "7102", 1, 2, False))
        self.assertEqual(data["payload"]["version"], {"number": 2, "message": "Added more"})
        self.assertEqual(data["payload"]["body"]["value"], "<p>Nothing to report this week.</p>\n<p>More.</p>")
        self.assertEqual(gateway.blogposts["7102"].version_number, 2)
        text = run_cli("blogpost-update", "7102", "--title", "Weekly update (2)", gateway=gateway)
        self.assertIn("Updated blog post 7102: Weekly update (2) (version 2 -> 3)", text.out)

    def test_the_same_title_is_nothing_to_change(self):
        gateway = FakeGateway()
        result = run_cli("blogpost-update", "7102", "--title", "Weekly update", gateway=gateway)
        self.assertEqual((result.code, result.out), (0, "Nothing to change: blog post 7102 is already as asked.\n"))
        data = run_cli("blogpost-update", "7102", "--title", "Weekly update", "--json", gateway=gateway).json()
        self.assertEqual((data["action"], data["payload"], data["versionFrom"], data["versionTo"]), ("unchanged", None, 1, 1))
        self.assertEqual(gateway.called("update_blogpost"), [])

    def test_the_guards_refuse_with_exit_code_3(self):
        gateway = FakeGateway()
        version = run_cli("blogpost-update", "7101", "--title", "T", "--if-version", "2", gateway=gateway)
        self.assertEqual(version.code, 3)
        self.assertIn("Blog post 7101 is at version 3, not 2.", version.err)
        since = run_cli("blogpost-update", "7101", "--title", "T", "--if-unchanged-since", "2026-10-14T09:00:00Z", gateway=gateway)
        self.assertEqual(since.code, 3)
        self.assertIn("Blog post 7101 changed in Confluence", since.err)
        self.assertEqual(gateway.called("update_blogpost"), [])
        self.assertEqual(run_cli("blogpost-update", "7101", "--title", "T", "--if-version", "3", "--if-unchanged-since", "2026-10-14T10:00:00Z", gateway=gateway).code, 0)

    def test_the_guards_hold_in_a_dry_run_too(self):
        self.assertEqual(run_cli("blogpost-update", "7101", "--title", "T", "--if-version", "1", "--dry-run").code, 3)
        self.assertEqual(run_cli("blogpost-update", "7101", "--title", "T", "--if-unchanged-since", "2026-10-14T09:00:00Z", "--dry-run").code, 3)

    def test_an_empty_guard_is_refused_with_the_name_of_the_option_and_nothing_is_sent_in_a_dry_run_too(self):
        for extra in ((), ("--dry-run",)):
            with self.subTest(dry_run=bool(extra)):
                gateway = FakeGateway()
                result = run_cli("blogpost-update", "7102", "--title", "T", "--if-unchanged-since", "", *extra, gateway=gateway)
                self.assertEqual(result.code, 1, result.err)
                self.assertIn("--if-unchanged-since: Not an ISO 8601 timestamp: ''", result.err)
                self.assertEqual(result.out, "")
                self.assertEqual(gateway.called("update_blogpost"), [])
                self.assertEqual(gateway.calls, [])
        error = run_cli("blogpost-update", "7102", "--title", "T", "--if-unchanged-since", "", "--json").error()
        self.assertEqual((error["code"], error["exitCode"]), ("INVALID", 1))
        self.assertEqual(run_cli("blogpost-update", "7102", "--title", "T", "--dry-run").code, 0)  # no guard given is no guard
        for extra in ((), ("--dry-run",)):  # the version guard has the same rule: an empty value is no number, so it is no "not given"
            gateway = FakeGateway()
            self.assertEqual(run_cli("blogpost-update", "7102", "--title", "T", "--if-version", "", *extra, gateway=gateway).code, 2)
            self.assertEqual(gateway.calls, [])

    def test_a_replacement_from_markdown_that_would_lose_something_is_refused_unless_forced(self):
        gateway = FakeGateway()
        refused = run_cli("blogpost-update", "7101", "--body", "New text.", gateway=gateway)
        self.assertEqual(refused.code, 1)
        self.assertIn("would lose what Markdown cannot say: mention, redacted-text", refused.err)
        self.assertIn("--force", refused.err)
        self.assertEqual(gateway.called("update_blogpost"), [])
        forced = run_cli("blogpost-update", "7101", "--body", "New text.", "--force", gateway=gateway)
        self.assertEqual(forced.code, 0, forced.err)
        self.assertIn("Warning: dropped what Markdown cannot say: mention, redacted-text.", forced.out)
        dry = run_cli("blogpost-update", "7102", "--body", "New text.", "--dry-run")
        self.assertNotIn("drops", dry.out)

    def test_appending_keeps_everything_that_is_there(self):
        gateway = FakeGateway()
        data = run_cli("blogpost-update", "7101", "--body", "Added.", "--append", "--json", gateway=gateway).json()
        sent = gateway.called("update_blogpost")[0][2]["body"]["value"]
        self.assertIn(ACCOUNT, sent)  # the mention is still a mention in Confluence
        self.assertTrue(sent.endswith("<p>Added.</p>"))
        self.assertTrue(data["payloadRedacted"])
        self.assertNotIn(ACCOUNT, json.dumps(data))

    def test_people_in_the_body_are_not_printed_unless_asked_for(self):
        shown = run_cli("blogpost-update", "7101", "--title", "T", "--dry-run")
        self.assertIn("The request is shown without the people and addresses that the body holds; --with-users shows it as it is.", shown.out)
        self.assertNotIn(ACCOUNT, shown.out)
        self.assertNotIn("alex@example.com", shown.out)
        exact = run_cli("blogpost-update", "7101", "--title", "T", "--dry-run", "--with-users", "--json").json()
        self.assertFalse(exact["payloadRedacted"])
        self.assertIn(ACCOUNT, exact["payload"]["body"]["value"])
        refused = run_cli("blogpost-update", "7101", "--title", "T", "--with-users", settings=default_settings(hide_users=True))
        self.assertEqual(refused.code, 1)
        self.assertIn("CONFLUENCE_HIDE_USERS", refused.err)

    def test_the_body_comes_from_a_file_and_an_empty_file_is_refused(self):
        files = MemoryFiles({"more.md": "From a file.\n", "empty.md": "  \n", "post.xml": "<p>Raw.</p>"})
        data = run_cli("blogpost-update", "7102", "--file", "more.md", "--append", "--dry-run", "--json", files=files).json()
        self.assertIn("<p>From a file.</p>", data["payload"]["body"]["value"])
        empty = run_cli("blogpost-update", "7102", "--file", "empty.md", "--dry-run", files=files)
        self.assertEqual(empty.code, 2)
        self.assertIn("empty", empty.err)
        cleared = run_cli("blogpost-update", "7102", "--body", "", "--dry-run", "--json", files=files).json()  # on purpose, on the command line
        self.assertEqual(cleared["payload"]["body"]["value"], "")
        storage = run_cli("blogpost-update", "7101", "--file", "post.xml", "--format", "storage", "--dry-run", "--json", files=files).json()
        self.assertEqual(storage["payload"]["body"]["value"], "<p>Raw.</p>")

    def test_wrong_input_is_refused_before_anything_is_sent(self):
        for argv, code in (
            (("blogpost-update", "7102"), 1),  # no change
            (("blogpost-update", "7102", "--title", "T", "--append", "--prepend", "--body", "x"), 2),
            (("blogpost-update", "7102", "--append", "--title", "T"), 2),
            (("blogpost-update", "7102", "--title", "two\nlines"), 1),
            (("blogpost-update", "7102", "--title", "T", "--body", "a", "--file", "x.md"), 2),
            (("blogpost-update", "7102", "--title", "T", "--if-version", "x"), 2),
            (("blogpost-update", "7102", "--title", "T", "--if-unchanged-since", "yesterday"), 1),
            (("blogpost-update", "7104", "--title", "T"), 1),  # it is in the trash
            (("blogpost-update", "2002", "--title", "T"), 4),  # a page
            (("blogpost-update", "99999", "--title", "T"), 4),
            (("blogpost-update", "../7102", "--title", "T"), 1),
            (("blogpost-update", "", "--title", "T"), 1),
        ):
            with self.subTest(argv=argv):
                gateway = FakeGateway()
                result = run_cli(*argv, gateway=gateway, files=MemoryFiles({"x.md": "x"}))
                self.assertEqual(result.code, code, result.err)
                self.assertEqual(gateway.called("update_blogpost"), [])

    def test_the_address_names_the_blog_post(self):
        data = run_cli("blogpost-update", f"{BASE}/spaces/ENG/blog/2026/10/12/7102/Weekly+update", "--title", "T", "--dry-run", "--json").json()
        self.assertEqual(data["blogpostId"], "7102")

    def test_the_title_and_the_address_in_the_answer_name_nobody(self):
        gateway = FakeGateway()
        gateway.blogposts["7102"].title = "Notes of alex@example.com"
        gateway.blogposts["7102"].url = f"{BASE}/spaces/ENG/blog/2026/10/12/7102/Notes+of+alex%40example.com"
        data = run_cli("blogpost-update", "7102", "--body", "More", "--append", "--dry-run", "--json", gateway=gateway).json()
        self.assertEqual((data["title"], data["url"]), ("Notes of [email]", f"{BASE}/spaces/ENG/blog/2026/10/12/7102"))


if __name__ == "__main__":
    unittest.main()
