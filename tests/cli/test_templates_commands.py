"""The commands `templates` and `template` on the command line, with the in-memory Confluence: what they print, what they refuse, how they are described."""
import shlex
import unittest

from conflu_c_cli.adapters.driving.cli.help import mcp_tool, render_command_help
from conflu_c_cli.adapters.driving.cli.parser import build_parser
from conflu_c_cli.adapters.driving.cli.registry import all_commands, find_command
from conflu_c_cli.domain.errors import AuthError
from conflu_c_cli.domain.templates import Template
from tests.support.cli import run_cli
from tests.support.fakes import ACCOUNT, FakeGateway, default_settings

BLUEPRINT = "7408a0b1-c2d3-4e5f-8a6b-7c8d9e0f1a2b"
PEOPLE = (ACCOUNT, "Alex Example", "alex@example.com")


def ids(out):
    return [line.split()[0] for line in out.splitlines()[1:]]


class DescriptionTest(unittest.TestCase):
    def test_both_are_read_only_and_in_the_group_of_the_spaces(self):
        for name in ("templates", "template"):
            command = find_command(name)
            with self.subTest(command=name):
                self.assertEqual(command.group, "Spaces")
                self.assertTrue(command.when and command.output and command.json_output and command.examples)
                self.assertFalse(command.writes or command.for_person or command.local or command.destructive)
        self.assertTrue(find_command("template").notes)

    def test_the_options_are_those_of_the_calls_and_nothing_makes_a_page_from_a_template(self):
        self.assertEqual([arg.names[0] for arg in find_command("templates").args], ["--space", "--blueprints", "--limit", "--start", "--all", "--select", "--format"])
        template = {arg.names[0]: arg for arg in find_command("template").args}
        self.assertEqual(list(template), ["id", "--format", "--body-only", "--out", "--force"])
        self.assertEqual((template["--format"].choices, template["--format"].default), (("markdown", "text", "storage"), "markdown"))
        for name in ("templates", "template"):
            self.assertFalse({arg.dest for arg in find_command(name).args} & {"create", "apply", "instantiate", "page", "title", "dry_run"}, name)

    def test_the_examples_parse(self):
        for name in ("templates", "template"):
            for example in find_command(name).examples:
                with self.subTest(example=example.command):
                    words = shlex.split(example.command)
                    self.assertEqual(words[:2], ["conflu", name])
                    arguments = words[2 : words.index(">")] if ">" in words else words[2:]  # a redirect into a file is the shell's, not an argument
                    build_parser(find_command(name)).parse_args(arguments)

    def test_the_help_says_that_the_api_cannot_make_a_page_from_a_template(self):
        for name in ("templates", "template"):
            text = " ".join(render_command_help(find_command(name)).split())
            self.assertIn("cannot make a page from a template", text)
        self.assertIn("older REST API", " ".join(render_command_help(find_command("templates")).split()))

    def test_an_agent_is_told_that_both_only_read_and_the_text_names_no_flag_of_its_own(self):
        for name in ("templates", "template"):
            tool = mcp_tool(find_command(name))
            self.assertTrue(tool["annotations"]["readOnlyHint"])
            properties = tool["inputSchema"]["properties"]
            text = tool["description"] + " ".join(item["description"] for item in properties.values())
            for arg in find_command(name).args:
                if not arg.positional and not arg.text_only:
                    self.assertNotIn(f" {arg.names[0]} ", text + " ", f"{name}: {arg.names[0]} is written as a flag in the text of the tool")
        self.assertEqual(set(mcp_tool(find_command("template"))["inputSchema"]["properties"]), {"id", "format", "bodyOnly", "out", "force"})

    def test_the_commands_are_listed_in_the_catalog(self):
        catalog = {item["name"]: item for item in run_cli("commands", "--json").json()["commands"]}
        self.assertFalse(catalog["templates"]["changesData"] or catalog["template"]["changesData"])
        self.assertIn("variablesComplete", catalog["template"]["jsonOutput"])
        self.assertEqual([item.name for item in all_commands() if item.name in ("templates", "template")], ["templates", "template"])


