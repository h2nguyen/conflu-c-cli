"""What the domain of the access area knows: which collection of the REST API answers for which kind, which names `--only` takes, how operations and assignments are counted."""
import re
import unittest

from conflu_c_cli.domain.access import (
    KNOWN_OPERATIONS,
    OPERATIONS_COLLECTIONS,
    RESTRICTION_COLLECTIONS,
    SPACE,
    STATE_MEANING,
    STATES,
    ContentPermission,
    Operation,
    RoleAssignment,
    SpacePermission,
    SpaceRole,
    can,
    count_content_permissions,
    count_roles,
    count_space_permissions,
    normalized_type,
    only_names,
    operations_for,
)
from conflu_c_cli.domain.content import KINDS
from conflu_c_cli.domain.errors import UsageError
from tests.support.conformance import documented_calls

ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"


def documented_gets() -> set[str]:
    """The GET operations of the v2 document, with the names of the placeholders left out: `/api/v2/pages/{}/operations`."""
    return {re.sub(r"\{[^}]+\}", "{}", template) for method, template, _ in documented_calls("v2") if method == "GET"}


class CollectionsTest(unittest.TestCase):
    def test_every_kind_with_operations_has_the_call_that_the_document_lists(self):
        listed = documented_gets()
        for kind, collection in OPERATIONS_COLLECTIONS.items():
            with self.subTest(kind=kind):
                self.assertIn(f"/api/v2/{collection}/{{}}/operations", listed)

    def test_the_kinds_of_the_tree_are_there_and_so_are_comments_attachments_custom_content_and_spaces(self):
        self.assertTrue({kind.name: kind.collection for kind in KINDS}.items() <= OPERATIONS_COLLECTIONS.items())
        self.assertTrue(
            {"footer-comment": "footer-comments", "inline-comment": "inline-comments", "attachment": "attachments", "custom": "custom-content", SPACE: "spaces"}.items()
            <= OPERATIONS_COLLECTIONS.items()
        )
        self.assertEqual(len(OPERATIONS_COLLECTIONS), len(KINDS) + 5)

    def test_five_kinds_have_a_restriction_state_and_direct_permissions_and_a_smart_link_is_not_one(self):
        self.assertEqual(set(RESTRICTION_COLLECTIONS), {"page", "blogpost", "folder", "whiteboard", "database"})
        listed = documented_gets()
        for kind, collection in RESTRICTION_COLLECTIONS.items():
            with self.subTest(kind=kind):
                self.assertIn(f"/api/v2/{collection}/{{}}/restriction-state", listed)
                self.assertIn(f"/api/v2/{collection}/{{}}/permissions", listed)
        for collection in ("embeds", "footer-comments", "inline-comments", "attachments", "custom-content", "spaces"):
            with self.subTest(collection=collection):
                self.assertNotIn(f"/api/v2/{collection}/{{}}/restriction-state", listed)  # the document has none: the command says so

    def test_a_space_is_asked_for_as_a_space_and_is_no_kind_of_content(self):
        self.assertEqual(OPERATIONS_COLLECTIONS[SPACE], "spaces")
        self.assertNotIn(SPACE, {kind.name for kind in KINDS})
        self.assertNotIn(SPACE, RESTRICTION_COLLECTIONS)

    def test_every_state_says_what_it_means(self):
        self.assertEqual(STATES, ("OPEN", "EDIT_RESTRICTED", "VIEW_RESTRICTED"))
        self.assertEqual(set(STATE_MEANING), set(STATES))
        for state, meaning in STATE_MEANING.items():
            with self.subTest(state=state):
                self.assertTrue(meaning.endswith("."))
        self.assertIn("parent", STATE_MEANING["OPEN"])  # a parent may restrict more: OPEN is not "everybody may read it"


class OnlyNamesTest(unittest.TestCase):
    def test_nothing_given_is_nothing_asked(self):
        self.assertEqual(only_names(None), [])
        self.assertEqual(only_names(""), [])

    def test_names_are_lower_case_trimmed_in_the_order_given_and_each_once(self):
        self.assertEqual(only_names("update,delete"), ["update", "delete"])
        self.assertEqual(only_names(" Update , DELETE ,update"), ["update", "delete"])
        self.assertEqual(only_names("restrict_content"), ["restrict_content"])

    def test_every_operation_of_the_document_is_accepted(self):
        self.assertEqual(only_names(",".join(KNOWN_OPERATIONS)), list(KNOWN_OPERATIONS))
        self.assertEqual(len(KNOWN_OPERATIONS), len(set(KNOWN_OPERATIONS)))

    def test_a_name_that_is_no_operation_is_refused_with_the_known_ones(self):
        with self.assertRaises(UsageError) as caught:
            only_names("update,updat")
        self.assertEqual(caught.exception.message, "Not an operation: updat.")
        self.assertIn("Known operations: use, create, read, update", caught.exception.hint)
        with self.assertRaises(UsageError) as caught:
            only_names("nope, also-nope")
        self.assertEqual(caught.exception.message, "Not an operation: nope, also-nope.")

    def test_only_commas_is_no_list_of_names(self):
        for text in (",", " , ,"):
            with self.subTest(text=text), self.assertRaises(UsageError) as caught:
                only_names(text)
            self.assertEqual(caught.exception.message, "--only needs the names of operations.")
            self.assertIn("--only update,delete", caught.exception.hint)

    def test_a_name_with_a_shell_or_path_meaning_is_refused_like_any_other_typo(self):
        for text in ("update;rm", "../delete", "update delete", "read&update"):
            with self.subTest(text=text), self.assertRaises(UsageError):
                only_names(text)


