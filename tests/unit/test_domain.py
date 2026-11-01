"""The domain: plain rules and data, no I/O."""
import unittest
from datetime import timezone

from conflu_c_cli.domain import cql, drafts, frontmatter, naming, payloads, privacy, timeutil, tree
from conflu_c_cli.domain.searchterms import parse_terms
from conflu_c_cli.domain.errors import (
    EXIT_CODES,
    AuthError,
    ConfigError,
    ConfluCliError,
    ConflictError,
    NotFoundError,
    RejectedError,
    UnavailableError,
    UsageError,
    ValidationError,
)
from conflu_c_cli.domain.model import (
    Comment,
    Page,
    PageRef,
    SearchHit,
    TreeNode,
    User,
    VersionInfo,
    is_attachment_id,
    parse_page_id,
    parse_space_key,
    space_key_from_link,
)

ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"


class ErrorsTest(unittest.TestCase):
    def test_every_error_carries_its_exit_code_and_code(self):
        expected = {
            ConfluCliError: (1, "ERROR"),
            ConfigError: (1, "CONFIG"),
            ValidationError: (1, "INVALID"),
            UsageError: (2, "USAGE"),
            ConflictError: (3, "CONFLICT"),
            NotFoundError: (4, "NOT_FOUND"),
            AuthError: (5, "AUTH"),
            RejectedError: (6, "REJECTED"),
            UnavailableError: (7, "UNAVAILABLE"),
        }
        for error_class, (exit_code, code) in expected.items():
            with self.subTest(error=error_class.__name__):
                error = error_class("message", hint="hint", details={"a": 1})
                self.assertEqual((error.exit_code, error.code, error.message, error.hint, error.details), (exit_code, code, "message", "hint", {"a": 1}))

    def test_the_exit_code_table_names_every_error_code(self):
        named = {name.strip() for _, names, _ in EXIT_CODES for name in names.split(",")}
        for error_class in (ConfigError, ValidationError, UsageError, ConflictError, NotFoundError, AuthError, RejectedError, UnavailableError):
            self.assertIn(error_class.code, named)
        self.assertEqual([code for code, _, _ in EXIT_CODES], list(range(8)))


class ParsingTest(unittest.TestCase):
    def test_a_page_id_is_a_number(self):
        self.assertEqual(parse_page_id(" 123456 "), "123456")

    def test_a_page_address_from_the_browser_gives_its_id(self):
        for text in (
            "https://example.atlassian.net/wiki/spaces/ENG/pages/123456/Release+notes",
            "https://example.atlassian.net/wiki/spaces/ENG/pages/123456",
            "https://example.atlassian.net/wiki/spaces/ENG/pages/123456/Release+notes?focusedCommentId=9#section",
            "https://example.atlassian.net/wiki/spaces/ENG/pages/edit-v2/123456",
            "https://example.atlassian.net/wiki/pages/viewpage.action?pageId=123456",
            "example.atlassian.net/wiki/spaces/~account/pages/123456/Title",
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_page_id(text), "123456")

    def test_what_is_not_a_page_is_refused_with_a_hint(self):
        for text in ("", "abc", "12 34", "-5", "https://example.atlassian.net/wiki/spaces/ENG/overview"):
            with self.subTest(text=text):
                with self.assertRaises(ValidationError) as caught:
                    parse_page_id(text)
                self.assertTrue(caught.exception.hint)

    def test_a_short_link_cannot_be_resolved_offline(self):
        with self.assertRaises(ValidationError) as caught:
            parse_page_id("https://example.atlassian.net/wiki/x/AbCdEf")
        self.assertIn("short link", caught.exception.message)

    def test_space_keys(self):
        for key in ("ENG", "eng", "A1", "~712020:abc-def", "My_Space.1"):
            self.assertEqual(parse_space_key(f" {key} "), key)
        for key in ("", " ", "-ENG", "E G", "ENG/", "a" * 256):
            with self.subTest(key=key):
                with self.assertRaises(ValidationError):
                    parse_space_key(key)

    def test_the_space_key_in_an_address(self):
        self.assertEqual(space_key_from_link("/spaces/ENG/pages/1/Title"), "ENG")
        self.assertEqual(space_key_from_link("/spaces/~abc123/pages/1"), "~abc123")
        self.assertEqual(space_key_from_link("/download/attachments/1/x.png"), "")

    def test_attachment_ids(self):
        self.assertTrue(is_attachment_id("att123"))
        self.assertTrue(is_attachment_id(" att1 "))
        for text in ("123", "att", "att12x", "Att1", "attachment1"):
            self.assertFalse(is_attachment_id(text))

    def test_page_properties_follow_the_current_version(self):
        page = Page("1", version=VersionInfo(4, "2026-10-10T09:00:00.000Z"), created="2026-10-01T08:00:00.000Z")
        self.assertEqual((page.version_number, page.updated), (4, "2026-10-10T09:00:00.000Z"))
        bare = Page("2", created="2026-10-01T08:00:00.000Z")
        self.assertEqual((bare.version_number, bare.updated), (0, "2026-10-01T08:00:00.000Z"))


