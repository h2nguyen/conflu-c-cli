"""The use cases around the templates of a space, against the fake Confluence: list the page templates and those of blueprints, and read one with its variables."""
import unittest

from conflu_c_cli.application.templates import ListTemplates, hide_people, replaced_in
from conflu_c_cli.domain.errors import AuthError, NotFoundError, UsageError, ValidationError
from conflu_c_cli.domain.templates import Template, TemplateInfo, TemplatePage
from tests.support.fakes import ACCOUNT, FakeGateway, RecordingDiagnostics, build_app, default_settings

BLUEPRINT = "7408a0b1-c2d3-4e5f-8a6b-7c8d9e0f1a2b"


def fresh():
    gateway = FakeGateway()
    app = build_app(gateway=gateway, settings=default_settings(), diagnostics=RecordingDiagnostics())
    return app, gateway


def ids(result):
    return [item.id for item in result.templates]


def asked(gateway):
    return [call[1:] for call in gateway.called("list_templates")]  # (space key, blueprints, limit, start)


class ListTemplatesTest(unittest.TestCase):
    def test_without_a_space_the_global_page_templates_are_listed(self):
        app, gateway = fresh()
        result = app.templates.list_templates.execute()
        self.assertEqual((ids(result), result.space, result.blueprints, result.start, result.next_start, result.truncated), (["7401"], "", False, 0, None, False))
        self.assertEqual(asked(gateway), [("", False, 25, 0)])
        self.assertEqual(gateway.called("get_space"), [])  # no space to ask for

    def test_the_templates_of_a_space_come_in_the_order_of_their_names_a_piece_at_a_time(self):
        app, gateway = fresh()
        first = app.templates.list_templates.execute(space="ENG")
        self.assertEqual((ids(first), first.next_start, first.space), (["7404", "7403"], 2, "ENG"))  # Decision record, Incident report
        second = app.templates.list_templates.execute(space="ENG", start=first.next_start)
        self.assertEqual((ids(second), second.start, second.next_start), (["7402"], 2, None))  # Release checklist
        self.assertEqual(asked(gateway), [("ENG", False, 25, 0), ("ENG", False, 25, 2)])

    def test_all_of_them_in_big_pieces_until_the_end(self):
        app, gateway = fresh()
        result = app.templates.list_templates.execute(space="ENG", fetch_everything=True, limit=1, start=2)
        self.assertEqual((ids(result), result.start, result.next_start, result.truncated), (["7404", "7403", "7402"], 0, None, False))
        self.assertEqual([call[2:] for call in asked(gateway)], [(100, 0), (100, 2)])  # the limit and the start that were given are not used for all of it

    def test_the_templates_that_blueprints_provide(self):
        app, gateway = fresh()
        self.assertEqual(ids(app.templates.list_templates.execute(blueprints=True, fetch_everything=True)), ["7406", "7407"])
        result = app.templates.list_templates.execute(space="ENG", blueprints=True)
        self.assertEqual((ids(result), result.blueprints, result.templates[0].type), ([BLUEPRINT], True, "blueprint"))
        self.assertEqual(asked(gateway)[-1], ("ENG", True, 25, 0))

    def test_a_key_is_written_as_the_space_writes_it(self):
        app, gateway = fresh()
        result = app.templates.list_templates.execute(space="eng")
        self.assertEqual((result.space, asked(gateway)[-1][0]), ("ENG", "ENG"))
        self.assertEqual(gateway.called("get_space"), [("get_space", "eng")])

    def test_a_space_that_is_not_there_is_not_found_and_no_template_is_asked_for(self):
        app, gateway = fresh()
        with self.assertRaises(NotFoundError):
            app.templates.list_templates.execute(space="NOPE")
        self.assertEqual(asked(gateway), [])
        for key in ("E N G", "ENG/../x", "a" * 300):
            with self.subTest(key=key[:20]), self.assertRaises(ValidationError):
                app.templates.list_templates.execute(space=key)

    def test_a_start_below_zero_is_a_usage_error_and_nothing_is_asked(self):
        app, gateway = fresh()
        with self.assertRaises(UsageError):
            app.templates.list_templates.execute(space="ENG", start=-1)
        self.assertEqual(gateway.calls, [])

    def test_the_text_of_a_template_is_redacted_like_a_title(self):
        app, gateway = fresh()
        gateway.templates["7499"] = Template("7499", "Ask alex@example.com", "page", "Write to alex@example.com", "", ("alex@example.com",), "a@b.example", "<p>x</p>")
        result = app.templates.list_templates.execute(fetch_everything=True)
        shown = next(item for item in result.templates if item.id == "7499")
        self.assertEqual((shown.name, shown.description, shown.labels, shown.blueprint), ("Ask [email]", "Write to [email]", ("[email]",), "[email]"))

    def test_a_refusal_says_what_is_known_and_none_of_the_words_of_confluence(self):
        app, gateway = fresh()
        gateway.errors["list_templates"] = AuthError("Confluence refused this request (HTTP 403): alex@example.com may not see it.", hint="x", details={"status": 403})
        for arguments, what in (({"space": "ENG"}, "the space ENG"), ({}, "the site"), ({"blueprints": True, "space": "ENG"}, "the blueprint templates of the space ENG"), ({"fetch_everything": True}, "the site")):
            with self.subTest(arguments=arguments), self.assertRaises(AuthError) as caught:
                app.templates.list_templates.execute(**arguments)
            self.assertEqual(caught.exception.exit_code, 5)
            self.assertIn("HTTP 403", caught.exception.message)
            self.assertIn(what, caught.exception.message)
            self.assertNotIn("alex@example.com", caught.exception.message + caught.exception.hint)
            self.assertEqual(caught.exception.details, {"status": 403})

    def test_credentials_that_were_not_accepted_go_on_as_they_are_and_are_not_a_403(self):
        app, gateway = fresh()
        unauthorized = AuthError("Confluence did not accept the credentials (HTTP 401).", hint="Check the token.", details={"status": 401, "request": "GET /rest/api/template/page"})
        undescribed = AuthError("Something refused.", hint="x")  # no status at all: the adapter always says one, and a fake that does not is not taken for a 403
        calls = (
            lambda: app.templates.list_templates.execute(),
            lambda: app.templates.list_templates.execute(fetch_everything=True),
            lambda: app.templates.show_template.execute("7402"),
        )
        for error in (unauthorized, undescribed):
            gateway.errors["list_templates"] = error
            gateway.errors["get_template"] = error
            for call in calls:
                with self.subTest(error=error.message), self.assertRaises(AuthError) as caught:
                    call()
                self.assertIs(caught.exception, error)

    def test_a_list_that_does_not_go_on_is_not_read_for_ever(self):
        app, gateway = fresh()
        info = TemplateInfo("1", "Same")
        gateway.list_templates = lambda **_: TemplatePage([info], 0, 0)  # the next piece starts where this one did
        self.assertEqual(ids(app.templates.list_templates.execute(fetch_everything=True)), ["1"])
        gateway.list_templates = lambda **kw: TemplatePage([info], kw["start"], kw["start"] + 1 if kw["start"] < 3 else 2)  # and one that goes back
        self.assertEqual(len(ids(app.templates.list_templates.execute(fetch_everything=True))), 4)
        gateway.list_templates = lambda **kw: TemplatePage([], kw["start"], kw["start"] + 1)  # and one that has nothing in it but says there is more
        self.assertEqual(ids(app.templates.list_templates.execute(fetch_everything=True)), [])

    def test_a_list_that_never_ends_is_cut_at_its_limit_and_says_so(self):
        app, gateway = fresh()
        calls = []

        def endless(**kw):
            calls.append(kw["start"])
            return TemplatePage([TemplateInfo(str(kw["start"] + number)) for number in range(kw["limit"])], kw["start"], kw["start"] + kw["limit"])

        gateway.list_templates = endless
        result = app.templates.list_templates.execute(fetch_everything=True)
        self.assertEqual((len(result.templates), result.truncated, result.next_start), (20_000, True, None))
        self.assertEqual(len(calls), 200)

    def test_nobody_is_asked_for_anything_but_the_templates_and_the_space(self):
        app, gateway = fresh()
        app.templates.list_templates.execute(space="ENG", fetch_everything=True)
        self.assertEqual({call[0] for call in gateway.calls}, {"get_space", "list_templates"})


