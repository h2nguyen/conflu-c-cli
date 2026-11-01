"""The time and the size that an answer may take, and what a hostile answer ends as.

`CONFLUENCE_MAX_TIME` is for the whole answer: the socket timeout is for each wait, and a server that sends a byte now and then never trips it.
A row of gzip members is copied once for each member, so a body of empty ones took minutes. And what an answer says about itself (a redirect
to an address, a total, a length) is the problem of the answer: exit code 7, never "unexpected", never a blame on the address that the person
typed. The answers that no Confluence gives come from a small server on this computer; nothing else is ever asked.
"""
import gzip
import http.client
import json
import socket
import threading
import time
import types
import unittest
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from conflu_c_cli.adapters.driven import confluence_mapper, map_templates, rest_support
from conflu_c_cli.adapters.driven.http_transport import MAX_GZIP_MEMBERS, AnswerTooBig, HttpTransport, _gunzip
from conflu_c_cli.application.settings import Settings
from conflu_c_cli.domain.errors import ConfigError, UnavailableError
from tests.integration.test_end_to_end import EndToEnd
from tests.integration.test_http_and_gateway import MockCase


class _Quiet(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass  # a client that hung up is what these tests want


class _Server:
    """A server on this computer whose answer is whatever `respond(handler)` writes."""

    def __init__(self, respond):
        self.requests: list[str] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            disable_nagle_algorithm = True  # a byte is sent as a byte

            def do_GET(self):
                owner.requests.append(self.path)
                respond(self)

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


def dribbling(pieces: int, pause: float):
    """An answer of `pieces` bytes, one every `pause` seconds."""

    def respond(handler):
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(pieces))
        handler.end_headers()
        for _ in range(pieces):
            handler.wfile.write(b" ")
            handler.wfile.flush()
            time.sleep(pause)

    return respond


def sending(body: bytes, headers=None, length=None):
    def respond(handler):
        handler.send_response(200)
        for name, value in (headers or {}).items():
            handler.send_header(name, value)
        handler.send_header("Content-Length", str(len(body)) if length is None else length)
        handler.end_headers()
        handler.wfile.write(body)

    return respond


class DeadlineTest(unittest.TestCase):
    def transport(self, server, max_time=0.3, retry=0):
        settings = server.settings(retry=retry, max_time=max_time)
        self.sleeps: list[float] = []
        transport = HttpTransport(settings, sleep=self.sleeps.append)
        self.addCleanup(transport.close)
        return transport

    def test_an_answer_that_trickles_in_is_cut_off_when_the_time_for_the_whole_answer_is_up(self):
        with _Server(dribbling(40, 0.05)) as server:  # two seconds in all, a byte every 0.05 s: the socket never waits for 0.3 s
            started = time.monotonic()
            with self.assertRaises(UnavailableError) as caught:
                self.transport(server).request("GET", "/api/v2/spaces")
            elapsed = time.monotonic() - started
        self.assertEqual(caught.exception.exit_code, 7)
        self.assertIn("CONFLUENCE_MAX_TIME", caught.exception.message)  # what was still coming in
        self.assertIn("conflu config set CONFLUENCE_MAX_TIME 600", caught.exception.hint)  # and what allows more
        self.assertLess(elapsed, 1.5)  # without the deadline all two seconds are waited for

    def test_a_download_has_the_same_limit(self):
        with _Server(dribbling(40, 0.05)) as server:
            started = time.monotonic()
            with self.assertRaises(UnavailableError):
                self.transport(server).download("/download/attachments/2002/diagram.png")
            self.assertLess(time.monotonic() - started, 1.5)

    def test_the_time_that_a_caller_allows_is_the_limit_of_that_request(self):
        with _Server(dribbling(40, 0.05)) as server:
            started = time.monotonic()
            with self.assertRaises(UnavailableError):
                self.transport(server, max_time=30.0).request("GET", "/api/v2/spaces", timeout=0.3)
            self.assertLess(time.monotonic() - started, 1.5)

    def test_a_read_is_asked_again_and_each_try_has_the_whole_time_and_no_more(self):
        with _Server(dribbling(40, 0.05)) as server:
            started = time.monotonic()
            with self.assertRaises(UnavailableError):
                self.transport(server, retry=1).request("GET", "/api/v2/spaces")
            self.assertLess(time.monotonic() - started, 2.5)
            self.assertEqual(len(server.requests), 2)
            self.assertEqual(self.sleeps, [1.0])

    def test_an_answer_that_is_slow_but_inside_the_time_is_read_whole(self):
        with _Server(dribbling(10, 0.01)) as server:
            response = self.transport(server, max_time=5.0).request("GET", "/api/v2/spaces")
        self.assertEqual((response.status, response.body), (200, b" " * 10))

    def test_an_answer_that_is_there_at_once_does_not_notice_the_deadline(self):
        with _Server(sending(b'{"results": []}', {"Content-Type": "application/json"})) as server:
            response = self.transport(server, max_time=0.3).request("GET", "/api/v2/spaces")
        self.assertEqual(response.body, b'{"results": []}')

    def test_the_time_is_counted_from_the_end_of_the_request_so_that_a_slow_upload_has_not_used_it_up(self):
        real = http.client.HTTPConnection.request

        def slow(connection, *args, **options):
            real(connection, *args, **options)
            time.sleep(0.5)  # the upload took longer than the whole time that the answer may take

        with _Server(sending(b"{}")) as server, mock.patch("http.client.HTTPConnection.request", slow):
            response = self.transport(server, max_time=0.3).request("GET", "/api/v2/spaces")
        self.assertEqual(response.body, b"{}")


