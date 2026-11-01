"""`ViewPage` and the containers of the tree: the id of a folder (or a whiteboard, a database, a smart link) given to `page` says what it is, and
a folder in the path of `--ancestors` has its title. Against the fake Confluence, which has the folder 7001 and its neighbours."""
import dataclasses
import unittest

from conflu_c_cli.application.pages import MissingPage, PageView
from conflu_c_cli.domain.drafts import PageChanges
from conflu_c_cli.domain.errors import NotFoundError
from tests.support.fakes import FakeGateway, RecordingDiagnostics, build_app, default_settings, sample_page


def app_for(gateway=None):
    gateway = gateway or FakeGateway()
    return build_app(gateway=gateway, settings=default_settings(), diagnostics=RecordingDiagnostics()), gateway


class BareAncestors(FakeGateway):
    """The answer of ancestors as the REST API gives it: a page is named, a folder and the like in the path are an id and a type only."""

    def list_ancestors(self, page_id):
        return [ref if ref.type == "page" else dataclasses.replace(ref, title="") for ref in super().list_ancestors(page_id)]


def below_folders(gateway):
    """A page below the folder 7011, which is below the folder 7001, and a page below that page."""
    gateway.pages["2090"] = sample_page("2090", "Below the runbooks", parent_id="7011")
    gateway.pages["2090"].parent_type = "folder"
    gateway.pages["2091"] = sample_page("2091", "Deeper", parent_id="2090")


class TheIdOfWhatIsNoPageTest(unittest.TestCase):
    def setUp(self):
        self.app, self.gateway = app_for()

    def test_a_folder_says_what_it_is_and_which_command_shows_it(self):
        with self.assertRaises(NotFoundError) as caught:
            self.app.view_page.execute("7001")
        error = caught.exception
        self.assertEqual((error.exit_code, error.code), (4, "NOT_FOUND"))
        self.assertEqual(error.message, "Not found: GET /api/v2/pages/7001")  # what Confluence said stays
        self.assertEqual(error.hint, "7001 is a folder, not a page: use `conflu folder 7001`.")
        self.assertEqual(self.gateway.called("get_page"), [("get_page", "7001", True)])
        self.assertEqual(self.gateway.called("content_types"), [("content_types", ("7001",))])  # one question, only after the page was not found
        self.assertIsInstance(error.__cause__, NotFoundError)

    def test_a_whiteboard_a_database_and_a_smart_link_say_what_they_are(self):
        for content_id, hint in (
            ("7021", "7021 is a whiteboard, not a page: use `conflu whiteboard 7021`."),
            ("7041", "7041 is a database, not a page: use `conflu database 7041`."),
            ("7061", "7061 is a smart link, not a page: use `conflu smartlink 7061`."),
        ):
            with self.subTest(id=content_id):
                with self.assertRaises(NotFoundError) as caught:
                    self.app.view_page.execute(content_id)
                self.assertEqual((caught.exception.hint, caught.exception.exit_code), (hint, 4))

    def test_a_blog_post_and_a_comment_are_named_too(self):
        self.gateway.content_kinds["4001"] = "footer-comment"
        with self.assertRaises(NotFoundError) as caught:
            self.app.view_page.execute("7101")
        self.assertEqual(caught.exception.hint, "7101 is a blog post, not a page: use `conflu blogpost 7101`.")
        with self.assertRaises(NotFoundError) as caught:
            self.app.view_page.execute("4001")
        self.assertEqual(caught.exception.hint, "4001 is a footer comment, not a page.")

    def test_an_id_that_is_nothing_keeps_the_error_as_it_was(self):
        with self.assertRaises(NotFoundError) as caught:
            self.app.view_page.execute("99999")
        self.assertEqual(caught.exception.message, "Not found: GET /api/v2/pages/99999")
        self.assertNotIn("not a page", caught.exception.hint)

    def test_a_failure_of_the_question_keeps_the_error_as_it_was(self):
        self.gateway.errors["content_types"] = NotFoundError("no")
        with self.assertRaises(NotFoundError) as caught:
            self.app.view_page.execute("7001")
        self.assertEqual(caught.exception.message, "Not found: GET /api/v2/pages/7001")
        self.assertNotIn("folder", caught.exception.hint)

    def test_it_holds_for_an_earlier_version_too(self):
        with self.assertRaises(NotFoundError) as caught:
            self.app.view_page.execute("7001", version=1)
        self.assertEqual(caught.exception.hint, "7001 is a folder, not a page: use `conflu folder 7001`.")
        self.assertEqual(self.gateway.called("get_page_version"), [])

    def test_among_several_pages_it_is_the_hint_of_the_entry(self):
        result = self.app.view_page.execute_many(["2002", "7001", "2003"])
        self.assertEqual([type(entry) for entry in result.entries], [PageView, MissingPage, PageView])
        missing = result.errors[0]
        self.assertEqual((missing.ref, missing.code, missing.exit_code), ("7001", "NOT_FOUND", 4))
        self.assertEqual(missing.hint, "7001 is a folder, not a page: use `conflu folder 7001`.")

    def test_versions_diff_and_restore_say_it_too(self):
        for name, call in (
            ("versions", lambda: self.app.list_versions.execute("7001")),
            ("diff", lambda: self.app.history.diff_versions.execute("7001")),
            ("restore", lambda: self.app.history.restore_version.execute("7001", 1)),
        ):
            with self.subTest(command=name):
                with self.assertRaises(NotFoundError) as caught:
                    call()
                self.assertEqual((caught.exception.hint, caught.exception.exit_code), ("7001 is a folder, not a page: use `conflu folder 7001`.", 4))
        self.assertEqual(self.gateway.called("restore_page_version"), [])

    def test_a_page_costs_the_requests_it_always_cost(self):
        self.app.view_page.execute("2002")
        self.assertEqual(self.gateway.calls, [("get_page", "2002", True)])
        self.gateway.calls.clear()
        self.app.view_page.execute("2004", with_ancestors=True, with_body=False)
        self.assertEqual(self.gateway.calls, [("get_page", "2004", False), ("list_ancestors", "2004")])
        self.gateway.calls.clear()
        self.app.view_page.execute("2002", version=2)
        self.assertEqual(self.gateway.calls, [("get_page", "2002", False), ("get_page_version", "2002", 2, True)])