class HidePeopleTest(unittest.TestCase):
    def test_the_name_the_description_the_labels_and_the_blueprint_are_redacted_and_the_rest_is_left(self):
        info = TemplateInfo("7", "alex@example.com", "page", "see https://example.atlassian.net/wiki/people/" + ACCOUNT, "ENG", ("a@b.example", "plain"), "x@y.example")
        shown = hide_people(info)
        self.assertEqual((shown.name, shown.labels, shown.blueprint), ("[email]", ("[email]", "plain"), "[email]"))
        self.assertIn("[personal link]", shown.description)
        self.assertEqual((shown.id, shown.type, shown.space_key), ("7", "page", "ENG"))


class ShowTemplateTest(unittest.TestCase):
    def test_a_template_is_its_description_its_body_and_the_variables_it_declares(self):
        app, gateway = fresh()
        view = app.templates.show_template.execute("7402")
        self.assertEqual((view.template.id, view.template.name, view.template.type, view.template.space_key, view.template.description, view.template.labels), ("7402", "Release checklist", "page", "ENG", "Steps for every release", ("release", "checklist")))
        self.assertEqual(view.variables, ("version",))
        self.assertTrue(view.variables_complete)
        self.assertEqual((view.body.format, view.body.text), ("markdown", "## Release\n\n- Update the notes\n- Tag"))
        self.assertIn("html:at:var", view.body.dropped)  # the Markdown cannot say it, so the variables are listed from the storage format
        self.assertEqual(gateway.called("get_template"), [("get_template", "7402")])

    def test_the_variables_of_a_body_are_read_from_the_storage_format_whatever_the_format_shown(self):
        app, _ = fresh()
        for body_format in ("markdown", "text", "storage"):
            with self.subTest(body_format=body_format):
                view = app.templates.show_template.execute("7404", body_format=body_format)
                self.assertEqual(view.variables, ("title", "Tom & Jerry"))  # `title` twice, one with an entity

    def test_in_storage_format_the_body_is_as_confluence_keeps_it_with_the_people_blanked(self):
        app, _ = fresh()
        view = app.templates.show_template.execute("7403", body_format="storage")
        self.assertEqual(view.body.format, "storage")
        self.assertIn('ri:account-id="hidden"', view.body.text)
        self.assertNotIn(ACCOUNT, view.body.text)
        self.assertNotIn("alex@example.com", view.body.text)
        self.assertIn("[email]", view.body.text)

    def test_how_many_addresses_and_links_the_redaction_replaced_is_counted_for_the_storage_format_only(self):
        app, gateway = fresh()
        gateway.templates["7494"] = Template(
            "7494", "Contact", "page", "", "ENG", (), "",
            '<p><a href="mailto:support@example.com">mail</a> <a href="https://example.atlassian.net/wiki/people/5b10ac8d82e05b22cc7d4ef5">me</a> and alex@example.com, [email]</p>',
        )
        self.assertEqual(app.templates.show_template.execute("7494", body_format="storage").replaced, 3)  # the [email] that the body says itself is not one of them
        self.assertEqual(app.templates.show_template.execute("7403", body_format="storage").replaced, 1)  # the mention is blanked, which `create` refuses: it is no replaced address
        self.assertEqual(app.templates.show_template.execute("7402", body_format="storage").replaced, 0)
        for body_format in ("markdown", "text"):
            self.assertEqual(app.templates.show_template.execute("7494", body_format=body_format).replaced, 0)

    def test_replaced_in_counts_the_markers_that_a_text_has_more_of(self):
        self.assertEqual(replaced_in("a alex@example.com b", "a [email] b"), 1)
        self.assertEqual(replaced_in("no one", "no one"), 0)
        self.assertEqual(replaced_in("[email] [personal link]", "[email] [personal link]"), 0)
        self.assertEqual(replaced_in("[email] x", "[email] [email] [personal link]"), 2)

    def test_in_the_other_formats_a_mention_is_a_word_and_an_address_is_redacted(self):
        app, _ = fresh()
        for body_format in ("markdown", "text"):
            with self.subTest(body_format=body_format):
                text = app.templates.show_template.execute("7403", body_format=body_format).body.text
                self.assertIn("@user", text)
                self.assertNotIn(ACCOUNT, text)
                self.assertNotIn("alex@example.com", text)

    def test_a_blueprint_template_is_read_by_its_id_as_well(self):
        app, _ = fresh()
        view = app.templates.show_template.execute(BLUEPRINT)
        self.assertEqual((view.template.type, view.template.space_key, view.template.name, view.body.text), ("blueprint", "ENG", "Retrospective", "Went well"))

    def test_a_global_template_has_no_space(self):
        app, _ = fresh()
        self.assertEqual(app.templates.show_template.execute("7401").template.space_key, "")

    def test_a_template_without_a_body_is_empty_and_one_that_the_format_cannot_show_is_not(self):
        app, gateway = fresh()
        gateway.templates["7498"] = Template("7498", "Empty", "page", "", "", (), "", "")
        gateway.templates["7497"] = Template("7497", "Variables only", "page", "", "", (), "", '<at:var at:name="a"/><at:var at:name="b"/>')
        empty = app.templates.show_template.execute("7498")
        self.assertEqual((empty.empty, empty.body.text, empty.variables), (True, "", ()))
        only = app.templates.show_template.execute("7497")
        self.assertEqual((only.empty, only.body.text, only.variables), (False, "", ("a", "b")))
        for number, body, expected in (("7496", " \n\t ", True), ("7495", "\r\n", True), ("7494", "<p></p>", False), ("7493", "<!-- note -->", False)):
            gateway.templates[number] = Template(number, "Blank", "page", "", "", (), "", body)
            with self.subTest(body=body):
                self.assertEqual(app.templates.show_template.execute(number).empty, expected)  # blanks alone are no body; markup that shows nothing is a body

    def test_the_text_of_the_template_is_redacted_like_a_title(self):
        app, gateway = fresh()
        gateway.templates["7499"] = Template("7499", "Ask alex@example.com", "page", "Write to alex@example.com", "", ("alex@example.com",), "", "<p>x</p>")
        shown = app.templates.show_template.execute("7499").template
        self.assertEqual((shown.name, shown.description, shown.labels), ("Ask [email]", "Write to [email]", ("[email]",)))

    def test_a_template_that_is_not_there_is_a_refusal_that_says_what_is_known_and_nothing_confluence_said(self):
        app, gateway = fresh()
        gateway.errors["get_template"] = AuthError("Confluence refused this request (HTTP 403): alex@example.com", hint="x", details={"status": 403, "request": "GET /rest/api/template/9"})
        with self.assertRaises(AuthError) as caught:
            app.templates.show_template.execute("9")
        self.assertEqual(caught.exception.exit_code, 5)
        self.assertIn("there is no template 9, or this account may not see it", caught.exception.message)
        self.assertNotIn("alex@example.com", caught.exception.message)
        self.assertIn("conflu templates", caught.exception.hint)
        self.assertEqual(caught.exception.details, {"status": 403, "request": "GET /rest/api/template/9"})

    def test_an_id_that_is_wrong_or_a_format_that_is_unknown_asks_nothing(self):
        app, gateway = fresh()
        for template_id in ("", "page", "../x", "a b"):
            with self.subTest(template_id=template_id), self.assertRaises(ValidationError):
                app.templates.show_template.execute(template_id)
        with self.assertRaises(UsageError):
            app.templates.show_template.execute("7402", body_format="html")
        self.assertEqual(gateway.calls, [])

    def test_a_body_that_cannot_be_converted_can_still_be_read_as_confluence_keeps_it(self):
        app, gateway = fresh()
        gateway.templates["7496"] = Template("7496", "Nested", "page", "", "", (), "", "<div>" * 200 + '<at:var at:name="deep"/>' + "</div>" * 200)
        for body_format in ("markdown", "text"):
            with self.subTest(body_format=body_format), self.assertRaises(ValidationError) as caught:
                app.templates.show_template.execute("7496", body_format=body_format)
            self.assertIn("--format storage", caught.exception.hint)
        view = app.templates.show_template.execute("7496", body_format="storage")
        self.assertEqual((view.body.format, view.variables), ("storage", ("deep",)))

    def test_a_body_of_broken_tags_is_read_quickly_and_the_list_of_variables_says_it_may_be_incomplete(self):
        app, gateway = fresh()
        gateway.templates["7495"] = Template("7495", "Broken", "page", "", "", (), "", '<at:var at:name="ok"/>' + "<at:var " * 50_000)
        view = app.templates.show_template.execute("7495", body_format="storage")
        self.assertEqual((view.variables, view.variables_complete), (("ok",), False))


class ListUseCaseConstructionTest(unittest.TestCase):
    def test_it_needs_nothing_but_the_gateway(self):
        ListTemplates(FakeGateway())


if __name__ == "__main__":
    unittest.main()