class _Body:
    """The part of an `HTTPResponse` that `_read` uses."""

    def __init__(self, pieces, length=None):
        self.pieces = list(pieces)
        self.length = length
        self.closed = False

    def getheader(self, name, default=""):
        return self.length if name == "Content-Length" and self.length is not None else default

    def read1(self, size):
        return self.pieces.pop(0) if self.pieces else b""

    def read(self, size):  # a stub of the old kind: it can only wait for the whole of what it is asked
        raise AssertionError("read() waits for as many bytes as asked: the pieces are taken with read1()")

    def close(self):
        self.closed = True


class ReadTest(unittest.TestCase):
    def test_a_deadline_that_has_passed_is_a_timeout_before_anything_is_read(self):
        body = _Body([b"x"])
        with self.assertRaises(TimeoutError) as caught:
            HttpTransport._read(body, 1000, time.monotonic() - 1.0)
        self.assertIn("CONFLUENCE_MAX_TIME", str(caught.exception))
        self.assertEqual(body.pieces, [b"x"])
        self.assertIsInstance(caught.exception, OSError)  # what the retry and the closing of the connection are made for

    def test_the_clock_is_looked_at_between_the_pieces(self):
        clock = iter([0.0, 0.0, 0.0, 99.0])  # three looks at the clock are in time, the fourth is not

        class Slow(_Body):
            def read1(self, size):
                return super().read1(size)

        with mock.patch("time.monotonic", lambda: next(clock)):
            with self.assertRaises(TimeoutError):
                HttpTransport._read(Slow([b"a", b"b", b"c", b"d", b"e"]), 1000, 10.0)

    def test_without_a_deadline_or_before_it_the_whole_body_is_read(self):
        self.assertEqual(HttpTransport._read(_Body([b"ab", b"cd"]), 1000), b"abcd")
        self.assertEqual(HttpTransport._read(_Body([b"ab", b"cd"]), 1000, time.monotonic() + 60.0), b"abcd")
        self.assertEqual(HttpTransport._read(_Body([]), 1000, time.monotonic() + 60.0), b"")

    def test_an_answer_that_was_read_to_its_end_is_closed_so_that_the_connection_takes_the_next_request(self):
        """Python 3.10, and 3.11 and 3.12 before December 2023, do not close an answer that `read1` read up to its Content-Length (gh-113199): the
        connection refuses the next request."""
        for pieces in ([b"ab", b"cd"], [b"ab"], []):
            with self.subTest(pieces=pieces):
                body = _Body(pieces)
                HttpTransport._read(body, 1000)
                self.assertTrue(body.closed)
        unfinished = _Body([b"abc", b"def"])
        with self.assertRaises(AnswerTooBig):
            HttpTransport._read(unfinished, 5)
        self.assertFalse(unfinished.closed)  # the connection is closed by the caller, which cannot use it again

    def test_a_response_without_read1_is_read_with_read(self):
        pieces = [b"ab", b"cd", b""]
        stub = types.SimpleNamespace(getheader=lambda name, default="": default, read=lambda size: pieces.pop(0), close=lambda: None)
        self.assertEqual(HttpTransport._read(stub, 1000, time.monotonic() + 60.0), b"abcd")

    def test_more_than_the_limit_is_refused_as_it_comes_in(self):
        with self.assertRaises(AnswerTooBig):
            HttpTransport._read(_Body([b"abc", b"def"]), 5)

    def test_a_length_of_thousands_of_digits_is_too_big_not_an_error_of_the_number_parser(self):
        for length in ("9" * 19, "9" * 5000, "1" + "0" * 400):
            with self.subTest(digits=len(length)), self.assertRaises(AnswerTooBig):
                HttpTransport._read(_Body([], length), 10)

    def test_a_length_that_is_no_number_is_not_believed_and_the_body_is_counted_instead(self):
        for length in ("\u00b2", "12abc", "", "-1", "1.5", " 5 "):
            with self.subTest(length=length):
                self.assertEqual(HttpTransport._read(_Body([b"ab"], length), 10), b"ab")

    def test_a_length_of_five_thousand_digits_from_a_server_ends_as_an_answer_that_is_too_big(self):
        with _Server(sending(b"x", length="9" * 5000)) as server:
            transport = HttpTransport(server.settings(max_time=5.0))
            self.addCleanup(transport.close)
            with self.assertRaises(UnavailableError) as caught:
                transport.request("GET", "/api/v2/spaces")
        self.assertIsInstance(caught.exception, AnswerTooBig)


