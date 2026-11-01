"""Use cases around folders and the rest of the tree, with the in-memory Confluence: where a page may be created, what a tree starts at, how a page is moved, what is read."""
import json
import unittest

from conflu_c_cli.application.containers import PARENT, ROOT, ContainerResolver, not_a_page, with_titles
from conflu_c_cli.application.refs import resolve_page_ref
from conflu_c_cli.domain.drafts import PageDraft
from conflu_c_cli.domain.errors import ConfluCliError, ConflictError, NotFoundError, UnavailableError, UsageError, ValidationError
from conflu_c_cli.domain.model import PageRef, Space
from conflu_c_cli.domain.privacy import HIDDEN
from tests.support.fakes import ACCOUNT, BASE, FakeGateway, MemoryFiles, build_app, default_settings, sample_page


def app_with(gateway=None, files=None, **settings):
    return build_app(gateway=gateway or FakeGateway(), files=files, settings=default_settings(**settings))


class ResolverTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.resolver = ContainerResolver(self.gateway)

    def test_a_page_is_asked_for_first_and_nothing_else_is(self):
        found = self.resolver.resolve("2003", PARENT)
        self.assertEqual((found.id, found.type, found.title, found.space_id, found.parent_id), ("2003", "page", "Architecture", "1001", "2001"))
        self.assertEqual(self.gateway.calls, [("get_page", "2003", False)])
        self.assertEqual(found.ref(), PageRef("2003", "Architecture", "page", "current"))

    def test_what_is_no_page_is_looked_up_by_its_type(self):
        found = self.resolver.resolve("7001", PARENT)
        self.assertEqual((found.id, found.type, found.title, found.space_id, found.parent_id), ("7001", "folder", "Guides", "1001", ""))
        self.assertEqual([call[0] for call in self.gateway.calls], ["get_page", "content_types", "get_container"])
        self.assertEqual(self.gateway.calls[-1], ("get_container", "folder", "7001"))
        self.assertEqual(self.resolver.resolve("7041", PARENT).type, "database")
        self.assertEqual(self.resolver.resolve("7061", PARENT).container.embed_url, "https://example.com/roadmap")

    def test_an_address_of_any_kind_is_understood(self):
        self.assertEqual(self.resolver.resolve(f"{BASE}/spaces/ENG/folder/7001", PARENT).id, "7001")
        self.assertEqual(self.resolver.resolve(f"{BASE}/spaces/ENG/pages/2003/Architecture", PARENT).id, "2003")

    def test_what_was_found_is_looked_up_once_when_the_resolver_remembers(self):
        remembering = ContainerResolver(self.gateway, remember=True)
        remembering.resolve("7001", PARENT)
        remembering.resolve("7001", PARENT)
        remembering.resolve(f"{BASE}/spaces/ENG/folder/7001", PARENT)
        self.assertEqual(len(self.gateway.called("content_types")), 1)

    def test_by_default_every_call_asks_again(self):
        self.resolver.resolve("7001", PARENT)
        self.gateway.containers["7001"].title = "Renamed meanwhile"
        self.assertEqual(self.resolver.resolve("7001", PARENT).title, "Renamed meanwhile")
        self.assertEqual(len(self.gateway.called("content_types")), 2)

    def test_a_blog_post_a_comment_and_an_attachment_are_named_for_what_they_are(self):
        self.gateway.content_kinds.update({"7101": "blogpost", "4001": "footer-comment", "5001": "attachment", "4002": "inline-comment"})
        for content_id, what in (("7101", "a blog post"), ("4001", "a footer comment"), ("5001", "an attachment"), ("4002", "an inline comment")):
            with self.subTest(id=content_id), self.assertRaises(ValidationError) as caught:
                self.resolver.resolve(content_id, PARENT)
            self.assertEqual(caught.exception.message, f"{content_id} is {what}, which cannot be a parent.")
            self.assertIn("a page, a folder, a whiteboard, a database or a smart link", caught.exception.hint)
            self.assertEqual(caught.exception.details, {"id": content_id, "type": self.gateway.content_kinds[content_id]})
        with self.assertRaises(ValidationError) as caught:
            self.resolver.resolve("7101", ROOT)
        self.assertIn("cannot be the start of a tree", caught.exception.message)

    def test_an_unknown_id_is_not_found_with_a_hint_and_the_id(self):
        with self.assertRaises(NotFoundError) as caught:
            self.resolver.resolve("99999", PARENT)
        self.assertEqual(caught.exception.message, "No page, folder, whiteboard, database or smart link with the id 99999 that this account can see.")
        self.assertIn("conflu tree", caught.exception.hint)
        self.assertEqual(caught.exception.details, {"id": "99999"})

    def test_a_page_that_the_first_answer_missed_keeps_the_first_error(self):
        self.gateway.errors["get_page"] = NotFoundError("Not found: GET /api/v2/pages/2003", hint="the first answer")
        with self.assertRaises(NotFoundError) as caught:
            self.resolver.resolve("2003", PARENT)
        self.assertEqual(caught.exception.hint, "the first answer")

    def test_other_errors_pass_through_and_nothing_is_remembered_for_them(self):
        self.gateway.errors["get_page"] = ConfluCliError("down")
        with self.assertRaises(ConfluCliError):
            self.resolver.resolve("2003", PARENT)
        self.assertEqual([call[0] for call in self.gateway.calls], ["get_page"])

    def test_an_id_that_is_none_costs_no_request(self):
        for text in ("../x", "abc", "", "1" * 25, "12\x00"):
            with self.subTest(text=text), self.assertRaises(ValidationError):
                self.resolver.resolve(text, PARENT)
        self.assertEqual(self.gateway.calls, [])

    def test_the_key_of_the_space(self):
        self.assertEqual(self.resolver.space_key(self.resolver.resolve("2003", PARENT)), "ENG")
        self.assertEqual(self.resolver.space_key(self.resolver.resolve("7001", PARENT)), "ENG")
        self.assertEqual(self.gateway.called("get_space_by_id"), [])  # the container knows it

    def test_the_key_is_asked_for_when_the_answer_does_not_name_it(self):
        folder = self.resolver.resolve("7011", PARENT)
        self.gateway.containers["7011"].space_key = ""
        found = ContainerResolver(self.gateway).resolve("7011", PARENT)
        self.assertEqual(folder.space_id, "1001")
        self.assertEqual(ContainerResolver(self.gateway).space_key(found), "ENG")
        self.assertEqual(self.gateway.called("get_space_by_id"), [("get_space_by_id", "1001")])


class WrongKindTest(unittest.TestCase):
    def test_a_page_that_is_none_says_what_the_id_is_and_which_command_shows_it(self):
        gateway = FakeGateway()
        gateway.content_kinds["7101"] = "blogpost"
        gateway.content_kinds["4001"] = "footer-comment"
        error = NotFoundError("Not found: GET /api/v2/pages/7001", hint="old", details={"status": 404})
        for content_id, hint in (
            ("7001", "7001 is a folder, not a page: use `conflu folder 7001`."),
            ("7021", "7021 is a whiteboard, not a page: use `conflu whiteboard 7021`."),
            ("7041", "7041 is a database, not a page: use `conflu database 7041`."),
            ("7061", "7061 is a smart link, not a page: use `conflu smartlink 7061`."),
            ("7101", "7101 is a blog post, not a page: use `conflu blogpost 7101`."),
            ("4001", "4001 is a footer comment, not a page."),
        ):
            with self.subTest(id=content_id):
                better = not_a_page(gateway, content_id, error)
                self.assertIsInstance(better, NotFoundError)
                self.assertEqual((better.message, better.hint, better.exit_code), (error.message, hint, 4))
                self.assertEqual(better.details["status"], 404)

    def test_an_id_that_is_unknown_or_a_page_keeps_its_error_and_a_failure_of_the_question_does_too(self):
        gateway = FakeGateway()
        error = NotFoundError("Not found", hint="old")
        self.assertIs(not_a_page(gateway, "99999", error), error)
        self.assertIs(not_a_page(gateway, "2003", error), error)
        gateway.errors["content_types"] = ConfluCliError("down")
        self.assertIs(not_a_page(gateway, "7001", error), error)


