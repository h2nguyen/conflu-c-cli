"""Earlier versions of a page, several pages in one call, the files of a page, the difference between two versions and restoring one: the real program against the mock Confluence.

What counts here is what is actually sent: the requests, their order, and that a dry run and a refused guard send no write."""
import json

from conflu_c_cli.domain.errors import ConflictError, NotFoundError, RejectedError
from conflu_c_cli.domain.history import restore_payload
from tests.integration.test_end_to_end import ACCOUNT, EndToEnd
from tests.integration.test_http_and_gateway import GatewayCase
from tests.support.fakes_history import FIRST_BODY, SECOND_BODY
from tests.support.mock_history import HistoryRoutes

WRITES = {"POST", "PUT", "DELETE", "PATCH"}


class HistoryFlow(EndToEnd):
    def setUp(self):
        super().setUp()
        self.area = self.mock.area(HistoryRoutes)

    def targets(self):
        """Every request that was made, as `GET /api/v2/pages/2002?version=1`."""
        found = []
        for item in self.mock.requests:
            query = "&".join(f"{key}={value[0]}" for key, value in item.query.items())
            found.append(f"{item.method} {item.path}" + (f"?{query}" if query else ""))
        return found

    def writes(self):
        return [item for item in self.mock.requests if item.method in WRITES and item.path != "/api/v2/content/convert-ids-to-types"]

    def version_body(self, number, page="2002"):
        return next(item for item in self.mock.pages[page]["versions"] if item["number"] == number)["body"]


class ReadAVersionTest(HistoryFlow):
    def test_the_page_now_and_the_version_are_the_two_requests(self):
        result = self.cli("page", "2002", "--version", "1", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.targets(), ["GET /api/v2/pages/2002?include-labels=true", "GET /api/v2/pages/2002?version=1&body-format=storage"])
        data = result.json()
        self.assertEqual((data["title"], data["version"]["number"], data["version"]["current"], data["currentVersion"]), ("Release notes (draft)", 1, False, 3))
        self.assertEqual(data["body"]["value"], "# Release notes\n\nDraft.")
        self.assertEqual(data["labels"], ["release", "notes"])

    def test_every_version_has_its_own_body_and_the_current_one_says_so(self):
        for number, expected in ((1, "Draft."), (2, "Contact @user."), (3, "write to [email]")):
            with self.subTest(version=number):
                data = self.cli("page", "2002", "--version", str(number), "--json").json()
                self.assertIn(expected, data["body"]["value"])
                self.assertEqual(data["version"]["current"], number == 3)
        self.assertEqual(self.cli("page", "2002", "--version", "3", "--format", "storage", "--body-only").out.strip(), self.version_body(3).replace(ACCOUNT, "hidden").replace("alex@example.com", "[email]"))

    def test_the_text_says_which_version_it_is(self):
        text = self.cli("page", "2002", "--version", "2").out
        self.assertIn("Version: 2 (an earlier version; the current one is 3)", text)
        self.assertIn("Updated: 2026-10-05T10:00:00.000Z", text)

    def test_a_version_above_the_newest_is_not_found_after_one_request(self):
        result = self.cli("page", "2002", "--version", "9")
        self.assertEqual(result.code, 4)
        self.assertIn("Page 2002 has no version 9.", result.err)
        self.assertIn("The page is at version 3. `conflu versions 2002` lists the versions it has.", result.err)
        self.assertEqual(self.targets(), ["GET /api/v2/pages/2002?include-labels=true"])

    def test_a_version_that_the_page_lost_is_not_found_with_the_same_words(self):
        self.mock.pages["2002"]["versions"] = [item for item in self.mock.pages["2002"]["versions"] if item["number"] != 2]
        result = self.cli("page", "2002", "--version", "2")
        self.assertEqual(result.code, 4)
        self.assertIn("Page 2002 has no version 2.", result.err)
        self.assertIn("conflu versions 2002", result.err)

    def test_people_stay_hidden_unless_they_are_asked_for(self):
        hidden = self.cli("page", "2002", "--version", "2", "--format", "storage", "--body-only").out
        self.assertIn('ri:account-id="hidden"', hidden)
        self.assertNotIn(ACCOUNT, hidden)
        before = len(self.mock.requests)
        shown = self.cli("page", "2002", "--version", "2", "--format", "storage", "--body-only", "--with-users").out
        self.assertIn(ACCOUNT, shown)
        self.assertEqual(
            self.targets()[before:],
            ["GET /api/v2/pages/2002?include-labels=true", "GET /api/v2/pages/2002?version=2&body-format=storage", "POST /api/v2/users-bulk"],  # the names of the people, once
        )
        data = self.cli("page", "2002", "--version", "2", "--with-users", "--json").json()
        self.assertEqual(data["version"]["author"]["accountId"], ACCOUNT)
        refused = self.cli("page", "2002", "--version", "2", "--with-users", env={"CONFLUENCE_HIDE_USERS": "true"})
        self.assertEqual(refused.code, 1)

    def test_the_options_that_do_not_fit_send_nothing(self):
        for argv in (("page", "2002", "--version", "0"), ("page", "2002", "--version", "1", "--comments"), ("page", "2002", "--version", "1", "--ancestors"), ("page", "2002", "2003", "--version", "1")):
            with self.subTest(argv=argv):
                self.assertEqual(self.cli(*argv).code, 2)
        self.assertEqual(self.mock.requests, [])

    def test_raw_with_what_it_does_not_hold_sends_nothing(self):
        for extra in ("--attachments", "--comments", "--ancestors"):
            with self.subTest(option=extra):
                result = self.cli("page", "2002", "--raw", extra)
                self.assertEqual(result.code, 2, result.err)
        self.assertEqual(self.mock.requests, [])
        self.assertEqual(self.cli("page", "2002", "--raw", "--no-body").code, 0)

    def test_the_address_of_the_page_names_it(self):
        data = self.cli("page", f"{self.mock.base_url}/spaces/ENG/pages/2002/Release+notes", "--version", "1", "--json").json()
        self.assertEqual(data["version"]["number"], 1)

    def test_nothing_that_the_documents_do_not_list_was_asked(self):
        self.cli("page", "2002", "--version", "1")
        self.cli("page", "2002", "2003", "--outline")
        self.cli("diff", "2002")
        self.assertEqual(self.mock.unknown_endpoints, [])
        self.assertEqual(self.mock.deprecated_endpoints, [])