class GzipMembersTest(unittest.TestCase):
    def counting(self, calls: list, stop_at: int = 1000):
        """`zlib.decompressobj`, counted: a body that would run for minutes ends the test with a failure instead."""
        real = zlib.decompressobj

        def decompressobj(*args, **options):
            calls.append(1)
            if len(calls) > stop_at:
                raise AssertionError(f"{stop_at} members were started: the limit is {MAX_GZIP_MEMBERS}")
            return real(*args, **options)

        return mock.patch("zlib.decompressobj", decompressobj)

    def test_up_to_the_limit_the_members_are_read_one_after_the_other(self):
        self.assertEqual(_gunzip(gzip.compress(b"ab") * MAX_GZIP_MEMBERS, 1000), b"ab" * MAX_GZIP_MEMBERS)
        self.assertEqual(_gunzip(gzip.compress(b"") * MAX_GZIP_MEMBERS, 1000), b"")
        self.assertEqual(_gunzip(gzip.compress(b"a") + b"\x00\x00\x00" + gzip.compress(b"b"), 1000), b"ab")  # padding between them is allowed

    def test_one_member_more_is_a_zlib_error_which_the_transport_calls_an_answer_that_could_not_be_read(self):
        with self.assertRaises(zlib.error) as caught:
            _gunzip(gzip.compress(b"ab") * (MAX_GZIP_MEMBERS + 1), 1000)
        self.assertIn(f"more than {MAX_GZIP_MEMBERS} gzip members", str(caught.exception))

    def test_a_hundred_thousand_empty_members_are_refused_at_once(self):
        body = gzip.compress(b"") * 100_000
        calls: list = []
        started = time.monotonic()
        with self.counting(calls), self.assertRaises(zlib.error):
            _gunzip(body, 64 * 1024 * 1024)
        self.assertEqual(len(calls), MAX_GZIP_MEMBERS)  # not one more was started
        self.assertLess(time.monotonic() - started, 5.0)  # the copies of the rest of the body for each of 100 000 members took minutes

    def test_the_limit_is_the_same_whatever_the_members_hold(self):
        calls: list = []
        with self.counting(calls), self.assertRaises(zlib.error):
            _gunzip(gzip.compress(b"x" * 100) * 5000, 64 * 1024 * 1024)
        self.assertEqual(len(calls), MAX_GZIP_MEMBERS)

    def test_the_size_limit_still_counts_what_the_members_make_together(self):
        with self.assertRaises(AnswerTooBig):
            _gunzip(gzip.compress(b"x" * 600) * 10, 5000)

    def test_a_body_of_members_from_a_server_is_an_answer_that_could_not_be_read(self):
        body = gzip.compress(b"") * 100_000  # two megabytes on the wire
        calls: list = []
        with self.counting(calls), _Server(sending(body, {"Content-Encoding": "gzip"})) as server:
            transport = HttpTransport(server.settings())
            self.addCleanup(transport.close)
            started = time.monotonic()
            with self.assertRaises(UnavailableError) as caught:
                transport.request("GET", "/api/v2/spaces")
        self.assertIn("could not be read", caught.exception.message)
        self.assertIn(f"more than {MAX_GZIP_MEMBERS} gzip members", caught.exception.message)
        self.assertEqual(caught.exception.exit_code, 7)
        self.assertEqual(len(calls), MAX_GZIP_MEMBERS)
        self.assertLess(time.monotonic() - started, 10.0)

    def test_an_answer_in_one_gzip_member_is_read_as_before(self):
        with _Server(sending(gzip.compress(b'{"a": 1}'), {"Content-Encoding": "gzip"})) as server:
            transport = HttpTransport(server.settings())
            self.addCleanup(transport.close)
            self.assertEqual(transport.request("GET", "/api/v2/spaces").body, b'{"a": 1}')


