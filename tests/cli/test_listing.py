"""`--select` and `--format`: the shared behaviour of every command that prints a list, and what each of those commands does with them."""
import dataclasses
import unittest

from conflu_c_cli.adapters.driving.cli.listing import FORMAT, LIST_FORMAT, SELECT, cell, known_paths, print_list, selected_json, structured_text
from conflu_c_cli.adapters.driving.cli.registry import all_commands, find_command
from conflu_c_cli.domain.errors import UsageError
from tests.support.cli import run_cli
from tests.support.fakes import FakeGateway, default_settings

ROWS = [
    {"id": "2001", "title": "Export | the report", "version": {"number": 3, "author": {"displayName": "Alex"}}, "ancestors": [{"id": "1", "title": "Home"}], "labels": ["a", "b"]},
    {"id": "2002", "title": "Fix", "version": None, "ancestors": [], "labels": []},
]
COLUMNS = [("ID", "id"), ("VERSION", "version.number"), ("TITLE", "title")]


class FakeContext:
    def __init__(self, *, json_mode=False, json_flag=False):
        self.json_mode, self.json_flag = json_mode, json_flag
        self.printed, self.json_printed = [], []

    def print(self, text=""):
        self.printed.append(text)

    def print_json(self, value):
        self.json_printed.append(value)


class Args:
    def __init__(self, select=None, format="table", list_format="table"):
        self.select, self.format, self.list_format = select, format, list_format


class SelectTest(unittest.TestCase):
    def test_nothing_selected_leaves_the_document_alone(self):
        document = {"count": 2, "pages": ROWS}
        self.assertIs(selected_json(document, None, "pages"), document)
        self.assertIs(selected_json(document, "  ", "pages"), document)

    def test_a_plain_and_a_dotted_key(self):
        picked = selected_json({"count": 2, "pages": ROWS}, "id,version.number", "pages")
        self.assertEqual(picked["count"], 2)
        self.assertEqual(picked["pages"], [{"id": "2001", "version": {"number": 3}}, {"id": "2002", "version": {"number": None}}])

    def test_a_document_that_is_the_list(self):
        self.assertEqual(selected_json(ROWS, "id"), [{"id": "2001"}, {"id": "2002"}])

    def test_a_path_through_a_list_of_objects_keeps_the_list(self):
        self.assertEqual(selected_json(ROWS, "ancestors.title", None), [{"ancestors": [{"title": "Home"}]}, {"ancestors": []}])
        both = selected_json(ROWS, "ancestors.id,ancestors.title", None)
        self.assertEqual(both[0], {"ancestors": [{"id": "1", "title": "Home"}]})

    def test_a_whole_object_can_be_selected(self):
        self.assertEqual(selected_json(ROWS, "version")[0], {"version": {"number": 3, "author": {"displayName": "Alex"}}})

    def test_an_unknown_name_is_a_usage_error_that_lists_the_valid_names(self):
        with self.assertRaises(UsageError) as caught:
            selected_json({"pages": ROWS}, "id,nope", "pages")
        self.assertEqual(caught.exception.exit_code, 2)
        self.assertIn("nope", caught.exception.message)
        self.assertIn("version.number", caught.exception.hint)
        self.assertIn("ancestors.title", caught.exception.hint)

    def test_an_empty_list_accepts_any_name(self):
        self.assertEqual(selected_json({"pages": []}, "whatever", "pages"), {"pages": []})

    def test_a_document_without_the_list_says_so(self):
        with self.assertRaises(UsageError):
            selected_json({"count": 1}, "id", "pages")

    def test_known_paths(self):
        self.assertEqual(
            known_paths(ROWS),
            ["ancestors", "ancestors.id", "ancestors.title", "id", "labels", "title", "version", "version.author", "version.author.displayName", "version.number"],
        )