class WhatIsNoPageTest(HistoryFlow):
    def test_the_id_of_a_folder_says_what_it_is(self):
        result = self.cli("page", "7001")
        self.assertEqual(result.code, 4)
        self.assertIn("Hint: 7001 is a folder, not a page: use `conflu folder 7001`.", result.err)
        self.assertEqual(self.targets(), ["GET /api/v2/pages/7001?include-labels=true&body-format=storage", "POST /api/v2/content/convert-ids-to-types"])
        self.assertEqual(self.mock.requests[-1].body, {"contentIds": ["7001"]})
        self.assertEqual(self.writes(), [])

    def test_a_page_that_does_not_exist_costs_the_question_and_keeps_its_error(self):
        result = self.cli("page", "99999", "--json")
        self.assertEqual(result.code, 4)
        self.assertEqual(result.err and json.loads(result.err.strip().splitlines()[-1])["error"]["code"], "NOT_FOUND")
        self.assertNotIn("not a page", result.err)

    def test_a_page_costs_no_question_at_all(self):
        self.cli("page", "2002")
        self.assertEqual(self.targets(), ["GET /api/v2/pages/2002?include-labels=true&body-format=storage"])

    def test_a_folder_in_the_path_has_its_title(self):
        created = self.cli("create", "--title", "Below a folder", "--space", "ENG", "--parent", "7011", "--body", "Text.", "--json").json()
        before = len(self.mock.requests)
        data = self.cli("page", created["pageId"], "--ancestors", "--no-body", "--json").json()
        self.assertEqual(data["ancestors"], [{"id": "7001", "title": "Guides"}, {"id": "7011", "title": "Runbooks"}])
        asked = self.targets()[before:]
        self.assertIn("GET /api/v2/folders/7001", asked)
        self.assertIn("GET /api/v2/folders/7011", asked)
        self.assertIn("Path:    Guides > Runbooks > Below a folder", self.cli("page", created["pageId"], "--ancestors", "--no-body").out)

    def test_a_path_of_pages_costs_what_it_always_cost(self):
        self.cli("page", "2004", "--ancestors", "--no-body")
        self.assertEqual(
            self.targets(),
            ["GET /api/v2/pages/2004?include-labels=true", "GET /api/v2/pages/2004/ancestors?limit=250", "GET /api/v2/pages?id=2001,2003&limit=250"],
        )


