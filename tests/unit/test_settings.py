"""The settings: parsing, defaults, masking and the address of the wiki."""
import unittest

from conflu_c_cli.application.settings import (
    MAX_SECONDS,
    SETTING_DEFS,
    Settings,
    gateway_address,
    gateway_cloud_id,
    host_of,
    is_local_host,
    mask_personal,
    mask_secret,
    setting_definition,
    shown_address,
    wiki_root,
)
from conflu_c_cli.domain.errors import ConfigError


class SettingsTest(unittest.TestCase):
    def test_defaults(self):
        settings = Settings.from_mapping({})
        self.assertEqual((settings.base_url, settings.email, settings.api_token, settings.space), ("", "", "", ""))
        self.assertEqual((settings.connect_timeout, settings.max_time, settings.retry, settings.output), (10.0, 120.0, 2, "text"))
        self.assertEqual((settings.tls_strict, settings.insecure, settings.allow_http, settings.hide_users), (False, False, False, False))
        self.assertFalse(settings.json_by_default)

    def test_values_are_parsed_by_their_type(self):
        settings = Settings.from_mapping(
            {
                "CONFLUENCE_BASE_URL": " https://example.atlassian.net/wiki ",
                "CONFLUENCE_HIDE_USERS": "Yes",
                "CONFLUENCE_TLS_STRICT": "on",
                "CONFLUENCE_RETRY": "5",
                "CONFLUENCE_MAX_TIME": "30.5",
                "CONFLUENCE_OUTPUT": "json",
            }
        )
        self.assertEqual(settings.base_url, "https://example.atlassian.net/wiki")
        self.assertTrue(settings.hide_users and settings.tls_strict and settings.json_by_default)
        self.assertEqual((settings.retry, settings.max_time), (5, 30.5))

    def test_wrong_values_are_config_errors(self):
        for name, value in (
            ("CONFLUENCE_HIDE_USERS", "maybe"),
            ("CONFLUENCE_RETRY", "many"),
            ("CONFLUENCE_RETRY", "-1"),
            ("CONFLUENCE_MAX_TIME", "soon"),
            ("CONFLUENCE_MAX_TIME", "0"),
            ("CONFLUENCE_CONNECT_TIMEOUT", "nan"),
            ("CONFLUENCE_OUTPUT", "xml"),
        ):
            with self.subTest(name=name, value=value):
                with self.assertRaises(ConfigError):
                    Settings.from_mapping({name: value})

    def test_the_secret_and_the_e_mail_do_not_appear_in_repr(self):
        text = repr(Settings(email="user@example.com", api_token="very-secret-token"))
        self.assertNotIn("very-secret-token", text)
        self.assertNotIn("user@example.com", text)

    def test_every_setting_is_described_once(self):
        names = [definition.name for definition in SETTING_DEFS]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(name.startswith("CONFLUENCE_") for name in names))
        self.assertTrue(all(definition.description for definition in SETTING_DEFS))
        self.assertEqual([definition.name for definition in SETTING_DEFS if definition.secret], ["CONFLUENCE_API_TOKEN"])
        self.assertEqual([definition.name for definition in SETTING_DEFS if definition.personal], ["CONFLUENCE_EMAIL"])
        self.assertIsNone(setting_definition("CONFLUENCE_NOPE"))
        self.assertEqual(setting_definition("CONFLUENCE_SPACE").attr, "space")

    def test_masks(self):
        self.assertEqual(mask_secret(""), "(not set)")
        self.assertEqual(mask_secret("abcdef"), "******** (6 characters)")
        self.assertEqual(mask_personal("alex@example.com"), "a***@example.com")
        self.assertEqual(mask_personal(""), "(not set)")
        self.assertEqual(mask_personal("nonsense"), "***")


class AddressTest(unittest.TestCase):
    def test_the_wiki_gets_its_path(self):
        self.assertEqual(wiki_root("https://example.atlassian.net"), "https://example.atlassian.net/wiki")
        self.assertEqual(wiki_root("https://example.atlassian.net/"), "https://example.atlassian.net/wiki")
        self.assertEqual(wiki_root("https://example.atlassian.net/wiki/"), "https://example.atlassian.net/wiki")
        self.assertEqual(wiki_root(" HTTPS://Example.Atlassian.net "), "HTTPS://Example.Atlassian.net/wiki")

    def test_the_gateway_of_tokens_with_scopes_gets_its_path(self):
        self.assertEqual(wiki_root("https://api.atlassian.com/ex/confluence/0a1b2c"), "https://api.atlassian.com/ex/confluence/0a1b2c/wiki")
        self.assertEqual(wiki_root("https://api.atlassian.com/ex/confluence/0a1b2c/wiki"), "https://api.atlassian.com/ex/confluence/0a1b2c/wiki")

    def test_other_addresses_are_left_alone(self):
        self.assertEqual(wiki_root("http://127.0.0.1:8080/wiki/"), "http://127.0.0.1:8080/wiki")
        self.assertEqual(wiki_root("https://wiki.example.com"), "https://wiki.example.com")

    def test_the_wiki_url_of_settings(self):
        self.assertEqual(Settings(base_url="https://example.atlassian.net").wiki_url, "https://example.atlassian.net/wiki")

    def test_hosts(self):
        self.assertEqual(host_of("https://user:pw@Example.Atlassian.net:8443/wiki"), "example.atlassian.net")
        self.assertEqual(host_of("http://[::1]:8080/x"), "::1")
        self.assertEqual(host_of("not a url"), "")
        for host in ("localhost", "127.0.0.1", "::1"):
            self.assertTrue(is_local_host(host))
        for host in ("example.atlassian.net", "10.0.0.1", "localhost.example.com"):
            self.assertFalse(is_local_host(host))