class TemplatesListTest(unittest.TestCase):
    def test_the_global_page_templates_as_a_table(self):
        result = run_cli("templates", gateway=FakeGateway())
        self.assertEqual(result.code, 0, result.err)
        lines = result.out.splitlines()
        self.assertEqual(lines[0].split(), ["ID", "NAME", "TYPE", "SPACE", "DESCRIPTION"])
        self.assertEqual(lines[1].split(None, 2)[:2], ["7401", "Meeting"])
        self.assertIn("Notes of a meeting", lines[1])
        self.assertEqual(len(lines), 2)
        self.assertEqual(result.err, "")

    def test_the_templates_of_a_space_a_piece_at_a_time_with_the_note_for_the_next(self):
        result = run_cli("templates", "--space", "ENG", gateway=FakeGateway())
        self.assertEqual(ids(result.out), ["7404", "7403"])
        self.assertEqual(result.err, "[conflu] More templates follow. Continue with --start 2, or use --all.\n")
        second = run_cli("templates", "--space", "ENG", "--start", "2", gateway=FakeGateway())
        self.assertEqual((ids(second.out), second.err), (["7402"], ""))
        self.assertEqual(ids(run_cli("templates", "--space", "eng", "--all", gateway=FakeGateway()).out), ["7404", "7403", "7402"])

    def test_the_templates_that_blueprints_provide(self):
        out = run_cli("templates", "--blueprints", "--all", gateway=FakeGateway()).out
        self.assertEqual(ids(out), ["7406", "7407"])
        self.assertIn("blueprint", out.splitlines()[1])
        self.assertEqual(ids(run_cli("templates", "--blueprints", "--space", "ENG", gateway=FakeGateway()).out), [BLUEPRINT])

    def test_a_space_that_has_none_says_so(self):
        gateway = FakeGateway()
        gateway.templates.clear()
        self.assertEqual(run_cli("templates", "--space", "DOCS", gateway=gateway).out, "No templates.\n")

    def test_the_json_has_the_keys_of_the_documentation(self):
        data = run_cli("templates", "--space", "ENG", "--limit", "2", "--json", gateway=FakeGateway()).json()
        self.assertEqual(list(data), ["space", "blueprints", "count", "start", "nextStart", "truncated", "templates"])
        self.assertEqual((data["space"], data["blueprints"], data["count"], data["start"], data["nextStart"], data["truncated"]), ("ENG", False, 2, 0, 2, False))
        self.assertEqual(list(data["templates"][0]), ["id", "name", "type", "description", "spaceKey", "labels", "blueprint"])
        self.assertEqual(data["templates"][0], {"id": "7404", "name": "Decision record", "type": "page", "description": "ADR style", "spaceKey": "ENG", "labels": ["adr"], "blueprint": None})
        global_ = run_cli("templates", "--json", gateway=FakeGateway()).json()
        self.assertEqual((global_["space"], global_["templates"][0]["spaceKey"]), (None, None))
        blueprint = run_cli("templates", "--blueprints", "--all", "--json", gateway=FakeGateway()).json()
        self.assertEqual((blueprint["blueprints"], blueprint["nextStart"], blueprint["templates"][0]["blueprint"].endswith("meeting-notes-blueprint")), (True, None, True))

    def test_the_note_for_a_person_is_not_in_the_way_of_the_json(self):
        self.assertEqual(run_cli("templates", "--space", "ENG", "--json", gateway=FakeGateway()).err, "")

    def test_a_list_can_be_shaped_for_a_script(self):
        tsv = run_cli("templates", "--space", "ENG", "--all", "--select", "id,name,description", "--format", "tsv", gateway=FakeGateway()).out.splitlines()
        self.assertEqual(tsv, ["id\tname\tdescription", "7404\tDecision record\tADR style", "7403\tIncident report\t", "7402\tRelease checklist\tSteps for every release"])
        data = run_cli("templates", "--space", "ENG", "--all", "--select", "id,labels", "--json", gateway=FakeGateway()).json()
        self.assertEqual(data["templates"][2], {"id": "7402", "labels": ["release", "checklist"]})
        md = run_cli("templates", "--space", "DOCS", "--format", "md", gateway=FakeGateway()).out.splitlines()
        self.assertEqual(md[0], "| ID | NAME | TYPE | SPACE | DESCRIPTION |")
        unknown = run_cli("templates", "--select", "nope", gateway=FakeGateway())
        self.assertEqual(unknown.code, 2)
        self.assertIn("Valid names:", unknown.err)
        self.assertEqual(run_cli("templates", "--format", "tsv", "--json", gateway=FakeGateway()).code, 2)

    def test_the_text_of_a_template_is_redacted_like_a_title(self):
        gateway = FakeGateway()
        gateway.templates["7499"] = Template("7499", "Ask alex@example.com", "page", "Write to alex@example.com", "", ("alex@example.com",), "", "<p>x</p>")
        for argv in (("templates", "--all"), ("templates", "--all", "--json"), ("templates", "--all", "--format", "tsv")):
            result = run_cli(*argv, gateway=gateway)
            with self.subTest(argv=argv):
                self.assertNotIn("alex@example.com", result.out + result.err)
                self.assertIn("[email]", result.out)

    def test_a_description_with_a_line_break_stays_in_its_row(self):
        gateway = FakeGateway()
        gateway.templates["7499"] = Template("7499", "Two\nlines", "page", "first\n7498 pretend row", "", (), "", "<p>x</p>")
        lines = run_cli("templates", "--all", gateway=gateway).out.splitlines()
        self.assertEqual(len(lines), 3)  # the header and two templates

    def test_nothing_makes_the_commands_name_a_person(self):
        for argv in (("templates", "--all"), ("templates", "--all", "--json"), ("templates", "--blueprints", "--all")):
            result = run_cli(*argv, gateway=FakeGateway())
            for text in PEOPLE:
                self.assertNotIn(text, result.out + result.err)