class PrivacyTest(unittest.TestCase):
    def test_emails_and_personal_links_are_removed_from_text(self):
        text = "Write to alex@example.com or see https://example.atlassian.net/wiki/people/5b10ac8d82e05b22 and https://example.atlassian.net/wiki/spaces/~5b10/overview."
        cleaned = privacy.redact_text(text)
        self.assertNotIn("alex@example.com", cleaned)
        self.assertNotIn("people/5b10", cleaned)
        self.assertNotIn("spaces/~5b10", cleaned)
        self.assertIn("[email]", cleaned)
        self.assertEqual(cleaned.count("[personal link]"), 2)

    def test_a_profile_link_the_page_writes_as_a_path_is_removed_with_its_text(self):
        for link in ("/wiki/people/5b10ac8d", "/people/5b10ac8d", "/wiki/spaces/~5b10ac8d/overview", "https://example.atlassian.net/wiki/people/5b10ac8d"):
            with self.subTest(link=link):
                self.assertEqual(privacy.redact_text(f"[Alex Example]({link})"), "[personal link]")  # the text of the link is the name
                self.assertEqual(privacy.redact_text(f"Profile: {link} done"), "Profile: [personal link] done")
                self.assertEqual(privacy.redact_text(f"see ({link})"), "see ([personal link])")

    def test_a_path_that_is_not_a_profile_is_left_alone(self):
        for text in ("docs/people/roles.md", "src/spaces/~x", "/api/people/list", "../people/roles.md", "./people/roles.md", "a//people/x", "~/spaces/~x", "[Team](/wiki/spaces/ENG/overview)", "https://example.atlassian.net/wiki/spaces/ENG/pages/1"):
            with self.subTest(text=text):
                self.assertEqual(privacy.redact_text(text), text)

    def test_redaction_stays_fast_on_hostile_text(self):
        import time

        for hostile in ("[" * 100_000, "[a" * 50_000, "[a](" * 25_000, "/wiki/people/" * 10_000):
            started = time.perf_counter()
            privacy.redact_text(hostile)
            self.assertLess(time.perf_counter() - started, 2.0)

    def test_account_ids_of_mentions_are_blanked_in_storage_format(self):
        storage = f'<p><ac:link><ri:user ri:account-id="{ACCOUNT}" /></ac:link> and alex@example.com</p>'
        cleaned = privacy.redact_storage(storage)
        self.assertNotIn(ACCOUNT, cleaned)
        self.assertIn('ri:account-id="hidden"', cleaned)
        self.assertNotIn("alex@example.com", cleaned)
        self.assertTrue(privacy.mentions_people(storage))
        self.assertTrue(privacy.has_blanked_mentions(cleaned))
        self.assertFalse(privacy.has_blanked_mentions(storage))

    def test_user_objects_and_person_ids_are_replaced_in_raw_json(self):
        raw = {
            "authorId": ACCOUNT,
            "ownerId": ACCOUNT,
            "version": {"number": 2, "authorId": ACCOUNT},
            "by": {"accountId": ACCOUNT, "displayName": "Alex Example", "email": "alex@example.com"},
            "body": f'<ri:user ri:account-id="{ACCOUNT}" /> mail alex@example.com',
            "items": [{"accountId": ACCOUNT, "publicName": "Alex"}],
            "title": "Plain",
        }
        cleaned = privacy.strip_users(raw)
        text = str(cleaned)
        self.assertNotIn(ACCOUNT, text)
        self.assertNotIn("alex@example.com", text)
        self.assertNotIn("Alex", text)
        self.assertEqual(cleaned["by"], {"hidden": True})
        self.assertEqual(cleaned["version"]["number"], 2)
        self.assertEqual(cleaned["title"], "Plain")

    def test_a_page_without_people(self):
        page = Page(
            "1",
            title="Mail alex@example.com",
            author=User(ACCOUNT, "Alex"),
            owner=User(ACCOUNT),
            version=VersionInfo(2, "t", "ask alex@example.com", False, User(ACCOUNT)),
            body=f'<ri:user ri:account-id="{ACCOUNT}" />',
            ancestors=[PageRef("0", "Home alex@example.com")],
            comments=[Comment("9", body="<p>alex@example.com</p>", author=User(ACCOUNT))],
            raw={"authorId": ACCOUNT},
        )
        hidden = privacy.hide_users(page)
        self.assertIsNone(hidden.author)
        self.assertIsNone(hidden.owner)
        self.assertIsNone(hidden.version.author)
        self.assertIsNone(hidden.raw)
        self.assertIsNone(hidden.comments[0].author)
        self.assertNotIn("alex@example.com", repr(hidden))
        self.assertNotIn(ACCOUNT, repr(hidden))
        self.assertEqual(page.author.account_id, ACCOUNT)  # the original is untouched

    def test_search_hits_lose_emails(self):
        hit = privacy.hide_hit(SearchHit("1", "page", "alex@example.com", excerpt="mail alex@example.com"))
        self.assertNotIn("@", hit.title + hit.excerpt)

    def test_a_search_excerpt_is_left_out_because_it_can_hold_the_name_of_a_mentioned_person(self):
        hit = privacy.hide_hit(SearchHit("1", "page", "Notes", excerpt="Team: Jane Example (project lead), John Example"))
        self.assertEqual((hit.title, hit.excerpt), ("Notes", ""))

    def test_newlines_are_normalised(self):
        self.assertEqual(privacy.normalize_newlines("a\r\nb\rc"), "a\nb\nc")


