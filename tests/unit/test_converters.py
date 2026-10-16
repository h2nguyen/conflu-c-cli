"""Regression tests for the Markdown and storage-format converters."""
from __future__ import annotations

import random
import re
import time
import unittest
import xml.etree.ElementTree as ET
from html import unescape
from pathlib import Path

from conflu_c_cli.domain.errors import ValidationError
from conflu_c_cli.domain.frontmatter import parse_markdown_page
from conflu_c_cli.domain.markdown import markdown_to_storage
from conflu_c_cli.domain.storage import lossy_constructs, storage_to_markdown, storage_to_text


def _xml_safe(storage: str) -> str:
    def replace(match: re.Match[str]) -> str:
        entity = match.group(0)
        if entity in {"&amp;", "&lt;", "&gt;", "&quot;", "&apos;"}:
            return entity
        text = unescape(entity)
        if text == entity:
            return entity.replace("&", "&amp;")
        return "".join(f"&#{ord(char)};" for char in text)

    return re.sub(r"&[A-Za-z][A-Za-z0-9]+;", replace, storage)


def _canonical_fragment(storage: str):
    wrapped = f'<root xmlns:ac="a" xmlns:ri="r">{_xml_safe(storage)}</root>'
    root = ET.fromstring(wrapped)

    def canon(node: ET.Element):
        ignored = {"{a}schema-version", "{a}macro-id"}
        attrs = tuple(sorted((key, value) for key, value in node.attrib.items() if key not in ignored))
        text = (node.text or "").replace("\r\n", "\n").replace("\r", "\n")
        if text.strip() == "" and len(node):
            text = ""
        children = tuple(canon(child) for child in node)
        tail = (node.tail or "").replace("\r\n", "\n").replace("\r", "\n")
        if tail.strip() == "":
            tail = ""
        return (node.tag, attrs, text, children, tail)

    return canon(root)


def _newline_variants(text: str) -> tuple[str, str, str, str]:
    base = text.replace("\r\n", "\n").replace("\r", "\n")
    base = base.rstrip("\n")
    return (
        base,
        base + "\n",
        base + "\n\n\n",
        base.replace("\n", "\r\n") + "\r\n",
    )