class TemplatesRefusalTest(unittest.TestCase):
    def test_a_space_that_is_not_there_is_not_found(self):
        gateway = FakeGateway()
        result = run_cli("templates", "--space", "NOPE", gateway=gateway)
        self.assertEqual((result.code, result.out), (4, ""))
        self.assertIn("No space with the key NOPE", result.err)
        self.assertEqual(gateway.called("list_templates"), [])

    def test_a_key_that_is_none_a_start_below_zero_and_a_limit_out_of_range_are_refused(self):
        self.assertEqual(run_cli("templates", "--space", "E N G", gateway=FakeGateway()).code, 1)
        self.assertEqual(run_cli("templates", "--start", "-1", gateway=FakeGateway()).code, 2)
        for limit in ("0", "251"):
            self.assertEqual(run_cli("templates", "--limit", limit, gateway=FakeGateway()).code, 2)

    def test_all_does_not_use_limit_and_start_but_a_limit_out_of_range_and_a_negative_start_are_still_refused(self):
        for argv in (("--limit", "0"), ("--limit", "251"), ("--start", "-1")):
            gateway = FakeGateway()
            with self.subTest(argv=argv):
                self.assertEqual(run_cli("templates", "--all", *argv, gateway=gateway).code, 2)
                self.assertEqual(gateway.called("list_templates"), [])
        every = run_cli("templates", "--space", "ENG", "--all", "--limit", "1", "--start", "5", gateway=FakeGateway())
        self.assertEqual(ids(every.out), ["7404", "7403", "7402"])
        text = " ".join(render_command_help(find_command("templates")).split())
        self.assertIn("--limit and --start are not used then, but a --limit out of range and a negative --start are still refused", text)

    def test_a_refusal_of_confluence_says_what_is_known_and_none_of_its_words(self):
        gateway = FakeGateway()
        gateway.errors["list_templates"] = AuthError("Confluence refused this request (HTTP 403): alex@example.com", hint="x", details={"status": 403})
        result = run_cli("templates", "--space", "ENG", gateway=gateway)
        self.assertEqual(result.code, 5)
        self.assertIn("the space ENG", result.err)
        self.assertNotIn("alex@example.com", result.err)

    def test_credentials_that_were_not_accepted_are_not_called_a_refusal_for_lack_of_permission(self):
        for argv, name in ((("templates", "--space", "ENG"), "list_templates"), (("template", "7402"), "get_template")):
            gateway = FakeGateway()
            gateway.errors[name] = AuthError("Confluence did not accept the credentials (HTTP 401).", hint="Check CONFLUENCE_EMAIL and create a new API token.", details={"status": 401})
            result = run_cli(*argv, gateway=gateway)
            with self.subTest(argv=argv):
                self.assertEqual(result.code, 5)
                self.assertIn("did not accept the credentials", result.err)
                self.assertIn("Check CONFLUENCE_EMAIL", result.err)
                self.assertNotIn("HTTP 403", result.err)
                self.assertNotIn("may not see", result.err)


