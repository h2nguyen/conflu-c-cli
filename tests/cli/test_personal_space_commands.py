"""A personal space is keyed by `~` and the account id of its owner: the commands that list what is in a space, search it, or show a page that links into it
do not print the key, as `spaces`, `space` and `use` do not (tests/cli/test_spaces_commands.py), unless people are asked for with `--with-users`."""
import json
import unittest

from conflu_c_cli.domain.errors import AuthError
from conflu_c_cli.domain.model import Comment, Space, User
from conflu_c_cli.domain.privacy import redact_storage
from conflu_c_cli.domain.tasks import INCOMPLETE, Task
from conflu_c_cli.domain.templates import Template
from tests.support.cli import run_cli
from tests.support.fakes import ACCOUNT, BASE, FakeGateway, default_settings, sample_page

KEY = f"~{ACCOUNT}"
LINK = f'<ac:link><ri:page ri:space-key="{KEY}" ri:content-title="Personal notes" /><ac:plain-text-link-body><![CDATA[the notes]]></ac:plain-text-link-body></ac:link>'
OUTSIDE = f"<p>See {LINK}, {LINK.replace('Personal notes', 'Other')} and " f'<ac:link><ri:space ri:space-key="{KEY}" /></ac:link>.</p>'
POLICY = default_settings(hide_users=True)


def fresh() -> FakeGateway:
    gateway = FakeGateway()
    gateway.spaces[KEY] = Space("1003", KEY, "Alex Example", "personal", "current", "Notes of alex@example.com", "2101", "2026-09-02T08:00:00.000Z", f"{BASE}/spaces/{KEY}/overview")
    gateway.pages["2101"] = sample_page("2101", "Personal notes", space_id="1003", space_key=KEY, body=f"<p>See {LINK}.</p>", labels=("diary",))
    gateway.pages["2102"] = sample_page("2102", "Links into a personal space", parent_id="2001", body=OUTSIDE)
    gateway.comments["2102"] = [Comment("4200", "footer", "2026-10-12T09:00:00.000Z", f"<p>See {LINK}.</p>", 1, User(ACCOUNT))]
    return gateway


def with_tasks_and_templates() -> FakeGateway:
    """The personal space with a task on its page, a page template and a template of a blueprint."""
    gateway = fresh()
    alex = User(ACCOUNT)
    gateway.tasks["7301"] = Task(
        "7301", INCOMPLETE, "1003", "2101", "", "1", f"<span>Call the owner, see {LINK}</span>", alex, alex, None, "2026-10-02T09:00:00.000Z", "2026-10-02T09:00:00.000Z", "2026-11-30T00:00:00.000Z", ""
    )
    gateway.templates["7501"] = Template("7501", "Personal checklist", "page", "Notes of the owner", KEY, ("diary",), "", f"<h2>Checklist</h2><p>See {LINK}</p><p><at:var at:name=\"topic\" /></p>")
    gateway.templates["7502"] = Template("7502", "Personal retrospective", "blueprint", "", KEY, (), "retrospectives-blueprint", "<p>Went well</p>")
    return gateway


class ListsTest(unittest.TestCase):
    def test_pages_say_of_the_space_what_spaces_say_and_the_rest_is_as_it_was(self):
        data = run_cli("pages", "--space", KEY, "--all", "--json", gateway=fresh()).json()
        self.assertEqual((data["space"], data["count"], [page["id"] for page in data["pages"]]), ("[hidden]", 1, ["2101"]))
        self.assertEqual(run_cli("pages", "--space", "ENG", "--json", gateway=fresh()).json()["space"], "ENG")

    def test_blog_posts_say_of_the_space_what_spaces_say(self):
        data = run_cli("blogposts", "--space", KEY, "--json", gateway=fresh()).json()
        self.assertEqual((data["space"], data["count"]), ("[hidden]", 0))
        self.assertEqual(run_cli("blogposts", "--space", "ENG", "--json", gateway=fresh()).json()["space"], "ENG")

    def test_the_labels_of_a_space_say_of_the_space_what_spaces_say(self):
        data = run_cli("labels", "--space", KEY, "--all", "--json", gateway=fresh()).json()
        self.assertEqual((data["space"], data["spaceId"], [label["name"] for label in data["labels"]]), ("[hidden]", "1003", ["diary"]))
        self.assertEqual(run_cli("labels", "--space", "ENG", "--json", gateway=fresh()).json()["space"], "ENG")

    def test_select_and_format_work_as_before(self):
        picked = run_cli("pages", "--space", KEY, "--select", "id,title", "--json", gateway=fresh()).json()
        self.assertEqual((picked["space"], picked["pages"]), ("[hidden]", [{"id": "2101", "title": "Personal notes"}]))
        tsv = run_cli("labels", "--space", KEY, "--select", "name", "--format", "tsv", gateway=fresh()).out
        self.assertEqual(tsv.splitlines(), ["name", "diary"])

    def test_no_account_id_comes_out_of_any_of_them_under_either_policy(self):
        for settings in (None, POLICY):
            for argv in (("pages", "--space", KEY), ("pages", "--space", KEY, "--json"), ("blogposts", "--space", KEY, "--json"), ("labels", "--space", KEY), ("labels", "--space", KEY, "--json")):
                with self.subTest(argv=argv, strict=settings is not None):
                    result = run_cli(*argv, gateway=fresh(), settings=settings)
                    self.assertEqual(result.code, 0, result.err)
                    self.assertNotIn(ACCOUNT, result.out + result.err)

    def test_the_current_space_is_one_of_them_too(self):
        data = run_cli("pages", "--json", gateway=fresh(), settings=default_settings(space=KEY)).json()
        self.assertEqual(data["space"], "[hidden]")