class RedirectOfADownloadTest(MockCase):
    """The `Location` of a redirect is the server's text: what no request can be made for is a damaged answer and nothing is sent to it."""

    def test_every_address_that_cannot_be_used_is_an_unavailable_error_and_nothing_is_sent_to_it(self):
        for location in ("/a b", "/\u00e9", "http://127.0.0.1:abc/x", "http://127.0.0.1:99999/x", "http://[::1/x", "http://]/x", "https://.example.com/x", "/x\x7f"):
            with self.subTest(location=location):
                self.mock.fail_next("/download/attachments", 302, headers={"Location": location})
                before = len(self.mock.requests)
                with self.assertRaises(UnavailableError) as caught:
                    self.transport().download("/download/attachments/2002/diagram.png")
                self.assertEqual(caught.exception.exit_code, 7)
                self.assertEqual(len(self.mock.requests), before + 1)  # the one that was redirected
                self.assertEqual(self.mock.media_requests, [])
                self.assertNotIn("CONFLUENCE_BASE_URL", caught.exception.message + caught.exception.hint)  # the address of the person is not at fault

    def test_the_error_does_not_blame_the_address_that_was_asked_for(self):
        self.mock.fail_next("/download/attachments", 302, headers={"Location": "/a b"})
        with self.assertRaises(UnavailableError) as caught:
            self.transport().download("/download/attachments/2002/diagram.png")
        self.assertIn("Confluence redirected the download", caught.exception.message)
        self.assertIn("Nothing was sent", caught.exception.hint)

    def test_a_port_that_is_no_port_is_a_damaged_answer_and_no_name_is_looked_up(self):
        """`urlsplit(...).port` raises a ValueError for `99999`: it ended as "unexpected ValueError" (exit code 1) instead of exit code 7."""
        looked_up: list[str] = []
        real = socket.getaddrinfo

        def watch(host, *args, **options):
            looked_up.append(str(host))
            return real(host, *args, **options)

        with mock.patch("socket.getaddrinfo", watch):
            for location in (
                "https://wiki.example.com:99999/x",
                "https://wiki.example.com:65536/x",
                "https://wiki.example.com:abc/x",
                "https://wiki.example.com:-1/x",
                "https://" + "name" + "@wiki.example.com:99999/x",
            ):
                with self.subTest(location=location):
                    self.mock.fail_next("/download/attachments", 302, headers={"Location": location})
                    with self.assertRaises(UnavailableError) as caught:
                        self.transport().download("/download/attachments/2002/diagram.png")
                    self.assertEqual(caught.exception.exit_code, 7)
                    self.assertIn("redirected the download to an address that cannot be read", caught.exception.message)
                    self.assertNotIn("wiki.example.com", caught.exception.message + caught.exception.hint)
        self.assertEqual(set(looked_up), {"127.0.0.1"})  # only the server that was asked: nothing was sent to, or looked up for, the address of the answer
        self.assertEqual(self.mock.media_requests, [])

    def test_a_good_redirect_is_still_followed(self):
        data = self.transport().download("/download/attachments/2002/diagram.png")
        self.assertEqual(data.status, 200)
        self.assertTrue(self.mock.media_requests)


