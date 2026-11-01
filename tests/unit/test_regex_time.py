"""Text from a page, a Markdown file or a command line is read in a time that grows with its length, whatever it is made of.

Each case is a text that made one pattern of the package try every way to split a run between two parts that can both take a character (the blanks at the
end of a heading line, a delimiter row, a fence, the end of an address, a run of slashes), or run on to the end of the text from every start of it. At the sizes
here those took ten seconds and more, and for a heading line the cube of its length; the code reads them in a few thousandths of a second. The last class
holds what the patterns read before and still read the same way (the answers of the old ones), and a few texts that were never slow, to keep them so."""
import threading
import time
import unittest
from datetime import datetime, timezone

from conflu_c_cli.adapters.driving.cli.mcp_calls import private_text_filter
from conflu_c_cli.domain.comments import parse_since
from conflu_c_cli.domain.durations import parse_duration
from conflu_c_cli.domain.errors import UsageError, ValidationError
from conflu_c_cli.domain.frontmatter import take_title_heading
from conflu_c_cli.domain.markdown import markdown_to_storage
from conflu_c_cli.domain.sections import outline, plain_title
from conflu_c_cli.domain.templates import variables_of
from tests.support.fakes import FakeGateway, MemoryConfigStore, build_app

LIMIT_SECONDS = 3.0  # each of these takes a few thousandths of a second; the old patterns took ten seconds and more


def seconds(call, *args) -> float:
    started = time.perf_counter()
    try:
        call(*args)
    except (ValidationError, UsageError):
        pass  # a text that is no good is refused, which is the right answer; the time is what is measured
    return time.perf_counter() - started


class MarkdownTimeTest(unittest.TestCase):
    def test_a_heading_with_a_long_run_of_blanks_inside_it(self):
        self.assertLess(seconds(markdown_to_storage, "# a" + " " * 2300 + "x"), LIMIT_SECONDS)  # the old pattern took the cube of the run: 2 300 blanks, 18 seconds

    def test_a_fence_with_a_long_run_of_blanks_and_then_a_backtick(self):
        self.assertLess(seconds(markdown_to_storage, "```" + " " * 60_000 + "`"), LIMIT_SECONDS)

    def test_a_delimiter_row_with_a_long_run_of_blanks(self):
        self.assertLess(seconds(markdown_to_storage, "a | b\n-|-" + "\t" * 60_000 + "!"), LIMIT_SECONDS)

    def test_an_address_after_every_parenthesis(self):
        self.assertLess(seconds(markdown_to_storage, "(http://" * 16_000), LIMIT_SECONDS)  # every one is read to the end of the line, and none is made a link

    def test_an_address_that_ends_in_a_long_run_of_closing_parentheses(self):
        self.assertLess(seconds(markdown_to_storage, "http://a" + ")" * 100_000), LIMIT_SECONDS)

    def test_a_quote_that_is_followed_by_a_long_run_of_blank_lines(self):
        self.assertLess(seconds(markdown_to_storage, "> a" + "\n" * 20_000 + "b"), LIMIT_SECONDS)

    def test_the_marks_of_the_converter_in_a_text_are_no_marks(self):
        self.assertEqual(markdown_to_storage("a\ufff0b\ufff1c"), "<p>a\ufffdb\ufffdc</p>")
        done: list[str] = []
        worker = threading.Thread(target=lambda: done.append(markdown_to_storage("`\ufff0C0\ufff1`")), daemon=True)  # the converter put this span into itself for ever
        worker.start()
        worker.join(LIMIT_SECONDS)
        self.assertFalse(worker.is_alive(), "the converter does not come back")
        self.assertEqual(done, ["<p><code>\ufffdC0\ufffd</code></p>"])


class OutlineTimeTest(unittest.TestCase):
    def test_a_heading_with_a_long_run_of_blanks_inside_it(self):
        self.assertLess(seconds(outline, "# a" + " " * 40_000 + "x"), LIMIT_SECONDS)

    def test_a_heading_of_opening_brackets(self):
        self.assertLess(seconds(outline, "# " + "[" * 60_000), LIMIT_SECONDS)
        self.assertLess(seconds(outline, "# " + "[a](" * 15_000), LIMIT_SECONDS)

    def test_a_heading_of_emphasis_that_never_ends(self):
        self.assertLess(seconds(outline, "# " + "*a " * 20_000), LIMIT_SECONDS)
        self.assertLess(seconds(plain_title, "_a!" * 20_000), LIMIT_SECONDS)

    def test_a_title_in_a_file_with_a_long_run_of_blanks_inside_it(self):
        self.assertLess(seconds(take_title_heading, "# a" + " " * 35_000 + "x"), LIMIT_SECONDS)

    def test_a_page_of_many_headings(self):
        self.assertLess(seconds(outline, "# a\n" * 60_000), LIMIT_SECONDS)  # each heading looked at all that follows it, to find where its section ends
        self.assertLess(seconds(outline, "# a\n" + "## b\n" * 60_000), LIMIT_SECONDS)


