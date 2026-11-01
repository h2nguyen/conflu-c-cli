"""`--out FILE` against the mock Confluence, with the real file system and as a child process.

`conflu page ID --format storage --with-users --body-only > page.xml` was the recipe of the guides. In Windows PowerShell 5.1 `>` decodes what the program
printed (UTF-8) with the code page of the console and stores UTF-16, so `Grüße` becomes `Gr├╝├ƒe`, and `update --file page.xml` writes that back. A
file that the program writes itself is UTF-8 whatever the shell does; these tests read it back as bytes. Everything runs against the bundled mock.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from tests.integration.test_end_to_end import ACCOUNT, ROOT, EndToEnd, Result
from tests.support.mock_blogposts import BlogpostsRoutes
from tests.support.mock_templates import TemplatesRoutes

UNICODE = "Grüße € naïve café – “quotes”"
POLISH = "Zażółć gęślą jaźń"  # not in Windows-1252: a console with that code page cannot show it


class OutFlow(EndToEnd):
    def setUp(self):
        super().setUp()
        self.mock.area(BlogpostsRoutes)
        self.templates = self.mock.area(TemplatesRoutes)
        self.folder = self.root / "files"
        self.folder.mkdir()

    def path(self, name="page.xml"):
        return str(self.folder / name)

    def child_in(self, folder, *argv):
        """As `child`, started in `folder`: a relative path writes there, so that a mistake of the program cannot leave a file in the working folder of the tests."""
        base = {key: value for key, value in os.environ.items() if not key.startswith(("CONFLUENCE_", "PYTHON"))}
        done = subprocess.run(
            [sys.executable, "-I", "-X", "utf8", str(ROOT / "conflu.py"), *argv],
            capture_output=True, text=True, encoding="utf-8", errors="replace", env={**base, **self.env}, cwd=str(folder), timeout=60,
        )
        return Result(done.returncode, done.stdout, done.stderr)

    def targets(self):
        found = []
        for item in self.mock.requests:
            query = "&".join(f"{key}={value[0]}" for key, value in item.query.items())
            found.append(f"{item.method} {item.path}" + (f"?{query}" if query else ""))
        return found

    def page_with(self, text=UNICODE, title="Unicode page"):
        return self.cli("create", "--space", "ENG", "--title", title, "--body", text, "--json").json()["pageId"]

    def blogpost_with(self, text=UNICODE):
        return self.cli("blogpost-create", "--space", "ENG", "--title", "Unicode post", "--body", text, "--json").json()["blogpostId"]

    def template_with(self, text=UNICODE):
        return self.templates.add_template("Unicode template", f"<p>{text}</p>", space_key="ENG")

    def bodies(self):
        """(a name, the arguments that print the body, with `--out` after them) for the three commands that have a body and a file."""
        return (
            ("page", ("page", self.page_with(), "--format", "storage", "--body-only")),
            ("blogpost", ("blogpost", self.blogpost_with(), "--format", "storage", "--body-only")),
            ("template", ("template", self.template_with(), "--format", "storage", "--body-only")),
        )

    def assertUtf8(self, data, expected_text):
        self.assertEqual(data, expected_text.encode("utf-8"))
        self.assertFalse(data.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")), "no byte-order mark")
        self.assertNotIn(b"\x00", data, "UTF-16 has NULs")
        self.assertNotIn(b"\r", data, "line ends are plain")


class WriteTest(OutFlow):
    def test_a_body_with_umlauts_euro_and_quotes_is_written_as_utf_8_and_read_back_as_bytes(self):
        for name, argv in self.bodies():
            with self.subTest(command=name):
                printed = self.cli(*argv).out
                self.assertIn(UNICODE, printed)
                target = self.path(f"{name}.xml")
                result = self.cli(*argv, "--out", target)
                self.assertEqual(result.code, 0, result.err)
                data = Path(target).read_bytes()
                self.assertUtf8(data, printed)  # what standard output would have held, as bytes
                self.assertIn("Grüße".encode("utf-8"), data)
                self.assertEqual(result.out, f"Wrote {len(data)} bytes to {target}\n")
                self.assertNotIn("Gr├╝├ƒe".encode("utf-8"), data)

    def test_convert_writes_the_storage_format_the_same_way(self):
        source = self.folder / "notes.md"
        source.write_bytes(f"# {UNICODE}\n\nBody.\n".encode("utf-8"))
        result = self.cli("convert", str(source), "--out", self.path("converted.xml"))
        self.assertEqual(result.code, 0, result.err)
        data = Path(self.path("converted.xml")).read_bytes()
        self.assertUtf8(data, self.cli("convert", str(source)).out)
        self.assertIn(f"<h1>{UNICODE}</h1>".encode("utf-8"), data)
        self.assertEqual(result.out, f"Wrote {len(data)} bytes to {self.path('converted.xml')}\n")

    def test_the_answer_in_json_and_in_an_envelope(self):
        for name, argv in self.bodies():
            with self.subTest(command=name):
                target = self.path(f"{name}.json.xml")
                shown = self.cli(*argv, "--out", target, "--json").json()
                self.assertEqual(shown, {"file": target, "bytes": len(Path(target).read_bytes())})
                wrapped = self.cli(*argv, "--out", self.path(f"{name}.env.xml"), "--json-envelope").json()
                self.assertEqual(wrapped, {"ok": True, "data": {"file": self.path(f"{name}.env.xml"), "bytes": len(Path(self.path(f"{name}.env.xml")).read_bytes())}})

    def test_the_folders_that_are_missing_are_made_and_no_temporary_file_is_left(self):
        target = self.folder / "a" / "b" / "page.xml"
        page_id = self.page_with()
        self.assertEqual(self.cli("page", page_id, "--body-only", "--out", str(target)).code, 0)
        self.assertTrue(target.is_file())
        self.assertEqual(sorted(path.name for path in target.parent.iterdir()), ["page.xml"])  # written whole or not at all: no `.tmp` left

    def test_it_costs_the_requests_of_the_command_without_it(self):
        page_id = self.page_with()
        before = len(self.mock.requests)
        self.cli("page", page_id, "--format", "storage", "--body-only")
        plain = self.targets()[before:]
        before = len(self.mock.requests)
        self.cli("page", page_id, "--format", "storage", "--body-only", "--out", self.path())
        self.assertEqual(self.targets()[before:], plain)
        self.assertEqual([item for item in self.mock.requests[-len(plain) :] if item.method != "GET"], [])  # it asks, and changes nothing in Confluence

    def test_what_was_saved_is_what_update_sees_and_a_word_changed_in_it_is_the_only_change(self):
        """The recipe of the guides: save the source, edit it, write it back."""
        page_id = self.page_with()
        self.assertEqual(self.cli("page", page_id, "--format", "storage", "--with-users", "--body-only", "--out", self.path()).code, 0)
        unchanged = self.cli("update", page_id, "--file", self.path(), "--format", "storage", "--dry-run", "--json")
        self.assertEqual((unchanged.code, unchanged.json()["action"]), (0, "unchanged"), unchanged.err)  # nothing was damaged on the way into the file
        Path(self.path()).write_bytes(Path(self.path()).read_bytes().replace("naïve".encode("utf-8"), "naive".encode("utf-8")))
        self.assertEqual(self.cli("update", page_id, "--file", self.path(), "--format", "storage").code, 0)
        now = self.cli("page", page_id, "--format", "storage", "--with-users", "--body-only").out
        self.assertEqual(now, f"<p>{UNICODE.replace('naïve', 'naive')}</p>\n")

    def test_a_cut_part_is_written_as_it_is_shown(self):
        page_id = self.page_with("# One\n\nFirst part.\n\n# Two\n\nSecond part: " + UNICODE + "\n")
        shown = self.cli("page", page_id, "--body-only", "--section", "Two").out
        self.assertEqual(self.cli("page", page_id, "--body-only", "--section", "Two", "--out", self.path("two.md")).code, 0)
        self.assertUtf8(Path(self.path("two.md")).read_bytes(), shown)
        self.assertIn(UNICODE, shown)


class ChildProcessTest(OutFlow):
    """The way a shell or an agent starts the program."""

    def test_a_child_writes_the_file_and_prints_one_line(self):
        page_id = self.page_with()
        printed = self.child("page", page_id, "--format", "storage", "--body-only")
        done = self.child("page", page_id, "--format", "storage", "--body-only", "--out", self.path())
        self.assertEqual((done.code, done.err), (0, ""))
        data = Path(self.path()).read_bytes()
        self.assertUtf8(data, printed.out)
        self.assertEqual(done.out, f"Wrote {len(data)} bytes to {self.path()}\n")

    def test_a_child_in_json_and_with_the_other_commands(self):
        for name, argv in self.bodies():
            with self.subTest(command=name):
                target = self.path(f"child-{name}.xml")
                done = self.child(*argv, "--out", target, "--json")
                self.assertEqual(done.code, 0, done.err)
                self.assertEqual(json.loads(done.out), {"file": target, "bytes": len(Path(target).read_bytes())})
                self.assertIn(UNICODE.encode("utf-8"), Path(target).read_bytes())
        source = self.folder / "notes.md"
        source.write_bytes(f"# {UNICODE}\n".encode("utf-8"))
        done = self.child("convert", str(source), "--out", self.path("child-convert.xml"))
        self.assertEqual((done.code, done.err), (0, ""))
        self.assertIn(f"<h1>{UNICODE}</h1>".encode("utf-8"), Path(self.path("child-convert.xml")).read_bytes())

    def test_a_console_with_another_code_page_does_not_matter(self):
        """Python is told that the console is Windows-1252, and the text has letters that this code page cannot hold: the file is UTF-8 all the same."""
        page_id = self.page_with(POLISH)
        base = {key: value for key, value in os.environ.items() if not key.startswith(("CONFLUENCE_", "PYTHON"))}
        environment = {**base, **self.env, "PYTHONUTF8": "0", "PYTHONIOENCODING": "cp1252:replace"}
        done = subprocess.run(
            [sys.executable, str(ROOT / "conflu.py"), "page", page_id, "--format", "storage", "--body-only", "--out", self.path()],
            capture_output=True, env=environment, timeout=60,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertUtf8(Path(self.path()).read_bytes(), f"<p>{POLISH}</p>\n")
        self.assertTrue(done.stdout.startswith(b"Wrote "))

    def test_a_refusal_is_the_usual_error_with_its_exit_code(self):
        page_id = self.page_with()
        Path(self.path()).write_bytes(b"mine")
        done = self.child("page", page_id, "--body-only", "--out", self.path())
        self.assertEqual(done.code, 1)
        self.assertIn("exists already", done.err)
        self.assertIn("Hint: Use --force", done.err)
        self.assertEqual(Path(self.path()).read_bytes(), b"mine")
        self.assertEqual(self.child("page", page_id, "--out", self.path("other.xml")).code, 2)
        self.assertFalse(Path(self.path("other.xml")).exists())
        self.assertEqual(json.loads(self.child("page", page_id, "--body-only", "--out", self.path(), "--json").err)["error"]["exitCode"], 1)


class NothingIsReplacedTest(OutFlow):
    def refused(self, argv, code):
        before = len(self.mock.requests)
        result = self.cli(*argv)
        self.assertEqual(result.code, code, result.err)
        self.assertEqual(self.targets()[before:], [], "the path is judged before Confluence is asked for anything")
        self.assertEqual(result.out, "")
        return result

    def test_a_file_that_is_there_is_kept_and_nothing_is_asked(self):
        page_id = self.page_with()
        Path(self.path()).write_bytes(b"mine")
        result = self.refused(("page", page_id, "--body-only", "--out", self.path()), 1)
        self.assertIn("exists already", result.err)
        self.assertEqual(Path(self.path()).read_bytes(), b"mine")

    def test_force_replaces_it_with_the_body_whole(self):
        page_id = self.page_with()
        Path(self.path()).write_bytes(b"mine, and longer than the replacement would ever be" * 40)
        result = self.cli("page", page_id, "--body-only", "--format", "storage", "--out", self.path(), "--force")
        self.assertEqual(result.code, 0, result.err)
        self.assertUtf8(Path(self.path()).read_bytes(), f"<p>{UNICODE}</p>\n")  # nothing of the old file is left

    def test_a_folder_is_not_replaced(self):
        page_id = self.page_with()
        self.refused(("page", page_id, "--body-only", "--out", str(self.folder), "--force"), 1)
        self.assertTrue(self.folder.is_dir())
        self.refused(("page", page_id, "--body-only", "--out", str(self.folder / "new") + os.sep), 2)  # a separator at the end names a folder
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_a_device_is_neither_read_nor_replaced_and_nobody_waits_for_it(self):
        """`--force` looks into a file that is there for the token. A device (`nul`, `/dev/null`, the console) has no end: it is refused first."""
        page_id = self.page_with()
        done = self.child("page", page_id, "--body-only", "--out", os.devnull, "--force")
        self.assertEqual(done.code, 1, done.err)
        self.assertIn("is not a plain file", done.err)
        self.assertEqual(done.out, "")

    def test_the_settings_file_is_refused_even_with_force_and_stays_as_it_was(self):
        page_id = self.page_with()
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_bytes(f"CONFLUENCE_API_TOKEN={self.mock.token}\n".encode("utf-8"))
        for force in ((), ("--force",)):
            with self.subTest(force=force):
                result = self.refused(("page", page_id, "--body-only", "--out", str(self.config), *force), 2)
                self.assertIn("configuration file of this CLI", result.err)
                self.assertNotIn(self.mock.token, result.err)
        spelled = str(self.config.parent / ".." / self.config.parent.name / self.config.name)  # another way to the same file
        self.refused(("page", page_id, "--body-only", "--out", spelled, "--force"), 2)
        self.refused(("blogpost", self.blogpost_with(), "--body-only", "--out", str(self.config), "--force"), 2)
        self.refused(("template", self.template_with(), "--body-only", "--out", str(self.config), "--force"), 2)
        self.refused(("convert", str(self.folder), "--out", str(self.config), "--force"), 2)
        self.assertEqual(self.config.read_bytes(), f"CONFLUENCE_API_TOKEN={self.mock.token}\n".encode("utf-8"))

    def test_nothing_is_written_next_to_the_settings(self):
        page_id = self.page_with()
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_bytes(b"x\n")
        self.refused(("page", page_id, "--body-only", "--out", str(self.config.parent / "page.xml"), "--force"), 2)
        self.assertEqual(sorted(path.name for path in self.config.parent.iterdir()), [self.config.name])
        self.assertEqual(self.cli("page", page_id, "--body-only", "--out", str(self.config.parent / "sub" / "page.xml")).code, 0)  # below it is no risk

    def test_a_file_that_holds_the_token_is_kept_even_with_force(self):
        page_id = self.page_with()
        notes = self.folder / "notes.txt"
        for codec in ("utf-8", "utf-16"):  # what an editor or Windows PowerShell 5.1 makes of a copy
            with self.subTest(codec=codec):
                notes.write_bytes(f"my token: {self.mock.token}\n".encode(codec))
                result = self.refused(("page", page_id, "--body-only", "--out", str(notes), "--force"), 2)
                self.assertIn("holds the API token", result.err)
                self.assertNotIn(self.mock.token, result.err)
                self.assertEqual(notes.read_bytes(), f"my token: {self.mock.token}\n".encode(codec))

    def test_the_option_without_the_body_alone_is_a_usage_error_and_nothing_is_asked(self):
        page_id = self.page_with()
        for argv in (("page", page_id, "--out", self.path()), ("page", page_id, "--out", self.path(), "--json"), ("blogpost", "7101", "--out", self.path()), ("template", "7402", "--out", self.path())):
            with self.subTest(argv=argv[:2]):
                result = self.refused(argv, 2)
                self.assertIn("--body-only", result.err)
                self.assertIn("--out", result.err)
        self.assertFalse(Path(self.path()).exists())
        self.refused(("page", page_id, "--force"), 2)

    def test_an_empty_value_is_an_error_and_makes_no_file(self):
        page_id = self.page_with()
        for value in ("", "  ", "-"):
            with self.subTest(value=value):
                done = self.child_in(self.folder, "page", page_id, "--body-only", "--out", value)
                self.assertEqual(done.code, 2, done.err)
                self.assertEqual(done.out, "")
        self.assertEqual(list(self.folder.iterdir()), [])  # nothing appeared in the folder that the program was started in

    def test_a_page_that_is_not_there_leaves_no_file_behind(self):
        for argv in (("page", "999"), ("blogpost", "999"), ("template", "999")):
            with self.subTest(argv=argv):
                result = self.cli(*argv, "--body-only", "--out", self.path("gone.xml"))
                self.assertNotEqual(result.code, 0)
        self.assertFalse(Path(self.path("gone.xml")).exists())
        self.assertEqual(list(self.folder.iterdir()), [])


class PeopleTest(OutFlow):
    """What the file holds is what the screen would show: people stay out unless they are asked for."""

    def test_without_users_the_file_has_no_account_id_and_no_address(self):
        for name, argv in (("page", ("page", "2002", "--format", "storage", "--body-only")), ("blogpost", ("blogpost", "7101", "--format", "storage", "--body-only")), ("template", ("template", "7403", "--format", "storage", "--body-only"))):
            with self.subTest(command=name):
                target = self.path(f"{name}.xml")
                result = self.cli(*argv, "--out", target)
                saved = Path(target).read_text(encoding="utf-8")
                self.assertNotIn(ACCOUNT, saved)
                self.assertNotIn("alex@example.com", saved)
                self.assertIn('ri:account-id="hidden"', saved)
                self.assertIn("[email]", saved)
                self.assertNotIn(ACCOUNT, result.out + result.err)

    def test_with_users_the_file_is_the_page_as_confluence_keeps_it(self):
        result = self.cli("page", "2002", "--format", "storage", "--body-only", "--with-users", "--out", self.path())
        self.assertEqual(result.code, 0, result.err)
        saved = Path(self.path()).read_text(encoding="utf-8")
        self.assertIn(f'ri:account-id="{ACCOUNT}"', saved)
        self.assertIn("alex@example.com", saved)
        self.assertNotIn(ACCOUNT, result.out)

    def test_the_policy_that_hides_people_refuses_with_users_and_no_file_is_made(self):
        result = self.cli("page", "2002", "--body-only", "--with-users", "--out", self.path(), env={"CONFLUENCE_HIDE_USERS": "true"})
        self.assertEqual(result.code, 1)
        self.assertFalse(Path(self.path()).exists())

    def test_the_markdown_that_convert_makes_of_storage_format_is_not_redacted_and_that_of_page_is(self):
        source = self.folder / "page.xml"
        source.write_text('<p>Mail alex@example.com</p>', encoding="utf-8")
        self.assertEqual(self.cli("convert", str(source), "--source", "storage", "--out", self.path("page.md")).code, 0)
        self.assertIn("alex@example.com", Path(self.path("page.md")).read_text(encoding="utf-8"))  # it converts what it is given
        self.assertEqual(self.cli("page", "2002", "--body-only", "--out", self.path("shown.md")).code, 0)
        self.assertNotIn("alex@example.com", Path(self.path("shown.md")).read_text(encoding="utf-8"))
