"""`--out FILE` of `page`, `blogpost`, `template` and `convert` on the command line, with the in-memory Confluence and files: the file holds what
the command prints, as UTF-8, and the answer is one line. Where the guides used to say `> page.xml`, Windows PowerShell 5.1 damaged the file."""
import json
import unittest

from conflu_c_cli.adapters.driving.cli.registry import find_command
from conflu_c_cli.adapters.driving.cli.spec import WRITES_FILE
from tests.support.cli import run_cli
from tests.support.fakes import ACCOUNT, FakeGateway, MemoryConfigStore, default_settings, sample_page
from tests.support.places_attachments import PlacedFiles

UNICODE = "Grüße € naïve café – “quotes”"
SETTINGS = "/home/me/.config/conflu-c-cli/config"
BODY_READERS = (("page", "2002"), ("blogpost", "7101"), ("template", "7402"))  # `--body-only` is what `--out` writes
STORAGE_WITH_PEOPLE = f'<p>Mail alex@example.com, <ac:link><ri:user ri:account-id="{ACCOUNT}" /></ac:link></p>'


def run(*argv, files=None, gateway=None, **more):
    files = PlacedFiles() if files is None else files
    gateway = FakeGateway() if gateway is None else gateway
    return run_cli(*argv, files=files, gateway=gateway, store=MemoryConfigStore(path=SETTINGS), **more), files, gateway


def written(files, path):
    return files.files[path]


class DeclarationTest(unittest.TestCase):
    NAMES = ("page", "blogpost", "template", "convert")

    def test_each_has_an_optional_file_to_write_and_a_flag_that_replaces_it(self):
        for name in self.NAMES:
            arguments = {arg.names[0]: arg for arg in find_command(name).args}
            with self.subTest(command=name):
                out, force = arguments["--out"], arguments["--force"]
                self.assertEqual((out.path, out.kind, out.metavar, out.required, out.default), (WRITES_FILE, "str", "FILE", False, None))
                self.assertEqual((force.kind, force.overwrites, force.required), ("flag", True, False))
                self.assertIn("Changes nothing in Confluence", out.help)  # the one thing that this option does besides printing
                self.assertIn("UTF-8", out.help)

    def test_they_still_only_read(self):
        for name in self.NAMES:
            command = find_command(name)
            with self.subTest(command=name):
                self.assertFalse(command.writes or command.writes_files or command.destructive or command.for_person)  # not a file tool: `conflu_page` would leave the default set
                self.assertFalse(any("--dry-run" in arg.names for arg in command.args))  # there is nothing to preview: --out is the only thing they write

    def test_the_examples_and_the_notes_say_out_and_not_a_redirect(self):
        for name in self.NAMES:
            command = find_command(name)
            with self.subTest(command=name):
                self.assertTrue(any("--out" in example.command for example in command.examples))
                self.assertFalse(any(" > " in example.command for example in command.examples), "a redirect is what PowerShell 5.1 damages")
                notes = " ".join(command.notes)
                self.assertIn("PowerShell 5.1", notes)
                self.assertIn("UTF-8 without a byte-order mark", notes)
                self.assertIn("never the settings file", notes)
                self.assertIn("changes nothing in Confluence", notes)

    def test_the_convert_text_says_what_it_does_not_redact(self):
        text = " ".join(find_command("convert").description.split())
        self.assertIn("without the redaction of `page`", text)
        self.assertNotIn("prints the Markdown that `page` shows, naming", text)

    def test_the_json_shape_is_in_the_output_text_of_the_three_that_have_json(self):
        for name in ("page", "blogpost", "template"):
            self.assertIn("with --body-only --out: file, bytes", find_command(name).output)
        self.assertFalse(find_command("convert").json_output)  # convert has no JSON: its one line is text


