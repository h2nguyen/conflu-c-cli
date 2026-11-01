"""What the answers of the REST API v2 for folders, whiteboards, databases and smart links mean: one answer in, domain objects out."""
import unittest

from conflu_c_cli.adapters.driven import map_structure as mapping
from conflu_c_cli.domain.model import PageRef, TreeNode, User, VersionInfo
from conflu_c_cli.domain.structure import DatabaseField, DatabaseView, FieldValue

ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"


class ContainerAnswerTest(unittest.TestCase):
    def test_a_folder(self):
        container = mapping.container_from(
            {
                "id": "7001",
                "type": "folder",
                "status": "current",
                "title": "Guides",
                "parentId": "2001",
                "parentType": "page",
                "position": 3,
                "authorId": ACCOUNT,
                "ownerId": ACCOUNT,
                "createdAt": "2026-10-01T08:00:00.000Z",
                "spaceId": "1001",
                "version": {"number": 2, "createdAt": "2026-10-02T08:00:00.000Z", "message": "m", "minorEdit": True, "authorId": ACCOUNT},
                "_links": {"webui": "/spaces/ENG/folder/7001", "base": "https://example.atlassian.net/wiki"},
            },
            "folder",
        )
        self.assertEqual((container.id, container.type, container.title, container.status), ("7001", "folder", "Guides", "current"))
        self.assertEqual((container.space_id, container.space_key, container.parent_id, container.parent_type, container.position), ("1001", "ENG", "2001", "page", 3))
        self.assertEqual(container.url, "https://example.atlassian.net/wiki/spaces/ENG/folder/7001")
        self.assertEqual((container.author, container.owner), (User(ACCOUNT), User(ACCOUNT)))
        self.assertEqual(container.version, VersionInfo(2, "2026-10-02T08:00:00.000Z", "m", True, User(ACCOUNT)))
        self.assertEqual((container.created, container.updated, container.version_number, container.embed_url), ("2026-10-01T08:00:00.000Z", "2026-10-02T08:00:00.000Z", 2, ""))
        self.assertEqual(container.raw["id"], "7001")

    def test_what_is_left_out_is_empty_and_not_an_error(self):
        container = mapping.container_from({"id": 7001, "title": None}, "database", "https://example.atlassian.net/wiki")
        self.assertEqual((container.id, container.type, container.title, container.url, container.parent_type, container.position), ("7001", "database", "", "", "", None))
        self.assertEqual((container.author, container.owner, container.version), (None, None, None))
        top = mapping.container_from({"id": "7001", "parentId": None, "parentType": "page", "_links": {"webui": "/spaces/ENG/folder/7001"}}, "folder", "https://example.atlassian.net/wiki/")
        self.assertEqual((top.parent_id, top.parent_type), ("", ""))  # no parent: no type of one
        self.assertEqual(top.url, "https://example.atlassian.net/wiki/spaces/ENG/folder/7001")
        self.assertEqual(mapping.container_from({"id": "1", "position": "x"}, "folder").position, None)

    def test_a_smart_link_has_the_address_it_shows(self):
        self.assertEqual(mapping.container_from({"id": "7061", "embedUrl": "https://example.com/x"}, "embed").embed_url, "https://example.com/x")
        self.assertEqual(mapping.container_from({"id": "7061"}, "embed").embed_url, "")


class ListAnswerTest(unittest.TestCase):
    def test_a_child_names_no_parent_so_the_call_gives_it(self):
        node = mapping.child_from({"id": "7011", "status": "current", "title": "Runbooks", "type": "folder", "spaceId": "1001", "childPosition": 2}, "7001")
        self.assertEqual(node, TreeNode("7011", "Runbooks", "folder", "7001", 1, "current", 2))
        self.assertEqual(mapping.child_from({"id": "5"}, "7001"), TreeNode("5", "", "page", "7001", 1, "", None))

    def test_an_ancestor_has_an_id_and_a_type(self):
        self.assertEqual(mapping.ancestor_from({"id": "7001", "type": "folder"}), PageRef("7001", "", "folder"))
        self.assertEqual(mapping.ancestor_from({"id": "2001"}), PageRef("2001", "", "page"))

    def test_fields_and_views(self):
        select = mapping.field_from(
            {"id": "f2", "name": "Tier", "description": None, "type": "select", "settings": {"options": [{"id": "o1", "label": "Gold"}, {"id": "o2", "label": "Silver"}]}}
        )
        self.assertEqual(select, DatabaseField("f2", "Tier", "select", "", ("Gold", "Silver")))
        self.assertEqual(mapping.field_from({"id": "f1", "name": "Name", "description": "Who", "type": "text", "settings": {}}), DatabaseField("f1", "Name", "text", "Who"))
        self.assertEqual(mapping.field_from({"id": "f3", "name": "N", "type": "number", "settings": {"format": {"x": 1}}}).options, ())
        self.assertEqual(mapping.view_from({"id": "v1", "name": "All", "type": "table"}), DatabaseView("v1", "All", "table"))


