"""Attachments, the real program against the mock Confluence: the requests that are really sent, the versions, the blog posts, the guards, hostile names and hostile content."""
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from conflu_c_cli.adapters.driven import atomic, http_transport
from conflu_c_cli.adapters.driven.confluence_rest import RestConfluenceGateway
from conflu_c_cli.adapters.driven.http_transport import HttpTransport
from conflu_c_cli.application.settings import Settings
from conflu_c_cli.domain.errors import NotFoundError, UnavailableError, ValidationError
from conflu_c_cli.domain.model import Attachment
from tests.integration.test_end_to_end import EndToEnd
from tests.support.attachment_data import AGENDA, PLAN, Edition
from tests.support.mock_attachments import AttachmentsRoutes
from tests.support.mock_confluence import _ApiHandler, _MediaHandler
from tests.support.office_files import docx, para, zipped

TOKEN = "test-token"


def page_downloads(mock_confluence, holder="2004"):
    return [item for item in mock_confluence.requests if item.method == "GET" and item.path.startswith(f"/rest/api/content/{holder}/child/attachment/") and item.path.endswith("/download")]


class AttachmentFlow(EndToEnd):
    def setUp(self):
        super().setUp()
        self.area = self.mock.area(AttachmentsRoutes)
        self.out = self.root / "out"

    def writes(self):
        """What the program sent that changes something: `POST /content/convert-ids-to-types` and `POST /users-bulk` only read."""
        reads = ("/api/v2/content/convert-ids-to-types", "/api/v2/users-bulk")
        return [item for item in self.mock.requests if item.method != "GET" and item.path not in reads]

    def tree(self, folder=None):
        folder = folder or self.root
        return sorted(str(path.relative_to(folder)).replace("\\", "/") for path in folder.rglob("*") if path.is_file())

    def put_config(self):
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_text(f"CONFLUENCE_EMAIL={self.mock.email}\nCONFLUENCE_API_TOKEN={TOKEN}\n", encoding="utf-8")
        return self.config