class FrontMatterTest(unittest.TestCase):
    def test_front_matter_and_body(self):
        page = frontmatter.parse_markdown_page("---\ntitle: Release notes\nspace: ENG\nlabels: a, b\n---\n# Heading\n\nBody\n")
        self.assertEqual(page.meta, {"title": "Release notes", "space": "ENG", "labels": "a, b"})
        self.assertEqual(page.body, "# Heading\n\nBody\n")
        self.assertEqual(page.title, "Release notes")

    def test_a_file_without_front_matter_is_all_page(self):
        page = frontmatter.parse_markdown_page("# Just text\n")
        self.assertEqual((page.meta, page.body), ({}, "# Just text\n"))

    def test_keys_are_normalised_and_aliased(self):
        page = frontmatter.parse_markdown_page("---\nPage-ID: 12\nspace_key: ENG\nparent_id: 7\nlabel: x\nTitle: T\n---\n")
        self.assertEqual(page.meta, {"page_id": "12", "space": "ENG", "parent": "7", "labels": "x", "title": "T"})

    def test_quotes_are_removed_in_pairs_only(self):
        page = frontmatter.parse_markdown_page("---\na: \"x y\"\nb: 'it'\nc: \"open\nd: Fix: the \"thing\"\ne:\n---\n")
        self.assertEqual(page.meta["a"], "x y")
        self.assertEqual(page.meta["b"], "it")
        self.assertEqual(page.meta["c"], '"open')
        self.assertEqual(page.meta["d"], 'Fix: the "thing"')
        self.assertEqual(page.meta["e"], "")

    def test_comments_blank_lines_crlf_and_bom_are_tolerated(self):
        page = frontmatter.parse_markdown_page("\ufeff---\r\n# a comment\r\n\r\ntitle: T\r\n---\r\nBody\r\n")
        self.assertEqual((page.meta, page.body), ({"title": "T"}, "Body\n"))

    def test_empty_and_unterminated_front_matter(self):
        self.assertEqual(frontmatter.parse_markdown_page("---\n---\nBody").meta, {})
        self.assertEqual(frontmatter.parse_markdown_page("---\ntitle: T\n---").body, "")
        with self.assertRaises(ValidationError) as caught:
            frontmatter.parse_markdown_page("---\ntitle: T\nBody")
        self.assertIn("closing ---", caught.exception.message)

    def test_a_line_that_is_not_key_value_is_explained(self):
        for text in ("---\n- item\n---\n", "---\nlabels:\n  - a\n---\n", "---\n1bad: x\n---\n"):
            with self.subTest(text=text):
                with self.assertRaises(ValidationError) as caught:
                    frontmatter.parse_markdown_page(text)
                self.assertIn("key: value", caught.exception.hint)

    def test_lists_are_comma_separated_and_deduplicated(self):
        self.assertEqual(frontmatter.split_list(" a, b ,,a,c "), ["a", "b", "c"])
        self.assertEqual(frontmatter.split_list(""), [])

    def test_the_title_comes_from_a_first_heading(self):
        self.assertEqual(frontmatter.take_title_heading("# My page\n\nText\n"), ("My page", "Text\n"))
        self.assertEqual(frontmatter.take_title_heading("\n\n# Title ##\nText"), ("Title", "Text"))
        self.assertEqual(frontmatter.take_title_heading("# C#\nText"), ("C#", "Text"))
        self.assertEqual(frontmatter.take_title_heading("## Sub\nText"), ("", "## Sub\nText"))
        self.assertEqual(frontmatter.take_title_heading("Text\n# Later"), ("", "Text\n# Later"))
        self.assertEqual(frontmatter.take_title_heading("```\n# code\n```"), ("", "```\n# code\n```"))

    def test_rendered_front_matter_is_read_back(self):
        meta = {"title": '"Quoted"', "page_id": "12", "space": "ENG", "parent": "", "note": "two\nlines  here"}
        text = frontmatter.render_front_matter(meta)
        self.assertNotIn("parent", text)
        parsed = frontmatter.parse_markdown_page(text + "\nBody\n")
        self.assertEqual(parsed.meta["title"], '"Quoted"')
        self.assertEqual(parsed.meta["note"], "two lines  here")  # the line break is one space; the two spaces stay
        self.assertEqual(parsed.body, "Body\n")

    def test_a_title_comes_back_exactly_as_it_was_written(self):
        for title in ("Guide -  Setup & Options (advanced)", "a   b", "Non\u00a0breaking", "Colon: and #hash", "It's \"quoted\"", "  trimmed at the ends  "):
            with self.subTest(title=title):
                parsed = frontmatter.parse_markdown_page(frontmatter.render_front_matter({"title": title.strip(), "page_id": "1"}) + "\nBody\n")
                self.assertEqual(parsed.meta["title"], title.strip())

    def test_the_redaction_markers_are_recognised(self):
        self.assertTrue(privacy.has_redaction_marker(privacy.redact_text("Notes for alex@example.com")))
        self.assertTrue(privacy.has_redaction_marker("see [personal link] now"))
        self.assertFalse(privacy.has_redaction_marker("Notes [draft] and e-mail"))


