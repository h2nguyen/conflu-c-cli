"""A personal space is keyed by `~` and the account id of its owner: where that key (not the name or the address, which other tests cover) comes out of a
command that does not list spaces. The rule is the one of `privacy.is_personal_space`; these are the places that took it from there after `spaces`, `space`
and `use` did: what `pages`, `blogposts`, `labels`, `tasks` and `templates` say about the space they list, the query that `search` echoes, the links in the body of a page, and
the storage format that `--format storage` and `--raw` show."""
import unittest

from conflu_c_cli.application.rendering import render_body, storage_from_input
from conflu_c_cli.domain.errors import AuthError, ValidationError
from conflu_c_cli.domain.model import Space, User
from conflu_c_cli.domain.privacy import HIDDEN, PERSONAL_SPACE, has_blanked_mentions, redact_query, redact_storage
from conflu_c_cli.domain.storage import storage_to_markdown, storage_to_text
from conflu_c_cli.domain.tasks import INCOMPLETE, Task
from conflu_c_cli.domain.templates import Template
from tests.support.fakes import ACCOUNT, BASE, FakeGateway, build_app, default_settings, sample_page

KEY = f"~{ACCOUNT}"


def link(key: str, title: str = "Notes", label: str = "") -> str:
    body = f"<ac:plain-text-link-body><![CDATA[{label}]]></ac:plain-text-link-body>" if label else ""
    return f'<ac:link><ri:page ri:space-key="{key}" ri:content-title="{title}" />{body}</ac:link>'


def app_with_personal_space():
    gateway = FakeGateway()
    gateway.spaces[KEY] = Space("1003", KEY, "Alex Example", "personal", "current", "Notes of alex@example.com", "2101", "2026-09-02T08:00:00.000Z", f"{BASE}/spaces/{KEY}/overview")
    gateway.pages["2101"] = sample_page("2101", "Notes", space_id="1003", space_key=KEY, labels=("diary",))
    return build_app(gateway=gateway, settings=default_settings()), gateway


def with_tasks_and_templates():
    """The personal space with a task on its page, a page template and a template of a blueprint."""
    app, gateway = app_with_personal_space()
    alex = User(ACCOUNT)
    gateway.tasks["7301"] = Task(
        "7301", INCOMPLETE, "1003", "2101", "", "1", "<span>Call the owner</span>", alex, alex, None, "2026-10-02T09:00:00.000Z", "2026-10-02T09:00:00.000Z", "2026-11-30T00:00:00.000Z", ""
    )
    gateway.templates["7501"] = Template("7501", "Personal checklist", "page", "Notes of the owner", KEY, ("diary",), "", f"<p>See {link(KEY, 'Notes', 'the notes')}</p>")
    gateway.templates["7502"] = Template("7502", "Personal retrospective", "blueprint", "", KEY, (), "retrospectives-blueprint", "<p>Went well</p>")
    return app, gateway


class MarkdownLinkTest(unittest.TestCase):
    def test_a_link_into_a_personal_space_does_not_name_the_account_id_of_its_owner(self):
        converted = storage_to_markdown(f"<p>See {link(KEY, 'Notes', 'the notes')}.</p>")
        self.assertEqual(converted.text, "See [the notes](page:[hidden]/Notes).")
        self.assertEqual(converted.dropped, ("link:page",))
        self.assertNotIn(ACCOUNT, converted.text)

    def test_a_short_key_that_starts_with_a_tilde_is_a_personal_space_too(self):
        self.assertEqual(storage_to_markdown(f"<p>{link('~alexe')}</p>").text, "[Notes](page:[hidden]/Notes)")

    def test_with_people_shown_the_key_stays_as_confluence_gives_it(self):
        self.assertEqual(storage_to_markdown(f"<p>{link(KEY, label='n')}</p>", show_mentions=True).text, f"[n](page:{KEY}/Notes)")

    def test_any_other_link_is_what_it_was(self):
        self.assertEqual(storage_to_markdown(f"<p>{link('ENG', 'Guide', 'Read me')}</p>").text, "[Read me](page:ENG/Guide)")
        self.assertEqual(storage_to_markdown('<p><ac:link><ri:page ri:content-title="Guide" /></ac:link></p>').text, "[Guide](page:Guide)")

    def test_the_text_of_a_body_has_the_label_and_no_key(self):
        self.assertEqual(storage_to_text(f"<p>{link(KEY, label='the notes')}</p>"), "the notes")

    def test_a_link_to_a_blog_post_or_to_the_space_says_no_key_in_markdown(self):
        body = f'<p><ac:link><ri:blog-post ri:space-key="{KEY}" ri:content-title="News" /></ac:link><ac:link><ri:space ri:space-key="{KEY}" /></ac:link></p>'
        self.assertNotIn(ACCOUNT, storage_to_markdown(body).text)

    def test_a_page_shows_it_through_render_body_in_every_format_but_storage(self):
        body = f"<p>See {link(KEY, 'Notes', 'the notes')}.</p>"
        self.assertEqual(render_body(body, "markdown", with_users=False).text, "See [the notes](page:[hidden]/Notes).")
        self.assertEqual(render_body(body, "text", with_users=False).text, "See the notes.")
        self.assertIn(KEY, render_body(body, "markdown", with_users=True).text)


