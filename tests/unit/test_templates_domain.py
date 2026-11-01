"""The rules about templates that need no Confluence: a template id, and the variables that a template declares, read from a body that nobody has checked."""
import time
import unittest

from conflu_c_cli.domain.errors import ValidationError
from conflu_c_cli.domain.templates import MAX_NAMES, MAX_TAG, MAX_TAGS, Template, TemplateInfo, TemplatePage, Variables, parse_template_id, variables_of


def names(storage):
    return variables_of(storage).names


class TemplateIdTest(unittest.TestCase):
    def test_a_numeric_id_and_the_uuid_of_a_blueprint_are_template_ids(self):
        for text in ("7402", " 7402 ", "7408a0b1-c2d3-4e5f-8a6b-7c8d9e0f1a2b", "a.b_c:d-e", "x" * 128, "0"):
            with self.subTest(text=text[:20]):
                self.assertEqual(parse_template_id(text), text.strip())

    def test_the_names_of_the_two_lists_are_no_template_ids(self):
        for text in ("page", "blueprint"):
            with self.subTest(text=text), self.assertRaises(ValidationError) as caught:
                parse_template_id(text)
            self.assertIn("conflu templates", caught.exception.hint)

    def test_anything_that_could_change_the_path_is_refused(self):
        for text in ("", "   ", "../x", "a/b", "a b", "x" * 129, ".hidden", "-x", "7402\n7403", "7402?x=1", "7402#a", "%2e%2e", "a\x00b", "\u0667\u0662", "a;b", "a\\b"):
            with self.subTest(text=text[:20]), self.assertRaises(ValidationError):
                parse_template_id(text)

    def test_the_message_shows_a_short_text_and_names_a_long_or_unprintable_one_without_echoing_it(self):
        with self.assertRaises(ValidationError) as short:
            parse_template_id("a b")
        self.assertIn("a b", short.exception.message)
        with self.assertRaises(ValidationError) as long:
            parse_template_id("x" * 400 + "/")
        self.assertNotIn("xxxxx", long.exception.message)
        self.assertIn("<not a template id>", long.exception.message)
        with self.assertRaises(ValidationError) as control:
            parse_template_id("a\x1b[2Jb")
        self.assertNotIn("\x1b", control.exception.message)
        with self.assertRaises(ValidationError) as nothing:
            parse_template_id("")
        self.assertIn("<missing>", nothing.exception.message)

    def test_nothing_is_not_a_template_id(self):
        with self.assertRaises(ValidationError):
            parse_template_id(None)  # type: ignore[arg-type]