class OtherCommandsOnWhatIsNoPageTest(HistoryFlow):
    """`labels`, `label`, `comments`, `comment` and `update` ask once what the id is when Confluence has no page of that id, and write nothing."""

    FIRST = (
        (("labels",), "GET /api/v2/pages/{id}/labels"),
        (("label", "--add", "x"), "GET /api/v2/pages/{id}/labels"),
        (("label", "--add", "x", "--dry-run"), "GET /api/v2/pages/{id}/labels"),
        (("comments",), "GET /api/v2/pages/{id}/footer-comments"),
        (("comments", "--inline"), "GET /api/v2/pages/{id}/footer-comments"),
        (("comment", "--text", "Hi"), "POST /api/v2/footer-comments"),
        (("comment", "--text", "Hi", "--dry-run"), "GET /api/v2/pages/{id}"),
        (("update", "--title", "T"), "GET /api/v2/pages/{id}"),
        (("update", "--title", "T", "--dry-run"), "GET /api/v2/pages/{id}"),
    )

    def test_each_command_says_what_the_id_is_after_one_question_and_writes_nothing(self):
        for ref, kind, command in (("7001", "folder", "folder"), ("7101", "blog post", "blogpost")):
            for tail, first in self.FIRST:
                with self.subTest(argv=tail, id=ref):
                    before = len(self.mock.requests)
                    comments = json.dumps(self.mock.comments, sort_keys=True)
                    result = self.cli(tail[0], ref, *tail[1:])
                    self.assertEqual(result.code, 4, result.err)
                    self.assertIn(f"Hint: {ref} is a {kind}, not a page: use `conflu {command} {ref}`.", result.err)
                    asked = self.targets()[before:]
                    self.assertEqual(len(asked), 2, asked)
                    self.assertTrue(asked[0].startswith(first.format(id=ref)), asked)
                    self.assertEqual(asked[1], "POST /api/v2/content/convert-ids-to-types")
                    self.assertEqual(self.mock.requests[-1].body, {"contentIds": [ref]})
                    self.assertEqual(json.dumps(self.mock.comments, sort_keys=True), comments)
                    self.assertEqual([item for item in self.writes() if item.path != "/api/v2/footer-comments"], [])

    def test_an_id_that_is_nothing_keeps_its_error_and_pages_cost_no_question(self):
        for tail, _ in self.FIRST:
            with self.subTest(argv=tail):
                result = self.cli(tail[0], "99999", *tail[1:])
                self.assertEqual(result.code, 4, result.err)
                self.assertNotIn("not a page", result.err)
        before = len(self.mock.requests)
        for tail in (("labels", "2002"), ("comments", "2002"), ("comment", "2002", "--text", "Hi", "--dry-run"), ("update", "2005", "--title", "T", "--dry-run")):
            self.assertEqual(self.cli(*tail).code, 0, tail)
        self.assertNotIn("POST /api/v2/content/convert-ids-to-types", self.targets()[before:])