class CellAnswerTest(unittest.TestCase):
    def test_every_documented_kind_of_cell(self):
        for raw, expected in (
            ({"type": "text", "plain": "Billing", "rich": {"version": 1, "type": "doc", "content": []}}, FieldValue("text", "Billing")),
            ({"type": "text", "plain": None, "rich": None}, FieldValue("text")),
            ({"type": "aiSummary", "plain": "A summary", "rich": None, "metadata": {}}, FieldValue("aiSummary", "A summary")),
            ({"type": "number", "value": "12.50"}, FieldValue("number", "12.50")),
            ({"type": "number", "value": None}, FieldValue("number")),
            ({"type": "checkbox", "value": True}, FieldValue("checkbox", True)),
            ({"type": "checkbox", "value": False}, FieldValue("checkbox", False)),
            ({"type": "checkbox", "value": None}, FieldValue("checkbox")),
            ({"type": "date", "value": "2026-10-15"}, FieldValue("date", "2026-10-15")),
            ({"type": "select", "value": [{"id": "o1", "label": "Gold"}, {"id": "o2", "label": "Silver"}]}, FieldValue("select", ["Gold", "Silver"])),
            ({"type": "hyperlink", "value": [{"url": "https://example.com", "label": "Site"}, {"url": "https://example.org"}]}, FieldValue("hyperlink", [{"url": "https://example.com", "label": "Site"}, {"url": "https://example.org", "label": ""}])),
            ({"type": "user", "value": [{"accountId": ACCOUNT}]}, FieldValue("user", [ACCOUNT])),
            ({"type": "user", "value": []}, FieldValue("user", [])),
            ({"type": "attachment", "value": [{"mediaId": "m1"}]}, FieldValue("attachment", ["m1"])),
            ({"type": "jiraIssue", "value": [{"key": "ENG-1", "cloudId": "c"}]}, FieldValue("jiraIssue", ["ENG-1"])),
            ({"type": "pageLink", "value": [{"contentId": "2002"}]}, FieldValue("pageLink", ["2002"])),
            ({"type": "entryLink", "value": [{"entryId": "7052", "databaseContentId": "7041"}]}, FieldValue("entryLink", ["7052"])),
            ({"type": "backlink", "value": None}, FieldValue("backlink")),
            ({"type": "pageStatus", "value": None}, FieldValue("pageStatus")),
        ):
            with self.subTest(cell=raw):
                self.assertEqual(mapping.value_from(raw), expected)

    def test_a_cell_that_nobody_knows_is_kept_by_its_type_without_a_value(self):
        self.assertEqual(mapping.value_from({"type": "hologram", "value": [{"x": 1}]}), FieldValue("hologram"))
        self.assertEqual(mapping.value_from({"type": "hologram", "value": "text"}), FieldValue("hologram", "text"))
        self.assertEqual(mapping.value_from(None), FieldValue(""))
        self.assertEqual(mapping.value_from("nonsense"), FieldValue(""))
        self.assertEqual(mapping.value_from({"type": "checkbox", "value": "yes"}), FieldValue("checkbox"))

    def test_an_entry_has_its_cells_by_the_id_of_the_field(self):
        entry = mapping.entry_from({"id": "7051", "databaseId": "7041", "values": {"name": {"type": "text", "plain": "Billing"}, "tier": {"type": "select", "value": None}}})
        self.assertEqual((entry.id, entry.database_id), ("7051", "7041"))
        self.assertEqual(entry.values, {"name": FieldValue("text", "Billing"), "tier": FieldValue("select")})
        self.assertEqual(mapping.entry_from({"id": "1"}).values, {})
        self.assertEqual(mapping.entry_from({"id": "1", "values": "nope"}).values, {})


if __name__ == "__main__":
    unittest.main()
