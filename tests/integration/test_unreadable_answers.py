"""A success whose answer cannot be read is an answer that cannot be read: exit code 7, never an empty result and never a success.

`_decode` took the `ValueError` of `json.loads` for "the body is no JSON" and answered `{"_text": ...}`, which every list reads as no results: a content
property that holds an integer of more than 4,300 digits (the decoder refuses to turn it into one) made `conflu properties` print `No properties` with exit
code 0, `tasks` printed `No tasks.`, a search `Nothing found.`, and the page of a proxy that answers HTTP 200 made `ping` say `OK` and `page` print a blank page.
JSON of another kind (`[]`, `null`) and an empty body were the same for a call that needs an object, and a write that was answered by the page of a proxy
(`property-set`: "Created", `task --complete`: "Completed") was reported as done. Here: the real gateway and the real program against a small server on this
computer that answers as the test says (nothing else is ever asked), every command of the conformance sweep against the page of a proxy, the writes that the
mock answers with the page of a proxy, and the refusals, which keep their meaning whatever their body is.
"""
import io
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from unittest import mock

from conflu_c_cli.adapters.driven.confluence_rest import RestConfluenceGateway
from conflu_c_cli.adapters.driven.http_transport import HttpResponse, HttpTransport
from conflu_c_cli.adapters.driving.cli.main import run
from conflu_c_cli.application.settings import Settings
from conflu_c_cli.bootstrap import create_application
from conflu_c_cli.domain.errors import AuthError, ConfigError, ConflictError, NotFoundError, RejectedError, UnavailableError
from conflu_c_cli.domain.watches import CONTENT, SPACE, WatchChange
from tests.integration.test_answer_limits import _Quiet
from tests.integration.test_properties_flow import TYPES, PropertiesFlow
from tests.support.mock_base import Routes
from tests.support.sweeps import LOCAL
from tests.support.sweeps_all import SWEEPS

DIGITS = 4400
HUGE = b'{"results":[{"id":"1","key":"k","value":1' + b"0" * DIGITS + b"}]}"  # an integer of 4,401 digits where the answer of a list has the value of a property
PROXY_PAGE = b"<html><head><title>Sign in</title></head><body>Sign in to the network to go on.</body></html>"
HTML = {"Content-Type": "text/html; charset=utf-8"}
PRIVATE_MARKER = "sign in to the network"  # what the page of the proxy says: no message repeats the text of an answer