class SeveralPagesTest(HistoryFlow):
    def test_one_request_reads_them_all(self):
        self.mock.page_cap = 1000
        result = self.cli("page", "2003", "2002", "2004", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.targets(), ["GET /api/v2/pages?id=2003,2002,2004&body-format=storage&limit=250"])
        data = result.json()
        self.assertEqual((data["count"], [page["id"] for page in data["pages"]], data["errors"]), (3, ["2003", "2002", "2004"], []))
        self.assertTrue(all(page["labels"] is None for page in data["pages"]))

    def test_an_answer_that_does_not_fit_is_followed_with_its_cursor(self):
        result = self.cli("page", "2001", "2002", "2003", "2004", "2005", "--no-body", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(result.json()["count"], 5)
        cursors = [item.query.get("cursor", [""])[0] for item in self.mock.requests]
        self.assertEqual(cursors, ["", "2", "4"])  # the mock hands out two at a time

    def test_a_page_that_is_not_there_is_asked_for_on_its_own_and_the_others_are_shown(self):
        self.mock.page_cap = 1000
        result = self.cli("page", "2002", "999", "2003", "--outline", "--json")
        self.assertEqual(result.code, 4)
        data = result.json()
        self.assertEqual([page["id"] for page in data["pages"]], ["2002", "2003"])
        self.assertEqual((data["errors"][0]["ref"], data["errors"][0]["code"]), ("999", "NOT_FOUND"))
        self.assertEqual(
            self.targets(),
            ["GET /api/v2/pages?id=2002,999,2003&body-format=storage&limit=250", "GET /api/v2/pages/999?include-labels=true&body-format=storage", "POST /api/v2/content/convert-ids-to-types"],
        )

    def test_a_page_that_the_list_leaves_out_but_that_exists_is_read_on_its_own(self):
        self.mock.page_cap = 1000
        self.mock.pages["2003"]["status"] = "trashed"
        data = self.cli("page", "2002", "2003", "--no-body", "--json").json()
        self.assertEqual([(page["id"], page["status"]) for page in data["pages"]], [("2002", "current"), ("2003", "trashed")])
        self.assertIn("GET /api/v2/pages/2003?include-labels=true", self.targets())

    def test_at_most_250_ids_go_into_one_request(self):
        self.mock.page_cap = 1000
        ids = [self.mock.add_page("ENG", f"Bulk {number}", "<p>x</p>") for number in range(251)]
        result = self.cli("page", *ids, "--no-body", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(result.json()["count"], 251)
        asked = [item for item in self.mock.requests if item.path == "/api/v2/pages"]
        self.assertEqual([len(item.query["id"][0].split(",")) for item in asked], [250, 1])
        self.assertTrue(all(item.query["limit"] == ["250"] and "body-format" not in item.query for item in asked))

    def test_the_text_has_a_rule_between_the_pages_and_a_line_for_the_one_that_is_missing(self):
        text = self.cli("page", "2002", "999", "2003", "--outline")
        self.assertEqual(text.code, 4)
        self.assertIn("=" * 72, text.out)
        self.assertIn("999  [NOT_FOUND] Not found: GET /api/v2/pages/999", text.out)
        self.assertLess(text.out.index("Release notes  [2002]"), text.out.index("999  [NOT_FOUND]"))
        self.assertLess(text.out.index("999  [NOT_FOUND]"), text.out.index("Architecture  [2003]"))

    def test_the_same_page_in_two_forms_is_read_once(self):
        self.mock.page_cap = 1000
        data = self.cli("page", "2002", f"{self.mock.base_url}/spaces/ENG/pages/2002/Release+notes", "2002", "--no-body", "--json").json()
        self.assertEqual([page["id"] for page in data["pages"]], ["2002"])
        self.assertEqual(self.mock.requests[0].query["id"], ["2002"])

    def test_a_page_named_by_its_title_is_found_first(self):
        self.mock.page_cap = 1000
        data = self.cli("page", "page:ENG/Architecture", "2002", "--no-body", "--json").json()
        self.assertEqual([page["id"] for page in data["pages"]], ["2003", "2002"])
        self.assertEqual(self.mock.requests[-1].query["id"], ["2003,2002"])

    def test_people_are_hidden_in_every_page_and_named_once_when_asked_for(self):
        out = self.cli("page", "2002", "2004", "--json").out
        self.assertNotIn(ACCOUNT, out)
        self.assertNotIn("alex@example.com", out)
        before = len(self.mock.requests)
        data = self.cli("page", "2002", "2004", "--with-users", "--no-body", "--json").json()
        self.assertEqual([page["author"]["displayName"] for page in data["pages"]], ["Alex Example", "Alex Example"])
        self.assertEqual(sum(1 for item in self.mock.requests[before:] if item.path == "/api/v2/users-bulk"), 1)

    def test_what_is_for_one_page_sends_nothing_for_several(self):
        for argv in (("page", "2002", "2003", "--raw"), ("page", "2002", "2003", "--body-only"), ("page", "2002", "../2003")):
            with self.subTest(argv=argv):
                self.assertNotEqual(self.cli(*argv).code, 0)
        self.assertEqual(self.mock.requests, [])

    def test_a_failure_of_the_request_ends_the_call(self):
        self.mock.fail_next("/api/v2/pages", 503, times=5, method="GET")
        result = self.cli("page", "2002", "2003")
        self.assertEqual(result.code, 7)
        self.assertNotIn("Release notes", result.out)


class AttachmentsTest(HistoryFlow):
    def test_one_request_asks_for_the_files_of_the_page(self):
        result = self.cli("page", "2002", "--attachments", "--no-body", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.targets(), ["GET /api/v2/pages/2002?include-labels=true", "GET /api/v2/pages/2002/attachments?limit=100"])
        data = result.json()
        self.assertEqual(data["attachmentTotal"], 2)
        self.assertEqual([item["title"] for item in data["attachments"]], ["diagram.png", "notes.txt"])
        self.assertEqual({item["mediaType"] for item in data["attachments"]}, {"image/png", "text/plain"})

    def test_without_the_option_nothing_is_asked_and_nothing_is_said(self):
        text = self.cli("page", "2002", "--no-body").out
        self.assertNotIn("Attachments", text)
        self.assertEqual(self.targets(), ["GET /api/v2/pages/2002?include-labels=true"])

    def test_the_text_names_the_files(self):
        self.assertIn("Attachments: 2 (diagram.png, notes.txt)", self.cli("page", "2002", "--attachments", "--no-body").out)
        self.assertIn("Attachments: none", self.cli("page", "2003", "--attachments", "--no-body").out)

    def test_a_file_name_with_an_address_is_hidden_unless_people_are_shown(self):
        self.mock.add_attachment("2003", "plan-alex@example.com.txt", b"x", "text/plain")
        hidden = self.cli("page", "2003", "--attachments", "--no-body", "--json").out
        self.assertNotIn("alex@example.com", hidden)
        self.assertIn("[email]", hidden)
        shown = self.cli("page", "2003", "--attachments", "--no-body", "--with-users", "--json").out
        self.assertIn("plan-alex@example.com.txt", shown)

    def test_a_long_list_is_read_whole(self):
        for number in range(105):
            self.mock.add_attachment("2003", f"file{number:03d}.txt", b"x", "text/plain")
        data = self.cli("page", "2003", "--attachments", "--no-body", "--json").json()
        self.assertEqual(data["attachmentTotal"], 105)
        self.assertGreater(len([item for item in self.mock.requests if item.path == "/api/v2/pages/2003/attachments"]), 1)  # the mock hands out two at a time


class DiffTest(HistoryFlow):
    def test_the_current_version_and_the_one_before_are_the_two_reads(self):
        result = self.cli("diff", "2002")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.targets(), ["GET /api/v2/pages/2002?include-labels=true&body-format=storage", "GET /api/v2/pages/2002?version=2&body-format=storage"])
        self.assertIn("-Contact @user.", result.out)
        self.assertIn("+Contact @user or write to [email].", result.out)
        self.assertIn("+- Second", result.out)
        self.assertNotIn(ACCOUNT, result.out)
        self.assertNotIn("alex@example.com", result.out)

    def test_two_versions_that_are_named_are_read_with_the_current_page(self):
        self.cli("diff", "2002", "--from", "1", "--to", "2")
        self.assertEqual(
            self.targets(),
            ["GET /api/v2/pages/2002?include-labels=true&body-format=storage", "GET /api/v2/pages/2002?version=2&body-format=storage", "GET /api/v2/pages/2002?version=1&body-format=storage"],
        )

    def test_the_json_counts_the_lines_and_names_both_sides(self):
        data = self.cli("diff", "2002", "--from", "1", "--json").json()
        self.assertEqual((data["from"]["number"], data["from"]["title"], data["to"]["number"], data["to"]["current"]), (1, "Release notes (draft)", 3, True))
        self.assertEqual((data["removed"], data["added"], data["identical"]), (1, 4, False))
        self.assertIn("-Draft.", data["diff"])
        self.assertEqual(data["dropped"], ["macro:toc", "mention", "redacted-text"])

    def test_a_page_with_one_version_is_one_request_and_no_failure(self):
        result = self.cli("diff", "2005")
        self.assertEqual((result.code, result.out), (0, "Page 2005 has one version only: there is nothing to compare.\n"))
        self.assertEqual(self.targets(), ["GET /api/v2/pages/2005?include-labels=true&body-format=storage"])

    def test_the_first_version_of_a_page_that_has_more_says_that_nothing_came_before_it(self):
        result = self.cli("diff", "2002", "--to", "1", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.targets(), ["GET /api/v2/pages/2002?include-labels=true&body-format=storage", "GET /api/v2/pages/2002?version=1&body-format=storage"])
        data = result.json()
        self.assertEqual((data["from"], data["identical"], data["sourceIdentical"], data["diff"]), (None, False, False, ""))
        self.assertTrue(data["note"].startswith("Version 1 is the first version of page 2002: nothing came before it"))
        self.assertNotIn("one version only", result.out)
        self.assertEqual(self.cli("diff", "2002", "--to", "").code, 2)

    def test_versions_that_differ_only_in_what_markdown_cannot_say_are_the_same_as_markdown(self):
        versions = self.mock.pages["2002"]["versions"]
        versions[0]["body"] = "<h1>Release notes</h1><p>Same.</p>"
        versions[1]["body"] = '<h1>Release notes</h1><p>Same.</p><ac:structured-macro ac:name="toc" ac:schema-version="1" />'
        data = self.cli("diff", "2002", "--from", "1", "--to", "2", "--json").json()
        self.assertEqual((data["identical"], data["sourceIdentical"], data["dropped"], data["diff"]), (True, False, ["macro:toc"], ""))
        self.assertEqual(data["note"], "Versions 1 and 2 read the same as Markdown.")

    def test_a_version_that_the_page_does_not_have_is_not_found(self):
        for argv in (("diff", "2002", "--from", "9"), ("diff", "2002", "--to", "9"), ("diff", "2002", "--from", "1", "--to", "7")):
            with self.subTest(argv=argv):
                result = self.cli(*argv)
                self.assertEqual(result.code, 4)
                self.assertIn("conflu versions 2002", result.err)
        self.assertEqual([item for item in self.targets() if "version=9" in item or "version=7" in item], [])  # a number above the newest is known without asking

    def test_what_is_wrong_sends_nothing(self):
        for argv in (("diff", "2002", "--to", "abc"), ("diff", "2002", "--context", "-1"), ("diff", "../2002"), ("diff", "2002", "--from", "0"), ("diff", "2002", "--max-chars", "-1")):
            with self.subTest(argv=argv):
                self.assertNotEqual(self.cli(*argv).code, 0)
        self.assertEqual(self.mock.requests, [])

    def test_people_in_titles_and_messages_are_hidden(self):
        self.mock.pages["2002"]["versions"][1]["message"] = "Mail alex@example.com"
        data = self.cli("diff", "2002", "--json").json()
        self.assertEqual(data["from"]["message"], "Mail [email]")
        self.assertNotIn("alex@example.com", json.dumps(data))
        self.assertNotIn(ACCOUNT, json.dumps(data))


class RestoreTest(HistoryFlow):
    def test_a_dry_run_reads_and_sends_nothing(self):
        result = self.cli("restore", "2002", "--version", "1", "--dry-run", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.targets(), ["GET /api/v2/pages/2002?include-labels=true&body-format=storage", "GET /api/v2/pages/2002?version=1&body-format=storage"])
        self.assertEqual(self.writes(), [])
        data = result.json()
        self.assertEqual((data["dryRun"], data["versionFrom"], data["versionTo"]), (True, 3, 4))
        self.assertEqual(len(self.mock.pages["2002"]["versions"]), 3)
        text = self.cli("restore", "2002", "--version", "1", "--dry-run").out
        self.assertIn("Dry run: version 1 of page 2002 'Release notes' would come back as version 4; nothing was sent", text)
        self.assertEqual(self.writes(), [])

    def test_the_real_run_sends_the_request_of_the_dry_run_and_reads_the_page_back(self):
        preview = self.cli("restore", "2002", "--version", "1", "--message", "Back to the draft", "--dry-run", "--json").json()["payload"]
        before = len(self.mock.requests)
        result = self.cli("restore", "2002", "--version", "1", "--message", "Back to the draft", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(
            self.targets()[before:],
            [
                "GET /api/v2/pages/2002?include-labels=true&body-format=storage",
                "GET /api/v2/pages/2002?version=1&body-format=storage",
                "POST /rest/api/content/2002/version",
                "GET /api/v2/pages/2002?include-labels=true",
            ],
        )
        sent = [item for item in self.mock.requests if item.method == "POST"]
        self.assertEqual([item.body for item in sent], [preview])
        self.assertEqual(preview, {"operationKey": "restore", "params": {"versionNumber": 1, "message": "Back to the draft", "restoreTitle": False}})
        data = result.json()
        self.assertEqual((data["dryRun"], data["restoredVersion"], data["versionFrom"], data["versionTo"], data["payload"]), (False, 1, 3, 4, preview))

    def test_it_makes_a_new_version_and_every_old_one_stays(self):
        self.cli("restore", "2002", "--version", "1")
        versions = self.mock.pages["2002"]["versions"]
        self.assertEqual([item["number"] for item in versions], [1, 2, 3, 4])
        self.assertEqual((versions[-1]["message"], versions[-1]["body"]), ("Restored version 1", FIRST_BODY))
        self.assertEqual((versions[1]["body"], "alex@example.com" in versions[2]["body"], "toc" in versions[2]["body"]), (SECOND_BODY, True, True))
        listed = self.cli("versions", "2002", "--all", "--json").json()
        self.assertEqual([item["number"] for item in listed["versions"]], [4, 3, 2, 1])
        self.assertEqual(self.mock.pages["2002"]["title"], "Release notes")

    def test_the_body_comes_back_as_it_was_with_its_mention_and_its_macro(self):
        self.cli("restore", "2002", "--version", "2")
        self.assertEqual(self.mock.pages["2002"]["versions"][-1]["body"], SECOND_BODY)  # the mention, byte for byte
        self.assertIn(ACCOUNT, self.mock.pages["2002"]["versions"][-1]["body"])
        original = self.version_body(3)
        self.cli("restore", "2002", "--version", "3")
        self.assertEqual(self.mock.pages["2002"]["versions"][-1]["body"], original)  # the macro and the address came back too
        self.assertIn('ac:name="toc"', original)
        self.assertEqual([item["number"] for item in self.mock.pages["2002"]["versions"]], [1, 2, 3, 4, 5])

    def test_the_request_holds_no_content(self):
        self.cli("restore", "2002", "--version", "2")
        posted = [item for item in self.mock.requests if item.method == "POST" and item.path == "/rest/api/content/2002/version"][0]
        self.assertEqual(set(posted.body), {"operationKey", "params"})
        self.assertEqual(set(posted.body["params"]), {"versionNumber", "message", "restoreTitle"})
        self.assertNotIn(ACCOUNT, json.dumps(posted.body))

    def test_the_old_title_comes_back_only_when_asked_for(self):
        self.cli("restore", "2002", "--version", "1")
        self.assertEqual(self.mock.pages["2002"]["title"], "Release notes")
        data = self.cli("restore", "2002", "--version", "1", "--restore-title", "--json").json()
        self.assertEqual((self.mock.pages["2002"]["title"], data["title"], data["payload"]["params"]["restoreTitle"]), ("Release notes (draft)", "Release notes (draft)", True))

    def test_a_title_that_is_taken_is_refused_by_confluence_and_nothing_is_saved(self):
        self.mock.add_page("ENG", "Release notes (draft)", "<p>Other.</p>")
        result = self.cli("restore", "2002", "--version", "1", "--restore-title")
        self.assertEqual(result.code, 6)
        self.assertIn("A page already exists with the same TITLE", result.err)
        self.assertEqual(len(self.mock.pages["2002"]["versions"]), 3)

    def test_the_message_defaults_to_the_version(self):
        self.cli("restore", "2002", "--version", "2")
        self.assertEqual(self.mock.pages["2002"]["versions"][-1]["message"], "Restored version 2")

    def test_the_version_that_was_read_is_checked_before_the_restore(self):
        result = self.cli("restore", "2002", "--version", "1", "--if-version", "2")
        self.assertEqual(result.code, 3)
        self.assertIn("Page 2002 is at version 3, not 2.", result.err)
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.cli("restore", "2002", "--version", "1", "--if-version", "2", "--dry-run").code, 3)
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.cli("restore", "2002", "--version", "1", "--if-version", "3").code, 0)

    def test_the_time_that_was_read_is_checked_before_the_restore(self):
        result = self.cli("restore", "2002", "--version", "1", "--if-unchanged-since", "2026-10-09T00:00:00Z")
        self.assertEqual(result.code, 3)
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.cli("restore", "2002", "--version", "1", "--if-unchanged-since", "2026-10-10T09:00:00.000Z").code, 0)
        self.assertEqual(len(self.writes()), 1)

    def test_an_empty_guard_is_refused_and_asks_and_sends_nothing_in_a_dry_run_too(self):
        for extra in ((), ("--dry-run",)):
            with self.subTest(dry_run=bool(extra)):
                result = self.cli("restore", "2002", "--version", "1", "--if-unchanged-since", "", *extra)
                self.assertEqual(result.code, 1, result.err)
                self.assertIn("--if-unchanged-since: Not an ISO 8601 timestamp: ''", result.err)
        self.assertEqual(self.mock.requests, [])
        self.assertEqual(len(self.mock.pages["2002"]["versions"]), 3)

    def test_somebody_who_saves_between_the_read_and_the_restore_is_a_conflict_of_confluence(self):
        self.mock.fail_next("/rest/api/content/2002/version", 409, method="POST")
        result = self.cli("restore", "2002", "--version", "1")
        self.assertEqual(result.code, 3)
        self.assertEqual(len(self.mock.pages["2002"]["versions"]), 3)

    def test_the_current_version_and_a_version_that_does_not_exist_are_refused_without_a_write(self):
        current = self.cli("restore", "2002", "--version", "3")
        self.assertEqual(current.code, 2)
        self.assertIn("nothing to restore", current.err)
        missing = self.cli("restore", "2002", "--version", "9")
        self.assertEqual(missing.code, 4)
        self.assertIn("The page is at version 3.", missing.err)
        self.assertEqual(self.writes(), [])

    def test_a_page_that_is_not_current_is_not_restored(self):
        self.mock.pages["2002"]["status"] = "trashed"
        result = self.cli("restore", "2002", "--version", "1")
        self.assertEqual(result.code, 1)
        self.assertIn("Page 2002 is trashed and is not restored.", result.err)
        self.assertEqual(self.writes(), [])

    def test_the_id_of_a_folder_and_hostile_ids_send_no_write(self):
        self.assertEqual(self.cli("restore", "7001", "--version", "1").code, 4)
        for ref in ("", "../2002", "2002;2003", "abc", "1" * 20):
            with self.subTest(ref=ref):
                self.assertNotEqual(self.cli("restore", ref, "--version", "1").code, 0)
        self.assertEqual(self.writes(), [])

    def test_the_answer_names_nobody(self):
        self.mock.pages["2002"]["title"] = "Notes of alex@example.com"
        data = self.cli("restore", "2002", "--version", "2", "--dry-run", "--json").json()
        self.assertEqual((data["title"], data["url"]), ("Notes of [email]", f"{self.mock.base_url}/spaces/ENG/pages/2002"))
        self.assertNotIn("alex", json.dumps(data))

    def test_what_was_sent_is_what_the_documents_list(self):
        self.cli("restore", "2002", "--version", "1")
        self.assertEqual(self.mock.unknown_endpoints, [])
        self.assertEqual(self.mock.deprecated_endpoints, [])
        self.assertIn("POST /rest/api/content/{id}/version", self.mock.used_endpoints)