class ValueTimeTest(unittest.TestCase):
    def test_a_length_of_time_with_a_long_run_of_blanks_after_it(self):
        self.assertLess(seconds(parse_duration, "1" + " " * 60_000 + "x"), LIMIT_SECONDS)

    def test_a_long_value_for_since_is_read_once(self):
        now = datetime(2026, 10, 15, tzinfo=timezone.utc)
        for text in ("0" * 200_000 + "!", "1." * 100_000, "+00" * 70_000, "2026-10-15T08:00:00." + "1" * 200_000):
            with self.subTest(shape=text[:6], size=len(text)):
                self.assertLess(seconds(parse_since, text, now), LIMIT_SECONDS)

    def test_an_address_of_dots_for_the_account_is_read_once(self):
        app = build_app(gateway=FakeGateway(), store=MemoryConfigStore())
        self.assertLess(seconds(app.config.set_value, "CONFLUENCE_EMAIL", "a@" + "." * 40_000 + " !"), LIMIT_SECONDS)


class TemplateTimeTest(unittest.TestCase):
    def test_a_body_of_broken_tags_is_read_within_its_limits(self):
        for body in ("<at:var " * 131_072, "<at:var at:name='" * 65_536, "<at:var x='" + "'" * 1_000_000, "<at:var " + "~" * 1_000_000, "<!--" * 250_000):
            with self.subTest(shape=body[:12], size=len(body)):
                self.assertLess(seconds(variables_of, body), LIMIT_SECONDS)


class PrivateFilterTimeTest(unittest.TestCase):
    def test_a_result_of_slashes_is_read_once(self):
        hide = private_text_filter(["C:\\Users\\alex"], ["alex"])
        for text in ("/" * 35_000, "\\" * 35_000, "/users" + "/" * 35_000 + "x"):
            with self.subTest(shape=text[:7], size=len(text)):
                self.assertLess(seconds(hide, text), LIMIT_SECONDS)


