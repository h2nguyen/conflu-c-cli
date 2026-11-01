"""What the answers of the REST API for an earlier version of a page, and for the restore of one, mean."""
import unittest

from conflu_c_cli.adapters.driven import map_history as mapping
from conflu_c_cli.domain.model import User, VersionInfo

ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"
WIKI = "https://example.atlassian.net/wiki"


class PageVersionAnswerTest(unittest.TestCase):
    def test_an_earlier_version_has_the_title_the_body_and_the_version_of_its_time(self):
        page = mapping.page_version_from(
            {
                "id": "2002",
                "status": "current",
                "title": "Release notes (draft)",
                "spaceId": "1001",
                "parentId": "2001",
                "parentType": "page",
                "authorId": ACCOUNT,
                "createdAt": "2026-10-01T08:00:00.000Z",
                "version": {"number": 1, "createdAt": "2026-10-01T08:00:00.000Z", "message": "Created", "minorEdit": False, "authorId": ACCOUNT},
                "body": {"storage": {"representation": "storage", "value": "<h1>Release notes</h1><p>Draft.</p>"}},
                "_links": {"webui": "/spaces/ENG/pages/2002/Release+notes", "base": WIKI},
            }
        )
        self.assertEqual((page.id, page.title, page.status, page.space_key, page.parent_id), ("2002", "Release notes (draft)", "current", "ENG", "2001"))
        self.assertEqual(page.version, VersionInfo(1, "2026-10-01T08:00:00.000Z", "Created", False, User(ACCOUNT)))
        self.assertEqual((page.version_number, page.updated), (1, "2026-10-01T08:00:00.000Z"))
        self.assertEqual(page.body, "<h1>Release notes</h1><p>Draft.</p>")
        self.assertEqual(page.labels, [])  # a version has none: the page's own are read apart
        self.assertEqual(page.url, f"{WIKI}/spaces/ENG/pages/2002/Release+notes")

    def test_without_a_body_there_is_none_and_the_fallback_address_stands_in(self):
        page = mapping.page_version_from({"id": "2002", "version": {"number": 2}, "_links": {"webui": "/spaces/ENG/pages/2002/x"}}, WIKI)
        self.assertEqual((page.body, page.version_number, page.url), (None, 2, f"{WIKI}/spaces/ENG/pages/2002/x"))

    def test_an_empty_answer_is_an_empty_page(self):
        page = mapping.page_version_from({})
        self.assertEqual((page.id, page.title, page.version, page.body), ("", "", None, None))


class RestoredNumberTest(unittest.TestCase):
    def test_the_answer_of_the_older_api_names_the_version_that_was_made(self):
        self.assertEqual(mapping.restored_number({"number": 4, "message": "Restored version 1", "minorEdit": False, "content": {"id": "2002"}}), 4)

    def test_an_answer_that_does_not_say_is_zero(self):
        for data in (None, {}, [], "4", 4, {"number": None}, {"number": "4"}, {"number": 4.0}, {"number": True}, {"number": 0}, {"number": -3}, {"number": [4]}):
            with self.subTest(data=data):
                self.assertEqual(mapping.restored_number(data), 0)


if __name__ == "__main__":
    unittest.main()
