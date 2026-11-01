"""From a template to a page: what the body of a template says about the addresses and links that it lost, and what a dry run says about the part of a body that it
does not print. The real program against the mock.

`conflu template ID --format storage --body-only` is the way to start a page from a template, and the body that it prints has `[email]` and `[personal link]` where
the template has addresses and links (people stay out of every output). A page that is created from it would carry those words, so the command says how many
there are. The dry run of `create` prints at most 1500 characters of the body, and says how many macros and external addresses are in the rest.
"""
import json
import re
import unittest

from conflu_c_cli.adapters.driving.cli.commands._common import shortened
from conflu_c_cli.domain.privacy import redact_storage
from tests.integration.test_end_to_end import ROOT, EndToEnd
from tests.support.mock_templates import TemplatesRoutes

GUIDE = ROOT / "docs" / "how-to" / "tasks-properties-and-templates.md"
CONTACT = (
    '<p><a href="mailto:support@example.com">mail</a> <a href="https://example.atlassian.net/wiki/people/5b10ac8d82e05b22cc7d4ef5">me</a> '
    "and alex@example.com</p>"
)
SENTENCE = (
    "3 e-mail addresses and personal links were replaced by [email] and [personal link] in this body: a page created from it would carry those words, not the addresses "
    "and links. `template` has no --with-users, so put the real ones into the file before you create the page, or take them out."
)
MACRO = '<ac:structured-macro ac:name="html"><ac:plain-text-body><![CDATA[x]]></ac:plain-text-body></ac:structured-macro>'
INCLUDE = '<ac:structured-macro ac:name="include"/>'
PIXEL = '<ac:image><ri:url ri:value="https://example.com/pixel.png"/></ac:image>'


class TemplateBodyTest(EndToEnd):
    def setUp(self):
        super().setUp()
        self.area = self.mock.area(TemplatesRoutes)
        self.contact = self.area.add_template("Contact", CONTACT, space_key="ENG")

    def warnings(self, result):
        return [line for line in result.err.splitlines() if "WARNING" in line]

    def test_the_body_for_a_file_says_how_many_addresses_and_links_it_lost(self):
        result = self.cli("template", self.contact, "--format", "storage", "--body-only")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(result.out, redact_storage(CONTACT) + "\n")
        self.assertEqual(result.out, '<p><a href="mailto:[email]">mail</a> <a href="[personal link]">me</a> and [email]</p>\n')
        self.assertEqual(self.warnings(result), ["[conflu] WARNING: " + SENTENCE])

    def test_the_file_that_the_program_writes_has_the_same_body_and_the_same_sentence(self):
        target = self.root / "body.xml"
        result = self.cli("template", self.contact, "--format", "storage", "--body-only", "--out", str(target))
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(target.read_text(encoding="utf-8"), redact_storage(CONTACT) + "\n")
        self.assertTrue(result.out.startswith("Wrote "), result.out)
        self.assertEqual(self.warnings(result), ["[conflu] WARNING: " + SENTENCE])

    def test_one_is_one_and_what_the_template_says_itself_is_not_counted(self):
        one = self.cli("template", "7403", "--format", "storage", "--body-only")  # a mention (refused by `create`), and one address
        self.assertIn("1 e-mail address or personal link was replaced by [email] and [personal link] in this body", self.warnings(one)[0])
        own = self.area.add_template("Own words", "<p>The word [email] stays, and alex@example.com goes</p>", space_key="ENG")
        result = self.cli("template", own, "--format", "storage", "--body-only")
        self.assertIn("1 e-mail address or personal link was replaced", self.warnings(result)[0])

    def test_the_other_forms_of_the_same_output_say_it_too_and_keep_their_shape(self):
        document = self.cli("template", self.contact, "--format", "storage", "--json")
        self.assertEqual(document.code, 0, document.err)
        self.assertEqual(self.warnings(document), ["[conflu] WARNING: " + SENTENCE])
        self.assertEqual(sorted(document.json()), sorted(["id", "name", "type", "description", "spaceKey", "labels", "blueprint", "variables", "variablesComplete", "body"]))
        self.assertEqual(document.json()["body"]["value"], redact_storage(CONTACT))
        text = self.cli("template", self.contact, "--format", "storage")
        self.assertEqual(self.warnings(text), ["[conflu] WARNING: " + SENTENCE])
        self.assertIn("[email]", text.out)

    def test_a_body_that_is_not_for_a_file_or_has_nobody_in_it_says_nothing(self):
        for argv in (("--format", "markdown"), ("--format", "text"), ("--format", "markdown", "--body-only"), ("--format", "text", "--json")):
            result = self.cli("template", self.contact, *argv)
            with self.subTest(argv=argv):
                self.assertEqual(result.code, 0, result.err)
                self.assertEqual(self.warnings(result), [])
        for template in ("7402", "7405"):
            result = self.cli("template", template, "--format", "storage", "--body-only")
            with self.subTest(template=template):
                self.assertEqual(self.warnings(result), [])

    def test_template_has_no_with_users_as_the_sentence_says(self):
        result = self.cli("template", self.contact, "--format", "storage", "--with-users")
        self.assertEqual(result.code, 2, result.err)
        self.assertIn("--with-users", result.err)
        self.assertEqual([item for item in self.mock.requests if item.path.startswith("/rest/api/template")], [])

    def test_a_page_created_from_the_body_carries_the_words_which_is_what_the_sentence_is_for(self):
        target = self.root / "body.xml"
        self.cli("template", self.contact, "--format", "storage", "--body-only", "--out", str(target))
        result = self.cli("create", "--space", "ENG", "--title", "From a template", "--file", str(target), "--format", "storage", "--dry-run", "--json")
        self.assertEqual(result.code, 0, result.err)
        body = result.json()["payload"]["body"]["value"]
        self.assertEqual((body.count("[email]"), body.count("[personal link]")), (2, 1))
        self.assertNotIn("alex@example.com", result.out + result.err)