class TitlesTest(unittest.TestCase):
    def test_the_titles_that_an_answer_of_ancestors_leaves_out_are_asked_for(self):
        gateway = FakeGateway()
        gateway.add_container("folder", "7090", "Below a page", parent_id="2003")
        refs = [PageRef("2001", "", "page"), PageRef("2003", "", "page"), PageRef("7090", "", "folder")]
        found = with_titles(gateway, refs)
        self.assertEqual([(ref.id, ref.title, ref.type) for ref in found], [("2001", "Engineering Home", "page"), ("2003", "Architecture", "page"), ("7090", "Below a page", "folder")])
        self.assertEqual(len(gateway.called("list_pages")), 1)  # the pages in one request
        self.assertEqual(gateway.called("get_container"), [("get_container", "folder", "7090")])

    def test_what_has_a_title_costs_nothing_and_what_cannot_be_seen_stays_bare(self):
        gateway = FakeGateway()
        with_title = [PageRef("2001", "Engineering Home", "page")]
        self.assertEqual(with_titles(gateway, with_title), with_title)
        self.assertEqual(gateway.calls, [])
        bare = with_titles(gateway, [PageRef("9999", "", "folder"), PageRef("9998", "", "page")])
        self.assertEqual([ref.title for ref in bare], ["", ""])
        self.assertEqual(with_titles(gateway, []), [])


class CreatePageBelowTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.app = app_with(self.gateway)

    def draft(self, **values):
        return PageDraft(**{"space": "ENG", "title": "Getting started", "body": "<p>Hi</p>", **values})

    def test_a_folder_is_a_parent_and_the_payload_is_what_the_post_takes(self):
        result = self.app.create_page.execute(self.draft(parent="7001"), dry_run=True)
        self.assertEqual(result.payload, {"spaceId": "1001", "status": "current", "title": "Getting started", "parentId": "7001", "body": {"representation": "storage", "value": "<p>Hi</p>"}})
        self.assertEqual(result.where, PageRef("7001", "Guides", "folder", "current"))
        self.assertEqual(self.gateway.called("create_page"), [])

    def test_the_real_run_sends_that_payload_and_the_page_sits_below_the_folder(self):
        preview = self.app.create_page.execute(self.draft(parent="7001"), dry_run=True)
        result = self.app.create_page.execute(self.draft(parent="7001"))
        self.assertEqual(self.gateway.called("create_page")[0][1], preview.payload)
        self.assertEqual((result.page.parent_id, result.page.parent_type), ("7001", "folder"))
        self.assertEqual(result.where, preview.where)
        self.assertEqual(self.app.view_page.execute(result.page.id, with_body=False).page.parent_type, "folder")

    def test_every_container_may_be_the_parent(self):
        for parent, kind in (("7011", "folder"), ("7021", "whiteboard"), ("7041", "database"), ("7061", "embed"), ("2003", "page")):
            with self.subTest(parent=parent):
                result = self.app.create_page.execute(self.draft(parent=parent, title=f"Below {parent}"))
                self.assertEqual((result.where.type, result.page.parent_type), (kind, kind))

    def test_a_page_as_the_parent_is_asked_for_as_it_always_was(self):
        self.app.create_page.execute(self.draft(parent="2003"), dry_run=True)
        self.assertEqual([call[0] for call in self.gateway.calls], ["get_space", "get_page", "list_pages"])

    def test_without_a_parent_nothing_is_said_about_one(self):
        result = self.app.create_page.execute(self.draft(), dry_run=True)
        self.assertIsNone(result.where)
        self.assertNotIn("parentId", result.payload)

    def test_a_blog_post_an_unknown_id_and_a_parent_of_another_space(self):
        self.gateway.content_kinds["7101"] = "blogpost"
        with self.assertRaises(ValidationError) as caught:
            self.app.create_page.execute(self.draft(parent="7101"))
        self.assertIn("7101 is a blog post", caught.exception.message)
        with self.assertRaises(NotFoundError):
            self.app.create_page.execute(self.draft(parent="99999"))
        self.gateway.add_container("folder", "7099", "Elsewhere", space_key="DOCS")
        with self.assertRaises(ValidationError) as caught:
            self.app.create_page.execute(self.draft(parent="7099"))
        self.assertEqual(caught.exception.message, "The parent folder 7099 is not in space ENG.")
        self.assertEqual(caught.exception.hint, "A page is created in the space of its parent: pass that space, or another parent.")
        self.assertEqual(self.gateway.called("create_page"), [])

    def test_the_title_of_the_parent_is_redacted(self):
        self.gateway.add_container("folder", "7090", "Mail alex@example.com")
        self.assertEqual(self.app.create_page.execute(self.draft(parent="7090"), dry_run=True).where.title, "Mail [email]")

    def test_the_title_check_still_covers_a_folder_parent(self):
        self.gateway.add_page_below("7001", "7101", "Getting started")
        with self.assertRaises(ConflictError):  # a page title is unique in its space, whatever the parent
            self.app.create_page.execute(self.draft(parent="7001"))


class ImportBelowTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()

    def test_import_md_names_a_folder_from_the_option_and_from_the_front_matter(self):
        files = MemoryFiles({"a.md": "# From the option\n\nText.\n", "b.md": "---\ntitle: From the file\nparent: 7011\n---\nText.\n"})
        app = app_with(self.gateway, files)
        first = app.import_markdown.execute("a.md", space="ENG", parent="7001", dry_run=True)
        self.assertEqual((first.action, first.parent, first.payload["parentId"]), ("created", PageRef("7001", "Guides", "folder", "current"), "7001"))
        second = app.import_markdown.execute("b.md", space="ENG", parent="7001")  # the front matter wins
        self.assertEqual((second.parent.id, second.parent.type), ("7011", "folder"))
        self.assertEqual(self.gateway.pages[second.page_id].parent_id, "7011")

    def test_the_front_matter_may_hold_the_address_of_a_folder(self):
        files = MemoryFiles({"a.md": f"---\ntitle: By address\nparent: {BASE}/spaces/ENG/folder/7001\n---\nText.\n"})
        outcome = app_with(self.gateway, files).import_markdown.execute("a.md", space="ENG", dry_run=True)
        self.assertEqual(outcome.parent.id, "7001")

    def test_a_page_that_is_updated_names_no_parent(self):
        files = MemoryFiles({"a.md": "---\ntitle: Plain page\n---\nChanged text.\n"})
        outcome = app_with(self.gateway, files).import_markdown.execute("a.md", space="ENG", parent="7001", dry_run=True)
        self.assertEqual((outcome.action, outcome.parent), ("updated", None))

    def test_a_folder_of_files_looks_the_parent_up_once(self):
        files = MemoryFiles({f"md/{name}.md": f"# Page {name}\n\nText.\n" for name in "abc"})
        batch = app_with(self.gateway, files).import_markdown_directory.execute("md", space="ENG", parent="7001")
        self.assertEqual([outcome.action for outcome in batch.outcomes], ["created"] * 3)
        self.assertEqual({outcome.parent.id for outcome in batch.outcomes}, {"7001"})
        self.assertEqual(len(self.gateway.called("content_types")), 1)
        self.assertEqual(len(self.gateway.called("get_container")), 1)

    def test_an_empty_space_or_parent_is_a_mistake_for_a_file_as_for_a_folder_of_files_and_is_refused_before_a_file_is_read(self):
        files = MemoryFiles({"a.md": "# From a file\n\nText.\n", "md/a.md": "# Page a\n\nText.\n", "md/b.md": "# Page b\n\nText.\n"})
        app = app_with(self.gateway, files, space="DOCS")
        for options, message in (({"space": ""}, "The space is empty."), ({"space": "  "}, "The space is empty."), ({"parent": ""}, "The parent is empty.")):
            for dry_run in (True, False):
                with self.subTest(options=options, dry_run=dry_run):
                    with self.assertRaises(UsageError) as caught:
                        app.import_markdown.execute("a.md", dry_run=dry_run, **options)
                    self.assertEqual(caught.exception.message, message)
                    with self.assertRaises(UsageError) as caught:
                        app.import_markdown_directory.execute("md", dry_run=dry_run, continue_on_error=True, **options)  # not one failed file after the other
                    self.assertEqual(caught.exception.message, message)
        self.assertEqual(self.gateway.calls, [])
        named = app.import_markdown.execute("a.md", space=None, parent=None, dry_run=True)  # none named: the current space, the home page of it
        self.assertEqual((named.action, named.payload["spaceId"]), ("created", "1002"))

    def test_a_file_that_would_be_updated_does_not_make_an_empty_option_acceptable(self):
        files = MemoryFiles({"a.md": "---\ntitle: Plain page\n---\nChanged text.\n"})
        with self.assertRaises(UsageError):
            app_with(self.gateway, files).import_markdown.execute("a.md", space="ENG", parent="", dry_run=True)
        self.assertEqual(self.gateway.calls, [])

    def test_a_parent_that_cannot_be_one_stops_the_batch_with_its_error(self):
        self.gateway.content_kinds["7101"] = "blogpost"
        files = MemoryFiles({"md/a.md": "# Page a\n\nText.\n", "md/b.md": "# Page b\n\nText.\n"})
        batch = app_with(self.gateway, files).import_markdown_directory.execute("md", space="ENG", parent="7101", continue_on_error=True)
        self.assertEqual([outcome.action for outcome in batch.outcomes], ["failed", "failed"])
        self.assertIsInstance(batch.first_error, ValidationError)
        self.assertIn("7101 is a blog post", batch.outcomes[0].message)


class TreeFromTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.gateway.add_page_below("7001", "7101", "Getting started")
        self.gateway.add_page_below("7101", "7102", "Deeper")
        self.app = app_with(self.gateway)

    def test_a_tree_starts_at_a_folder(self):
        result = self.app.tree_pages.execute("7001", depth=3)
        self.assertEqual(result.root, PageRef("7001", "Guides", "folder", "current"))
        self.assertEqual(result.space_key, "ENG")
        self.assertEqual([(node.id, node.type, node.depth) for node in result.nodes], [("7021", "whiteboard", 1), ("7101", "page", 1), ("7102", "page", 2), ("7061", "embed", 1), ("7011", "folder", 1), ("7041", "database", 1)])
        self.assertEqual(result.depth, 3)

    def test_the_depth_limits_the_levels(self):
        self.assertNotIn("7102", [node.id for node in self.app.tree_pages.execute("7001", depth=1).nodes])

    def test_a_tree_from_a_page_asks_what_it_always_asked(self):
        result = self.app.tree_pages.execute("2001", depth=3)
        self.assertEqual(result.root.type, "page")
        self.assertEqual([call[0] for call in self.gateway.calls], ["get_page", "list_descendants", "list_descendants"])  # the fake hands out two at a time

    def test_a_page_below_a_folder_has_a_tree_of_its_own(self):
        self.assertEqual([node.id for node in self.app.tree_pages.execute("7101").nodes], ["7102"])

    def test_the_other_roots_and_the_title_reference(self):
        self.assertEqual(self.app.tree_pages.execute("7041").root.type, "database")
        self.assertEqual(self.app.tree_pages.execute("page:Architecture", depth=1, space="ENG").root.title, "Architecture")
        self.assertEqual(self.app.tree_pages.execute(f"{BASE}/spaces/ENG/folder/7011").root.title, "Runbooks")

    def test_what_cannot_start_a_tree(self):
        self.gateway.content_kinds["7201"] = "blogpost"
        with self.assertRaises(ValidationError) as caught:
            self.app.tree_pages.execute("7201")
        self.assertIn("7201 is a blog post, which cannot be the start of a tree", caught.exception.message)
        with self.assertRaises(NotFoundError):
            self.app.tree_pages.execute("99999")
        with self.assertRaises(ValidationError):
            self.app.tree_pages.execute("../x")

    def test_a_depth_that_is_none_is_refused_before_anything_is_read(self):
        self.gateway.calls.clear()
        for depth in (0, 11, -1):
            with self.assertRaises(UsageError):
                self.app.tree_pages.execute("7001", depth=depth)
        self.assertEqual(self.gateway.calls, [])

    def test_the_titles_are_redacted(self):
        self.gateway.add_container("folder", "7090", "Mail alex@example.com", parent_id="7001")
        result = self.app.tree_pages.execute("7001")
        self.assertIn("Mail [email]", [node.title for node in result.nodes])
        self.gateway.containers["7001"].title = "Root alex@example.com"
        self.assertEqual(self.app.tree_pages.execute("7001").root.title, "Root [email]")

    def test_a_space_that_is_empty_is_a_mistake_for_a_title_reference_and_for_an_id_alike(self):
        self.gateway.calls.clear()
        for root in ("page:Architecture", "2001", "7001"):
            for blank in ("", "  "):
                with self.subTest(root=root, space=blank):
                    with self.assertRaises(UsageError) as caught:
                        self.app.tree_pages.execute(root, space=blank)
                    self.assertEqual(caught.exception.message, "The space is empty.")
        self.assertEqual(self.gateway.calls, [])
        self.assertEqual(app_with(self.gateway, space="ENG").tree_pages.execute("page:Architecture", depth=1, space=None).root.title, "Architecture")  # none: the current space


class MoveBelowTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.app = app_with(self.gateway)

    def test_a_move_below_a_folder_is_the_page_saved_again_with_the_next_version(self):
        result = self.app.move_page.execute("2002", "7001")
        self.assertEqual((result.action, result.dry_run, result.version_from, result.version_to), ("moved", False, 3, 4))
        sent = self.gateway.called("update_page")[0]
        self.assertEqual(sent[1], "2002")
        payload = sent[2]
        self.assertEqual(payload["id"], "2002")
        self.assertEqual((payload["parentId"], payload["status"], payload["title"]), ("7001", "current", "Release notes"))
        self.assertEqual(payload["version"], {"number": 4, "message": "Moved below Guides"})
        self.assertEqual(payload["body"], {"representation": "storage", "value": self.gateway.pages["2002"].body})  # what is sent is the page as it is
        self.assertTrue(result.redacted)  # and what is printed is not: the page holds a mention and an address
        self.assertEqual(result.payload["parentId"], "7001")
        self.assertNotIn("alex@example.com", json.dumps(result.payload))
        self.assertNotIn(ACCOUNT, json.dumps(result.payload))
        self.assertEqual(result.where, PageRef("7001", "Guides", "folder", "current"))
        page = self.gateway.pages["2002"]
        self.assertEqual((page.parent_id, page.parent_type, page.version_number), ("7001", "folder", 4))
        self.assertEqual(self.gateway.called("move_page"), [])  # not the v1 call

    def test_the_body_goes_back_as_it_was_mentions_and_macros_included(self):
        before = self.gateway.pages["2002"].body
        self.app.move_page.execute("2002", "7001")
        self.assertEqual(self.gateway.pages["2002"].body, before)
        self.assertIn("ri:account-id", self.gateway.called("update_page")[0][2]["body"]["value"])

    def test_a_dry_run_reads_and_changes_nothing(self):
        result = self.app.move_page.execute("2005", "7001", dry_run=True)
        self.assertEqual((result.action, result.dry_run, result.version_from, result.version_to, result.payload["parentId"]), ("moved", True, 1, 2, "7001"))
        self.assertEqual(self.gateway.called("update_page"), [])
        self.assertEqual(self.gateway.pages["2005"].parent_id, "2001")
        self.assertFalse(result.redacted)  # nothing in this page to hide
        self.app.move_page.execute("2005", "7001")
        self.assertEqual(self.gateway.called("update_page")[0][2], result.payload)  # the request is the one that the dry run showed

    def test_the_people_in_the_body_are_hidden_in_what_is_shown_and_never_in_what_is_sent(self):
        shown = self.app.move_page.execute("2002", "7001", dry_run=True)
        self.assertTrue(shown.redacted)
        value = shown.payload["body"]["value"]
        self.assertIn('ri:account-id="hidden"', value)
        self.assertIn("[email]", value)
        self.assertNotIn("alex@example.com", value)
        exact = self.app.move_page.execute("2002", "7001", dry_run=True, with_users=True)
        self.assertFalse(exact.redacted)
        self.assertIn(ACCOUNT, exact.payload["body"]["value"])
        self.app.move_page.execute("2002", "7001")
        sent = self.gateway.called("update_page")[0][2]
        self.assertIn(ACCOUNT, sent["body"]["value"])  # a body that is saved is the page as it is
        self.assertIn("alex@example.com", sent["body"]["value"])
        self.assertNotIn("hidden", sent["body"]["value"])

    def test_a_title_with_an_address_is_redacted_in_what_is_shown(self):
        self.gateway.pages["2005"].title = "Plain alex@example.com"
        shown = self.app.move_page.execute("2005", "7001", dry_run=True)
        self.assertEqual((shown.payload["title"], shown.redacted), ("Plain [email]", True))
        self.assertEqual(self.app.move_page.execute("2005", "7001").payload["title"], "Plain [email]")
        self.assertEqual(self.gateway.called("update_page")[0][2]["title"], "Plain alex@example.com")

    def test_a_page_below_the_parent_already_is_left_alone(self):
        self.app.move_page.execute("2005", "7001")
        again = self.app.move_page.execute("2005", "7001")
        self.assertEqual((again.action, again.payload, again.version_from, again.version_to), ("unchanged", None, 2, 2))
        self.assertEqual(len(self.gateway.called("update_page")), 1)
        dry = self.app.move_page.execute("2005", "7001", dry_run=True)
        self.assertEqual(dry.action, "unchanged")

    def test_a_move_to_a_page_is_what_it_was(self):
        result = self.app.move_page.execute("2005", "2003", position="before")
        self.assertEqual(result.payload, {"pageId": "2005", "position": "before", "targetId": "2003"})
        self.assertEqual([call[0] for call in self.gateway.calls], ["get_page", "get_page", "move_page", "get_page"])
        self.assertEqual(self.gateway.calls[0], ("get_page", "2005", False))
        self.assertEqual(self.gateway.calls[1], ("get_page", "2003", False))
        self.assertEqual(self.gateway.called("update_page"), [])
        self.assertEqual(result.where.type, "page")

    def test_a_folder_only_takes_append(self):
        for position in ("before", "after"):
            with self.assertRaises(UsageError) as caught:
                self.app.move_page.execute("2005", "7001", position=position)
            self.assertIn("A folder can only be a parent", caught.exception.message)
        with self.assertRaises(UsageError) as caught:
            self.app.move_page.execute("2005", "7061", position="before")
        self.assertIn("A smart link can only be a parent", caught.exception.message)
        self.assertEqual(self.gateway.called("update_page"), [])

    def test_what_cannot_be_moved_and_what_cannot_be_moved_to(self):
        with self.assertRaises(ValidationError) as caught:
            self.app.move_page.execute("7001", "2003")
        self.assertEqual(caught.exception.message, "7001 is a folder, and the API has no call to move a folder.")
        self.gateway.content_kinds["7101"] = "blogpost"
        with self.assertRaises(ValidationError) as caught:
            self.app.move_page.execute("7101", "2003")
        self.assertEqual(caught.exception.message, "7101 is a blog post, which cannot be moved: only a page can.")
        with self.assertRaises(ValidationError) as caught:
            self.app.move_page.execute("2005", "7101")
        self.assertIn("cannot be the target of a move", caught.exception.message)
        with self.assertRaises(NotFoundError):
            self.app.move_page.execute("99999", "7001")
        with self.assertRaises(NotFoundError):
            self.app.move_page.execute("2005", "99999")
        with self.assertRaises(ValidationError):
            self.app.move_page.execute("7001", "7001")
        self.assertEqual(self.gateway.called("update_page") + self.gateway.called("move_page"), [])

    def test_a_target_of_another_space_a_page_that_is_not_current_and_a_move_into_itself(self):
        self.gateway.add_container("folder", "7099", "Elsewhere", space_key="DOCS")
        with self.assertRaises(ValidationError) as caught:
            self.app.move_page.execute("2005", "7099")
        self.assertEqual(caught.exception.message, "The target folder 7099 is not in the space of page 2005.")
        self.gateway.pages["2005"].status = "archived"
        with self.assertRaises(ValidationError) as caught:
            self.app.move_page.execute("2005", "7001")
        self.assertIn("is archived and is not moved", caught.exception.message)
        self.gateway.add_container("folder", "7090", "Below Architecture", parent_id="2003")
        with self.assertRaises(ValidationError) as caught:
            self.app.move_page.execute("2003", "7090")
        self.assertIn("A page cannot be moved below one of its own descendants", caught.exception.message)
        self.assertEqual(self.gateway.called("update_page"), [])

    def test_the_guards_of_an_update_hold_for_both_kinds_of_move(self):
        with self.assertRaises(ConflictError) as caught:
            self.app.move_page.execute("2002", "7001", if_version=2)
        self.assertEqual(caught.exception.details, {"pageId": "2002", "version": 3, "expected": 2})
        with self.assertRaises(ConflictError):
            self.app.move_page.execute("2002", "7001", if_unchanged_since="2026-10-02T00:00:00Z")
        with self.assertRaises(ConflictError):
            self.app.move_page.execute("2002", "2003", if_version=2)
        with self.assertRaises(ConflictError):
            self.app.move_page.execute("2002", "2003", if_unchanged_since="2026-10-02T00:00:00Z")
        self.assertEqual(self.gateway.called("update_page") + self.gateway.called("move_page"), [])
        self.assertEqual(self.app.move_page.execute("2002", "7001", if_version=3, if_unchanged_since="2026-10-30T00:00:00Z").version_to, 4)

    def test_a_guard_that_is_empty_or_no_time_is_refused_before_anything_is_asked_and_never_means_no_guard(self):
        for target in ("7001", "2003"):
            for text in ("", " ", "yesterday"):
                for dry_run in (True, False):
                    with self.subTest(target=target, guard=text, dry_run=dry_run):
                        with self.assertRaises(ValidationError) as caught:
                            self.app.move_page.execute("2002", target, if_unchanged_since=text, dry_run=dry_run)
                        self.assertIn("--if-unchanged-since", caught.exception.message)
        self.assertEqual(self.gateway.calls, [])  # not even a read
        self.assertEqual(self.app.move_page.execute("2002", "7001", if_unchanged_since=None).version_to, 4)  # none given: no guard

    def test_the_version_guard_is_a_number_and_zero_is_no_version(self):
        with self.assertRaises(ConflictError):
            self.app.move_page.execute("2002", "7001", if_version=0)
        with self.assertRaises(ConflictError):
            self.app.move_page.execute("2002", "2003", if_version=0)
        self.assertEqual(self.gateway.called("update_page") + self.gateway.called("move_page"), [])

    def test_a_conflict_that_confluence_reports_is_a_conflict(self):
        self.gateway.errors["update_page"] = ConflictError("Confluence reports a conflict (HTTP 409): Version conflict.")
        with self.assertRaises(ConflictError):
            self.app.move_page.execute("2005", "7001")
        self.assertEqual(self.gateway.pages["2005"].parent_id, "2001")

    def test_the_message_of_the_version_and_the_title_of_the_target_are_redacted(self):
        self.gateway.containers["7001"].title = "Guides of alex@example.com"
        result = self.app.move_page.execute("2005", "7001", dry_run=True)
        self.assertEqual((result.payload["version"]["message"], result.where.title), ("Moved below Guides of [email]", "Guides of [email]"))

    def test_the_position_of_a_move_is_judged_before_a_title_that_is_none_matters(self):
        with self.assertRaises(UsageError):
            self.app.move_page.execute("2005", "2003", position="inside")
        self.assertEqual(self.gateway.calls, [])


