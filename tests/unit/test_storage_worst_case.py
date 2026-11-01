"""The converter of storage format reads a body in a time that grows with its size, whatever it is made of, and says so when it cannot read one.

The shapes below are bodies that took seconds to minutes before: a run of blanks in code, a run of `&`, constructs that are never closed (and the code of a
section that Python's parser ends early), a table that is all padding. Each is long enough that the old code needed 5 s or more and the code now needs a few
hundredths of a second, and the limit is 3 s as in the neighbouring tests, so that a slow machine does not fail them.
"""
import random
import re
import time
import unittest
from unittest import mock

from conflu_c_cli.application.rendering import render_body, storage_from_input
from conflu_c_cli.domain import storage
from conflu_c_cli.domain.errors import UsageError, ValidationError
from conflu_c_cli.domain.payloads import create_page_payload, label_payload, update_page_payload
from conflu_c_cli.domain.storage import _cleanup, _escape_inline_markdown, _neutralize, _number, lossy_constructs, storage_to_markdown, storage_to_text

LIMIT_SECONDS = 3.0
MEGABYTE = 1_000_000


def seconds(call, *args) -> float:
    started = time.perf_counter()
    try:
        call(*args)
    except (UsageError, ValidationError):
        pass  # a body that is nested too deeply, or a text that is refused, is the right answer: the time is what is measured
    return time.perf_counter() - started


def code(body: str) -> str:
    return f'<ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA[{body}]]></ac:plain-text-body></ac:structured-macro>'


def old_cleanup(text: str) -> str:
    """`_cleanup` as it was: a pattern for the blanks before a line end, which takes the square of a run of blanks that no line end follows."""
    text = re.sub(r"[ \t]+\n", "\n", text)
    lines = text.strip().split("\n")
    cleaned: list[str] = []
    blank_run = 0
    fence = ""
    for line in lines:
        token = line.strip()
        if token.startswith("```"):
            fence = "" if fence else token[:3]
            blank_run = 0
            cleaned.append(line)
            continue
        if not token and not fence:
            blank_run += 1
            if blank_run <= 1:
                cleaned.append("")
            continue
        blank_run = 0
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def old_escape(text: str, in_table: bool = False) -> str:
    """`_escape_inline_markdown` as it was: a slice of the rest of the text for every `&`, which copies it again and again."""
    escaped = []
    index = 0
    while index < len(text):
        if text[index] == "&":
            match = re.match(r"&(?:#?[A-Za-z0-9]+);", text[index:])
            if match:
                escaped.append("\\&")
                escaped.append(match.group(0)[1:])
                index += len(match.group(0))
                continue
        char = text[index]
        if char in "\\`*_[]<>|" or (in_table and char == "|"):
            escaped.append("\\" + char)
        else:
            escaped.append(char)
        index += 1
    return "".join(escaped)


class CleanupTest(unittest.TestCase):
    def test_a_run_of_blanks_in_code_costs_a_moment(self):
        for label, body in (
            ("spaces in a pre", "<pre>" + " " * 80_000 + "x</pre>"),
            ("blanks of both kinds in a code macro", code(" \t" * 40_000 + "x")),
        ):
            for convert in (storage_to_markdown, storage_to_text):
                with self.subTest(body=label, convert=convert.__name__):
                    self.assertLess(seconds(convert, body), LIMIT_SECONDS)

    def test_the_blanks_at_the_end_of_a_line_still_go_and_nothing_else_does(self):
        self.assertEqual(_cleanup("a  \n\n\n  b \t\n"), "a\n\n  b")
        self.assertEqual(_cleanup("  \n x \n```\n  y  \n\n\n  z\t\n```\n\n\n\nw  "), "x\n```\n  y\n\n\n  z\n```\n\nw")
        self.assertEqual(storage_to_markdown("<pre>a   \n   b</pre>").text, "```\na\n   b\n```")

    def test_it_cleans_as_the_pattern_did(self):
        generator = random.Random(1)
        alphabet = " \t\n\fa`-\xa0"
        for _ in range(3000):
            text = "".join(generator.choice(alphabet) for _ in range(generator.randint(0, 30)))
            self.assertEqual(_cleanup(text), old_cleanup(text), repr(text))