class StorageTest(unittest.TestCase):
    def test_the_key_of_a_personal_space_in_a_link_is_hidden_in_storage_format(self):
        shown = redact_storage(f"<p>{link(KEY, label='n')}</p>")
        self.assertIn(f'ri:space-key="{HIDDEN}"', shown)
        self.assertNotIn(ACCOUNT, shown)

    def test_every_kind_of_link_and_the_attribute_wherever_it_stands(self):
        body = (
            f'<ri:blog-post ri:space-key="{KEY}" ri:content-title="News" /><ri:space ri:space-key="{KEY}" />'
            f'<ac:structured-macro ac:name="include"><ac:parameter ac:name="">{link(KEY)}</ac:parameter></ac:structured-macro><ri:page ri:content-title="x" ri:space-key="~alexe" />'
        )
        shown = redact_storage(body)
        self.assertEqual(shown.count(f'ri:space-key="{HIDDEN}"'), 4)
        self.assertNotIn("~", shown)

    def test_the_key_of_any_other_space_and_the_rest_of_the_body_stay(self):
        body = f"<p>{link('ENG', 'Guide')} and {link('DOCS')}</p>"
        self.assertEqual(redact_storage(body), body)

    def test_mentions_are_blanked_as_before(self):
        shown = redact_storage(f'<ri:user ri:account-id="{ACCOUNT}" />{link(KEY)}')
        self.assertIn('ri:account-id="hidden"', shown)
        self.assertIn(f'ri:space-key="{HIDDEN}"', shown)

    def test_what_was_hidden_is_known_by_the_guard_that_keeps_it_from_being_written_back(self):
        self.assertTrue(has_blanked_mentions(redact_storage(f"<p>{link(KEY)}</p>")))
        self.assertTrue(has_blanked_mentions(f'<ri:user ri:account-id="hidden" />'))
        self.assertFalse(has_blanked_mentions(f"<p>{link('ENG')}</p>"))
        self.assertFalse(has_blanked_mentions(redact_storage(f"<p>{link('ENG')}</p>")))

    def test_a_body_that_was_read_without_people_is_refused_as_input(self):
        with self.assertRaises(ValidationError) as caught:
            storage_from_input(redact_storage(f"<p>{link(KEY)}</p>"), "storage")
        self.assertIn("personal space whose key was hidden", caught.exception.message)
        self.assertIn("mentions whose account ids were hidden", caught.exception.message)
        self.assertEqual(storage_from_input(f"<p>{link('ENG')}</p>", "storage"), f"<p>{link('ENG')}</p>")
        self.assertEqual(storage_from_input(f"<p>{link(KEY)}</p>", "storage"), f"<p>{link(KEY)}</p>")  # the key as Confluence gives it is the real link


