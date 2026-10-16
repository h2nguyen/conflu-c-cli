"""HTTP and the Confluence gateway, against a mock Confluence Cloud in a thread."""
import base64
import json
import socket
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from conflu_c_cli.adapters.driven import http_transport
from conflu_c_cli.adapters.driven.confluence_mapper import search_hit_from
from conflu_c_cli.adapters.driven.confluence_rest import RestConfluenceGateway, _request_target
from conflu_c_cli.adapters.driven.http_transport import HttpResponse, HttpTransport
from conflu_c_cli.application.paging import fetch_all
from conflu_c_cli.application.settings import Settings
from conflu_c_cli.domain.errors import (
    AuthError,
    ConfigError,
    ConflictError,
    NotFoundError,
    RejectedError,
    UnavailableError,
)
from conflu_c_cli.domain.model import Attachment
from conflu_c_cli.domain.payloads import create_page_payload, label_payload, update_page_payload
from tests.support.fakes import ACCOUNT, RELEASE_NOTES_BODY
from tests.support.public_certificates import AMAZON_ROOT_CA_1, CROSS_SIGNED, INTERMEDIATE
from tests.support.mock_confluence import MockConfluence


class MockCase(unittest.TestCase):
    def setUp(self):
        self.mock = MockConfluence()
        self.mock.start()
        self.addCleanup(self.mock.stop)
        self.sleeps: list[float] = []
        self.debug: list[str] = []

    def settings(self, **overrides):
        values = dict(base_url=self.mock.base_url, email=self.mock.email, api_token=self.mock.token, retry=2, connect_timeout=5.0, max_time=10.0)
        values.update(overrides)
        return Settings(**values)

    def transport(self, **overrides):
        transport = HttpTransport(self.settings(**overrides), debug=self.debug.append, sleep=self.sleeps.append)
        self.addCleanup(transport.close)
        return transport

    def api(self, **overrides):
        return RestConfluenceGateway(self.settings(**overrides), self.transport(**overrides))

    def calls(self, method, prefix):
        return [item for item in self.mock.requests if item.method == method and item.path.startswith(prefix)]