class FormatTest(unittest.TestCase):
    def test_cells(self):
        self.assertEqual(cell(None), "")
        self.assertEqual(cell(True), "true")
        self.assertEqual(cell(5.0), "5")
        self.assertEqual(cell(["a", "b"]), "a, b")
        self.assertEqual(cell({"a": 1}), '{"a":1}')
        self.assertEqual(cell("two\nlines\tand tab"), "two lines and tab")

    def test_markdown_escapes_the_pipe(self):
        text = structured_text(ROWS, COLUMNS, None, "md")
        self.assertEqual(text.splitlines(), ["| ID | VERSION | TITLE |", "| --- | --- | --- |", "| 2001 | 3 | Export \\| the report |", "| 2002 |  | Fix |"])

    def test_tsv_has_a_header_line_and_tabs(self):
        lines = structured_text(ROWS, COLUMNS, None, "tsv").splitlines()
        self.assertEqual(lines[0], "ID\tVERSION\tTITLE")
        self.assertEqual(lines[1], "2001\t3\tExport | the report")

    def test_table(self):
        lines = structured_text(ROWS, COLUMNS, None, "table").splitlines()
        self.assertTrue(lines[0].startswith("ID"))
        self.assertIn("2001", lines[1])

    def test_select_names_the_columns(self):
        lines = structured_text(ROWS, COLUMNS, "id,version.author.displayName", "tsv").splitlines()
        self.assertEqual(lines, ["id\tversion.author.displayName", "2001\tAlex", "2002\t"])

    def test_select_with_an_unknown_name(self):
        with self.assertRaises(UsageError):
            structured_text(ROWS, COLUMNS, "nope", "md")


class PrintListTest(unittest.TestCase):
    def run_print(self, ctx, args, **more):
        printed_json = print_list(ctx, args, payload={"pages": ROWS}, rows=ROWS, list_key="pages", columns=COLUMNS, plain=lambda: "PLAIN", **more)
        return ctx, printed_json

    def test_the_commands_own_text_is_the_default(self):
        ctx, printed_json = self.run_print(FakeContext(), Args())
        self.assertEqual((ctx.printed, printed_json), (["PLAIN"], False))

    def test_json_mode_prints_the_document_with_the_selection_and_says_so(self):
        ctx, printed_json = self.run_print(FakeContext(json_mode=True), Args(select="id"))
        self.assertEqual(ctx.json_printed, [{"pages": [{"id": "2001"}, {"id": "2002"}]}])
        self.assertEqual((ctx.printed, printed_json), ([], True))

    def test_a_format_turns_the_text_into_that_format(self):
        ctx, printed_json = self.run_print(FakeContext(), Args(format="md"))
        self.assertTrue(ctx.printed[0].startswith("| ID"))
        self.assertFalse(printed_json)

    def test_select_alone_prints_a_table_of_those_columns(self):
        ctx, _ = self.run_print(FakeContext(), Args(select="id"))
        self.assertTrue(ctx.printed[0].startswith("id"))
        self.assertNotIn("TITLE", ctx.printed[0])

    def test_a_format_beats_the_json_default_of_the_environment(self):
        ctx, printed_json = self.run_print(FakeContext(json_mode=True, json_flag=False), Args(format="tsv"))
        self.assertTrue(ctx.printed[0].startswith("ID\t"))
        self.assertEqual((ctx.json_printed, printed_json), ([], False))

    def test_json_and_a_format_on_the_command_line_clash(self):
        with self.assertRaises(UsageError) as caught:
            self.run_print(FakeContext(json_mode=True, json_flag=True), Args(format="md"))
        self.assertIn("--format md", caught.exception.message)
        self.assertIn("--json-envelope", caught.exception.message)

    def test_a_command_with_a_format_of_its_own_names_the_destination_of_the_list_format(self):
        args = Args(format="markdown", list_format="tsv")  # `format` is the format of a comment text
        ctx, _ = self.run_print(FakeContext(), args, format_dest="list_format")
        self.assertTrue(ctx.printed[0].startswith("ID\t"))
        ctx, _ = self.run_print(FakeContext(), Args(format="markdown"), format_dest="list_format")
        self.assertEqual(ctx.printed, ["PLAIN"])
        with self.assertRaises(UsageError) as caught:
            self.run_print(FakeContext(json_mode=True, json_flag=True), args, format_dest="list_format")
        self.assertIn("--list-format tsv", caught.exception.message)

    def test_the_shared_arguments_are_described(self):
        self.assertEqual(SELECT.dest, "select")
        self.assertEqual((FORMAT.dest, FORMAT.default, FORMAT.choices), ("format", "table", ("table", "tsv", "md")))
        self.assertEqual((LIST_FORMAT.dest, LIST_FORMAT.default, LIST_FORMAT.choices), ("list_format", "table", ("table", "tsv", "md")))
        self.assertTrue(FORMAT.text_only and LIST_FORMAT.text_only and not SELECT.text_only)


LISTS = {
    "pages": (("pages", "--space", "ENG"), "pages"),
    "spaces": (("spaces", "--all"), "spaces"),
    "versions": (("versions", "2002", "--all"), "versions"),
    "search": (("search", "ports", "--space", "ENG", "--all"), "hits"),
    "comments": (("comments", "2002", "--inline"), "comments"),
    "labels": (("labels", "2002"), "labels"),
    "attachments": (("attachments", "2002", "--all"), "attachments"),
    "tree": (("tree", "2001"), "nodes"),
}


