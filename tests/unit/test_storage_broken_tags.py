"""Storage format that nobody has checked: a body made of start tags that are never closed is read in a moment, and nothing that is well formed changes."""
import time
import unittest

from conflu_c_cli.application.rendering import render_body
from conflu_c_cli.domain.storage import _neutralize, storage_to_markdown, storage_to_text

CODE = (
    '<ac:structured-macro ac:name="code" ac:schema-version="1"><ac:parameter ac:name="language">c</ac:parameter>'
    "<ac:plain-text-body><![CDATA[for (i=0;i<n;i++) { if (a <b && c) x = '<tag'; }]]></ac:plain-text-body></ac:structured-macro>"
)
WELL_FORMED = (
    '<h1>Title</h1><p>Contact <ac:link><ri:user ri:account-id="x" /></ac:link> a &lt; b &amp; c, 1 < 2, x<3</p><ul><li>One</li><li>Two</li></ul>'
    "<!-- a note <x with a tag --><p><at:var at:name=\"title\" /> and <strong>bold</strong></p>" + CODE
)


class NeutralizeTest(unittest.TestCase):
    def test_what_is_well_formed_is_not_touched(self):
        for text in (WELL_FORMED, CODE, "", "no tags at all", "<p>one</p>", "<br/><hr />", "a < b > c", "<![CDATA[x<y]]>", "<?xml version='1.0'?><p>x</p>", "</p></p>", '<a title="a>b">x</a>'):
            with self.subTest(text=text[:40]):
                self.assertEqual(_neutralize(text), text)

    def test_a_start_tag_that_is_never_closed_is_the_text_that_it_is(self):
        self.assertEqual(_neutralize("<p>abc <str"), "<p>abc &lt;str")
        self.assertEqual(_neutralize("<p <a <b>x</b>"), "&lt;p &lt;a <b>x</b>")
        self.assertEqual(_neutralize("<at:var at:name='x"), "&lt;at:var at:name='x")
        self.assertEqual(_neutralize("<p>a<b</p>"), "<p>a&lt;b</p>")

    def test_a_cdata_section_is_left_alone_and_one_that_never_ends_is_text(self):
        self.assertEqual(_neutralize("<p <![CDATA[a <b c]]> <q"), "&lt;p <![CDATA[a <b c]]> &lt;q")
        self.assertEqual(_neutralize("<![CDATA[never <p ends"), "&lt;![CDATA[never &lt;p ends")
        self.assertEqual(_neutralize("<p>x</p><![CDATA[a]]><![CDATA[b <c]]><d"), "<p>x</p><![CDATA[a]]><![CDATA[b <c]]>&lt;d")

    def test_it_costs_a_moment_whatever_the_input(self):
        started = time.perf_counter()
        for text in ("<p " * 200_000, "<p <a <b <c " * 50_000, "<![CDATA[" * 100_000, "<![CDATA[" + "<p " * 100_000, "]]>" * 100_000, '<ri:user ri:account-id="' * 50_000, "<" * 500_000):
            _neutralize(text)
        self.assertLess(time.perf_counter() - started, 5)


class ConversionTest(unittest.TestCase):
    def test_code_keeps_every_character_of_it(self):
        text = storage_to_markdown(CODE).text
        self.assertIn("for (i=0;i<n;i++) { if (a <b && c) x = '<tag'; }", text)
        self.assertNotIn("&lt;", text)
        self.assertIn("for (i=0;i<n;i++)", storage_to_text(CODE))

    def test_a_well_formed_body_converts_as_it_did(self):
        text = storage_to_markdown(WELL_FORMED).text
        self.assertIn("# Title", text)
        self.assertIn("a < b & c", text.replace("\\", ""))
        self.assertIn("- One", text)
        self.assertIn("**bold**", text)

    def test_a_body_that_is_cut_off_inside_a_tag_ends_with_what_it_had(self):
        self.assertIn("abc", storage_to_markdown("<p>abc <str").text)
        self.assertIn("abc", storage_to_text("<p>abc <ac:link ac:anch"))

    def test_bodies_made_of_tags_that_never_end_are_read_in_a_moment_and_say_what_they_hold(self):
        started = time.perf_counter()
        for unit in ("<p ", "<p <a <b <c ", '<ri:user ri:account-id="', "<at:var ", "<p a='", '<p a="'):
            body = unit * 50_000
            for convert in (lambda value: storage_to_markdown(value).text, storage_to_text, lambda value: render_body(value, "markdown", with_users=False).text):
                with self.subTest(unit=unit):
                    text = convert(body)
                    self.assertGreater(len(text), 1000)  # the text is there; it is only no markup
        self.assertLess(time.perf_counter() - started, 20)

    def test_the_words_around_tags_that_never_end_are_kept(self):
        text = storage_to_markdown("<p>Start</p><p " * 3 + "<p>End</p>").text
        self.assertIn("Start", text)
        self.assertIn("End", text)


if __name__ == "__main__":
    unittest.main()