def _storage_stats(storage: str) -> dict[str, object]:
    wrapped = f'<root xmlns:ac="a" xmlns:ri="r">{_xml_safe(storage)}</root>'
    root = ET.fromstring(wrapped)
    block_tags = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "td", "th", "tr", "blockquote", "ul", "ol", "table", "hr", "br", "div", "rich-text-body", "plain-text-body", "task", "task-body", "layout-cell", "layout-section"}

    def block_text(element: ET.Element) -> str:
        parts: list[str] = []

        def walk(node: ET.Element) -> None:
            local = node.tag.split("}")[-1]
            if local in block_tags:
                parts.append(" ")
            parts.append(node.text or "")
            for child in node:
                walk(child)
                parts.append(child.tail or "")
            if local in block_tags:
                parts.append(" ")

        walk(element)
        return "".join(parts)

    text = re.sub(r"[\s\u00a0]+", " ", block_text(root)).strip()
    hrefs: list[str] = []
    counts = {name: 0 for name in ("h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "table", "tr", "th", "td", "{a}image", "{a}structured-macro")}
    code_bodies: list[str] = []
    nested_anchor = False

    def walk(node: ET.Element, anchor_depth: int = 0) -> None:
        nonlocal nested_anchor
        if node.tag == "a":
            if anchor_depth:
                nested_anchor = True
            anchor_depth += 1
            href = node.attrib.get("href")
            if href:
                hrefs.append(href)
        elif node.tag == "{r}url":
            value = node.attrib.get("{r}value")
            if value:
                hrefs.append(value)
        elif node.tag == "{r}attachment":
            value = node.attrib.get("{r}filename")
            if value:
                hrefs.append("attachment:" + value)
        elif node.tag == "{r}page":
            title = node.attrib.get("{r}content-title", "")
            space = node.attrib.get("{r}space-key", "")
            hrefs.append(f"page:{space}/{title}" if space else f"page:{title}")
        elif node.tag == "{a}plain-text-body":
            code_bodies.append(node.text or "")
        if node.tag in counts:
            counts[node.tag] += 1
        for child in node:
            walk(child, anchor_depth)

    walk(root)
    return {"text": text, "hrefs": tuple(hrefs), "counts": counts, "code_bodies": tuple(code_bodies), "nested_anchor": nested_anchor}


class ConverterTestCase(unittest.TestCase):
    maxDiff = None

    def assert_xml_fragment(self, storage: str) -> None:
        wrapped = f'<root xmlns:ac="a" xmlns:ri="r">{_xml_safe(storage)}</root>'
        ET.fromstring(wrapped)

    def assert_stable_markdown(self, markdown: str) -> None:
        first = storage_to_markdown(markdown_to_storage(markdown))
        second = storage_to_markdown(markdown_to_storage(first.text))
        self.assertEqual(first.dropped, ())
        self.assertEqual(second.dropped, ())
        self.assertEqual(first.text, second.text)

    def assert_canonical_equal(self, left: str, right: str) -> None:
        self.assertEqual(_canonical_fragment(left), _canonical_fragment(right))

    def assert_markdown_trailing_newlines_do_not_matter(self, markdown: str) -> None:
        variants = _newline_variants(markdown)
        rendered = [markdown_to_storage(item) for item in variants]
        self.assertEqual(rendered[0], rendered[1])
        self.assertEqual(rendered[0], rendered[2])
        self.assertEqual(rendered[0], rendered[3])


class MarkdownToStorageCaseTest(ConverterTestCase):
    pass


MARKDOWN_CASES = {
    "empty_input": {"source": "", "equals": ""},
    "whitespace_input": {"source": " \n\t \n", "equals": ""},
    "atx_heading_one": {"source": "# Title\n", "contains": ("<h1>Title</h1>",)},
    "atx_heading_six": {"source": "###### Tiny\n", "contains": ("<h6>Tiny</h6>",)},
    "setext_heading_one": {"source": "Title\n=====\n", "contains": ("<h1>Title</h1>",)},
    "setext_heading_two": {"source": "Subtitle\n-----\n", "contains": ("<h2>Subtitle</h2>",)},
    "paragraph_lines_join": {"source": "one\ntwo\n", "contains": ("<p>one\ntwo</p>",)},
    "hard_break_spaces": {"source": "one  \ntwo\n", "contains": ("<br />",)},
    "hard_break_backslash": {"source": "one\\\ntwo\n", "contains": ("<br />",)},
    "blockquote": {"source": "> quoted\n", "contains": ("<blockquote>", "<p>quoted</p>", "</blockquote>")},
    "blockquote_lazy": {"source": "> first\nsecond\n", "contains": ("<blockquote>", "first\nsecond")},
    "alert_note": {"source": "> [!NOTE]\n> text\n", "contains": ('ac:name="info"', "<p>text</p>")},
    "alert_tip": {"source": "> [!TIP]\n> text\n", "contains": ('ac:name="tip"',)},
    "alert_warning": {"source": "> [!WARNING]\n> text\n", "contains": ('ac:name="warning"',)},
    "unordered_list": {"source": "- a\n- b\n", "contains": ("<ul>", "<li>a</li>", "<li>b</li>")},
    "ordered_list": {"source": "1. one\n2. two\n", "contains": ("<ol>", "<li>one</li>", "<li>two</li>")},
    "ordered_start": {"source": "3. three\n4. four\n", "contains": ('<ol start="3">',)},
    "task_list": {"source": "- [ ] todo\n- [x] done\n", "contains": ("<ac:task-list>", "<ac:task-id>1</ac:task-id>", "<ac:task-status>complete</ac:task-status>")},
    "mixed_task_list_stays_literal": {"source": "- [ ] todo\n- later\n", "contains": ("[ ] todo",), "not_contains": ("<ac:task-list>",)},
    "fenced_code_language_alias": {"source": "```py\nprint(1)\n```\n", "contains": ('ac:name="code"', '<ac:parameter ac:name="language">python</ac:parameter>', "print(1)")},
    "fenced_code_unclosed": {"source": "```text\none\ntwo", "contains": ("one\ntwo",)},
    "fenced_code_cdata_split": {"source": "```\n]]>\n```\n", "contains": ("]]]]><![CDATA[>",)},
    "indented_code": {"source": "    code\n    more\n", "contains": ('ac:name="code"', "code\nmore")},
    "horizontal_rule_dash": {"source": "---\n", "contains": ("<hr />",)},
    "horizontal_rule_star": {"source": "***\n", "contains": ("<hr />",)},
    "table_basic": {"source": "| A | B |\n| --- | --- |\n| x | y |\n", "contains": ("<table><tbody>", "<th>A</th>", "<td>x</td>")},
    "table_alignment": {"source": "| A | B | C |\n| :--- | :---: | ---: |\n| x | y | z |\n", "contains": ('style="text-align: left;"', 'style="text-align: center;"', 'style="text-align: right;"')},
    "bold_em_strike_code": {"source": "***both*** **bold** *em* ~~gone~~ `code`\n", "contains": ("<strong><em>both</em></strong>", "<strong>bold</strong>", "<em>em</em>", 'text-decoration: line-through;', "<code>code</code>")},
    "inline_link_title": {"source": '[site](https://example.com "Example")\n', "contains": ('<a href="https://example.com" title="Example">site</a>',)},
    "reference_link": {"source": "[site][ref]\n\n[ref]: https://example.com/path\n", "contains": ('<a href="https://example.com/path">site</a>',)},
    "autolink": {"source": "<https://example.com/a>\n", "contains": ('<a href="https://example.com/a">https://example.com/a</a>',)},
    "bare_url": {"source": "See https://example.com/a, now.\n", "contains": ('<a href="https://example.com/a">https://example.com/a</a>',)},
    "image_url": {"source": "![Alt](https://example.com/a.png)\n", "contains": ('<ac:image ac:alt="Alt"><ri:url ri:value="https://example.com/a.png" /></ac:image>',)},
    "image_attachment": {"source": "![Alt](docs/My%20File.png)\n", "contains": ('<ri:attachment ri:filename="My File.png" />',)},
    "raw_html_escaped": {"source": "<script>alert(1)</script>\n", "contains": ("&lt;script&gt;alert(1)&lt;/script&gt;",), "not_contains": ("<script>",)},
    "raw_html_br_preserved": {"source": "a<br>b\n", "contains": ("<br />",)},
    "entities_preserved": {"source": "Fish &amp; Chips &nbsp; and &#169;\n", "contains": ("&amp;", "\xa0", "©")},
    "invalid_entity_escaped": {"source": "A &bogus; B\n", "contains": ("&amp;bogus;",)},
    "control_chars_stripped": {"source": "A\x01B\x0bC\n", "contains": ("ABC",), "not_contains": ("\x01", "\x0b")},
    "crlf_is_normalized": {"source": "# Title\r\n\r\nText\r\n", "contains": ("<h1>Title</h1>", "<p>Text</p>")},
    "deep_nesting_is_well_formed": {"source": "".join("  " * level + "- item\n" for level in range(30)), "contains": ("<ul>",)},
}


def _make_markdown_test(case: dict[str, object]):
    def test(self: ConverterTestCase) -> None:
        rendered = markdown_to_storage(case["source"])  # type: ignore[index]
        if "equals" in case:
            self.assertEqual(rendered, case["equals"])
            return
        self.assert_xml_fragment(rendered)
        for snippet in case.get("contains", ()):  # type: ignore[union-attr]
            self.assertIn(snippet, rendered)
        for snippet in case.get("not_contains", ()):  # type: ignore[union-attr]
            self.assertNotIn(snippet, rendered)

    return test


for _name, _case in MARKDOWN_CASES.items():
    setattr(MarkdownToStorageCaseTest, f"test_{_name}", _make_markdown_test(_case))


class StorageToMarkdownCaseTest(ConverterTestCase):
    pass


STORAGE_MARKDOWN_CASES = {
    "empty_input": {"source": "", "text": "", "dropped": ()},
    "paragraph_text": {"source": "<p>Hello world</p>", "text": "Hello world", "dropped": ()},
    "heading": {"source": "<h2>Title</h2>", "text": "## Title", "dropped": ()},
    "hard_break": {"source": "<p>one<br />two</p>", "text": "one\\\ntwo", "dropped": ()},
    "inline_formatting": {"source": "<p><strong>bold</strong> <em>em</em> <span style=\"text-decoration: line-through;\">gone</span> <code>c</code></p>", "text": "**bold** *em* ~~gone~~ `c`", "dropped": ()},
    "simple_link": {"source": "<p><a href=\"https://example.com\">site</a></p>", "text": "[site](https://example.com)", "dropped": ()},
    "page_link": {"source": "<ac:link><ri:page ri:content-title=\"Guide\" ri:space-key=\"ENG\" /><ac:plain-text-link-body><![CDATA[Read me]]></ac:plain-text-link-body></ac:link>", "text": "[Read me](page:ENG/Guide)", "dropped": ("link:page",)},
    "attachment_link": {"source": "<ac:link><ri:attachment ri:filename=\"spec.pdf\" /><ac:plain-text-link-body><![CDATA[Spec]]></ac:plain-text-link-body></ac:link>", "text": "[Spec](attachment:spec.pdf)", "dropped": ("link:attachment",)},
    "anchor_link": {"source": "<ac:link ac:anchor=\"sec-1\"><ac:plain-text-link-body><![CDATA[Jump]]></ac:plain-text-link-body></ac:link>", "text": "[Jump](#sec-1)", "dropped": ("link:anchor",)},
    "mention_hidden": {"source": "<p>Hello <ac:link><ri:user ri:account-id=\"abc-123\" /></ac:link></p>", "text": "Hello @user", "dropped": ("mention",), "show_mentions": False},
    "mention_shown": {"source": "<p>Hello <ac:link><ri:user ri:account-id=\"abc-123\" /></ac:link></p>", "text": "Hello @<abc-123>", "dropped": ("mention",), "show_mentions": True},
    "task_list": {"source": "<ac:task-list><ac:task><ac:task-id>1</ac:task-id><ac:task-status>incomplete</ac:task-status><ac:task-body>todo</ac:task-body></ac:task><ac:task><ac:task-id>2</ac:task-id><ac:task-status>complete</ac:task-status><ac:task-body>done</ac:task-body></ac:task></ac:task-list>", "text": "- [ ] todo\n- [x] done", "dropped": ()},
    "code_macro": {"source": "<ac:structured-macro ac:name=\"code\"><ac:parameter ac:name=\"language\">python</ac:parameter><ac:plain-text-body><![CDATA[print(1)]]></ac:plain-text-body></ac:structured-macro>", "text": "```python\nprint(1)\n```", "dropped": ()},
    "info_macro": {"source": "<ac:structured-macro ac:name=\"info\"><ac:rich-text-body><p>Heads up</p></ac:rich-text-body></ac:structured-macro>", "text": "> [!NOTE]\n> Heads up", "dropped": ()},
    "note_macro": {"source": "<ac:structured-macro ac:name=\"note\"><ac:rich-text-body><p>Important</p></ac:rich-text-body></ac:structured-macro>", "text": "> [!IMPORTANT]\n> Important", "dropped": ()},
    "warning_macro": {"source": "<ac:structured-macro ac:name=\"warning\"><ac:rich-text-body><p>Careful</p></ac:rich-text-body></ac:structured-macro>", "text": "> [!WARNING]\n> Careful", "dropped": ()},
    "tip_macro": {"source": "<ac:structured-macro ac:name=\"tip\"><ac:rich-text-body><p>Helpful</p></ac:rich-text-body></ac:structured-macro>", "text": "> [!TIP]\n> Helpful", "dropped": ()},
    "panel_macro": {"source": "<ac:structured-macro ac:name=\"panel\"><ac:parameter ac:name=\"title\">T</ac:parameter><ac:rich-text-body><p>P</p></ac:rich-text-body></ac:structured-macro>", "text": "> P", "dropped": ("macro:panel",)},
    "quote_macro": {"source": "<ac:structured-macro ac:name=\"quote\"><ac:rich-text-body><p>P</p></ac:rich-text-body></ac:structured-macro>", "text": "> P", "dropped": ()},
    "status_macro": {"source": "<ac:structured-macro ac:name=\"status\"><ac:parameter ac:name=\"title\">LIVE</ac:parameter></ac:structured-macro>", "text": "[LIVE]", "dropped": ("macro:status",)},
    "toc_macro": {"source": "<ac:structured-macro ac:name=\"toc\" />", "text": "", "dropped": ("macro:toc",)},
    "image_url": {"source": "<p><ac:image ac:alt=\"Pic\"><ri:url ri:value=\"https://example.com/a.png\" /></ac:image></p>", "text": "![Pic](https://example.com/a.png)", "dropped": ()},
    "image_attachment": {"source": "<p><ac:image ac:alt=\"Pic\"><ri:attachment ri:filename=\"pic.png\" /></ac:image></p>", "text": "![Pic](pic.png)", "dropped": ()},
    "table_with_header": {"source": "<table><tbody><tr><th>A</th><th>B</th></tr><tr><td>x</td><td>y</td></tr></tbody></table>", "text": "| A | B |\n| --- | --- |\n| x | y |", "dropped": ()},
    "table_without_header": {"source": "<table><tbody><tr><td>x</td><td>y</td></tr></tbody></table>", "text": "|  |  |\n| --- | --- |\n| x | y |", "dropped": ()},
    "table_merged_cells": {"source": "<table><tbody><tr><th>A</th><th>B</th></tr><tr><td colspan=\"2\">x</td></tr></tbody></table>", "text": "| A | B |\n| --- | --- |\n| x |  |", "dropped": ("table:merged-cells",)},
    "table_rich_cells": {"source": "<table><tbody><tr><th>A</th></tr><tr><td><ul><li>x</li></ul></td></tr></tbody></table>", "text": "| A |\n| --- |\n| - x |", "dropped": ("table:rich-cells",)},
    "emoticon": {"source": "<p><ac:emoticon ac:name=\"smile\" ac:emoji-fallback=\"🙂\" /></p>", "text": "🙂", "dropped": ("emoticon",)},
    "time": {"source": "<p><time datetime=\"2026-10-15\">15 Oct</time></p>", "text": "2026-10-15", "dropped": ("time",)},
    "adf_extension": {"source": "<ac:adf-extension><ac:adf-fallback><p>Fallback</p></ac:adf-fallback></ac:adf-extension>", "text": "Fallback", "dropped": ("adf-extension",)},
    "layout": {"source": "<ac:layout><ac:layout-section><ac:layout-cell><p>A</p></ac:layout-cell><ac:layout-cell><p>B</p></ac:layout-cell></ac:layout-section></ac:layout>", "text": "A\n\nB", "dropped": ("layout",)},
    "inline_comment": {"source": "<p>Hi <ac:inline-comment-marker>there</ac:inline-comment-marker></p>", "text": "Hi there", "dropped": ("inline-comment",)},
    "unknown_html": {"source": "<font color=\"red\">x</font>", "text": "x", "dropped": ("html:font",)},
    "unknown_ac_tag": {"source": "<ac:widget>text</ac:widget>", "text": "text", "dropped": ("tag:widget",)},
    "code_macro_extra_params": {"source": "<ac:structured-macro ac:name=\"code\"><ac:parameter ac:name=\"language\">python</ac:parameter><ac:parameter ac:name=\"title\">Snippet</ac:parameter><ac:plain-text-body><![CDATA[print(1)]]></ac:plain-text-body></ac:structured-macro>", "text": "```python\nprint(1)\n```", "dropped": ("macro:code",)},
    "info_macro_extra_params": {"source": "<ac:structured-macro ac:name=\"info\"><ac:parameter ac:name=\"title\">Heads up</ac:parameter><ac:rich-text-body><p>Body</p></ac:rich-text-body></ac:structured-macro>", "text": "> [!NOTE]\n> Body", "dropped": ("macro:info",)},
    "image_extra_attrs": {"source": "<p><ac:image ac:alt=\"Pic\" ac:width=\"500\"><ri:attachment ri:filename=\"pic.png\" /></ac:image></p>", "text": "![Pic](pic.png)", "dropped": ("formatting:image",)},
    "table_page_link_and_mention": {"source": "<table><tbody><tr><th>A</th><th>B</th></tr><tr><td><ac:link><ri:page ri:content-title=\"Guide\" /></ac:link></td><td><ac:link><ri:user ri:account-id=\"abc-123\" /></ac:link></td></tr></tbody></table>", "text": "| A | B |\n| --- | --- |\n| [Guide](page:Guide) | @user |", "dropped": ("link:page", "mention")},
    "paragraph_align": {"source": "<p style=\"text-align: center;\">Centered</p>", "text": "Centered", "dropped": ("formatting:align",)},
    "list_formatting": {"source": "<ol type=\"a\"><li>one</li></ol>", "text": "1. one", "dropped": ("formatting:list",)},
    "table_row_headers": {"source": "<table><tbody><tr><th>A</th><th>B</th></tr><tr><th>R</th><td>x</td></tr></tbody></table>", "text": "| A | B |\n| --- | --- |\n| R | x |", "dropped": ("table:row-headers",)},
    "malformed_truncated": {"source": "<p>Start <strong>bold", "text": "Start **bold**", "dropped": ()},
}


def _make_storage_markdown_test(case: dict[str, object]):
    def test(self: ConverterTestCase) -> None:
        converted = storage_to_markdown(case["source"], show_mentions=case.get("show_mentions", False))  # type: ignore[index]
        self.assertEqual(converted.text, case["text"])
        self.assertEqual(converted.dropped, case["dropped"])
        self.assertEqual(lossy_constructs(case["source"]), case["dropped"])  # type: ignore[index]

    return test


for _name, _case in STORAGE_MARKDOWN_CASES.items():
    setattr(StorageToMarkdownCaseTest, f"test_{_name}", _make_storage_markdown_test(_case))


class StorageToTextCaseTest(ConverterTestCase):
    pass


STORAGE_TEXT_CASES = {
    "paragraph": {"source": "<p>Hello world</p>", "text": "Hello world"},
    "link": {"source": "<p><a href=\"https://example.com\">site</a></p>", "text": "site (https://example.com)"},
    "internal_link": {"source": "<ac:link><ri:page ri:content-title=\"Guide\" /></ac:link>", "text": "Guide"},
    "mention_hidden": {"source": "<p>Hello <ac:link><ri:user ri:account-id=\"abc-123\" /></ac:link></p>", "text": "Hello @user", "show_mentions": False},
    "mention_shown": {"source": "<p>Hello <ac:link><ri:user ri:account-id=\"abc-123\" /></ac:link></p>", "text": "Hello @<abc-123>", "show_mentions": True},
    "task_list": {"source": "<ac:task-list><ac:task><ac:task-id>1</ac:task-id><ac:task-status>complete</ac:task-status><ac:task-body>done</ac:task-body></ac:task></ac:task-list>", "text": "- [x] done"},
    "code_macro": {"source": "<ac:structured-macro ac:name=\"code\"><ac:plain-text-body><![CDATA[line 1\nline 2]]></ac:plain-text-body></ac:structured-macro>", "text": "line 1\nline 2"},
    "status_macro": {"source": "<ac:structured-macro ac:name=\"status\"><ac:parameter ac:name=\"title\">LIVE</ac:parameter></ac:structured-macro>", "text": "[LIVE]"},
    "table": {"source": "<table><tbody><tr><th>A</th><th>B</th></tr><tr><td>x</td><td>y</td></tr></tbody></table>", "text": "A | B\nx | y"},
    "image": {"source": "<p><ac:image ac:alt=\"Pic\"><ri:attachment ri:filename=\"pic.png\" /></ac:image></p>", "text": "Pic"},
    "layout": {"source": "<ac:layout><ac:layout-section><ac:layout-cell><p>A</p></ac:layout-cell><ac:layout-cell><p>B</p></ac:layout-cell></ac:layout-section></ac:layout>", "text": "A\n\nB"},
    "malformed": {"source": "<p>Open <em>tag", "text": "Open tag"},
}


def _make_storage_text_test(case: dict[str, object]):
    def test(self: ConverterTestCase) -> None:
        rendered = storage_to_text(case["source"], show_mentions=case.get("show_mentions", False))  # type: ignore[index]
        self.assertEqual(rendered, case["text"])

    return test


for _name, _case in STORAGE_TEXT_CASES.items():
    setattr(StorageToTextCaseTest, f"test_{_name}", _make_storage_text_test(_case))


class RoundTripAndRobustnessTest(ConverterTestCase):
    def test_supported_heading_round_trip_is_stable(self) -> None:
        self.assert_stable_markdown("# Title\n\nBody\n")

    def test_supported_alert_round_trip_is_stable(self) -> None:
        self.assert_stable_markdown("> [!NOTE]\n> body\n")

    def test_supported_code_round_trip_is_stable(self) -> None:
        self.assert_stable_markdown("```py\nprint(1)\n```\n")

    def test_supported_table_round_trip_is_stable(self) -> None:
        self.assert_stable_markdown("| A | B |\n| --- | --- |\n| x | y |\n")

    def test_supported_link_round_trip_is_stable(self) -> None:
        self.assert_stable_markdown("[site](https://example.com)\n")

    def test_supported_image_round_trip_is_stable(self) -> None:
        self.assert_stable_markdown("![Pic](pic.png)\n")

    def test_supported_task_list_round_trip_is_stable(self) -> None:
        self.assert_stable_markdown("- [ ] todo\n- [x] done\n")

    def test_supported_quote_round_trip_is_stable(self) -> None:
        self.assert_stable_markdown("> quote\n")

    def test_supported_paragraph_round_trip_is_stable(self) -> None:
        self.assert_stable_markdown("plain text\n")

    def test_supported_inline_formatting_round_trip_is_stable(self) -> None:
        self.assert_stable_markdown("**bold** *em* `code`\n")

    def test_markdown_cases_ignore_trailing_newlines_and_crlf(self) -> None:
        for name, case in MARKDOWN_CASES.items():
            with self.subTest(case=name):
                self.assert_markdown_trailing_newlines_do_not_matter(case["source"])

    def test_all_sample_markdown_outputs_are_xml_well_formed(self) -> None:
        for case in MARKDOWN_CASES.values():
            source = case["source"]
            rendered = markdown_to_storage(source)  # type: ignore[arg-type]
            if rendered:
                self.assert_xml_fragment(rendered)

    def test_nasty_inputs_are_xml_well_formed(self) -> None:
        nasty = [
            "`unfinished",
            "[broken](https://example.com",
            "***oops**",
            "```\n]]>\n",
            "<script>alert(1)</script>",
            "& && &bogus; &#x41;",
            "A\x00B\x01C",
            "x" * 50000,
            "".join("> " for _ in range(30)) + "deep\n",
            "".join("  " * level + "- item\n" for level in range(30)),
            "",
            " \n\t\n",
            "# Title\r\n\r\nBody\r\n",
        ]
        for text in nasty:
            with self.subTest(text=text[:20]):
                rendered = markdown_to_storage(text)
                if rendered:
                    self.assert_xml_fragment(rendered)

    def test_raw_html_never_reaches_output_unescaped(self) -> None:
        rendered = markdown_to_storage("<script>bad()</script>\n<div>x</div>\n")
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<div>", rendered)
        self.assertIn("&lt;script&gt;bad()&lt;/script&gt;", rendered)
        self.assertIn("&lt;div&gt;x&lt;/div&gt;", rendered)

    def test_lossy_constructs_matches_dropped_for_mixed_sample(self) -> None:
        storage = (
            '<ac:layout><ac:layout-cell><p>A</p></ac:layout-cell></ac:layout>'
            '<ac:structured-macro ac:name="status"><ac:parameter ac:name="title">LIVE</ac:parameter></ac:structured-macro>'
            '<ac:link><ri:page ri:content-title="Guide" /></ac:link>'
        )
        converted = storage_to_markdown(storage)
        self.assertEqual(lossy_constructs(storage), converted.dropped)
        self.assertEqual(converted.dropped, ("layout", "link:page", "macro:status"))

    def test_show_mentions_changes_markdown_only_for_account_ids(self) -> None:
        storage = "<p>Hello <ac:link><ri:user ri:account-id=\"abc-123\" /></ac:link></p>"
        self.assertEqual(storage_to_markdown(storage, show_mentions=False).text, "Hello @user")
        self.assertEqual(storage_to_markdown(storage, show_mentions=True).text, "Hello @<abc-123>")

    def test_show_mentions_changes_text_only_for_account_ids(self) -> None:
        storage = "<p>Hello <ac:link><ri:user ri:account-id=\"abc-123\" /></ac:link></p>"
        self.assertEqual(storage_to_text(storage, show_mentions=False), "Hello @user")
        self.assertEqual(storage_to_text(storage, show_mentions=True), "Hello @<abc-123>")

    def test_markdown_converter_never_raises_for_random_garbage(self) -> None:
        rng = random.Random(71337)
        alphabet = "[]()<>*&_~`|/\\abc123 \n\t\x00\x01"
        for index in range(80):
            text = "".join(rng.choice(alphabet) for _ in range(200 + index))
            rendered = markdown_to_storage(text)
            if rendered:
                self.assert_xml_fragment(rendered)

    def test_storage_converter_never_raises_for_random_garbage(self) -> None:
        rng = random.Random(88001)
        alphabet = "<>/=\":;abc123 \n\t"
        for index in range(80):
            text = "".join(rng.choice(alphabet) for _ in range(240 + index))
            converted = storage_to_markdown(text, show_mentions=bool(index % 2))
            plain = storage_to_text(text, show_mentions=bool(index % 2))
            self.assertIsInstance(converted.text, str)
            self.assertIsInstance(converted.dropped, tuple)
            self.assertIsInstance(plain, str)

    def test_large_markdown_document_finishes_quickly(self) -> None:
        paragraph = "Some **bold** text with [a link](https://example.com).\n"
        text = "".join(
            "# Heading {0}\n\n{1}\n- item {0}\n- [ ] task {0}\n\n| A | B |\n| --- | --- |\n| {0} | x |\n\n".format(index, paragraph)
            for index in range(400)
        )
        start = time.perf_counter()
        rendered = markdown_to_storage(text)
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 5.0)
        self.assert_xml_fragment(rendered)

    def test_large_storage_document_finishes_quickly(self) -> None:
        block = (
            "<h2>Heading</h2><p>Some <strong>bold</strong> text with <a href=\"https://example.com\">a link</a>.</p>"
            "<ac:task-list><ac:task><ac:task-id>1</ac:task-id><ac:task-status>incomplete</ac:task-status><ac:task-body>todo</ac:task-body></ac:task></ac:task-list>"
            "<table><tbody><tr><th>A</th><th>B</th></tr><tr><td>x</td><td>y</td></tr></tbody></table>"
        )
        storage = block * 500
        start = time.perf_counter()
        converted = storage_to_markdown(storage)
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 5.0)
        self.assertTrue(converted.text)

    def test_nested_lists_render_with_relative_indentation(self) -> None:
        storage = "<ol><li>one<ul><li>nested<ol><li>deep</li></ol></li></ul></li><li>two</li></ol>"
        self.assertEqual(storage_to_markdown(storage).text, "1. one\n    - nested\n        1. deep\n2. two")

    def test_nested_lists_round_trip_back_to_same_nesting(self) -> None:
        markdown = "1. one\n    - nested\n        1. deep\n2. two"
        storage = markdown_to_storage(markdown)
        self.assertEqual(storage_to_markdown(storage).text, markdown)
        self.assert_canonical_equal(storage, markdown_to_storage(storage_to_markdown(storage).text))

    def test_nested_task_lists_inside_lists_do_not_gain_blank_lines(self) -> None:
        storage = "<ul><li><p>parent</p><ac:task-list><ac:task><ac:task-id>1</ac:task-id><ac:task-status>incomplete</ac:task-status><ac:task-body>todo</ac:task-body></ac:task></ac:task-list></li></ul>"
        self.assertEqual(storage_to_markdown(storage).text, "- parent\n    - [ ] todo")
        self.assertEqual(storage_to_text(storage), "- parent\n    - [ ] todo")

    def test_nested_list_only_item_stays_nested_without_extra_blank_lines(self) -> None:
        storage = "<ul><li><ul><li>nested</li></ul></li></ul>"
        self.assertEqual(storage_to_markdown(storage).text, "-\n    - nested")

    def test_long_lists_keep_stable_numbering(self) -> None:
        items = "".join(f"<li>item {index}</li>" for index in range(1, 13))
        storage = f"<ol>{items}</ol>"
        lines = storage_to_markdown(storage).text.splitlines()
        self.assertEqual(lines[0], "1. item 1")
        self.assertEqual(lines[-1], "12. item 12")
        self.assertEqual(storage_to_markdown(markdown_to_storage(storage_to_markdown(storage).text)).text, storage_to_markdown(storage).text)

    def test_table_cells_keep_inline_constructs_and_record_losses(self) -> None:
        storage = (
            "<table><tbody><tr><th><strong>H</strong></th><th>B</th></tr>"
            "<tr><td><a href=\"https://example.com\">site</a></td>"
            "<td><ac:link><ri:user ri:account-id=\"abc-123\" /></ac:link></td></tr></tbody></table>"
        )
        converted = storage_to_markdown(storage)
        self.assertEqual(converted.text, "| **H** | B |\n| --- | --- |\n| [site](https://example.com) | @user |")
        self.assertEqual(converted.dropped, ("mention",))

    def test_table_cells_with_block_content_are_marked_rich_and_keep_macro_names(self) -> None:
        storage = (
            "<table><tbody><tr><th>A</th></tr>"
            "<tr><td><ac:structured-macro ac:name=\"status\"><ac:parameter ac:name=\"title\">LIVE</ac:parameter></ac:structured-macro></td></tr>"
            "<tr><td><ul><li>x</li></ul></td></tr></tbody></table>"
        )
        converted = storage_to_markdown(storage)
        self.assertIn("[LIVE]", converted.text)
        self.assertEqual(converted.dropped, ("macro:status", "table:rich-cells"))

    def test_pre_inside_list_item_does_not_raise(self) -> None:
        storage = "<ul><li>item<pre>code\nblock</pre></li></ul>"
        converted = storage_to_markdown(storage)
        self.assertIn("```", converted.text)
        self.assertTrue(converted.text.startswith("- item"))

    def test_code_macro_inside_table_cell_marks_the_cell_rich(self) -> None:
        storage = "<table><tbody><tr><th>A</th></tr><tr><td><ac:structured-macro ac:name=\"code\"><ac:plain-text-body><![CDATA[x = 1]]></ac:plain-text-body></ac:structured-macro></td></tr></tbody></table>"
        converted = storage_to_markdown(storage)
        self.assertIn("```", converted.text)
        self.assertEqual(converted.dropped, ("table:rich-cells",))

    def test_nbsp_only_and_empty_paragraphs_are_skipped(self) -> None:
        self.assertEqual(storage_to_markdown("<p>&nbsp;</p><p></p><p>x</p>").text, "x")

    def test_storage_with_windows_line_endings_is_normalized(self) -> None:
        self.assertEqual(storage_to_markdown("<h1>Title</h1>\r\n<p>Body</p>").text, "# Title\n\nBody")

    def test_deeply_nested_storage_does_not_raise(self) -> None:
        storage = "leaf"
        for _ in range(200):
            storage = f"<blockquote>{storage}</blockquote>"
        with self.assertRaises(ValidationError):
            storage_to_markdown(storage)

    def test_documents_ending_in_supported_constructs_are_unchanged_by_trailing_newlines(self) -> None:
        samples = (
            "- First\n- Second",
            "1. First\n2. Second",
            "1. First\n    - Nested\n        1. Deep",
            "- [ ] First\n- [x] Second",
            "> Quote",
            "> [!NOTE]\n> Alert",
            "| A | B |\n| --- | --- |\n| x | y |",
            "```python\nprint(1)\n```",
            "---",
            "# Heading",
            "Paragraph",
        )
        for sample in samples:
            with self.subTest(sample=sample.splitlines()[0]):
                self.assert_markdown_trailing_newlines_do_not_matter(sample)

    def test_storage_to_markdown_text_has_no_trailing_newline(self) -> None:
        for sample in SoundnessCorpusTest.CORPUS:
            with self.subTest(sample=sample["name"]):
                text = storage_to_markdown(sample["storage"]).text
                self.assertEqual(text, text.rstrip("\n"))

    def test_storage_markdown_text_is_stable_with_final_newline(self) -> None:
        for sample in SoundnessCorpusTest.CORPUS:
            with self.subTest(sample=sample["name"]):
                converted = storage_to_markdown(sample["storage"])
                self.assertEqual(storage_to_markdown(markdown_to_storage(converted.text)).text, storage_to_markdown(markdown_to_storage(converted.text + "\n")).text)