class InlineEscapeTest(unittest.TestCase):
    def test_a_text_of_ampersands_is_read_once(self):
        for label, body in (("an ampersand and a blank", "& " * 500_000), ("an ampersand and a number sign", "&#" * 500_000)):
            with self.subTest(shape=label):
                self.assertLess(seconds(storage_to_markdown, "<p>" + body + "</p>"), LIMIT_SECONDS)

    def test_it_escapes_as_the_loop_did(self):
        generator = random.Random(2)
        alphabet = ["&", "a", "1", "#", ";", "x", "\\", "`", "*", "_", "[", "]", "<", ">", "|", " ", "\n", "&amp;", "&#x41;", "&lt;", "\u00e9", "\ud83d", "-"]
        for _ in range(3000):
            text = "".join(generator.choice(alphabet) for _ in range(generator.randint(0, 18)))
            for in_table in (False, True):
                self.assertEqual(_escape_inline_markdown(text, in_table=in_table), old_escape(text, in_table), repr(text))

    def test_a_character_reference_keeps_its_name_and_loses_the_first_character_to_a_backslash(self):
        self.assertEqual(storage_to_markdown("<p>a &amp; b &lt; c &#65; d & e &x; f</p>").text, "a & b \\< c A d & e \\&x; f")


class NeutralizeTest(unittest.TestCase):
    def test_a_construct_that_is_never_closed_is_the_text_that_it_is(self):
        cases = {
            "<!--": "&lt;!--",
            "<!-- x": "&lt;!-- x",
            "<!--x>": "&lt;!--x>",  # a `>` is no end of a comment
            "<!-->": "&lt;!-->",  # nor is the `-->` that shares its dashes with the opener
            "<!--->x-->": "&lt;!--->x-->",  # HTML5 ends `<!-->` and `<!--->` at once, so a parser may not read the rest as a comment
            "-->a<!--": "-->a&lt;!--",  # an end before the comment does not close it
            "<!-- a --> <!--": "<!-- a --> &lt;!--",
            "</p ": "&lt;/p ",
            "</p": "&lt;/p",
            "</p <b>x</b>": "&lt;/p <b>x</b>",
            "<?x ": "&lt;?x ",
            "<?x <b>": "&lt;?x <b>",
            "<!x ": "&lt;!x ",
            "<!DOCTYPE html": "&lt;!DOCTYPE html",
            "<![if x]>y<![endif]>": "&lt;![if x]>y&lt;![endif]>",  # no XML: the parser fails on some of it
            "<![foo[": "&lt;![foo[",
            "<![ ": "&lt;![ ",
            "<![[": "&lt;![[",
            "<![]]>": "&lt;![]]>",
            "<![x y[": "&lt;![x y[",
            "<![cdata[x]]>": "&lt;![cdata[x]]>",  # the name of a section is written in capitals
            "<![CDATA[a<![CDATA[b": "&lt;![CDATA[a&lt;![CDATA[b",  # none of two that never end is a section
            "<![CDATA[x]]><!--y": "<![CDATA[x]]>&lt;!--y",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(_neutralize(text), expected)

    def test_what_is_closed_is_not_touched(self):
        for text in (
            "<!-- a comment -->",
            "<!---->",
            "<!-- <b> inside, and <x too -->",
            "</p>",
            "</>",
            "<?xml version='1.0'?><p>x</p>",
            "<?x?>",
            "<!DOCTYPE html>",
            "<!x>",
            "<![CDATA[x]]>",
            "<![CDATA[x <y && z > w <a b]]>",
            "<p>a</p><!-- b --><![CDATA[c]]><p>d</p>",
            "a < b, 1 <2 and x<3 > y",
        ):
            with self.subTest(text=text):
                self.assertEqual(_neutralize(text), text)

    def test_the_inside_of_a_comment_and_of_a_section_is_not_looked_at(self):
        for text in ("<!-- a <![x[ <p <q -->", "<![CDATA[ a <!-- b <p ]]>", "<!-- <![CDATA[ x --> y ]]>", "<![CDATA[ <!-- ]]> c -->"):
            with self.subTest(text=text):
                self.assertEqual(_neutralize(text), text)

    def test_a_comment_that_a_parser_may_end_early_is_an_empty_comment(self):
        self.assertEqual(_neutralize("<p>a</p><!-- x -- > y --><p>b</p>"), "<p>a</p><!----><p>b</p>")
        self.assertEqual(_neutralize("a<!-- x --!> <p <q -->b"), "a<!---->b")
        self.assertEqual(_neutralize("<<!-- a -- > b -->?"), "<<!---->?")  # nothing that is left joins what stands around it into a tag
        self.assertEqual(storage_to_text("a<!-- x -- > y -->b"), "ab")

    def test_a_section_that_the_parser_would_end_early_is_the_text_that_it_holds(self):
        # `a[b[i]] > 3` has a `]` `]` and a `>` with a blank between: Python's parser ends the section there and reads the rest of the code as markup
        self.assertEqual(_neutralize("<![CDATA[a[b[i]] > 3 <x & y]]>"), "a[b[i]] > 3 &lt;x &amp; y")
        self.assertEqual(_neutralize("<p>1</p><![CDATA[ ] ] > <!--x> ]]><p>2</p>"), "<p>1</p> ] ] > &lt;!--x> <p>2</p>")
        self.assertEqual(_neutralize("<![CDATA[a]]>b<![CDATA[c] ]>d]]>"), "<![CDATA[a]]>bc] ]>d")
        self.assertEqual(_neutralize("<<![CDATA[x ]] > <p ]]>"), "&lt;x ]] > &lt;p ")  # a `<` in front of the code would make a tag of its first character
        macro = code("if (a[b[i]] > 3) { x <y; }")
        self.assertEqual(storage_to_markdown(macro).text, "```\nif (a[b[i]] > 3) { x <y; }\n```")
        self.assertEqual(storage_to_text(macro), "if (a[b[i]] > 3) { x <y; }")

    def test_it_is_the_same_again_when_it_is_done_twice(self):
        for text in (
            "<!--x>",
            "</p <b>x",
            "<![if x]>",
            "<![CDATA[a[b[i]] > 3 <x]]>",
            "<p <a <!-- <![x[ </ <? <!",
            "<![CDATA[never <p ends",
            "-->a<!--b<![CDATA[c]]>",
            "<<!--] ]<![CDATA[/]-- ><![CDATA[/p--!>] ]<!-->?",
            "<<![CDATA[x] ]>]]>",
            "<<!-- a -- > b -->?",
        ):
            with self.subTest(text=text):
                self.assertEqual(_neutralize(_neutralize(text)), _neutralize(text))

    def test_a_body_that_is_made_of_such_constructs_is_converted_in_a_moment(self):
        for unit, repeated in (
            ("<!--", 40_000),
            ("<!--x>", 100_000),
            ("</p ", 100_000),
            ("<?x ", 100_000),
            ("<!x ", 250_000),
            ("<![if ", 100_000),
            ("<![foo[", 100_000),
            ("<![CDATA[", 100_000),
        ):
            body = "<p>before</p>" + unit * repeated + "<p>after</p>"
            with self.subTest(unit=unit, size=len(body)):
                self.assertLess(seconds(storage_to_markdown, body), LIMIT_SECONDS)
                text = storage_to_text(body)
                self.assertTrue(text.startswith("before") and text.endswith("after"), text[:40])  # the words around them are there

    def test_what_a_parser_would_read_as_markup_after_an_early_end_is_not_left_to_cost_the_square(self):
        for head, middle, tail in (
            ("<![CDATA[ ] ] > ", "<!--x>", " ]]>"),
            ("<![CDATA[ ] ] > ", "<![if >", " ]]>"),
            ("<![CDATA[ ] ] > ", "</p x>", " ]]>"),
            ("<![CDATA[ ] ] > ", "<?x >", " ]]>"),
            ("<![CDATA[ ] ] > ", "<p b='>", " ]]>"),
            ("<!-- <![CDATA[ --> ", "<!--x>", " ]]>"),  # the opener of a section inside a comment is no opener
            ("<!-- <![CDATA[ --> ", "<![if >", " ]]>"),
            ("<!-- -- > ", "<![if >", " -->"),
            ("<!-- --!> ", "<!--x>", " -->"),
            ("<!---> ", "<!--x>", " -->"),
            ("<!--> ", "<![if >", " -->"),
        ):
            body = head + middle * 40_000 + tail
            with self.subTest(head=head, middle=middle, size=len(body)):
                self.assertLess(seconds(storage_to_markdown, body), LIMIT_SECONDS)

    def test_the_neutralisation_alone_is_a_moment_for_any_shape(self):
        started = time.perf_counter()
        for text in ("<" * MEGABYTE, "<!" * 500_000, "<!--" * 250_000 + "-->", "]]>" * 300_000, "<![CDATA[" * 100_000 + "]]>", "-->" * 300_000 + "<!--"):
            _neutralize(text)
        self.assertLess(time.perf_counter() - started, LIMIT_SECONDS)


class LinearTimeTest(unittest.TestCase):
    """What the old code read in time that grows with the size, and what it still does: each of these is a body of the size that is named."""

    def test_a_body_of_a_million_characters_that_is_text_is_read_in_a_moment(self):
        for label, body in (
            ("one long word", "<p>" + "a" * MEGABYTE + "</p>"),
            ("blanks in a paragraph", "<p>a" + " " * MEGABYTE + "b</p>"),
            ("backticks", "<p>" + "`" * MEGABYTE + "</p>"),
            ("what Markdown escapes", "<p>" + "\\`*_[]|" * 150_000 + "</p>"),
            ("lines", "<p>" + "a\n" * 500_000 + "</p>"),
            ("numbered lines", "<p>" + "1. x\n" * 200_000 + "</p>"),
            ("a run of digits", "<p>" + "1" * MEGABYTE + "x</p>"),
            ("a run of dashes", "<p>" + "-" * MEGABYTE + "x</p>"),
            ("an address of a million characters", '<p><a href="http://' + "a" * MEGABYTE + '">x</a></p>'),
            ("a table cell of a million characters", "<table><tr><td>" + "a" * MEGABYTE + "</td></tr></table>"),
            ("a code block of a million blanks", "<pre>" + " " * MEGABYTE + "x</pre>"),
            ("comments", "<!-- x -->" * 100_000),
            ("sections", "<![CDATA[x]]>" * 70_000),
            ("end tags that nothing opened", "</p>" * 250_000),
            ("character references that are no reference", "<p>" + ("&" + "a" * 31 + " ") * 30_000 + "</p>"),
        ):
            for convert in (storage_to_markdown, storage_to_text):
                with self.subTest(body=label, convert=convert.__name__):
                    self.assertLess(seconds(convert, body), LIMIT_SECONDS)

    def test_a_body_of_200_thousand_characters_that_is_nothing_but_markup_is_read_in_a_moment(self):
        for label, body in (
            ("paragraphs", "<p>x</p>" * 25_000),
            ("list items", "<ul>" + "<li>x</li>" * 20_000 + "</ul>"),
            ("line breaks in a paragraph", "<p>" + "<br/>" * 40_000 + "</p>"),
            ("rows of a table", "<table>" + "<tr><td>x</td></tr>" * 10_000 + "</table>"),
            ("cells of a row", "<table><tr>" + "<td/>" * 40_000 + "</tr></table>"),
            ("parameters of a macro", '<ac:structured-macro ac:name="info">' + '<ac:parameter ac:name="a">x</ac:parameter>' * 5_000 + "</ac:structured-macro>"),
            ("links", "<p>" + '<ac:link><ri:page ri:content-title="x"/></ac:link>' * 4_000 + "</p>"),
            ("tasks", "<ac:task-list>" + "<ac:task><ac:task-status>incomplete</ac:task-status><ac:task-body>x</ac:task-body></ac:task>" * 2_000 + "</ac:task-list>"),
            ("nested divs beyond the limit", "<div>" * 20_000 + "x"),
        ):
            for convert in (storage_to_markdown, storage_to_text):
                with self.subTest(body=label, convert=convert.__name__):
                    self.assertLess(seconds(convert, body), LIMIT_SECONDS)

    def test_a_start_of_thousands_of_digits_is_not_written_into_every_item(self):
        body = '<ol start="' + "9" * 4_000 + '">' + "<li>x</li>" * 20_000 + "</ol>"
        text = storage_to_markdown(body).text
        self.assertLess(len(text), 20_000 * 25)
        self.assertTrue(text.startswith("999999999. x\n1000000000. x"))


class TableLimitTest(unittest.TestCase):
    def test_a_table_that_is_all_padding_is_refused_and_a_table_at_the_limit_is_not(self):
        wide = "<table><tr>" + "<td/>" * 2001 + "</tr>" + "<tr><td/></tr>" * 1000 + "</table>"  # one row of 2001 cells, 1000 rows of one: 2,003,001 cells in Markdown
        with self.assertRaises(ValidationError) as caught:
            storage_to_markdown(wide)
        self.assertIn("too large", caught.exception.message)
        self.assertIn("--format storage", caught.exception.hint)
        self.assertIsInstance(storage_to_text(wide), str)  # the text has no padding: it reads as it always did
        limit = "<table><tr>" + "<td/>" * 2000 + "</tr>" + "<tr><td/></tr>" * 999 + "</table>"
        self.assertTrue(storage_to_markdown(limit).text.startswith("|"))

    def test_the_size_that_matters_is_the_padded_table_and_not_the_body(self):
        body = "<table>" + "<tr><td>x</td><td>y</td></tr>" * 20_000 + "</table>"  # 40,000 cells that are all there
        self.assertEqual(storage_to_markdown(body).text.count("\n"), 20_001)


class UnreadableBodyTest(unittest.TestCase):
    def test_what_breaks_the_converter_is_a_body_that_cannot_be_read_and_the_error_does_not_quote_the_body(self):
        calls = (
            storage_to_markdown,
            storage_to_text,
            lossy_constructs,
            lambda body: render_body(body, "markdown", with_users=False),
            lambda body: render_body(body, "text", with_users=False),
        )
        for index, call in enumerate(calls):
            with self.subTest(call=index), mock.patch.object(storage._Builder, "close", side_effect=AssertionError("unknown status keyword 'alex@example.com' in marked section")):
                with self.assertRaises(ValidationError) as caught:
                    call("<p>a</p>")
            self.assertEqual(caught.exception.message, "cannot read this body as storage format")
            self.assertIn("--format storage", caught.exception.hint)
            self.assertNotIn("alex@example.com", caught.exception.message + caught.exception.hint)

    def test_what_nests_too_deeply_is_still_said_so(self):
        with self.assertRaises(ValidationError) as caught:
            storage_to_markdown("<div>" * 200 + "x" + "</div>" * 200)
        self.assertEqual(caught.exception.message, "nested too deeply to convert")
        with mock.patch.object(storage._Builder, "close", side_effect=RecursionError()), self.assertRaises(ValidationError) as caught:
            storage_to_text("<p>a</p>")
        self.assertEqual(caught.exception.message, "nested too deeply to convert")

    def test_what_used_to_end_in_an_assertion_error_is_text(self):
        for piece in ("<![foo[", "<![ ", "<![[", "<![]]>", "<![x y["):
            body = f"<p>a</p>{piece}<p>b</p>"
            with self.subTest(piece=piece):
                markdown, text = storage_to_markdown(body).text, storage_to_text(body)
                self.assertTrue(markdown.startswith("a") and markdown.endswith("b"), markdown)
                self.assertTrue(text.startswith("a") and text.endswith("b"), text)
                self.assertIn(piece.strip(), text)
                self.assertEqual(lossy_constructs(body), ())


class NumberTest(unittest.TestCase):
    def test_the_number_of_an_attribute_is_read_safely(self):
        cases = (
            ("12", 1, 12),
            ("x", 1, 1),
            ("", 5, 5),
            (" 3 ", 1, 3),
            ("+4", 1, 4),
            ("-2", 1, -2),
            ("0012", 1, 12),
            ("1_0", 1, 1),
            ("1.5", 1, 1),
            ("2px", 1, 1),
            ("\u0663", 1, 1),  # a digit of another script is no number here
            ("9" * 30, 1, 999_999_999),
            ("0" * 5000 + "7", 1, 7),
            ("9" * 5000, 1, 999_999_999),
            ("-" + "9" * 30, 1, -999_999_999),
        )
        for text, default, expected in cases:
            with self.subTest(text=text[:12], size=len(text)):
                self.assertEqual(_number(text, default), expected)

    def test_a_list_that_does_not_say_where_it_starts_starts_at_one(self):
        for start in ("x", "", " ", "1e3", "\u0663", "1_0"):
            with self.subTest(start=start):
                self.assertEqual(storage_to_markdown(f'<ol start="{start}"><li>one</li></ol>').text, "1. one")
                self.assertEqual(storage_to_text(f'<ol start="{start}"><li>one</li></ol>'), "1. one")
        self.assertEqual(storage_to_markdown('<ol start=" 7 "><li>a</li><li>b</li></ol>').text, "7. a\n8. b")
        self.assertEqual(storage_to_text('<ol start="7"><li>a</li><li>b</li></ol>'), "7. a\n8. b")

    def test_a_cell_that_does_not_say_how_far_it_reaches_reaches_one(self):
        def dropped(attributes):
            return storage_to_markdown(f"<table><tr><td {attributes}>a</td></tr></table>").dropped

        self.assertEqual(dropped('colspan="x" rowspan="y"'), ())
        self.assertEqual(dropped('colspan="" rowspan="1"'), ())
        self.assertEqual(dropped('colspan="2"'), ("table:merged-cells",))
        self.assertEqual(dropped('rowspan="3"'), ("table:merged-cells",))
        self.assertEqual(dropped('colspan="' + "9" * 30 + '"'), ("table:merged-cells",))


class BodyHelpersTimeTest(unittest.TestCase):
    """What `application/rendering.py` and `domain/payloads.py` do with a body of a million characters: the converter, the redaction of the people in it, and the
    request that is built from it."""

    def test_a_body_of_a_million_characters_is_shown_in_every_format_in_a_moment(self):
        for label, body in (
            ("mentions", "<p>" + '<ri:user ri:account-id="x"/>' * 35_000 + "</p>"),
            ("attributes with blanks and single quotes", "<p " + "ri:account-id = 'x' " * 50_000 + "></p>"),
            ("attributes that are never closed", "<p " + 'ri:account-id="' * 60_000),
            ("attributes that mean a person", "<p>" + '<span data-account-id="x">a</span>' * 28_000 + "</p>"),
            ("blanks before an attribute", "<p " + " " * MEGABYTE + 'ri:account-id="x">'),
            ("equal signs", "ri:account-id" + " = " * (MEGABYTE // 3)),
            ("e-mail addresses", "<p>" + "a@b.example " * 80_000 + "</p>"),
            ("addresses of people", "<p>" + "http://x/wiki/people/" * 47_000 + "</p>"),
        ):
            for fmt in ("markdown", "text", "storage"):
                with self.subTest(body=label, format=fmt):
                    self.assertLess(seconds(lambda: render_body(body, fmt, with_users=False)), LIMIT_SECONDS)

    def test_a_body_that_is_written_in_storage_format_is_checked_for_blanked_mentions_in_a_moment(self):
        for label, text in (
            ("blanked attributes", 'ri:account-id = "hidden" ' * 40_000),
            ("a name and a million blanks", "ri:account-id" + " " * MEGABYTE + "x"),
            ("openers of attributes", 'data-userkey="' * 70_000),
            ("quotes", "ri:space-key=" + "'" * MEGABYTE),
            ("text", "<p>" + "x" * MEGABYTE + "</p>"),
        ):
            with self.subTest(text=label):
                self.assertLess(seconds(storage_from_input, text, "storage"), LIMIT_SECONDS)

    def test_the_request_of_a_page_of_a_million_characters_is_built_in_a_moment_and_holds_the_body_as_it_is(self):
        body = "<p>" + "x" * MEGABYTE + "</p>"
        started = time.perf_counter()
        created = create_page_payload("1", "T", body, "2")
        updated = update_page_payload("1", "T", body, 2, "a message")
        labels = label_payload(["a"] * 100_000)
        self.assertLess(time.perf_counter() - started, LIMIT_SECONDS)
        self.assertEqual((created["body"]["value"], updated["body"]["value"], len(labels)), (body, body, 100_000))


if __name__ == "__main__":
    unittest.main()