class SearchTest(unittest.TestCase):
    def test_the_query_that_ran_does_not_name_the_key_in_json_or_in_the_raw_answer(self):
        gateway = fresh()
        document = run_cli("search", "notes", "--space", KEY, "--json", gateway=gateway).json()
        self.assertIn('space = "[hidden]"', document["cql"])
        raw = run_cli("search", "notes", "--space", KEY, "--raw", gateway=gateway)
        self.assertEqual(json.loads(raw.out)["cql"], document["cql"])
        self.assertNotIn(ACCOUNT, raw.out + raw.err)
        self.assertIn(f'space = "{KEY}"', gateway.called("search")[-1][1])  # Confluence got the real key

    def test_a_query_that_the_person_wrote_is_hidden_the_same_way(self):
        gateway = fresh()
        query = f'space = "{KEY}" AND type = page'
        self.assertEqual(run_cli("search", "--cql", query, "--json", gateway=gateway).json()["cql"], 'space = "[hidden]" AND type = page')
        self.assertEqual(gateway.called("search")[-1][1], query)

    def test_with_people_shown_the_query_is_as_it_ran(self):
        document = run_cli("search", "notes", "--space", KEY, "--with-users", "--json", gateway=fresh()).json()
        self.assertIn(f'space = "{KEY}"', document["cql"])

    def test_the_policy_refuses_people_and_still_hides_the_key(self):
        refused = run_cli("search", "notes", "--space", KEY, "--with-users", gateway=fresh(), settings=POLICY)
        self.assertEqual((refused.code, refused.out), (1, ""))
        self.assertNotIn(ACCOUNT, refused.err)
        self.assertIn('space = "[hidden]"', run_cli("search", "notes", "--space", KEY, "--json", gateway=fresh(), settings=POLICY).json()["cql"])

    def test_a_space_that_is_not_personal_is_searched_and_shown_as_before(self):
        self.assertIn('space = "ENG"', run_cli("search", "notes", "--space", "ENG", "--json", gateway=fresh()).json()["cql"])