class FailsToReadBack(FakeGateway):
    """A Confluence that cannot be asked for a page once a move has been made."""

    def get_page(self, page_id, *, with_body=True):
        if self.called("move_page"):
            raise UnavailableError("busy for alex@example.com")
        return super().get_page(page_id, with_body=with_body)


class IgnoresTheParent(FakeGateway):
    """A Confluence that saves a page again and leaves it where it was."""

    def update_page(self, page_id, payload):
        return super().update_page(page_id, {**payload, "parentId": ""})


class MoveConfirmationTest(unittest.TestCase):
    """A move that was made is not a failure because what comes after it fails: the page is read again, and the answer says what is known."""

    def test_a_move_that_cannot_be_read_back_is_still_a_move_and_says_so(self):
        gateway = FailsToReadBack()
        result = app_with(gateway).move_page.execute("2005", "2003")
        self.assertEqual((result.action, result.confirmed, result.page.id, result.version_from, result.version_to), ("moved", None, "2005", 1, 1))
        self.assertEqual(
            result.message, "The page was moved, but it could not be read back: busy for [email]. Check it with `conflu page 2005 --json` (parentId)."
        )  # what Confluence says is redacted
        self.assertEqual(gateway.pages["2005"].parent_id, "2003")  # the move was made, once
        self.assertEqual(len(gateway.called("move_page")), 1)

    def test_a_move_that_is_read_back_below_its_new_parent_is_confirmed(self):
        for position, target, parent in (("append", "2003", "2003"), ("before", "2003", "2001"), ("after", "2004", "2003")):
            with self.subTest(position=position):
                result = app_with(FakeGateway()).move_page.execute("2005", target, position=position)
                self.assertEqual((result.confirmed, result.message), (True, ""))
        self.assertEqual(app_with(FakeGateway()).move_page.execute("2005", "7001").confirmed, True)  # below a folder: the answer of the save says it

    def test_a_dry_run_and_a_page_that_stays_confirm_nothing(self):
        app = app_with(FakeGateway())
        self.assertEqual([app.move_page.execute("2005", target, dry_run=True).confirmed for target in ("2003", "7001")], [None, None])
        app.move_page.execute("2005", "7001")
        again = app.move_page.execute("2005", "7001")
        self.assertEqual((again.action, again.confirmed, again.message), ("unchanged", None, ""))

    def test_a_move_that_confluence_accepted_and_did_not_make_is_not_confirmed(self):
        gateway = FakeGateway()
        gateway.move_page = lambda page_id, position, target_id: gateway._enter("move_page", page_id, position, target_id)  # accepted, and nothing moved
        result = app_with(gateway).move_page.execute("2005", "2003")
        self.assertEqual((result.action, result.confirmed), ("moved", False))
        self.assertEqual(
            result.message, "Confluence accepted the move, but page 2005 sits below 2001, not below 2003. Check it with `conflu page 2005 --json` (parentId)."
        )
        stays = app_with(IgnoresTheParent()).move_page.execute("2005", "7001")
        self.assertEqual((stays.confirmed, stays.message.startswith("Confluence accepted the move, but page 2005 sits below 2001, not below 7001.")), (False, True))


class ShowTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.app = app_with(self.gateway)
        self.show = self.app.structure.show

    def test_a_folder_without_people(self):
        view = self.show.execute("folder", "7001")
        container = view.container
        self.assertEqual((container.id, container.type, container.title, container.space_key, container.parent_id), ("7001", "folder", "Guides", "ENG", ""))
        self.assertEqual((container.author, container.owner, container.version.author, view.users_shown), (None, None, None, False))
        self.assertEqual((view.listing, view.items, view.ancestors), ("", [], None))
        self.assertEqual([call[0] for call in self.gateway.calls], ["get_container"])

    def test_people_are_named_only_when_asked_for(self):
        view = self.show.execute("folder", "7001", with_users=True)
        self.assertEqual((view.container.author.display_name, view.container.owner.display_name, view.container.version.author.display_name), ("Alex Example",) * 3)
        refused = app_with(self.gateway, hide_users=True)
        with self.assertRaises(ValidationError):
            refused.structure.show.execute("folder", "7001", with_users=True)
        self.assertEqual(refused.structure.show.execute("folder", "7001").container.author, None)

    def test_text_is_redacted_unless_people_are_shown(self):
        self.gateway.containers["7061"].title = "Mail alex@example.com"
        self.gateway.containers["7061"].embed_url = "https://example.atlassian.net/wiki/people/5b10ac8d82e05b22cc7d4ef5"
        hidden = self.show.execute("embed", "7061").container
        self.assertEqual((hidden.title, hidden.embed_url), ("Mail [email]", "[personal link]"))
        shown = self.show.execute("embed", "7061", with_users=True).container
        self.assertEqual((shown.title, "/people/" in shown.embed_url), ("Mail alex@example.com", True))

    def test_the_path_has_titles_and_the_children_come_in_the_order_of_the_tree(self):
        self.gateway.add_page_below("7001", "7101", "Getting started")
        view = self.show.execute("folder", "7011", listing="children", ancestors=True)
        self.assertEqual([(ref.id, ref.title, ref.type) for ref in view.ancestors], [("7001", "Guides", "folder")])
        self.assertEqual(view.items, [])
        children = self.show.execute("folder", "7001", listing="children", fetch_everything=True)
        self.assertEqual([(node.id, node.type) for node in children.items], [("7021", "whiteboard"), ("7101", "page"), ("7061", "embed"), ("7011", "folder"), ("7041", "database")])
        self.assertEqual((children.next_cursor, children.truncated, children.listing), ("", False, "children"))

    def test_a_list_comes_in_pieces_with_a_cursor(self):
        first = self.show.execute("folder", "7001", listing="children", limit=2)
        self.assertEqual((len(first.items), first.next_cursor), (2, "2"))
        second = self.show.execute("folder", "7001", listing="children", limit=2, cursor=first.next_cursor)
        self.assertEqual(([node.id for node in second.items], second.next_cursor), (["7011", "7041"], ""))  # four children: the last piece names no cursor
        self.assertEqual(self.gateway.called("list_children")[-1], ("list_children", "folder", "7001", 2, "2"))

    def test_the_fields_the_views_and_the_entries_of_a_database(self):
        fields = self.show.execute("database", "7041", listing="fields", fetch_everything=True)
        self.assertEqual([(item.id, item.type, item.options) for item in fields.items][1], ("tier", "select", ("Gold", "Silver", "Bronze")))
        views = self.show.execute("database", "7041", listing="views", fetch_everything=True)
        self.assertEqual([(item.id, item.name, item.type) for item in views.items], [("view-all", "All services", "table"), ("view-tier", "By tier", "board")])
        entries = self.show.execute("database", "7041", listing="entries", fetch_everything=True)
        self.assertEqual([column.id for column in entries.columns], ["name", "tier", "owner", "active", "docs"])
        first, second, third = entries.items
        self.assertEqual(first.values["owner"], ["[hidden]"])
        self.assertEqual((second.values["owner"], second.values["active"]), (None, False))
        self.assertEqual((third.values["name"], third.values["owner"]), ("Contact [email]", []))
        self.assertNotIn(ACCOUNT, json.dumps([item.values for item in entries.items]))

    def test_with_users_the_people_in_the_cells_are_named_and_the_text_is_left_alone(self):
        entries = self.show.execute("database", "7041", listing="entries", fetch_everything=True, with_users=True)
        self.assertEqual(entries.items[0].values["owner"], [{"accountId": ACCOUNT, "displayName": "Alex Example", "email": "alex@example.com"}])
        self.assertEqual(entries.items[2].values["name"], "Contact alex@example.com")
        self.assertEqual(len(self.gateway.called("lookup_users")), 2)  # the people of the database, and those in its cells

    def test_the_entries_name_a_field_that_has_no_column(self):
        self.gateway.database_entries["7041"][0].values["extra"] = type(self.gateway.database_entries["7041"][0].values["name"])("text", "More")
        entries = self.show.execute("database", "7041", listing="entries", limit=1)
        self.assertEqual(list(entries.items[0].values), ["name", "tier", "owner", "active", "docs", "extra"])

    def test_the_other_kinds_have_no_fields_views_or_entries(self):
        for listing in ("fields", "views", "entries"):
            with self.subTest(listing=listing), self.assertRaises(UsageError):
                self.show.execute("folder", "7001", listing=listing)
        self.assertEqual(self.gateway.calls, [])

    def test_an_id_of_another_kind_says_what_it_is(self):
        with self.assertRaises(NotFoundError) as caught:
            self.show.execute("folder", "2003")
        self.assertEqual(caught.exception.hint, "2003 is a page, not a folder: use `conflu page 2003`.")
        with self.assertRaises(NotFoundError) as caught:
            self.show.execute("database", "7001")
        self.assertEqual(caught.exception.hint, "7001 is a folder, not a database: use `conflu folder 7001`.")
        with self.assertRaises(NotFoundError) as caught:
            self.show.execute("embed", "7041")
        self.assertIn("use `conflu database 7041`", caught.exception.hint)
        with self.assertRaises(NotFoundError) as caught:
            self.show.execute("folder", "99999")
        self.assertEqual(caught.exception.hint, "")  # nothing to add: it is not known

    def test_an_address_names_the_item(self):
        self.assertEqual(self.show.execute("folder", f"{BASE}/spaces/ENG/folder/7011").container.id, "7011")
        with self.assertRaises(ValidationError):
            self.show.execute("folder", "../x")
        with self.assertRaises(ValueError):
            self.show.execute("page", "2003")


class CreateContainerTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.app = app_with(self.gateway)

    def test_a_folder_below_a_page_below_a_folder_and_at_the_top(self):
        below_page = self.app.structure.create_folder.execute("Runbooks", space="ENG", parent="2003")
        self.assertEqual(below_page.payload, {"spaceId": "1001", "title": "Runbooks", "parentId": "2003"})
        self.assertEqual((below_page.container.type, below_page.container.parent_type, below_page.parent.type), ("folder", "page", "page"))
        below_folder = self.app.structure.create_folder.execute("Nested", space="ENG", parent=below_page.container.id)
        self.assertEqual((below_folder.container.parent_id, below_folder.container.parent_type), (below_page.container.id, "folder"))
        top = self.app.structure.create_folder.execute("Top", space="ENG")
        self.assertEqual((top.payload, top.parent, top.container.parent_id), ({"spaceId": "1001", "title": "Top"}, None, ""))
        self.assertEqual(self.gateway.content_kinds[top.container.id], "folder")  # known to content_types as well

    def test_the_dry_run_sends_nothing_and_proves_the_parent(self):
        result = self.app.structure.create_folder.execute("Preview", space="ENG", parent="7001", dry_run=True)
        self.assertEqual((result.dry_run, result.container, result.parent.title), (True, None, "Guides"))
        self.assertEqual(self.gateway.called("create_folder"), [])
        with self.assertRaises(NotFoundError):
            self.app.structure.create_folder.execute("Preview", space="ENG", parent="99999", dry_run=True)

    def test_what_a_dry_run_cannot_know_is_not_asked(self):
        self.app.structure.create_folder.execute("Guides", space="ENG", parent="7001", dry_run=True)  # the title is taken, and that is fine
        self.assertEqual(self.gateway.called("list_pages"), [])
        first = self.app.structure.create_folder.execute("Twin", space="ENG")
        second = self.app.structure.create_folder.execute("Twin", space="ENG")
        self.assertNotEqual(first.container.id, second.container.id)

    def test_the_request_is_the_one_of_the_dry_run(self):
        preview = self.app.structure.create_folder.execute("Same", space="ENG", parent="7001", dry_run=True)
        self.app.structure.create_folder.execute("Same", space="ENG", parent="7001")
        self.assertEqual(self.gateway.called("create_folder")[0][1], preview.payload)

    def test_a_smart_link_has_its_address_as_given(self):
        result = self.app.structure.create_smartlink.execute("Roadmap", url=" https://example.com/Road%20map?x=1 ", space="ENG", parent="7001")
        self.assertEqual(result.payload, {"spaceId": "1001", "title": "Roadmap", "parentId": "7001", "embedUrl": "https://example.com/Road%20map?x=1"})
        self.assertEqual((result.container.type, result.container.embed_url, result.container.parent_type), ("embed", "https://example.com/Road%20map?x=1", "folder"))
        self.assertEqual(self.gateway.called("create_smartlink")[0][1], result.payload)

    def test_what_is_refused_is_refused_before_anything_is_read(self):
        for call in (
            lambda: self.app.structure.create_folder.execute(" ", space="ENG"),
            lambda: self.app.structure.create_folder.execute("a\nb", space="ENG"),
            lambda: self.app.structure.create_smartlink.execute("T", url="ftp://example.com", space="ENG"),
            lambda: self.app.structure.create_smartlink.execute("T", url="", space="ENG"),
            lambda: self.app.structure.create_smartlink.execute("T", url="https://u:p@example.com", space="ENG"),
        ):
            with self.assertRaises(ValidationError):
                call()
        self.assertEqual(self.gateway.calls, [])

    def test_an_empty_space_or_parent_is_a_mistake_and_not_the_current_space_or_the_top_of_the_space(self):
        current = app_with(self.gateway, space="DOCS")
        for execute in (current.structure.create_folder.execute, lambda title, **options: current.structure.create_smartlink.execute(title, url="https://example.com", **options)):
            for options, message in (({"space": ""}, "The space is empty."), ({"space": "  "}, "The space is empty."), ({"parent": ""}, "The parent is empty."), ({"parent": " "}, "The parent is empty.")):
                for dry_run in (True, False):
                    with self.subTest(options=options, dry_run=dry_run):
                        with self.assertRaises(UsageError) as caught:
                            execute("Empty", dry_run=dry_run, **{"space": "ENG", **options})
                        self.assertEqual(caught.exception.message, message)
        self.assertEqual(self.gateway.calls, [])  # nothing was asked, and nothing was made in DOCS or at the top of ENG
        self.assertEqual(current.structure.create_folder.execute("Here", space=None, parent=None, dry_run=True).space_key, "DOCS")  # none named: the current space

    def test_the_space_the_parent_and_the_current_space(self):
        with self.assertRaises(UsageError):
            self.app.structure.create_folder.execute("No space")
        with self.assertRaises(NotFoundError):
            self.app.structure.create_folder.execute("Wrong", space="NOPE")
        self.gateway.add_container("folder", "7099", "Elsewhere", space_key="DOCS")
        with self.assertRaises(ValidationError) as caught:
            self.app.structure.create_folder.execute("Wrong space", space="ENG", parent="7099")
        self.assertEqual(caught.exception.hint, "A folder is created in the space of its parent: pass that space, or another parent.")
        with self.assertRaises(ValidationError) as caught:
            self.app.structure.create_smartlink.execute("Wrong space", url="https://example.com", space="ENG", parent="7099")
        self.assertIn("A smart link is created in the space", caught.exception.hint)
        self.gateway.content_kinds["7101"] = "blogpost"
        with self.assertRaises(ValidationError):
            self.app.structure.create_folder.execute("Below a blog post", space="ENG", parent="7101")
        current = app_with(self.gateway, space="DOCS")
        self.assertEqual(current.structure.create_folder.execute("Here", dry_run=True).space_key, "DOCS")
        self.assertEqual(self.gateway.called("create_folder"), [])


class ExportBelowTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.gateway.add_page_below("7001", "7101", "Getting started", body="<p>Start.</p>")
        self.gateway.add_page_below("7101", "7102", "Deeper", body="<p>Deep.</p>")
        self.gateway.add_container("folder", "7090", "Archive", parent_id="7011")
        self.gateway.add_page_below("7090", "7103", "Old notes", body="<p>Old.</p>")
        self.files = MemoryFiles()
        self.app = app_with(self.gateway, self.files)

    def test_the_pages_below_a_folder_are_exported_and_the_folder_is_not(self):
        result = self.app.export_pages.execute(out_dir="out", root="7001")
        self.assertEqual((result.root, result.space, result.truncated), ("7001", "ENG", False))
        self.assertEqual(sorted(page.id for page in result.pages), ["7101", "7102", "7103"])
        self.assertEqual(result.notes, ["A folder is not a page: the pages below it are exported, and it is not."])
        paths = {page.id: page.path for page in result.pages}
        self.assertEqual(paths, {"7101": "Guides", "7102": "Guides > Getting started", "7103": "Guides > Runbooks > Archive"})
        by_id = {page.id: page for page in result.pages}
        self.assertEqual(by_id["7101"].parent_id, "7001")
        written = self.files.text(self.files.join("out", by_id["7101"].file))
        self.assertIn("parent: 7001", written)
        self.assertIn("path: Guides", written)
        index = json.loads(self.files.text("out/index.json"))
        self.assertEqual((index["root"], index["space"], [page["id"] for page in index["pages"]][0]), ("7001", "ENG", "7102"))

    def test_a_dry_run_writes_nothing(self):
        result = self.app.export_pages.execute(out_dir="out", root="7001", dry_run=True)
        self.assertEqual((len(result.pages), self.files.writes), (3, []))

    def test_the_path_above_a_folder_has_every_kind_of_ancestor(self):
        self.gateway.add_container("folder", "7091", "Top", parent_id="2003")
        self.gateway.add_container("folder", "7092", "Inner", parent_id="7091")
        self.gateway.add_page_below("7092", "7104", "Deep page")
        result = self.app.export_pages.execute(out_dir="out2", root="7092")
        self.assertEqual({page.id: page.path for page in result.pages}, {"7104": "Engineering Home > Architecture > Top > Inner"})

    def test_a_page_root_shows_the_folder_it_sits_in(self):
        result = self.app.export_pages.execute(out_dir="out3", root="7101")
        self.assertEqual({page.id: page.path for page in result.pages}, {"7101": "Guides", "7102": "Guides > Getting started"})
        self.assertEqual(result.notes, [])

    def test_the_path_of_a_page_below_a_folder_below_a_page(self):
        result = self.app.export_pages.execute(out_dir="out4", root="2003")
        paths = {page.id: page.path for page in result.pages}
        self.assertEqual(paths["2003"], "Engineering Home")
        self.assertEqual(paths["2004"], "Engineering Home > Architecture")

    def test_the_other_roots_and_what_cannot_be_one(self):
        with self.assertRaises(ValidationError) as caught:
            self.app.export_pages.execute(out_dir="out5", root="7041")
        self.assertEqual(caught.exception.message, "There are no pages to export.")
        self.gateway.content_kinds["7201"] = "blogpost"
        with self.assertRaises(ValidationError) as caught:
            self.app.export_pages.execute(out_dir="out5", root="7201")
        self.assertIn("cannot be the start of a tree", caught.exception.message)
        with self.assertRaises(NotFoundError):
            self.app.export_pages.execute(out_dir="out5", root="99999")
        with self.assertRaises(UsageError):
            self.app.export_pages.execute(out_dir="out5", root="7001", space="ENG")

    def test_a_page_root_asks_what_it_always_asked(self):
        self.gateway.calls.clear()
        self.app.export_pages.execute(out_dir="out6", root="2003", dry_run=True)
        self.assertEqual([call[0] for call in self.gateway.calls][:2], ["get_page", "list_descendants"])
        self.assertNotIn("content_types", [call[0] for call in self.gateway.calls])

    def test_an_option_that_is_empty_is_a_mistake_and_nothing_is_asked_or_written(self):
        current = app_with(self.gateway, self.files, space="ENG")
        for options, message in (
            ({"out_dir": "out7", "root": ""}, "The page is empty."),  # it would have exported the whole current space
            ({"out_dir": "out7", "root": "  "}, "The page is empty."),
            ({"out_dir": "out7", "space": ""}, "The space is empty."),
            ({"out_dir": "out7", "space": "  "}, "The space is empty."),
            ({"out_dir": "", "space": "ENG"}, "The output folder is empty."),  # it would have written into the folder that the command runs in
            ({"out_dir": " ", "space": "ENG"}, "The output folder is empty."),
        ):
            for dry_run in (True, False):
                with self.subTest(options=options, dry_run=dry_run):
                    self.gateway.calls.clear()
                    with self.assertRaises(UsageError) as caught:
                        current.export_pages.execute(dry_run=dry_run, **options)
                    self.assertEqual(caught.exception.message, message)
                    self.assertEqual((self.gateway.calls, self.files.writes), ([], []))
        named_root = current.export_pages.execute(out_dir="out7", root="7001", dry_run=True)  # none given is none: the root alone
        self.assertEqual((named_root.root, named_root.space), ("7001", "ENG"))
        self.assertEqual(current.export_pages.execute(out_dir="out7", root=None, space=None, dry_run=True).space, "ENG")  # and the current space


