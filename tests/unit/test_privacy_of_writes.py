"""A page address and a write do not show what the people in a page would put there.

The address of a page ends in its title, and a title can hold an e-mail address; an `update` that appends sends the whole body, mentions
included. Neither may be printed when people are not shown. (tests/integration/test_privacy_sweep.py checks every command; this module
holds the rules of the helper and of `update`.)
"""
import unittest
from dataclasses import replace

from conflu_c_cli.domain.drafts import PageChanges
from conflu_c_cli.domain.model import SearchHit
from conflu_c_cli.domain.privacy import hide_hit, hide_users, redact_address, strip_users
from tests.support.cli import run_cli
from tests.support.fakes import ACCOUNT, BASE, FakeGateway, build_app, default_settings

HOST = "https://example.atlassian.net/wiki"


class RedactAddressTest(unittest.TestCase):
    def test_an_address_whose_title_holds_an_e_mail_address_ends_at_the_id(self):
        self.assertEqual(
            redact_address(f"{HOST}/spaces/ENG/pages/2002/Contact+alex%40example.com+about+SSO"),
            f"{HOST}/spaces/ENG/pages/2002",
        )

    def test_a_title_without_personal_data_stays_in_the_address(self):
        address = f"{HOST}/spaces/ENG/pages/2002/Release+notes+%28swept%29"
        self.assertEqual(redact_address(address), address)

    def test_the_address_of_a_blog_post_and_a_query_are_kept_where_they_belong(self):
        self.assertEqual(
            redact_address(f"{HOST}/spaces/ENG/blog/2026/10/04/7101/Mail+alex%40example.com?focusedCommentId=5#comment-5"),
            f"{HOST}/spaces/ENG/blog/2026/10/04/7101?focusedCommentId=5#comment-5",
        )

    def test_a_link_to_a_person_in_a_title_goes_too(self):
        slug = "Notes+https%3A%2F%2Fexample.atlassian.net%2Fwiki%2Fpeople%2F" + ACCOUNT  # Confluence writes the slashes of a title as %2F
        self.assertEqual(redact_address(f"{HOST}/spaces/ENG/pages/2002/{slug}"), f"{HOST}/spaces/ENG/pages/2002")

    def test_an_address_without_a_title_and_what_is_no_address_stay_as_they_are(self):
        for text in (f"{HOST}/spaces/ENG/pages/2002", f"{HOST}/spaces/ENG", "", "Plain text, no address.", "/spaces/ENG/overview"):
            with self.subTest(text=text):
                self.assertEqual(redact_address(text), text)
        self.assertEqual(redact_address(None), "")

    def test_the_raw_answer_of_the_api_is_scrubbed_in_its_addresses_too(self):
        raw = {"id": "2002", "_links": {"webui": "/spaces/ENG/pages/2002/Contact+alex%40example.com", "base": HOST}, "title": "Contact alex@example.com"}
        shown = strip_users(raw)
        self.assertEqual(shown["_links"], {"webui": "/spaces/ENG/pages/2002", "base": HOST})
        self.assertEqual(shown["title"], "Contact [email]")

    def test_a_page_and_a_hit_that_are_shown_without_people_have_no_e_mail_address_in_their_address(self):
        page = replace(FakeGateway().pages["2002"], title="Contact alex@example.com", url=f"{BASE}/spaces/ENG/pages/2002/Contact+alex%40example.com")
        self.assertEqual((hide_users(page).title, hide_users(page).url), ("Contact [email]", f"{BASE}/spaces/ENG/pages/2002"))
        hit = SearchHit("2002", "page", "Contact alex@example.com", "ENG", f"{BASE}/spaces/ENG/pages/2002/Contact+alex%40example.com", "", "", "", (), 1)
        self.assertEqual((hide_hit(hit).title, hide_hit(hit).url), ("Contact [email]", f"{BASE}/spaces/ENG/pages/2002"))


