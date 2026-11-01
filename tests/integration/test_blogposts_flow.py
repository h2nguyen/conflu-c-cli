"""Blog posts, the real program against the mock Confluence: list, read, create and change.

What counts here is what is actually sent: the requests, their order, the body of a write, and that a dry run and a refused guard send no write."""
import json

from conflu_c_cli.domain.errors import ConflictError, NotFoundError, RejectedError
from tests.integration.test_end_to_end import ACCOUNT, EndToEnd
from tests.integration.test_http_and_gateway import GatewayCase
from tests.support.mock_blogposts import RELEASE_BODY, BlogpostsRoutes

WRITES = {"POST", "PUT", "DELETE", "PATCH"}


class BlogpostsFlow(EndToEnd):
    def setUp(self):
        super().setUp()
        self.area = self.mock.area(BlogpostsRoutes)

    def targets(self):
        """Every request that was made, as `GET /api/v2/blogposts/7101?body-format=storage`."""
        found = []
        for item in self.mock.requests:
            query = "&".join(f"{key}={value[0]}" for key, value in item.query.items())
            found.append(f"{item.method} {item.path}" + (f"?{query}" if query else ""))
        return found

    def writes(self):
        return [item for item in self.mock.requests if item.method in WRITES and item.path != "/api/v2/content/convert-ids-to-types"]

    def stored(self, blogpost_id):
        return self.area.blogposts[blogpost_id]