class EveryListCommandTest(unittest.TestCase):
    """The same two options on every command that prints a list, and nothing changed without them."""

    def test_every_list_command_has_the_options_and_documents_them(self):
        for name in LISTS:
            command = find_command(name)
            with self.subTest(command=name):
                self.assertTrue(any(arg is SELECT for arg in command.args))
                self.assertTrue(any(arg in (FORMAT, LIST_FORMAT) for arg in command.args))
                self.assertIn("with --select only those (dotted) keys of every", command.output)
                self.assertTrue(any("--select" in example.command for example in command.examples))

    def test_the_options_change_nothing_by_themselves(self):
        for name, (argv, _) in LISTS.items():
            with self.subTest(command=name):
                plain = run_cli(*argv)
                self.assertEqual(plain.code, 0, plain.err)
                self.assertEqual(run_cli(*argv, "--select", "", environ={}).out, plain.out)

    def test_select_keeps_only_those_keys_of_every_item_and_the_rest_of_the_document(self):
        keep = {"pages": ("id", "title"), "spaces": ("key", "name"), "versions": ("number",), "search": ("id", "spaceKey"), "comments": ("id", "kind"), "labels": ("name",), "attachments": ("id", "size"), "tree": ("id", "depth")}
        for name, (argv, key) in LISTS.items():
            with self.subTest(command=name):
                full = run_cli(*argv, "--json").json()
                picked = run_cli(*argv, "--select", ",".join(keep[name]), "--json").json()
                self.assertTrue(full[key], "the fake holds something to list")
                self.assertEqual([set(item) for item in picked[key]], [set(keep[name])] * len(full[key]))
                self.assertEqual({k: v for k, v in picked.items() if k != key}, {k: v for k, v in full.items() if k != key})
                for item, kept in zip(full[key], picked[key]):
                    self.assertEqual({k: item[k] for k in keep[name]}, kept)

    def test_every_format_prints_the_columns_of_the_list(self):
        headers = {
            "pages": ["ID", "TITLE", "STATUS", "VERSION", "UPDATED"],
            "spaces": ["KEY", "NAME", "TYPE", "STATUS", "HOMEPAGE"],
            "versions": ["NUMBER", "SAVED", "MESSAGE"],
            "search": ["ID", "TYPE", "SPACE", "TITLE", "MODIFIED", "PATH"],
            "comments": ["ID", "KIND", "UPDATED", "PARENT", "RESOLUTION", "TEXT"],
            "labels": ["NAME", "PREFIX"],
            "attachments": ["ID", "NAME", "SIZE", "TYPE", "VERSION", "CREATED"],
            "tree": ["ID", "TITLE", "TYPE", "PARENT", "DEPTH", "STATUS"],
        }
        for name, (argv, key) in LISTS.items():
            option = "--list-format" if name == "comments" else "--format"
            items = run_cli(*argv, "--json").json()[key]
            with self.subTest(command=name):
                tsv = run_cli(*argv, option, "tsv")
                self.assertEqual(tsv.code, 0, tsv.err)
                lines = tsv.out.splitlines()
                self.assertEqual(lines[0].split("\t"), headers[name])
                self.assertEqual(len(lines) - 1, len(items))
                self.assertEqual({len(line.split("\t")) for line in lines}, {len(headers[name])})
                md = run_cli(*argv, option, "md").out.splitlines()
                self.assertEqual(md[0], "| " + " | ".join(headers[name]) + " |")
                self.assertEqual(md[1], "| " + " | ".join("---" for _ in headers[name]) + " |")
                self.assertEqual(len(md) - 2, len(items))
                table = run_cli(*argv, option, "table")
                self.assertEqual(table.out, run_cli(*argv).out)  # the name of the default changes nothing

    def test_the_columns_are_the_selected_keys_with_a_format(self):
        result = run_cli("pages", "--space", "ENG", "--select", "id,version", "--format", "tsv")
        self.assertEqual(result.out.splitlines()[:2], ["id\tversion", "2001\t1"])
        result = run_cli("pages", "--space", "ENG", "--select", "id,title", "--format", "md")
        self.assertEqual(result.out.splitlines()[:3], ["| id | title |", "| --- | --- |", "| 2001 | Engineering Home |"])

    def test_select_alone_prints_a_table_of_those_columns(self):
        lines = run_cli("pages", "--space", "ENG", "--select", "id,title").out.splitlines()
        self.assertEqual(lines[0].split(), ["id", "title"])
        self.assertEqual(lines[1].split()[:1], ["2001"])

    def test_an_unknown_name_is_exit_code_2_and_lists_the_valid_keys(self):
        for name, (argv, _) in LISTS.items():
            with self.subTest(command=name):
                for extra in (("--json",), ("--format" if name != "comments" else "--list-format", "tsv")):
                    result = run_cli(*argv, "--select", "nope", *extra)
                    self.assertEqual(result.code, 2)
                    self.assertIn("Unknown name in --select: nope", result.err)
                    self.assertIn("Valid names:", result.err)
                    self.assertEqual(result.out, "")

    def test_json_and_a_format_are_a_usage_error_but_the_json_default_of_the_settings_is_not(self):
        for name, (argv, _) in LISTS.items():
            option = "--list-format" if name == "comments" else "--format"
            with self.subTest(command=name):
                clash = run_cli(*argv, "--json", option, "md")
                self.assertEqual(clash.code, 2)
                self.assertIn(f"{option} md", clash.err)
                again = run_cli(*argv, "--json-envelope", option, "md")
                self.assertEqual(again.code, 2)
                by_default = run_cli(*argv, option, "tsv", settings=default_settings(output="json"))
                self.assertEqual(by_default.code, 0, by_default.err)
                self.assertIn("\t", by_default.out.splitlines()[0])
                by_environment = run_cli(*argv, option, "md", environ={"CONFLUENCE_OUTPUT": "json"})
                self.assertEqual(by_environment.code, 0, by_environment.err)
                self.assertTrue(by_environment.out.startswith("| "))

    def test_select_works_with_the_json_default_and_with_the_envelope(self):
        by_default = run_cli("pages", "--space", "ENG", "--select", "id", settings=default_settings(output="json")).json()
        self.assertEqual(by_default["pages"][0], {"id": "2001"})
        enveloped = run_cli("pages", "--space", "ENG", "--select", "id", "--json-envelope").json()
        self.assertEqual((enveloped["ok"], enveloped["data"]["pages"][0]), (True, {"id": "2001"}))

    def test_an_empty_list_stays_empty_in_every_form(self):
        self.assertEqual(run_cli("pages", "--space", "ENG", "--title", "Nothing", "--select", "whatever", "--json").json()["pages"], [])
        self.assertEqual(run_cli("pages", "--space", "ENG", "--title", "Nothing", "--format", "tsv").out, "ID\tTITLE\tSTATUS\tVERSION\tUPDATED\n")
        self.assertEqual(run_cli("labels", "2003", "--format", "md").out.splitlines(), ["| NAME | PREFIX |", "| --- | --- |"])

    def test_the_catalog_lists_the_options(self):
        from conflu_c_cli.adapters.driving.cli.help import catalog
        from conflu_c_cli.version import __version__

        entries = {item["name"]: item for item in catalog(all_commands(), __version__)["commands"]}
        for name in LISTS:
            names = [arg["names"][0] for arg in entries[name]["arguments"]]
            with self.subTest(command=name):
                self.assertIn("--select", names)
                self.assertTrue("--format" in names or "--list-format" in names)


