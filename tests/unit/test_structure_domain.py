"""Folders, whiteboards, databases and smart links as data: the names of the kinds, the rules for titles and addresses, the requests, the cells."""
import unittest

from conflu_c_cli.domain.content import (
    CONTAINER_NOUNS,
    CONTAINERS,
    CONTAINERS_SENTENCE,
    OTHER_CONTAINERS,
    describe,
    kind_named,
    noun_of,
    parse_content_id,
    point_at,
)
from conflu_c_cli.domain.drafts import validate_title as page_title
from conflu_c_cli.domain.errors import ValidationError
from conflu_c_cli.domain.model import Page, User, VersionInfo
from conflu_c_cli.domain.privacy import HIDDEN
from conflu_c_cli.domain.structure import (
    Container,
    FieldValue,
    folder_payload,
    hide_people,
    hide_people_in_payload,
    move_message,
    move_payload,
    shown_key,
    shown_value,
    smartlink_payload,
    validate_title,
    validate_url,
)

ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"
PERSONAL = f"~{ACCOUNT}"


class KindsTest(unittest.TestCase):
    def test_every_kind_has_the_words_a_message_needs(self):
        self.assertEqual([(kind.name, kind.noun, kind.command) for kind in CONTAINERS], [
            ("page", "page", "page"), ("folder", "folder", "folder"), ("whiteboard", "whiteboard", "whiteboard"), ("database", "database", "database"), ("embed", "smart link", "smartlink"),
        ])
        self.assertEqual([kind.name for kind in OTHER_CONTAINERS], ["folder", "whiteboard", "database", "embed"])
        self.assertEqual(kind_named("blogpost").command, "blogpost")
        self.assertEqual(CONTAINERS_SENTENCE, "a page, a folder, a whiteboard, a database or a smart link")
        self.assertEqual(CONTAINER_NOUNS, "page, folder, whiteboard, database or smart link")

    def test_a_noun_is_the_kind_without_its_article(self):
        self.assertEqual((noun_of("embed"), noun_of("folder"), noun_of("footer-comment")), ("smart link", "folder", "footer-comment"))
        self.assertEqual(describe("embed"), "a smart link")

    def test_a_message_points_at_content_by_kind_title_and_id(self):
        self.assertEqual(point_at("folder", "7001", "Guides"), "the folder 'Guides' [7001]")
        self.assertEqual(point_at("embed", "7061"), "the smart link [7061]")
        self.assertEqual(point_at("page", "2003", "Two\nlines   and\ttabs"), "the page 'Two lines and tabs' [2003]")
        shown = point_at("folder", "7001", "x" * 200)
        self.assertEqual(len(shown), len("the folder '' [7001]") + 60)
        self.assertIn("...'", shown)

    def test_an_attachment_is_named_for_what_it_is(self):
        with self.assertRaises(ValidationError) as caught:
            parse_content_id("att5001")
        self.assertEqual(caught.exception.message, "att5001 is an attachment, not a page, folder, whiteboard, database or smart link.")
        self.assertIn("conflu attachments PAGE", caught.exception.hint)
        for text in ("att", "att5001x", "xatt5001", "ATT5001"):
            with self.subTest(text=text), self.assertRaises(ValidationError) as caught:
                parse_content_id(text)
            self.assertNotIn("is an attachment", caught.exception.message)

    def test_ids_that_are_none_are_refused(self):
        for text in ("../x", "7001/../x", "1" * 20, "12\x00", "12\n34", "٣٤٥", "7001;DROP", "-1", "0x10", "7 001", "https://example.com/wiki/folder/abc"):
            with self.subTest(text=text), self.assertRaises(ValidationError):
                parse_content_id(text)
        self.assertEqual(parse_content_id("9" * 19), "9" * 19)  # the longest number that an id is
        self.assertEqual(parse_content_id("https://example.com/wiki/spaces/ENG/folder/7001/x?y=1"), "7001")


