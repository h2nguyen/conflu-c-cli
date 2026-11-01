"""What the raw answer of `conflu api`, a page in a personal space and a search hit show when people are not shown."""
import unittest
from dataclasses import replace

from conflu_c_cli.domain.model import SearchHit
from conflu_c_cli.domain.privacy import HIDDEN, PERSONAL_SPACE, hide_hit, hide_users, page_address, redact_address, strip_users
from tests.support.fakes import ACCOUNT, BASE, FakeGateway

PERSONAL = f"~{ACCOUNT}"


class RawAnswerTest(unittest.TestCase):
    def test_the_people_of_a_task_are_hidden(self):
        raw = {"id": "7200", "status": "incomplete", "createdBy": ACCOUNT, "assignedTo": ACCOUNT, "completedBy": ACCOUNT, "body": {"storage": {"value": "<p>Do it</p>"}}}
        shown = strip_users(raw)
        self.assertEqual((shown["createdBy"], shown["assignedTo"], shown["completedBy"]), (HIDDEN, HIDDEN, HIDDEN))
        self.assertEqual(shown["id"], "7200")
        self.assertNotIn(ACCOUNT, str(shown))

    def test_the_id_of_a_principal_is_hidden_and_its_type_is_not(self):
        shown = strip_users({"principal": {"type": "user", "id": ACCOUNT}, "operation": "read"})
        self.assertEqual(shown, {"principal": {"type": "user", "id": HIDDEN}, "operation": "read"})

    def test_a_mention_in_the_other_body_formats_is_hidden(self):
        adf = {"type": "paragraph", "content": [{"type": "mention", "attrs": {"id": ACCOUNT, "text": "@Alex Example"}}]}
        view = '<a class="user-mention" data-account-id="%s">@Alex</a>' % ACCOUNT
        self.assertNotIn(ACCOUNT, str(strip_users(adf)))
        self.assertNotIn("Alex", str(strip_users(adf)))
        self.assertNotIn(ACCOUNT, strip_users(view))

    def test_a_user_that_has_only_a_name_is_hidden(self):
        self.assertEqual(strip_users({"ownedBy": {"displayName": "Alex Example"}, "id": "1"}), {"ownedBy": {"hidden": True}, "id": "1"})

    def test_a_personal_space_has_no_key_and_no_name(self):
        space = {"id": "9", "key": PERSONAL, "name": "Alex Example", "type": "personal", "description": "Alex's notes", "_links": {"webui": f"/spaces/{PERSONAL}"}}
        shown = strip_users(space)
        self.assertEqual((shown["key"], shown["name"], shown["id"], shown["type"]), (HIDDEN, PERSONAL_SPACE, "9", "personal"))
        self.assertNotIn(ACCOUNT, str(shown))
        self.assertEqual(strip_users({"id": "1", "key": "ENG", "name": "Engineering", "type": "global"})["key"], "ENG")


class PersonalSpaceAddressTest(unittest.TestCase):
    def test_the_address_of_a_page_in_a_personal_space_names_the_page_by_its_id(self):
        url = f"{BASE}/spaces/{PERSONAL}/pages/2002/Release+notes"
        self.assertEqual(page_address(url, "2002"), f"{BASE}/pages/viewpage.action?pageId=2002")
        self.assertEqual(redact_address(url), f"{BASE}/pages/viewpage.action?pageId=2002")
        self.assertEqual(redact_address(f"{BASE}/spaces/{PERSONAL}/blog/2026/10/04/7101/Update"), f"{BASE}/pages/viewpage.action?pageId=7101")
        self.assertEqual(page_address(f"{BASE}/spaces/ENG/pages/2002/Release+notes", "2002"), f"{BASE}/spaces/ENG/pages/2002/Release+notes")

    def test_other_content_of_a_personal_space_keeps_its_path_and_loses_the_key(self):
        self.assertEqual(redact_address(f"{BASE}/spaces/{PERSONAL}/folder/7001"), f"{BASE}/spaces/{HIDDEN}/folder/7001")
        self.assertEqual(page_address(f"{BASE}/spaces/{PERSONAL}/overview", "9"), f"{BASE}/pages/viewpage.action?pageId=9")

    def test_a_page_in_a_personal_space_shows_no_key_and_no_owner_address(self):
        page = replace(FakeGateway().pages["2002"], space_key=PERSONAL, url=f"{BASE}/spaces/{PERSONAL}/pages/2002/Release+notes")
        shown = hide_users(page)
        self.assertEqual(shown.space_key, HIDDEN)
        self.assertNotIn(ACCOUNT, shown.url)
        self.assertTrue(shown.url.endswith("pageId=2002"))

    def test_a_search_hit_in_a_personal_space_is_cleaned_the_same_way(self):
        hit = SearchHit("2002", "page", "Notes", PERSONAL, f"{BASE}/spaces/{PERSONAL}/pages/2002/Notes", "", "", "", (), 1)
        shown = hide_hit(hit)
        self.assertEqual(shown.space_key, HIDDEN)
        self.assertNotIn(ACCOUNT, shown.url)


if __name__ == "__main__":
    unittest.main()