if __name__ == "__main__":
    unittest.main()


class HardeningTest(unittest.TestCase):
    """What a page written by somebody else, or a Markdown file from anywhere, must not be able to do."""

    def test_a_link_to_a_script_or_a_data_address_loses_its_link_and_keeps_its_text(self):
        for destination in ("javascript:alert(1)", "JaVaScRiPt:alert(1)", "java\tscript:alert(1)", " javascript:alert(1)", "data:text/html;base64,PHNjcmlwdD4=", "vbscript:x", "file:///etc/passwd"):
            with self.subTest(destination=destination):
                self.assertEqual(markdown_to_storage(f"[click me]({destination}) after"), "<p>click me after</p>")

    def test_safe_destinations_stay_links(self):
        for destination in ("https://example.com/a?b=1&c=2", "http://example.com", "mailto:user@example.com", "tel:+4930123", "ftp://example.com/x", "/wiki/spaces/ENG", "page.html", "#anchor", "../up/down"):
            with self.subTest(destination=destination):
                self.assertIn("<a href=", markdown_to_storage(f"[text]({destination})"))

    def test_an_image_from_a_script_or_data_address_becomes_its_alternative_text(self):
        for source in ("javascript:alert(1)", "data:image/svg+xml;base64,PHN2Zz4="):
            with self.subTest(source=source):
                self.assertEqual(markdown_to_storage(f"![the picture]({source})"), "<p>the picture</p>")
        self.assertIn("<ri:url", markdown_to_storage("![x](https://example.com/x.png)"))
        self.assertIn("<ri:attachment", markdown_to_storage("![x](diagram.png)"))

    def test_a_reference_link_is_checked_like_any_other(self):
        self.assertEqual(markdown_to_storage("[text][r]\n\n[r]: javascript:alert(1)"), "<p>text</p>")

    def test_a_table_may_have_a_short_delimiter_row(self):
        for delimiter in ("|:--|--:|", "|-|-|", "| :-: | --- |", "-|-"):
            with self.subTest(delimiter=delimiter):
                out = markdown_to_storage(f"| a | b |\n{delimiter}\n| 1 | 2 |")
                self.assertIn("<table>", out)
                self.assertIn("<th", out)
                self.assertIn("<td", out)

    def test_a_lone_rule_or_heading_underline_is_not_a_table(self):
        self.assertEqual(markdown_to_storage("Title\n---"), "<h2>Title</h2>")
        self.assertNotIn("<table>", markdown_to_storage("a | b\n---"))