class CutBodyTest(EndToEnd):
    def body(self, tail):
        return "<p>" + "a" * 1600 + "</p>" + tail

    def write(self, text):
        target = self.root / "body.xml"
        target.write_text(text, encoding="utf-8")
        return str(target)

    def test_the_dry_run_of_a_page_says_how_many_macros_and_external_addresses_are_in_the_part_that_it_cuts(self):
        body = '<ac:structured-macro ac:name="info"/>' + self.body(MACRO + INCLUDE + PIXEL)  # a macro in the part that is printed is there to read
        result = self.cli("create", "--space", "ENG", "--title", "T", "--file", self.write(body), "--format", "storage", "--dry-run")
        self.assertEqual(result.code, 0, result.err)
        more = len(body) - 1500
        self.assertIn(f"... ({more} more characters, among them 2 macros and 1 external address)", result.out)
        for hidden in ("pixel.png", "example.com", "include"):
            self.assertNotIn(hidden, result.out)  # a count, never the text

    def test_the_json_of_the_dry_run_is_never_cut(self):
        body = self.body(MACRO + PIXEL)
        data = self.cli("create", "--space", "ENG", "--title", "T", "--file", self.write(body), "--format", "storage", "--dry-run", "--json").json()
        self.assertEqual(data["payload"]["body"]["value"], body)
        self.assertIn("pixel.png", data["payload"]["body"]["value"])

    def test_a_cut_part_that_holds_none_of_them_is_cut_as_before(self):
        body = self.body("<p>" + "b" * 300 + "</p>")
        result = self.cli("create", "--space", "ENG", "--title", "T", "--file", self.write(body), "--format", "storage", "--dry-run")
        self.assertIn(f"... ({len(body) - 1500} more characters)", result.out)
        self.assertNotIn("among them", result.out)

    def test_a_body_that_is_not_cut_has_no_note(self):
        result = self.cli("create", "--space", "ENG", "--title", "T", "--file", self.write("<p>short</p>" + MACRO), "--format", "storage", "--dry-run")
        self.assertNotIn("more characters", result.out)

    def test_the_dry_run_of_an_update_and_of_a_blog_post_say_it_too(self):
        body = self.body(MACRO + MACRO + PIXEL + PIXEL + PIXEL)
        path = self.write(body)
        for argv in (
            ("update", "2005", "--file", path, "--format", "storage", "--dry-run"),
            ("blogpost-create", "--space", "ENG", "--title", "T", "--file", path, "--format", "storage", "--dry-run"),
        ):
            result = self.cli(*argv)
            with self.subTest(command=argv[0]):
                self.assertEqual(result.code, 0, result.err)
                self.assertIn(f"({len(body) - 1500} more characters, among them 2 macros and 3 external addresses)", result.out)

    def test_a_body_that_is_made_of_markdown_says_it_too_because_its_storage_format_is_what_is_cut(self):
        text = "a " * 800 + "\n\n![x](https://example.com/pixel.png)\n"
        result = self.cli("create", "--space", "ENG", "--title", "T", "--file", self.write(text), "--dry-run")
        self.assertEqual(result.code, 0, result.err)
        self.assertRegex(result.out, r"\(\d+ more characters, among them 1 external address\)")
        self.assertNotIn("pixel.png", result.out)