class NotesForAPersonTest(unittest.TestCase):
    """What the commands tell on standard error stays in every text mode, and stays out of the JSON."""

    def test_more_pages_follow(self):
        for argv in (("--format", "tsv"), ("--select", "id"), ()):
            with self.subTest(argv=argv):
                result = run_cli("pages", "--space", "ENG", "--limit", "2", *argv)
                self.assertIn("--cursor 2", result.err)
        for argv in (("--json",), ("--json", "--select", "id")):
            with self.subTest(argv=argv):
                self.assertEqual(run_cli("pages", "--space", "ENG", "--limit", "2", *argv).err, "")
        self.assertIn("--cursor 2", run_cli("pages", "--space", "ENG", "--limit", "2", "--format", "md", settings=default_settings(output="json")).err)

    def test_the_other_notes(self):
        self.assertIn("More spaces follow", run_cli("spaces", "--limit", "1", "--format", "tsv").err)
        self.assertIn("Older versions follow", run_cli("versions", "2002", "--limit", "1", "--select", "number").err)
        self.assertIn("More attachments follow", run_cli("attachments", "2002", "--limit", "1", "--format", "tsv").err)
        self.assertIn("Showing 2 of 3", run_cli("search", "ports", "--format", "tsv").err)
        self.assertNotIn("Showing", run_cli("search", "ports", "--json").err)

    def test_a_tree_that_was_cut_short_still_warns(self):
        gateway = FakeGateway()
        from conflu_c_cli.application import structure as tree_module

        original = tree_module.fetch_all
        tree_module.fetch_all = lambda read: (original(read)[0], True)
        try:
            result = run_cli("tree", "2001", "--format", "tsv", gateway=gateway)
        finally:
            tree_module.fetch_all = original
        self.assertIn("cut short", result.err)

    def test_the_notes_that_came_with_the_search_stay(self):
        result = run_cli("search", "how do I request an SSO group?", "--format", "tsv")
        self.assertIn("Left out as filler", result.err)

    def test_the_excerpts_that_are_hidden_are_still_explained(self):
        result = run_cli("search", "x", "--excerpts", "--limit", "1", "--select", "id")
        self.assertIn("--with-users", result.err)

    def test_nothing_found_stays_a_sentence_and_a_note(self):
        gateway = FakeGateway()
        gateway.search_handler = lambda cql: []
        result = run_cli("search", "nothing", gateway=gateway)
        self.assertEqual(result.out, "Nothing found.\n")
        self.assertIn("Nothing found.", result.err)
        structured = run_cli("search", "nothing", "--format", "tsv", gateway=gateway)
        self.assertEqual(structured.out, "ID\tTYPE\tSPACE\tTITLE\tMODIFIED\n")