class SoundnessCorpusTest(ConverterTestCase):
    CORPUS = (
        {"name": "paragraph", "storage": "<p>Hello world</p>", "dropped": ()},
        {"name": "heading_and_paragraph", "storage": "<h2>Title</h2><p>Body</p>", "dropped": ()},
        {"name": "inline_formatting", "storage": "<p>Some <strong>bold</strong> and <em>em</em>.</p>", "dropped": ()},
        {"name": "inline_code", "storage": "<p>Inline <code>x = 1</code> code</p>", "dropped": ()},
        {"name": "simple_link", "storage": "<p><a href=\"https://example.com\">site</a></p>", "dropped": ()},
        {"name": "link_with_title", "storage": "<p><a href=\"https://example.com\" title=\"Example\">site</a></p>", "dropped": ()},
        {"name": "blockquote", "storage": "<blockquote><p>quoted</p></blockquote>", "dropped": ()},
        {"name": "alert_info", "storage": "<ac:structured-macro ac:name=\"info\"><ac:rich-text-body><p>Heads up</p></ac:rich-text-body></ac:structured-macro>", "dropped": ()},
        {"name": "alert_tip", "storage": "<ac:structured-macro ac:name=\"tip\"><ac:rich-text-body><p>Helpful</p></ac:rich-text-body></ac:structured-macro>", "dropped": ()},
        {"name": "code_python", "storage": "<ac:structured-macro ac:name=\"code\"><ac:parameter ac:name=\"language\">python</ac:parameter><ac:plain-text-body><![CDATA[print(1)]]></ac:plain-text-body></ac:structured-macro>", "dropped": ()},
        {"name": "code_plain_with_cdata_split", "storage": "<ac:structured-macro ac:name=\"code\"><ac:plain-text-body><![CDATA[a]]]]><![CDATA[>b]]></ac:plain-text-body></ac:structured-macro>", "dropped": ()},
        {"name": "task_list", "storage": "<ac:task-list><ac:task><ac:task-id>1</ac:task-id><ac:task-status>incomplete</ac:task-status><ac:task-body>todo</ac:task-body></ac:task><ac:task><ac:task-id>2</ac:task-id><ac:task-status>complete</ac:task-status><ac:task-body>done</ac:task-body></ac:task></ac:task-list>", "dropped": ()},
        {"name": "table_simple", "storage": "<table><tbody><tr><th>A</th><th>B</th></tr><tr><td>x</td><td>y</td></tr></tbody></table>", "dropped": ()},
        {"name": "table_inline", "storage": "<table><tbody><tr><th><strong>A</strong></th><th>B</th></tr><tr><td><a href=\"https://example.com\">site</a></td><td><code>x</code></td></tr></tbody></table>", "dropped": ()},
        {"name": "image_url", "storage": "<p><ac:image ac:alt=\"Pic\"><ri:url ri:value=\"https://example.com/a.png\" /></ac:image></p>", "dropped": ()},
        {"name": "image_attachment", "storage": "<p><ac:image ac:alt=\"Pic\"><ri:attachment ri:filename=\"pic.png\" /></ac:image></p>", "dropped": ()},
        {"name": "hr", "storage": "<hr />", "dropped": ()},
        {"name": "ordered_start", "storage": "<ol start=\"3\"><li>three</li><li>four</li></ol>", "dropped": ()},
        {"name": "nested_list", "storage": "<ol><li>one<ul><li>nested<ol><li>deep</li></ol></li></ul></li><li>two</li></ol>", "dropped": ()},
        {"name": "mention", "storage": "<p>Hello <ac:link><ri:user ri:account-id=\"abc-123\" /></ac:link></p>", "dropped": ("mention",)},
        {"name": "page_link", "storage": "<ac:link><ri:page ri:content-title=\"Guide\" ri:space-key=\"ENG\" /><ac:plain-text-link-body><![CDATA[Read me]]></ac:plain-text-link-body></ac:link>", "dropped": ("link:page",)},
        {"name": "attachment_link", "storage": "<ac:link><ri:attachment ri:filename=\"spec.pdf\" /><ac:plain-text-link-body><![CDATA[Spec]]></ac:plain-text-link-body></ac:link>", "dropped": ("link:attachment",)},
        {"name": "anchor_link", "storage": "<ac:link ac:anchor=\"sec-1\"><ac:plain-text-link-body><![CDATA[Jump]]></ac:plain-text-link-body></ac:link>", "dropped": ("link:anchor",)},
        {"name": "status_macro", "storage": "<ac:structured-macro ac:name=\"status\"><ac:parameter ac:name=\"title\">LIVE</ac:parameter></ac:structured-macro>", "dropped": ("macro:status",)},
        {"name": "jira_macro", "storage": "<ac:structured-macro ac:name=\"jira\" />", "dropped": ("macro:jira",)},
        {"name": "toc_macro", "storage": "<ac:structured-macro ac:name=\"toc\" />", "dropped": ("macro:toc",)},
        {"name": "expand_macro", "storage": "<ac:structured-macro ac:name=\"expand\"><ac:rich-text-body><p>More</p></ac:rich-text-body></ac:structured-macro>", "dropped": ("macro:expand",)},
        {"name": "layout", "storage": "<ac:layout><ac:layout-section><ac:layout-cell><p>A</p></ac:layout-cell><ac:layout-cell><p>B</p></ac:layout-cell></ac:layout-section></ac:layout>", "dropped": ("layout",)},
        {"name": "inline_comment", "storage": "<p>Hi <ac:inline-comment-marker>there</ac:inline-comment-marker></p>", "dropped": ("inline-comment",)},
        {"name": "adf_extension", "storage": "<ac:adf-extension><ac:adf-fallback><p>Fallback</p></ac:adf-fallback></ac:adf-extension>", "dropped": ("adf-extension",)},
        {"name": "emoticon", "storage": "<p><ac:emoticon ac:name=\"smile\" ac:emoji-fallback=\"🙂\" /></p>", "dropped": ("emoticon",)},
        {"name": "time", "storage": "<p><time datetime=\"2026-10-15\">15 Oct</time></p>", "dropped": ("time",)},
        {"name": "image_formatting", "storage": "<p><ac:image ac:alt=\"Pic\" ac:width=\"400\"><ri:attachment ri:filename=\"pic.png\" /></ac:image></p>", "dropped": ("formatting:image",)},
        {"name": "code_extra_params", "storage": "<ac:structured-macro ac:name=\"code\"><ac:parameter ac:name=\"language\">python</ac:parameter><ac:parameter ac:name=\"title\">Snippet</ac:parameter><ac:plain-text-body><![CDATA[print(1)]]></ac:plain-text-body></ac:structured-macro>", "dropped": ("macro:code",)},
        {"name": "info_with_title", "storage": "<ac:structured-macro ac:name=\"info\"><ac:parameter ac:name=\"title\">Heads up</ac:parameter><ac:rich-text-body><p>Body</p></ac:rich-text-body></ac:structured-macro>", "dropped": ("macro:info",)},
        {"name": "panel_with_title", "storage": "<ac:structured-macro ac:name=\"panel\"><ac:parameter ac:name=\"title\">Panel</ac:parameter><ac:rich-text-body><p>Body</p></ac:rich-text-body></ac:structured-macro>", "dropped": ("macro:panel",)},
        {"name": "paragraph_align", "storage": "<p style=\"text-align: center;\">Centered</p>", "dropped": ("formatting:align",)},
        {"name": "list_formatting", "storage": "<ol type=\"a\"><li>one</li></ol>", "dropped": ("formatting:list",)},
        {"name": "table_merged", "storage": "<table><tbody><tr><th>A</th><th>B</th></tr><tr><td colspan=\"2\">x</td></tr></tbody></table>", "dropped": ("table:merged-cells",)},
        {"name": "table_rich", "storage": "<table><tbody><tr><th>A</th></tr><tr><td><ul><li>x</li></ul></td></tr></tbody></table>", "dropped": ("table:rich-cells",)},
        {"name": "table_row_headers", "storage": "<table><tbody><tr><th>A</th><th>B</th></tr><tr><th>R</th><td>x</td></tr></tbody></table>", "dropped": ("table:row-headers",)},
        {"name": "table_page_link_cell", "storage": "<table><tbody><tr><th>A</th></tr><tr><td><ac:link><ri:page ri:content-title=\"Guide\" /></ac:link></td></tr></tbody></table>", "dropped": ("link:page",)},
        {"name": "table_mention_cell", "storage": "<table><tbody><tr><th>A</th></tr><tr><td><ac:link><ri:user ri:account-id=\"abc-123\" /></ac:link></td></tr></tbody></table>", "dropped": ("mention",)},
        {"name": "unknown_html", "storage": "<font color=\"red\">x</font>", "dropped": ("html:font",)},
        {"name": "unknown_ac_tag", "storage": "<ac:widget>text</ac:widget>", "dropped": ("tag:widget",)},
        {"name": "colored_cell", "storage": "<table><tbody><tr><th>A</th></tr><tr><td data-highlight-colour=\"red\">x</td></tr></tbody></table>", "dropped": ("formatting:color",)},
    )

    def test_storage_samples_are_sound(self) -> None:
        self.assertGreaterEqual(len(self.CORPUS), 40)
        benign_structure = {"nested_list"}
        for sample in self.CORPUS:
            with self.subTest(sample=sample["name"]):
                converted = storage_to_markdown(sample["storage"])
                self.assertEqual(converted.text, converted.text.rstrip("\n"))
                self.assert_markdown_trailing_newlines_do_not_matter(converted.text)
                roundtrip = markdown_to_storage(converted.text)
                self.assert_xml_fragment(roundtrip)
                self.assertEqual(converted.dropped, sample["dropped"])
                if converted.dropped:
                    continue
                if sample["name"] not in benign_structure:
                    self.assert_canonical_equal(sample["storage"], roundtrip)
                second = storage_to_markdown(roundtrip)
                self.assertEqual(second.dropped, ())
                self.assertEqual(second.text, converted.text)
                self.assertEqual(storage_to_markdown(markdown_to_storage(converted.text + "\n")).text, converted.text)