class VariablesTest(unittest.TestCase):
    def test_a_variable_is_named_by_at_name(self):
        self.assertEqual(variables_of('<h1><at:var at:name="title" /></h1>'), Variables(("title",), True))

    def test_each_name_once_in_the_order_of_its_first_appearance(self):
        storage = '<p><at:var at:name="b"/><at:var at:name="a"/><at:var at:name="b"/><at:var at:name="c"></at:var></p>'
        self.assertEqual(names(storage), ("b", "a", "c"))

    def test_single_quotes_blanks_and_the_order_of_the_attributes_do_not_matter(self):
        self.assertEqual(names("<at:var at:name='x'/>"), ("x",))
        self.assertEqual(names('<at:var   at:name  =  "x"   />'), ("x",))
        self.assertEqual(names('<at:var at:rawxhtml="x" at:name="y"/>'), ("y",))
        self.assertEqual(names('<at:var\nat:name="multi\nline"\n/>'), ("multi\nline",))

    def test_an_entity_in_the_name_is_read_and_a_greater_than_sign_inside_an_attribute_does_not_end_the_tag(self):
        self.assertEqual(names('<at:var at:name="Tom &amp; Jerry" at:rawxhtml="a>b"/>'), ("Tom & Jerry",))
        self.assertEqual(names('<at:var at:rawxhtml="a>b" at:name="after"/>'), ("after",))
        self.assertEqual(names("<at:var at:name='it&#39;s'/>"), ("it's",))

    def test_a_word_that_only_starts_like_the_tag_is_not_a_variable(self):
        self.assertEqual(names('<at:variable at:name="no"/><at:vars at:name="no"/><at:var2 at:name="no"/>'), ())
        self.assertEqual(names('<at:var at:name="yes"/>'), ("yes",))

    def test_a_tag_that_has_no_name_or_an_empty_one_names_nothing(self):
        self.assertEqual(names('<at:var/><at:var at:name=""/><at:var at:name="   "/><at:var at:other="x"/><at:var at:name=bare />'), ())

    def test_an_attribute_that_only_mentions_the_name_in_its_value_is_not_the_name(self):
        self.assertEqual(names('<at:var at:rawxhtml="at:name=&quot;fake&quot;" at:note=\'at:name="fake"\'/>'), ())
        self.assertEqual(names('<at:var at:rawxhtml=\'x at:name="fake" y\' at:name="real"/>'), ("real",))

    def test_text_that_is_not_a_tag_is_not_looked_at(self):
        self.assertEqual(names('&lt;at:var at:name="x"/&gt; and at:name="y"'), ())
        self.assertEqual(names(""), ())
        self.assertEqual(variables_of(None), Variables((), True))  # type: ignore[arg-type]

    def test_an_address_or_a_link_to_a_person_in_a_name_is_redacted_like_any_text(self):
        self.assertEqual(names('<at:var at:name="Ask alex@example.com"/>'), ("Ask [email]",))

    def test_a_tag_inside_something_else_is_found(self):
        storage = '<ac:structured-macro ac:name="info"><ac:parameter ac:name="title"><at:var at:name="infotitle"/></ac:parameter></ac:structured-macro><table><tr><td><at:var at:name="cell"/></td></tr></table>'
        self.assertEqual(names(storage), ("infotitle", "cell"))

    def test_what_looks_like_a_variable_in_a_cdata_section_or_a_comment_is_text_and_none(self):
        storage = (
            '<p><at:var at:name="real"/></p><ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA[<at:var at:name="in.code"/>]]></ac:plain-text-body>'
            '</ac:structured-macro><!-- <at:var at:name="in.comment"/> --><p><at:var at:name="after"/></p>'
        )
        self.assertEqual(variables_of(storage), Variables(("real", "after"), True))
        self.assertEqual(names('<!--<at:var at:name="a"/>--><![CDATA[<at:var at:name="b"/>]]>'), ())
        self.assertEqual(names('<![CDATA[<at:var at:name="b"/>]]><at:var at:name="c"/><!-- --><at:var at:name="d"/>'), ("c", "d"))

    def test_a_comment_in_a_cdata_section_and_a_cdata_section_in_a_comment_are_what_they_are_inside(self):
        self.assertEqual(names('<![CDATA[ <!-- ]]><at:var at:name="real"/><!-- x -->'), ("real",))  # the comment never started: it is text of the section
        self.assertEqual(names('<!-- <![CDATA[ --><at:var at:name="real"/>'), ("real",))  # the section never started: it is text of the comment
        self.assertEqual(names('<!-- <![CDATA[ <at:var at:name="hidden"/> ]]> --><at:var at:name="real"/>'), ("real",))

    def test_a_comment_ends_at_its_own_end_and_an_empty_one_is_a_comment_too(self):
        self.assertEqual(names('<!----><at:var at:name="a"/><!-- - -- --><at:var at:name="b"/>'), ("a", "b"))
        self.assertEqual(names('<!-->--><at:var at:name="a"/>'), ("a",))  # `<!--` and then `>--` is the comment `>`: a comment does not end inside its own start
        self.assertEqual(names("<![CDATA[]]><at:var at:name=\"a\"/>"), ("a",))

    def test_a_comment_or_a_cdata_section_that_never_ends_holds_the_rest_and_the_list_may_be_incomplete(self):
        for storage in ('<at:var at:name="first"/><!-- <at:var at:name="lost"/>', '<at:var at:name="first"/><![CDATA[ <at:var at:name="lost"/>'):
            with self.subTest(storage=storage):
                self.assertEqual(variables_of(storage), Variables(("first",), False))

    def test_a_cdata_section_only_counts_where_its_start_is_written_exactly(self):
        self.assertEqual(names('<![cdata[<at:var at:name="a"/>]]>'), ("a",))  # XML is case sensitive: this is no section
        self.assertEqual(names('<! --<at:var at:name="a"/>-->'), ("a",))

    def test_the_numbers_that_limit_the_scan_are_the_ones_that_were_chosen(self):
        self.assertEqual((MAX_TAG, MAX_TAGS, MAX_NAMES), (1000, 2000, 200))
        self.assertEqual(variables_of('<at:var at:name="same"/>' * 2000), Variables(("same",), True))
        self.assertEqual(variables_of('<at:var at:name="same"/>' * 2001), Variables(("same",), False))
        self.assertEqual(len(variables_of("".join(f'<at:var at:name="v{number}"/>' for number in range(200))).names), 200)
        self.assertEqual(variables_of("".join(f'<at:var at:name="v{number}"/>' for number in range(201))).complete, False)
        self.assertEqual(variables_of('<at:var at:name="a" at:filler="' + "x" * 960 + '"/>'), Variables(("a",), True))
        self.assertEqual(variables_of('<at:var at:name="a" at:filler="' + "x" * 1000 + '"/>'), Variables((), False))

    def test_comments_and_sections_do_not_count_against_the_limit_of_tags(self):
        storage = "<!-- c -->" * 5000 + '<![CDATA[x]]>' * 5000 + '<at:var at:name="late"/>'
        self.assertEqual(variables_of(storage), Variables(("late",), True))

    def test_the_tags_of_a_long_body_are_all_found(self):
        storage = "".join(f'<p>text <at:var at:name="v{number}" /> more</p>' for number in range(150))
        found = variables_of(storage)
        self.assertEqual((len(found.names), found.names[0], found.names[-1], found.complete), (150, "v0", "v149", True))

    def test_more_distinct_names_than_the_limit_are_not_listed_and_the_list_says_it_is_cut(self):
        storage = "".join(f'<at:var at:name="v{number}"/>' for number in range(MAX_NAMES + 50))
        found = variables_of(storage)
        self.assertEqual((len(found.names), found.names[-1], found.complete), (MAX_NAMES, f"v{MAX_NAMES - 1}", False))

    def test_the_same_name_over_and_over_is_one_name_and_the_scan_stops_at_its_limit_of_tags(self):
        storage = '<at:var at:name="same"/>' * (MAX_TAGS + 10)
        found = variables_of(storage)
        self.assertEqual((found.names, found.complete), (("same",), False))
        self.assertEqual(variables_of('<at:var at:name="same"/>' * MAX_TAGS), Variables(("same",), True))

    def test_a_tag_that_does_not_end_is_skipped_and_the_list_says_it_may_be_incomplete(self):
        found = variables_of('<at:var at:name="first"/><at:var at:name="broken" ' + "x" * (MAX_TAG * 3) + '<at:var at:name="last"/>')
        self.assertEqual((found.names, found.complete), (("first", "last"), False))

    def test_a_tag_within_the_length_that_is_read_is_read(self):
        found = variables_of(f'<at:var at:name="long" at:filler="{"x" * (MAX_TAG - 100)}"/>')
        self.assertEqual((found.names, found.complete), (("long",), True))
        found = variables_of(f'<at:var at:name="too long" at:filler="{"x" * (MAX_TAG + 100)}"/>')
        self.assertEqual((found.names, found.complete), ((), False))

    def test_tags_that_never_end_cost_no_more_than_a_moment(self):
        started = time.perf_counter()
        for storage in (
            "<at:var " * 20_000,
            '<at:var "' * 20_000,
            "<at:var '" * 20_000 + ">",
            '<at:var at:name="' + "x" * 300_000,
            '<at:var at:name="a" ' * 15_000 + '">',
            "<at:var " + 'at:name="' * 50_000,
            "<at:var />" * 100_000,
            "<!--" * 100_000,
            "<![CDATA[" * 100_000,
            "<!-- " * 50_000 + "-->" + '<at:var at:name="late"/>',
            "<!---->" * 200_000,
            "<![CDATA[]]>" * 100_000 + "<!--",
            "<at:var " * 20_000 + "<!--" * 20_000,
        ):
            variables_of(storage)
        self.assertLess(time.perf_counter() - started, 10)


class RecordsTest(unittest.TestCase):
    def test_a_template_is_its_information_and_a_body(self):
        info = TemplateInfo("7402", "Release checklist", "page", "Steps", "ENG", ("release",), "")
        template = Template("7402", "Release checklist", "page", "Steps", "ENG", ("release",), "", "<p>Body</p>")
        self.assertEqual((template.id, template.name, template.space_key, template.labels, template.body), (info.id, info.name, info.space_key, info.labels, "<p>Body</p>"))
        self.assertEqual(TemplateInfo("1").labels, ())

    def test_a_piece_of_a_list_says_where_the_next_one_starts(self):
        page = TemplatePage()
        self.assertEqual((page.templates, page.start, page.next_start), ([], 0, None))
        self.assertIsNot(TemplatePage().templates, page.templates)


if __name__ == "__main__":
    unittest.main()