class OtherCommandsOnWhatIsNoPageTest(unittest.TestCase):
    """`labels`, `label`, `comments`, `comment` and `update` name what an id is, as `page` does, instead of a bare "Not found"."""

    FOLDER = "7001 is a folder, not a page: use `conflu folder 7001`."
    BLOG_POST = "7101 is a blog post, not a page: use `conflu blogpost 7101`."

    def setUp(self):
        self.app, self.gateway = app_for()

    def commands(self):
        app = self.app
        return (
            ("labels", lambda ref: app.list_labels.execute(ref)),
            ("label", lambda ref: app.change_labels.execute(ref, add=["x"], remove=[])),
            ("label --dry-run", lambda ref: app.change_labels.execute(ref, add=["x"], remove=[], dry_run=True)),
            ("comments", lambda ref: app.comments.find.execute(ref)),
            ("comments --inline", lambda ref: app.comments.find.execute(ref, inline=True)),
            ("comments --resolution", lambda ref: app.comments.find.execute(ref, resolution="open")),
            ("comment", lambda ref: app.add_comment.execute(ref, "Hi")),
            ("comment --dry-run", lambda ref: app.add_comment.execute(ref, "Hi", dry_run=True)),
            ("update", lambda ref: app.update_page.execute(ref, PageChanges(title="T"))),
            ("update --dry-run", lambda ref: app.update_page.execute(ref, PageChanges(title="T"), dry_run=True)),
        )

    def test_a_folder_and_a_blog_post_say_what_they_are(self):
        before = {page_id: list(items) for page_id, items in self.gateway.comments.items()}
        for ref, hint in (("7001", self.FOLDER), ("7101", self.BLOG_POST)):
            for name, call in self.commands():
                with self.subTest(command=name, id=ref):
                    with self.assertRaises(NotFoundError) as caught:
                        call(ref)
                    self.assertEqual((caught.exception.hint, caught.exception.exit_code), (hint, 4))
        for name in ("add_labels", "remove_label", "update_page", "update_title"):
            self.assertEqual(self.gateway.called(name), [], name)  # the page is read first: nothing is attempted
        self.assertEqual(self.gateway.comments, before)  # a comment is attempted, and Confluence has no such page

    def test_what_confluence_said_stays_and_the_question_is_asked_after_the_failure_only(self):
        with self.assertRaises(NotFoundError) as caught:
            self.app.list_labels.execute("7001")
        self.assertEqual(caught.exception.message, "Not found: GET /api/v2/pages/7001")
        self.assertEqual([call[0] for call in self.gateway.calls], ["list_labels", "content_types"])

    def test_an_id_that_is_nothing_keeps_its_error(self):
        for name, call in self.commands():
            with self.subTest(command=name):
                with self.assertRaises(NotFoundError) as caught:
                    call("99999")
                self.assertNotIn("not a page", caught.exception.hint)

    def test_a_page_costs_no_question_at_all(self):
        self.app.list_labels.execute("2002")
        self.app.change_labels.execute("2002", add=["x"], remove=[], dry_run=True)
        self.app.comments.find.execute("2002", inline=True)
        self.app.add_comment.execute("2002", "Hi", dry_run=True)
        self.app.update_page.execute("2002", PageChanges(title="T"), dry_run=True)
        self.assertEqual(self.gateway.called("content_types"), [])

    def test_a_reply_to_a_comment_that_is_not_there_is_about_the_comment_and_not_about_the_page(self):
        with self.assertRaises(NotFoundError) as caught:
            self.app.add_comment.execute("2002", "Hi", reply_to="99999", dry_run=True)
        self.assertIn("No comment 99999 on page 2002", caught.exception.message)
        self.assertEqual(self.gateway.called("content_types"), [])


