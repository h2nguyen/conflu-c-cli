"""Search, reading a page in parts, following a `page:` link and the path in an export: the use cases behind what agents need."""
import json
import unittest

from conflu_c_cli.domain.errors import ConfluCliError, NotFoundError, RejectedError, UsageError, ValidationError
from conflu_c_cli.domain.model import SearchHit
from tests.support.fakes import ACCOUNT, FakeGateway, MemoryFiles, build_app, default_settings, sample_page


def app_with(gateway=None, files=None, **settings):
    return build_app(gateway=gateway or FakeGateway(), files=files, settings=default_settings(**settings))


class SearchWordsTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.app = app_with(self.gateway)

    def cqls(self):
        return [call[1] for call in self.gateway.called("search")]

    def test_a_question_is_searched_by_its_meaningful_words_and_the_answer_says_what_was_left_out(self):
        result = self.app.search_content.execute(text="how do I read the release notes?")
        self.assertEqual(self.cqls(), ['type = page AND text ~ "read release notes"'])
        self.assertEqual((result.terms, result.ignored, result.match, result.relaxed), (("read", "release", "notes"), ("how", "do", "I", "the"), "all", False))
        self.assertTrue(any("Left out as filler: how, do, I, the" in note for note in result.notes))

    def test_a_phrase_is_a_clause_of_its_own(self):
        result = self.app.search_content.execute(text='"release notes" ports')
        self.assertEqual(self.cqls(), ['type = page AND text ~ "ports" AND text ~ "\\"release notes\\""'])
        self.assertEqual(result.terms, ('"release notes"', "ports"))  # in the order they were typed; the query puts words first

    def test_when_no_page_has_every_word_the_pages_with_some_are_shown_and_it_is_said(self):
        self.gateway.search_handler = lambda cql: [] if " OR " not in cql else self.gateway.search_hits[:2]
        result = self.app.search_content.execute(text="alpha beta")
        self.assertEqual(len(self.cqls()), 2)
        self.assertEqual(self.cqls()[1], 'type = page AND (text ~ "alpha" OR text ~ "beta")')
        self.assertEqual((result.relaxed, result.match, result.total, len(result.hits)), (True, "any", 2, 2))
        self.assertTrue(result.notes[0].startswith("No page holds all of these words (alpha, beta)"))

    def test_all_never_relaxes_and_any_asks_for_some_directly(self):
        self.gateway.search_handler = lambda cql: [] if " OR " not in cql else self.gateway.search_hits[:2]
        strict = self.app.search_content.execute(text="alpha beta", match="all")
        self.assertEqual((len(self.cqls()), strict.relaxed, strict.total), (1, False, 0))
        self.gateway.calls.clear()
        direct = self.app.search_content.execute(text="alpha beta", match="any")
        self.assertEqual((len(self.cqls()), direct.relaxed, direct.match, len(direct.hits)), (1, False, "any", 2))
        self.assertIn(" OR ", self.cqls()[0])

    def test_a_search_that_has_hits_is_not_repeated_and_one_word_is_never_relaxed(self):
        self.app.search_content.execute(text="alpha beta")
        self.assertEqual(len(self.cqls()), 1)
        self.gateway.calls.clear()
        self.gateway.search_handler = lambda cql: []
        result = self.app.search_content.execute(text="alpha")
        self.assertEqual((len(self.cqls()), result.relaxed), (1, False))

    def test_relaxing_also_works_when_everything_is_fetched(self):
        self.gateway.search_handler = lambda cql: [] if " OR " not in cql else self.gateway.search_hits
        result = self.app.search_content.execute(text="alpha beta", fetch_everything=True)
        self.assertEqual((result.relaxed, len(result.hits)), (True, 3))

    def test_nothing_found_explains_what_to_try(self):
        self.gateway.search_handler = lambda cql: []
        result = self.app.search_content.execute(text="wie beantrage ich eine Gruppe")
        text = " ".join(result.notes)
        self.assertIn("Nothing found", text)
        self.assertIn("another language", text)
        self.assertIn("wildcard", text)
        self.assertEqual(result.ignored, ("wie", "ich", "eine"))

    def test_a_query_written_by_hand_is_used_as_it_is_and_its_words_are_the_terms(self):
        result = self.app.search_content.execute(cql='type = page AND text ~ "ports adapters" AND label = "adr"', text="ignored")
        self.assertEqual(self.cqls(), ['type = page AND text ~ "ports adapters" AND label = "adr"'])
        self.assertEqual((result.match, result.terms, result.relaxed), ("cql", ("ports", "adapters"), False))

    def test_a_text_of_nothing_but_punctuation_is_nothing_to_search_for(self):
        with self.assertRaises(ValidationError):
            self.app.search_content.execute(text="?! = -")
        self.assertEqual(self.cqls(), [])

    def test_the_options_are_checked(self):
        for kwargs in ({"match": "some"}, {"snippets": -1}, {"snippets": 26}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(UsageError):
                    self.app.search_content.execute(text="x", **kwargs)
        self.assertEqual(self.cqls(), [])


class SearchHitsTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.gateway.page_cap = 10  # the fake hands out two hits at a time unless told otherwise
        self.app = app_with(self.gateway)

    def test_a_hit_says_where_it_is_how_it_is_tagged_and_which_version(self):
        hit = self.app.search_content.execute(text="release").hits[0]
        self.assertEqual((hit.path, hit.labels, hit.version), ("Engineering Home", ("release", "notes"), 3))

    def test_the_path_is_redacted_like_every_other_text(self):
        self.gateway.search_handler = lambda cql: [SearchHit("1", "page", "T", "ENG", path="Mail alex@example.com > Sub")]
        self.assertEqual(self.app.search_content.execute(text="x").hits[0].path, "Mail [email] > Sub")

    def test_snippets_come_from_one_request_and_from_the_page_as_conflu_page_shows_it(self):
        result = self.app.search_content.execute(text="release notes", snippets=2)
        reads = self.gateway.called("list_pages")
        self.assertEqual(len(reads), 1)
        self.assertEqual((reads[0][2], reads[0][7]), (("2002", "2003"), True))  # the two ids, with the body
        first, second, third = result.hits
        self.assertNotIn("alex@example.com", first.snippet)
        self.assertNotIn(ACCOUNT, first.snippet)
        self.assertIn("[email]", first.snippet)  # the page as `conflu page` shows it
        self.assertEqual(first.matched, ("release", "notes"))
        self.assertTrue(second.snippet)  # no word of the search in it: the beginning of the page
        self.assertEqual(second.matched, ())
        self.assertEqual(third.snippet, "")  # beyond the first two
        self.assertNotIn(ACCOUNT, json.dumps([hit.__dict__ for hit in result.hits], default=str))

    def test_the_passage_is_around_the_words(self):
        self.gateway.pages["2003"].body = "<p>" + "Filler words go here. " * 30 + "The ports and adapters decision is recorded here. " + "More filler. " * 30 + "</p>"
        self.gateway.search_handler = lambda cql: [self.gateway.search_hits[1]]
        hit = self.app.search_content.execute(text="ports adapters", snippets=1).hits[0]
        self.assertIn("ports and adapters decision", hit.snippet)
        self.assertEqual(hit.matched, ("ports", "adapters"))

    def test_only_pages_get_a_snippet_and_only_their_ids_are_read(self):
        self.gateway.search_handler = lambda cql: [SearchHit("att1", "attachment", "file.pdf", "ENG"), self.gateway.search_hits[0]]
        result = self.app.search_content.execute(text="release", snippets=5)
        self.assertEqual(self.gateway.called("list_pages")[0][2], ("2002",))
        self.assertEqual((result.hits[0].snippet, bool(result.hits[1].snippet)), ("", True))

    def test_no_snippets_means_no_request_for_the_pages(self):
        self.app.search_content.execute(text="release")
        self.assertEqual(self.gateway.called("list_pages"), [])

    def test_a_page_that_cannot_be_read_does_not_fail_the_search(self):
        self.gateway.errors["list_pages"] = RejectedError("Confluence refused")
        result = self.app.search_content.execute(text="release", snippets=2)
        self.assertEqual(len(result.hits), 3)
        self.assertEqual({hit.snippet for hit in result.hits}, {""})
        self.assertTrue(any("could not be read" in note and "Confluence refused" in note for note in result.notes))

    def test_a_page_that_links_to_a_profile_shows_no_profile_path_in_a_snippet(self):
        body = '<p>Contact <a href="/wiki/people/5b10ac8d82e05b22cc7d4ef5">Alex Example</a> about the release process.</p>'
        self.gateway.pages["2002"].body = body
        self.gateway.search_handler = lambda cql: [self.gateway.search_hits[0]]
        hit = self.app.search_content.execute(text="release process", snippets=1).hits[0]
        self.assertIn("release process", hit.snippet)
        for secret in ("5b10ac8d82e05b22cc7d4ef5", "/people/", "Alex Example"):
            self.assertNotIn(secret, hit.snippet)

    def test_the_page_as_markdown_text_and_export_show_no_profile_path(self):
        from conflu_c_cli.application.rendering import render_body

        body = '<p>See <a href="/wiki/people/5b10ac8d82e05b22cc7d4ef5">Alex Example</a>.</p>'
        for fmt in ("markdown", "text"):
            with self.subTest(fmt=fmt):
                shown = render_body(body, fmt, with_users=False)
                self.assertEqual(shown.text.strip(), "See @user.")  # a link to a profile names a person, as a mention does
        self.assertIn("mention", render_body(body, "markdown", with_users=False).dropped)  # so Markdown cannot replace this page unforced
        self.assertIn("5b10ac8d82e05b22cc7d4ef5", render_body(body, "markdown", with_users=True).text)  # with --with-users the page is as it is

    def test_a_page_that_the_read_leaves_out_has_no_snippet_and_the_others_have(self):
        del self.gateway.pages["2003"]
        result = self.app.search_content.execute(text="release", snippets=2)
        self.assertEqual([bool(hit.snippet) for hit in result.hits], [True, False, False])


class PagePartsTest(unittest.TestCase):
    BODY = (
        "<h1>Intro</h1><p>Alpha text.</p><h2>Steps</h2><p>Do this.</p><ul><li>one</li><li>two</li></ul>"
        "<h2>Notes</h2><p>" + "Remember this. " * 40 + "</p>"
    )

    def setUp(self):
        self.gateway = FakeGateway()
        self.gateway.pages["2005"].body = self.BODY
        self.app = app_with(self.gateway)

    def view(self, **kwargs):
        return self.app.view_page.execute("2005", **kwargs)

    def test_the_outline_lists_the_headings_and_returns_no_body(self):
        view = self.view(outline=True)
        self.assertIsNone(view.body)
        self.assertEqual([(h.index, h.level, h.title) for h in view.outline], [(1, 1, "Intro"), (2, 2, "Steps"), (3, 2, "Notes")])
        self.assertGreater(view.outline[2].chars, view.outline[1].chars)

    def test_a_section_is_only_that_section(self):
        body = self.view(section="steps").body
        self.assertEqual(body.section, "Steps")
        self.assertTrue(body.text.startswith("## Steps"))
        self.assertIn("one", body.text)
        self.assertNotIn("Remember", body.text)
        self.assertFalse(body.truncated)
        self.assertEqual(self.view(section="2").body.section, "Steps")

    def test_a_long_text_is_cut_and_says_how_long_it_was(self):
        whole = len(self.view().body.text)
        body = self.view(max_chars=120).body
        self.assertTrue(body.truncated)
        self.assertEqual(body.total_chars, whole)
        self.assertLessEqual(len(body.text), 121)
        self.assertFalse(self.view(max_chars=100000).body.truncated)

    def test_a_section_can_be_cut_too_and_the_size_is_the_sections(self):
        section = self.view(section="Notes").body.text
        body = self.view(section="Notes", max_chars=60).body
        self.assertEqual((body.section, body.truncated, body.total_chars), ("Notes", True, len(section)))

    def test_the_text_format_can_be_cut_but_has_no_headings(self):
        self.assertTrue(self.view(body_format="text", max_chars=50).body.truncated)
        for kwargs in ({"outline": True}, {"section": "Steps"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(UsageError):
                self.view(body_format="text", **kwargs)

    def test_the_storage_format_is_never_cut(self):
        for kwargs in ({"outline": True}, {"section": "Steps"}, {"max_chars": 50}):
            with self.subTest(kwargs=kwargs), self.assertRaises(UsageError) as caught:
                self.view(body_format="storage", **kwargs)
            self.assertTrue(caught.exception.hint)

    def test_the_options_that_do_not_fit_together_are_refused(self):
        for kwargs in ({"outline": True, "section": "Steps"}, {"outline": True, "max_chars": 10}, {"outline": True, "with_body": False}, {"section": "Steps", "with_body": False}, {"max_chars": -1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(UsageError):
                self.view(**kwargs)

    def test_an_unknown_section_lists_the_headings(self):
        with self.assertRaises(ValidationError) as caught:
            self.view(section="nothing")
        self.assertIn("1. Intro", caught.exception.hint)

    def test_what_markdown_cannot_say_is_named_for_the_whole_page_also_when_a_section_is_read(self):
        view = self.app.view_page.execute("2002", section="Release notes")
        self.assertIn("macro:toc", view.body.dropped)

    def test_people_stay_out_of_a_section_as_in_the_whole_page(self):
        text = self.app.view_page.execute("2002", section="Release notes").body.text
        self.assertNotIn(ACCOUNT, text)
        self.assertNotIn("alex@example.com", text)


class FollowALinkTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.app = app_with(self.gateway)

    def title_of(self, ref, **kwargs):
        return self.app.view_page.execute(ref, with_body=False, **kwargs).page.title

    def test_a_page_reference_names_the_space(self):
        self.assertEqual(self.title_of("page:ENG/Architecture"), "Architecture")
        self.assertEqual(self.title_of("PAGE:eng/architecture"), "Architecture")  # a reference in any case

    def test_without_a_space_the_option_then_the_current_space_then_the_whole_site(self):
        self.assertEqual(self.title_of("page:Architecture", space="ENG"), "Architecture")
        self.assertEqual(self.app.tree_pages.execute("page:Architecture", depth=1, space="ENG").root.title, "Architecture")
        self.assertEqual(self.app.view_page.execute("page:Architecture", with_body=False).page.id, "2003")  # unique on the site
        app = app_with(self.gateway, space="ENG")
        self.assertEqual(app.view_page.execute("page:Architecture", with_body=False).page.id, "2003")

    def test_a_title_in_two_spaces_asks_for_the_space(self):
        self.gateway.pages["2099"] = sample_page("2099", "Architecture", space_id="1002", space_key="DOCS")
        with self.assertRaises(ValidationError) as caught:
            self.title_of("page:Architecture")
        self.assertIn("2 pages are titled", caught.exception.message)
        self.assertIn("DOCS 2099", caught.exception.message)
        self.assertIn("page:KEY/Title", caught.exception.hint)
        self.assertEqual(self.title_of("page:DOCS/Architecture"), "Architecture")

    def test_a_title_with_a_slash_is_a_title_when_its_first_part_is_no_space(self):
        self.gateway.pages["2098"] = sample_page("2098", "CI/CD pipeline")
        self.assertEqual(self.title_of("page:CI/CD pipeline", space="ENG"), "CI/CD pipeline")

    def test_a_title_with_a_slash_is_found_when_its_first_part_is_a_space_that_lacks_the_page(self):
        self.gateway.pages["2097"] = sample_page("2097", "Runbook", space_id="1002", space_key="DOCS")
        self.gateway.pages["2098"] = sample_page("2098", "DOCS/Runbook index")  # in ENG; DOCS exists but has no `Runbook index`
        self.assertEqual(self.title_of("page:DOCS/Runbook index", space="ENG"), "DOCS/Runbook index")
        self.assertEqual(self.title_of("page:DOCS/Runbook"), "Runbook")  # the named space wins when it holds the page

    def test_a_named_space_without_the_page_still_reports_that_space(self):
        with self.assertRaises(NotFoundError) as caught:
            self.title_of("page:DOCS/No such page", space="ENG")
        self.assertIn("'No such page' in the space DOCS", caught.exception.message)

    def test_a_missing_page_says_where_it_looked(self):
        with self.assertRaises(NotFoundError) as caught:
            self.title_of("page:ENG/No such page")
        self.assertIn("in the space ENG", caught.exception.message)
        self.assertIn("conflu search", caught.exception.hint)
        with self.assertRaises(NotFoundError) as caught:
            self.title_of("page:No such page")
        self.assertIn("on this site", caught.exception.message)

    def test_an_empty_reference_is_explained(self):
        with self.assertRaises(ValidationError):
            self.title_of("page:")

    def test_ids_and_addresses_work_as_before(self):
        self.assertEqual(self.app.view_page.execute("2003", with_body=False).page.title, "Architecture")
        self.assertEqual(self.app.view_page.execute("https://example.atlassian.net/wiki/spaces/ENG/pages/2003/Architecture", with_body=False).page.title, "Architecture")
        with self.assertRaises(ValidationError):
            self.app.view_page.execute("Architecture", with_body=False)


class ExportPathTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.files = MemoryFiles()
        self.app = app_with(self.gateway, self.files)

    def test_every_page_says_where_it_lives_in_its_front_matter_and_in_the_index(self):
        result = self.app.export_pages.execute(out_dir="out", space="ENG")
        paths = {page.id: page.path for page in result.pages}
        self.assertEqual(paths, {"2001": "", "2002": "Engineering Home", "2003": "Engineering Home", "2004": "Engineering Home > Architecture", "2005": "Engineering Home"})
        adr = self.files.files["out/adr-0001-2004.md"].decode("utf-8")
        self.assertIn("\npath: Engineering Home > Architecture\n", adr)
        self.assertNotIn("\npath:", self.files.files["out/engineering-home-2001.md"].decode("utf-8"))  # the root has none
        index = json.loads(self.files.files["out/index.json"].decode("utf-8"))
        self.assertEqual({page["id"]: page["path"] for page in index["pages"]}["2004"], "Engineering Home > Architecture")

    def test_a_tree_export_starts_its_paths_above_the_first_page(self):
        result = self.app.export_pages.execute(out_dir="out", root="2003")
        self.assertEqual({page.id: page.path for page in result.pages}, {"2003": "Engineering Home", "2004": "Engineering Home > Architecture"})

    def test_a_title_with_an_address_is_redacted_in_the_path(self):
        self.gateway.pages["2003"].title = "Mail alex@example.com"
        result = self.app.export_pages.execute(out_dir="out", space="ENG")
        self.assertEqual({page.id: page.path for page in result.pages}["2004"], "Engineering Home > Mail [email]")
        self.assertNotIn("alex@example.com", b"".join(self.files.files.values()).decode("utf-8"))

    def test_an_import_ignores_the_path_line(self):
        self.app.export_pages.execute(out_dir="out", space="ENG")
        before = len(self.gateway.called("update_page"))
        outcome = self.app.import_markdown.execute("out/adr-0001-2004.md")
        self.assertEqual(outcome.action, "unchanged")
        self.assertEqual(len(self.gateway.called("update_page")), before)


if __name__ == "__main__":
    unittest.main()