class PayloadsTest(unittest.TestCase):
    def test_create_page(self):
        self.assertEqual(
            payloads.create_page_payload("1001", "T", "<p>x</p>", "2001"),
            {"spaceId": "1001", "status": "current", "title": "T", "parentId": "2001", "body": {"representation": "storage", "value": "<p>x</p>"}},
        )
        self.assertNotIn("parentId", payloads.create_page_payload("1001", "T", ""))

    def test_update_page(self):
        payload = payloads.update_page_payload("5", "T", "<p>x</p>", 4, " why ")
        self.assertEqual(payload["version"], {"number": 4, "message": "why"})
        self.assertEqual((payload["id"], payload["status"]), ("5", "current"))
        self.assertNotIn("message", payloads.update_page_payload("5", "T", "", 2)["version"])
        self.assertEqual(payloads.update_page_payload("5", "T", "", 2, status="draft")["status"], "draft")

    def test_title_comment_and_labels(self):
        self.assertEqual(payloads.title_payload("T"), {"status": "current", "title": "T"})
        self.assertEqual(payloads.comment_payload("5", "<p>x</p>", "9"), {"parentCommentId": "9", "body": {"representation": "storage", "value": "<p>x</p>"}})
        self.assertEqual(payloads.comment_payload("5", "x"), {"pageId": "5", "body": {"representation": "storage", "value": "x"}})
        self.assertNotIn("pageId", payloads.comment_payload("5", "x", "9"))  # the document: do not provide the page if creating a reply
        self.assertEqual(payloads.label_payload(["a", "b"]), [{"prefix": "global", "name": "a"}, {"prefix": "global", "name": "b"}])


