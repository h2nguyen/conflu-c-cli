"""The settings: parsing, defaults, masking and the address of the wiki."""
import unittest

from conflu_c_cli.application.settings import (
    SETTING_DEFS,
    Settings,
    host_of,
    is_local_host,
    mask_personal,
    mask_secret,
    setting_definition,
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


if __name__ == "__main__":
    unittest.main()