class StillTheSameTest(unittest.TestCase):
    """What the patterns read before, they read now: the answers of the old ones, for the cases where the parts of a pattern had to share."""

    def test_headings(self):
        cases = {
            "# Title": "<h1>Title</h1>",
            "## Title ##": "<h2>Title</h2>",
            "#\tTitle\t#\t": "<h1>Title</h1>",
            "### a # b ###": "<h3>a # b</h3>",
            "# foo#": "<h1>foo</h1>",
            "####### seven": "<p>####### seven</p>",
            "#  ": "<h1></h1>",
            "# ": "<p># </p>",
            "#hashtag": "<p>#hashtag</p>",
            "text\n# heading inside": "<p>text</p>\n<h1>heading inside</h1>",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(markdown_to_storage(text), expected)

    def test_fences(self):
        code = '<ac:structured-macro ac:name="code" ac:schema-version="1">'
        cases = {
            "``` python\ncode\n```": code + '<ac:parameter ac:name="language">python</ac:parameter><ac:plain-text-body><![CDATA[code]]></ac:plain-text-body></ac:structured-macro>',
            "~~~ info here\nx\n~~~": code + '<ac:parameter ac:name="language">info</ac:parameter><ac:plain-text-body><![CDATA[x]]></ac:plain-text-body></ac:structured-macro>',
            "``` a`b\nx\n```": "<p>``` a`b\nx</p>\n" + code + "<ac:plain-text-body><![CDATA[]]></ac:plain-text-body></ac:structured-macro>",  # a backtick in the info: no fence opens
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(markdown_to_storage(text), expected)

    def test_tables(self):
        plain = "<table><tbody><tr><th>a</th><th>b</th></tr><tr><td>1</td><td>2</td></tr></tbody></table>"
        for text in ("a | b\n--|--\n1 | 2", "a | b\n- | - |  \n1 | 2"):
            with self.subTest(text=text):
                self.assertEqual(markdown_to_storage(text), plain)
        self.assertEqual(markdown_to_storage("| a |\n| - |\n| 1 |"), "<table><tbody><tr><th>a</th></tr><tr><td>1</td></tr></tbody></table>")
        for text in ("a | b\n--|", "a | b\n|--|", "a | b\n-| |"):  # one cell without the pipes of a one-column table, or an empty cell: no table
            with self.subTest(text=text):
                self.assertEqual(markdown_to_storage(text), f"<p>{text}</p>")

    def test_addresses_and_quotes(self):
        self.assertEqual(
            markdown_to_storage("see http://example.org/a), and (http://example.org/b) ok a=http://c.example http://d.example/x(1))."),
            '<p>see <a href="http://example.org/a">http://example.org/a</a>), and (http://example.org/b) ok a=http://c.example '
            '<a href="http://d.example/x(1)">http://d.example/x(1)</a>).</p>',
        )
        two = "<blockquote><p>a</p></blockquote>\n<blockquote><p>b</p></blockquote>"
        self.assertEqual(markdown_to_storage("> a\n\n\n> b"), two)
        self.assertEqual(markdown_to_storage("> a\n\n\n\n> b\n\n"), two)
        self.assertEqual(markdown_to_storage("> a\n\n\nb"), "<blockquote><p>a</p></blockquote>\n<p>b</p>")

    def test_the_text_of_a_heading(self):
        cases = {
            "[Docs](http://x.example) and ![img](a.png) *em* **strong** \\*raw\\* `c`": "Docs and img em strong raw c",
            "[a](b": "[a](b",
            "[a] (b)": "[a] (b)",
            "![](x)": "",
            "a [b](c) d [e](f)": "a b d e",
            "[[a]](b)": "[[a]](b)",
            "*a *b* c*": "a *b c*",
            "_a_ b_c_d __e__": "a b_c_d e",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(plain_title(raw), expected)

    def test_the_outline_of_a_page(self):
        text = "# One #\n## Two ##\n```\n# not a heading\n```\n#Three\n# Four  #  \n###### Six\n####### no\n#\n# \n"
        self.assertEqual(
            [(heading.index, heading.level, heading.title, heading.line, heading.end, heading.chars) for heading in outline(text)],
            [(1, 1, "One", 0, 6, 48), (2, 2, "Two", 1, 6, 40), (3, 1, "Four", 6, 10, 35), (4, 6, "Six", 7, 10, 23), (5, 1, "", 10, 12, 1)],
        )

    def test_the_title_of_a_file(self):
        cases = {
            "\n\n# Title #\nbody": ("Title", "body"),
            "  # T\nrest": ("T", "rest"),
            "# a #\n": ("a", ""),
            "# a": ("a", ""),
            "#  \nx": ("", "x"),
            "# \nx": ("", "# \nx"),
            "text\n# no": ("", "text\n# no"),
            "#\tTitle\t\nmore": ("Title", "more"),
        }
        for body, expected in cases.items():
            with self.subTest(body=body):
                self.assertEqual(take_title_heading(body), expected)

    def test_lengths_of_time(self):
        for text, expected in {" 10 m ": 600.0, "1.5h": 5400.0, "90": 90.0, "2 D": 172800.0, "7w": 4233600.0, "\u00a05s\u00a0": 5.0}.items():
            with self.subTest(text=text):
                self.assertEqual(parse_duration(text), expected)
        for text in ("x", "1 2", "", None, "10 minutes"):
            with self.subTest(text=text), self.assertRaises(ValidationError):
                parse_duration(text)

    def test_an_address_for_the_account(self):
        app = build_app(gateway=FakeGateway(), store=MemoryConfigStore())
        for value in ("alex@example.com", "a@b.c", "  alex@example.com  ", "a@b..c", "a@.b.c"):
            with self.subTest(value=value):
                app.config.set_value("CONFLUENCE_EMAIL", value)
        for value in ("a@b", "a@.c", "@b.c", "a b@c.d", "a@b@c.d", "a@b.", "alex"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                app.config.set_value("CONFLUENCE_EMAIL", value)

    def test_the_folder_of_a_user_in_a_result(self):
        hide = private_text_filter(["C:\\Users\\alex", "/home/alex"], ["alex"])
        cases = {
            "C:\\Users\\alex\\x and /Users/alex/y /home/alex/z": "~\\x and ~/y ~/z",
            "d:\\users\\alex": "~",
            "///users///alex///": "~///",
            "/home/alexander": "/home/alexander",
            "C:\\\\Users\\\\alex\\\\f": "~\\\\f",
            "x/users/alex.corp": "x/users/alex.corp",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(hide(text), expected)


if __name__ == "__main__":
    unittest.main()