MARKDOWN_CORPUS = {
    "heading levels": "# One\n\n## Two\n\n### Three\n\n#### Four\n\n##### Five\n\n###### Six\n",
    "emphasis mix": "*a* **b** ***c*** _d_ __e__ ~~f~~ `g` **bold `code` inside** *it **nested** alic*\n",
    "bullet list nested": "- a\n  - b\n    - c\n- d\n",
    "ordered list start": "3. three\n4. four\n   1. nested one\n   2. nested two\n5. five\n",
    "list with paragraphs": "- first\n\n  second paragraph\n\n- next\n",
    "list with code": "1. Step one\n\n   ```bash\n   a\n   b\n   ```\n\n2. Step two\n",
    "bullet list with code": "- item\n\n  ```python\n  print(1)\n  ```\n",
    "code with blank lines": "```\nfirst\n\n\nlast\n```\n",
    "code leading trailing blank": "```\n\nx\n\n```\n",
    "code with tabs": "```\n\tindented\n```\n",
    "indented code": "    code line 1\n    code line 2\n",
    "yaml in fence": "```yaml\n---\nkey: value\n---\n```\n",
    "fence after paragraph": "Text\n```\ncode\n```\n",
    "quote with list": "> intro\n>\n> - a\n> - b\n",
    "quote nested": "> a\n>> b\n",
    "quote with code": "> ```\n> code\n> ```\n",
    "table basic": "| a | b |\n|---|---|\n| 1 | 2 |\n",
    "table align": "| a | b | c |\n|:--|:-:|--:|\n| 1 | 2 | 3 |\n",
    "table inline": "| `code` | [link](https://x.test) | **bold** |\n|---|---|---|\n| a\\|b | ![i](p.png) | x |\n",
    "link title": "[a](https://x.test \"Title\")\n",
    "link ref": "[a][r]\n\n[r]: https://x.test\n",
    "image": "![alt text](diagram.png)\n",
    "image url": "![alt](https://x.test/i.png)\n",
    "autolink": "<https://x.test/a?b=1&c=2>\n",
    "bare url": "go to https://x.test/a now\n",
    "email autolink": "<user@example.com>\n",
    "hard break": "line one  \nline two\\\nline three\n",
    "hr variants": "a\n\n---\n\n***\n\n___\n\nb\n",
    "html comment": "a\n\n<!-- note -->\n\nb\n",
    "inline html": "a <b>bold</b> <br> c\n",
    "task list": "- [ ] todo\n- [x] done\n",
    "alerts": "> [!NOTE]\n> Be careful.\n\n> [!WARNING]\n> Really.\n",
    "escapes": "\\*not em\\* \\# no heading \\[x\\] 1\\. no list\n",
    "entities": "&copy; &nbsp; &amp; &lt;tag&gt; &#169;\n",
    "unicode": "Grüße — naïve café ✓ 日本語 😀\n",
    "long paragraph": ("word " * 200).strip() + "\n",
    "setext": "Title\n=====\n\nSub\n-----\n",
    "numbers in text": "1986. A great year\n\nversion 2.0 - released\n",
    "star list": "* a\n* b\n",
    "plus list": "+ a\n+ b\n",
    "lazy continuation": "- item\ncontinued lazily\n",
    "heading with trailing hashes": "## Title ##\n",
    "emphasis intraword": "snake_case_name and 2*3*4\n",
    "backticks in code": "`` `x` `` and ```` ``` ````\n",
    "pipes outside table": "a | b | c\n",
    "definition like": "term\n: definition\n",
    "footnote like": "text[^1]\n\n[^1]: note\n",
    "nested quote list code": "> 1. a\n>    ```\n>    c\n>    ```\n",
}