PERSONAL = f"~{ACCOUNT}"


class PersonalSpaceTest(unittest.TestCase):
    """The key of a personal space is `~` and the account id of its owner: what a use case hands to a command has `[hidden]` for it (the commands
    that have `--with-users` show what Confluence names)."""

    def setUp(self):
        self.gateway = FakeGateway()
        self.gateway.spaces[PERSONAL] = Space("1003", PERSONAL, "Alex Example", "personal", "current", "", "30000", "2026-09-01T08:00:00.000Z", f"{BASE}/spaces/{PERSONAL}")
        self.gateway.pages["30000"] = sample_page("30000", "Start", space_id="1003", space_key=PERSONAL)
        self.gateway.add_page_below("30000", "30001", "Notes", space_key=PERSONAL)
        self.gateway.add_container("folder", "7095", "Archive", parent_id="30000", space_key=PERSONAL)
        self.gateway.add_page_below("7095", "30002", "Old notes", space_key=PERSONAL)
        self.files = MemoryFiles()
        self.app = app_with(self.gateway, self.files)

    def test_a_tree_has_no_key_of_the_space(self):
        for root in ("30001", "30000", "7095"):
            with self.subTest(root=root):
                self.assertEqual(self.app.tree_pages.execute(root).space_key, HIDDEN)
        self.assertEqual(self.app.tree_pages.execute("2001").space_key, "ENG")

    def test_an_export_names_no_key_and_no_address_of_the_space_whoever_typed_the_key(self):
        for options in ({"space": PERSONAL}, {"root": "30000"}, {"root": "30001"}, {"root": "7095"}):
            with self.subTest(options=options):
                files = MemoryFiles()
                result = app_with(self.gateway, files).export_pages.execute(out_dir="out", **options)
                self.assertEqual(result.space, HIDDEN)
                self.assertTrue(files.files)
                for path, content in files.files.items():
                    self.assertNotIn(ACCOUNT, path + content.decode("utf-8"))
                self.assertEqual(json.loads(files.text("out/index.json"))["space"], HIDDEN)

    def test_the_front_matter_of_a_page_in_a_personal_space(self):
        result = self.app.export_pages.execute(out_dir="out", root="30001")
        written = self.files.text(self.files.join("out", result.pages[0].file))
        self.assertIn("space: [hidden]\n", written)
        self.assertIn(f"url: {BASE}/pages/viewpage.action?pageId=30001\n", written)  # the address that names the page by its id alone
        elsewhere = self.app.export_pages.execute(out_dir="out2", root="2003")
        self.assertIn("space: ENG\n", self.files.text(self.files.join("out2", elsewhere.pages[0].file)))
        self.assertEqual(elsewhere.space, "ENG")

    def test_a_folder_in_the_space_has_no_key_and_no_account_id_in_its_address(self):
        view = self.app.structure.show.execute("folder", "7095")
        self.assertEqual((view.container.space_key, view.container.url), (HIDDEN, f"{BASE}/spaces/{HIDDEN}/folder/7095"))
        shown = self.app.structure.show.execute("folder", "7095", with_users=True)
        self.assertEqual((shown.container.space_key, shown.container.url), (PERSONAL, f"{BASE}/spaces/{PERSONAL}/folder/7095"))

    def test_a_new_folder_or_smart_link_in_the_space_names_no_key(self):
        for dry_run in (True, False):
            folder = self.app.structure.create_folder.execute("Top", space=PERSONAL, dry_run=dry_run)
            link = self.app.structure.create_smartlink.execute("Link", url="https://example.com/x", space=PERSONAL, parent="7095", dry_run=dry_run)
            self.assertEqual((folder.space_key, link.space_key), (HIDDEN, HIDDEN))
            self.assertEqual(folder.payload["spaceId"], "1003")  # the request names the space by its id
        self.assertEqual(self.app.structure.create_folder.execute("Top", space="ENG", dry_run=True).space_key, "ENG")

    def test_what_is_refused_names_no_key(self):
        draft = PageDraft(space=PERSONAL, title="Notes", body="<p>Hi</p>")
        with self.assertRaises(ConflictError) as caught:
            self.app.create_page.execute(draft)
        self.assertEqual(caught.exception.message, "A page titled 'Notes' exists already in space [hidden] (id 30001).")
        self.assertEqual(caught.exception.details["space"], HIDDEN)
        with self.assertRaises(ValidationError) as caught:
            self.app.create_page.execute(PageDraft(space=PERSONAL, title="Elsewhere", parent="7001"))
        self.assertEqual(caught.exception.message, "The parent folder 7001 is not in space [hidden].")
        with self.assertRaises(ValidationError) as caught:
            self.app.structure.create_folder.execute("Elsewhere", space=PERSONAL, parent="7001")
        self.assertEqual(caught.exception.message, "The parent folder 7001 is not in space [hidden].")

    def test_a_title_that_is_asked_for_by_name_names_no_key(self):
        self.gateway.add_page_below("2001", "2010", "Same")
        self.gateway.add_page_below("30000", "30010", "Same", space_key=PERSONAL)
        with self.assertRaises(ValidationError) as caught:
            resolve_page_ref(self.gateway, default_settings(), "page:Same")
        self.assertEqual(caught.exception.message, "2 pages are titled 'Same' on this site: ENG 2010, [hidden] 30010.")
        with self.assertRaises(NotFoundError) as caught:
            resolve_page_ref(self.gateway, default_settings(), f"page:{PERSONAL}/Missing")
        self.assertEqual(caught.exception.message, "No current page is titled 'Missing' in the space [hidden].")
        self.assertEqual(resolve_page_ref(self.gateway, default_settings(), f"page:{PERSONAL}/Same"), "30010")


if __name__ == "__main__":
    unittest.main()