class GatewayTest(GatewayCase):
    """The REST calls of the area, one by one, with what the gateway makes of the answers."""

    def test_an_earlier_version_has_its_title_its_body_and_its_version(self):
        first = self.gw.get_page_version("2002", 1)
        self.assertEqual((first.id, first.title, first.version_number, first.version.message, first.body), ("2002", "Release notes (draft)", 1, "Created", FIRST_BODY))
        self.assertEqual(self.mock.requests[-1].query, {"version": ["1"], "body-format": ["storage"]})
        self.assertEqual(self.mock.requests[-1].path, "/api/v2/pages/2002")
        self.assertEqual(self.gw.get_page_version("2002", 2).body, SECOND_BODY)
        current = self.gw.get_page_version("2002", 3)
        self.assertEqual((current.title, current.version_number), ("Release notes", 3))
        self.assertEqual(first.labels, [])  # a version has none: the page's are read apart

    def test_a_version_without_its_body_does_not_ask_for_it(self):
        page = self.gw.get_page_version("2002", 2, with_body=False)
        self.assertIsNone(page.body)
        self.assertEqual(self.mock.requests[-1].query, {"version": ["2"]})

    def test_a_version_that_is_not_there_and_a_page_that_is_not_there_are_not_found(self):
        for page, number in (("2002", 9), ("2002", 0), ("99999", 1), ("7001", 1)):
            with self.subTest(page=page, version=number):
                with self.assertRaises(NotFoundError):
                    self.gw.get_page_version(page, number)

    def test_several_pages_come_with_one_request_and_what_does_not_exist_is_left_out(self):
        self.mock.page_cap = 1000
        found = self.gw.get_pages(["2003", "2002", "999", "2004"], with_body=True)
        self.assertEqual(([page.id for page in found.items], found.cursor), (["2002", "2003", "2004"], ""))  # the mock orders them by id: the use case puts them back in the order asked for
        self.assertEqual(len(self.mock.requests), 1)
        self.assertEqual(self.mock.requests[0].query, {"id": ["2003,2002,999,2004"], "body-format": ["storage"], "limit": ["250"]})
        self.assertTrue(all(page.body is not None and page.labels == [] for page in found.items))
        self.assertIsNone(self.gw.get_pages(["2002"]).items[0].body)
        self.assertEqual(self.gw.get_pages(["999"]).items, [])

    def test_an_answer_that_does_not_fit_has_a_cursor_for_the_rest(self):
        first = self.gw.get_pages(["2001", "2002", "2003"], limit=250)
        self.assertEqual(([page.id for page in first.items], first.cursor), (["2001", "2002"], "2"))
        rest = self.gw.get_pages(["2001", "2002", "2003"], limit=250, cursor=first.cursor)
        self.assertEqual(([page.id for page in rest.items], rest.cursor), (["2003"], ""))
        self.mock.pages["2003"]["status"] = "trashed"
        self.mock.pages["2002"]["status"] = "archived"
        self.mock.page_cap = 1000
        self.assertEqual([(page.id, page.status) for page in self.gw.get_pages(["2001", "2002", "2003"]).items], [("2001", "current"), ("2002", "archived")])  # a trashed page is left out

    def test_a_restore_returns_the_number_of_the_version_it_made(self):
        number = self.gw.restore_page_version("2002", restore_payload(1, "Back to the draft"))
        self.assertEqual(number, 4)
        sent = self.mock.requests[-1]
        self.assertEqual((sent.method, sent.path, sent.body), ("POST", "/rest/api/content/2002/version", {"operationKey": "restore", "params": {"versionNumber": 1, "message": "Back to the draft", "restoreTitle": False}}))
        self.assertEqual(self.gw.restore_page_version("2002", restore_payload(2, "Again", True)), 5)
        self.assertEqual(self.mock.pages["2002"]["versions"][-1]["message"], "Again")

    def test_what_confluence_refuses_is_the_error_of_that_kind(self):
        with self.assertRaises(NotFoundError):
            self.gw.restore_page_version("2002", restore_payload(9, "m"))
        with self.assertRaises(NotFoundError):
            self.gw.restore_page_version("99999", restore_payload(1, "m"))
        with self.assertRaises(RejectedError):
            self.gw.restore_page_version("2002", {"operationKey": "restore", "params": {"versionNumber": 1}})  # no message
        with self.assertRaises(RejectedError):
            self.gw.restore_page_version("2002", {"operationKey": "delete", "params": {"versionNumber": 1, "message": "m"}})
        self.mock.fail_next("/rest/api/content/2002/version", 409, method="POST")
        with self.assertRaises(ConflictError):
            self.gw.restore_page_version("2002", restore_payload(1, "m"))
        self.assertEqual(len(self.mock.pages["2002"]["versions"]), 3)

    def test_an_answer_that_names_no_number_is_zero(self):
        self.mock.fail_next("/rest/api/content/2002/version", 200, method="POST", body={"message": "done"})
        self.assertEqual(self.gw.restore_page_version("2002", restore_payload(1, "m")), 0)
        self.assertEqual(len(self.mock.pages["2002"]["versions"]), 3)  # that answer was injected: nothing was saved

    def test_only_the_calls_that_the_documents_list_were_made(self):
        self.gw.get_page_version("2002", 1)
        self.gw.get_pages(["2002"])
        self.gw.restore_page_version("2002", restore_payload(1, "m"))
        self.assertEqual((self.mock.unknown_endpoints, self.mock.deprecated_endpoints), ([], []))
        self.assertEqual(sorted(self.mock.used_endpoints), ["GET /api/v2/pages", "GET /api/v2/pages/{id}", "POST /rest/api/content/{id}/version"])