STORAGE_CORPUS = {
    "plain": {"storage": "<p>Hello <strong>world</strong>, this is <em>text</em> with <code>code</code> and a <a href=\"https://x.test/a?b=1&amp;c=2\">link</a>.</p>", "accepted": ()},
    "headings": {"storage": "<h1>One</h1><p>a</p><h2>Two</h2><p>b</p><h3>Three</h3>", "accepted": ()},
    "nested lists": {"storage": "<ul><li>a<ul><li>b<ol><li>c</li><li>d</li></ol></li></ul></li><li>e</li></ul>", "accepted": ()},
    "list with paragraphs": {"storage": "<ul><li><p>first</p><p>second</p></li><li><p>third</p></li></ul>", "accepted": ()},
    "ordered start": {"storage": '<ol start="3"><li>three</li><li>four</li></ol>', "accepted": ()},
    "table": {"storage": "<table><tbody><tr><th>A</th><th>B</th></tr><tr><td>1</td><td><code>x</code> and <strong>y</strong></td></tr><tr><td colspan=\"1\"><p>p</p></td><td>4</td></tr></tbody></table>", "accepted": ()},
    "table with colgroup": {"storage": '<table><colgroup><col /><col /></colgroup><tbody><tr><th><p>A</p></th><th><p>B</p></th></tr><tr><td><p>1</p></td><td><p>2</p></td></tr></tbody></table>', "accepted": ()},
    "blockquote": {"storage": "<blockquote><p>quoted</p><ul><li>a</li></ul></blockquote>", "accepted": ()},
    "code macro": {"storage": '<ac:structured-macro ac:name="code" ac:schema-version="1"><ac:parameter ac:name="language">python</ac:parameter><ac:plain-text-body><![CDATA[def f():\n    return 1\n\nprint(f())]]></ac:plain-text-body></ac:structured-macro>', "accepted": ()},
    "code macro no lang": {"storage": '<ac:structured-macro ac:name="code" ac:schema-version="1"><ac:plain-text-body><![CDATA[plain text\n  indented]]></ac:plain-text-body></ac:structured-macro>', "accepted": ()},
    "noformat": {"storage": '<ac:structured-macro ac:name="noformat" ac:schema-version="1"><ac:plain-text-body><![CDATA[raw]]></ac:plain-text-body></ac:structured-macro>', "accepted": ("macro:noformat",)},
    "info panel": {"storage": '<ac:structured-macro ac:name="info" ac:schema-version="1"><ac:rich-text-body><p>Careful!</p><ul><li>a</li></ul></ac:rich-text-body></ac:structured-macro>', "accepted": ()},
    "note tip warning": {"storage": '<ac:structured-macro ac:name="note" ac:schema-version="1"><ac:rich-text-body><p>n</p></ac:rich-text-body></ac:structured-macro><ac:structured-macro ac:name="tip" ac:schema-version="1"><ac:rich-text-body><p>t</p></ac:rich-text-body></ac:structured-macro><ac:structured-macro ac:name="warning" ac:schema-version="1"><ac:rich-text-body><p>w</p></ac:rich-text-body></ac:structured-macro>', "accepted": ()},
    "toc macro": {"storage": '<ac:structured-macro ac:name="toc" ac:schema-version="1"></ac:structured-macro><p>after</p>', "accepted": ("macro:toc",)},
    "expand macro": {"storage": '<ac:structured-macro ac:name="expand" ac:schema-version="1"><ac:parameter ac:name="title">More</ac:parameter><ac:rich-text-body><p>hidden</p></ac:rich-text-body></ac:structured-macro>', "accepted": ("macro:expand",)},
    "status macro": {"storage": '<p>State: <ac:structured-macro ac:name="status" ac:schema-version="1"><ac:parameter ac:name="colour">Green</ac:parameter><ac:parameter ac:name="title">OK</ac:parameter></ac:structured-macro></p>', "accepted": ("macro:status",)},
    "page link": {"storage": '<p>See <ac:link><ri:page ri:content-title="Other Page" /><ac:link-body>this page</ac:link-body></ac:link>.</p>', "accepted": ("link:page",)},
    "page link no body": {"storage": '<p>See <ac:link><ri:page ri:content-title="Other Page" /></ac:link>.</p>', "accepted": ("link:page",)},
    "attachment link": {"storage": '<p><ac:link><ri:attachment ri:filename="spec.pdf" /><ac:link-body>the spec</ac:link-body></ac:link></p>', "accepted": ("link:attachment",)},
    "image attachment": {"storage": '<p><ac:image ac:alt="diagram"><ri:attachment ri:filename="diagram.png" /></ac:image></p>', "accepted": ()},
    "image url": {"storage": '<p><ac:image><ri:url ri:value="https://x.test/i.png" /></ac:image></p>', "accepted": ()},
    "user mention": {"storage": '<p>Hello <ac:link><ri:user ri:account-id="5b10ac8d82e05b22cc7d4ef5" /></ac:link>!</p>', "accepted": ("mention",)},
    "emoticon": {"storage": '<p>nice <ac:emoticon ac:name="smile" /> work</p>', "accepted": ("emoticon",)},
    "date": {"storage": '<p>Due <time datetime="2026-10-15" /> sharp</p>', "accepted": ("time",)},
    "task list": {"storage": "<ac:task-list><ac:task><ac:task-id>1</ac:task-id><ac:task-status>incomplete</ac:task-status><ac:task-body>do this</ac:task-body></ac:task><ac:task><ac:task-id>2</ac:task-id><ac:task-status>complete</ac:task-status><ac:task-body>done</ac:task-body></ac:task></ac:task-list>", "accepted": ()},
    "layout": {"storage": '<ac:layout><ac:layout-section ac:type="two_equal"><ac:layout-cell><p>left</p></ac:layout-cell><ac:layout-cell><p>right</p></ac:layout-cell></ac:layout-section></ac:layout>', "accepted": ("layout",)},
    "hr and br": {"storage": "<p>a<br />b</p><hr /><p>c</p>", "accepted": ()},
    "underline etc": {"storage": "<p><u>under</u> <s>strike</s> <sub>sub</sub> <sup>sup</sup> <span style=\"color: rgb(255,0,0);\">red</span></p>", "accepted": ("formatting:color", "formatting:subscript", "formatting:superscript", "formatting:underline")},
    "entities": {"storage": "<p>a&nbsp;b &ndash; c &rsquo;d&rsquo; &hellip; &copy; &lt;x&gt; &amp; &quot;q&quot;</p>", "accepted": ()},
    "literal markdown chars": {"storage": "<p>1. not a list - not a bullet # not a heading *not em* _x_ `tick` [br] | pipe \\ backslash &gt; quote</p>", "accepted": ()},
    "literal entity text": {"storage": "<p>The entity &amp;nbsp; and &amp;#169; and &amp;copy; are written like this</p>", "accepted": ()},
    "empty paragraphs": {"storage": "<p>a</p><p /><p>b</p><p>&nbsp;</p>", "accepted": ()},
    "inline comment marker": {"storage": '<p>some <ac:inline-comment-marker ac:ref="abc">marked</ac:inline-comment-marker> text</p>', "accepted": ("inline-comment",)},
    "jira macro": {"storage": '<ac:structured-macro ac:name="jira" ac:schema-version="1"><ac:parameter ac:name="key">ABC-1</ac:parameter></ac:structured-macro>', "accepted": ("macro:jira",)},
    "long text": {"storage": "<p>" + "Lorem ipsum dolor sit amet. " * 40 + "</p>", "accepted": ()},
    "url as text": {"storage": '<p><a href="https://a.test/x">https://a.test/x</a> and <a href="https://a.test/y">y</a></p>', "accepted": ()},
    "wikipedia link": {"storage": '<p><a href="https://en.wikipedia.org/wiki/Foo_(bar)">Foo</a> and <a href="https://en.wikipedia.org/wiki/Foo_(bar)">https://en.wikipedia.org/wiki/Foo_(bar)</a></p>', "accepted": ()},
}


