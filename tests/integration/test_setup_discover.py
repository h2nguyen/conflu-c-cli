"""`conflu setup --discover` through the real adapters: the request that is made, and what the transport does with the answer.

The mock Confluence serves the public tenant information and records the request. For answers that no Confluence gives (a redirect, an answer that
is too big, one that is no JSON) a small server on this computer answers as the test says; nothing else is ever asked.
"""
import gzip
import json
import socket
import ssl
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from conflu_c_cli.adapters.driven.confluence_rest import RestConfluenceGateway
from conflu_c_cli.adapters.driven.http_transport import HttpTransport
from conflu_c_cli.application.settings import Settings
from conflu_c_cli.domain.errors import ConfigError, UnavailableError
from conflu_c_cli.version import __version__
from tests.integration.test_end_to_end import EndToEnd
from tests.support.public_certificates import CROSS_SIGNED, INTERMEDIATE

GATEWAY = "https://api.atlassian.com/ex/confluence/"
OTHER_CLOUD_ID = "ffffffff-1111-4222-8333-444444444444"


class SetupAgainstTheMockTest(EndToEnd):
    def only_request(self):
        self.assertEqual(len(self.mock.requests), 1, [item.target for item in self.mock.requests])
        return self.mock.requests[0]

    def test_the_request_carries_no_credential_and_goes_to_the_root_of_the_host(self):
        result = self.cli("setup", "--discover", "--yes", "--json")
        self.assertEqual(result.code, 0, result.err)
        sent = self.only_request()
        self.assertEqual((sent.method, sent.path), ("GET", "/_edge/tenant_info"))  # at the root, not below /wiki
        for name in ("authorization", "cookie", "proxy-authorization"):
            self.assertNotIn(name, sent.headers)
        self.assertNotIn(self.mock.token, json.dumps(sent.headers))
        self.assertNotIn(self.mock.email, json.dumps(sent.headers))
        self.assertEqual(sent.headers["accept"], "application/json")
        self.assertEqual(sent.headers["user-agent"], f"conflu-c-cli/{__version__}")
        self.assertEqual(self.mock.outside_calls, ["GET /_edge/tenant_info"])
        self.assertEqual((self.mock.used_endpoints, self.mock.unknown_endpoints), ([], []))

    def test_it_saves_the_gateway_address_with_the_cloud_id_that_the_site_names(self):
        self.mock.cloud_id = OTHER_CLOUD_ID
        result = self.cli("setup", "--discover", "--yes", "--json")
        self.assertEqual(result.code, 0, result.err)
        data = result.json()
        self.assertEqual((data["cloudId"], data["gatewayAddress"], data["written"], data["changed"]), (OTHER_CLOUD_ID, GATEWAY + OTHER_CLOUD_ID, True, True))
        self.assertEqual(data["current"], self.mock.base_url)
        self.assertIn(f"CONFLUENCE_BASE_URL={GATEWAY}{OTHER_CLOUD_ID}", self.config.read_text(encoding="utf-8"))
        self.assertIn("also set in the environment", result.err)  # the variable of this test overrides the file: the person is told

    def test_nothing_needs_to_be_configured_but_the_address(self):
        bare = {"CONFLUENCE_CONFIG_FILE": str(self.config), "HOME": str(self.root), "XDG_CACHE_HOME": str(self.root / "cache"), "CONFLUENCE_BASE_URL": self.mock.base_url}
        result = self.cli("setup", "--discover", "--yes", env=bare, replace_env=True)
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.only_request().headers.get("authorization"), None)
        stored = self.config.read_text(encoding="utf-8")
        self.assertIn(f"CONFLUENCE_BASE_URL={GATEWAY}{self.mock.cloud_id}", stored)
        self.assertNotIn("CONFLUENCE_API_TOKEN", stored)

    def test_the_address_may_come_from_the_configuration_file(self):
        self.config.parent.mkdir(parents=True)
        self.config.write_text(f"CONFLUENCE_BASE_URL={self.mock.base_url}\n", encoding="utf-8")
        only_the_file = {"CONFLUENCE_CONFIG_FILE": str(self.config), "HOME": str(self.root), "XDG_CACHE_HOME": str(self.root / "cache")}
        result = self.cli("setup", "--discover", "--yes", env=only_the_file, replace_env=True)
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(result.err, "")  # no variable overrides it
        self.assertEqual(self.config.read_text(encoding="utf-8").strip(), f"CONFLUENCE_BASE_URL={GATEWAY}{self.mock.cloud_id}")
        again = self.cli("setup", "--discover", "--yes", env=only_the_file, replace_env=True)  # the address is the gateway address now
        self.assertIn("is the gateway address already", again.out)
        self.assertEqual(len(self.mock.requests), 1)  # and nothing was asked the second time

    def test_without_yes_and_a_terminal_and_with_a_dry_run_the_site_is_asked_and_no_file_is_written(self):
        self.assertEqual(self.cli("setup", "--discover").code, 0)
        self.assertEqual(self.cli("setup", "--discover", "--dry-run").code, 0)
        self.assertFalse(self.config.exists())
        self.assertEqual([item.target for item in self.mock.requests], ["GET /_edge/tenant_info"] * 2)

    def test_a_site_that_is_not_there_is_unavailable_and_nothing_is_written(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        result = self.cli("setup", "--discover", "--yes", env={"CONFLUENCE_BASE_URL": f"http://127.0.0.1:{port}/wiki", "CONFLUENCE_RETRY": "0"})
        self.assertEqual(result.code, 7)
        self.assertIn("Cannot reach", result.err)
        self.assertFalse(self.config.exists())

    def test_the_commands_that_need_credentials_still_do(self):
        self.assertEqual(self.cli("ping", env={"CONFLUENCE_API_TOKEN": ""}).code, 1)  # only `setup --discover` goes without


class _Site:
    """A server on this computer that answers the tenant information as the test says, and records what it was asked."""

    def __init__(self, status=200, body=b"", headers=None, length=True):
        self.status, self.body, self.headers, self.length = status, body, dict(headers or {}), length
        self.requests: list[tuple[str, dict[str, str]]] = []
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                site.requests.append((self.path, {key.lower(): value for key, value in self.headers.items()}))
                self.send_response(site.status)
                for name, value in site.headers.items():
                    self.send_header(name, value)
                if site.length:
                    self.send_header("Content-Length", str(len(site.body)))
                self.end_headers()
                try:
                    self.wfile.write(site.body)
                except OSError:
                    pass  # the client refused the answer and hung up

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}/wiki"