class ListTest(BlogpostsFlow):
    def test_a_space_is_asked_for_by_its_id_and_the_list_follows_the_cursor(self):
        result = self.cli("blogposts", "--space", "ENG", "--all", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual([row["id"] for row in result.json()["blogposts"]], ["7101", "7102", "7105"])
        self.assertEqual(
            self.targets(),
            [
                "GET /api/v2/spaces?keys=ENG&description-format=plain",
                "GET /api/v2/spaces/1001/blogposts?status=current&limit=100",
                "GET /api/v2/spaces/1001/blogposts?status=current&limit=100&cursor=2",
            ],
        )

    def test_without_a_space_the_whole_site_is_listed(self):
        result = self.cli("blogposts", "--all", "--json")
        self.assertEqual([row["id"] for row in result.json()["blogposts"]], ["7101", "7102", "7103", "7105"])
        self.assertEqual(result.json()["space"], None)
        self.assertEqual(self.targets()[0], "GET /api/v2/blogposts?status=current&limit=100")
        self.assertEqual([item for item in self.targets() if "/spaces" in item], [])

    def test_the_current_space_is_the_default_and_a_named_one_wins(self):
        self.assertEqual(self.cli("blogposts", "--all", "--json", env={"CONFLUENCE_SPACE": "DOCS"}).json()["space"], "DOCS")
        self.assertEqual(self.cli("blogposts", "--all", "--json", "--space", "ENG", env={"CONFLUENCE_SPACE": "DOCS"}).json()["space"], "ENG")

    def test_the_title_the_status_and_the_order_go_to_confluence(self):
        self.cli("blogposts", "--space", "ENG", "--title", "Weekly update", "--status", "trashed", "--sort", "created-date", "--desc", "--limit", "7")
        asked = self.mock.requests[-1]
        self.assertEqual(asked.path, "/api/v2/spaces/1001/blogposts")
        self.assertEqual(asked.query, {"title": ["Weekly update"], "status": ["trashed"], "sort": ["-created-date"], "limit": ["7"]})
        self.assertEqual(self.cli("blogposts", "--space", "ENG", "--title", "weekly update", "--json").json()["blogposts"][0]["id"], "7102")
        self.assertEqual([row["id"] for row in self.cli("blogposts", "--space", "ENG", "--status", "trashed", "--json").json()["blogposts"]], ["7104"])

    def test_a_cursor_continues_where_the_last_answer_stopped(self):
        first = self.cli("blogposts", "--space", "ENG", "--limit", "2", "--json").json()
        self.assertEqual((len(first["blogposts"]), first["nextCursor"]), (2, "2"))
        rest = self.cli("blogposts", "--space", "ENG", "--limit", "2", "--cursor", first["nextCursor"], "--json").json()
        self.assertEqual(([row["id"] for row in rest["blogposts"]], rest["nextCursor"]), (["7105"], None))

    def test_the_text_is_a_table_and_select_and_format_shape_it(self):
        text = self.cli("blogposts", "--space", "ENG", "--all").out
        self.assertEqual(text.splitlines()[0].split(), ["ID", "TITLE", "STATUS", "VERSION", "CREATED"])
        self.assertIn("Planning notes", text)
        tsv = self.cli("blogposts", "--space", "ENG", "--all", "--select", "id,version", "--format", "tsv").out
        self.assertEqual(tsv.splitlines(), ["id\tversion", "7101\t3", "7102\t1", "7105\t2"])

    def test_a_space_that_is_not_there_is_not_found(self):
        self.assertEqual(self.cli("blogposts", "--space", "NOPE").code, 4)
        self.assertEqual(self.cli("blogposts", "--space", "../x").code, 1)

    def test_an_empty_space_or_title_asks_nothing_and_is_not_the_current_space_or_every_blog_post(self):
        for argv in (("blogposts", "--space", ""), ("blogposts", "--space", " "), ("blogposts", "--title", "")):
            with self.subTest(argv=argv):
                result = self.cli(*argv, env={"CONFLUENCE_SPACE": "DOCS"})
                self.assertEqual(result.code, 2, result.err)
                self.assertIn("is empty.", result.err)
        self.assertEqual(self.mock.requests, [])
        self.assertEqual(self.cli("blogposts", "--all", "--json", env={"CONFLUENCE_SPACE": "DOCS"}).json()["space"], "DOCS")  # none named: the current one

    def test_a_title_with_an_address_and_a_url_with_it_name_nobody(self):
        self.area.add_blogpost("ENG", "Notes of alex@example.com", "<p>x</p>")
        data = self.cli("blogposts", "--space", "ENG", "--all", "--json")
        self.assertNotIn("alex", data.out)
        listed = {row["title"]: row["url"] for row in data.json()["blogposts"]}
        self.assertTrue(listed["Notes of [email]"].endswith("/20000"))
        self.assertTrue(listed["Weekly update"].endswith("/Weekly+update"))

    def test_nothing_that_the_documents_do_not_list_was_asked(self):
        self.cli("blogposts", "--space", "ENG", "--all")
        self.cli("blogposts", "--all")
        self.assertEqual((self.mock.unknown_endpoints, self.mock.deprecated_endpoints), ([], []))


class ReadTest(BlogpostsFlow):
    def test_a_read_is_the_blog_post_and_its_labels(self):
        result = self.cli("blogpost", "7101", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.targets(), ["GET /api/v2/blogposts/7101?body-format=storage", "GET /api/v2/blogposts/7101/labels?limit=250"])
        data = result.json()
        self.assertEqual((data["id"], data["spaceKey"], data["labels"], data["version"]["number"]), ("7101", "ENG", ["news", "release"], 3))
        self.assertEqual(data["body"]["dropped"], ["mention", "redacted-text"])
        self.assertNotIn("comments", data)

    def test_every_label_is_read_however_many_pieces_there_are(self):
        self.stored("7101")["labels"] = ["a", "b", "c", "d", "e"]
        data = self.cli("blogpost", "7101", "--no-body", "--json").json()
        self.assertEqual(data["labels"], ["a", "b", "c", "d", "e"])
        self.assertEqual(len([item for item in self.mock.requests if item.path == "/api/v2/blogposts/7101/labels"]), 3)  # the mock hands out two at a time

    def test_the_comments_are_the_footer_ones_then_the_inline_ones_each_with_its_replies(self):
        data = self.cli("blogpost", "7101", "--comments", "--json").json()
        self.assertEqual([(item["id"], item["kind"], item["parentId"]) for item in data["comments"]], [("7151", "footer", None), ("7152", "footer", "7151"), ("7153", "inline", None)])
        self.assertEqual(
            self.targets()[2:],
            [
                "GET /api/v2/blogposts/7101/footer-comments?body-format=storage&sort=created-date&limit=100",
                "GET /api/v2/footer-comments/7151/children?body-format=storage&sort=created-date&limit=100",
                "GET /api/v2/blogposts/7101/inline-comments?body-format=storage&sort=created-date&limit=100",
                "GET /api/v2/inline-comments/7153/children?body-format=storage&sort=created-date&limit=100",
            ],
        )

    def test_a_comment_added_to_the_mock_is_read_too(self):
        self.area.add_comment("7101", "<p>A later one.</p>", kind="footer")
        text = self.cli("blogpost", "7101", "--comments").out
        self.assertIn("Comments: 4", text)
        self.assertIn("A later one.", text)

    def test_the_outline_and_a_section_are_read_from_the_body_without_another_request(self):
        data = self.cli("blogpost", "7101", "--outline", "--json").json()
        self.assertEqual([item["title"] for item in data["outline"]], ["Release 2026.10", "Highlights", "Known issues"])
        section = self.cli("blogpost", "7101", "--section", "Highlights", "--json").json()
        self.assertEqual(section["body"]["value"], "## Highlights\n\n- Faster search\n- Better export")
        self.assertEqual(len([item for item in self.mock.requests if item.path == "/api/v2/blogposts/7101"]), 2)

    def test_without_a_body_the_body_is_not_asked_for(self):
        self.cli("blogpost", "7101", "--no-body")
        self.assertEqual(self.targets()[0], "GET /api/v2/blogposts/7101")

    def test_the_body_is_as_markdown_or_as_confluence_keeps_it(self):
        self.assertIn("## Known issues", self.cli("blogpost", "7101", "--body-only").out)
        storage = self.cli("blogpost", "7101", "--body-only", "--format", "storage", "--with-users").out
        self.assertEqual(storage.strip(), RELEASE_BODY)

    def test_people_are_hidden_unless_they_are_asked_for(self):
        out = self.cli("blogpost", "7101", "--comments", "--json").out
        self.assertNotIn(ACCOUNT, out)
        self.assertNotIn("alex@example.com", out)
        self.assertEqual(len([item for item in self.mock.requests if item.path == "/api/v2/users-bulk"]), 0)
        before = len(self.mock.requests)
        data = self.cli("blogpost", "7101", "--comments", "--with-users", "--json").json()
        self.assertEqual((data["author"]["displayName"], data["comments"][0]["author"]["displayName"]), ("Alex Example", "Alex Example"))
        self.assertEqual(len([item for item in self.mock.requests[before:] if item.path == "/api/v2/users-bulk"]), 1)
        self.assertEqual(self.cli("blogpost", "7101", "--with-users", env={"CONFLUENCE_HIDE_USERS": "true"}).code, 1)

    def test_raw_is_confluences_answer_without_people(self):
        raw = json.loads(self.cli("blogpost", "7101", "--raw").out)
        self.assertEqual(raw["id"], "7101")
        self.assertNotIn(ACCOUNT, json.dumps(raw))
        self.assertIn(ACCOUNT, self.cli("blogpost", "7101", "--raw", "--with-users").out)

    def test_the_address_copied_from_the_browser_names_the_blog_post(self):
        address = f"{self.mock.base_url}/spaces/ENG/blog/2026/10/12/7102/Weekly+update"
        self.assertEqual(self.cli("blogpost", address, "--json").json()["id"], "7102")

    def test_an_id_that_is_a_page_or_a_folder_says_what_it_is_after_one_question(self):
        page = self.cli("blogpost", "2002")
        self.assertEqual(page.code, 4)
        self.assertIn("2002 is a page, not a blog post.", page.err)
        self.assertIn("Use `conflu page 2002`.", page.err)
        self.assertEqual(self.targets(), ["GET /api/v2/blogposts/2002?body-format=storage", "POST /api/v2/content/convert-ids-to-types"])
        self.assertEqual(self.mock.requests[-1].body, {"contentIds": ["2002"]})
        folder = self.cli("blogpost", "7001")
        self.assertEqual(folder.code, 4)
        self.assertIn("Use `conflu folder 7001`.", folder.err)
        self.assertEqual(self.cli("blogpost", "99999").code, 4)
        self.assertEqual(self.writes(), [])

    def test_a_blog_post_costs_no_question_at_all(self):
        self.cli("blogpost", "7101")
        self.assertEqual(len([item for item in self.mock.requests if item.path == "/api/v2/content/convert-ids-to-types"]), 0)

    def test_hostile_ids_send_nothing(self):
        for ref in ("", "abc", "../7101", "7101;7102", "7101 7102", "-7101", "1" * 20, "7101\n7102", "https://example.atlassian.net/wiki/x/AbCd"):
            with self.subTest(ref=ref):
                self.assertNotEqual(self.cli("blogpost", ref).code, 0)
        self.assertEqual(self.mock.requests, [])

    def test_raw_with_the_comments_is_refused_and_asks_nothing(self):
        result = self.cli("blogpost", "7101", "--raw", "--comments")
        self.assertEqual(result.code, 2)
        self.assertEqual(self.mock.requests, [])

    def test_a_title_with_an_address_and_a_url_with_it_name_nobody(self):
        post = self.area.add_blogpost("ENG", "Notes of alex@example.com", "<p>x</p>")
        text = self.cli("blogpost", post)
        self.assertNotIn("alex", text.out)
        self.assertIn("Notes of [email]  [20000]", text.out)
        shown = self.cli("blogpost", post, "--with-users").out
        self.assertIn("Notes of alex@example.com  [20000]", shown)
        self.assertIn("alex%40example.com", shown)

    def test_nothing_that_the_documents_do_not_list_was_asked(self):
        self.cli("blogpost", "7101", "--comments", "--with-users")
        self.cli("blogpost", "2002")
        self.assertEqual((self.mock.unknown_endpoints, self.mock.deprecated_endpoints), ([], []))


class CreateTest(BlogpostsFlow):
    ARGV = ("blogpost-create", "--space", "ENG", "--title", "Release 2026.11 is out", "--body", "Hello **world**", "--labels", "News,weekly")

    def test_a_dry_run_asks_for_the_space_and_sends_nothing(self):
        result = self.cli(*self.ARGV, "--dry-run", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.targets(), ["GET /api/v2/spaces?keys=ENG&description-format=plain"])
        self.assertEqual(self.writes(), [])
        self.assertEqual(sorted(self.area.blogposts), ["7101", "7102", "7103", "7104", "7105"])
        data = result.json()
        self.assertEqual((data["dryRun"], data["blogpostId"], data["labels"]), (True, None, ["news", "weekly"]))
        self.assertEqual(data["payload"], {"spaceId": "1001", "status": "current", "title": "Release 2026.11 is out", "body": {"representation": "storage", "value": "<p>Hello <strong>world</strong></p>"}})

    def test_the_real_run_sends_the_payload_of_the_dry_run_and_then_the_labels(self):
        preview = self.cli(*self.ARGV, "--dry-run", "--json").json()["payload"]
        before = len(self.mock.requests)
        result = self.cli(*self.ARGV, "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(
            self.targets()[before:],
            ["GET /api/v2/spaces?keys=ENG&description-format=plain", "POST /api/v2/blogposts", "POST /rest/api/content/20000/label"],
        )
        posted = [item for item in self.mock.requests if item.method == "POST"]
        self.assertEqual(posted[0].body, preview)
        self.assertEqual(posted[1].body, [{"prefix": "global", "name": "news"}, {"prefix": "global", "name": "weekly"}])
        data = result.json()
        self.assertEqual((data["action"], data["dryRun"], data["blogpostId"], data["versionTo"], data["labels"]), ("created", False, "20000", 1, ["news", "weekly"]))
        self.assertEqual((self.stored("20000")["title"], self.stored("20000")["labels"], self.stored("20000")["spaceId"]), ("Release 2026.11 is out", ["news", "weekly"], "1001"))

    def test_what_was_created_can_be_read_listed_and_found_by_the_other_commands(self):
        created = self.cli(*self.ARGV, "--json").json()
        read = self.cli("blogpost", created["blogpostId"], "--json").json()
        self.assertEqual((read["title"], read["labels"], read["body"]["value"]), ("Release 2026.11 is out", ["news", "weekly"], "Hello **world**"))
        self.assertIn(created["blogpostId"], [row["id"] for row in self.cli("blogposts", "--space", "ENG", "--all", "--json").json()["blogposts"]])
        self.assertEqual(self.mock.content_kinds[created["blogpostId"]], "blogpost")  # registered, so that the commands of other areas know the id

    def test_without_labels_no_label_request_is_made(self):
        self.cli("blogpost-create", "--space", "ENG", "--title", "Plain", "--body", "x")
        self.assertEqual([item.path for item in self.mock.requests if item.method == "POST"], ["/api/v2/blogposts"])

    def test_blog_posts_may_share_a_title_and_nothing_looks_for_the_other_one(self):
        self.cli("blogpost-create", "--space", "ENG", "--title", "Weekly update", "--body", "Again")
        self.assertEqual([item for item in self.targets() if "title=" in item], [])
        titles = [post["title"] for post in self.area.blogposts.values()]
        self.assertEqual(titles.count("Weekly update"), 2)
        self.assertEqual(len(self.cli("blogposts", "--space", "ENG", "--title", "Weekly update", "--all", "--json").json()["blogposts"]), 2)

    def test_the_body_comes_from_a_file_or_standard_input(self):
        path = self.root / "post.md"
        path.write_text("# Heading\n\nText.\n", encoding="utf-8")
        data = self.cli("blogpost-create", "--space", "ENG", "--title", "From a file", "--file", str(path), "--json").json()
        self.assertEqual(self.stored(data["blogpostId"])["versions"][-1]["body"], "<h1>Heading</h1>\n<p>Text.</p>")
        piped = self.cli("blogpost-create", "--space", "ENG", "--title", "From a pipe", "--file", "-", "--json", stdin="Piped.\n").json()
        self.assertEqual(self.stored(piped["blogpostId"])["versions"][-1]["body"], "<p>Piped.</p>")
        storage = self.cli("blogpost-create", "--space", "ENG", "--title", "Raw", "--body", "<p>Raw.</p>", "--format", "storage", "--json").json()
        self.assertEqual(self.stored(storage["blogpostId"])["versions"][-1]["body"], "<p>Raw.</p>")

    def test_when_the_labels_fail_the_blog_post_is_there_and_the_error_says_so(self):
        self.mock.fail_next("/rest/api/content/", 503, method="POST")
        result = self.cli(*self.ARGV, "--json")
        self.assertEqual(result.code, 7)
        error = json.loads(result.err.strip().splitlines()[-1])["error"]
        self.assertIn("The blog post was created (id 20000), but its labels were not added", error["message"])
        self.assertEqual(error["details"]["blogpostId"], "20000")
        self.assertEqual((self.stored("20000")["title"], self.stored("20000")["labels"]), ("Release 2026.11 is out", []))

    def test_what_confluence_refuses_is_said_with_exit_code_6(self):
        self.mock.fail_next("/api/v2/blogposts", 400, method="POST", body={"errors": [{"title": "That title is not allowed"}]})
        result = self.cli("blogpost-create", "--space", "ENG", "--title", "Refused", "--body", "x")
        self.assertEqual(result.code, 6)
        self.assertIn("That title is not allowed", result.err)
        self.assertEqual(sorted(self.area.blogposts), ["7101", "7102", "7103", "7104", "7105"])

    def test_wrong_input_sends_nothing(self):
        for argv in (
            ("blogpost-create", "--space", "ENG", "--title", ""),
            ("blogpost-create", "--space", "ENG", "--title", "two\nlines"),
            ("blogpost-create", "--space", "ENG", "--title", "x" * 256),
            ("blogpost-create", "--space", "ENG", "--title", "T", "--labels", "bad label"),
            ("blogpost-create", "--space", "ENG", "--title", "T", "--body", "a", "--file", "x.md"),
            ("blogpost-create", "--space", "../x", "--title", "T"),
            ("blogpost-create", "--title", "No space"),
        ):
            with self.subTest(argv=argv):
                self.assertNotEqual(self.cli(*argv).code, 0)
        self.assertEqual(self.writes(), [])
        self.assertEqual(len(self.mock.requests), 0)

    def test_a_space_that_does_not_exist_sends_no_write(self):
        self.assertEqual(self.cli("blogpost-create", "--space", "NOPE", "--title", "T").code, 4)
        self.assertEqual(self.writes(), [])

    def test_an_empty_space_is_a_mistake_and_nothing_is_made_in_the_current_space(self):
        for extra in ((), ("--dry-run",)):
            with self.subTest(dry_run=bool(extra)):
                result = self.cli("blogpost-create", "--space", "", "--title", "Not in ENG", "--body", "x", *extra, env={"CONFLUENCE_SPACE": "ENG"})
                self.assertEqual(result.code, 2, result.err)
                self.assertIn("The space is empty.", result.err)
        self.assertEqual(self.mock.requests, [])
        self.assertEqual(sorted(self.area.blogposts), ["7101", "7102", "7103", "7104", "7105"])

    def test_the_title_in_the_answer_names_nobody_but_the_blog_post_has_it_as_it_was_asked(self):
        data = self.cli("blogpost-create", "--space", "ENG", "--title", "Notes of alex@example.com", "--body", "x", "--json").json()
        self.assertEqual(data["title"], "Notes of [email]")
        self.assertTrue(data["url"].endswith("/20000"))
        self.assertEqual(self.stored("20000")["title"], "Notes of alex@example.com")
        self.assertNotIn("alex", json.dumps(data["url"]))

    def test_nothing_that_the_documents_do_not_list_was_asked(self):
        self.cli(*self.ARGV)
        self.assertEqual((self.mock.unknown_endpoints, self.mock.deprecated_endpoints), ([], []))
        self.assertIn("POST /rest/api/content/{id}/label", self.mock.used_endpoints)


class UpdateTest(BlogpostsFlow):
    def test_a_new_title_sends_the_whole_body_and_the_next_version(self):
        result = self.cli("blogpost-update", "7102", "--title", "Weekly update (week 42)", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.targets(), ["GET /api/v2/blogposts/7102?body-format=storage", "PUT /api/v2/blogposts/7102"])
        put = self.mock.requests[-1].body
        self.assertEqual(put, {"id": "7102", "status": "current", "title": "Weekly update (week 42)", "body": {"representation": "storage", "value": "<p>Nothing to report this week.</p>"}, "version": {"number": 2}})
        data = result.json()
        self.assertEqual((data["action"], data["versionFrom"], data["versionTo"], data["payloadRedacted"]), ("updated", 1, 2, False))
        self.assertEqual((self.stored("7102")["title"], len(self.stored("7102")["versions"])), ("Weekly update (week 42)", 2))

    def test_a_dry_run_reads_and_sends_nothing(self):
        result = self.cli("blogpost-update", "7102", "--title", "New", "--dry-run", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.targets(), ["GET /api/v2/blogposts/7102?body-format=storage"])
        self.assertEqual((result.json()["dryRun"], result.json()["versionTo"]), (True, 2))
        self.assertEqual(self.stored("7102")["title"], "Weekly update")
        self.assertIn("Dry run: blog post 7102 'Weekly update' would go from version 1 to 2; nothing was sent", self.cli("blogpost-update", "7102", "--title", "New", "--dry-run").out)

    def test_the_real_request_is_the_one_of_the_dry_run_when_nothing_is_hidden(self):
        preview = self.cli("blogpost-update", "7102", "--body", "More.", "--append", "--message", "Added more", "--dry-run", "--json").json()["payload"]
        self.cli("blogpost-update", "7102", "--body", "More.", "--append", "--message", "Added more", "--json")
        self.assertEqual([item.body for item in self.mock.requests if item.method == "PUT"], [preview])
        self.assertEqual(preview["version"], {"number": 2, "message": "Added more"})
        self.assertEqual(self.stored("7102")["versions"][-1]["message"], "Added more")

    def test_appending_to_a_body_with_a_mention_keeps_the_mention_in_confluence_and_hides_it_in_the_answer(self):
        result = self.cli("blogpost-update", "7101", "--body", "Added.", "--append", "--json")
        self.assertEqual(result.code, 0, result.err)
        sent = self.mock.requests[-1].body["body"]["value"]
        self.assertIn(ACCOUNT, sent)
        self.assertIn("alex@example.com", sent)
        self.assertTrue(sent.startswith(RELEASE_BODY))
        self.assertEqual(self.stored("7101")["versions"][-1]["body"], sent)  # Confluence got the mention, not the blank
        data = result.json()
        self.assertTrue(data["payloadRedacted"])
        self.assertNotIn(ACCOUNT, result.out)
        self.assertNotIn("alex@example.com", result.out)
        self.assertIn('ri:account-id=\\"hidden\\"', result.out)

    def test_with_users_prints_exactly_what_is_sent(self):
        data = self.cli("blogpost-update", "7101", "--title", "T", "--with-users", "--dry-run", "--json").json()
        self.assertFalse(data["payloadRedacted"])
        self.assertEqual(data["payload"]["body"]["value"], RELEASE_BODY)
        self.assertEqual(self.cli("blogpost-update", "7101", "--title", "T", "--with-users", env={"CONFLUENCE_HIDE_USERS": "true"}).code, 1)
        self.assertEqual(self.writes(), [])

    def test_the_version_that_was_read_is_checked_before_anything_is_sent(self):
        result = self.cli("blogpost-update", "7101", "--title", "T", "--if-version", "2")
        self.assertEqual(result.code, 3)
        self.assertIn("Blog post 7101 is at version 3, not 2.", result.err)
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.cli("blogpost-update", "7101", "--title", "T", "--if-version", "2", "--dry-run").code, 3)
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.cli("blogpost-update", "7101", "--title", "T", "--if-version", "3").code, 0)

    def test_the_time_that_was_read_is_checked_before_anything_is_sent(self):
        result = self.cli("blogpost-update", "7101", "--title", "T", "--if-unchanged-since", "2026-10-14T08:59:59Z")
        self.assertEqual(result.code, 3)
        self.assertIn("Blog post 7101 changed in Confluence", result.err)
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.cli("blogpost-update", "7101", "--title", "T", "--if-unchanged-since", "2026-10-14T09:00:00.000Z").code, 0)
        self.assertEqual(len(self.writes()), 1)

    def test_an_empty_guard_is_refused_and_asks_and_sends_nothing_in_a_dry_run_too(self):
        for extra in ((), ("--dry-run",)):
            with self.subTest(dry_run=bool(extra)):
                result = self.cli("blogpost-update", "7101", "--title", "T", "--if-unchanged-since", "", *extra)
                self.assertEqual(result.code, 1, result.err)
                self.assertIn("--if-unchanged-since: Not an ISO 8601 timestamp: ''", result.err)
        self.assertEqual(self.mock.requests, [])
        self.assertEqual(len(self.stored("7101")["versions"]), 3)

    def test_somebody_who_saves_in_between_is_the_conflict_of_confluence(self):
        self.mock.fail_next("/api/v2/blogposts/7102", 409, method="PUT")
        result = self.cli("blogpost-update", "7102", "--title", "T")
        self.assertEqual(result.code, 3)
        self.assertEqual((self.stored("7102")["title"], len(self.stored("7102")["versions"])), ("Weekly update", 1))
        self.assertEqual(self.cli("blogpost-update", "7102", "--title", "T").code, 0)  # the next try reads the blog post again and goes through

    def test_the_same_title_is_nothing_to_change(self):
        result = self.cli("blogpost-update", "7102", "--title", "Weekly update", "--json")
        self.assertEqual(result.code, 0)
        self.assertEqual((result.json()["action"], result.json()["payload"]), ("unchanged", None))
        self.assertEqual(self.writes(), [])

    def test_a_replacement_from_markdown_that_would_lose_something_is_refused_unless_forced(self):
        refused = self.cli("blogpost-update", "7101", "--body", "New text.")
        self.assertEqual(refused.code, 1)
        self.assertIn("would lose what Markdown cannot say: mention, redacted-text", refused.err)
        self.assertEqual(self.writes(), [])
        forced = self.cli("blogpost-update", "7101", "--body", "New text.", "--force", "--json")
        self.assertEqual((forced.code, forced.json()["lost"]), (0, ["mention", "redacted-text"]))
        self.assertEqual(self.stored("7101")["versions"][-1]["body"], "<p>New text.</p>")

    def test_a_replacement_in_storage_format_needs_no_force(self):
        self.assertEqual(self.cli("blogpost-update", "7101", "--body", "<p>Raw.</p>", "--format", "storage").code, 0)
        self.assertEqual(self.stored("7101")["versions"][-1]["body"], "<p>Raw.</p>")

    def test_a_body_that_was_read_without_people_is_not_written_back(self):
        blanked = self.cli("blogpost", "7101", "--body-only", "--format", "storage").out
        refused = self.cli("blogpost-update", "7101", "--body", blanked, "--format", "storage")
        self.assertEqual(refused.code, 1)
        self.assertEqual(self.writes(), [])

    def test_a_trashed_blog_post_and_other_kinds_of_content_are_not_changed(self):
        self.assertEqual(self.cli("blogpost-update", "7104", "--title", "T").code, 1)
        self.assertEqual(self.cli("blogpost-update", "2002", "--title", "T").code, 4)
        self.assertEqual(self.cli("blogpost-update", "99999", "--title", "T").code, 4)
        self.assertEqual(self.writes(), [])

    def test_wrong_input_sends_nothing(self):
        for argv in (
            ("blogpost-update", "7102"),
            ("blogpost-update", "7102", "--title", "T", "--append", "--prepend", "--body", "x"),
            ("blogpost-update", "7102", "--append", "--title", "T"),
            ("blogpost-update", "7102", "--title", "two\nlines"),
            ("blogpost-update", "../7102", "--title", "T"),
            ("blogpost-update", "7102;7101", "--title", "T"),
            ("blogpost-update", "7102", "--title", "T", "--if-unchanged-since", "yesterday"),
        ):
            with self.subTest(argv=argv):
                self.assertNotEqual(self.cli(*argv).code, 0)
        self.assertEqual(self.writes(), [])

    def test_the_title_in_the_answer_names_nobody_and_the_blog_post_has_the_new_title_as_it_was_asked(self):
        post = self.area.add_blogpost("ENG", "Notes", "<p>x</p>")
        data = self.cli("blogpost-update", post, "--title", "Notes of alex@example.com", "--json").json()
        self.assertEqual(data["title"], "Notes of [email]")
        self.assertEqual(self.stored(post)["title"], "Notes of alex@example.com")
        self.assertNotIn("alex", data["url"])
        self.assertTrue(data["payloadRedacted"])
        self.assertEqual(data["payload"]["title"], "Notes of [email]")

    def test_nothing_that_the_documents_do_not_list_was_asked(self):
        self.cli("blogpost-update", "7102", "--title", "T")
        self.cli("blogpost-update", "2002", "--title", "T")
        self.assertEqual((self.mock.unknown_endpoints, self.mock.deprecated_endpoints), ([], []))


