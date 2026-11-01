"""An export writes only into its own folder, whatever Confluence puts into an id, a title or a name."""
import unittest
from dataclasses import replace

from conflu_c_cli.domain.naming import export_file_name, safe_file_name
from tests.support.fakes import FakeGateway, MemoryFiles, build_app, default_settings


class ExportFileNameTest(unittest.TestCase):
    def test_a_normal_name_is_what_it_always_was(self):
        self.assertEqual(export_file_name("Release notes", "2002"), "release-notes-2002.md")
        self.assertEqual(export_file_name("Release notes", "2002", ".xml"), "release-notes-2002.xml")
        self.assertEqual(export_file_name("", "att5001"), "page-att5001.md")

    def test_an_id_cannot_name_a_folder(self):
        for hostile in ("7/../../AGENTS", "7\\..\\..\\x", "..", "../..", "a/b", "C:\\x", "7\x00", "7 8", "%2e%2e%2f", "\u202ex"):
            with self.subTest(id=hostile):
                name = export_file_name("Title", hostile)
                self.assertNotRegex(name, r"[\\/:\x00-\x1f\u202e]")
                self.assertEqual(name.count("."), 1)  # only the extension has a dot
                self.assertEqual(safe_file_name(name), name)

    def test_an_empty_id_leaves_a_name(self):
        self.assertEqual(export_file_name("Title", ""), "title-_.md")

    def test_a_name_that_starts_with_a_dot_cannot_plant_a_hidden_file(self):
        for name, expected in ((".mcp.json", "_.mcp.json"), (".env", "_.env"), ("..hidden", "_..hidden"), (".vscode", "_.vscode"), ("a.b", "a.b"), ("x/.env", "_.env")):
            with self.subTest(name=name):
                self.assertEqual(safe_file_name(name), expected)


class ExportStaysInsideItsFolderTest(unittest.TestCase):
    def test_a_page_with_a_hostile_id_is_written_into_the_export_folder(self):
        from conflu_c_cli.domain.model import Chunk

        gateway = FakeGateway()
        hostile = replace(gateway.pages["2005"], id="7/../../AGENTS", title="Plain page")

        class Hostile(type(gateway)):  # a Confluence whose answer holds an id that is no number
            def list_pages(self, *args, **kwargs):
                return Chunk([hostile], "")

        gateway.__class__ = Hostile
        files = MemoryFiles()
        app = build_app(gateway=gateway, files=files, settings=default_settings())
        app.export_pages.execute(out_dir="project/docs/confluence", space="ENG")
        written = [path for path in files.writes if path.endswith((".md", ".xml", ".json"))]
        self.assertEqual(len(written), 2)  # the page and the index
        for path in written:
            self.assertTrue(path.startswith("project/docs/confluence/"), path)
            self.assertNotIn("..", path)
            self.assertEqual(path.count("/"), 3, path)  # project/docs/confluence/NAME


if __name__ == "__main__":
    unittest.main()