class TitleTest(unittest.TestCase):
    def test_a_title_follows_the_rules_of_a_page_title(self):
        for title in ("Guides", "  padded  ", "", "   ", "a\nb", "a\x00b", "a\tb", "x" * 255, "x" * 256, "ünïcode Ümlauts", "\u200bzero"):
            with self.subTest(title=title):
                try:
                    expected = page_title(title)
                except ValidationError:
                    with self.assertRaises(ValidationError):
                        validate_title(title, "folder")
                else:
                    self.assertEqual(validate_title(title, "folder"), expected)

    def test_the_message_names_what_is_made(self):
        with self.assertRaises(ValidationError) as caught:
            validate_title(" ", "smart link")
        self.assertEqual(caught.exception.message, "The smart link title is empty.")
        with self.assertRaises(ValidationError) as caught:
            validate_title("x" * 300, "folder")
        self.assertIn("The folder title is longer than 255 characters (300)", caught.exception.message)


class UrlTest(unittest.TestCase):
    def test_what_a_smart_link_may_show(self):
        for url in (
            "https://example.com/roadmap",
            "http://example.com",
            "HTTPS://Example.COM/Path",
            "https://example.com:8443/a?b=c&d=e#frag",
            "https://[2001:db8::1]:8080/x",
            "https://example.com/a%20b",
            "https://bücher.example/straße",
            "https://" + "a" * 60 + ".example/" + "p" * 1900,
        ):
            with self.subTest(url=url[:50]):
                self.assertEqual(validate_url(url), url)

    def test_the_address_is_returned_as_given_apart_from_blanks_around_it(self):
        self.assertEqual(validate_url("  https://example.com/x \n"), "https://example.com/x")

    def test_what_is_refused(self):
        for url, why in (
            ("", "empty"),
            ("   ", "empty"),
            ("https://example.com/" + "a" * 2048, "longer than 2048"),
            ("ftp://example.com/x", "not an http or https"),
            ("example.com/x", "not an http or https"),
            ("javascript:alert(1)", "not an http or https"),
            ("//example.com/x", "not an http or https"),
            ("https://user@example.com/x", "user name or a password"),
            ("https://user:secret@example.com/x", "user name or a password"),
            ("https://@example.com/", "user name or a password"),
            ("https://example.com/a b", "blank"),
            ("https://example.com/a\tb", "blank"),
            ("https://example.com/a\x00b", "blank"),
            ("https://example.com/a\u202eb", "blank"),  # a right-to-left override
            ("https://example.com/a\u200bb", "blank"),  # a zero-width space
            ("https://example.com\\@evil.example/", "blank"),
            ("https://", "no valid host"),
            ("https:///path", "no valid host"),
            ("https://example.com:/x", "no valid host"),
            ("https://example.com:0/x", "no valid host"),
            ("https://example.com:70000/x", "no valid host"),
            ("https://exa[mple.com/x", "no valid host"),
        ):
            with self.subTest(url=url[:40]), self.assertRaises(ValidationError) as caught:
                validate_url(url)
            self.assertIn(why, caught.exception.message)
            self.assertNotIn("secret", caught.exception.message + caught.exception.hint)  # a password is not repeated