class QueryTest(unittest.TestCase):
    def test_the_key_of_a_personal_space_in_a_query_is_hidden(self):
        self.assertEqual(redact_query(f'space = "{KEY}" AND type = page'), 'space = "[hidden]" AND type = page')
        self.assertEqual(redact_query(f'space in ("ENG", "{KEY}", "~alexe")'), 'space in ("ENG", "[hidden]", "[hidden]")')
        self.assertEqual(redact_query(f"space = {KEY}"), "space = [hidden]")

    def test_every_form_of_a_comparison_that_names_spaces(self):
        cases = {
            'space.key = "~alexe"': 'space.key = "[hidden]"',
            'SPACE = "~alexe"': 'SPACE = "[hidden]"',
            'space!="~alexe"': 'space!="[hidden]"',
            'space not in ("~a", "ENG", "~b")': 'space not in ("[hidden]", "ENG", "[hidden]")',
            'space in("~a","~b") AND type = page': 'space in("[hidden]","[hidden]") AND type = page',
            'space = "~a" OR space = "~b"': 'space = "[hidden]" OR space = "[hidden]"',
            'type = page AND space = ~alexe AND label = "x"': 'type = page AND space = [hidden] AND label = "x"',
            'space   =   "~alexe"': 'space   =   "[hidden]"',
            f'space = "{KEY}" AND text ~ "~notes"': 'space = "[hidden]" AND text ~ "~notes"',  # the text search that follows is left alone
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                self.assertEqual(redact_query(query), expected)

    def test_the_operator_that_looks_for_text_and_any_other_query_stay(self):
        for query in (
            'text ~ "alex" AND type = page',
            'title ~"x*"',
            'label = "my~label"',
            'text ~ "a~b"',
            'type = page AND space = "ENG"',
            "~",
            "",
            'text !~ "x"',
            'text ~ "jira atlassian"~10',  # proximity
            'text ~ "jira"~0.8 AND space = "ENG"',
            'title ~ "~notes"',  # a text that happens to start with a tilde
            'text ~ jira~ AND title ~ conflu~2',  # fuzziness
            'workspace = "~alexe"',  # not the field `space`
            'text ~ "space"',
        ):
            with self.subTest(query=query):
                self.assertEqual(redact_query(query), query)

    def test_nothing_is_a_query_that_is_empty(self):
        self.assertEqual(redact_query(None), "")

    def test_an_account_id_of_a_person_is_not_a_key_and_stays(self):
        self.assertEqual(redact_query(f'creator = "{ACCOUNT}"'), f'creator = "{ACCOUNT}"')

    def test_a_query_made_of_comparisons_that_never_end_is_read_in_a_time_that_grows_with_its_length(self):
        import time

        for unit in ("space = (", 'space = "', "space in (", "space  ", "space = ~a space = ~a ", "space in (~a, " * 2, "space.key = " + " " * 100):
            text = unit * (400_000 // len(unit))
            with self.subTest(unit=unit[:14]):
                started = time.perf_counter()
                redact_query(text)
                self.assertLess(time.perf_counter() - started, 3.0)

    def test_a_list_that_never_ends_is_hidden_to_its_end(self):
        shown = redact_query('space in ("ENG", "~alexe", "~bob"')
        self.assertEqual(shown, 'space in ("ENG", "[hidden]", "[hidden]"')

    def test_a_run_of_tildes_and_dashes_is_read_in_a_time_that_grows_with_its_length(self):
        import time

        for unit in ("~-", "~", "~:", "~.-", "~-a", "a~-", "~~-"):
            for clause in ('space = "%s"', "space = %s", "space in (%s)"):
                text = clause % (unit * (200_000 // len(unit)))
                with self.subTest(unit=unit, clause=clause):
                    started = time.perf_counter()
                    redact_query(text)
                    self.assertLess(time.perf_counter() - started, 3.0)

    def test_the_pattern_finds_what_the_old_one_found_that_had_to_end_in_a_letter(self):
        import random
        import re

        from conflu_c_cli.domain.privacy import _PERSONAL_KEY, _hide_personal_key

        old = re.compile(r"(?<![\w~])~[\w:.~-]*\w")
        generator = random.Random(2026)
        alphabet = "~~~-:.a1_ \"'(),"
        for _ in range(30_000):
            text = "".join(generator.choice(alphabet) for _ in range(generator.randint(0, 40)))
            self.assertEqual(_PERSONAL_KEY.sub(_hide_personal_key, text), old.sub(HIDDEN, text), text)


class ListsTest(unittest.TestCase):
    def test_pages_say_of_the_space_what_spaces_say(self):
        app, gateway = app_with_personal_space()
        for kwargs in ({}, {"fetch_everything": True}, {"limit": 1}):
            with self.subTest(kwargs=kwargs):
                listed = app.list_pages.execute(space=KEY, **kwargs)
                self.assertEqual((listed.space.key, listed.space.name, listed.space.id), (HIDDEN, PERSONAL_SPACE, "1003"))
                self.assertEqual([page.id for page in listed.pages], ["2101"])
        self.assertEqual(gateway.called("get_space")[-1], ("get_space", KEY))  # Confluence is asked by the key that was typed
        self.assertEqual(gateway.called("list_pages")[-1][1], "1003")

    def test_pages_of_any_other_space_and_of_no_space(self):
        app, _ = app_with_personal_space()
        self.assertEqual(app.list_pages.execute(space="ENG").space.key, "ENG")
        self.assertIsNone(app.list_pages.execute().space)

    def test_the_current_space_is_masked_when_it_is_a_personal_space(self):
        gateway = FakeGateway()
        gateway.spaces[KEY] = Space("1003", KEY, "Alex Example", "personal", "current")
        app = build_app(gateway=gateway, settings=default_settings(space=KEY))
        self.assertEqual(app.list_pages.execute().space.key, HIDDEN)

    def test_blog_posts_say_of_the_space_what_spaces_say(self):
        app, gateway = app_with_personal_space()
        for kwargs in ({}, {"fetch_everything": True}):
            with self.subTest(kwargs=kwargs):
                listed = app.blogposts.list_blogposts.execute(space=KEY, **kwargs)
                self.assertEqual((listed.space.key, listed.space.name, listed.space.id), (HIDDEN, PERSONAL_SPACE, "1003"))
        self.assertEqual(gateway.called("get_space")[-1], ("get_space", KEY))
        self.assertEqual(app.blogposts.list_blogposts.execute(space="ENG").space.key, "ENG")

    def test_the_labels_of_a_space_say_of_the_space_what_spaces_say(self):
        app, gateway = app_with_personal_space()
        for kwargs in ({}, {"fetch_everything": True}):
            with self.subTest(kwargs=kwargs):
                found = app.labels.in_space.execute(KEY, **kwargs)
                self.assertEqual((found.space.key, found.space.name, found.space.id), (HIDDEN, PERSONAL_SPACE, "1003"))
                self.assertEqual([label.name for label in found.labels], ["diary"])
        self.assertEqual(gateway.called("get_space")[-1], ("get_space", KEY))
        self.assertEqual(app.labels.in_space.execute("ENG").space.key, "ENG")


class SearchTest(unittest.TestCase):
    def test_the_query_that_ran_is_not_printed_with_the_key_that_it_names(self):
        app, gateway = app_with_personal_space()
        result = app.search_content.execute(text="notes", space=KEY)
        self.assertIn('space = "[hidden]"', result.cql)
        self.assertNotIn(ACCOUNT, result.cql)
        self.assertIn(f'space = "{KEY}"', gateway.called("search")[-1][1])  # what was sent is the query itself

    def test_a_query_that_the_person_wrote_is_hidden_as_well(self):
        app, gateway = app_with_personal_space()
        query = f'space = "{KEY}" AND type = page'
        self.assertEqual(app.search_content.execute(cql=query).cql, 'space = "[hidden]" AND type = page')
        self.assertEqual(gateway.called("search")[-1][1], query)

    def test_with_people_shown_the_query_is_as_it_ran(self):
        app, _ = app_with_personal_space()
        self.assertIn(f'space = "{KEY}"', app.search_content.execute(text="notes", space=KEY, with_users=True).cql)

    def test_any_other_space_and_no_space(self):
        app, _ = app_with_personal_space()
        self.assertIn('space = "ENG"', app.search_content.execute(text="notes", space="ENG").cql)
        self.assertNotIn("space =", app.search_content.execute(text="notes").cql)


class TasksTest(unittest.TestCase):
    def test_the_space_of_the_list_is_said_as_spaces_say_it_and_the_filter_is_the_id(self):
        app, gateway = with_tasks_and_templates()
        for kwargs in ({}, {"fetch_everything": True}):
            with self.subTest(kwargs=kwargs):
                listed = app.tasks.list_tasks.execute(space=KEY, **kwargs)
                self.assertEqual((listed.space.key, listed.space.name, listed.space.id), (HIDDEN, PERSONAL_SPACE, "1003"))
                self.assertEqual([view.task.id for view in listed.tasks], ["7301"])
        self.assertEqual(gateway.called("get_space")[-1], ("get_space", KEY))  # Confluence is asked by the key that was typed
        self.assertEqual(gateway.called("list_tasks")[-1][3], ("1003",))

    def test_with_people_shown_the_space_is_as_confluence_gives_it(self):
        app, _ = with_tasks_and_templates()
        listed = app.tasks.list_tasks.execute(space=KEY, with_users=True)
        self.assertEqual((listed.space.key, listed.space.name), (KEY, "Alex Example"))

    def test_any_other_space_and_no_space(self):
        app, _ = with_tasks_and_templates()
        self.assertEqual(app.tasks.list_tasks.execute(space="ENG").space.key, "ENG")
        self.assertIsNone(app.tasks.list_tasks.execute().space)


class TemplatesTest(unittest.TestCase):
    def test_the_space_of_the_list_and_of_every_template_in_it_is_hidden(self):
        app, gateway = with_tasks_and_templates()
        for kwargs in ({}, {"fetch_everything": True}):
            with self.subTest(kwargs=kwargs):
                listed = app.templates.list_templates.execute(space=KEY, **kwargs)
                self.assertEqual(listed.space, HIDDEN)
                self.assertEqual([(item.id, item.space_key) for item in listed.templates], [("7501", HIDDEN)])
        blueprints = app.templates.list_templates.execute(space=KEY, blueprints=True)
        self.assertEqual((blueprints.space, [(item.id, item.space_key) for item in blueprints.templates]), (HIDDEN, [("7502", HIDDEN)]))
        self.assertEqual({call[1] for call in gateway.called("list_templates")}, {KEY})  # every call names the space by its real key

    def test_a_refusal_names_the_space_as_hidden_and_keeps_its_words_out(self):
        app, gateway = with_tasks_and_templates()
        gateway.errors["list_templates"] = AuthError("Confluence refused this request (HTTP 403).", details={"status": 403})
        for blueprints, words in ((False, "the templates of the space [hidden]"), (True, "the blueprint templates of the space [hidden]")):
            with self.subTest(blueprints=blueprints), self.assertRaises(AuthError) as caught:
                app.templates.list_templates.execute(space=KEY, blueprints=blueprints)
            self.assertIn(words, caught.exception.message)
            self.assertNotIn(ACCOUNT, caught.exception.message + caught.exception.hint)
        with self.assertRaises(AuthError) as caught:
            app.templates.list_templates.execute(space=KEY, fetch_everything=True)
        self.assertIn("the space [hidden]", caught.exception.message)

    def test_one_template_has_its_space_hidden_and_so_has_a_link_in_its_body(self):
        app, _ = with_tasks_and_templates()
        view = app.templates.show_template.execute("7501")
        self.assertEqual(view.template.space_key, HIDDEN)
        self.assertIn("[the notes](page:[hidden]/Notes)", view.body.text)
        stored = app.templates.show_template.execute("7501", body_format="storage")
        self.assertIn('ri:space-key="[hidden]"', stored.body.text)
        self.assertNotIn(ACCOUNT, view.body.text + stored.body.text)

    def test_the_global_templates_and_those_of_another_space_are_what_they_were(self):
        app, _ = with_tasks_and_templates()
        self.assertEqual(app.templates.list_templates.execute().space, "")
        self.assertEqual(app.templates.list_templates.execute(space="ENG").space, "ENG")
        self.assertEqual({item.space_key for item in app.templates.list_templates.execute(space="ENG", fetch_everything=True).templates}, {"ENG"})
        self.assertEqual(app.templates.show_template.execute("7402").template.space_key, "ENG")
        self.assertEqual(app.templates.show_template.execute("7401").template.space_key, "")


if __name__ == "__main__":
    unittest.main()
