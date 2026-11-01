"""What the answers of the REST API v2 for blog posts mean: one answer in, domain objects out. The mapping of a blog post is the one of a page, and what is different is here."""
import unittest

from conflu_c_cli.adapters.driven import map_blogposts as mapping
from conflu_c_cli.domain.model import Label, User, VersionInfo

ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"
WIKI = "https://example.atlassian.net/wiki"


def answer(**changes):
    data = {
        "id": "7101",
        "status": "current",
        "title": "Release 2026.10 is out",
        "spaceId": "1001",
        "authorId": ACCOUNT,
        "createdAt": "2026-10-12T09:00:00.000Z",
        "version": {"number": 3, "createdAt": "2026-10-14T09:00:00.000Z", "message": "Added the known issues", "minorEdit": True, "authorId": ACCOUNT},
        "body": {"storage": {"representation": "storage", "value": "<p>Hi</p>"}},
        "labels": {"results": [{"id": "1", "name": "release", "prefix": "global"}, {"id": "2", "name": "news", "prefix": "team"}]},
        "_links": {"webui": "/spaces/ENG/blog/2026/10/12/7101/Release+2026.10+is+out", "base": WIKI},
    }
    data.update(changes)
    return data


class BlogpostAnswerTest(unittest.TestCase):
    def test_a_blog_post_is_a_page_without_a_parent(self):
        post = mapping.blogpost_from(answer())
        self.assertEqual((post.id, post.title, post.status, post.space_id, post.space_key), ("7101", "Release 2026.10 is out", "current", "1001", "ENG"))
        self.assertEqual((post.parent_id, post.parent_type, post.position, post.owner), ("", "", None, None))
        self.assertEqual(post.url, f"{WIKI}/spaces/ENG/blog/2026/10/12/7101/Release+2026.10+is+out")
        self.assertEqual((post.created, post.updated, post.version_number), ("2026-10-12T09:00:00.000Z", "2026-10-14T09:00:00.000Z", 3))
        self.assertEqual(post.version, VersionInfo(3, "2026-10-14T09:00:00.000Z", "Added the known issues", True, User(ACCOUNT)))
        self.assertEqual(post.author, User(ACCOUNT))
        self.assertEqual(post.body, "<p>Hi</p>")
        self.assertEqual(post.labels, [Label("release", "global"), Label("news", "team")])
        self.assertEqual(post.raw["id"], "7101")

    def test_the_address_of_the_site_that_was_configured_stands_in_when_the_answer_has_none(self):
        data = answer()
        del data["_links"]["base"]
        self.assertEqual(mapping.blogpost_from(data, WIKI).url, f"{WIKI}/spaces/ENG/blog/2026/10/12/7101/Release+2026.10+is+out")
        self.assertEqual(mapping.blogpost_from(data).url, "/spaces/ENG/blog/2026/10/12/7101/Release+2026.10+is+out")
        self.assertEqual(mapping.blogpost_from(answer(_links={"base": WIKI}), "").url, "")  # no address to show: none is made up

    def test_what_the_answer_leaves_out_is_empty_and_not_an_error(self):
        post = mapping.blogpost_from({})
        self.assertEqual((post.id, post.title, post.status, post.space_key, post.url), ("", "", "", "", ""))
        self.assertEqual((post.version, post.author, post.body, post.labels), (None, None, None, []))
        self.assertEqual(post.version_number, 0)

    def test_an_answer_without_a_body_has_none_and_an_empty_body_is_empty(self):
        self.assertIsNone(mapping.blogpost_from(answer(body={})).body)
        self.assertIsNone(mapping.blogpost_from({k: v for k, v in answer().items() if k != "body"}).body)
        self.assertEqual(mapping.blogpost_from(answer(body={"storage": {"value": ""}})).body, "")

    def test_values_of_the_wrong_type_do_not_break_it(self):
        post = mapping.blogpost_from(answer(id=7101, title=None, version="three", labels={"results": ["x", None]}, body="text", _links=None))
        self.assertEqual((post.id, post.title, post.version, post.body, post.labels, post.url), ("7101", "", None, None, [], ""))

    def test_the_space_key_is_read_from_the_address_of_the_blog_post(self):
        self.assertEqual(mapping.blogpost_from(answer(_links={"webui": "/spaces/~5b10ac8d82e05b22cc7d4ef5/blog/2026/10/12/7101/x"})).space_key, "~5b10ac8d82e05b22cc7d4ef5")
        self.assertEqual(mapping.blogpost_from(answer(_links={"webui": "/blog/2026/10/12/7101/x"})).space_key, "")


if __name__ == "__main__":
    unittest.main()