class GuideTest(unittest.TestCase):
    def test_the_guide_says_what_the_command_says(self):
        guide = " ".join(GUIDE.read_text(encoding="utf-8").split())
        self.assertIn(" ".join(SENTENCE.replace("3 e-mail addresses", "N e-mail addresses").split()), guide)
        self.assertIn("1 e-mail address or personal link was replaced", guide)
        self.assertIn("(1283 more characters, among them 2 macros and 1 external address)", guide)
        self.assertIn("`conflu template` has no `--with-users`", guide)


class ShortenedTest(unittest.TestCase):
    def cut(self, body, limit=1500):
        value = shortened({"body": {"representation": "storage", "value": body}}, limit)["body"]["value"]
        return value[limit:]

    def test_a_tag_that_the_cut_goes_through_is_hidden_and_one_that_ends_at_the_cut_is_shown(self):
        macro = "<ac:structured-macro"
        for start, counted in ((1479, 0), (1480, 0), (1481, 1), (1499, 1)):  # `<ac:structured-macro` is 20 characters long
            body = "x" * start + macro + ' ac:name="a"/>' + "y" * 200
            with self.subTest(start=start):
                self.assertEqual(self.cut(body), "... (" + str(len(body) - 1500) + " more characters" + (", among them 1 macro" if counted else "") + ")")
        address = "<ri:url"
        for start, counted in ((1493, 0), (1494, 1)):
            body = "x" * start + address + ' ri:value="a"/>' + "y" * 200
            with self.subTest(start=start, address=True):
                self.assertEqual(self.cut(body).endswith("external address)"), bool(counted))

    def test_the_old_form_of_a_macro_counts_and_the_case_does_not_matter(self):
        body = "x" * 1600 + '<ac:macro ac:name="a"/><AC:STRUCTURED-MACRO ac:name="b"/><ri:URL ri:value="c"/><ac:macros/><ri:urls/>'
        self.assertTrue(self.cut(body).endswith(", among them 2 macros and 1 external address)"), self.cut(body))

    def test_what_is_counted_is_a_count_and_never_the_text(self):
        body = "x" * 1600 + MACRO + PIXEL
        note = self.cut(body)
        self.assertEqual(note, f"... ({len(body) - 1500} more characters, among them 1 macro and 1 external address)")
        self.assertFalse(re.search(r"example|html|CDATA", note))
        self.assertEqual(json.dumps(shortened({"a": 1}, 5)), '{"a": 1}')  # what is no body is as it was


if __name__ == "__main__":
    unittest.main()