class LocalHostTest(unittest.TestCase):
    """What is sent to a local host does not leave the computer: only a name or an address that really is one counts."""

    def test_the_loopback_addresses_and_localhost_are_local(self):
        for host in ("localhost", "LOCALHOST", "127.0.0.1", "127.0.0.2", "127.255.255.254", "::1"):
            with self.subTest(host=host):
                self.assertTrue(is_local_host(host))

    def test_a_name_that_only_starts_like_an_address_is_not(self):
        for host in ("127.example.com", "127.0.0.1.example.com", "127", "1270.0.0.1", "localhost.example.com", "notlocalhost", "::2", "0.0.0.0", "", "10.0.0.1", "192.168.0.1"):
            with self.subTest(host=host):
                self.assertFalse(is_local_host(host))


class TimeoutBoundsTest(unittest.TestCase):
    def test_a_timeout_of_more_than_a_day_is_refused_where_the_socket_layer_would_fail(self):
        for name in ("CONFLUENCE_MAX_TIME", "CONFLUENCE_CONNECT_TIMEOUT"):
            for value in ("86401", "3000000", "1e9", "1e308"):
                with self.subTest(name=name, value=value), self.assertRaises(ConfigError) as caught:
                    Settings.from_mapping({name: value})
                self.assertIn(f"at most {MAX_SECONDS}", caught.exception.message)

    def test_a_day_is_the_longest_timeout_that_is_accepted(self):
        settings = Settings.from_mapping({"CONFLUENCE_MAX_TIME": "86400", "CONFLUENCE_CONNECT_TIMEOUT": "86400"})
        self.assertEqual((settings.max_time, settings.connect_timeout), (86400.0, 86400.0))
        self.assertEqual(MAX_SECONDS, 86400)

    def test_zero_negative_and_not_a_number_are_still_refused(self):
        for value in ("0", "-1", "nan", "inf", "-inf"):
            with self.subTest(value=value), self.assertRaises(ConfigError):
                Settings.from_mapping({"CONFLUENCE_MAX_TIME": value})


USER, SECRET = "alex", "s3cr3tpw"
HOST = "example.atlassian.net"


class ShownAddressTest(unittest.TestCase):
    """An address ends up on the screen, in a result and in a log: what it holds as credentials must not."""

    def test_a_user_name_and_password_are_replaced(self):
        for written, shown in (
            (f"https://{USER}:{SECRET}@{HOST}/wiki", f"https://********@{HOST}/wiki"),
            (f"https://{USER}@{HOST}:8443/wiki", f"https://********@{HOST}:8443/wiki"),
            (f"http://{USER}:{SECRET}@127.0.0.1:8080", "http://********@127.0.0.1:8080"),
            (f"{USER}:{SECRET}@{HOST}/wiki", f"********@{HOST}/wiki"),
        ):
            with self.subTest(written=written.replace(SECRET, "<secret>")):
                self.assertEqual(shown_address(written), shown)
                self.assertNotIn(SECRET, shown_address(written))

    def test_an_address_with_an_at_after_the_host_name_is_not_shown_at_all(self):
        """A password that holds a `/`, `?` or `#` cannot be told apart from a path: the part before it is a part of the password."""
        for separator in ("/", "?", "#"):
            written = f"https://{USER}:pa{separator}{SECRET}@{HOST}/wiki"
            with self.subTest(separator=separator):
                shown = shown_address(written)
                self.assertTrue(shown.startswith("(not shown"))
                self.assertNotIn(SECRET, shown)
                self.assertNotIn(USER, shown)

    def test_an_address_without_credentials_is_shown_as_it_is(self):
        for plain in ("https://example.atlassian.net/wiki", "http://127.0.0.1:8080/wiki", "", "https://api.atlassian.com/ex/confluence/0a1b2c3d", "not an address"):
            with self.subTest(plain=plain):
                self.assertEqual(shown_address(plain), plain)


class GatewayAddressTest(unittest.TestCase):
    def test_the_cloud_id_is_in_the_gateway_address_with_or_without_the_wiki(self):
        for address in (
            "https://api.atlassian.com/ex/confluence/0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
            "https://api.atlassian.com/ex/confluence/0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d/",
            "https://api.atlassian.com/ex/confluence/0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d/wiki",
            "HTTPS://API.ATLASSIAN.COM/ex/confluence/0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d/wiki/",
        ):
            with self.subTest(address=address):
                self.assertEqual(gateway_cloud_id(address), "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d")

    def test_another_address_has_none(self):
        for address in (
            "",
            "https://example.atlassian.net/wiki",
            "http://api.atlassian.com/ex/confluence/0a1b2c3d",
            "https://api.atlassian.com/ex/jira/0a1b2c3d",
            "https://api.atlassian.com/ex/confluence/",
            "https://api.atlassian.com/ex/confluence/0a1b2c3d/other",
            "https://api.atlassian.com.example.org/ex/confluence/0a1b2c3d",
            f"https://{USER}@api.atlassian.com/ex/confluence/0a1b2c3d",
        ):
            with self.subTest(address=address):
                self.assertEqual(gateway_cloud_id(address), "")

    def test_the_address_made_of_a_cloud_id_is_the_one_that_is_recognised(self):
        self.assertEqual(gateway_address("0a1b2c3d"), "https://api.atlassian.com/ex/confluence/0a1b2c3d")
        self.assertEqual(gateway_cloud_id(gateway_address("0a1b2c3d")), "0a1b2c3d")
        self.assertEqual(wiki_root(gateway_address("0a1b2c3d")), "https://api.atlassian.com/ex/confluence/0a1b2c3d/wiki")


if __name__ == "__main__":
    unittest.main()