class OperationsTest(unittest.TestCase):
    OPERATIONS = [
        Operation("update", "page"),
        Operation("read", "page"),
        Operation("create", "comment"),
        Operation("create", "attachment"),
        Operation("restrict_content", "page"),
        Operation("read", "page"),
    ]

    def test_read_update_and_delete_are_always_answered_and_what_else_is_allowed_follows(self):
        self.assertEqual(
            can(self.OPERATIONS),
            {"read": True, "update": True, "delete": False, "create": True, "restrict_content": True},
        )
        self.assertEqual(list(can(self.OPERATIONS)), ["read", "update", "delete", "create", "restrict_content"])  # the headline ones first, the rest sorted
        self.assertEqual(can([]), {"read": False, "update": False, "delete": False})

    def test_only_the_named_operations_are_answered_in_the_order_given_and_a_missing_one_is_no(self):
        self.assertEqual(can(self.OPERATIONS, ["delete", "update", "export"]), {"delete": False, "update": True, "export": False})
        self.assertEqual(list(can(self.OPERATIONS, ["delete", "update", "export"])), ["delete", "update", "export"])

    def test_the_list_is_in_a_fixed_order_without_doubles_and_keeps_only_what_was_named(self):
        self.assertEqual(
            operations_for(self.OPERATIONS),
            [Operation("create", "attachment"), Operation("create", "comment"), Operation("read", "page"), Operation("restrict_content", "page"), Operation("update", "page")],
        )
        self.assertEqual(operations_for(self.OPERATIONS, ["create"]), [Operation("create", "attachment"), Operation("create", "comment")])
        self.assertEqual(operations_for(self.OPERATIONS, ["delete"]), [])


class CountTest(unittest.TestCase):
    def test_a_content_without_direct_permissions_has_every_count_and_it_is_zero(self):
        self.assertEqual(count_content_permissions([]), {"read": {"user": 0, "group": 0}, "update": {"user": 0, "group": 0}})

    def test_direct_permissions_are_counted_by_operation_and_kind_of_principal(self):
        permissions = [
            ContentPermission("read", "user", ACCOUNT),
            ContentPermission("read", "user", "5b10ac8d82e05b22cc7d4ef6"),
            ContentPermission("read", "group", "g1"),
            ContentPermission("update", "group", "g1"),
            ContentPermission("update", "group", "g2"),
        ]
        self.assertEqual(count_content_permissions(permissions), {"read": {"user": 2, "group": 1}, "update": {"user": 0, "group": 2}})

    def test_what_the_document_does_not_know_is_counted_under_its_own_name_and_not_lost(self):
        counts = count_content_permissions([ContentPermission("administer", "bot", "b1")])
        self.assertEqual(counts["administer"], {"user": 0, "group": 0, "bot": 1})
        self.assertEqual(counts["read"], {"user": 0, "group": 0})

    def test_space_permissions_are_counted_for_each_operation_on_each_kind_of_thing(self):
        permissions = [
            SpacePermission("1", "user", ACCOUNT, "read", "space"),
            SpacePermission("2", "group", "g1", "read", "space"),
            SpacePermission("3", "role", "r1", "read", "space"),
            SpacePermission("4", "user", ACCOUNT, "create", "page"),
            SpacePermission("5", "user", "5b10ac8d82e05b22cc7d4ef6", "create", "page"),
            SpacePermission("6", "group", "g1", "create", "comment"),
        ]
        counts = [(item.operation, item.target_type, item.user, item.group, item.role) for item in count_space_permissions(permissions)]
        self.assertEqual(counts, [("create", "comment", 0, 1, 0), ("create", "page", 2, 0, 0), ("read", "space", 1, 1, 1)])
        self.assertEqual(count_space_permissions([]), [])

    def test_role_assignments_are_counted_per_role_with_its_name_and_a_role_that_nobody_holds_is_left_out(self):
        roles = [SpaceRole("r1", "Viewer", "SYSTEM"), SpaceRole("r2", "admin", "SYSTEM"), SpaceRole("r3", "Reviewers", "CUSTOM")]
        assignments = [
            RoleAssignment("user", ACCOUNT, "r2"),
            RoleAssignment("user", "5b10ac8d82e05b22cc7d4ef6", "r1"),
            RoleAssignment("group", "g1", "r1"),
            RoleAssignment("access_class", "authenticated-users", "r1"),
        ]
        found = [(item.role_id, item.name, item.type, item.user, item.group, item.access_class) for item in count_roles(assignments, roles)]
        self.assertEqual(found, [("r2", "admin", "SYSTEM", 1, 0, 0), ("r1", "Viewer", "SYSTEM", 1, 1, 1)])  # by name, without regard to case; r3 is held by nobody

    def test_a_role_that_the_list_of_roles_lacks_is_shown_by_its_id(self):
        found = count_roles([RoleAssignment("group", "g1", "r9")], [])
        self.assertEqual([(item.role_id, item.name, item.type, item.group) for item in found], [("r9", "r9", "", 1)])


class WordsTest(unittest.TestCase):
    def test_the_document_spells_types_in_capitals_for_roles_and_in_lower_case_for_permissions(self):
        self.assertEqual([normalized_type(text) for text in ("USER", "user", " Group ", "ACCESS_CLASS", None, "")], ["user", "user", "group", "access_class", "", ""])


if __name__ == "__main__":
    unittest.main()