class AFolderInThePathTest(unittest.TestCase):
    def setUp(self):
        self.app, self.gateway = app_for(BareAncestors())
        below_folders(self.gateway)

    def path(self, page_id):
        view = self.app.view_page.execute(page_id, with_ancestors=True, with_body=False)
        return [(ref.id, ref.title, ref.type) for ref in view.page.ancestors]

    def test_a_folder_has_its_title_in_the_path(self):
        self.assertEqual(self.path("2090"), [("7001", "Guides", "folder"), ("7011", "Runbooks", "folder")])
        self.assertEqual(self.gateway.called("get_container"), [("get_container", "folder", "7001"), ("get_container", "folder", "7011")])

    def test_pages_and_folders_in_one_path_are_all_named(self):
        self.assertEqual(self.path("2091"), [("7001", "Guides", "folder"), ("7011", "Runbooks", "folder"), ("2090", "Below the runbooks", "page")])
        self.assertEqual(self.gateway.called("list_pages"), [])  # the title of a page is in the answer already

    def test_a_folder_that_cannot_be_read_stays_without_a_title(self):
        original = self.gateway.get_container

        def refuse(kind, container_id):
            if container_id == "7001":
                raise NotFoundError("not for this account")
            return original(kind, container_id)

        self.gateway.get_container = refuse
        self.assertEqual(self.path("2090"), [("7001", "", "folder"), ("7011", "Runbooks", "folder")])

    def test_the_titles_are_redacted_as_every_title_is(self):
        self.gateway.containers["7011"] = dataclasses.replace(self.gateway.containers["7011"], title="Notes of alex@example.com")
        view = self.app.view_page.execute("2090", with_ancestors=True, with_body=False)
        self.assertEqual([ref.title for ref in view.page.ancestors], ["Guides", "Notes of [email]"])

    def test_without_the_option_nothing_is_asked(self):
        self.app.view_page.execute("2090", with_body=False)
        self.assertEqual([call[0] for call in self.gateway.calls], ["get_page"])

    def test_a_path_whose_titles_are_all_there_costs_nothing_more(self):
        app, gateway = app_for()
        below_folders(gateway)
        view = app.view_page.execute("2090", with_ancestors=True, with_body=False)
        self.assertEqual([ref.title for ref in view.page.ancestors], ["Guides", "Runbooks"])
        self.assertEqual([call[0] for call in gateway.calls], ["get_page", "list_ancestors"])

    def test_several_pages_name_the_folders_of_each_path(self):
        result = self.app.view_page.execute_many(["2090", "2002"], with_ancestors=True, with_body=False)
        self.assertEqual([[ref.title for ref in view.page.ancestors] for view in result.pages], [["Guides", "Runbooks"], ["Engineering Home"]])


if __name__ == "__main__":
    unittest.main()