class CqlTest(unittest.TestCase):
    def test_quoting_escapes_the_quote_and_the_backslash(self):
        self.assertEqual(cql.quote('a "b" \\c'), '"a \\"b\\" \\\\c"')
        self.assertEqual(cql.quote("line\nbreak"), '"line break"')

    def test_a_text_search(self):
        self.assertEqual(cql.content_search(text="data quality"), 'type = page AND text ~ "data quality"')

    def test_filters_are_anded_and_a_search_without_text_is_ordered(self):
        query = cql.content_search(space="ENG", label="adr", title="ADR", under="2003", since="2026-10-01")
        self.assertEqual(
            query,
            'type = page AND space = "ENG" AND title ~ "ADR" AND label = "adr" AND ancestor = 2003 AND lastmodified >= "2026-10-01" ORDER BY lastmodified DESC',
        )

    def test_any_type_and_other_types(self):
        self.assertEqual(cql.content_search(text="x", content_type="any"), 'text ~ "x"')
        self.assertEqual(cql.content_search(text="x", content_type="blogpost"), 'type = blogpost AND text ~ "x"')

    def test_a_query_written_by_hand_is_used_as_it_is(self):
        self.assertEqual(cql.content_search(cql=' type = page AND creator = currentUser() ', text="ignored"), "type = page AND creator = currentUser()")

    def test_bad_input_is_refused(self):
        for options in (
            {}, {"content_type": "page"}, {"text": "x", "since": "yesterday"}, {"text": "x", "under": "abc"}, {"text": "x", "content_type": "space"},
            {"text": "x", "under": "\u00b2"}, {"text": "x", "under": "\u0661\u0662\u0663"},  # digits of other scripts are not ids
            {"text": "x", "since": "2026-10-01\n"}, {"text": "x", "since": "\u0662\u0660\u0662\u0666-10-01"},
        ):
            with self.subTest(options=options):
                with self.assertRaises(ValidationError):
                    cql.content_search(**options)

    def test_a_value_cannot_break_out_of_its_quotes(self):
        query = cql.content_search(text='x" OR space = "SECRET')
        self.assertEqual(query, 'type = page AND text ~ "x space SECRET"')  # the quotes are punctuation, `OR` is no word to look for
        for hostile in ('a\\" OR space = \\"SECRET', '"unterminated', 'x\\', '")) OR (type = page', '\x00\x1b[2J'):
            with self.subTest(hostile=hostile):
                query = cql.content_search(text=hostile, space="ENG")
                body = query.split(' AND text ~ ', 1)[1]
                self.assertRegex(body, r'^"(?:[^"\\]|\\.)*"$')  # one string, in which every quote and backslash is escaped

    def test_words_and_phrases_become_clauses(self):
        words = parse_terms('"SSO group" QA roles').used
        self.assertEqual(cql.text_clause(words), 'text ~ "QA roles" AND text ~ "\\"SSO group\\""')
        self.assertEqual(cql.text_clause(words, "any"), '(text ~ "\\"SSO group\\"" OR text ~ "QA" OR text ~ "roles")')
        self.assertEqual(cql.text_clause(parse_terms("alpha").used, "any"), 'text ~ "alpha"')  # one term needs no group
        self.assertEqual(cql.text_clause(()), "")
        with self.assertRaises(ValidationError):
            cql.text_clause(words, "some")

    def test_a_search_for_any_word_and_a_search_by_filters_only(self):
        self.assertEqual(cql.content_search(text="alpha beta", match="any", space="ENG"), 'type = page AND space = "ENG" AND (text ~ "alpha" OR text ~ "beta")')
        self.assertEqual(cql.content_search(label="adr"), 'type = page AND label = "adr" ORDER BY lastmodified DESC')
        self.assertEqual(cql.content_search(text="?!", label="adr"), 'type = page AND label = "adr" ORDER BY lastmodified DESC')  # no word is left
        parsed = parse_terms("alpha beta")
        self.assertEqual(cql.content_search(terms=parsed, text="ignored"), 'type = page AND text ~ "alpha beta"')  # the parsed terms win