class PayloadTest(unittest.TestCase):
    def test_a_folder_and_a_smart_link_have_what_the_post_takes(self):
        self.assertEqual(folder_payload("1001", "Guides"), {"spaceId": "1001", "title": "Guides"})
        self.assertEqual(folder_payload("1001", "Guides", "2001"), {"spaceId": "1001", "title": "Guides", "parentId": "2001"})
        self.assertEqual(
            smartlink_payload("1001", "Roadmap", "https://example.com/x", "7001"),
            {"spaceId": "1001", "title": "Roadmap", "parentId": "7001", "embedUrl": "https://example.com/x"},
        )
        self.assertNotIn("parentId", smartlink_payload("1001", "Roadmap", "https://example.com/x"))

    def test_a_move_is_the_page_as_it_is_at_the_next_version_with_a_new_parent(self):
        page = Page("2005", "Plain page", "current", "1001", "ENG", "2001", "page", version=VersionInfo(4, "2026-10-10T09:00:00.000Z"), body="<p>Text &amp; more</p>")
        payload = move_payload(page, "7001", "Moved below Guides")
        self.assertEqual(
            payload,
            {
                "id": "2005",
                "status": "current",
                "title": "Plain page",
                "parentId": "7001",
                "body": {"representation": "storage", "value": "<p>Text &amp; more</p>"},
                "version": {"number": 5, "message": "Moved below Guides"},
            },
        )
        with self.assertRaises(ValueError):  # a page that was read without its body would be saved empty
            move_payload(Page("1", "T", "current", version=VersionInfo(1)), "7001", "m")
        self.assertEqual(move_payload(Page("1", "T", "current", version=VersionInfo(1), body=""), "7001", "m")["body"]["value"], "")  # an empty page stays empty

    def test_the_message_of_a_move_is_short_redacted_and_on_one_line(self):
        self.assertEqual(move_message("Guides"), "Moved below Guides")
        self.assertEqual(move_message("Guides of alex@example.com"), "Moved below Guides of [email]")
        self.assertEqual(move_message("Two\nlines"), "Moved below Two lines")
        self.assertEqual(move_message("x" * 100), "Moved below " + "x" * 57 + "...")
        self.assertEqual(move_message("   "), "Moved")

    def test_the_request_may_be_shown_without_the_people_in_it_and_the_original_stays_whole(self):
        body = '<p>Ask <ac:link><ri:user ri:account-id="5b10ac8d82e05b22cc7d4ef5" /></ac:link> or alex@example.com.</p>'
        payload = {"id": "1", "status": "current", "title": "Mail alex@example.com", "parentId": "7001", "body": {"representation": "storage", "value": body}, "version": {"number": 2}}
        shown = hide_people_in_payload(payload)
        self.assertEqual(shown["title"], "Mail [email]")
        self.assertEqual(shown["body"], {"representation": "storage", "value": '<p>Ask <ac:link><ri:user ri:account-id="hidden" /></ac:link> or [email].</p>'})
        self.assertEqual((shown["parentId"], shown["version"], shown["id"]), ("7001", {"number": 2}, "1"))
        self.assertEqual(payload["body"]["value"], body)  # the request itself is untouched
        self.assertEqual(hide_people_in_payload({"pageId": "1", "position": "append"}), {"pageId": "1", "position": "append"})
        self.assertEqual(hide_people_in_payload({"title": 5, "body": "x"}), {"title": 5, "body": "x"})


class CellTest(unittest.TestCase):
    def test_a_cell_that_is_empty_is_none(self):
        for kind in ("text", "select", "user", "hyperlink", "checkbox", "entryDetails"):
            self.assertIsNone(shown_value(FieldValue(kind), None))
            self.assertIsNone(shown_value(FieldValue(kind), {}))

    def test_text_and_links_are_redacted_without_people_and_untouched_with_them(self):
        text = FieldValue("text", "Mail alex@example.com or see https://example.atlassian.net/wiki/people/5b10ac8d82e05b22cc7d4ef5")
        self.assertEqual(shown_value(text, None), "Mail [email] or see [personal link]")
        self.assertIn("alex@example.com", shown_value(text, {}))
        link = FieldValue("hyperlink", [{"url": "https://example.atlassian.net/wiki/people/abc", "label": "alex@example.com"}])
        self.assertEqual(shown_value(link, None), [{"url": "[personal link]", "label": "[email]"}])
        self.assertEqual(shown_value(FieldValue("select", ["a@example.com", "Gold"]), None), ["[email]", "Gold"])

    def test_people_are_markers_one_each_or_named(self):
        owners = FieldValue("user", ["1", "2"])
        self.assertEqual(shown_value(owners, None), ["[hidden]", "[hidden]"])
        self.assertEqual(shown_value(FieldValue("user", []), None), [])
        named = shown_value(owners, {"1": User("1", "Alex Example", "alex@example.com")})
        self.assertEqual(named, [{"accountId": "1", "displayName": "Alex Example", "email": "alex@example.com"}, {"accountId": "2", "displayName": "", "email": ""}])

    def test_numbers_and_checkboxes_are_what_they_are(self):
        self.assertEqual(shown_value(FieldValue("number", "12.50"), None), "12.50")
        self.assertIs(shown_value(FieldValue("checkbox", False), None), False)
        self.assertEqual(shown_value(FieldValue("pageLink", ["2002"]), None), ["2002"])