class _Answers:
    """A server on this computer that answers every request, of any method, as the test says, and records what it was asked."""

    def __init__(self, body: bytes = b"", status: int = 200, headers: dict | None = None):
        self.body, self.status, self.headers = body, status, dict(headers or {})
        self.requests: list[tuple[str, str]] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def answer(self):
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)  # a request that is not read to its end is a connection that is reset
                owner.requests.append((self.command, self.path))
                self.send_response(owner.status)
                for name, value in owner.headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(owner.body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(owner.body)

            do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = answer

            def log_message(self, *args):
                pass

        self.server = _Quiet(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/wiki"

    def settings(self, **overrides) -> Settings:
        values = dict(base_url=self.base_url, email="alex@example.com", api_token="a-token-123", retry=0, connect_timeout=5.0, max_time=10.0)
        values.update(overrides)
        return Settings(**values)


class StubbedCase(unittest.TestCase):
    """The home of the tests is their own: the profile of the person who runs them is never a home folder, and the cache is a folder of the test."""

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name)
        profile = mock.patch("pathlib.Path.home", return_value=self.root / "profile")
        profile.start()
        self.addCleanup(profile.stop)

    def serve(self, *args, **options) -> _Answers:
        answers = _Answers(*args, **options)
        answers.__enter__()
        self.addCleanup(answers.__exit__, None, None, None)
        return answers

    def gateway(self, answers: _Answers, **overrides) -> RestConfluenceGateway:
        settings = answers.settings(**overrides)
        transport = HttpTransport(settings, sleep=lambda seconds: None)
        self.addCleanup(transport.close)
        return RestConfluenceGateway(settings, transport)

    def environment(self, answers: _Answers, **more) -> dict:
        return {
            "CONFLUENCE_BASE_URL": answers.base_url,
            "CONFLUENCE_EMAIL": "alex@example.com",
            "CONFLUENCE_API_TOKEN": "a-token-123",
            "CONFLUENCE_CONFIG_FILE": str(self.root / "config" / "conflu-c-cli" / "config"),
            "HOME": str(self.root),
            "XDG_CACHE_HOME": str(self.root / "cache"),
            **more,
        }

    def program(self, answers: _Answers, *argv: str, **more):
        """The real program, in this process: (exit code, standard output, standard error)."""
        environ = self.environment(answers, **more)
        out, err = io.StringIO(), io.StringIO()
        code = run(list(argv), app_factory=lambda diagnostics: create_application(diagnostics, environ), environ=environ, stdout=out, stderr=err, stdin=io.StringIO(""))
        return code, out.getvalue(), err.getvalue()

    # what the gateway reads, each with the call that reads it: a list of properties, a list of tasks, a search, and some that are not lists
    def reads(self, gateway: RestConfluenceGateway):
        return {
            "list_properties": lambda: gateway.list_properties("page", "2002"),
            "list_tasks": lambda: gateway.list_tasks(),
            "search": lambda: gateway.search("type = page"),
            "list_spaces": lambda: gateway.list_spaces(),
            "get_space": lambda: gateway.get_space("ENG"),
            "get_page": lambda: gateway.get_page("2002"),
            "current_user": lambda: gateway.current_user(),
            "list_comments": lambda: gateway.list_comments("2002"),
            "list_attachments": lambda: gateway.list_attachments("2002"),
            "list_labels": lambda: gateway.list_labels("2002"),
        }


@unittest.skipUnless(hasattr(sys, "set_int_max_str_digits"), "this Python does not limit the digits of an integer")
class HugeNumberTest(StubbedCase):
    def setUp(self):
        super().setUp()
        before = sys.get_int_max_str_digits()
        sys.set_int_max_str_digits(4300)  # the default of the versions that have the limit: a test must not depend on PYTHONINTMAXSTRDIGITS
        self.addCleanup(sys.set_int_max_str_digits, before)

    def test_a_list_of_properties_a_list_of_tasks_and_a_search_are_no_empty_lists(self):
        answers = self.serve(HUGE, headers={"Content-Type": "application/json"})
        for name, read in self.reads(self.gateway(answers)).items():
            with self.subTest(read=name), self.assertRaises(UnavailableError) as caught:
                read()
            self.assertEqual(caught.exception.exit_code, 7)
            self.assertIn("a number that is too long to be read (more than 4,300 digits)", caught.exception.message)
            self.assertIn("HTTP 200", caught.exception.message)
            self.assertEqual(caught.exception.details["status"], 200)
            self.assertIn("a content property", caught.exception.hint)
            self.assertNotIn("000000", caught.exception.message + caught.exception.hint)  # no digit of it is repeated

    def test_the_program_says_so_for_every_command_that_reads_it(self):
        answers = self.serve(HUGE, headers={"Content-Type": "application/json"})
        for argv in (("properties", "2002"), ("tasks",), ("search", "release"), ("ping",), ("page", "2002"), ("spaces",), ("space", "ENG"), ("labels", "2002")):
            with self.subTest(argv=argv):
                code, out, err = self.program(answers, *argv)
                self.assertEqual((code, out), (7, ""))
                self.assertIn("a number that is too long to be read", err)
                self.assertNotIn("No properties", out + err)
                self.assertNotIn("No tasks", out + err)
                self.assertNotIn("Nothing found", out + err)

    def test_in_json_it_is_the_error_object_and_nothing_on_standard_output(self):
        answers = self.serve(HUGE, headers={"Content-Type": "application/json"})
        for argv in (("properties", "2002", "--json"), ("tasks", "--json"), ("search", "release", "--json"), ("ping", "--json")):
            with self.subTest(argv=argv):
                code, out, err = self.program(answers, *argv)
                self.assertEqual((code, out), (7, ""))
                error = json.loads(err.strip().splitlines()[-1])["error"]
                self.assertEqual((error["code"], error["exitCode"]), ("UNAVAILABLE", 7))
                self.assertEqual(error["details"]["status"], 200)

    def test_the_doctor_does_not_call_it_a_connection(self):
        answers = self.serve(HUGE, headers={"Content-Type": "application/json"})
        code, out, err = self.program(answers, "doctor", "--quick")
        self.assertEqual(code, 1)
        self.assertIn("[FAIL] connection", out)
        self.assertNotIn("reachable, the credentials are accepted", out)

    def test_a_number_just_under_the_limit_is_read_as_it_always_was(self):
        body = b'{"results":[{"id":"1","key":"k","value":1' + b"0" * 4298 + b',"version":{"number":1}}]}'  # 4,299 digits
        answers = self.serve(body, headers={"Content-Type": "application/json"})
        chunk = self.gateway(answers).list_properties("page", "2002")
        self.assertEqual([item.key for item in chunk.items], ["k"])
        self.assertEqual(len(str(chunk.items[0].value)), 4299)

    def test_a_refusal_with_such_a_body_is_still_the_refusal_that_its_status_says(self):
        for status, error in ((400, RejectedError), (401, AuthError), (403, AuthError), (404, NotFoundError), (409, ConflictError), (410, RejectedError), (500, UnavailableError)):
            answers = self.serve(HUGE, status=status, headers={"Content-Type": "application/json"})
            with self.subTest(status=status), self.assertRaises(error) as caught:
                self.gateway(answers).get_page("2002")
            self.assertNotIn("too long to be read", caught.exception.message)
            self.assertNotIn("000000", caught.exception.message + caught.exception.hint)


class NotJsonTest(StubbedCase):
    def test_every_read_that_gets_the_page_of_a_proxy_is_an_answer_that_cannot_be_read(self):
        answers = self.serve(PROXY_PAGE, headers=HTML)
        for name, read in self.reads(self.gateway(answers)).items():
            with self.subTest(read=name), self.assertRaises(UnavailableError) as caught:
                read()
            self.assertEqual(caught.exception.exit_code, 7)
            self.assertIn("Confluence answered HTTP 200 with something that is not JSON (text/html).", caught.exception.message)
            self.assertIn("a captive portal", caught.exception.hint)
            self.assertIn("CONFLUENCE_BASE_URL", caught.exception.hint)
            self.assertNotIn(PRIVATE_MARKER, (caught.exception.message + caught.exception.hint + repr(caught.exception.details)).lower())
            self.assertEqual(set(caught.exception.details), {"status", "request"})

    def test_whatever_is_no_json_is_the_same(self):
        for body in (b"OK", b"<?xml version='1.0'?><a/>", b'{"results": [', b"12abc", b"\xff\xfe\x00 not utf-8", b"\xef\xbb\xbf{}", b"nul", b"{'a': 1}", b"<html>"):
            answers = self.serve(body)
            with self.subTest(body=body[:16]), self.assertRaises(UnavailableError) as caught:
                self.gateway(answers).list_properties("page", "2002")
            self.assertIn("with something that is not JSON", caught.exception.message)
            self.assertEqual(caught.exception.exit_code, 7)

    def test_the_media_type_is_named_only_when_it_looks_like_one(self):
        for header, named in (
            ("text/html; charset=utf-8", " (text/html)"),
            ("TEXT/PLAIN", " (text/plain)"),
            ("application/xml", " (application/xml)"),
            ("<b>hi</b>", ""),
            ("text/html, text/plain", ""),
            ("a" * 200 + "/b", ""),
            ("\u00e9/x", ""),
            ("", ""),
        ):
            answers = self.serve(PROXY_PAGE, headers={"Content-Type": header} if header else {})
            with self.subTest(header=header[:30]), self.assertRaises(UnavailableError) as caught:
                self.gateway(answers).list_spaces()
            self.assertIn(f"something that is not JSON{named}.", caught.exception.message)

    def test_an_empty_answer_to_a_read_is_not_a_list_that_is_empty(self):
        answers = self.serve(b"")
        for name, read in self.reads(self.gateway(answers)).items():
            with self.subTest(read=name), self.assertRaises(UnavailableError) as caught:
                read()
            self.assertIn("Confluence answered HTTP 200 with an empty body, where an answer with data was expected.", caught.exception.message)
            self.assertEqual(caught.exception.exit_code, 7)
        answers = self.serve(b"  \n ")
        with self.assertRaises(UnavailableError):
            self.gateway(answers).list_properties("page", "2002")

    def test_what_may_answer_with_nothing_still_does(self):
        decode = RestConfluenceGateway._decode
        for method, status in (("PUT", 204), ("DELETE", 204), ("POST", 204), ("POST", 201), ("PUT", 202), ("DELETE", 200), ("GET", 204)):
            with self.subTest(method=method, status=status):
                self.assertEqual(decode(HttpResponse(status, {}, b""), method, "/api/v2/x"), {})
        self.assertEqual(decode(HttpResponse(200, {}, b""), "", ""), {})  # no method named: a body that is read to say what it said, as before

    def test_a_label_that_is_removed_is_still_a_success_with_no_body(self):
        answers = self.serve(b"", status=204)
        gateway = self.gateway(answers)
        gateway.remove_label("2002", "notes")
        self.assertEqual(answers.requests, [("DELETE", "/wiki/rest/api/content/2002/label/notes")])

    def test_a_write_that_gets_the_page_of_a_proxy_is_not_taken_for_done(self):
        answers = self.serve(PROXY_PAGE, headers=HTML)
        gateway = self.gateway(answers)
        with self.assertRaises(UnavailableError):
            gateway.add_labels("2002", [{"prefix": "global", "name": "notes"}])
        with self.assertRaises(UnavailableError):
            gateway.remove_label("2002", "notes")

    def test_the_raw_api_says_it_too(self):
        answers = self.serve(PROXY_PAGE, headers=HTML)
        with self.assertRaises(UnavailableError) as caught:
            self.gateway(answers).request("GET", "/api/v2/spaces")
        self.assertIn("not JSON (text/html)", caught.exception.message)

    def test_a_refusal_is_what_its_status_says_whatever_its_body_is(self):
        for status, error in ((400, RejectedError), (401, AuthError), (403, AuthError), (404, NotFoundError), (409, ConflictError), (410, RejectedError), (500, UnavailableError), (502, UnavailableError)):
            for body in (PROXY_PAGE, b"", b"\xff\xfe", b'{"message": ['):
                answers = self.serve(body, status=status, headers=HTML)
                with self.subTest(status=status, body=body[:10]), self.assertRaises(error) as caught:
                    self.gateway(answers).get_page("2002")
                self.assertNotIn("is not JSON", caught.exception.message)

    def test_a_redirect_is_what_its_status_says_too(self):
        answers = self.serve(PROXY_PAGE, status=302, headers={**HTML, "Location": "https://login.example.com/sso"})
        with self.assertRaises(ConfigError) as caught:
            self.gateway(answers).list_spaces()
        self.assertIn("login.example.com/sso", caught.exception.message)

    def test_a_body_that_nests_too_deeply_is_still_told_so(self):
        """The answer to JSON that nests deeper than the decoder reads is not the answer to JSON that is no JSON: its message and its details are as they were."""
        answers = self.serve(b"[" * 5000 + b"]" * 5000, headers={"Content-Type": "application/json"})
        with self.assertRaises(UnavailableError) as caught:
            self.gateway(answers).list_properties("page", "2002")
        self.assertEqual(caught.exception.message, "Confluence answered with JSON that nests arrays or objects too deeply to be read.")
        self.assertEqual(caught.exception.details, {"status": 200})
        self.assertIn("a content property", caught.exception.hint)

    def test_the_connection_and_the_doctor_are_not_fooled_by_the_page_of_a_proxy(self):
        answers = self.serve(PROXY_PAGE, headers=HTML)
        code, out, err = self.program(answers, "ping")
        self.assertEqual((code, out), (7, ""))
        self.assertNotIn("OK", err)
        code, out, err = self.program(answers, "doctor", "--quick")
        self.assertEqual(code, 1)
        self.assertIn("[FAIL] connection", out)
        self.assertIn("something that is not JSON (text/html)", out)
        self.assertNotIn("reachable, the credentials are accepted", out)

    def test_a_page_that_is_read_is_not_a_blank_page(self):
        answers = self.serve(PROXY_PAGE, headers=HTML)
        code, out, err = self.program(answers, "page", "2002")
        self.assertEqual((code, out), (7, ""))
        code, out, err = self.program(answers, "pages", "--space", "ENG")
        self.assertEqual((code, out), (7, ""))  # the space is read first: not "No space with the key ENG"
        self.assertNotIn("No space", err)

    def test_the_document_that_the_site_serves_for_its_tenant_is_checked_as_it_was(self):
        answers = self.serve(PROXY_PAGE, headers=HTML)
        code, out, err = self.program(answers, "setup", "--discover", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("does not hold the cloud id", err)

    def test_json_of_another_kind_is_no_answer_to_a_call_that_needs_an_object(self):
        """`[]` and `null` are valid JSON and no answer: every call that reads something or makes it needs an object (a list is an object with `results`)."""
        for body, kind in ((b"[]", "a list"), (b"null", "null"), (b"5", "a number"), (b'"text"', "a text"), (b"true", "true or false"), (b'[{"results": []}]', "a list")):
            answers = self.serve(body, headers={"Content-Type": "application/json"})
            for name, read in self.reads(self.gateway(answers)).items():
                with self.subTest(body=body, read=name), self.assertRaises(UnavailableError) as caught:
                    read()
                self.assertEqual(caught.exception.exit_code, 7)
                self.assertEqual(caught.exception.message, f"Confluence answered HTTP 200 with {kind}, where a JSON object was expected.")
                self.assertEqual(set(caught.exception.details), {"status", "request"})

    def test_an_object_that_holds_nothing_is_still_an_answer(self):
        """`{}` and an object whose `results` is not a list are objects: what the code makes of them is its own tolerance, as it was."""
        for body in (b"{}", b'{"results": null}', b'{"results": "x"}', b'{"results": []}'):
            answers = self.serve(body, headers={"Content-Type": "application/json"})
            with self.subTest(body=body):
                self.assertEqual(self.gateway(answers).list_tasks().items, [])

    def test_a_refusal_with_a_body_of_another_kind_is_what_its_status_says(self):
        for status, error in ((400, RejectedError), (403, AuthError), (404, NotFoundError), (409, ConflictError), (500, UnavailableError)):
            for body in (b"[]", b"null", b'"x"'):
                answers = self.serve(body, status=status, headers={"Content-Type": "application/json"})
                with self.subTest(status=status, body=body), self.assertRaises(error) as caught:
                    self.gateway(answers).get_page("2002")
                self.assertNotIn("where a JSON object was expected", caught.exception.message)


class WhatTheCallNeedsTest(StubbedCase):
    """A call that makes something needs the answer that says what it made: a property that is "created" by the page of a proxy is no property."""

    WRITES = {
        "create_property": lambda gateway: gateway.create_property("page", "2002", {"key": "zz.new", "value": 1}),
        "update_task": lambda gateway: gateway.update_task("7203", {"id": "7203", "status": "complete"}),
        "create_page": lambda gateway: gateway.create_page({"spaceId": "1001", "title": "T", "body": {"representation": "storage", "value": "<p>x</p>"}}),
        "update_page": lambda gateway: gateway.update_page("2002", {"id": "2002", "status": "current", "title": "T"}),
        "add_comment": lambda gateway: gateway.add_comment({"pageId": "2002", "body": {"representation": "storage", "value": "<p>x</p>"}}),
        "add_labels": lambda gateway: gateway.add_labels("2002", [{"prefix": "global", "name": "notes"}]),
    }
    NOTHING = {
        "remove_label": lambda gateway: gateway.remove_label("2002", "notes"),
        "move_page": lambda gateway: gateway.move_page("2002", "append", "2003"),
        "change_watch": lambda gateway: gateway.change_watch(WatchChange(CONTENT, "2002", True)),
        "stop_watch": lambda gateway: gateway.change_watch(WatchChange(SPACE, "ENG", False)),
    }

    def test_a_write_that_gets_the_page_of_a_proxy_or_no_data_or_the_wrong_kind_has_made_nothing_that_it_can_report(self):
        for body, status, headers, said in (
            (PROXY_PAGE, 200, HTML, "something that is not JSON (text/html)"),
            (b"", 200, {}, "an empty body"),
            (b"", 201, {}, "an empty body"),
            (b"", 204, {}, "an empty body"),
            (b"[]", 200, {}, "a list, where a JSON object was expected"),
            (b"null", 201, {}, "null, where a JSON object was expected"),
        ):
            answers = self.serve(body, status=status, headers=headers)
            for name, write in self.WRITES.items():
                with self.subTest(write=name, status=status, body=body[:12]), self.assertRaises(UnavailableError) as caught:
                    write(self.gateway(answers))
                self.assertEqual(caught.exception.exit_code, 7)
                self.assertIn(said, caught.exception.message)

    def test_a_write_that_gets_what_it_needs_is_done(self):
        answers = self.serve(b'{"id": "7399", "key": "zz.new", "value": 1, "version": {"number": 1}}', headers={"Content-Type": "application/json"})
        created = self.gateway(answers).create_property("page", "2002", {"key": "zz.new", "value": 1})
        self.assertEqual((created.id, created.key, created.version), ("7399", "zz.new", 1))

    def test_a_call_that_ignores_its_answer_accepts_no_content_and_any_json(self):
        for body, status in ((b"", 204), (b"", 200), (b"", 201), (b"{}", 200), (b'{"id": "2002"}', 200), (b"[]", 200), (b"null", 200), (b"true", 200)):
            answers = self.serve(body, status=status, headers={"Content-Type": "application/json"} if body else {})
            for name, call in self.NOTHING.items():
                with self.subTest(call=name, status=status, body=body):
                    self.assertIsNone(call(self.gateway(answers)))

    def test_a_call_that_ignores_its_answer_does_not_take_the_page_of_a_proxy_for_it(self):
        answers = self.serve(PROXY_PAGE, headers=HTML)
        for name, call in self.NOTHING.items():
            with self.subTest(call=name), self.assertRaises(UnavailableError) as caught:
                call(self.gateway(answers))
            self.assertIn("something that is not JSON (text/html)", caught.exception.message)

    def test_a_call_that_ignores_its_answer_is_still_refused_when_it_is_refused(self):
        for status, error in ((403, AuthError), (404, NotFoundError), (409, ConflictError), (500, UnavailableError)):
            answers = self.serve(PROXY_PAGE, status=status, headers=HTML)
            for name, call in self.NOTHING.items():
                with self.subTest(call=name, status=status), self.assertRaises(error):
                    call(self.gateway(answers))

    def test_the_raw_api_prints_any_json_and_nothing_that_is_no_json(self):
        for body, value in ((b"[]", []), (b"null", None), (b"5", 5), (b'"text"', "text"), (b"true", True), (b'[{"a": 1}]', [{"a": 1}]), (b"{}", {})):
            answers = self.serve(body, headers={"Content-Type": "application/json"})
            with self.subTest(body=body):
                self.assertEqual(self.gateway(answers).request("GET", "/api/v2/spaces"), value)
        for body, status in ((b"", 200), (PROXY_PAGE, 200)):
            answers = self.serve(body, status=status, headers=HTML if body else {})
            with self.subTest(body=body[:10]), self.assertRaises(UnavailableError):
                self.gateway(answers).request("GET", "/api/v2/spaces")
        answers = self.serve(b"", status=204)
        self.assertEqual(self.gateway(answers).request("DELETE", "/api/v2/things/1"), {})  # an answer of no content is what a raw call may get


class TheReviewTest(StubbedCase):
    """The matrix of the review: `tasks`, `properties 2002` and `templates` with a 200 answer that is no answer."""

    BODIES = {
        "the page of a proxy": (PROXY_PAGE, HTML),
        "nothing": (b"", {}),
        "bytes that are no UTF-8": (b'{"results": [], "x": "\xff\xfe"}', {"Content-Type": "application/json"}),
        "a number of 5,000 digits": (b'{"results":[],"x":' + b"9" * 5000 + b"}", {"Content-Type": "application/json"}),
        "a list": (b"[]", {"Content-Type": "application/json"}),
        "null": (b"null", {"Content-Type": "application/json"}),
    }
    SAYS_NONE = ("No tasks", "No properties", "No templates", "Nothing found", "No content")

    def setUp(self):
        super().setUp()
        if hasattr(sys, "set_int_max_str_digits"):
            before = sys.get_int_max_str_digits()
            sys.set_int_max_str_digits(4300)  # the default: the number of 5,000 digits must be one that the decoder refuses
            self.addCleanup(sys.set_int_max_str_digits, before)

    def test_every_one_is_exit_code_7_and_none_says_that_there_is_nothing(self):
        for label, (body, headers) in self.BODIES.items():
            if "5,000 digits" in label and not hasattr(sys, "set_int_max_str_digits"):
                continue
            answers = self.serve(body, headers=headers)
            for argv in (("tasks",), ("properties", "2002"), ("templates",), ("templates", "--space", "ENG"), ("tasks", "--json"), ("properties", "2002", "--json")):
                with self.subTest(answer=label, argv=argv):
                    code, out, err = self.program(answers, *argv)
                    self.assertEqual((code, out), (7, ""), err)
                    for words in self.SAYS_NONE:
                        self.assertNotIn(words, out + err)
                    self.assertIn("Confluence answered", err)


class WriteAnsweredByAProxyTest(PropertiesFlow):
    """What the review did: a write of which nothing was changed, answered by the page of a proxy, was reported as done."""

    def answered(self, method, pattern, body=PROXY_PAGE, status=200, content_type="text/html"):
        answer = _Answer(self.mock, method, pattern, body, status, content_type)
        self.mock.extensions.insert(0, answer)  # asked before the routes of the mock
        return answer

    def test_a_property_that_is_created_by_the_page_of_a_proxy_is_not_created(self):
        answer = self.answered("POST", r"/api/v2/pages/2002/properties")
        result = self.cli("property-set", "2002", "--key", "zz.new", "--value", "1")
        self.assertEqual((result.code, result.out), (7, ""))
        self.assertEqual(answer.hits, 1)
        self.assertNotIn("Created", result.out + result.err)
        self.assertIn("something that is not JSON (text/html)", result.err)

    def test_the_same_for_no_data_and_for_the_wrong_kind(self):
        for body, status, content_type, said in ((b"", 200, "application/json", "an empty body"), (b"", 201, "application/json", "an empty body"), (b"[]", 200, "application/json", "a list, where"), (b"null", 201, "application/json", "null, where")):
            answer = self.answered("POST", r"/api/v2/pages/2002/properties", body, status, content_type)
            with self.subTest(body=body, status=status):
                result = self.cli("property-set", "2002", "--key", "zz.new", "--value", "1", "--json")
                self.assertEqual((result.code, result.out), (7, ""))
                self.assertIn(said, result.err)
                self.assertNotIn("created", result.out)
            self.mock.extensions.remove(answer)

    def test_a_property_that_is_changed_by_the_page_of_a_proxy_is_not_changed(self):
        self.answered("PUT", r"/api/v2/pages/2002/properties/7301")
        result = self.cli("property-set", "2002", "--key", "editor", "--value", '"v3"')
        self.assertEqual((result.code, result.out), (7, ""))
        self.assertNotIn("Updated", result.out + result.err)

    def test_a_task_that_is_completed_by_the_page_of_a_proxy_is_not_completed(self):
        answer = self.answered("PUT", r"/api/v2/tasks/7203")
        result = self.cli("task", "7203", "--complete")
        self.assertEqual((result.code, result.out), (7, ""))
        self.assertEqual(answer.hits, 1)
        self.assertNotIn("Completed", result.out + result.err)
        self.assertIn("something that is not JSON (text/html)", result.err)

    def test_a_write_that_the_mock_answers_is_done_as_it_was(self):
        result = self.cli("property-set", "2002", "--key", "zz.new", "--value", "1", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(result.json()["action"], "created")


class _Answer(Routes):
    """Answers one request of the mock with bytes of its own where the mock would answer with JSON: the page of a proxy for a write."""

    def __init__(self, mock, method, pattern, body, status=200, content_type="text/html"):
        super().__init__(mock)
        self.method, self.pattern, self.body, self.status, self.content_type = method, pattern, body, status, content_type
        self.hits = 0

    def handle(self, handler, method, path, query, query_pairs, body):
        if method != self.method or self.match(self.pattern, path) is None:
            return False
        self.hits += 1
        handler._reply_bytes(self.status, self.body, content_type=self.content_type)
        return True


class EveryCommandTest(StubbedCase):
    """What does each command do with an answer of HTTP 200 that is no JSON? Not what it does for an empty result: the command lines of the conformance
    sweep, one module for each feature area, run against the page of a proxy. A line that asked for anything and ended with exit code 0 is a command that
    took the page for an answer."""

    SKIPPED = {"sweep_personal"}  # the variants of the privacy sweep: the same commands again

    def test_no_command_that_asks_confluence_is_content_with_the_page_of_a_proxy(self):
        answers = self.serve(PROXY_PAGE, headers=HTML)
        base = self.environment(answers)
        contented, asked_lines, commands = [], 0, set()
        for module in SWEEPS:
            name = module.__name__.rpartition(".")[2]
            if name in self.SKIPPED:
                continue
            work = self.root / name
            work.mkdir()
            for item in module.LINES:
                if item.command in LOCAL:
                    continue
                for path, content in item.files:
                    target = Path(path.replace("{work}", work.as_posix())) if "{work}" in path else work / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
                argv = [text.replace("{work}", work.as_posix()) for text in item.argv]
                environ = {**base, **dict(item.env)}
                before = len(answers.requests)
                out, err = io.StringIO(), io.StringIO()
                code = run(argv, app_factory=lambda diagnostics, environ=environ: create_application(diagnostics, environ), environ=environ, stdout=out, stderr=err, stdin=io.StringIO(item.stdin))
                if len(answers.requests) > before:
                    asked_lines += 1
                    commands.add(item.command)
                    if code == 0:
                        contented.append(f"{name}: conflu {' '.join(item.argv)} -> {out.getvalue().strip()[:80]!r}")
        self.assertEqual(contented, [])
        self.assertGreater(asked_lines, 300)  # the sweep did ask (455 lines of it did): a test that asks nothing proves nothing
        self.assertTrue({"page", "pages", "search", "properties", "tasks", "templates", "ping", "doctor", "spaces", "export", "download", "attach"} <= commands, sorted(commands))


class ReviewReproductionTest(PropertiesFlow):
    """The reproduction of the review: the mock of the properties answers a list with an integer of 5,000 digits."""

    def setUp(self):
        super().setUp()
        before = sys.get_int_max_str_digits() if hasattr(sys, "get_int_max_str_digits") else None
        if before is None:
            self.skipTest("this Python does not limit the digits of an integer")
        sys.set_int_max_str_digits(4300)
        self.addCleanup(sys.set_int_max_str_digits, before)
        self.area.raw_answers.append(b'{"results":[{"id":"7399","key":"big","value":' + b"9" * 5000 + b',"version":{"number":1}}],"_links":{}}')

    def test_the_list_is_an_error_and_not_no_properties(self):
        result = self.cli("properties", "2002")
        self.assertEqual((result.code, result.out), (7, ""))
        self.assertIn("a number that is too long to be read (more than 4,300 digits)", result.err)
        self.assertNotIn("No properties", result.err)

    def test_json_has_no_count_of_zero(self):
        result = self.cli("properties", "2002", "--json")
        self.assertEqual((result.code, result.out), (7, ""))
        self.assertNotIn('"count"', result.err)

    def test_property_set_goes_to_no_creation_branch(self):
        result = self.cli("property-set", "2002", "--key", "big", "--value", "1")
        self.assertEqual((result.code, result.out), (7, ""))
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.calls(), [TYPES, ("GET", "/api/v2/pages/2002/properties")])

    def test_the_next_list_is_read_as_before(self):
        self.cli("properties", "2002")  # the raw answer is served once
        result = self.cli("properties", "2002", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertGreaterEqual(result.json()["count"], 1)


if __name__ == "__main__":
    unittest.main()