class LinksTest(unittest.TestCase):
    def test_a_page_that_links_into_a_personal_space_shows_the_link_without_the_key(self):
        result = run_cli("page", "2102", gateway=fresh())
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("[the notes](page:[hidden]/Personal notes)", result.out)
        self.assertIn("[the notes](page:[hidden]/Other)", result.out)
        self.assertNotIn(ACCOUNT, result.out + result.err)

    def test_json_text_storage_outline_and_raw_have_no_key_either(self):
        for argv in (("--json",), ("--format", "text"), ("--format", "storage"), ("--outline",), ("--raw",), ("--json", "--ancestors", "--comments"), ("--format", "storage", "--json")):
            with self.subTest(argv=argv):
                result = run_cli("page", "2102", *argv, gateway=fresh())
                self.assertEqual(result.code, 0, result.err)
                self.assertNotIn(ACCOUNT, result.out + result.err)

    def test_storage_format_names_the_key_as_hidden(self):
        shown = run_cli("page", "2102", "--format", "storage", gateway=fresh()).out
        self.assertEqual(shown.count('ri:space-key="[hidden]"'), 3)

    def test_with_people_shown_the_key_is_as_confluence_gives_it(self):
        gateway = fresh()
        markdown = run_cli("page", "2102", "--with-users", gateway=gateway).out
        storage = run_cli("page", "2102", "--with-users", "--format", "storage", gateway=gateway).out
        self.assertIn(f"[the notes](page:{KEY}/Personal notes)", markdown)
        self.assertIn(f'ri:space-key="{KEY}"', storage)

    def test_the_policy_refuses_people_and_still_hides_the_key(self):
        refused = run_cli("page", "2102", "--with-users", gateway=fresh(), settings=POLICY)
        self.assertEqual((refused.code, refused.out), (1, ""))
        self.assertNotIn(ACCOUNT, refused.err)
        shown = run_cli("page", "2102", gateway=fresh(), settings=POLICY)
        self.assertIn("page:[hidden]/Personal notes", shown.out)
        self.assertNotIn(ACCOUNT, shown.out + shown.err)

    def test_the_comments_of_a_page_show_the_link_without_the_key(self):
        gateway = fresh()
        listed = run_cli("comments", "2102", gateway=gateway)
        self.assertIn("[the notes](page:[hidden]/Personal notes)", listed.out)
        one = run_cli("comment", "2102", "--get", "4200", "--format", "storage", gateway=gateway)
        self.assertIn('ri:space-key="[hidden]"', one.out)
        for result in (listed, one, run_cli("comments", "2102", "--json", gateway=gateway), run_cli("page", "2102", "--comments", gateway=gateway)):
            self.assertNotIn(ACCOUNT, result.out + result.err)

    def test_a_page_in_the_personal_space_that_links_to_itself_is_the_same(self):
        shown = run_cli("page", "2101", gateway=fresh()).out
        self.assertIn("[the notes](page:[hidden]/Personal notes)", shown)
        self.assertNotIn(ACCOUNT, shown)

    def test_a_link_to_a_team_space_is_what_it_was(self):
        gateway = fresh()
        gateway.pages["2103"] = sample_page("2103", "Guide links", body='<p><ac:link><ri:page ri:space-key="ENG" ri:content-title="Guide" /></ac:link></p>')
        self.assertIn("[Guide](page:ENG/Guide)", run_cli("page", "2103", gateway=gateway).out)


class WritingBackTest(unittest.TestCase):
    def test_a_body_read_without_people_is_refused_as_storage_input_and_nothing_is_written(self):
        gateway = fresh()
        hidden = redact_storage(OUTSIDE)
        result = run_cli("update", "2102", "--format", "storage", "--body", hidden, gateway=gateway)
        self.assertEqual(result.code, 1)
        self.assertIn("personal space whose key was hidden", result.err)
        self.assertEqual(gateway.called("update_page"), [])

    def test_the_dry_run_of_the_same_is_refused_too(self):
        gateway = fresh()
        result = run_cli("update", "2102", "--format", "storage", "--body", redact_storage(OUTSIDE), "--dry-run", gateway=gateway)
        self.assertEqual(result.code, 1)
        self.assertEqual(gateway.called("update_page"), [])

    def test_the_real_links_are_written_as_they_are(self):
        gateway = fresh()
        body = OUTSIDE + "<p>More.</p>"
        result = run_cli("update", "2102", "--format", "storage", "--body", body, "--force", gateway=gateway)
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(gateway.called("update_page")[-1][2]["body"]["value"], body)