class TheFileHoldsWhatIsPrintedTest(unittest.TestCase):
    def printed(self, name, ref, *more):
        result, _, _ = run(name, ref, "--body-only", *more)
        self.assertEqual(result.code, 0, result.err)
        return result.out

    def test_for_every_command_every_format_and_both_ways_of_hiding_people(self):
        for name, ref in BODY_READERS:
            for fmt in ("markdown", "text", "storage"):
                for users in ((), ("--with-users",)) if name != "template" else ((),):
                    argv = (name, ref, "--body-only", "--format", fmt, *users)
                    with self.subTest(argv=argv):
                        shown = self.printed(name, ref, "--format", fmt, *users)
                        result, files, _ = run(*argv, "--out", "body.out")
                        self.assertEqual(result.code, 0, result.err)
                        self.assertEqual(written(files, "body.out").decode("utf-8"), shown)  # exactly what standard output would have held

    def test_a_cut_text_is_cut_in_the_file_too(self):
        shown = self.printed("page", "2002", "--max-chars", "20")
        result, files, _ = run("page", "2002", "--body-only", "--max-chars", "20", "--out", "body.out")
        self.assertEqual(written(files, "body.out").decode("utf-8"), shown)
        self.assertIn("The text was cut", result.err)  # the notes for the person stay on standard error

    def test_a_section_is_written_as_it_is_printed(self):
        shown = self.printed("page", "2002", "--section", "Release notes")
        _, files, _ = run("page", "2002", "--body-only", "--section", "Release notes", "--out", "body.out")
        self.assertEqual(written(files, "body.out").decode("utf-8"), shown)

    def test_an_earlier_version_is_written_as_it_is_printed(self):
        shown = self.printed("page", "2002", "--version", "2", "--format", "storage")
        _, files, _ = run("page", "2002", "--body-only", "--version", "2", "--format", "storage", "--out", "body.out")
        self.assertEqual(written(files, "body.out").decode("utf-8"), shown)

    def test_the_answer_is_one_line_and_the_body_is_not_printed(self):
        for name, ref in BODY_READERS:
            with self.subTest(command=name):
                result, files, _ = run(name, ref, "--body-only", "--format", "storage", "--out", "body.out")
                data = written(files, "body.out")
                self.assertEqual(result.out, f"Wrote {len(data)} bytes to body.out\n")
                self.assertEqual(result.code, 0)
                self.assertGreater(len(data), 10)

    def test_in_json_it_is_an_object_with_the_file_and_its_size(self):
        for name, ref in BODY_READERS:
            with self.subTest(command=name):
                result, files, _ = run(name, ref, "--body-only", "--format", "storage", "--out", "sub/body.out", "--json")
                self.assertEqual(result.json(), {"file": "sub/body.out", "bytes": len(written(files, "sub/body.out"))})
                self.assertEqual(result.out.count("\n"), 1)

    def test_in_an_envelope_and_with_json_in_the_environment_it_is_the_same_object(self):
        for name, ref in BODY_READERS:
            with self.subTest(command=name):
                result, files, _ = run(name, ref, "--body-only", "--out", "body.out", "--json-envelope")
                self.assertEqual(result.json(), {"ok": True, "data": {"file": "body.out", "bytes": len(written(files, "body.out"))}})
                result, files, _ = run(name, ref, "--body-only", "--out", "again.out", environ={"CONFLUENCE_OUTPUT": "json"})
                self.assertEqual(result.json(), {"file": "again.out", "bytes": len(written(files, "again.out"))})

    def test_the_text_that_a_screen_would_not_obey_is_left_out_of_the_file_as_it_is_left_out_of_the_screen(self):
        gateway = FakeGateway()
        gateway.pages["2090"] = sample_page("2090", "Odd page", body="<p>a\x1b[2Jb\r\nc\x07d</p>")
        shown = run("page", "2090", "--body-only", "--format", "storage", gateway=gateway)[0].out
        result, files, _ = run("page", "2090", "--body-only", "--format", "storage", "--out", "odd.out", gateway=gateway)
        data = written(files, "odd.out")
        self.assertEqual(data.decode("utf-8"), shown)
        self.assertFalse({b"\x1b", b"\r", b"\x07"} & set(data[i : i + 1] for i in range(len(data))))
        self.assertEqual(data, b"<p>a[2Jb\nc" + b"d</p>\n")