class TemplateShowTest(unittest.TestCase):
    def test_a_template_with_what_it_is_its_variables_and_its_body(self):
        result = run_cli("template", "7402", gateway=FakeGateway())
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(
            result.out,
            "Release checklist  [7402]\nType:        page\nSpace:       ENG\nDescription: Steps for every release\nLabels:      release, checklist\nVariables:   version\n\n## Release\n\n- Update the notes\n- Tag\n",
        )
        self.assertEqual(result.err, "[conflu] The Markdown cannot show: html:at:var. `--format storage` shows the template as Confluence keeps it.\n")

    def test_a_global_template_says_so_and_a_blueprint_names_what_it_references(self):
        out = run_cli("template", "7401", gateway=FakeGateway()).out
        self.assertIn("Space:       (global)", out)
        self.assertIn("Variables:   title, Meeting date", out)
        blueprint = run_cli("template", "7406", gateway=FakeGateway()).out
        self.assertIn("Blueprint:   com.atlassian.confluence.plugins.confluence-business-blueprints:meeting-notes-blueprint", blueprint)
        self.assertIn("Type:        blueprint", blueprint)

    def test_the_source_is_what_confluence_keeps_with_the_people_blanked(self):
        result = run_cli("template", "7403", "--format", "storage", gateway=FakeGateway())
        self.assertEqual(result.code, 0, result.err)
        self.assertIn('<ac:link><ri:user ri:account-id="hidden" /></ac:link>', result.out)
        self.assertIn("[email]", result.out)
        for text in PEOPLE:
            self.assertNotIn(text, result.out + result.err)
        self.assertEqual(result.err.count("WARNING"), 1)  # nothing was dropped: it is the source, and one address of it is [email] now, which the line says
        self.assertIn("1 e-mail address or personal link was replaced by [email] and [personal link]", result.err)

    def test_in_markdown_and_in_text_a_mention_is_a_word_and_an_address_is_redacted(self):
        for fmt in ("markdown", "text"):
            result = run_cli("template", "7403", "--format", fmt, gateway=FakeGateway())
            with self.subTest(fmt=fmt):
                self.assertIn("@user", result.out)
                self.assertIn("[email]", result.out)
                for text in PEOPLE:
                    self.assertNotIn(text, result.out + result.err)

    def test_the_body_alone_is_for_a_file_and_wins_over_json(self):
        result = run_cli("template", "7402", "--format", "storage", "--body-only", gateway=FakeGateway())
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(result.out, '<h2>Release <at:var at:name="version" /></h2><ul><li>Update the notes</li><li>Tag <at:var at:name="version" /></li></ul>\n')
        self.assertEqual(result.err, "")
        self.assertEqual(run_cli("template", "7402", "--format", "storage", "--body-only", "--json", gateway=FakeGateway()).out, result.out)
        markdown = run_cli("template", "7402", "--body-only", gateway=FakeGateway())
        self.assertEqual(markdown.out, "## Release\n\n- Update the notes\n- Tag\n")
        self.assertIn("html:at:var", markdown.err)  # what the Markdown cannot say is still said, on standard error
        blanked = run_cli("template", "7403", "--format", "storage", "--body-only", gateway=FakeGateway()).out
        self.assertIn('ri:account-id="hidden"', blanked)
        for text in PEOPLE:
            self.assertNotIn(text, blanked)

    def test_the_json_has_the_keys_of_the_documentation(self):
        data = run_cli("template", "7402", "--json", gateway=FakeGateway()).json()
        self.assertEqual(list(data), ["id", "name", "type", "description", "spaceKey", "labels", "blueprint", "variables", "variablesComplete", "body"])
        self.assertEqual((data["variables"], data["variablesComplete"], data["spaceKey"], data["labels"], data["blueprint"]), (["version"], True, "ENG", ["release", "checklist"], None))
        self.assertEqual(data["body"], {"format": "markdown", "value": "## Release\n\n- Update the notes\n- Tag", "dropped": ["html:at:var"]})
        storage = run_cli("template", "7402", "--format", "storage", "--json", gateway=FakeGateway()).json()
        self.assertEqual((storage["body"]["format"], storage["body"]["dropped"], storage["variables"]), ("storage", [], ["version"]))
        self.assertEqual(run_cli("template", "7402", "--json", gateway=FakeGateway()).err, "")

    def test_a_template_without_a_body_and_one_that_the_format_cannot_show(self):
        gateway = FakeGateway()
        gateway.templates["7498"] = Template("7498", "Empty", "page", "", "", (), "", "")
        gateway.templates["7497"] = Template("7497", "Only variables", "page", "", "", (), "", '<at:var at:name="a"/>')
        self.assertTrue(run_cli("template", "7498", gateway=gateway).out.endswith("(the template is empty)\n"))
        only = run_cli("template", "7497", gateway=gateway).out
        self.assertIn("(nothing that this format can show: `--format storage` shows the body)", only)
        self.assertRegex(only, r"Variables:\s+a\n")

    def test_a_list_of_variables_that_may_be_incomplete_says_so(self):
        gateway = FakeGateway()
        gateway.templates["7495"] = Template("7495", "Broken", "page", "", "", (), "", '<at:var at:name="ok"/>' + "<at:var " * 50_000)
        result = run_cli("template", "7495", "--format", "storage", gateway=gateway)  # the converter of the other formats is not made for such a body
        self.assertEqual(result.code, 0, result.err)
        self.assertRegex(result.out, r"Variables:\s+ok, \.\.\.\n")
        self.assertIn("may be incomplete", result.err)
        data = run_cli("template", "7495", "--format", "storage", "--json", gateway=gateway).json()
        self.assertEqual((data["variables"], data["variablesComplete"]), (["ok"], False))

    def test_text_with_a_line_break_cannot_pretend_to_be_another_line(self):
        gateway = FakeGateway()
        gateway.templates["7499"] = Template("7499", "Name\nSpace: spoof", "page", "first\nSpace: spoof", "ENG", ("a\nSpace: spoof",), "x\nSpace: spoof", "<p>x</p>")
        out = run_cli("template", "7499", gateway=gateway).out
        self.assertEqual(sum(1 for line in out.splitlines() if line.startswith("Space:")), 1)
        self.assertEqual(out.splitlines()[0].count("\n"), 0)

    def test_the_policy_that_hides_people_changes_nothing_because_nobody_is_shown(self):
        self.assertEqual(run_cli("template", "7403", gateway=FakeGateway(), settings=default_settings(hide_users=True)).code, 0)

    def test_what_is_not_there_is_a_refusal_of_confluence_and_what_is_no_id_is_invalid(self):
        result = run_cli("template", "99999", gateway=FakeGateway())
        self.assertEqual((result.code, result.out), (5, ""))
        self.assertIn("there is no template 99999, or this account may not see it", result.err)
        for text in ("page", "blueprint", "../x", "a b", ""):
            with self.subTest(text=text):
                self.assertEqual(run_cli("template", text, gateway=FakeGateway()).code, 1)
        self.assertEqual(run_cli("template", gateway=FakeGateway()).code, 2)
        self.assertEqual(run_cli("template", "7402", "--format", "html", gateway=FakeGateway()).code, 2)

    def test_the_error_is_json_when_json_is_asked_for_and_names_no_word_of_confluence(self):
        gateway = FakeGateway()
        gateway.errors["get_template"] = AuthError("Confluence refused this request (HTTP 403): alex@example.com", hint="x", details={"status": 403})
        result = run_cli("template", "7402", "--json", gateway=gateway)
        self.assertEqual((result.code, result.error()["code"], result.error()["exitCode"]), (5, "AUTH", 5))
        self.assertNotIn("alex@example.com", result.err)


if __name__ == "__main__":
    unittest.main()