class UpdateShowsNoPeopleTest(unittest.TestCase):
    """Page 2002 of the fake has a mention (`ri:account-id`) and an e-mail address in its body."""

    def setUp(self):
        self.gateway = FakeGateway()
        self.app = build_app(gateway=self.gateway)
        self.tail = PageChanges(body="<p>tail</p>", body_mode="append", from_markdown=True)

    def test_an_append_shows_the_request_without_the_mention_and_the_address(self):
        result = self.app.update_page.execute("2002", self.tail, dry_run=True)
        shown = result.payload["body"]["value"]
        self.assertNotIn(ACCOUNT, shown)
        self.assertNotIn("alex@example.com", shown)
        self.assertIn("<p>tail</p>", shown)
        self.assertTrue(result.redacted)

    def test_what_is_sent_is_the_exact_request_and_still_has_the_mention(self):
        result = self.app.update_page.execute("2002", self.tail)
        sent = self.gateway.called("update_page")[0][2]["body"]["value"]
        self.assertIn(ACCOUNT, sent)
        self.assertIn("alex@example.com", sent)
        self.assertNotIn(ACCOUNT, result.payload["body"]["value"])
        self.assertTrue(result.redacted)

    def test_with_users_shows_the_request_exactly(self):
        result = self.app.update_page.execute("2002", self.tail, dry_run=True, with_users=True)
        self.assertIn(ACCOUNT, result.payload["body"]["value"])
        self.assertFalse(result.redacted)

    def test_a_request_with_nobody_in_it_is_shown_as_it_is(self):
        result = self.app.update_page.execute("2005", PageChanges(title="Renamed", body="<p>x</p>"), dry_run=True)
        self.assertFalse(result.redacted)
        self.assertEqual(result.payload["title"], "Renamed")

    def test_a_title_that_holds_an_address_is_shown_redacted_and_sent_as_it_is(self):
        self.app.update_page.execute("2005", PageChanges(title="Ask alex@example.com"))
        self.assertEqual(self.gateway.called("update_title")[0][2]["title"], "Ask alex@example.com")
        shown = self.app.update_page.execute("2005", PageChanges(title="Ask alex@example.com again"), dry_run=True)
        self.assertEqual(shown.payload["title"], "Ask [email] again")
        self.assertTrue(shown.redacted)


class UpdateCommandTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()

    def update(self, *argv, **kwargs):
        return run_cli("update", "2002", *argv, gateway=self.gateway, **kwargs)

    def test_the_json_says_that_the_printed_request_is_not_the_one_that_is_sent(self):
        result = self.update("--body", "tail", "--append", "--dry-run", "--json")
        self.assertEqual(result.code, 0, result.err)
        document = result.json()
        self.assertTrue(document["payloadRedacted"])
        self.assertNotIn(ACCOUNT, result.out)
        self.assertNotIn("alex@example.com", result.out)

    def test_the_text_says_so_and_points_at_the_option(self):
        result = self.update("--body", "tail", "--append", "--dry-run")
        self.assertIn("--with-users shows it as it is", result.out)
        self.assertNotIn(ACCOUNT, result.out)

    def test_with_users_prints_the_request_as_it_is(self):
        result = self.update("--body", "tail", "--append", "--dry-run", "--json", "--with-users")
        self.assertEqual(result.code, 0, result.err)
        self.assertFalse(result.json()["payloadRedacted"])
        self.assertIn(ACCOUNT, result.out)

    def test_with_users_is_refused_when_the_policy_forbids_people(self):
        result = self.update("--body", "tail", "--append", "--dry-run", "--with-users", settings=default_settings(hide_users=True))
        self.assertEqual(result.code, 1)
        self.assertIn("CONFLUENCE_HIDE_USERS=true", result.err)
        self.assertEqual(self.gateway.called("update_page"), [])

    def test_the_title_and_the_address_of_the_result_have_no_e_mail_address(self):
        page = self.gateway.pages["2005"]
        self.gateway.pages["2005"] = replace(page, title="Ask alex@example.com", url=f"{BASE}/spaces/ENG/pages/2005/Ask+alex%40example.com")
        result = run_cli("update", "2005", "--title", "Ask alex@example.com now", "--json", gateway=self.gateway)
        self.assertEqual(result.code, 0, result.err)
        document = result.json()
        self.assertEqual(document["title"], "Ask [email] now")
        self.assertNotIn("%40", document["url"])
        self.assertNotIn("alex", result.out.replace("Alex", ""))


if __name__ == "__main__":
    unittest.main()