class TimeTest(unittest.TestCase):
    def test_timestamps_in_the_shapes_confluence_and_people_use(self):
        for text in ("2026-10-15T08:07:04Z", "2026-10-15T08:07:04.123Z", "2026-10-15T08:07:04.123456+00:00", "2026-10-15T10:07:04+0200", "2026-10-15T08:07:04"):
            with self.subTest(text=text):
                moment = timeutil.parse_timestamp(text).astimezone(timezone.utc)
                self.assertEqual((moment.hour, moment.minute), (8, 7))
        with self.assertRaises(ValidationError):
            timeutil.parse_timestamp("yesterday")

    def test_a_page_changed_after_the_given_time_is_a_conflict(self):
        timeutil.ensure_unchanged_since("5", "2026-10-10T09:00:00.000Z", "2026-10-10T09:00:00Z")
        timeutil.ensure_unchanged_since("5", "2026-10-10T09:00:00.000Z", "2026-10-11T00:00:00Z")
        with self.assertRaises(ConflictError) as caught:
            timeutil.ensure_unchanged_since("5", "2026-10-10T09:00:00.000Z", "2026-10-09T00:00:00Z")
        self.assertEqual(caught.exception.exit_code, 3)
        self.assertEqual(caught.exception.details["pageId"], "5")

    def test_the_version_guard(self):
        timeutil.ensure_version("5", 3, 3)
        with self.assertRaises(ConflictError) as caught:
            timeutil.ensure_version("5", 4, 3)
        self.assertEqual(caught.exception.details, {"pageId": "5", "version": 4, "expected": 3})


class TreeTest(unittest.TestCase):
    def test_depth_first_in_position_order(self):
        nodes = [
            TreeNode("3", "C", parent_id="1", depth=1, position=2),
            TreeNode("4", "A1", parent_id="2", depth=2, position=0),
            TreeNode("2", "A", parent_id="1", depth=1, position=0),
            TreeNode("5", "B", parent_id="1", depth=1, position=1),
            TreeNode("6", "B1", parent_id="5", depth=2, position=0),
        ]
        self.assertEqual([node.id for node in tree.arrange(nodes, "1")], ["2", "4", "5", "6", "3"])

    def test_siblings_without_position_are_sorted_by_title(self):
        nodes = [TreeNode("3", "b", parent_id="1"), TreeNode("2", "A", parent_id="1")]
        self.assertEqual([node.id for node in tree.arrange(nodes, "1")], ["2", "3"])

    def test_nodes_whose_parent_is_missing_come_last(self):
        nodes = [TreeNode("9", "Lost", parent_id="77", depth=3), TreeNode("2", "A", parent_id="1")]
        self.assertEqual([node.id for node in tree.arrange(nodes, "1")], ["2", "9"])

    def test_a_cycle_does_not_loop(self):
        nodes = [TreeNode("2", "A", parent_id="3"), TreeNode("3", "B", parent_id="2")]
        self.assertEqual(sorted(node.id for node in tree.arrange(nodes, "1")), ["2", "3"])