class HidePeopleTest(unittest.TestCase):
    def test_a_container_loses_its_people_and_its_text_is_redacted(self):
        container = Container(
            "7061", "embed", "Mail alex@example.com", "current", "1001", "ENG", "7001", "folder", 3, "2026-10-01T08:00:00.000Z",
            VersionInfo(2, "2026-10-02T08:00:00.000Z", "by alex@example.com", False, User("5b10ac8d82e05b22cc7d4ef5")),
            User("5b10ac8d82e05b22cc7d4ef5"), User("5b10ac8d82e05b22cc7d4ef5"), "https://example.atlassian.net/wiki/spaces/ENG/embed/7061",
            "https://example.atlassian.net/wiki/people/5b10ac8d82e05b22cc7d4ef5", {"authorId": "5b10ac8d82e05b22cc7d4ef5"},
        )
        hidden = hide_people(container)
        self.assertEqual((hidden.title, hidden.embed_url, hidden.author, hidden.owner, hidden.raw), ("Mail [email]", "[personal link]", None, None, None))
        self.assertEqual((hidden.version.author, hidden.version.message, hidden.version.number), (None, "by [email]", 2))
        self.assertEqual((container.updated, container.version_number), ("2026-10-02T08:00:00.000Z", 2))
        self.assertEqual(Container("1", "folder", created="c").updated, "c")


class PersonalSpaceTest(unittest.TestCase):
    """A personal space is keyed by `~` and the account id of its owner: no key, no address of it may be shown to somebody who may not see people."""

    def test_the_key_of_a_personal_space_is_hidden_and_no_other_key_is(self):
        self.assertEqual(shown_key(PERSONAL), HIDDEN)
        self.assertEqual(shown_key("ENG", "personal"), HIDDEN)  # the type says it, whatever the key looks like
        self.assertEqual((shown_key("ENG"), shown_key("ENG", "global"), shown_key("")), ("ENG", "ENG", ""))

    def test_a_container_in_a_personal_space_has_no_key_and_no_account_id_in_its_address(self):
        container = Container("7095", "folder", "Archive", "current", "10000", PERSONAL, url=f"https://example.atlassian.net/wiki/spaces/{PERSONAL}/folder/7095")
        hidden = hide_people(container)
        self.assertEqual((hidden.space_key, hidden.url), (HIDDEN, f"https://example.atlassian.net/wiki/spaces/{HIDDEN}/folder/7095"))
        self.assertNotIn(ACCOUNT, repr(hidden))
        self.assertEqual((container.space_key, ACCOUNT in container.url), (PERSONAL, True))  # the container that was read is as it was

    def test_a_container_in_another_space_keeps_its_key_and_its_address(self):
        container = Container("7001", "folder", "Guides", "current", "1001", "ENG", url="https://example.atlassian.net/wiki/spaces/ENG/folder/7001")
        hidden = hide_people(container)
        self.assertEqual((hidden.space_key, hidden.url), ("ENG", "https://example.atlassian.net/wiki/spaces/ENG/folder/7001"))
        self.assertEqual(hide_people(Container("1", "folder")).url, "")


if __name__ == "__main__":
    unittest.main()