class HostileAnswersTest(MockCase):
    def test_a_redirect_to_an_address_that_no_parser_takes_is_unavailable_not_a_wrong_address(self):
        for location in ("http://[", "http://]", "https://[::1"):
            with self.subTest(location=location):
                self.mock.fail_next("/api/v2/spaces", 302, headers={"Location": location})
                with self.assertRaises(UnavailableError) as caught:
                    self.api().list_spaces()
                self.assertEqual(caught.exception.exit_code, 7)
                self.assertIn("redirect (HTTP 302)", caught.exception.message)
                self.assertNotIn("CONFLUENCE_BASE_URL", caught.exception.message + caught.exception.hint)

    def test_a_redirect_with_an_address_is_still_a_wrong_address(self):
        self.mock.fail_next("/api/v2/spaces", 302, headers={"Location": "https://login.example.com/sso"})
        with self.assertRaises(ConfigError) as caught:
            self.api().list_spaces()
        self.assertIn("login.example.com/sso", caught.exception.message)
        self.assertIn("CONFLUENCE_BASE_URL", caught.exception.hint)

    def search_with(self, **answer):
        self.mock.fail_next("/rest/api/search", 200, body={"results": [], **answer})
        return self.api().search("type = page")

    def test_a_total_that_is_no_whole_number_is_an_unavailable_error(self):
        for total in ("many", None, [1], {"a": 1}, float("inf"), float("-inf"), float("nan"), "1e999", "", "1.5x"):
            with self.subTest(total=repr(total)), self.assertRaises(UnavailableError) as caught:
                self.search_with(totalSize=total)
            self.assertEqual(caught.exception.exit_code, 7)
            self.assertIn("not a number", caught.exception.message)

    def test_a_start_or_a_limit_that_is_no_number_is_the_same_error(self):
        for name in ("start", "limit"):
            with self.subTest(name=name), self.assertRaises(UnavailableError):
                self.search_with(totalSize=0, **{name: "x"})

    def test_an_answer_that_is_no_object_is_an_unavailable_error(self):
        for answer, kind in (([1, 2], "a list"), ("text", "a text"), (7, "a number"), (True, "true or false")):
            self.mock.fail_next("/rest/api/search", 200, body=answer)
            with self.subTest(answer=answer), self.assertRaises(UnavailableError) as caught:
                self.api().search("type = page")
            self.assertEqual(caught.exception.exit_code, 7)
            self.assertIn(f"with {kind}, where a JSON object was expected", caught.exception.message)

    def test_numbers_that_are_written_as_text_are_still_read(self):
        page = self.search_with(totalSize="3", start="0", limit="25")
        self.assertEqual((page.total, page.start, page.limit), (3, 0, 25))