class TenantInfoAnswersTest(unittest.TestCase):
    def ask(self, site, **overrides):
        settings = Settings(base_url=site.base_url, retry=overrides.pop("retry", 2), connect_timeout=5.0, max_time=10.0, **overrides)
        self.sleeps: list[float] = []
        transport = HttpTransport(settings, sleep=self.sleeps.append)
        self.addCleanup(transport.close)
        return RestConfluenceGateway(settings, transport).tenant_info(site.base_url)

    def refused(self, site, error=ConfigError, **overrides):
        with self.assertRaises(error) as caught:
            self.ask(site, **overrides)
        return caught.exception

    def test_the_cloud_id_of_the_answer_is_returned(self):
        for cloud_id in ("0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d", "abcdefgh", "A" * 64, "12345678"):
            with self.subTest(cloud_id=cloud_id[:12]), _Site(body=json.dumps({"cloudId": cloud_id}).encode()) as site:
                self.assertEqual(self.ask(site), cloud_id)
                self.assertEqual([path for path, _ in site.requests], ["/_edge/tenant_info"])

    def test_a_gzip_answer_is_read(self):
        with _Site(body=gzip.compress(b'{"cloudId": "0a1b2c3d-4e5f"}'), headers={"Content-Encoding": "gzip"}) as site:
            self.assertEqual(self.ask(site), "0a1b2c3d-4e5f")

    def test_other_members_of_the_answer_are_ignored(self):
        with _Site(body=b'{"cloudId": "0a1b2c3d-4e5f", "extra": {"deeper": [1, 2]}}') as site:
            self.assertEqual(self.ask(site), "0a1b2c3d-4e5f")

    def test_what_is_no_cloud_id_is_a_config_error_that_says_the_address_may_not_be_a_cloud_site(self):
        for body in (
            b"",
            b"<html>Sign in</html>",
            b"[]",
            b'"0a1b2c3d-4e5f"',
            b"{}",
            b'{"cloudId": null}',
            b'{"cloudId": 12345678}',
            b'{"cloudId": ""}',
            b'{"cloudId": "short"}',  # fewer than 8 characters
            b'{"cloudId": "' + b"a" * 65 + b'"}',  # more than 64
            b'{"cloudId": "0a1b2c3d 4e5f"}',
            b'{"cloudId": "0a1b2c3d/../x"}',
            b'{"cloudId": "0a1b2c3d\\n4e5f"}',
            b'{"cloudId": "0a1b2c3d4e5f\\u00e9"}',
            b'{"cloudId": ["0a1b2c3d4e5f"]}',
            b"\xff\xfe not utf-8",
        ):
            with self.subTest(body=body[:24]), _Site(body=body) as site:
                error = self.refused(site)
                self.assertEqual(error.exit_code, 1)
                self.assertIn("does not hold the cloud id", error.message)
                self.assertIn("may not be a Confluence Cloud site", error.hint)

    def test_a_status_that_is_not_200_says_so(self):
        for status in (204, 400, 401, 403, 404, 410):
            with self.subTest(status=status), _Site(status=status, body=b'{"cloudId": "0a1b2c3d-4e5f"}') as site:
                error = self.refused(site)
                self.assertIn(f"HTTP {status}", error.message)
                self.assertIn("may not be a Confluence Cloud site", error.hint)

    def test_an_answer_that_nests_too_deeply_to_be_read_is_unavailable_not_unexpected(self):
        """Sixty thousand `[` are inside the limit of 64 KiB, and the decoder gives up long before the end of them."""
        for body in (b"[" * 60000, b"[" * 60000 + b"]" * 5000, b'{"a":' * 9000 + b"1" + b"}" * 9000):
            with self.subTest(size=len(body)), _Site(body=body) as site:
                self.assertLess(len(body), 64 * 1024)
                error = self.refused(site, UnavailableError)
                self.assertEqual(error.exit_code, 7)
                self.assertIn("nests arrays or objects too deeply", error.message)
                self.assertIn("may not be a Confluence Cloud site", error.hint)

    def test_a_server_error_is_unavailable_and_is_asked_again_first(self):
        with _Site(status=503, body=b"busy") as site:
            error = self.refused(site, UnavailableError)
            self.assertIn("503", error.message)
            self.assertEqual(len(site.requests), 3)  # a read is retried
            self.assertEqual(self.sleeps, [1.0, 2.0])
        with _Site(status=429, body=b"slow down", headers={"Retry-After": "nan"}) as site:  # an answer that cannot be waited for is ignored
            self.refused(site, UnavailableError)
            self.assertEqual(self.sleeps, [1.0, 2.0])

    def test_a_redirect_is_not_followed_and_says_where_it_leads(self):
        with _Site(status=302, headers={"Location": "https://elsewhere.example.com/_edge/tenant_info?token=abc"}) as site:
            error = self.refused(site)
            self.assertEqual(len(site.requests), 1)
            self.assertIn("redirect (HTTP 302) to elsewhere.example.com", error.message)
            self.assertIn("not followed", error.message)
            self.assertNotIn("token=abc", error.message + error.hint)  # only the host is named
            self.assertNotIn("abc", error.message + error.hint)

    def test_every_kind_of_redirect_is_refused_the_same_way(self):
        for status in (301, 303, 307, 308):
            with self.subTest(status=status), _Site(status=status, headers={"Location": "/elsewhere"}) as site:
                error = self.refused(site)
                self.assertIn(f"HTTP {status}", error.message)
                self.assertEqual(len(site.requests), 1)

    def test_a_redirect_without_a_usable_location_is_still_refused(self):
        for location in ("", "http://[bad", "//", "mailto:x"):
            with self.subTest(location=location), _Site(status=302, headers={"Location": location} if location else {}) as site:
                self.assertIn("redirect", self.refused(site).message)

    def test_an_answer_of_more_than_64_kib_is_refused_whether_or_not_it_says_how_long_it_is(self):
        big = b'{"cloudId": "0a1b2c3d-4e5f", "padding": "' + b"x" * (64 * 1024) + b'"}'
        for length in (True, False):
            with self.subTest(announced=length), _Site(body=big, length=length) as site:
                error = self.refused(site)
                self.assertIn("larger than 64 KiB", error.message)
                self.assertIn("may not be a Confluence Cloud site", error.hint)

    def test_an_answer_that_grows_past_64_kib_when_it_is_unpacked_is_refused(self):
        bomb = gzip.compress(b'{"cloudId": "0a1b2c3d-4e5f", "padding": "' + b"x" * (1024 * 1024) + b'"}')
        self.assertLess(len(bomb), 64 * 1024)  # small on the wire
        with _Site(body=bomb, headers={"Content-Encoding": "gzip"}) as site:
            self.assertIn("larger than 64 KiB", self.refused(site).message)

    def test_an_answer_just_under_the_limit_is_read(self):
        padding = b"x" * (64 * 1024 - 100)
        with _Site(body=b'{"cloudId": "0a1b2c3d-4e5f", "padding": "' + padding + b'"}') as site:
            self.assertEqual(self.ask(site), "0a1b2c3d-4e5f")

    def test_no_credential_is_sent_even_when_all_are_set(self):
        with _Site(body=b'{"cloudId": "0a1b2c3d-4e5f"}') as site:
            self.ask(site, email="alex@example.com", api_token="a-very-secret-token")
            (_, headers), = site.requests
            self.assertNotIn("authorization", headers)
            self.assertNotIn("a-very-secret-token", json.dumps(headers))
            self.assertNotIn("alex@example.com", json.dumps(headers))
            self.assertEqual(set(headers) - {"host", "accept", "accept-encoding", "user-agent", "connection"}, set())  # nothing else goes with it