class ListingTest(AttachmentFlow):
    def test_a_page_is_one_request_and_a_blog_post_is_found_by_asking_what_the_id_is(self):
        self.mock.page_cap = 100
        self.assertEqual(self.cli("attachments", "2004", "--all", "--json").code, 0)
        self.assertEqual([item.path for item in self.mock.requests], ["/api/v2/pages/2004/attachments"])
        self.mock.requests.clear()
        result = self.cli("attachments", "7102", "--all", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual([(item.method, item.path) for item in self.mock.requests], [
            ("GET", "/api/v2/pages/7102/attachments"),
            ("POST", "/api/v2/content/convert-ids-to-types"),
            ("GET", "/api/v2/blogposts/7102/attachments"),
        ])
        data = result.json()
        self.assertEqual((data["pageId"], data["blogPostId"], [item["title"] for item in data["attachments"]]), (None, "7102", ["agenda.txt", "minutes.md"]))
        self.assertEqual({item["blogPostId"] for item in data["attachments"]}, {"7102"})

    def test_a_blog_post_is_pageable_by_cursor(self):
        self.mock.page_cap = 1
        first = self.cli("attachments", "7102", "--limit", "1", "--json").json()
        self.assertEqual(([item["id"] for item in first["attachments"]], first["nextCursor"]), (["att5111"], "1"))
        second = self.cli("attachments", "7102", "--limit", "1", "--cursor", first["nextCursor"], "--json").json()
        self.assertEqual(([item["id"] for item in second["attachments"]], second["nextCursor"]), (["att5112"], None))

    def test_a_name_is_looked_for_by_the_service_for_a_page_and_for_a_blog_post(self):
        self.cli("attachments", "2004", "--name", "plan.txt")
        self.assertEqual(self.sent("GET", "/api/v2/pages/2004/attachments")[0].query, {"filename": ["plan.txt"], "limit": ["50"]})
        self.cli("attachments", "7102", "--name", "minutes.md")
        self.assertEqual(self.sent("GET", "/api/v2/blogposts/7102/attachments")[0].query, {"filename": ["minutes.md"], "limit": ["50"]})

    def test_the_id_of_a_folder_and_the_id_of_nothing(self):
        folder = self.cli("attachments", "7001")
        self.assertEqual(folder.code, 4)
        self.assertIn("a folder", folder.err)
        self.assertEqual(self.cli("attachments", "999").code, 4)

    def test_names_and_comments_with_an_address_are_redacted_unless_people_are_asked_for(self):
        self.area.add_attachment("2004", "alex@example.com.txt", [Edition(b"x", created="2026-10-20T09:00:00.000Z")], "text/plain", comment="from alex@example.com")
        hidden = self.cli("attachments", "2004", "--all", "--json").json()["attachments"][-1]
        self.assertEqual((hidden["title"], hidden["comment"]), ("[email]", "from [email]"))
        self.assertEqual(hidden["downloadLink"], "/download/attachments/2004?version=1&modificationDate=0&api=v2")  # the address that Confluence gives ends in the name
        shown = self.cli("attachments", "2004", "--all", "--with-users", "--json").json()["attachments"][-1]
        self.assertEqual((shown["title"], shown["comment"]), ("alex@example.com.txt", "from alex@example.com"))
        self.assertEqual(shown["downloadLink"], "/download/attachments/2004/alex%40example.com.txt?version=1&modificationDate=0&api=v2")
        one = self.cli("attachment", hidden["id"], "--json")
        self.assertNotIn("example.com", one.out)
        self.assertNotIn("alex", self.cli("attachment", hidden["id"]).out.lower())
        refused = self.cli("attachments", "2004", "--with-users", env={"CONFLUENCE_HIDE_USERS": "true"})
        self.assertEqual(refused.code, 1)


class OneAttachmentTest(AttachmentFlow):
    def test_the_requests_of_the_properties_the_versions_and_the_labels(self):
        result = self.cli("attachment", "att5101", "--versions", "--labels", "--all", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual([(item.path, item.query) for item in self.mock.requests], [
            ("/api/v2/attachments/att5101", {}),
            ("/api/v2/attachments/att5101/versions", {"sort": ["-modified-date"], "limit": ["100"]}),
            ("/api/v2/attachments/att5101/versions", {"sort": ["-modified-date"], "limit": ["100"], "cursor": ["2"]}),
            ("/api/v2/attachments/att5101", {"version": ["2"]}),  # the size of an older version is the one thing that the list does not say
            ("/api/v2/attachments/att5101", {"version": ["1"]}),
            ("/api/v2/attachments/5101/labels", {"limit": ["100"]}),  # the document types the id of this one call as an integer
        ])
        data = result.json()
        self.assertEqual([(version["number"], version["size"], version["message"]) for version in data["versions"]], [
            (3, len(PLAN[2].data), ""), (2, len(PLAN[1].data), "Added the contact"), (1, len(PLAN[0].data), "First draft"),
        ])
        self.assertEqual([label["name"] for label in data["labels"]], ["draft", "plan"])
        self.assertEqual(data["updated"], "2026-10-09T14:00:00.000Z")

    def test_an_attachment_of_a_blog_post_is_shown_with_its_blog_post(self):
        data = self.cli("attachment", "att5111", "--versions", "--json").json()
        self.assertEqual((data["pageId"], data["blogPostId"], data["version"]), (None, "7102", 2))
        self.assertEqual([(version["number"], version["message"], version["size"]) for version in data["versions"]], [(2, "Added the items", len(AGENDA[1].data)), (1, "Draft", len(AGENDA[0].data))])

    def test_who_saved_a_version_costs_one_lookup_and_only_when_asked_for(self):
        self.cli("attachment", "att5101", "--versions", "--json")
        self.assertEqual(self.sent("POST", "/api/v2/users-bulk"), [])
        shown = self.cli("attachment", "att5101", "--versions", "--with-users", "--json").json()
        self.assertEqual(len(self.sent("POST", "/api/v2/users-bulk")), 1)
        self.assertEqual({version["author"]["displayName"] for version in shown["versions"]}, {"Alex Example"})
        refused = self.cli("attachment", "att5101", "--versions", "--with-users", env={"CONFLUENCE_HIDE_USERS": "true"})
        self.assertEqual(refused.code, 1)

    def test_a_version_the_list_names_and_cannot_be_read_leaves_the_size_unknown(self):
        self.mock.fail_next("/api/v2/attachments/att5101", 404, times=1, method="GET")  # the first request is the properties: let it be the version lookup instead
        self.mock.requests.clear()
        self.assertEqual(self.cli("attachment", "att5101", "--json").code, 4)

    def test_what_confluence_refuses_is_an_exit_code(self):
        self.mock.fail_next("/api/v2/attachments/att5101/versions", 403)
        denied = self.cli("attachment", "att5101", "--versions")
        self.assertEqual(denied.code, 5)
        self.mock.fail_next("/api/v2/attachments/att5101", 503, times=3)
        self.assertEqual(self.cli("attachment", "att5101").code, 7)
        self.assertEqual(self.cli("attachment", "att99999").code, 4)
        for result in (denied,):
            self.assertNotIn(TOKEN, result.err + result.out)


class DownloadTest(AttachmentFlow):
    def test_a_file_arrives_through_the_media_service_without_the_credentials(self):
        result = self.cli("download", "att5101", "--out", str(self.out), "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual((self.out / "plan.txt").read_bytes(), PLAN[2].data)
        asked = page_downloads(self.mock)
        self.assertEqual([(item.path, item.query) for item in asked], [("/rest/api/content/2004/child/attachment/att5101/download", {})])
        self.assertIn("authorization", asked[0].headers)
        self.assertTrue(self.mock.media_requests)
        self.assertTrue(all("authorization" not in item.headers for item in self.mock.media_requests))
        self.assertEqual(result.json()["files"][0]["version"], 3)

    def test_a_version_is_asked_for_by_its_number_and_is_the_bytes_of_that_version(self):
        for number, edition in enumerate(PLAN, 1):
            folder = self.root / f"v{number}"
            result = self.cli("download", "att5101", "--version", str(number), "--out", str(folder))
            self.assertEqual(result.code, 0, result.err)
            self.assertEqual((folder / "plan.txt").read_bytes(), edition.data, number)
        self.assertEqual([item.query for item in page_downloads(self.mock)], [{"version": ["1"]}, {"version": ["2"]}, {"version": ["3"]}])
        self.assertEqual([item.query["version"] for item in self.mock.media_requests], [["1"], ["2"], ["3"]])
        self.assertTrue(all("authorization" not in item.headers for item in self.mock.media_requests))

    def test_a_version_that_is_not_there_is_not_found_and_nothing_is_written(self):
        self.mock.requests.clear()
        result = self.cli("download", "att5101", "--version", "9", "--out", str(self.out))
        self.assertEqual(result.code, 4)
        self.assertIn("conflu attachment att5101 --versions", result.err)
        self.assertEqual((self.tree(), page_downloads(self.mock)), ([], []))

    def test_a_version_that_the_list_names_and_the_service_cannot_serve_is_an_error_and_not_a_half_file(self):
        self.area.add_version("att5101", b"version four")
        del self.mock.attachments["att5101"]["versions"][1]  # version 2 is gone for the media service, as a purged one would be
        result = self.cli("download", "att5101", "--version", "2", "--out", str(self.out))
        self.assertEqual(result.code, 4)
        self.assertEqual(self.tree(), [])

    def test_the_files_of_a_blog_post_by_name_by_version_and_all_of_them(self):
        result = self.cli("download", "7102", "--all", "--out", str(self.out))
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual((self.out / "agenda.txt").read_bytes(), AGENDA[1].data)
        self.assertEqual((self.out / "minutes.md").read_bytes(), b"# Minutes\n\nDecisions were made.\n")
        self.assertEqual(sorted(item.path for item in page_downloads(self.mock, "7102")), ["/rest/api/content/7102/child/attachment/att5111/download", "/rest/api/content/7102/child/attachment/att5112/download"])
        older = self.cli("download", "7102", "--name", "agenda.txt", "--version", "1", "--out", str(self.root / "old"))
        self.assertEqual(older.code, 0, older.err)
        self.assertEqual((self.root / "old" / "agenda.txt").read_bytes(), AGENDA[0].data)
        self.assertEqual(page_downloads(self.mock, "7102")[-1].query, {"version": ["1"]})

    def test_an_address_in_an_answer_is_never_a_place_to_send_the_credentials_to(self):
        self.mock._attachment_download_path = lambda attachment, version=None: "https://evil.example/steal?token=1"
        shown = self.cli("attachment", "att5101", "--json").json()
        self.assertEqual(shown["downloadLink"], "https://evil.example/steal?token=1")  # the address as the answer gives it, shown and never used
        result = self.cli("download", "att5101", "--out", str(self.out))
        self.assertEqual(result.code, 0, result.err)  # a request to that host could not have succeeded
        self.assertEqual((self.out / "plan.txt").read_bytes(), PLAN[2].data)
        self.assertEqual([item.path for item in page_downloads(self.mock)], ["/rest/api/content/2004/child/attachment/att5101/download"])
        self.assertTrue(all("authorization" not in item.headers for item in self.mock.media_requests))
        self.assertEqual((self.mock.unknown_endpoints, self.mock.deprecated_endpoints), ([], []))

    def test_a_file_over_max_bytes_is_refused_by_its_size_before_the_file_is_asked_for(self):
        self.mock.requests.clear()
        result = self.cli("download", "2004", "--all", "--out", str(self.out), "--max-bytes", "100")
        self.assertEqual(result.code, 1)
        self.assertIn("--max-bytes 100", result.err)
        self.assertEqual((page_downloads(self.mock), self.tree(), self.mock.media_requests), ([], [], []))

    def test_a_dry_run_asks_for_no_file_and_writes_nothing(self):
        result = self.cli("download", "2004", "--all", "--out", str(self.out), "--dry-run", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual({item["action"] for item in result.json()["files"]}, {"would download"})
        self.assertEqual((page_downloads(self.mock), self.mock.media_requests, self.tree()), ([], [], []))

    def test_a_file_that_is_there_is_never_replaced_without_force_and_a_replacement_is_whole(self):
        self.out.mkdir()
        (self.out / "plan.txt").write_bytes(b"mine")
        refused = self.cli("download", "att5101", "--out", str(self.out))
        self.assertEqual(refused.code, 1)
        self.assertEqual((self.out / "plan.txt").read_bytes(), b"mine")
        self.assertEqual(self.cli("download", "att5101", "--out", str(self.out), "--force").code, 0)
        self.assertEqual((self.out / "plan.txt").read_bytes(), PLAN[2].data)
        self.assertEqual(self.tree(self.out), ["plan.txt"])  # no temporary file is left behind

    def test_a_write_that_fails_leaves_the_old_file_and_no_temporary_file(self):
        self.out.mkdir()
        (self.out / "plan.txt").write_bytes(b"mine")
        with mock.patch.object(atomic.os, "replace", side_effect=OSError(13, "Permission denied")):
            result = self.cli("download", "att5101", "--out", str(self.out), "--force")
        self.assertEqual(result.code, 1)
        self.assertIn("Cannot write", result.err)
        self.assertEqual((self.out / "plan.txt").read_bytes(), b"mine")
        self.assertEqual(self.tree(self.out), ["plan.txt"])

    def test_a_server_error_that_does_not_go_away_is_exit_code_7_and_writes_nothing(self):
        self.mock.fail_next("/rest/api/content/2004/child/attachment/att5101/download", 503)
        result = self.cli("download", "att5101", "--out", str(self.out), env={"CONFLUENCE_RETRY": "0"})
        self.assertEqual(result.code, 7, result.err)
        self.assertEqual(self.tree(), [])

    def test_a_file_that_arrives_incomplete_is_not_written(self):
        # The media service says how long the file is and ends the transfer half way. The transport hands over the short body without a word (it
        # is what http.client does), so the one that finds out is the download: Confluence listed the whole size.
        def cut_off(handler, status, body=b"", headers=None, content_type="application/octet-stream"):
            handler.send_response(status)
            handler.send_header("Content-Type", content_type)
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body[: len(body) // 2])
            handler.close_connection = True

        size = len(PLAN[2].data)
        with mock.patch.object(_MediaHandler, "_reply_bytes", cut_off):
            result = self.cli("download", "att5101", "--out", str(self.out), env={"CONFLUENCE_RETRY": "0"})
        self.assertEqual(result.code, 7, result.err)
        self.assertIn("incomplete", result.err.lower())
        self.assertIn(f"{size // 2} of {size} bytes", result.err)
        self.assertEqual((self.tree(), len(self.mock.media_requests)), ([], 1))  # it was fetched, and nothing of it is left: not the file, not a temporary one
        ok = self.cli("download", "att5101", "--out", str(self.out))  # the same file when the transfer is whole
        self.assertEqual(ok.code, 0, ok.err)
        self.assertEqual((self.out / "plan.txt").read_bytes(), PLAN[2].data)

    def test_a_file_that_arrives_shorter_than_listed_is_not_written_whichever_way_the_listing_is_wrong(self):
        make_model = _ApiHandler._attachment_model

        def overstated(handler, attachment, **kwargs):
            model = make_model(handler, attachment, **kwargs)
            model["fileSize"] += 10  # Confluence says that the file has ten bytes more than the media service sends
            return model

        size = len(PLAN[2].data)
        with mock.patch.object(_ApiHandler, "_attachment_model", overstated):
            result = self.cli("download", "att5101", "--out", str(self.out), env={"CONFLUENCE_RETRY": "0"})
        self.assertEqual(result.code, 7, result.err)
        self.assertIn(f"plan.txt arrived incomplete ({size} of {size + 10} bytes); nothing was written for it.", result.err)
        self.assertEqual(self.tree(), [])

    def test_the_names_that_strangers_give_files_are_made_safe_and_nothing_leaves_the_folder(self):
        names = ["../../evil.txt", "..\\..\\evil2.txt", "con.txt", "a:b.txt", "trailing dot.", "tab\tname.txt", "x\u202egnp.exe", "/etc/passwd", "C:\\Windows\\system.ini", "nul", "a" * 100 + ".txt"]
        for number, name in enumerate(names):
            self.area.add_attachment("2003", name, [Edition(f"data {number}".encode(), created="2026-10-20T09:00:00.000Z")], "text/plain")
        self.mock.page_cap = 100
        result = self.cli("download", "2003", "--all", "--out", str(self.out), "--json")
        self.assertEqual(result.code, 0, result.err)
        written = self.tree()
        self.assertEqual(len(written), len(names))
        self.assertTrue(all(path.startswith("out/") and path.count("/") == 1 for path in written), written)  # everything is in the one folder
        files = {Path(item["path"]).name: item for item in result.json()["files"]}
        for item in result.json()["files"]:
            self.assertEqual(Path(item["path"]).parent.name, "out")
            self.assertFalse(any(char in Path(item["path"]).name for char in '<>:"/\\|?*\t\u202e'), item["path"])
        self.assertIn("evil.txt", files)
        self.assertIn("_con.txt", files)
        self.assertFalse((self.root / "evil.txt").exists() or (self.root.parent / "evil.txt").exists())

    def test_two_names_that_become_one_file_are_refused_before_anything_is_written(self):
        self.area.add_attachment("2003", "a:b.txt", [Edition(b"one", created="2026-10-20T09:00:00.000Z")], "text/plain")
        self.area.add_attachment("2003", "a_b.txt", [Edition(b"two", created="2026-10-20T09:00:00.000Z")], "text/plain")
        result = self.cli("download", "2003", "--all", "--out", str(self.out))
        self.assertEqual(result.code, 1)
        self.assertEqual((self.tree(), page_downloads(self.mock, "2003")), ([], []))

    def test_a_file_that_would_be_written_into_the_folder_of_the_configuration_is_refused_whatever_the_options(self):
        config = self.put_config()
        folder = config.parent
        for extra in ((), ("--force",), ("--dry-run",), ("--force", "--dry-run")):
            result = self.cli("download", "att5101", "--out", str(folder), *extra)
            self.assertEqual(result.code, 2, extra)
            self.assertIn("--out", result.err)
        sideways = self.cli("download", "att5101", "--out", str(folder / ".." / folder.name), "--force")
        self.assertEqual(sideways.code, 2)
        self.assertEqual(config.read_text(encoding="utf-8"), f"CONFLUENCE_EMAIL={self.mock.email}\nCONFLUENCE_API_TOKEN={TOKEN}\n")
        self.assertEqual(page_downloads(self.mock), [])
        below = self.cli("download", "att5101", "--out", str(folder / "downloads"))
        self.assertEqual(below.code, 0, below.err)

    def test_an_attachment_named_like_the_configuration_cannot_replace_it(self):
        config = self.put_config()
        self.area.add_attachment("2003", "config", [Edition(b"CONFLUENCE_BASE_URL=https://evil.example\n", created="2026-10-20T09:00:00.000Z")], "text/plain")
        result = self.cli("download", "2003", "--name", "config", "--out", str(config.parent), "--force")
        self.assertEqual(result.code, 2)
        self.assertNotIn("evil", config.read_text(encoding="utf-8"))

    def test_a_link_to_the_folder_of_the_configuration_does_not_help(self):
        config = self.put_config()
        link = self.root / "shortcut"
        try:
            os.symlink(config.parent, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("this system does not let a test make a symbolic link")
        self.assertEqual(self.cli("download", "att5101", "--out", str(link), "--force").code, 2)
        self.assertEqual(self.cli("download", "att5101", "--out", str(link / "sub")).code, 0)

    def test_an_error_never_shows_the_token(self):
        self.mock.fail_next("/rest/api/content/2004/child/attachment/att5101/download", 403, body={"message": f"Authorization: Basic ... {TOKEN}"})
        result = self.cli("download", "att5101", "--out", str(self.out))
        self.assertEqual(result.code, 5)
        self.assertNotIn(TOKEN, result.err + result.out)


class TextTest(AttachmentFlow):
    def test_the_text_of_files_and_documents_goes_to_standard_output_and_nothing_is_saved(self):
        result = self.cli("download", "2004", "--all", "--text", "--json")
        self.assertEqual(result.code, 0, result.err)
        entries = {item["name"]: item for item in result.json()["files"]}
        self.assertEqual({name: (item["kind"], item["action"]) for name, item in entries.items()}, {
            "plan.txt": ("text", "read"), "spec.docx": ("document", "read"), "budget.xlsx": ("document", "read"),
            "deck.pptx": ("document", "read"), "contacts.csv": ("text", "read"), "broken.docx": ("document", "not text"),
        })
        self.assertEqual(entries["plan.txt"]["text"], PLAN[2].data.decode())
        self.assertIn("# Specification", entries["spec.docx"]["text"])
        self.assertIn("Hardware\t1200", entries["budget.xlsx"]["text"])
        self.assertIn("Say hello.", entries["deck.pptx"]["text"])
        self.assertNotIn("alex@example.com", result.out)
        self.assertIn("[email]", entries["contacts.csv"]["text"])
        self.assertIn("no Office Open XML document", entries["broken.docx"]["hint"])
        self.assertEqual(self.tree(), [])

    def test_people_are_kept_only_on_request(self):
        shown = self.cli("download", "att5105", "--text", "--with-users", "--json").json()["files"][0]
        self.assertIn("alex@example.com", shown["text"])

    def test_a_version_of_a_file_and_a_blog_post_file(self):
        first = self.cli("download", "att5101", "--text", "--version", "1", "--json").json()["files"][0]
        self.assertEqual((first["text"], first["version"], first["size"]), (PLAN[0].data.decode(), 1, len(PLAN[0].data)))
        blog = self.cli("download", "7102", "--name", "agenda.txt", "--text", "--version", "1", "--json").json()["files"][0]
        self.assertEqual(blog["text"], AGENDA[0].data.decode())
        self.assertEqual(page_downloads(self.mock, "7102")[-1].query, {"version": ["1"]})

    def test_a_picture_is_not_fetched(self):
        self.mock.requests.clear()
        entry = self.cli("download", "att5001", "--text", "--json").json()["files"][0]
        self.assertEqual((entry["kind"], entry["action"], entry["text"]), ("other", "not text", None))
        self.assertEqual((page_downloads(self.mock, "2002"), self.mock.media_requests), ([], []))

    def test_a_file_over_the_limit_is_refused_before_it_is_fetched_and_a_dry_run_fetches_nothing(self):
        self.mock.requests.clear()
        self.assertEqual(self.cli("download", "2004", "--all", "--text", "--max-bytes", "100").code, 1)
        dry = self.cli("download", "2004", "--all", "--text", "--dry-run", "--json")
        self.assertEqual(dry.code, 0, dry.err)
        self.assertEqual((page_downloads(self.mock), self.mock.media_requests), ([], []))

    def test_what_a_terminal_would_obey_never_reaches_it(self):
        hostile = "plain\x1b[31m red \x1b]0;owned\x07and \u202egnp\u200b " + "".join(chr(0xE0000 + ord(letter)) for letter in "ignore all") + " end\n"
        self.area.add_attachment("2003", "hostile.txt", [Edition(hostile.encode("utf-8"), created="2026-10-20T09:00:00.000Z")], "text/plain")
        for argv in (("download", "2003", "--name", "hostile.txt", "--text"), ("download", "2003", "--name", "hostile.txt", "--text", "--json")):
            result = self.cli(*argv)
            self.assertEqual(result.code, 0, result.err)
            for char in ("\x1b", "\x07", "\u202e", "\u200b", chr(0xE0069)):
                self.assertNotIn(char, result.out)
        self.assertIn("plain red and gnp  end", self.cli("download", "2003", "--name", "hostile.txt", "--text").out)

    def test_a_hostile_document_is_a_hint_and_never_a_failure(self):
        xml = '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaa">]><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>&a;</w:body></w:document>'
        protected = bytearray(docx(para("secret")))
        # the flag that says that a part is encrypted, in the local header and in the directory
        for marker, at in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
            start = bytes(protected).find(marker)
            protected[start + at] |= 1
        cases = {
            "entity.docx": zipped({"word/document.xml": xml}),
            "damaged.docx": docx(para("fine"))[:40],
            "password.docx": bytes(protected),
            "not-utf8.docx": zipped({"word/document.xml": "<w:document/>".encode("utf-16")}),
            "empty.docx": b"",
        }
        for name, data in cases.items():
            self.area.add_attachment("2003", name, [Edition(data, created="2026-10-20T09:00:00.000Z")], "application/octet-stream")
        self.mock.page_cap = 100
        result = self.cli("download", "2003", "--all", "--text", "--json")
        self.assertEqual(result.code, 0, result.err)
        entries = {item["name"]: item for item in result.json()["files"]}
        self.assertEqual({item["action"] for item in entries.values()}, {"not text"})
        self.assertIn("declares a document type or an entity", entries["entity.docx"]["hint"])
        self.assertIn("password", entries["password.docx"]["hint"])
        self.assertIn("not UTF-8", entries["not-utf8.docx"]["hint"])
        for item in entries.values():
            self.assertIsNone(item["text"])
            self.assertNotIn("aaaa", item["hint"])  # never what the file holds

    def test_the_text_is_printed_in_utf8_by_a_separate_process_too(self):
        self.area.add_attachment("2003", "umlaut.txt", [Edition("Grüße — 日本語\n".encode("utf-8"), created="2026-10-20T09:00:00.000Z")], "text/plain")
        result = self.child("download", "2003", "--name", "umlaut.txt", "--text")
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("Grüße — 日本語", result.out)


class AttachTest(AttachmentFlow):
    def make(self, name, data):
        path = self.root / "in" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path

    def test_a_dry_run_reads_and_writes_nothing_and_shows_what_the_upload_does(self):
        path = self.make("plan.txt", "A new plan.\n")
        result = self.cli("attach", "2004", str(path), "--comment", "Swept", "--dry-run", "--json")
        self.assertEqual(result.code, 0, result.err)
        (item,) = result.json()["files"]
        self.assertEqual((item["action"], item["name"], item["size"], item["replaces"], item["versionFrom"], item["versionTo"]), ("would upload", "plan.txt", 12, "att5101", 3, 4))
        self.assertEqual(self.writes(), [])
        self.assertEqual([(entry.method, entry.path) for entry in self.mock.requests], [("GET", "/api/v2/pages/2004/attachments")])
        self.assertEqual(self.mock.requests[0].query["filename"], ["plan.txt"])
        self.assertEqual(len(self.mock.attachments["att5101"]["versions"]), 3)

    def test_the_real_upload_is_what_the_dry_run_said_and_becomes_a_new_version(self):
        path = self.make("plan.txt", "A new plan.\n")
        preview = self.cli("attach", "2004", str(path), "--comment", "October", "--minor", "--dry-run", "--json").json()
        done = self.cli("attach", "2004", str(path), "--comment", "October", "--minor", "--json")
        self.assertEqual(done.code, 0, done.err)
        real = done.json()
        (item,) = real["files"]
        self.assertEqual((item["name"], item["size"], item["replaces"], item["versionFrom"], item["versionTo"], item["version"]), ("plan.txt", 12, "att5101", 3, 4, 4))
        self.assertEqual((real["comment"], real["minorEdit"]), (preview["comment"], preview["minorEdit"]))
        sent = self.sent("PUT", "/rest/api/content/2004/child/attachment")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].headers["x-atlassian-token"], "nocheck")
        self.assertEqual((sent[0].body["file"]["name"], sent[0].body["file"]["data"], sent[0].body["fields"]), ("plan.txt", b"A new plan.\n", {"minorEdit": "true", "comment": "October"}))
        self.assertEqual(self.mock.attachments["att5101"]["versions"][-1]["data"], b"A new plan.\n")
        self.assertEqual(self.mock.attachments["att5101"]["comment"], "October")

    def test_the_comment_is_sent_as_utf8_text_and_arrives_as_it_was_written(self):
        path = self.make("notes.txt", "x")
        self.assertEqual(self.cli("attach", "2003", str(path), "--comment", "Größe — 日本語").code, 0)
        sent = self.sent("PUT", "/rest/api/content/2003/child/attachment")[0]
        self.assertIn(b'name="comment"\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n', sent.raw)
        self.assertEqual(sent.body["fields"]["comment"], "Größe — 日本語")
        (attachment,) = [item for item in self.mock.attachments.values() if item["pageId"] == "2003"]
        self.assertEqual(attachment["comment"], "Größe — 日本語")

    def test_the_conflict_guards_are_exit_code_3_and_nothing_is_sent(self):
        path = self.make("plan.txt", "A new plan.\n")
        for extra in (("--if-version", "2"), ("--if-unchanged-since", "2026-10-09T13:00:00Z"), ("--if-version", "0")):
            for dry in ((), ("--dry-run",)):
                result = self.cli("attach", "2004", str(path), *extra, *dry)
                self.assertEqual(result.code, 3, (extra, dry, result.err))
        self.assertEqual(self.writes(), [])
        ok = self.cli("attach", "2004", str(path), "--if-version", "3", "--if-unchanged-since", "2026-10-09T14:00:00Z", "--json")
        self.assertEqual(ok.code, 0, ok.err)
        again = self.cli("attach", "2004", str(path), "--if-version", "3")
        self.assertEqual(again.code, 3)  # it is at version 4 now
        self.assertEqual(len(self.sent("PUT", "/rest/api/content/2004/child/attachment")), 1)

    def test_an_empty_guard_time_is_refused_and_nothing_is_asked_or_sent(self):
        path = self.make("plan.txt", "A new plan.\n")  # the file of an attachment that the page has: the guard would have counted
        for value in ("", " "):
            for dry in ((), ("--dry-run",)):
                self.mock.requests.clear()
                result = self.cli("attach", "2004", str(path), "--if-unchanged-since", value, *dry)
                self.assertEqual(result.code, 1, (value, dry, result.err))
                self.assertIn("--if-unchanged-since", result.err)
                self.assertEqual(self.mock.requests, [])
        self.assertEqual(len(self.mock.attachments["att5101"]["versions"]), 3)

    def test_a_run_that_fails_after_it_uploaded_says_which_files_went_and_what_the_page_has_is_what_it_says(self):
        first, second = self.make("a.txt", "first"), self.make("b.txt", "second")
        real = RestConfluenceGateway.upload_attachment
        names = []

        def second_one_fails(gateway, page_id, filename, data, **kwargs):
            names.append(filename)
            if len(names) % 2 == 0:
                raise UnavailableError("Cannot reach Confluence (TimeoutError: timed out).", hint="Check the network.")
            return real(gateway, page_id, filename, data, **kwargs)

        with mock.patch.object(RestConfluenceGateway, "upload_attachment", second_one_fails):
            result = self.cli("attach", "2003", str(first), str(second))
            as_json = self.cli("attach", "2003", str(first), str(second), "--json")
        self.assertEqual((result.code, result.out), (7, ""))
        self.assertIn("Cannot reach Confluence (TimeoutError: timed out). 1 of the 2 files were uploaded to page 2003 before that: a.txt.", result.err)
        self.assertIn("`conflu attachments 2003`", result.err)
        self.assertIn("the files that are left: b.txt.", result.err)
        listed = self.cli("attachments", "2003", "--json").json()["attachments"]
        self.assertEqual([(item["title"], item["version"]) for item in listed], [("a.txt", 2)])  # a.txt twice, as the error warned; b.txt never
        error = json.loads(as_json.err)["error"]
        self.assertEqual((as_json.code, error["code"], error["exitCode"]), (7, "UNAVAILABLE", 7))
        self.assertEqual([(item["name"], item["version"], item["path"]) for item in error["details"]["uploaded"]], [("a.txt", 2, str(first))])
        self.assertEqual(error["details"]["failed"], {"path": str(second), "name": "b.txt"})

    def test_a_blog_post_is_no_page(self):
        path = self.make("plan.txt", "x")
        result = self.cli("attach", "7102", str(path))
        self.assertEqual(result.code, 4)
        self.assertIn("a blog post", result.err)
        self.assertEqual(self.writes(), [])

    def test_the_configuration_is_never_attached_whichever_way_it_is_named_and_nothing_is_sent(self):
        config = self.put_config()
        elsewhere = self.make("elsewhere.txt", "fine")
        spellings = [str(config), str(self.root / "in" / ".." / "config" / "conflu-c-cli" / "config"), str(config.parent / ".." / config.parent.name / "config")]
        for spelling in spellings:
            for dry in ((), ("--dry-run",)):
                self.mock.requests.clear()
                result = self.cli("attach", "2004", str(elsewhere), spelling, *dry)
                self.assertEqual(result.code, 2, (spelling, dry, result.err))
                self.assertNotIn(TOKEN, result.err)
                self.assertEqual(self.mock.requests, [])
        self.assertEqual(self.writes(), [])

    def test_the_configuration_by_a_hard_link_and_by_a_symbolic_link(self):
        config = self.put_config()
        hard = self.root / "in" / "hard.txt"
        hard.parent.mkdir(parents=True, exist_ok=True)
        links = []
        try:
            os.link(config, hard)
            links.append(hard)
        except (OSError, NotImplementedError):
            pass
        soft = self.root / "in" / "soft.txt"
        try:
            os.symlink(config, soft)
            links.append(soft)
        except (OSError, NotImplementedError):
            pass
        if not links:
            self.skipTest("this system lets a test make neither a hard link nor a symbolic link")
        for link in links:
            result = self.cli("attach", "2004", str(link), "--dry-run")
            self.assertEqual(result.code, 2, (link, result.err))
        self.assertEqual(self.mock.requests, [])

    def test_a_file_with_the_name_of_the_configuration_that_is_another_file_is_attached(self):
        self.put_config()
        other = self.root / "in" / "config"
        other.parent.mkdir(parents=True, exist_ok=True)
        other.write_text("just a file named config", encoding="utf-8")
        self.assertEqual(self.cli("attach", "2003", str(other)).code, 0)

    def test_a_file_that_holds_the_token_is_refused_in_every_encoding_and_nothing_is_sent(self):
        import base64

        header = base64.b64encode(f"{self.mock.email}:{TOKEN}".encode()).decode()
        leaks = {
            "plain.txt": f"CONFLUENCE_API_TOKEN={TOKEN}\n".encode("utf-8"),
            "utf16.txt": f"CONFLUENCE_API_TOKEN={TOKEN}\r\n".encode("utf-16"),
            "header.log": f"GET /wiki/api/v2/pages HTTP/1.1\r\nAuthorization: Basic {header}\r\n".encode("utf-8"),
            "binary.bin": b"\x00\x01" * 100 + TOKEN.encode() + b"\xff" * 10,
        }
        for name, data in leaks.items():
            path = self.make(name, data)
            for dry in ((), ("--dry-run",)):
                self.mock.requests.clear()
                result = self.cli("attach", "2004", str(path), *dry)
                self.assertEqual(result.code, 2, (name, dry, result.err))
                self.assertNotIn(TOKEN, result.err + result.out)
                self.assertNotIn(header, result.err + result.out)
                self.assertEqual(self.mock.requests, [])
        self.assertEqual(self.writes(), [])

    def test_the_token_is_found_in_a_large_file_where_a_piece_of_it_ends(self):
        boundary = 1 << 20  # the size of the pieces that a file is read in
        for offset in (boundary - 5, boundary - 1, boundary):
            path = self.make("large.bin", b"x" * offset + TOKEN.encode() + b"y" * 1000)
            result = self.cli("attach", "2004", str(path), "--dry-run")
            self.assertEqual(result.code, 2, offset)
        clean = self.make("clean.bin", b"x" * (boundary + 5000))
        self.assertEqual(self.cli("attach", "2003", str(clean), "--dry-run").code, 0)

    def test_a_missing_file_a_folder_and_a_page_that_is_not_there(self):
        self.assertEqual(self.cli("attach", "2004", str(self.root / "missing.txt")).code, 1)
        self.assertEqual(self.cli("attach", "2004", str(self.root)).code, 1)
        path = self.make("a.txt", "a")
        self.assertEqual(self.cli("attach", "999", str(path)).code, 4)
        self.assertEqual(self.cli("attach", "999", str(path), "--dry-run").code, 4)
        self.assertEqual(self.writes(), [])

    def test_a_name_that_is_hostile_is_sent_as_it_is_written_on_disk_and_does_not_break_the_request(self):
        path = self.make("ünï côdé ✓.txt", "x")
        result = self.cli("attach", "2003", str(path), "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(result.json()["files"][0]["name"], "ünï côdé ✓.txt")
        self.assertIn("ünï côdé ✓.txt", [item["title"] for item in self.mock.attachments.values()])


class RedactedNameFlowTest(AttachmentFlow):
    """What is printed as the name of a file is the name of the file on disk, and neither holds the address that somebody put in the name."""

    def setUp(self):
        super().setUp()
        self.cv = self.area.add_attachment("2003", "alex@example.com-cv.txt", [Edition(b"cv data", created="2026-10-20T09:00:00.000Z")], "text/plain")

    def test_the_name_and_the_path_are_the_name_of_the_file_that_is_on_disk(self):
        result = self.cli("download", self.cv, "--out", str(self.out), "--json")
        self.assertEqual(result.code, 0, result.err)
        entry = result.json()["files"][0]
        self.assertEqual((entry["name"], Path(entry["path"])), ("[email]", self.out / "[email]"))
        self.assertEqual((self.out / "[email]").read_bytes(), b"cv data")
        self.assertEqual(self.tree(self.out), ["[email]"])
        self.assertNotIn("alex", (result.out + result.err).lower())
        for extra in (("--dry-run",), ()):
            shown = self.cli("download", self.cv, "--out", str(self.root / "plain"), *extra)
            self.assertEqual(shown.code, 0, shown.err)
            self.assertIn("[email]", shown.out)
            self.assertNotIn("alex", (shown.out + shown.err).lower())
        self.assertEqual(self.tree(self.root / "plain"), ["[email]"])

    def test_with_people_the_file_is_named_as_it_is_called_and_the_policy_refuses_that(self):
        result = self.cli("download", self.cv, "--out", str(self.out), "--with-users", "--json")
        self.assertEqual(result.code, 0, result.err)
        entry = result.json()["files"][0]
        self.assertEqual((entry["name"], Path(entry["path"])), ("alex@example.com-cv.txt", self.out / "alex@example.com-cv.txt"))
        self.assertEqual(self.tree(self.out), ["alex@example.com-cv.txt"])
        refused = self.cli("download", self.cv, "--out", str(self.root / "no"), "--with-users", env={"CONFLUENCE_HIDE_USERS": "true"})
        self.assertEqual(refused.code, 1)
        self.assertFalse((self.root / "no").exists())

    def test_a_name_is_still_found_by_what_it_really_is_and_the_file_is_asked_for_by_its_id(self):
        result = self.cli("download", "2003", "--name", "alex@example.com-cv.txt", "--out", str(self.out))
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.tree(self.out), ["[email]"])
        self.assertEqual(self.sent("GET", "/api/v2/pages/2003/attachments")[0].query["filename"], ["alex@example.com-cv.txt"])
        self.assertEqual([item.path for item in page_downloads(self.mock, "2003")], [f"/rest/api/content/2003/child/attachment/{self.cv}/download"])
        redacted = self.cli("download", "2003", "--name", "[email]", "--out", str(self.root / "more"))
        self.assertEqual(redacted.code, 4)
        self.assertIn("by its id", redacted.err)

    def test_what_a_refusal_says_of_the_file_does_not_hold_the_address(self):
        for argv in (
            ("download", self.cv, "--max-bytes", "3", "--out", str(self.out)),
            ("download", self.cv, "--version", "9", "--out", str(self.out)),
            ("download", self.cv, "--text", "--max-bytes", "3"),
            ("download", self.cv, "--text", "--version", "9"),
        ):
            with self.subTest(argv=argv[2:]):
                result = self.cli(*argv)
                self.assertNotEqual(result.code, 0)
                self.assertIn("[email]", result.err)
                self.assertNotIn("alex", result.err.lower())
        self.assertEqual(self.tree(), [])

    def test_the_text_of_a_file_is_headed_by_the_redacted_name_and_by_its_own_with_people(self):
        hidden = self.cli("download", self.cv, "--text")
        self.assertEqual(hidden.code, 0, hidden.err)
        self.assertIn("[email]", hidden.out.splitlines()[0])
        self.assertNotIn("alex", hidden.out.lower())
        shown = self.cli("download", self.cv, "--text", "--with-users")
        self.assertIn("alex@example.com-cv.txt", shown.out.splitlines()[0])

    def test_two_names_that_become_one_when_they_are_redacted_are_refused_and_nothing_is_written(self):
        self.area.add_attachment("2003", "bob@example.com-cv.txt", [Edition(b"other cv", created="2026-10-20T09:00:00.000Z")], "text/plain")
        result = self.cli("download", "2003", "--all", "--out", str(self.out))
        self.assertEqual(result.code, 1)
        self.assertIn("would be saved as the same file ([email])", result.err)
        self.assertIn("--with-users", result.err)
        self.assertNotIn("example.com", result.err)
        self.assertEqual((self.tree(), page_downloads(self.mock, "2003")), ([], []))
        own = self.cli("download", "2003", "--all", "--out", str(self.out), "--with-users")
        self.assertEqual(own.code, 0, own.err)
        self.assertEqual(self.tree(self.out), ["alex@example.com-cv.txt", "bob@example.com-cv.txt"])


class HiddenNameFlowTest(AttachmentFlow):
    NAMES = [".mcp.json", ".env", ".vscode", ".git", "..hidden", "AGENTS.md", "conftest.py"]

    def test_a_name_that_starts_with_a_dot_gets_an_underscore_so_that_a_download_cannot_plant_a_hidden_file(self):
        for number, name in enumerate(self.NAMES):
            self.area.add_attachment("2003", name, [Edition(f"data {number}".encode(), created="2026-10-20T09:00:00.000Z")], "text/plain")
        self.mock.page_cap = 100
        self.out.mkdir()
        (self.out / ".env").write_bytes(b"mine")  # a file that a person has: nothing is written over it, and nothing is written next to it under its name
        result = self.cli("download", "2003", "--all", "--out", str(self.out), "--json")
        self.assertEqual(result.code, 0, result.err)
        expected = ["_.mcp.json", "_.env", "_.vscode", "_.git", "_..hidden", "AGENTS.md", "conftest.py"]
        self.assertEqual(self.tree(self.out), sorted([*expected, ".env"]))
        self.assertEqual((self.out / ".env").read_bytes(), b"mine")
        files = result.json()["files"]
        saved_as = {item["name"]: Path(item["path"]).name for item in files}  # the name as the attachment has it, and the file that it was saved as
        self.assertEqual(saved_as, dict(zip(self.NAMES, expected)))
        self.assertTrue(all(Path(item["path"]).is_file() for item in files))
        dry = self.cli("download", "2003", "--name", ".mcp.json", "--out", str(self.root / "other"), "--dry-run", "--json")
        self.assertEqual([Path(item["path"]).name for item in dry.json()["files"]], ["_.mcp.json"])


class PartialRunFlowTest(AttachmentFlow):
    def assert_what_was_written_is_said(self, result):
        self.assertEqual(result.code, 7, result.err)
        self.assertEqual(self.tree(self.out), ["plan.txt", "spec.docx"])
        self.assertIn("2 of the 6 files were written to", result.err)
        self.assertIn("before that: plan.txt, spec.docx.", result.err)
        self.assertIn("--force", result.err)

    def test_an_answer_that_cannot_be_used_after_files_were_written_is_an_exit_code_and_says_what_was_written(self):
        self.mock.fail_next("/rest/api/content/2004/child/attachment/att5103/download", 302, headers={"Location": "https://media.example:99999/x"})
        self.assert_what_was_written_is_said(self.cli("download", "2004", "--all", "--out", str(self.out)))

    def test_an_error_of_confluence_after_files_were_written_says_the_same(self):
        self.mock.fail_next("/rest/api/content/2004/child/attachment/att5103/download", 503)
        self.assert_what_was_written_is_said(self.cli("download", "2004", "--all", "--out", str(self.out), env={"CONFLUENCE_RETRY": "0"}))

    def test_the_summary_is_in_the_json_error_too(self):
        self.mock.fail_next("/rest/api/content/2004/child/attachment/att5103/download", 302, headers={"Location": "https://media.example:99999/x"})
        result = self.cli("download", "2004", "--all", "--out", str(self.out), "--json")
        self.assertEqual(result.code, 7, result.err)
        error = json.loads(result.err)["error"]
        self.assertEqual([item["attachmentId"] for item in error["details"]["written"]], ["att5101", "att5102"])
        self.assertEqual(error["details"]["failed"], {"attachmentId": "att5103"})
        self.assertEqual((error["code"], error["exitCode"]), ("UNAVAILABLE", 7))
        self.assertEqual([Path(item["path"]) for item in error["details"]["written"]], [self.out / "plan.txt", self.out / "spec.docx"])

    def test_a_run_that_fails_on_its_first_file_has_nothing_to_say_of_files(self):
        self.mock.fail_next("/rest/api/content/2004/child/attachment/att5101/download", 302, headers={"Location": "https://media.example:99999/x"})
        result = self.cli("download", "2004", "--all", "--out", str(self.out))
        self.assertNotEqual(result.code, 0)
        self.assertNotIn("files were written", result.err)
        self.assertEqual(self.tree(), [])


class BoundedReadTest(AttachmentFlow):
    """The limit that the caller takes is given to the transport, which stops reading at it: a server that says one thing of the size of a file and sends
    another cannot make the program hold or decode more than was asked for."""

    def settings(self):
        return Settings(base_url=self.mock.base_url, email=self.mock.email, api_token=self.mock.token, retry=0, connect_timeout=5.0, max_time=10.0)

    def transport(self):
        transport = HttpTransport(self.settings())
        self.addCleanup(transport.close)
        return transport

    def gateway(self):
        return RestConfluenceGateway(self.settings(), self.transport())

    def test_a_file_longer_than_the_limit_is_refused_and_one_of_exactly_the_limit_is_not(self):
        gateway = self.gateway()
        item = gateway.get_attachment("att5101")
        size = len(PLAN[2].data)
        self.assertEqual(gateway.fetch_attachment(item, 0, size), PLAN[2].data)
        with self.assertRaises(ValidationError) as caught:
            gateway.fetch_attachment(item, 0, size - 1)
        self.assertEqual(caught.exception.message, f"plan.txt (att5101) is larger than {size - 1} B; it was not read to the end and nothing was kept.")
        self.assertEqual(caught.exception.details, {"attachmentId": "att5101", "maxBytes": size - 1})

    def test_the_request_is_the_same_with_and_without_a_limit(self):
        gateway = self.gateway()
        item = gateway.get_attachment("att5101")
        for version, limit in ((0, 0), (0, 1000), (2, 1000), (2, 0)):
            gateway.fetch_attachment(item, version, limit)
        first, second = {}, {"version": ["2"]}
        self.assertEqual(
            [(entry.path, entry.query) for entry in page_downloads(self.mock)],
            [("/rest/api/content/2004/child/attachment/att5101/download", query) for query in (first, first, second, second)],
        )
        self.assertTrue(all("authorization" not in entry.headers for entry in self.mock.media_requests))

    def test_a_version_and_the_file_of_a_blog_post_are_limited_too(self):
        gateway = self.gateway()
        with self.assertRaises(ValidationError):
            gateway.fetch_attachment(gateway.get_attachment("att5101"), 1, 3)
        post_file = gateway.get_attachment("att5111")
        self.assertEqual(gateway.fetch_attachment(post_file, 0, 1000), AGENDA[1].data)
        with self.assertRaises(ValidationError):
            gateway.fetch_attachment(post_file, 0, 3)

    def test_the_limit_of_the_transport_itself_is_not_taken_for_the_one_of_the_caller(self):
        gateway = self.gateway()
        item = gateway.get_attachment("att5101")
        with mock.patch.object(http_transport, "MAX_DOWNLOAD", 5):
            for asked in (0, 1000):
                with self.subTest(max_bytes=asked):
                    with self.assertRaises(UnavailableError) as caught:
                        gateway.fetch_attachment(item, 0, asked)
                    self.assertNotIsInstance(caught.exception, ValidationError)
                    self.assertIn("larger than 5 bytes; it was not read", caught.exception.message)

    def test_the_transport_stops_at_the_limit_of_its_caller(self):
        transport = self.transport()
        path = "/rest/api/content/2004/child/attachment/att5101/download"
        self.assertEqual(transport.download(path, limit=len(PLAN[2].data)).body, PLAN[2].data)
        with self.assertRaises(http_transport.AnswerTooBig):
            transport.download(path, limit=5)
        self.assertEqual(transport.download(path).body, PLAN[2].data)  # no limit of its own: the call that was always made

    def test_a_server_that_declares_one_byte_and_sends_more_is_refused_for_text_and_for_saving(self):
        big = self.area.add_attachment("2004", "big.txt", [Edition(b"y" * 5000, created="2026-10-20T09:00:00.000Z")], "text/plain")
        make_model = _ApiHandler._attachment_model
        real_download = HttpTransport.download
        asked = []

        def understated(handler, attachment, **kwargs):
            model = make_model(handler, attachment, **kwargs)
            model["fileSize"] = 1
            return model

        def spy(transport, path, **kwargs):
            asked.append(kwargs.get("limit"))
            return real_download(transport, path, **kwargs)

        with mock.patch.object(_ApiHandler, "_attachment_model", understated), mock.patch.object(HttpTransport, "download", spy):
            self.assertEqual(self.cli("attachment", big, "--json").json()["size"], 1)  # the claim, as the program saw it
            text = self.cli("download", big, "--text", "--max-bytes", "100")
            saved = self.cli("download", big, "--max-bytes", "100", "--out", str(self.out))
        for result in (text, saved):
            self.assertEqual(result.code, 1, result.err)
            self.assertIn("is larger than 100 B", result.err)
            self.assertNotIn("yyyy", result.out + result.err)
        self.assertEqual((text.out, self.tree()), ("", []))
        self.assertEqual(asked, [100, 100])


class GatewayMessageTest(AttachmentFlow):
    """What the adapter says of a file does not repeat the address that somebody put in its name; the id says which file it is."""

    def gateway(self):
        settings = Settings(base_url=self.mock.base_url, email=self.mock.email, api_token=self.mock.token, retry=0, connect_timeout=5.0, max_time=10.0)
        transport = HttpTransport(settings)
        self.addCleanup(transport.close)
        return RestConfluenceGateway(settings, transport)

    def test_a_file_whose_holder_is_not_known_and_a_file_without_an_address(self):
        gateway = self.gateway()
        nameless = Attachment("att9", "alex@example.com.txt")
        with self.assertRaises(NotFoundError) as holder:
            gateway.fetch_attachment(nameless, 1)
        self.assertIn("holds [email] (att9), so its file cannot be asked for.", holder.exception.message)
        with self.assertRaises(NotFoundError) as address:
            gateway.download_attachment(nameless)
        self.assertEqual(address.exception.message, "Confluence gave no download address for [email] (att9).")

    def test_an_answer_that_is_no_file(self):
        gateway = self.gateway()
        item = Attachment("att5101", "alex@example.com.txt", page_id="2004")
        self.mock.fail_next("/rest/api/content/2004/child/attachment/att5101/download", 202, times=2, body={"message": "injected"})
        for call in (lambda: gateway.fetch_attachment(item, 0, 1000), lambda: gateway.download_attachment(item)):
            with self.assertRaises(UnavailableError) as caught:
                call()
            self.assertEqual(caught.exception.message, "Confluence did not send [email] (att5101) (HTTP 202).")


class JsonReferenceFlowTest(AttachmentFlow):
    def test_every_document_of_the_area_is_valid_json_with_the_keys_that_were_promised(self):
        for argv, keys in (
            (("attachments", "2004", "--json"), {"pageId", "blogPostId", "count", "nextCursor", "attachments"}),
            (("attachment", "att5101", "--json"), {"id", "title", "mediaType", "size", "version", "created", "updated", "pageId", "blogPostId", "downloadLink", "comment"}),
            (("download", "att5101", "--text", "--json"), {"dryRun", "count", "files"}),
            (("download", "att5101", "--out", str(self.out), "--dry-run", "--json"), {"dryRun", "count", "files"}),
        ):
            with self.subTest(argv=argv):
                result = self.cli(*argv)
                self.assertEqual(result.code, 0, result.err)
                self.assertEqual(set(json.loads(result.out)), keys)


if __name__ == "__main__":
    unittest.main()