class HostileAnswersEndAsUnavailableTest(EndToEnd):
    """The real program: a damaged answer is exit code 7 with the error that says so, never an "unexpected" one."""

    def test_a_total_that_is_no_number(self):
        self.mock.fail_next("/rest/api/search", 200, body={"results": [], "totalSize": "many"})
        result = self.cli("search", "release", "--json")
        self.assertEqual(result.code, 7, result.err)
        error = json.loads(result.err)["error"]
        self.assertEqual((error["code"], error["exitCode"]), ("UNAVAILABLE", 7))
        self.assertNotIn("Traceback", result.err)

    def test_a_redirect_that_no_parser_takes(self):
        self.mock.fail_next("/api/v2/spaces", 302, headers={"Location": "http://["})
        result = self.cli("spaces")
        self.assertEqual(result.code, 7, result.err)
        self.assertNotIn("Traceback", result.err)
        self.assertIn("redirect (HTTP 302)", result.err)

    def test_an_answer_of_the_search_that_is_a_list(self):
        self.mock.fail_next("/rest/api/search", 200, body=[1, 2, 3])
        self.assertEqual(self.cli("search", "release").code, 7)


class FieldsOfAnAnswerTest(unittest.TestCase):
    def test_a_link_to_the_next_piece_that_no_parser_takes_is_a_damaged_answer_not_the_end_of_the_list(self):
        for link in ("http://[", "http://]"):
            with self.subTest(link=link), self.assertRaises(UnavailableError) as caught:
                rest_support.next_cursor({"_links": {"next": link}})
            self.assertEqual(caught.exception.exit_code, 7)

    def test_the_cursor_is_read_from_a_link_and_what_has_no_link_is_the_last_piece(self):
        self.assertEqual(rest_support.next_cursor({"_links": {"next": "/wiki/api/v2/spaces?cursor=abc&limit=2"}}), "abc")
        self.assertEqual(rest_support.next_cursor({"_links": {"next": "/wiki/api/v2/spaces?limit=2"}}), "")
        for data in (None, [], "x", 5, {}, {"_links": None}, {"_links": []}, {"_links": "x"}, {"_links": {"next": 5}}, {"_links": {"next": ""}}, {"_links": {"next": None}}):
            with self.subTest(data=data):
                self.assertEqual(rest_support.next_cursor(data), "")

    def test_a_start_of_a_template_list_that_is_no_number_or_is_enormous_is_not_an_error_of_the_number_parser(self):
        for start in ("9" * 5000, "x", "", "\u00b2", "-3"):
            with self.subTest(start=start[:10]):
                page = map_templates.page_from({"results": [], "_links": {"next": f"/x?start={start}"}}, 0)
                self.assertIsNone(page.next_start)
        self.assertEqual(map_templates.page_from({"results": [], "_links": {"next": "/x?start=7"}}, 0).next_start, 7)

    def test_a_link_of_a_template_list_that_no_parser_takes_is_a_damaged_answer(self):
        with self.assertRaises(UnavailableError):
            map_templates.page_from({"results": [], "_links": {"next": "http://["}}, 0)

    def test_a_number_that_the_answer_leaves_out_is_the_default_and_one_that_it_holds_and_is_no_number_is_a_damaged_answer(self):
        for value in (None, ""):
            self.assertEqual(confluence_mapper._number(value, 5), 5)
        for value in (float("inf"), float("-inf"), float("nan"), [], [1], {}, {"n": 1}, "many", "1e999", True, False, "9" * 5000, "1" + "0" * 4400):
            with self.subTest(value=repr(value)[:20]), self.assertRaises(UnavailableError) as caught:
                confluence_mapper._number(value, 5, "a file size")
            self.assertEqual(caught.exception.exit_code, 7)
            self.assertIn("a file size that is not a number", caught.exception.message)
        self.assertEqual([confluence_mapper._number(value) for value in ("12", 3.9, 0, "0", -3, 7, " 8 ")], [12, 3, 0, 0, -3, 7, 8])


if __name__ == "__main__":
    unittest.main()