class NamingTest(unittest.TestCase):
    def test_slugs(self):
        self.assertEqual(naming.slugify("Release notes 2026.10"), "release-notes-2026-10")
        self.assertEqual(naming.slugify("Größe & Überblick"), "groe-uberblick")
        self.assertEqual(naming.slugify("日本語"), "page")
        self.assertEqual(len(naming.slugify("x" * 200)), 60)

    def test_export_names_hold_the_id(self):
        self.assertEqual(naming.export_file_name("Release notes", "2002"), "release-notes-2002.md")
        self.assertEqual(naming.export_file_name("Release notes", "2002", ".xml"), "release-notes-2002.xml")
        self.assertNotEqual(naming.export_file_name("Same", "1"), naming.export_file_name("Same", "2"))

    def test_safe_file_names(self):
        self.assertEqual(naming.safe_file_name("report.pdf"), "report.pdf")
        self.assertEqual(naming.safe_file_name("a:b*c?.txt"), "a_b_c_.txt")
        self.assertEqual(naming.safe_file_name("../../etc/passwd"), "passwd")
        self.assertEqual(naming.safe_file_name("C:\\Windows\\win.ini"), "win.ini")
        self.assertEqual(naming.safe_file_name("nul.txt"), "_nul.txt")
        self.assertEqual(naming.safe_file_name("trailing. "), "trailing")
        self.assertEqual(naming.safe_file_name("invoice\u202etxt.exe"), "invoice_txt.exe")  # right-to-left override
        self.assertEqual(naming.safe_file_name("a\u200bb.txt"), "a_b.txt")  # zero-width space
        self.assertEqual(naming.safe_file_name("a\x7fb\x85c.txt"), "a_b_c.txt")
        for name in ("", "..", ".", "dir/", "   "):
            with self.subTest(name=name):
                with self.assertRaises(ValidationError):
                    naming.safe_file_name(name)


class DraftsTest(unittest.TestCase):
    def test_titles(self):
        self.assertEqual(drafts.validate_title("  Release notes "), "Release notes")
        for title in ("", "   ", "a\nb", "x" * 256):
            with self.subTest(title=title[:10]):
                with self.assertRaises(ValidationError):
                    drafts.validate_title(title)

    def test_labels_are_lower_cased_unique_and_checked(self):
        self.assertEqual(drafts.normalize_labels(["ADR", " adr ", "Release-Notes", "", "a_b.c"]), ["adr", "release-notes", "a_b.c"])
        for bad in ("two words", "a,b", "x/y", "a:b", "<b>", "q?"):
            with self.subTest(label=bad):
                with self.assertRaises(ValidationError):
                    drafts.normalize_labels([bad])

    def test_bodies_are_combined(self):
        self.assertEqual(drafts.combine_body("<p>old</p>", "<p>new</p>", "replace"), "<p>new</p>")
        self.assertEqual(drafts.combine_body("<p>old</p>", "<p>new</p>", "append"), "<p>old</p>\n<p>new</p>")
        self.assertEqual(drafts.combine_body("<p>old</p>", "<p>new</p>", "prepend"), "<p>new</p>\n<p>old</p>")
        self.assertEqual(drafts.combine_body("  ", "<p>new</p>", "append"), "<p>new</p>")
        with self.assertRaises(ValidationError):
            drafts.combine_body("", "", "sideways")

    def test_changes_know_when_they_are_empty(self):
        self.assertTrue(drafts.PageChanges().is_empty())
        self.assertFalse(drafts.PageChanges(title="T").is_empty())
        self.assertFalse(drafts.PageChanges(body="").is_empty())

    def test_json_objects(self):
        self.assertEqual(drafts.parse_json_object('{"a": 1}'), {"a": 1})
        for text in ("[1]", "nope", ""):
            with self.assertRaises(ValidationError):
                drafts.parse_json_object(text, "--data")


if __name__ == "__main__":
    unittest.main()