class TasksAndTemplatesTest(unittest.TestCase):
    def test_tasks_say_of_the_space_what_spaces_say(self):
        gateway = with_tasks_and_templates()
        data = run_cli("tasks", "--space", KEY, "--json", gateway=gateway).json()
        self.assertEqual((data["space"], data["count"], [task["id"] for task in data["tasks"]], data["tasks"][0]["spaceId"]), ("[hidden]", 1, ["7301"], "1003"))
        self.assertEqual(run_cli("tasks", "--space", "ENG", "--json", gateway=gateway).json()["space"], "ENG")
        self.assertIsNone(run_cli("tasks", "--json", gateway=gateway).json()["space"])

    def test_with_people_shown_the_key_is_as_confluence_gives_it_and_the_policy_refuses_that(self):
        gateway = with_tasks_and_templates()
        self.assertEqual(run_cli("tasks", "--space", KEY, "--with-users", "--json", gateway=gateway).json()["space"], KEY)
        refused = run_cli("tasks", "--space", KEY, "--with-users", gateway=gateway, settings=POLICY)
        self.assertEqual((refused.code, refused.out), (1, ""))
        self.assertNotIn(ACCOUNT, refused.err)

    def test_templates_say_of_the_space_and_of_every_template_what_spaces_say(self):
        gateway = with_tasks_and_templates()
        data = run_cli("templates", "--space", KEY, "--json", gateway=gateway).json()
        self.assertEqual((data["space"], [(item["id"], item["spaceKey"]) for item in data["templates"]]), ("[hidden]", [("7501", "[hidden]")]))
        blueprints = run_cli("templates", "--blueprints", "--space", KEY, "--json", gateway=gateway).json()
        self.assertEqual((blueprints["space"], blueprints["templates"][0]["spaceKey"]), ("[hidden]", "[hidden]"))
        table = run_cli("templates", "--space", KEY, gateway=gateway).out.splitlines()
        self.assertEqual(table[0].split(), ["ID", "NAME", "TYPE", "SPACE", "DESCRIPTION"])
        self.assertEqual(table[1].split()[:2], ["7501", "Personal"])
        self.assertIn("[hidden]", table[1])
        tsv = run_cli("templates", "--space", KEY, "--select", "id,spaceKey", "--format", "tsv", gateway=gateway).out
        self.assertEqual(tsv.splitlines(), ["id\tspaceKey", "7501\t[hidden]"])

    def test_one_template_shows_the_space_and_the_links_in_its_body_as_hidden_in_every_form(self):
        gateway = with_tasks_and_templates()
        text = run_cli("template", "7501", gateway=gateway)
        self.assertIn("Space:       [hidden]\n", text.out)
        self.assertIn("[the notes](page:[hidden]/Personal notes)", text.out)
        self.assertEqual(run_cli("template", "7501", "--json", gateway=gateway).json()["spaceKey"], "[hidden]")
        self.assertIn("page:[hidden]/Personal notes", run_cli("template", "7501", "--body-only", gateway=gateway).out)
        self.assertIn('ri:space-key="[hidden]"', run_cli("template", "7501", "--format", "storage", "--body-only", gateway=gateway).out)

    def test_the_templates_of_another_space_and_the_global_ones_are_what_they_were(self):
        gateway = with_tasks_and_templates()
        team = run_cli("templates", "--space", "ENG", "--all", "--json", gateway=gateway).json()
        self.assertEqual((team["space"], {item["spaceKey"] for item in team["templates"]}), ("ENG", {"ENG"}))
        site = run_cli("templates", "--all", "--json", gateway=gateway).json()
        self.assertEqual((site["space"], {item["spaceKey"] for item in site["templates"]}), (None, {None}))
        self.assertEqual(run_cli("template", "7402", "--json", gateway=gateway).json()["spaceKey"], "ENG")
        self.assertIn("Space:       (global)", run_cli("template", "7401", gateway=gateway).out)

    def test_a_refusal_names_the_space_as_hidden(self):
        gateway = with_tasks_and_templates()
        gateway.errors["list_templates"] = AuthError("Confluence refused this request (HTTP 403).", details={"status": 403})
        refused = run_cli("templates", "--space", KEY, gateway=gateway)
        self.assertEqual((refused.code, refused.out), (5, ""))
        self.assertIn("the templates of the space [hidden]", refused.err)
        self.assertNotIn(ACCOUNT, refused.err)

    def test_no_account_id_comes_out_of_any_of_them_under_either_policy(self):
        invocations = (
            ("tasks", "--space", KEY),
            ("tasks", "--space", KEY, "--json"),
            ("tasks", "--page", "2101", "--json"),
            ("task", "7301"),
            ("task", "7301", "--complete", "--dry-run"),
            ("templates", "--space", KEY),
            ("templates", "--space", KEY, "--json"),
            ("templates", "--blueprints", "--space", KEY),
            ("template", "7501"),
            ("template", "7501", "--json"),
            ("template", "7501", "--body-only"),
            ("template", "7502", "--json"),
        )
        for settings in (None, POLICY):
            for argv in invocations:
                with self.subTest(argv=argv, strict=settings is not None):
                    result = run_cli(*argv, gateway=with_tasks_and_templates(), settings=settings)
                    self.assertEqual(result.code, 0, result.err)
                    self.assertNotIn(ACCOUNT, result.out + result.err)


if __name__ == "__main__":
    unittest.main()