class UnicodeTest(unittest.TestCase):
    """What `>` of Windows PowerShell 5.1 turns into `Gr├╝├ƒe`: the file is UTF-8, nothing else."""

    def setUp(self):
        self.gateway = FakeGateway()
        self.gateway.pages["2090"] = sample_page("2090", "Unicode page", body=f"<p>{UNICODE}</p>")

    def test_the_body_is_utf_8_without_a_mark_and_with_plain_line_ends(self):
        for fmt, expected in (("storage", f"<p>{UNICODE}</p>\n"), ("markdown", f"{UNICODE}\n"), ("text", f"{UNICODE}\n")):
            with self.subTest(format=fmt):
                result, files, _ = run("page", "2090", "--body-only", "--format", fmt, "--out", "page.out", gateway=self.gateway)
                data = written(files, "page.out")
                self.assertEqual(data, expected.encode("utf-8"))
                self.assertEqual(result.out, f"Wrote {len(data)} bytes to page.out\n")
                self.assertGreater(len(data), len(expected))  # the size is bytes, not characters
                self.assertFalse(data.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")))
                self.assertNotIn(b"\x00", data)  # UTF-16 has NULs
                self.assertNotIn(b"\r", data)
                self.assertNotIn("Gr├╝├ƒe".encode("utf-8"), data)

    def test_convert_writes_the_same_way(self):
        files = PlacedFiles({"notes.md": f"# {UNICODE}\n\nBody.\n"})
        result, _, _ = run("convert", "notes.md", "--out", "page.xml", files=files)
        self.assertEqual(written(files, "page.xml"), f"<h1>{UNICODE}</h1>\n<p>Body.</p>\n".encode("utf-8"))
        self.assertEqual(result.out, f"Wrote {len(written(files, 'page.xml'))} bytes to page.xml\n")

    def test_what_was_written_can_be_written_back_unchanged(self):
        """The recipe of the guides: save the source, edit, and `update --file ... --format storage` sends the text as it was saved."""
        _, files, _ = run("page", "2090", "--body-only", "--format", "storage", "--out", "page.xml", gateway=self.gateway)
        result, _, _ = run("update", "2090", "--file", "page.xml", "--format", "storage", "--dry-run", "--json", files=files, gateway=self.gateway)
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(json.loads(result.out)["action"], "unchanged")  # the page holds exactly what was saved: nothing was damaged on the way


class ConvertTest(unittest.TestCase):
    def test_what_is_read_from_a_pipe_goes_into_the_file(self):
        result, files, _ = run("convert", "--out", "page.xml", stdin="# Title\n\nGrüße\n")
        self.assertEqual(written(files, "page.xml"), "<h1>Title</h1>\n<p>Grüße</p>\n".encode("utf-8"))
        self.assertEqual(result.out, f"Wrote {len(written(files, 'page.xml'))} bytes to page.xml\n")
        self.assertEqual(result.err, "")

    def test_it_has_no_json_so_the_line_is_text_and_an_envelope_holds_it_as_text(self):
        self.assertEqual(run("convert", "--out", "page.xml", "--json", stdin="x\n")[0].code, 2)
        result, files, _ = run("convert", "--out", "page.xml", "--json-envelope", stdin="x\n")
        self.assertEqual(result.json(), {"ok": True, "data": {"text": f"Wrote {len(written(files, 'page.xml'))} bytes to page.xml"}})

    def test_the_conversion_to_markdown_redacts_nothing_and_says_so(self):
        files = PlacedFiles({"page.xml": STORAGE_WITH_PEOPLE})
        printed = run("convert", "page.xml", "--source", "storage", files=files)[0].out
        result, _, _ = run("convert", "page.xml", "--source", "storage", "--out", "page.md", files=files)
        saved = written(files, "page.md").decode("utf-8")
        self.assertEqual(saved, printed)
        self.assertIn("alex@example.com", saved)  # the command converts what it is given: the redaction is a thing of `page`
        self.assertIn("@user", saved)  # a mention is the one thing that Markdown shows only as a name

    def test_what_the_markdown_cannot_say_is_still_named_on_standard_error(self):
        files = PlacedFiles({"page.xml": '<p>Text</p><ac:structured-macro ac:name="toc" />'})
        result, _, _ = run("convert", "page.xml", "--source", "storage", "--out", "page.md", files=files)
        self.assertIn("The Markdown cannot show", result.err)
        self.assertTrue(result.out.startswith("Wrote "))


class NothingIsReplacedTest(unittest.TestCase):
    def refused(self, argv, code, fragment, files=None, gateway=None, expected_calls=0):
        gateway = FakeGateway() if gateway is None else gateway
        result, files, gateway = run(*argv, files=files, gateway=gateway)
        self.assertEqual(result.code, code, result.err)
        self.assertIn(fragment, result.err)
        self.assertEqual(result.out, "")
        self.assertEqual(len(gateway.calls), expected_calls, "the path is judged before Confluence is asked for anything")
        return files

    def test_a_file_that_is_there_is_not_replaced_and_nothing_is_asked(self):
        for name, ref in BODY_READERS:
            with self.subTest(command=name):
                files = self.refused((name, ref, "--body-only", "--out", "body.out"), 1, "body.out exists already", PlacedFiles({"body.out": "mine"}))
                self.assertEqual(written(files, "body.out"), b"mine")
                self.assertEqual(files.writes, [])
        files = self.refused(("convert", "notes.md", "--out", "page.xml"), 1, "page.xml exists already", PlacedFiles({"notes.md": "x", "page.xml": "mine"}))
        self.assertEqual(written(files, "page.xml"), b"mine")

    def test_with_force_it_is_replaced_and_the_answer_is_the_same_line(self):
        for name, ref in BODY_READERS:
            with self.subTest(command=name):
                result, files, _ = run(name, ref, "--body-only", "--out", "body.out", "--force", files=PlacedFiles({"body.out": "mine"}))
                self.assertEqual(result.code, 0, result.err)
                self.assertEqual(result.out, f"Wrote {len(written(files, 'body.out'))} bytes to body.out\n")
                self.assertNotEqual(written(files, "body.out"), b"mine")

    def test_a_folder_is_never_replaced(self):
        files = PlacedFiles({"sub/page.xml": "x"})
        self.refused(("page", "2002", "--body-only", "--out", "sub", "--force"), 1, "sub is a folder", files)
        self.assertEqual(files.writes, [])

    def test_the_flag_that_replaces_needs_the_file_it_replaces(self):
        for argv in (("page", "2002", "--force"), ("blogpost", "7101", "--force"), ("template", "7402", "--force"), ("convert", "notes.md", "--force")):
            with self.subTest(argv=argv):
                self.refused(argv, 2, "--force replaces the file that --out names", PlacedFiles({"notes.md": "x"}))

    def test_the_option_needs_the_body_alone_and_says_so_before_anything_is_asked(self):
        for argv in (
            ("page", "2002", "--out", "body.out"),
            ("page", "2002", "--out", "body.out", "--json"),
            ("page", "2002", "--out", "body.out", "--outline"),
            ("page", "2002", "--out", "body.out", "--no-body"),
            ("page", "2002", "2003", "--out", "body.out"),
            ("blogpost", "7101", "--out", "body.out"),
            ("blogpost", "7101", "--out", "body.out", "--comments"),
            ("template", "7402", "--out", "body.out"),
        ):
            with self.subTest(argv=argv):
                files = self.refused(argv, 2, "--body-only", PlacedFiles())
                self.assertEqual(files.writes, [])
        result, _, _ = run("page", "2002", "--out", "body.out")
        self.assertIn("Example: conflu page 123456 --format storage --body-only --out page.xml", result.err)

    def test_the_options_that_a_body_cannot_have_stay_refused_with_it(self):
        for argv in (("page", "2002", "2003", "--body-only", "--out", "body.out"), ("page", "2002", "--body-only", "--raw", "--out", "body.out")):
            with self.subTest(argv=argv):
                self.assertEqual(self.refused(argv, 2, "--body-only prints", PlacedFiles()).writes, [])

    def test_a_value_that_is_given_and_empty_is_an_error_and_no_file(self):
        for value, fragment in (("", "--out is empty"), ("  ", "--out is empty"), ("-", "not standard output"), ("a\x00b", "control character"), ("sub/", "ends with a separator"), ("sub\\", "ends with a separator")):
            with self.subTest(value=value):
                files = self.refused(("page", "2002", "--body-only", "--out", value), 2, fragment, PlacedFiles())
                self.assertEqual(files.writes, [])

    def test_the_settings_of_the_cli_are_never_replaced_not_even_with_force(self):
        for path in (SETTINGS, "/home/me/.config/conflu-c-cli/../conflu-c-cli/config", "/HOME/ME/.CONFIG/CONFLU-C-CLI/CONFIG"):
            for force in ((), ("--force",)):
                with self.subTest(path=path, force=force):
                    files = PlacedFiles({SETTINGS: "CONFLUENCE_API_TOKEN=x\n"}, ignore_case=True)
                    self.refused(("page", "2002", "--body-only", "--out", path, *force), 2, "configuration file of this CLI", files)
                    self.assertEqual(written(files, SETTINGS), b"CONFLUENCE_API_TOKEN=x\n")
        files = PlacedFiles()
        self.refused(("convert", "--out", SETTINGS, "--force"), 2, "configuration file of this CLI", files)

    def test_nothing_is_written_next_to_the_settings_either(self):
        files = self.refused(("blogpost", "7101", "--body-only", "--out", "/home/me/.config/conflu-c-cli/post.xml", "--force"), 2, "the folder where the CLI keeps its own configuration", PlacedFiles())
        self.assertEqual(files.writes, [])
        result, files, _ = run("blogpost", "7101", "--body-only", "--out", "/home/me/.config/conflu-c-cli/sub/post.xml")
        self.assertEqual(result.code, 0, result.err)  # a folder below it is no risk

    def test_a_file_that_holds_the_token_is_never_replaced_not_even_with_force(self):
        files = PlacedFiles({"notes.txt": "my token is secret-token, do not lose it"})
        self.refused(("page", "2002", "--body-only", "--out", "notes.txt", "--force"), 2, "holds the API token", files)
        self.assertEqual(written(files, "notes.txt"), b"my token is secret-token, do not lose it")
        result, _, _ = run("page", "2002", "--body-only", "--out", "notes.txt", "--force", files=files)
        self.assertNotIn("secret-token", result.err)  # the token is never shown

    def test_a_page_that_is_not_there_leaves_no_file_behind(self):
        files = PlacedFiles()
        result, files, gateway = run("page", "999", "--body-only", "--out", "body.out", files=files)
        self.assertEqual(result.code, 4)
        self.assertEqual((files.files, files.writes), ({}, []))
        result, files, _ = run("blogpost", "7999", "--body-only", "--out", "body.out", files=PlacedFiles())
        self.assertEqual((result.code, files.writes), (4, []))
        result, files, _ = run("template", "9999", "--body-only", "--out", "body.out", files=PlacedFiles())
        self.assertNotEqual(result.code, 0)
        self.assertEqual(files.writes, [])

    def test_a_file_that_appears_while_confluence_is_asked_is_not_replaced(self):
        files = PlacedFiles()
        gateway = FakeGateway()
        original = gateway.get_page

        def slow(page_id, *, with_body=True):
            files.put("body.out", b"somebody was quicker")
            return original(page_id, with_body=with_body)

        gateway.get_page = slow
        result, _, _ = run("page", "2002", "--body-only", "--out", "body.out", files=files, gateway=gateway)
        self.assertEqual(result.code, 1)
        self.assertIn("body.out exists already", result.err)
        self.assertEqual(written(files, "body.out"), b"somebody was quicker")


class PeopleTest(unittest.TestCase):
    """The file holds what the command would have printed, so people stay out of it unless they are asked for, as they do on the screen."""

    def test_without_users_the_file_has_no_mention_and_no_address(self):
        for name, ref in (("page", "2002"), ("blogpost", "7101")):
            with self.subTest(command=name):
                result, files, _ = run(name, ref, "--body-only", "--format", "storage", "--out", "body.out")
                saved = written(files, "body.out").decode("utf-8")
                self.assertNotIn(ACCOUNT, saved)
                self.assertNotIn("alex@example.com", saved)
                self.assertIn('ri:account-id="hidden"', saved)
                self.assertIn("[email]", saved)
                self.assertNotIn(ACCOUNT, result.out + result.err)

    def test_with_users_the_file_is_the_page_as_confluence_keeps_it(self):
        result, files, _ = run("page", "2002", "--body-only", "--format", "storage", "--with-users", "--out", "body.out")
        saved = written(files, "body.out").decode("utf-8")
        self.assertIn(f'ri:account-id="{ACCOUNT}"', saved)
        self.assertIn("alex@example.com", saved)
        self.assertNotIn(ACCOUNT, result.out)  # the answer about the file names nobody

    def test_with_users_is_refused_under_the_policy_and_no_file_is_made(self):
        files = PlacedFiles()
        result = run_cli("page", "2002", "--body-only", "--with-users", "--out", "body.out", files=files, settings=default_settings(hide_users=True))
        self.assertEqual(result.code, 1)
        self.assertIn("CONFLUENCE_HIDE_USERS=true", result.err)
        self.assertEqual(files.writes, [])

    def test_the_name_of_the_file_is_the_one_given_and_is_not_made_of_a_title(self):
        result, files, _ = run("page", "2002", "--body-only", "--out", "x.out")
        self.assertEqual(list(files.files), ["x.out"])
        self.assertNotIn("Release", result.out)


if __name__ == "__main__":
    unittest.main()