class MarkdownCorpusTest(ConverterTestCase):
    def test_markdown_corpus_is_stable(self) -> None:
        self.assertGreaterEqual(len(MARKDOWN_CORPUS), 48)
        for name, markdown in MARKDOWN_CORPUS.items():
            with self.subTest(sample=name):
                s1 = markdown_to_storage(markdown)
                self.assert_xml_fragment(s1)
                converted = storage_to_markdown(s1)
                s2 = markdown_to_storage(converted.text)
                s3 = markdown_to_storage(storage_to_markdown(s2).text)
                self.assertEqual(s2, s3)
                stats1 = _storage_stats(s1)
                stats2 = _storage_stats(s2)
                self.assertFalse(stats1["nested_anchor"])
                self.assertFalse(stats2["nested_anchor"])
                self.assertEqual(stats1["text"], stats2["text"])
                self.assertEqual(stats1["hrefs"], stats2["hrefs"])
                self.assertEqual(stats1["counts"], stats2["counts"])
                if "macro:code" not in converted.dropped:
                    self.assertEqual(stats1["code_bodies"], stats2["code_bodies"])

    def test_project_documents_are_stable(self) -> None:
        root = Path(__file__).resolve().parents[2]
        files = [root / "README.md", *sorted((root / "docs").rglob("*.md")), *sorted((root / "examples").rglob("*.md")), root / "skills" / "conflu-c-cli" / "SKILL.md", root / "CHANGELOG.md"]
        for path in files:
            with self.subTest(path=path.name):
                body = parse_markdown_page(path.read_text(encoding="utf-8")).body
                s1 = markdown_to_storage(body)
                self.assert_xml_fragment(s1)
                converted = storage_to_markdown(s1)
                s2 = markdown_to_storage(converted.text)
                s3 = markdown_to_storage(storage_to_markdown(s2).text)
                self.assertEqual(s2, s3)
                stats1 = _storage_stats(s1)
                stats2 = _storage_stats(s2)
                self.assertFalse(stats1["nested_anchor"])
                self.assertFalse(stats2["nested_anchor"])
                self.assertEqual(stats1["text"], stats2["text"])
                self.assertEqual(stats1["hrefs"], stats2["hrefs"])
                self.assertEqual(stats1["counts"], stats2["counts"])
                if "macro:code" not in converted.dropped:
                    self.assertEqual(stats1["code_bodies"], stats2["code_bodies"])

    def test_storage_side_fuzz_stays_safe(self) -> None:
        rng = random.Random(20261015)
        macros = ("info", "warning", "tip", "note", "status", "jira")

        def fragment(depth: int) -> str:
            if depth >= 5:
                return rng.choice((
                    "<p>x</p>",
                    "<strong>x</strong>",
                    "<em>x</em>",
                    "<code>x</code>",
                    "&nbsp;",
                    "<ac:link><ri:page ri:content-title=\"T\" /></ac:link>",
                ))
            choice = rng.randrange(10)
            if choice == 0:
                return "<p>" + fragment(depth + 1) + "</p>"
            if choice == 1:
                return "<strong>" + fragment(depth + 1) + "</strong>"
            if choice == 2:
                return "<em>" + fragment(depth + 1) + "</em>"
            if choice == 3:
                return "<code>x</code>"
            if choice == 4:
                return "<ul><li>" + fragment(depth + 1) + "</li></ul>"
            if choice == 5:
                return "<ol><li>" + fragment(depth + 1) + "</li></ol>"
            if choice == 6:
                return "<table><tbody><tr><td>" + fragment(depth + 1) + "</td></tr></tbody></table>"
            if choice == 7:
                return f'<ac:structured-macro ac:name="{rng.choice(macros)}"><ac:rich-text-body><p>x</p></ac:rich-text-body></ac:structured-macro>'
            if choice == 8:
                return "<ac:link><ri:page ri:content-title=\"T\" /></ac:link>"
            return rng.choice(("&nbsp;", "&rsquo;", "&ndash;", "<![CDATA[x]]>", "plain"))

        for _ in range(300):
            storage = "".join(fragment(0) for _ in range(rng.randint(1, 4)))
            try:
                converted = storage_to_markdown(storage)
            except ValidationError:
                continue
            self.assert_xml_fragment(markdown_to_storage(converted.text))

    def test_markdown_hostile_inputs_finish_quickly(self) -> None:
        cases = {
            "*a pattern": "*a" * 100000,
            "**a* pattern": "**a*" * 50000,
            "[a]( pattern": "[a](" * 50000,
            "<a pattern": "<a " * 70000,
            "backslashes": "\\" * 200000,
        }
        for name, text in cases.items():
            with self.subTest(case=name):
                start = time.perf_counter()
                markdown_to_storage(text)
                self.assertLess(time.perf_counter() - start, 3.0)


