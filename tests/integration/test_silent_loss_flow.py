"""What the Markdown cannot carry is named wherever the names are shown, and a Markdown that would replace it is refused (the real program against the mock).

A page whose storage format links to a blog post, to a space, to a shortcut or to content by its id, holds a named anchor or a placeholder: the Markdown shows the
text of the link, or nothing, and these were dropped without a name once, so that `update --file` and `import-md` took them away without a word."""
import json

from tests.integration.test_end_to_end import EndToEnd
from tests.support.mock_blogposts import BlogpostsRoutes

TEXT = "<ac:plain-text-link-body><![CDATA[the post]]></ac:plain-text-link-body>"
LINKS = {
    "link:blogpost": ('<ac:link><ri:blog-post ri:content-title="Release 2026" ri:posting-day="2026/10/01" ri:space-key="ENG" />{}</ac:link>', "ri:blog-post"),
    "link:space": ('<ac:link><ri:space ri:space-key="ENG" />{}</ac:link>', "ri:space"),
    "link:shortcut": ('<ac:link><ri:shortcut ri:key="jira" ri:parameter="ENG-1" />{}</ac:link>', "ri:shortcut"),
    "link:content": ('<ac:link><ri:content-entity ri:content-id="12345" />{}</ac:link>', "ri:content-entity"),
}


def constructs():
    """(what it is, the name, the storage format of a page that holds it, what stays in the page while nobody replaces the body)."""
    for name, (link, marker) in LINKS.items():
        yield f"{name} with text", name, f"<p>Read {link.format(TEXT)} now.</p>", marker
        yield f"{name} without text", name, f"<p>Read {link.format('')} now.</p>", marker
    yield "anchor", "anchor", '<p><a name="top"></a>Top of the page.</p>', 'name="top"'
    yield "placeholder", "placeholder", "<p>Date: <ac:placeholder>type a date</ac:placeholder></p>", "ac:placeholder"


class LostConstructsFlow(EndToEnd):
    def seed(self, body):
        self.mock.pages["2005"]["versions"][-1]["body"] = body

    def stored(self):
        return self.mock.pages["2005"]["versions"][-1]["body"]

    def puts(self):
        return [item for item in self.mock.requests if item.method == "PUT"]

    def edited(self, name="edited.md"):
        """A Markdown file that is the Markdown of the page with one paragraph more."""
        path = self.root / name
        path.write_text(self.cli("page", "2005", "--body-only").out.rstrip() + "\n\nAn edit.\n", encoding="utf-8")
        return path


class ShownTest(LostConstructsFlow):
    def test_the_page_names_it_in_the_json_and_on_standard_error(self):
        for what, name, body, _ in constructs():
            self.seed(body)
            with self.subTest(what=what):
                self.assertEqual(self.cli("page", "2005", "--json").json()["body"]["dropped"], [name])
                self.assertIn(f"The Markdown cannot show: {name}.", self.cli("page", "2005").err)

    def test_export_writes_it_as_lossy_into_the_file_and_the_index(self):
        for number, (what, name, body, _) in enumerate(constructs()):
            self.seed(body)
            out = self.root / f"mirror{number}"
            with self.subTest(what=what):
                self.assertEqual(self.cli("export", "--space", "ENG", "--out", str(out)).code, 0)
                index = json.loads((out / "index.json").read_text(encoding="utf-8"))
                self.assertEqual(next(page["lossy"] for page in index["pages"] if page["id"] == "2005"), [name])
                self.assertIn(f"lossy: {name}\n", (out / "plain-page-2005.md").read_text(encoding="utf-8"))

    def test_convert_names_it_on_standard_error(self):
        for what, name, body, _ in constructs():
            path = self.root / "page.xml"
            path.write_text(body, encoding="utf-8")
            with self.subTest(what=what):
                result = self.cli("convert", str(path), "--source", "storage")
                self.assertEqual(result.code, 0, result.err)
                self.assertIn(f"The Markdown cannot show: {name}.", result.err)

    def test_the_history_names_it_too(self):
        for what, name, body, _ in constructs():
            self.seed(body)
            changed = self.cli("update", "2005", "--body", "<p>Other.</p>", "--format", "storage", "--json")
            self.assertEqual(changed.code, 0, changed.err)
            version = changed.json()["versionTo"]
            diff = self.cli("diff", "2005", "--from", str(version - 1), "--to", str(version), "--json")
            with self.subTest(what=what):
                self.assertEqual((diff.code, diff.json()["dropped"]), (0, [name]))