class TransportTest(MockCase):
    def test_every_request_is_signed_with_basic_authentication(self):
        response = self.transport().request("GET", "/rest/api/user/current")
        self.assertEqual(response.status, 200)
        sent = self.mock.requests[-1]
        expected = "Basic " + base64.b64encode(f"{self.mock.email}:{self.mock.token}".encode()).decode()
        self.assertEqual(sent.headers["authorization"], expected)
        self.assertEqual(sent.headers["accept"], "application/json")
        self.assertEqual(sent.headers["accept-encoding"], "gzip")
        self.assertTrue(sent.headers["user-agent"].startswith("conflu-c-cli/"))
        self.assertEqual(sent.path, "/rest/api/user/current")

    def test_neither_the_token_nor_its_encoding_reaches_the_debug_log(self):
        self.transport().request("GET", "/rest/api/user/current")
        text = "\n".join(self.debug)
        self.assertIn("/rest/api/user/current -> 200", text)
        self.assertNotIn(self.mock.token, text)
        self.assertNotIn(base64.b64encode(f"{self.mock.email}:{self.mock.token}".encode()).decode(), text)

    def test_one_connection_serves_several_requests(self):
        transport = self.transport()
        transport.request("GET", "/rest/api/user/current")
        first = transport._connection
        transport.request("GET", "/api/v2/spaces?limit=1")
        self.assertIs(transport._connection, first)

    def test_gzip_answers_are_decoded(self):
        self.mock.gzip = True
        response = self.transport().request("GET", "/api/v2/spaces")
        self.assertEqual(response.headers.get("content-encoding"), "gzip")
        self.assertEqual({item["key"] for item in json.loads(response.body)["results"]}, {"ENG", "DOCS"})

    def test_an_answer_larger_than_the_limit_is_refused_without_being_read(self):
        with mock.patch.object(http_transport, "MAX_RESPONSE", 100):
            with self.assertRaises(UnavailableError) as caught:
                self.transport().request("GET", "/api/v2/spaces")
        self.assertIn("larger than 100 bytes", caught.exception.message)
        self.assertEqual(self.transport().request("GET", "/api/v2/spaces").status, 200)  # the connection and the limit recover

    def test_a_gzip_answer_that_grows_past_the_limit_is_refused(self):
        self.mock.gzip = True
        path = "/api/v2/pages/2002?body-format=storage"
        decoded = len(self.transport().request("GET", path).body)
        with mock.patch.object(http_transport, "MAX_RESPONSE", decoded - 1):
            with self.assertRaises(UnavailableError) as caught:
                self.transport().request("GET", path)
        self.assertIn("larger than", caught.exception.message)

    def test_a_read_is_retried_after_a_server_error_with_a_growing_wait(self):
        self.mock.fail_next("/api/v2/spaces", 503, times=2)
        response = self.transport().request("GET", "/api/v2/spaces?limit=1")
        self.assertEqual(response.status, 200)
        self.assertEqual(len(self.calls("GET", "/api/v2/spaces")), 3)
        self.assertEqual(self.sleeps, [1.0, 2.0])

    def test_the_wait_asked_for_by_the_server_is_honoured(self):
        self.mock.fail_next("/api/v2/spaces", 429, times=1, headers={"Retry-After": "3"})
        self.assertEqual(self.transport().request("GET", "/api/v2/spaces?limit=1").status, 200)
        self.assertEqual(self.sleeps, [3.0])

    def test_the_retries_run_out_and_the_last_answer_is_returned(self):
        self.mock.fail_next("/api/v2/spaces", 503, times=10)
        self.assertEqual(self.transport().request("GET", "/api/v2/spaces").status, 503)
        self.assertEqual(len(self.calls("GET", "/api/v2/spaces")), 3)
        self.mock.requests.clear()
        self.assertEqual(self.transport(retry=0).request("GET", "/api/v2/spaces").status, 503)
        self.assertEqual(len(self.mock.requests), 1)

    def test_a_write_is_never_retried(self):
        self.mock.fail_next("/api/v2/pages", 503, times=5, method="POST")
        response = self.transport().request("POST", "/api/v2/pages", body=b"{}")
        self.assertEqual(response.status, 503)
        self.assertEqual(len(self.calls("POST", "/api/v2/pages")), 1)
        self.assertEqual(self.sleeps, [])

    def test_an_unreachable_server_is_unavailable_and_says_what_to_check(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        transport = HttpTransport(self.settings(base_url=f"http://127.0.0.1:{port}/wiki", retry=1), sleep=self.sleeps.append)
        with self.assertRaises(UnavailableError) as caught:
            transport.request("GET", "/api/v2/spaces")
        self.assertIn("Cannot reach Confluence", caught.exception.message)
        self.assertIn("conflu doctor", caught.exception.hint)
        self.assertEqual(self.sleeps, [1.0])

    def test_what_is_missing_is_a_config_error_with_the_command_that_fixes_it(self):
        for overrides, name in (({"base_url": ""}, "CONFLUENCE_BASE_URL"), ({"email": ""}, "CONFLUENCE_EMAIL"), ({"api_token": ""}, "CONFLUENCE_API_TOKEN")):
            with self.subTest(name=name):
                with self.assertRaises(ConfigError) as caught:
                    self.transport(**overrides).request("GET", "/api/v2/spaces")
                self.assertIn(name, caught.exception.message)
                self.assertIn("conflu", caught.exception.hint)
        self.assertEqual(self.mock.requests, [])

    def test_a_bad_address_is_refused_before_anything_is_sent(self):
        for url, text in (
            ("http://confluence.example.com/wiki", "plain http"),
            ("ftp://example.atlassian.net/wiki", "not a valid web address"),
            ("https://user:secret@example.atlassian.net/wiki", "must not contain a user name"),
            ("https://example.atlassian.net/wiki?x=1", "must not contain a user name"),
            ("https://example.atlassian.net/wiki#frag", "must not contain a user name"),
        ):
            with self.subTest(url=url):
                with self.assertRaises(ConfigError) as caught:
                    self.transport(base_url=url).request("GET", "/api/v2/spaces")
                self.assertIn(text, caught.exception.message)
        self.assertNotIn("secret", " ".join(self.debug))

    def test_plain_http_is_allowed_on_this_computer_and_when_asked_for(self):
        self.assertEqual(self.transport().request("GET", "/api/v2/spaces?limit=1").status, 200)  # the mock is on 127.0.0.1
        remote = self.transport(base_url="http://confluence.example.com/wiki", allow_http=True)
        self.assertEqual(remote._target()[:2], ("http", "confluence.example.com"))

    def test_an_atlassian_address_without_wiki_gets_its_path(self):
        self.assertEqual(self.transport(base_url="https://example.atlassian.net")._target(), ("https", "example.atlassian.net", None, "/wiki"))
        self.assertEqual(self.transport(base_url="https://api.atlassian.com/ex/confluence/0a1b/")._target(), ("https", "api.atlassian.com", None, "/ex/confluence/0a1b/wiki"))

    def test_the_certificate_chain_and_host_name_are_always_verified_but_strict_x509_is_optional(self):
        relaxed = self.transport()._context()
        self.assertEqual((relaxed.verify_mode, relaxed.check_hostname), (ssl.CERT_REQUIRED, True))
        self.assertFalse(relaxed.verify_flags & getattr(ssl, "VERIFY_X509_STRICT", 0))
        strict = self.transport(tls_strict=True)._context()
        self.assertEqual(strict.verify_flags, ssl.create_default_context().verify_flags)  # Python's own default
        insecure = self.transport(insecure=True)._context()
        self.assertEqual((insecure.verify_mode, insecure.check_hostname), (ssl.CERT_NONE, False))

    def test_an_unreadable_ca_bundle_is_a_config_error(self):
        with self.assertRaises(ConfigError) as caught:
            self.transport(ca_bundle="C:/does/not/exist.pem")._context()
        self.assertIn("CONFLUENCE_CA_BUNDLE", caught.exception.message)

    def test_a_file_that_holds_no_certificate_is_a_config_error_too(self):
        with tempfile.TemporaryDirectory() as folder:
            bundle = Path(folder) / "notes.pem"
            bundle.write_text("this is not a certificate\n", encoding="utf-8")
            with self.assertRaises(ConfigError) as caught:
                self.transport(ca_bundle=str(bundle))._context()
        self.assertIn("CONFLUENCE_CA_BUNDLE", caught.exception.message)
        self.assertIn("PEM", caught.exception.hint)

    def test_the_ca_bundle_is_added_to_the_system_authorities_not_put_in_their_place(self):
        with tempfile.TemporaryDirectory() as folder:
            bundle = Path(folder) / "extra.pem"
            bundle.write_text(AMAZON_ROOT_CA_1, encoding="ascii")
            created = []
            real_create = ssl.create_default_context

            def spy(*args, **kwargs):
                created.append((args, kwargs))
                return real_create(*args, **kwargs)

            with mock.patch.object(ssl, "create_default_context", side_effect=spy):
                with mock.patch.object(ssl.SSLContext, "load_verify_locations", autospec=True) as load:
                    context = self.transport(ca_bundle=str(bundle))._context()
        self.assertEqual(created, [((), {})])  # the system's authorities, loaded as Python does by itself
        self.assertEqual(load.call_args_list[-1], mock.call(cafile=str(bundle)))  # and then the file on top of them
        self.assertEqual([call for call in load.call_args_list if call.kwargs.get("cafile") == str(bundle)], [load.call_args_list[-1]])  # once
        self.assertEqual((context.verify_mode, context.check_hostname), (ssl.CERT_REQUIRED, True))  # nothing else is relaxed

    def test_a_real_bundle_keeps_the_chain_and_host_name_checks(self):
        with tempfile.TemporaryDirectory() as folder:
            bundle = Path(folder) / "extra.pem"
            bundle.write_text(AMAZON_ROOT_CA_1, encoding="ascii")
            context = self.transport(ca_bundle=str(bundle))._context()
        self.assertEqual((context.verify_mode, context.check_hostname), (ssl.CERT_REQUIRED, True))
        self.assertGreater(len(context.get_ca_certs()), 0)

    def refusing_transport(self, verify_code, **overrides):
        """A transport whose connection attempt fails the way a refused certificate does."""
        error = ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
        error.verify_code = verify_code
        transport = self.transport(base_url="https://wiki.example.com/wiki", **overrides)
        patches = [mock.patch.object(HttpTransport, "_open", side_effect=error)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return transport

    def test_a_refused_certificate_is_not_asked_for_again_and_names_the_chain(self):
        transport = self.refusing_transport(20)
        with mock.patch.object(HttpTransport, "_presented_chain", return_value=[ssl.PEM_cert_to_DER_cert(INTERMEDIATE), ssl.PEM_cert_to_DER_cert(CROSS_SIGNED)]) as presented:
            with self.assertRaises(UnavailableError) as caught:
                transport.request("GET", "/api/v2/spaces")
        self.assertEqual(self.sleeps, [])  # a GET is retried after a network error, not after this: the answer is always the same
        presented.assert_called_once_with("wiki.example.com", None)
        hint = caught.exception.hint
        for name in ("Amazon RSA 2048 M04", "Amazon Root CA 1", "Starfield Services Root Certificate Authority - G2"):
            self.assertIn(name, hint)
        self.assertIn("CONFLUENCE_CA_BUNDLE", hint)
        self.assertIn("fingerprint", hint)
        self.assertIn("in addition to the system store", hint)

    def test_every_reason_for_an_unknown_authority_gets_the_note(self):
        for code in (2, 18, 19, 20, 21):
            with self.subTest(code=code):
                transport = self.refusing_transport(code)
                with mock.patch.object(HttpTransport, "_presented_chain", return_value=[ssl.PEM_cert_to_DER_cert(INTERMEDIATE)]):
                    with self.assertRaises(UnavailableError) as caught:
                        transport.request("GET", "/api/v2/spaces")
                self.assertIn("Amazon RSA 2048 M04", caught.exception.hint)

    def test_other_certificate_problems_are_not_asked_about_and_not_retried_either(self):
        for code in (10, 62):  # expired, wrong host name
            with self.subTest(code=code):
                self.sleeps.clear()
                transport = self.refusing_transport(code)
                with mock.patch.object(HttpTransport, "_presented_chain") as presented:
                    with self.assertRaises(UnavailableError) as caught:
                        transport.request("GET", "/api/v2/spaces")
                presented.assert_not_called()
                self.assertEqual(self.sleeps, [])
                self.assertIn("CONFLUENCE_CA_BUNDLE", caught.exception.hint)  # the general advice stays

    def test_an_explanation_that_cannot_be_had_leaves_the_general_advice(self):
        transport = self.refusing_transport(20)
        with mock.patch.object(HttpTransport, "_presented_chain", return_value=[]):
            with self.assertRaises(UnavailableError) as caught:
                transport.request("GET", "/api/v2/spaces")
        self.assertIn("CONFLUENCE_CA_BUNDLE", caught.exception.hint)
        self.assertNotIn("presented this chain", caught.exception.hint)

    def test_looking_at_the_chain_never_raises_and_sends_no_request(self):
        transport = self.transport()
        with mock.patch("socket.create_connection", side_effect=OSError("no network")):
            self.assertEqual(transport._presented_chain("wiki.example.com", None), [])
        self.assertEqual(self.mock.requests, [])

    def test_a_certificate_error_is_explained(self):
        transport = self.transport()
        self.assertIn("CONFLUENCE_CA_BUNDLE", transport._reach_hint("SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED] Missing Authority Key Identifier"))
        strict_hint = self.transport(tls_strict=True)._reach_hint("CERTIFICATE_VERIFY_FAILED")
        self.assertIn("CONFLUENCE_TLS_STRICT", strict_hint)
        self.assertNotIn("CONFLUENCE_TLS_STRICT", transport._reach_hint("CERTIFICATE_VERIFY_FAILED"))

    def test_a_download_follows_the_redirect_without_sending_the_credentials_to_the_media_host(self):
        response = self.transport().download("/download/attachments/2002/diagram.png?version=1&modificationDate=0&api=v2")
        self.assertEqual((response.status, response.body), (200, b"PNGDATA123"))
        from_api = self.calls("GET", "/download/attachments/2002/diagram.png")
        self.assertEqual(len(from_api), 1)
        self.assertIn("authorization", from_api[0].headers)
        self.assertEqual(len(self.mock.media_requests), 1)
        media = self.mock.media_requests[0]
        self.assertNotIn("authorization", media.headers)
        self.assertNotIn("cookie", media.headers)
        self.assertNotIn(self.mock.token, json.dumps(media.headers))
        self.assertNotIn("token=", "\n".join(self.debug))  # the media address carries a token of its own

    def test_a_redirect_to_a_plain_http_address_elsewhere_is_refused(self):
        self.mock.fail_next("/download/attachments", 302, headers={"Location": "http://files.example.com/file"})
        with self.assertRaises(UnavailableError) as caught:
            self.transport().download("/download/attachments/2002/diagram.png")
        self.assertIn("plain http", caught.exception.message)
        self.assertEqual(self.mock.media_requests, [])

    def test_a_redirect_with_credentials_in_the_address_is_refused(self):
        self.mock.fail_next("/download/attachments", 302, headers={"Location": "https://user:pw@files.example.com/file"})
        with self.assertRaises(UnavailableError):
            self.transport().download("/download/attachments/2002/diagram.png")

    def test_endless_redirects_stop(self):
        here = f"{self.mock.base_url}/download/attachments/2002/diagram.png"
        self.mock.fail_next("/download/attachments", 302, times=50, headers={"Location": here})
        with self.assertRaises(UnavailableError) as caught:
            self.transport().download("/download/attachments/2002/diagram.png")
        self.assertIn("too many times", caught.exception.message)
        self.assertLessEqual(len(self.calls("GET", "/download/attachments")), 7)

    def test_a_file_that_is_too_big_is_not_held_in_memory(self):
        with mock.patch.object(http_transport, "MAX_DOWNLOAD", 5):
            with self.assertRaises(UnavailableError) as caught:
                self.transport().download("/download/attachments/2002/diagram.png")
        self.assertIn("larger than", caught.exception.message)


class ReadTest(unittest.TestCase):
    """`_read` takes the size a server announces as a hint only; whatever it announces cannot crash it."""

    class Response:
        def __init__(self, announced, body=b"data"):
            self.announced, self._chunks = announced, [body, b""]

        def getheader(self, name, default=""):
            return self.announced if name == "Content-Length" else default

        def read(self, size):
            return self._chunks.pop(0)

    def test_odd_content_length_values_are_ignored_not_trusted(self):
        for announced in ("\u00b2", "\u0661\u0662", "-5", "1e3", " ", "abc", "12 ", ""):
            with self.subTest(announced=announced):
                self.assertEqual(http_transport.HttpTransport._read(self.Response(announced), 1000), b"data")

    def test_an_announced_size_beyond_the_limit_is_refused_before_reading(self):
        with self.assertRaises(UnavailableError):
            http_transport.HttpTransport._read(self.Response("1001"), 1000)


class GunzipTest(unittest.TestCase):
    """`_gunzip` is gzip.decompress with a ceiling on what comes out."""

    def test_it_gives_what_gzip_gives(self):
        import gzip

        for data in (b"", b"a", b"hello " * 1000, bytes(range(256)) * 300):
            with self.subTest(size=len(data)):
                self.assertEqual(http_transport._gunzip(gzip.compress(data), 10**7), data)

    def test_several_members_and_zero_padding_are_read_like_gzip_reads_them(self):
        import gzip

        wire = gzip.compress(b"first ") + gzip.compress(b"second") + b"\x00\x00\x00"
        self.assertEqual(http_transport._gunzip(wire, 1000), gzip.decompress(wire))

    def test_a_small_bomb_is_stopped_at_the_limit(self):
        import gzip
        import tracemalloc

        wire = gzip.compress(b"B" * (64 * 1024 * 1024))
        self.assertLess(len(wire), 100_000)
        tracemalloc.start()
        try:
            with self.assertRaises(UnavailableError) as caught:
                http_transport._gunzip(wire, 1024 * 1024)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertIn("larger than 1 MiB", caught.exception.message)
        self.assertLess(peak, 8 * 1024 * 1024)  # it stopped near the limit instead of building 64 MiB

    def test_truncated_and_damaged_data_are_errors(self):
        import gzip
        import zlib

        wire = gzip.compress(b"hello " * 1000)
        with self.assertRaises(EOFError):
            http_transport._gunzip(wire[:-10], 10**7)
        with self.assertRaises(zlib.error):
            http_transport._gunzip(b"not gzip at all", 10**7)
        damaged = bytearray(wire)
        damaged[-6] ^= 0xFF  # the checksum
        with self.assertRaises(zlib.error):
            http_transport._gunzip(bytes(damaged), 10**7)


class GatewayCase(MockCase):
    def setUp(self):
        super().setUp()
        self.gw = self.api()


class PeopleAndSpacesTest(GatewayCase):
    def test_the_current_user(self):
        user = self.gw.current_user()
        self.assertEqual((user.account_id, user.display_name, user.email), (ACCOUNT, "Alex Example", "alex@example.com"))

    def test_names_for_account_ids_in_bulk(self):
        found = self.gw.lookup_users([ACCOUNT, "unknown-account"])
        self.assertEqual(list(found), [ACCOUNT])
        self.assertEqual(found[ACCOUNT].display_name, "Alex Example")

    def test_more_than_250_ids_go_in_several_requests(self):
        self.gw.lookup_users([f"account-{number}" for number in range(300)] + [ACCOUNT])
        self.assertEqual(len(self.calls("POST", "/api/v2/users-bulk")), 2)

    def test_spaces_with_a_cursor(self):
        self.mock.page_cap = 1
        first = self.gw.list_spaces(limit=25)
        self.assertEqual(([space.key for space in first.items], bool(first.cursor)), (["ENG"], True))
        second = self.gw.list_spaces(limit=25, cursor=first.cursor)
        self.assertEqual(([space.key for space in second.items], second.cursor), (["DOCS"], ""))
        everything, truncated = fetch_all(lambda cursor: self.gw.list_spaces(cursor=cursor))
        self.assertEqual(([space.key for space in everything], truncated), (["ENG", "DOCS"], False))

    def test_one_space(self):
        space = self.gw.get_space("ENG")
        self.assertEqual((space.id, space.name, space.type, space.status, space.homepage_id), ("1001", "Engineering", "global", "current", "2001"))
        self.assertEqual(space.description, "Engineering documentation")
        self.assertEqual(space.url, f"{self.mock.base_url}/spaces/ENG")
        self.assertEqual(self.gw.get_space("eng").key, "ENG")  # the key is found in upper case too
        self.assertEqual(self.gw.get_space_by_id("1002").key, "DOCS")

    def test_an_unknown_space(self):
        with self.assertRaises(NotFoundError) as caught:
            self.gw.get_space("NOPE")
        self.assertIn("conflu spaces", caught.exception.hint)
        with self.assertRaises(NotFoundError):
            self.gw.get_space_by_id("9999")

    def test_a_filter_that_matches_nothing(self):
        self.assertEqual(self.gw.list_spaces(space_type="personal").items, [])
        self.assertEqual(self.gw.list_spaces(status="archived").items, [])


class PagesTest(GatewayCase):
    def test_a_page_with_everything_the_cli_shows(self):
        page = self.gw.get_page("2002")
        self.assertEqual((page.id, page.title, page.status, page.space_id, page.space_key, page.parent_id), ("2002", "Release notes", "current", "1001", "ENG", "2001"))
        self.assertEqual((page.version.number, page.version.created, page.version.message), (3, "2026-10-10T09:00:00.000Z", "Added the October notes"))
        self.assertEqual((page.author.account_id, page.owner.account_id), (ACCOUNT, ACCOUNT))
        self.assertEqual([label.name for label in page.labels], ["release", "notes"])
        self.assertEqual(page.body, RELEASE_NOTES_BODY)
        self.assertEqual(page.url, f"{self.mock.base_url}/spaces/ENG/pages/2002/Release+notes")
        self.assertEqual((page.updated, page.version_number), ("2026-10-10T09:00:00.000Z", 3))
        self.assertEqual(page.raw["id"], "2002")

    def test_without_the_body(self):
        self.assertIsNone(self.gw.get_page("2002", with_body=False).body)
        self.assertEqual(self.mock.requests[-1].query.get("body-format"), None)

    def test_an_unknown_page(self):
        with self.assertRaises(NotFoundError):
            self.gw.get_page("999")

    def test_listing_a_space_page_by_page(self):
        first = self.gw.list_pages(space_id="1001", limit=250)
        self.assertEqual(([page.id for page in first.items], bool(first.cursor)), (["2001", "2002"], True))
        everything, _ = fetch_all(lambda cursor: self.gw.list_pages(space_id="1001", cursor=cursor))
        self.assertEqual([page.id for page in everything], ["2001", "2002", "2003", "2004", "2005"])

    def test_the_filters(self):
        ids = lambda **kwargs: [page.id for page in fetch_all(lambda cursor: self.gw.list_pages(cursor=cursor, **kwargs))[0]]  # noqa: E731
        self.assertEqual(ids(space_id="1001", root_only=True), ["2001"])
        self.assertEqual(ids(ids=["2003", "2004"]), ["2003", "2004"])
        self.assertEqual(ids(space_id="1001", title="Plain page"), ["2005"])
        self.assertEqual(ids(space_id="1001", sort="-title")[0], "2002")
        self.assertEqual(ids(space_id="1001", status="archived"), [])
        self.assertEqual(ids(), ["2001", "2002", "2003", "2004", "2005", "3001"])
        self.assertEqual(ids(space_id="1002"), ["3001"])

    def test_bodies_come_with_the_list_on_request(self):
        pages = self.gw.list_pages(ids=["2005"], with_body=True).items
        self.assertEqual(pages[0].body, "<p>Just a paragraph &amp; text.</p>")
        self.assertIsNone(self.gw.list_pages(ids=["2005"]).items[0].body)

    def test_ancestors_have_titles_and_come_top_down(self):
        self.assertEqual([(ref.id, ref.title) for ref in self.gw.list_ancestors("2004")], [("2001", "Engineering Home"), ("2003", "Architecture")])
        self.assertEqual(self.gw.list_ancestors("2001"), [])

    def test_descendants_with_depth_and_cursor(self):
        self.mock.page_cap = 2
        nodes, _ = fetch_all(lambda cursor: self.gw.list_descendants("2001", depth=3, cursor=cursor))
        self.assertEqual({(node.id, node.parent_id, node.depth) for node in nodes}, {("2002", "2001", 1), ("2003", "2001", 1), ("2005", "2001", 1), ("2004", "2003", 2)})
        shallow, _ = fetch_all(lambda cursor: self.gw.list_descendants("2001", depth=1, cursor=cursor))
        self.assertEqual({node.id for node in shallow}, {"2002", "2003", "2005"})
        self.assertEqual({node.type for node in nodes}, {"page"})

    def test_versions_newest_first(self):
        versions, _ = fetch_all(lambda cursor: self.gw.list_versions("2002", cursor=cursor))
        self.assertEqual([(version.number, version.message) for version in versions], [(3, "Added the October notes"), (2, ""), (1, "Created")])
        self.assertEqual(versions[0].author.account_id, ACCOUNT)
        self.assertEqual(self.gw.list_versions("2002", limit=2).cursor, "2")


class PageWritesTest(GatewayCase):
    def test_a_page_is_created_below_the_home_page_or_a_parent(self):
        page = self.gw.create_page(create_page_payload("1001", "A new page", "<p>Hello</p>"))
        self.assertEqual((page.title, page.space_key, page.parent_id, page.version_number, page.status), ("A new page", "ENG", "2001", 1, "current"))
        self.assertEqual(self.gw.get_page(page.id).body, "<p>Hello</p>")
        below = self.gw.create_page(create_page_payload("1001", "Below", "", "2003"))
        self.assertEqual(below.parent_id, "2003")

    def test_a_title_that_exists_is_rejected_with_confluences_reason(self):
        with self.assertRaises(RejectedError) as caught:
            self.gw.create_page(create_page_payload("1001", "Plain page", ""))
        self.assertIn("already exists", caught.exception.message)
        self.assertEqual(caught.exception.details["status"], 400)

    def test_an_update_needs_the_next_version_number(self):
        page = self.gw.update_page("2005", update_page_payload("2005", "Plain page", "<p>New</p>", 2, "Edited"))
        self.assertEqual((page.version_number, page.version.message), (2, "Edited"))
        self.assertEqual(self.gw.get_page("2005").body, "<p>New</p>")
        with self.assertRaises(ConflictError) as caught:
            self.gw.update_page("2005", update_page_payload("2005", "Plain page", "<p>Late</p>", 2))
        self.assertEqual(caught.exception.exit_code, 3)
        self.assertEqual(caught.exception.details["status"], 409)
        self.assertEqual(self.gw.get_page("2005").body, "<p>New</p>")

    def test_a_title_alone(self):
        page = self.gw.update_title("2005", {"status": "current", "title": "Renamed"})
        self.assertEqual((page.title, page.version_number), ("Renamed", 2))
        self.assertEqual(self.gw.get_page("2005").body, "<p>Just a paragraph &amp; text.</p>")

    def test_moving_a_page(self):
        self.gw.move_page("2005", "append", "2003")
        self.assertEqual(self.gw.get_page("2005").parent_id, "2003")
        self.gw.move_page("2005", "before", "2002")
        self.assertEqual(self.gw.get_page("2005").parent_id, "2001")
        with self.assertRaises(RejectedError):
            self.gw.move_page("2003", "append", "2004")  # below its own descendant

    def test_unknown_pages_are_not_found(self):
        with self.assertRaises(NotFoundError):
            self.gw.update_page("999", update_page_payload("999", "T", "", 2))
        with self.assertRaises(NotFoundError):
            self.gw.move_page("999", "append", "2003")


class CommentsLabelsTest(GatewayCase):
    def test_conversations(self):
        roots = self.gw.list_comments("2002")
        self.assertEqual([(comment.id, comment.kind, comment.parent_id) for comment in roots.items], [("4001", "footer", "")])
        self.assertEqual(roots.items[0].body, "<p>Looks good.</p>")
        self.assertEqual(roots.items[0].author.account_id, ACCOUNT)
        self.assertEqual(roots.items[0].updated, "2026-10-02T10:00:00.000Z")
        replies = self.gw.list_replies("4001")
        self.assertEqual([(comment.id, comment.parent_id) for comment in replies.items], [("4002", "4001")])

    def test_inline_comments(self):
        comment = self.gw.list_comments("2002", inline=True).items[0]
        self.assertEqual((comment.id, comment.kind, comment.resolution), ("4003", "inline", "open"))

    def test_adding_a_comment_and_a_reply(self):
        created = self.gw.add_comment({"pageId": "2002", "body": {"representation": "storage", "value": "<p>Noted.</p>"}})
        self.assertEqual((created.kind, created.body, created.author.account_id), ("footer", "<p>Noted.</p>", ACCOUNT))
        reply = self.gw.add_comment({"pageId": "2002", "parentCommentId": created.id, "body": {"representation": "storage", "value": "<p>Yes.</p>"}})
        self.assertEqual(reply.parent_id, created.id)
        self.assertEqual([comment.id for comment in self.gw.list_replies(created.id).items], [reply.id])
        with self.assertRaises(NotFoundError):
            self.gw.add_comment({"pageId": "999", "body": {"representation": "storage", "value": "<p>x</p>"}})

    def test_every_label_is_read_however_the_server_cuts_the_list(self):
        self.mock.page_cap = 1
        self.assertEqual(sorted(label.name for label in self.gw.list_labels("2002")), ["notes", "release"])
        self.assertEqual(len(self.calls("GET", "/api/v2/pages/2002/labels")), 2)

    def test_labels(self):
        self.assertEqual(sorted(label.name for label in self.gw.list_labels("2002")), ["notes", "release"])
        added = self.gw.add_labels("2003", label_payload(["alpha", "beta"]))
        self.assertEqual(sorted(label.name for label in added), ["alpha", "beta"])
        self.gw.remove_label("2003", "alpha")
        self.assertEqual([label.name for label in self.gw.list_labels("2003")], ["beta"])
        with self.assertRaises(NotFoundError):
            self.gw.remove_label("2003", "never-there")
        with self.assertRaises(RejectedError):
            self.gw.add_labels("2003", label_payload(["two words"]))
        with self.assertRaises(NotFoundError):
            self.gw.list_labels("999")


class AttachmentsTest(GatewayCase):
    def test_listing_and_one_attachment(self):
        listed = self.gw.list_attachments("2002")
        self.assertEqual([(item.id, item.title, item.media_type, item.size) for item in listed.items], [("att5001", "diagram.png", "image/png", 10), ("att5002", "notes.txt", "text/plain", 12)])
        self.assertEqual([item.id for item in self.gw.list_attachments("2002", filename="notes.txt").items], ["att5002"])
        one = self.gw.get_attachment("att5001")
        self.assertEqual((one.version, one.page_id), (1, "2002"))
        self.assertTrue(one.download_link.startswith("/download/attachments/2002/diagram.png"))
        with self.assertRaises(NotFoundError):
            self.gw.get_attachment("att99999")

    def test_download_goes_through_the_media_service(self):
        self.assertEqual(self.gw.download_attachment(self.gw.get_attachment("att5002")), b"hello notes\n")
        self.assertEqual(len(self.mock.media_requests), 1)
        self.assertNotIn("authorization", self.mock.media_requests[0].headers)

    def test_a_download_without_a_link_uses_the_page_and_the_id(self):
        bare = Attachment("att5001", "diagram.png", page_id="2002")
        self.assertEqual(self.gw.download_attachment(bare), b"PNGDATA123")
        with self.assertRaises(NotFoundError):
            self.gw.download_attachment(Attachment("att5001", "diagram.png"))

    def test_upload_creates_and_then_versions(self):
        first = self.gw.upload_attachment("2003", "report.txt", b"first", comment="c1", minor=True)
        self.assertEqual((first.title, first.version, first.page_id, first.size, first.media_type, first.comment), ("report.txt", 1, "2003", 5, "text/plain", "c1"))
        sent = self.calls("PUT", "/rest/api/content/2003/child/attachment")[0]
        self.assertEqual(sent.headers["x-atlassian-token"], "nocheck")
        self.assertEqual((sent.body["fields"]["minorEdit"], sent.body["fields"]["comment"]), ("true", "c1"))
        self.assertTrue(sent.headers["content-type"].startswith("multipart/form-data; boundary="))
        second = self.gw.upload_attachment("2003", "report.txt", b"second version")
        self.assertEqual((second.id, second.version), (first.id, 2))
        self.assertEqual(self.gw.download_attachment(second), b"second version")

    def test_an_odd_file_name_does_not_break_the_multipart_body(self):
        item = self.gw.upload_attachment("2003", 'weird "name"\r\nx.txt', b"data")
        self.assertNotIn("\n", item.title)
        self.assertNotIn('"', item.title)
        unicode_name = self.gw.upload_attachment("2003", "Übersicht ✓.txt", "ünï".encode("utf-8"))
        self.assertEqual(unicode_name.title, "Übersicht ✓.txt")

    def test_unknown_pages(self):
        with self.assertRaises(NotFoundError):
            self.gw.upload_attachment("999", "x.txt", b"x")
        with self.assertRaises(NotFoundError):
            self.gw.list_attachments("999")


class SearchAndRawTest(GatewayCase):
    def test_a_search_hit_is_cleaned_and_complete(self):
        page = self.gw.search('type = page AND text ~ "release"')
        self.assertEqual((page.total, len(page.hits), page.start), (1, 1, 0))
        hit = page.hits[0]
        self.assertEqual((hit.id, hit.type, hit.title, hit.space_key), ("2002", "page", "Release notes", "ENG"))
        self.assertEqual(hit.url, f"{self.mock.base_url}/spaces/ENG/pages/2002/Release+notes")
        self.assertNotIn("@@@", hit.title + hit.excerpt)
        self.assertEqual(hit.last_modified, "2026-10-10T09:00:00.000Z")
        self.assertEqual(page.raw_results[0]["entityType"], "content")

    def test_a_title_and_an_excerpt_with_special_characters_come_out_as_written(self):
        self.mock.pages["2002"]["title"] = "Release & <notes> Q&A"
        raw = self.gw.request("GET", '/rest/api/search?cql=type = page AND text ~ "release"')["results"][0]
        self.assertIn("&amp;", raw["title"])  # what the service really sends: escaped
        self.assertEqual(raw["content"]["title"], "Release & <notes> Q&A")
        hit = self.gw.search('type = page AND text ~ "release"').hits[0]
        self.assertEqual(hit.title, "Release & <notes> Q&A")
        plain = self.gw.search('type = page AND text ~ "paragraph"').hits[0]
        self.assertIn("paragraph & text", plain.excerpt)  # the body of page 2005 says "a paragraph & text"
        self.assertNotIn("&amp;", plain.excerpt)

    def test_a_hit_without_content_gets_its_escaped_title_and_excerpt_unescaped(self):
        hit = search_hit_from({"title": "Q&amp;A @@@hl@@@docs@@@endhl@@@", "entityType": "space", "excerpt": "a &lt;b&gt; &amp;\n  c", "url": "/spaces/ENG"})
        self.assertEqual((hit.title, hit.excerpt), ("Q&A docs", "a <b> & c"))

    def test_the_title_of_the_content_wins_over_the_escaped_one(self):
        hit = search_hit_from({"title": "Fish &amp; Chips", "content": {"id": "7", "type": "page", "title": "Fish & Chips"}})
        self.assertEqual(hit.title, "Fish & Chips")
        self.assertEqual(search_hit_from({"title": "Only &lt;this&gt;"}).title, "Only <this>")

    def test_paging_by_offset(self):
        self.mock.page_cap = 2
        first = self.gw.search("type = page AND space = \"ENG\"", limit=25)
        self.assertEqual((len(first.hits), first.total), (2, 5))
        last = self.gw.search("type = page AND space = \"ENG\"", limit=25, start=4)
        self.assertEqual((len(last.hits), last.start), (1, 4))

    def test_filters_of_the_cql_builder_are_understood_by_the_server(self):
        from conflu_c_cli.domain import cql

        for query, expected in (
            (cql.content_search(label="adr"), ["2004"]),
            (cql.content_search(under="2003"), ["2004"]),
            (cql.content_search(title="plain", space="ENG"), ["2005"]),
            (cql.content_search(since="2026-10-10"), ["2002"]),
            (cql.content_search(text="ports adapters"), ["2004"]),
        ):
            with self.subTest(query=query):
                self.assertEqual(sorted(hit.id for hit in self.gw.search(query, limit=25).hits), expected)

    def test_a_query_the_server_cannot_parse_is_rejected_with_its_message(self):
        with self.assertRaises(RejectedError) as caught:
            self.gw.search("this is not cql")
        self.assertIn("cql", caught.exception.message.lower())

    def test_the_raw_call(self):
        self.assertEqual(self.gw.request("GET", "/api/v2/pages/2002")["id"], "2002")
        changed = self.gw.request("PUT", "/api/v2/pages/2005/title", {"status": "current", "title": "Raw"})
        self.assertEqual(changed["title"], "Raw")

    def test_a_raw_query_with_spaces_quotes_and_umlauts_is_sent_escaped(self):
        found = self.gw.request("GET", '/rest/api/search?cql=type=page AND space="ENG" AND text ~ "release"')
        self.assertEqual([item["content"]["id"] for item in found["results"]], ["2002"])
        self.assertEqual(self.mock.requests[-1].query["cql"], ['type=page AND space="ENG" AND text ~ "release"'])

    def test_a_request_target_keeps_what_is_escaped_and_drops_the_fragment(self):
        for typed, sent in (
            ("/api/v2/pages/2002", "/api/v2/pages/2002"),
            ('/rest/api/search?cql=a b&limit=5', "/rest/api/search?cql=a%20b&limit=5"),
            ("/rest/api/search?cql=a%20b%3D%22c%22", "/rest/api/search?cql=a%20b%3D%22c%22"),
            ('/rest/api/search?cql=text ~ "100%"', "/rest/api/search?cql=text%20~%20%22100%25%22"),
            ("/rest/api/search?cql=title ~ \u00dcbersicht", "/rest/api/search?cql=title%20~%20%C3%9Cbersicht"),
            ("/api/v2/pages/2002#fragment", "/api/v2/pages/2002"),
            ("/rest/api/search?cql=a+b,c;d:e@f", "/rest/api/search?cql=a+b,c;d:e@f"),
        ):
            with self.subTest(typed=typed):
                self.assertEqual(_request_target(typed), sent)


class ErrorMappingTest(MockCase):
    def raises(self, error, status, body=None, headers=None, **settings):
        gateway = self.api(**settings)
        attempts = 1 + settings.get("retry", 2) if status in (429, 502, 503, 504) else 1  # only these are retried
        self.mock.fail_next("/api/v2/spaces", status, times=attempts, body=body, headers=headers)
        with self.assertRaises(error) as caught:
            gateway.list_spaces()
        return caught.exception

    def test_a_refused_login_is_an_auth_error_that_says_what_to_do(self):
        error = self.raises(AuthError, 401)
        self.assertIn("did not accept the credentials", error.message)
        self.assertIn("conflu setup-token", error.hint)
        self.assertEqual(error.details["status"], 401)

    def test_a_custom_domain_is_named_as_the_likely_reason_for_a_refusal(self):
        gateway = RestConfluenceGateway(self.settings(base_url="https://wiki.example.com/wiki"), self.transport())
        anonymous = {"statusCode": 403, "message": 'com.atlassian.confluence.mvc.rest.common.exception.StacklessResponseStatusException: 403 FORBIDDEN "Request rejected because caller cannot access Confluence"'}
        for status in (401, 403):
            with self.subTest(status=status):
                with self.assertRaises(AuthError) as caught:
                    gateway._raise_for_status(HttpResponse(status, {}, b""), anonymous, "GET", "/rest/api/user/current")
                hint = caught.exception.hint
                self.assertIn("wiki.example.com is not an atlassian.net address", hint)
                self.assertIn("https://wiki.example.com/_edge/tenant_info", hint)
                self.assertIn("CONFLUENCE_BASE_URL https://api.atlassian.com/ex/confluence/CLOUD_ID", hint)

    def test_no_custom_domain_is_blamed_for_an_address_that_is_none(self):
        for base in ("https://example.atlassian.net/wiki", "https://example.atlassian.net", "https://api.atlassian.com/ex/confluence/0a1b-2c3d", self.mock.base_url):
            with self.subTest(base=base):
                gateway = RestConfluenceGateway(self.settings(base_url=base), self.transport())
                for status in (401, 403):
                    with self.assertRaises(AuthError) as caught:
                        gateway._raise_for_status(HttpResponse(status, {}, b""), {}, "GET", "/rest/api/user/current")
                    self.assertNotIn("tenant_info", caught.exception.hint)

    def test_a_look_alike_host_is_not_taken_for_an_atlassian_one(self):
        gateway = RestConfluenceGateway(self.settings(base_url="https://example.atlassian.net.evil.example/wiki"), self.transport())
        with self.assertRaises(AuthError) as caught:
            gateway._raise_for_status(HttpResponse(403, {}, b""), {}, "GET", "/x")
        self.assertIn("tenant_info", caught.exception.hint)

    def test_a_wrong_token_is_a_real_401_from_the_server(self):
        gateway = self.api(api_token="a-wrong-token")
        with self.assertRaises(AuthError):
            gateway.current_user()

    def test_a_refused_permission_shows_confluences_reason(self):
        error = self.raises(AuthError, 403, {"errors": [{"status": 403, "code": "FORBIDDEN", "title": "Forbidden", "detail": "You may not view this space"}]})
        self.assertIn("You may not view this space", error.message)

    def test_status_codes_become_the_documented_errors(self):
        self.assertEqual(self.raises(NotFoundError, 404, {"errors": [{"status": 404, "title": "Not Found"}]}).exit_code, 4)
        conflict = self.raises(ConflictError, 409, {"errors": [{"status": 409, "title": "Version conflict"}]})
        self.assertIn("Version conflict", conflict.message)
        self.assertIn("Read it again", conflict.hint)
        self.assertIn("gone", self.raises(RejectedError, 410).message)
        self.assertIn("rate", self.raises(UnavailableError, 429, retry=0).message)
        self.assertIn("server error", self.raises(UnavailableError, 500, {"errors": [{"title": "Internal", "detail": "boom"}]}).message)
        self.assertEqual(self.raises(RejectedError, 418).exit_code, 6)

    def test_both_error_shapes_are_explained(self):
        v2 = self.raises(RejectedError, 400, {"errors": [{"status": 400, "code": "INVALID_REQUEST_PARAMETER", "title": "Invalid parameter", "detail": "limit must be at most 250"}]})
        self.assertIn("limit must be at most 250", v2.message)
        older = self.raises(RejectedError, 400, {"statusCode": 400, "data": {"errors": [{"message": {"key": "x", "translation": "Label is too long"}}]}, "message": "Bad Request", "reason": "Bad Request"})
        self.assertIn("Label is too long", older.message)
        self.assertIn("no explanation", self.raises(RejectedError, 400, {}).message)

    def test_a_page_that_is_not_json_does_not_break_the_error(self):
        gateway = self.api()
        self.mock.fail_next("/api/v2/spaces", 502, times=3, body="<html>Bad gateway</html>")
        with self.assertRaises(UnavailableError) as caught:
            gateway.list_spaces()
        self.assertIn("502", caught.exception.message)

    def test_a_redirect_says_where_it_leads(self):
        error = self.raises(ConfigError, 302, headers={"Location": "https://other.example.com/wiki/api/v2/spaces?secret=1"})
        self.assertIn("other.example.com/wiki/api/v2/spaces", error.message)
        self.assertNotIn("secret=1", error.message)
        self.assertIn("CONFLUENCE_BASE_URL", error.hint)

    def test_the_credentials_are_taken_out_of_what_confluence_echoes(self):
        echoed = f"bad request for {self.mock.email}:{self.mock.token} with token {self.mock.token}"
        error = self.raises(RejectedError, 400, {"errors": [{"detail": echoed}]})
        self.assertNotIn(self.mock.token, error.message)
        self.assertNotIn(self.mock.token, json.dumps(error.details))
        encoded = base64.b64encode(f"{self.mock.email}:{self.mock.token}".encode()).decode()
        error = self.raises(RejectedError, 400, {"errors": [{"detail": f"saw {encoded}"}]})
        self.assertNotIn(encoded, error.message)

    def test_the_account_e_mail_is_taken_out_of_what_confluence_echoes(self):
        echoed = {"errors": [{"detail": f"{self.mock.email} may not do this", "title": f"user {self.mock.email}"}], "user": self.mock.email}
        for error_type, status in ((RejectedError, 400), (AuthError, 403), (NotFoundError, 404)):
            with self.subTest(status=status):
                error = self.raises(error_type, status, echoed)
                self.assertNotIn(self.mock.email, error.message + error.hint + json.dumps(error.details))

    def test_under_the_privacy_policy_people_are_taken_out_of_errors_too(self):
        body = {"errors": [{"detail": "Not allowed for alex@example.com"}], "user": {"accountId": ACCOUNT, "displayName": "Alex Example"}}
        error = self.raises(RejectedError, 400, body, hide_users=True)
        self.assertNotIn("alex@example.com", error.message + json.dumps(error.details))
        self.assertNotIn(ACCOUNT, json.dumps(error.details))
        self.assertNotIn("Alex Example", json.dumps(error.details))


if __name__ == "__main__":
    unittest.main()