class GatewayTest(GatewayCase):
    """The REST calls of the area, one by one, with what the gateway makes of the answers."""

    def test_a_blog_post_is_read_with_and_without_its_body(self):
        post = self.gw.get_blogpost("7101")
        self.assertEqual((post.id, post.title, post.status, post.space_id, post.space_key, post.version_number, post.labels), ("7101", "Release 2026.10 is out", "current", "1001", "ENG", 3, []))
        self.assertEqual(post.body, RELEASE_BODY)
        self.assertEqual(post.url, f"{self.mock.base_url}/spaces/ENG/blog/2026/10/12/7101/Release+2026.10+is+out")
        self.assertEqual(self.mock.requests[-1].query, {"body-format": ["storage"]})
        self.assertIsNone(self.gw.get_blogpost("7101", with_body=False).body)
        self.assertEqual(self.mock.requests[-1].query, {})
        self.assertEqual(post.raw["authorId"], ACCOUNT)

    def test_a_blog_post_that_is_not_there_is_not_found(self):
        with self.assertRaises(NotFoundError):
            self.gw.get_blogpost("99999")
        with self.assertRaises(NotFoundError):
            self.gw.get_blogpost("2002")  # a page has its own collection

    def test_a_list_has_the_pieces_the_cursor_and_the_filters(self):
        chunk = self.gw.list_blogposts(space_id="1001", limit=2)
        self.assertEqual(([post.id for post in chunk.items], chunk.cursor), (["7101", "7102"], "2"))
        self.assertIsNone(chunk.items[0].body)
        rest = self.gw.list_blogposts(space_id="1001", limit=2, cursor=chunk.cursor)
        self.assertEqual(([post.id for post in rest.items], rest.cursor), (["7105"], ""))
        self.assertEqual([post.id for post in self.gw.list_blogposts(title="Docs news").items], ["7103"])
        self.assertEqual([post.id for post in self.gw.list_blogposts(status="trashed").items], ["7104"])
        self.assertEqual([post.id for post in self.gw.list_blogposts(space_id="1001", sort="-id", limit=2).items], ["7105", "7102"])  # the newest first
        self.assertEqual(self.mock.requests[-1].path, "/api/v2/spaces/1001/blogposts")

    def test_a_blog_post_is_created_and_changed_and_a_version_that_is_not_the_next_is_a_conflict(self):
        created = self.gw.create_blogpost({"spaceId": "1001", "status": "current", "title": "Made here", "body": {"representation": "storage", "value": "<p>x</p>"}})
        self.assertEqual((created.id, created.version_number, created.body, created.status), ("20000", 1, "<p>x</p>", "current"))
        self.assertEqual(self.mock.content_kinds["20000"], "blogpost")
        changed = self.gw.update_blogpost("20000", {"id": "20000", "status": "current", "title": "Changed", "body": {"representation": "storage", "value": "<p>y</p>"}, "version": {"number": 2, "message": "m"}})
        self.assertEqual((changed.title, changed.version_number, changed.version.message), ("Changed", 2, "m"))
        with self.assertRaises(ConflictError):
            self.gw.update_blogpost("20000", {"id": "20000", "status": "current", "title": "Again", "body": {"representation": "storage", "value": "z"}, "version": {"number": 2}})
        with self.assertRaises(RejectedError):
            self.gw.update_blogpost("20000", {"id": "20000", "title": "No body"})
        with self.assertRaises(NotFoundError):
            self.gw.update_blogpost("99999", {"id": "99999", "status": "current", "title": "T", "body": {"representation": "storage", "value": "z"}, "version": {"number": 2}})

    def test_the_labels_are_read_in_pieces_and_added_with_the_older_call(self):
        self.assertEqual([label.name for label in self.gw.list_blogpost_labels("7101")], ["news", "release"])
        added = self.gw.add_blogpost_labels("7102", [{"prefix": "global", "name": "one"}, {"prefix": "global", "name": "two"}])
        self.assertEqual([label.name for label in added], ["one", "two"])
        self.assertEqual(self.mock.requests[-1].path, "/rest/api/content/7102/label")
        self.assertEqual([label.name for label in self.gw.list_blogpost_labels("7102")], ["one", "two"])
        with self.assertRaises(RejectedError):
            self.gw.add_blogpost_labels("7102", [{"prefix": "global", "name": "bad label"}])

    def test_the_comments_of_a_blog_post_and_their_replies(self):
        footer = self.gw.list_blogpost_comments("7101")
        self.assertEqual([(item.id, item.kind, item.body) for item in footer.items], [("7151", "footer", "<p>Great news.</p>")])
        inline = self.gw.list_blogpost_comments("7101", inline=True)
        self.assertEqual([(item.id, item.kind, item.resolution) for item in inline.items], [("7153", "inline", "open")])
        self.assertEqual([(item.id, item.parent_id) for item in self.gw.list_replies("7151").items], [("7152", "7151")])
        self.assertEqual(self.gw.list_blogpost_comments("7102").items, [])
        with self.assertRaises(NotFoundError):
            self.gw.list_blogpost_comments("99999")
        self.assertEqual((self.mock.unknown_endpoints, self.mock.deprecated_endpoints), ([], []))