class ReplaceTest(LostConstructsFlow):
    def test_update_from_markdown_is_refused_with_the_name_and_forced(self):
        for what, name, body, marker in constructs():
            self.seed(body)
            edited = self.edited()
            self.mock.requests.clear()
            version = len(self.mock.pages["2005"]["versions"])
            with self.subTest(what=what):
                refused = self.cli("update", "2005", "--file", str(edited))
                self.assertEqual((refused.code, refused.out), (1, ""))
                self.assertIn(f"would lose what Markdown cannot say: {name}.", refused.err)
                as_json = self.cli("update", "2005", "--file", str(edited), "--json")
                self.assertEqual(json.loads(as_json.err.strip().splitlines()[-1])["error"]["details"]["lost"], [name])
                self.assertEqual(self.cli("update", "2005", "--file", str(edited), "--dry-run").code, 1)
                self.assertEqual((self.puts(), len(self.mock.pages["2005"]["versions"]), marker in self.stored()), ([], version, True))
                preview = self.cli("update", "2005", "--file", str(edited), "--force", "--dry-run", "--json")
                self.assertEqual((preview.code, preview.json()["lost"], preview.json()["dryRun"]), (0, [name], True))
                self.assertEqual(self.puts(), [])
                forced = self.cli("update", "2005", "--file", str(edited), "--force", "--json")
                self.assertEqual((forced.code, forced.json()["lost"], forced.json()["action"]), (0, [name], "updated"))
                self.assertEqual((len(self.mock.pages["2005"]["versions"]), marker in self.stored(), "An edit." in self.stored()), (version + 1, False, True))

    def test_what_a_markdown_that_is_the_pages_own_changes_nothing_and_an_append_keeps_it_all(self):
        for what, name, body, marker in constructs():
            self.seed(body)
            own = self.root / "own.md"
            own.write_text(self.cli("page", "2005", "--body-only").out, encoding="utf-8")
            tail = self.root / "tail.md"
            tail.write_text("A tail.\n", encoding="utf-8")
            self.mock.requests.clear()
            with self.subTest(what=what):
                unchanged = self.cli("update", "2005", "--file", str(own), "--json")
                self.assertEqual((unchanged.code, unchanged.json()["action"], self.puts()), (0, "unchanged", []))
                appended = self.cli("update", "2005", "--file", str(tail), "--append", "--json")
                self.assertEqual((appended.code, appended.json()["lost"]), (0, []))
                self.assertIn(marker, self.stored())
                self.assertIn("<p>A tail.</p>", self.stored())

    def test_import_md_and_import_md_dir_are_refused_the_same_way(self):
        for number, (what, name, body, marker) in enumerate(constructs()):
            self.seed(body)
            out = self.root / f"mirror{number}"
            self.assertEqual(self.cli("export", "--space", "ENG", "--out", str(out)).code, 0)
            file = out / "plain-page-2005.md"
            file.write_text(file.read_text(encoding="utf-8").rstrip() + "\n\nAn edit.\n", encoding="utf-8")
            with self.subTest(what=what):
                single = self.cli("import-md", str(file))
                self.assertEqual(single.code, 1)
                self.assertIn(name, single.err)
                report = self.cli("import-md-dir", str(out), "--continue-on-error", "--json")
                failed = [item for item in report.json()["outcomes"] if item["action"] == "failed"]
                self.assertEqual(len(failed), 1)
                self.assertIn(name, failed[0]["message"])
                self.assertIn(marker, self.stored())
                forced = self.cli("import-md", str(file), "--force", "--json")
                self.assertEqual((forced.code, forced.json()["lost"]), (0, [name]))
                self.assertNotIn(marker, self.stored())

    def test_a_page_without_them_is_replaced_without_a_word(self):
        self.seed("<p>Plain text.</p>")
        result = self.cli("update", "2005", "--file", str(self.edited()), "--json")
        self.assertEqual((result.code, result.json()["lost"], result.json()["action"]), (0, [], "updated"))
        self.assertIn("An edit.", self.stored())

    def test_the_names_that_were_there_before_are_still_there(self):
        self.seed('<p>Hello <ac:link><ri:user ri:account-id="5b10ac8d82e05b22cc7d4ef5" /></ac:link> <ac:link><ri:page ri:content-title="Guide" /></ac:link></p>')
        refused = self.cli("update", "2005", "--file", str(self.edited()))
        self.assertEqual(refused.code, 1)
        self.assertIn("would lose what Markdown cannot say: link:page, mention.", refused.err)

    def test_a_blog_post_is_guarded_in_the_same_way(self):
        area = self.mock.area(BlogpostsRoutes)
        for what, name, body, marker in constructs():
            area.blogposts["7102"]["versions"][-1]["body"] = body
            with self.subTest(what=what):
                self.assertEqual(self.cli("blogpost", "7102", "--json").json()["body"]["dropped"], [name])
                self.mock.requests.clear()
                refused = self.cli("blogpost-update", "7102", "--body", "New text.")
                self.assertEqual(refused.code, 1)
                self.assertIn(f"would lose what Markdown cannot say: {name}.", refused.err)
                self.assertEqual([item for item in self.mock.requests if item.method == "PUT"], [])
                forced = self.cli("blogpost-update", "7102", "--body", "New text.", "--force", "--json")
                self.assertEqual((forced.code, forced.json()["lost"]), (0, [name]))
                self.assertNotIn(marker, area.blogposts["7102"]["versions"][-1]["body"])
