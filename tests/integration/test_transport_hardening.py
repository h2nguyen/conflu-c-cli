"""What the transport does with a `Retry-After` that cannot be waited for, and with an address that no URL can hold."""
import http.client
import math
import unittest
from unittest import mock

from conflu_c_cli.adapters.driven import http_transport
from conflu_c_cli.adapters.driven.http_transport import HttpTransport, _retry_delay
from conflu_c_cli.domain.errors import UnavailableError, UsageError
from tests.integration.test_http_and_gateway import MockCase


class RetryDelayTest(unittest.TestCase):
    def test_a_wait_the_server_asks_for_is_honoured_up_to_the_limit(self):
        self.assertEqual(_retry_delay(1, "3"), 3.0)
        self.assertEqual(_retry_delay(2, " 2.5 "), 2.5)
        self.assertEqual(_retry_delay(1, "0"), 0.0)
        self.assertEqual(_retry_delay(1, "-4"), 0.0)
        self.assertEqual(_retry_delay(1, "100"), http_transport._MAX_RETRY_WAIT)

    def test_without_a_wait_or_with_one_that_is_no_number_the_default_grows_with_the_attempts(self):
        for asked in (None, "", "soon", "Wed, 21 Oct 2026 07:28:00 GMT", "1,5", "3 seconds"):
            with self.subTest(asked=asked):
                self.assertEqual(_retry_delay(2, asked), 2.0)

    def test_a_value_that_is_not_a_finite_number_is_ignored_because_sleeping_for_it_raises(self):
        for asked in ("nan", "NaN", "-nan", "inf", "-inf", "Infinity", "1e999", "-1e999", "9" * 400):
            with self.subTest(asked=asked):
                delay = _retry_delay(3, asked)
                self.assertEqual(delay, 3.0)
                self.assertTrue(math.isfinite(delay))


class RetryAfterTest(MockCase):
    def test_a_read_that_is_told_to_wait_for_nan_waits_the_default_and_succeeds(self):
        for asked in ("nan", "inf", "-inf", "1e999"):
            with self.subTest(asked=asked):
                self.sleeps.clear()
                self.mock.fail_next("/api/v2/spaces", 429, times=1, headers={"Retry-After": asked})
                response = self.transport().request("GET", "/api/v2/spaces?limit=1")
                self.assertEqual(response.status, 200)
                self.assertEqual(self.sleeps, [1.0])  # one second for the first attempt, as without the header

    def test_the_answer_at_the_end_of_the_retries_is_returned_not_a_crash(self):
        self.mock.fail_next("/api/v2/spaces", 503, times=10, headers={"Retry-After": "nan"})
        self.assertEqual(self.transport().request("GET", "/api/v2/spaces").status, 503)
        self.assertEqual(self.sleeps, [1.0, 2.0])


class InvalidAddressTest(MockCase):
    def test_a_space_or_a_control_character_in_the_address_is_a_usage_error_and_nothing_is_sent(self):
        for path in ("/api/v2/pages/2002 x", "/api/v2/pages/2002\x01", "/api/v2/pages/2002\r\nX-Injected: 1", "/api/v2/pages/\x7f", "/api/v2/pages/a\tb"):
            with self.subTest(path=path):
                transport = self.transport()
                with self.assertRaises(UsageError) as caught:
                    transport.request("GET", path)
                self.assertEqual(caught.exception.exit_code, 2)
                self.assertIn("nothing was sent", caught.exception.message)
                self.assertIn("%20", caught.exception.hint)
        self.assertEqual(self.mock.requests, [])
        self.assertEqual(self.sleeps, [])  # and it was not tried again

    def test_it_is_not_retried_as_a_network_error_would_be(self):
        transport = self.transport(retry=5)
        with self.assertRaises(UsageError):
            transport.request("GET", "/api/v2/spaces?x=a b")
        self.assertEqual((self.mock.requests, self.sleeps), ([], []))

    def test_the_address_is_not_repeated_in_the_error_or_the_log(self):
        transport = self.transport()
        with self.assertRaises(UsageError) as caught:
            transport.request("GET", "/api/v2/pages/2002?token=s3cr3tpw x")
        shown = caught.exception.message + caught.exception.hint + "\n".join(self.debug)
        self.assertNotIn("s3cr3tpw", shown)
        self.assertNotIn("Cannot reach Confluence", shown)
        self.assertIsNone(caught.exception.__cause__)  # the text of the library repeats the address, and a traceback would print it

    def test_the_connection_is_usable_afterwards(self):
        transport = self.transport()
        self.assertEqual(transport.request("GET", "/api/v2/spaces?limit=1").status, 200)
        with self.assertRaises(UsageError):
            transport.request("GET", "/api/v2/pages/2002 x")
        self.assertEqual(transport.request("GET", "/api/v2/spaces?limit=1").status, 200)  # the library stops half-way into a request: the connection is dropped
        self.assertEqual(len(self.mock.requests), 2)

    def test_a_write_with_such_an_address_is_not_sent_either(self):
        with self.assertRaises(UsageError):
            self.transport().request("POST", "/api/v2/pages x", body=b"{}")
        self.assertEqual(self.mock.requests, [])

    def test_a_redirect_to_an_address_that_no_url_can_hold_blames_the_answer_not_the_address_that_was_asked_for(self):
        self.mock.fail_next("/download/attachments", 302, headers={"Location": f"{self.mock.media_url}/file with spaces?token=s3cr3tpw"})
        with self.assertRaises(UnavailableError) as caught:  # the person typed no such address: the server's answer holds it
            self.transport().download("/download/attachments/2002/diagram.png")
        self.assertEqual(caught.exception.exit_code, 7)
        self.assertNotIn("s3cr3tpw", caught.exception.message + caught.exception.hint + "\n".join(self.debug))
        self.assertEqual(self.mock.media_requests, [])

    def test_the_control_characters_are_what_the_library_refuses(self):
        """The transport leaves the decision to http.client: whatever it takes for an address that no URL can hold is one."""
        refusal = http.client.InvalidURL("URL can't contain control characters. '/x' (found at least ' ')")
        with mock.patch("http.client.HTTPConnection.putrequest", side_effect=refusal):
            with self.assertRaises(UsageError):
                self.transport().request("GET", "/api/v2/spaces")
        self.assertEqual(self.sleeps, [])

    def test_an_ipv6_address_goes_to_the_library_in_brackets_so_that_no_group_of_it_is_taken_for_a_port(self):
        opened = []

        class Stop(Exception):
            pass

        def refuse(name, port=None, **options):
            opened.append((name, port))
            raise Stop

        with mock.patch("http.client.HTTPConnection", refuse):
            for base, expected in (("http://[::1]/wiki", ("[::1]", None)), ("http://[::1]:8080/wiki", ("[::1]", 8080)), ("http://localhost:8080/wiki", ("localhost", 8080))):
                with self.subTest(base=base), self.assertRaises(Stop):
                    HttpTransport(self.settings(base_url=base)).request("GET", "/api/v2/spaces")
                self.assertEqual(opened[-1], expected)
        # and what the library makes of the brackets: the host without them, and no port in the name
        connection = http.client.HTTPConnection("[::1]", None)
        self.assertEqual((connection.host, connection.port), ("::1", 80))


if __name__ == "__main__":
    unittest.main()