class SearchSpecialsTest(unittest.TestCase):
    def test_raw_is_confluences_own_json_and_has_no_columns(self):
        for extra in (("--select", "id"), ("--format", "tsv")):
            result = run_cli("search", "ports", "--raw", *extra)
            self.assertEqual(result.code, 2)
            self.assertIn("--raw prints Confluence's own JSON", result.err)

    def test_the_path_column_is_there_when_a_hit_has_a_path(self):
        header = run_cli("search", "ports", "--format", "tsv").out.splitlines()[0]
        self.assertEqual(header.split("\t")[-1], "PATH")
        gateway = FakeGateway()
        gateway.search_hits = [dataclasses.replace(hit, path="") for hit in gateway.search_hits]
        self.assertEqual(run_cli("search", "ports", "--format", "tsv", gateway=gateway).out.splitlines()[0], "ID\tTYPE\tSPACE\tTITLE\tMODIFIED")

    def test_the_passages_and_the_excerpts_stay_the_default_text(self):
        passages = run_cli("search", "ports", "--snippets", "2")
        self.assertIn("    in: ", passages.out)
        as_table = run_cli("search", "ports", "--snippets", "2", "--format", "tsv")
        self.assertEqual(as_table.out.splitlines()[0].split("\t")[:2], ["ID", "TYPE"])


class CommentsHaveTwoFormatsTest(unittest.TestCase):
    def test_the_format_of_the_text_and_of_the_list_are_two_options(self):
        text = run_cli("comments", "2002", "--format", "storage", "--list-format", "tsv")
        self.assertEqual(text.code, 0, text.err)
        self.assertIn("<p>Looks good.</p>", text.out)
        self.assertEqual(text.out.splitlines()[0], "ID\tKIND\tUPDATED\tPARENT\tRESOLUTION\tTEXT")
        plain = run_cli("comments", "2002", "--format", "storage")
        self.assertIn("--- #4001 footer", plain.out)  # the default text, as before

    def test_a_list_of_comments_with_the_authors_when_they_are_asked_for(self):
        header = run_cli("comments", "2002", "--with-users", "--list-format", "tsv").out.splitlines()[0]
        self.assertEqual(header.split("\t")[-2:], ["AUTHOR", "TEXT"])
        row = run_cli("comments", "2002", "--with-users", "--list-format", "tsv").out.splitlines()[1]
        self.assertIn("Alex Example", row)
        self.assertNotIn("Alex Example", run_cli("comments", "2002", "--list-format", "tsv").out)

    def test_a_reply_has_its_parent(self):
        lines = run_cli("comments", "2002", "--select", "id,parentId", "--list-format", "tsv").out.splitlines()
        self.assertEqual(lines, ["id\tparentId", "4001\t", "4002\t4001"])

    def test_the_text_of_a_comment_is_one_line_in_a_table(self):
        gateway = FakeGateway()
        gateway.comments["2002"][0] = dataclasses.replace(gateway.comments["2002"][0], body="<p>First line</p><p>Second line</p>")
        lines = run_cli("comments", "2002", "--select", "id,body.value", "--list-format", "tsv", gateway=gateway).out.splitlines()
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[1], "4001\tFirst line Second line")


if __name__ == "__main__":
    unittest.main()