class StorageCorpusTest(ConverterTestCase):
    def test_storage_fragments_are_explained_or_stable(self) -> None:
        self.assertGreaterEqual(len(STORAGE_CORPUS), 30)
        for name, case in STORAGE_CORPUS.items():
            with self.subTest(sample=name):
                converted = storage_to_markdown(case["storage"])
                self.assertEqual(converted.dropped, case["accepted"])
                s2 = markdown_to_storage(converted.text)
                s3 = markdown_to_storage(storage_to_markdown(s2).text)
                self.assertEqual(s2, s3)
                stats1 = _storage_stats(case["storage"])
                stats2 = _storage_stats(s2)
                self.assertFalse(stats1["nested_anchor"])
                self.assertFalse(stats2["nested_anchor"])
                if not converted.dropped:
                    self.assertEqual(stats1["text"], stats2["text"])
                    self.assertEqual(stats1["hrefs"], stats2["hrefs"])
                    self.assertEqual(stats1["counts"], stats2["counts"])
                    self.assertEqual(stats1["code_bodies"], stats2["code_bodies"])

    def test_adjacent_panels_stay_separate(self) -> None:
        storage = STORAGE_CORPUS["note tip warning"]["storage"]
        converted = storage_to_markdown(storage)
        self.assertIn("> [!IMPORTANT]", converted.text)
        self.assertIn("> [!TIP]", converted.text)
        self.assertIn("> [!WARNING]", converted.text)
        roundtrip = markdown_to_storage(converted.text)
        self.assertEqual(_storage_stats(storage)["counts"]["{a}structured-macro"], _storage_stats(roundtrip)["counts"]["{a}structured-macro"])

    def test_literal_backticks_stay_literal(self) -> None:
        cases = (
            "<p>\\`tick\\`</p>",
            "<p>\\``tick``</p>",
            "<p><a href=\"https://x.test\">\\`tick\\`</a></p>",
        )
        for storage in cases:
            with self.subTest(storage=storage):
                self.assert_canonical_equal(storage, markdown_to_storage(storage_to_markdown(storage).text))

    def test_escaped_and_unescaped_backticks_in_markdown_follow_commonmark(self) -> None:
        self.assertEqual(markdown_to_storage("\\`tick\\`"), "<p>`tick`</p>")
        self.assertIn("<code>tick</code>", markdown_to_storage("\\\\`tick`"))
        self.assertIn("<code>tick</code>", markdown_to_storage("| H |\n| --- |\n| \\\\`tick` |"))

    def test_literal_entity_spellings_stay_literal(self) -> None:
        storage = "<p>The entity &amp;nbsp; and &amp;#169; and &amp;copy; are written like this</p>"
        self.assert_canonical_equal(storage, markdown_to_storage(storage_to_markdown(storage).text))

    def test_url_cases_follow_gfm_and_export_rules(self) -> None:
        markdown_cases = (
            "<https://a.test/Foo_(bar)>",
            "<https://a.test/Foo_(bar)_(baz)>",
            "(see https://a.test/x)",
            "https://a.test/x.",
            "https://a.test/x,",
            "https://a.test/x?",
            "https://a.test/x&amp;",
            "\"https://a.test/x\"",
            "https://a.test/x>",
        )
        for markdown in markdown_cases:
            with self.subTest(markdown=markdown):
                s1 = markdown_to_storage(markdown)
                self.assert_xml_fragment(s1)
                s2 = markdown_to_storage(storage_to_markdown(s1).text)
                s3 = markdown_to_storage(storage_to_markdown(s2).text)
                self.assertEqual(s2, s3)

        href_cases = (
            "http://x>",
            "http://(*",
            "http://](",
            "http://\\\\",
            "http://``",
            "https://a.test/a b",
            "https://a.test/a%20b/%28x%29",
        )
        for href in href_cases:
            with self.subTest(href=href):
                escaped_href = href.replace("&", "&amp;").replace('"', "&quot;")
                storage = f'<p><a href="{escaped_href}">x</a></p>'
                self.assert_xml_fragment(markdown_to_storage(storage_to_markdown(storage).text))

    def test_all_space_code_spans_do_not_grow(self) -> None:
        for text in (" ", "  ", "   ", "\t"):
            with self.subTest(text=repr(text)):
                storage = f"<p><code>{text}</code></p>"
                converted = storage_to_markdown(storage)
                self.assert_canonical_equal(storage, markdown_to_storage(converted.text))

    def test_nonstandard_line_separators_stay_in_text_or_are_stripped_if_xml_illegal(self) -> None:
        cases = ("a\u2028b", "a\x0bb", "a\x85b", "a\x0cb")
        for text in cases:
            with self.subTest(text=repr(text)):
                rendered = markdown_to_storage(f"{text}\n")
                self.assert_xml_fragment(rendered)


class ReviewerRegressionTest(ConverterTestCase):
    def test_unsafe_schemes_are_canonicalized_before_validation(self) -> None:
        for destination in (
            "java&#x73;cript:alert(1)",
            "java&#115;cript:alert(1)",
            "JaVaScRiPt:alert(1)",
            "java\tscript:alert(1)",
            "java\nscript:alert(1)",
            " javascript:alert(1)\x00",
            "data:text/html;base64,PHNjcmlwdD4=",
            "vbscript:x",
            "file:///secret.txt",
        ):
            with self.subTest(destination=destination):
                self.assertEqual(markdown_to_storage(f"[open]({destination})"), "<p>open</p>")
                self.assertEqual(markdown_to_storage(f"![x]({destination})"), "<p>x</p>")

    def test_safe_destinations_are_canonicalized_and_kept(self) -> None:
        self.assertEqual(markdown_to_storage("[ok](https://x.test/?a=1&amp;b=2)"), '<p><a href="https://x.test/?a=1&amp;b=2">ok</a></p>')
        self.assertIn('href="mailto:user@example.com"', markdown_to_storage("[mail](mailto:user@example.com)"))
        self.assertIn('ri:value="https://example.com/x.png"', markdown_to_storage("![x](https://example.com/x.png)"))

    def test_reference_links_and_autolinks_use_the_same_scheme_rules(self) -> None:
        self.assertEqual(markdown_to_storage("[x][r]\n\n[r]: java&#x73;cript:alert(1)"), "<p>x</p>")
        self.assertEqual(markdown_to_storage("<java&#x73;cript:alert(1)>"), "<p>javascript:alert(1)</p>")
        self.assertEqual(markdown_to_storage("<https://x.test/?a=1&amp;b=2>"), '<p><a href="https://x.test/?a=1&amp;b=2">https://x.test/?a=1&amp;b=2</a></p>')

    def test_code_macros_with_backticks_choose_a_long_enough_fence(self) -> None:
        source = '<ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA[a\n```\nb]]></ac:plain-text-body></ac:structured-macro>'
        converted = storage_to_markdown(source)
        self.assertEqual(converted.text, "````\na\n```\nb\n````")
        self.assert_canonical_equal(source, markdown_to_storage(converted.text))

    def test_code_macros_preserve_special_bodies_or_record_loss(self) -> None:
        cases = (
            ('<ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA[]]></ac:plain-text-body></ac:structured-macro>', "```\n```", ()),
            ('<ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA[\n\n]]></ac:plain-text-body></ac:structured-macro>', "```\n\n\n\n```", ("macro:code",)),
            ('<ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA[\nlead]]></ac:plain-text-body></ac:structured-macro>', "```\n\nlead\n```", ()),
            ('<ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA[a]]]]><![CDATA[>b]]></ac:plain-text-body></ac:structured-macro>', "```\na]]>b\n```", ()),
        )
        for storage, markdown, dropped in cases:
            with self.subTest(markdown=markdown):
                converted = storage_to_markdown(storage)
                self.assertEqual(converted.text, markdown)
                self.assertEqual(converted.dropped, dropped)

    def test_markdown_output_is_xml_well_formed_with_named_and_invalid_entities(self) -> None:
        rendered = markdown_to_storage("&copy; &nbsp; &#0; &#xD800; &foo; AT&T &amp; &#169;")
        self.assert_xml_fragment(rendered)
        self.assertIn("\xa0", rendered)
        self.assertIn("&amp;foo;", rendered)
        self.assertIn("&amp;#0;", rendered)
        self.assertIn("&amp;#xD800;", rendered)

    def test_storage_reader_handles_common_named_html_entities(self) -> None:
        storage = "<p>&nbsp;Hello&rsquo;s&ndash;world&hellip;</p>"
        converted = storage_to_markdown(storage)
        self.assertEqual(converted.text, "Hello’s–world…")

    def test_literal_storage_text_round_trips_without_gaining_markup(self) -> None:
        cases = (
            "<p>**literal**</p>",
            "<p># literal</p>",
            "<p>1. not a list</p>",
            "<p>- not a bullet</p>",
            "<p>&gt; not a quote</p>",
            "<p><code> x </code></p>",
            "<p>snake_case_name</p>",
            "<p>[literal]</p>",
            "<p>a | b</p>",
            "<p>ends with slash\\</p>",
            "<p>AT&amp;T &lt;x&gt;</p>",
        )
        for storage in cases:
            with self.subTest(storage=storage):
                converted = storage_to_markdown(storage)
                self.assert_canonical_equal(storage, markdown_to_storage(converted.text))

    def test_task_continuation_lines_are_preserved(self) -> None:
        rendered = markdown_to_storage("- [ ] first\n  continuation")
        self.assertIn("<ac:task-body>first continuation</ac:task-body>", rendered)

    def test_complex_task_items_fall_back_to_literal_lists(self) -> None:
        markdown = "- [ ] first\n\n  second paragraph\n- [x] done\n  - nested"
        rendered = markdown_to_storage(markdown)
        self.assertNotIn("<ac:task-list>", rendered)
        self.assertIn("[ ] first", rendered)
        self.assertIn("[x] done", rendered)

    def test_bare_list_marker_can_hold_nested_lists(self) -> None:
        markdown = "-\n  - nested\n  1. deep"
        storage = markdown_to_storage(markdown)
        self.assertIn("<ul>", storage)
        self.assertEqual(storage_to_markdown(storage).text, "-\n    - nested\n    1. deep")

    def test_too_deep_inputs_raise_validation_error_instead_of_recursion_error(self) -> None:
        deep_quotes = "".join("> " for _ in range(1500)) + "x\n"
        deep_list = "".join("  " * level + "- x\n" for level in range(400))
        with self.assertRaises(ValidationError):
            markdown_to_storage(deep_quotes)
        with self.assertRaises(ValidationError):
            markdown_to_storage(deep_list)
        with self.assertRaises(ValidationError):
            storage_to_markdown("<strong>" * 400 + "x" + "</strong>" * 400)

    def test_pathological_inputs_do_not_raise_recursion_error(self) -> None:
        for text in ("*" * 5000, "[" * 5000):
            with self.subTest(kind=text[:1]):
                try:
                    markdown_to_storage(text)
                except RecursionError as exc:  # pragma: no cover - explicit regression guard
                    self.fail(f"RecursionError leaked: {exc}")

    def test_token_restoration_is_linear_enough_for_many_code_spans(self) -> None:
        text = " ".join(f"`x{index}`" for index in range(10000))
        start = time.perf_counter()
        rendered = markdown_to_storage(text)
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 2.5)
        self.assertIn("<code>x9999</code>", rendered)

    def test_markdown_to_storage_drops_one_leading_bom(self) -> None:
        self.assertEqual(markdown_to_storage("\ufeff# title\r\nbody"), "<h1>title</h1>\n<p>body</p>")