class TenantInfoAddressTest(unittest.TestCase):
    """The rules for the address of the site apply to this request as to every other, and nothing is sent before they are met."""

    def gateway(self, base_url, **overrides):
        settings = Settings(base_url=base_url, **overrides)
        transport = HttpTransport(settings)
        self.addCleanup(transport.close)
        return RestConfluenceGateway(settings, transport)

    def test_plain_http_to_a_host_of_the_network_is_refused_before_anything_is_sent(self):
        with mock.patch.object(HttpTransport, "_open", side_effect=AssertionError("a connection was made")):
            with self.assertRaises(ConfigError) as caught:
                self.gateway("http://wiki.example.com/wiki").tenant_info("http://wiki.example.com/wiki")
        self.assertIn("plain http", caught.exception.message)

    def test_plain_http_is_asked_when_it_is_allowed(self):
        with _Site(body=b'{"cloudId": "0a1b2c3d-4e5f"}') as site:  # this computer: allowed without a setting
            self.assertEqual(self.gateway(site.base_url).tenant_info(site.base_url), "0a1b2c3d-4e5f")
        opened = []

        def refuse(self, scheme, host, port):
            opened.append((scheme, host, port))
            raise OSError("no network in this test")

        with mock.patch.object(HttpTransport, "_open", refuse):
            with self.assertRaises(UnavailableError):
                self.gateway("http://wiki.example.com:8080/wiki", allow_http=True, retry=0).tenant_info("http://wiki.example.com:8080/wiki")
        self.assertEqual(opened, [("http", "wiki.example.com", 8080)])  # that host, on that port, and no other

    def test_the_host_and_port_of_the_address_are_the_ones_that_are_asked(self):
        opened = []

        def refuse(self, scheme, host, port):
            opened.append((scheme, host, port))
            raise OSError("no network in this test")

        with mock.patch.object(HttpTransport, "_open", refuse):
            for base in ("https://wiki.example.org/wiki", "https://wiki.example.org:8443/some/context", "https://EXAMPLE.atlassian.net", "https://example.atlassian.net/wiki/"):
                with self.assertRaises(UnavailableError):
                    self.gateway(base, retry=0).tenant_info(base)
        self.assertEqual(
            opened,
            [("https", "wiki.example.org", None), ("https", "wiki.example.org", 8443), ("https", "example.atlassian.net", None), ("https", "example.atlassian.net", None)],
        )

    def test_an_address_with_credentials_is_refused_before_anything_is_sent_and_is_not_repeated(self):
        secret = "s3cr3tpw"
        for base in (
            "https://" + "alex:" + secret + "@example.atlassian.net/wiki",
            "https://" + "alex:pa/" + secret + "@example.atlassian.net/wiki",
            "https://" + "alex:pa?" + secret + "@example.atlassian.net/wiki",
            "https://" + "alex:" + secret + "@example.atlassian.net:abc/wiki",
            "https://example.atlassian.net/wiki/" + "alex:" + secret + "@x",
            "alex:" + secret + "@example.atlassian.net/wiki",
        ):
            with self.subTest(base=base.replace(secret, "<secret>")), mock.patch.object(HttpTransport, "_open", side_effect=AssertionError("a connection was made")):
                with self.assertRaises(ConfigError) as caught:
                    self.gateway(base).tenant_info(base)
                self.assertNotIn(secret, caught.exception.message + caught.exception.hint + repr(caught.exception.details))
                self.assertNotIn("alex:", caught.exception.message)

    def test_an_address_that_is_none_is_refused(self):
        for base in ("ftp://example.atlassian.net/wiki", "example.atlassian.net", "https://", "https://[::1/wiki", "https://example.atlassian.net:abc/wiki", "https://example.atlassian.net/wiki?x=1", "https://example.atlassian.net/wiki#x"):
            with self.subTest(base=base), mock.patch.object(HttpTransport, "_open", side_effect=AssertionError("a connection was made")):
                with self.assertRaises(ConfigError):
                    self.gateway(base).tenant_info(base)

    def refusing_transport(self, verify_code):
        error = ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
        error.verify_code = verify_code
        patch = mock.patch.object(HttpTransport, "_open", side_effect=error)
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_refused_certificate_gets_the_explanation_of_every_other_request(self):
        self.refusing_transport(20)
        with mock.patch.object(HttpTransport, "_presented_chain", return_value=[ssl.PEM_cert_to_DER_cert(INTERMEDIATE), ssl.PEM_cert_to_DER_cert(CROSS_SIGNED)]) as presented:
            with self.assertRaises(UnavailableError) as caught:
                self.gateway("https://wiki.example.com/wiki").tenant_info("https://wiki.example.com/wiki")
        presented.assert_called_once_with("wiki.example.com", None)
        hint = caught.exception.hint
        for text in ("Amazon RSA 2048 M04", "Amazon Root CA 1", "CONFLUENCE_CA_BUNDLE", "fingerprint"):
            self.assertIn(text, hint)

    def test_another_certificate_problem_gets_the_general_advice(self):
        self.refusing_transport(10)  # expired
        with self.assertRaises(UnavailableError) as caught:
            self.gateway("https://wiki.example.com/wiki").tenant_info("https://wiki.example.com/wiki")
        self.assertIn("CONFLUENCE_CA_BUNDLE", caught.exception.hint)


if __name__ == "__main__":
    unittest.main()
