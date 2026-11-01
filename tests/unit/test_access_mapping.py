"""What the answers of the REST API v2 about operations, restrictions, permissions and roles mean: one answer in, domain objects out."""
import unittest

from conflu_c_cli.adapters.driven import map_access as mapping
from conflu_c_cli.domain.access import ContentPermission, Operation, RestrictionState, RoleAssignment, SpacePermission, SpaceRole

ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"


class OperationsAnswerTest(unittest.TestCase):
    def test_the_operations_of_an_answer(self):
        data = {"operations": [{"operation": "read", "targetType": "page"}, {"operation": "create", "targetType": "comment"}]}
        self.assertEqual(mapping.operations_from(data), [Operation("read", "page"), Operation("create", "comment")])

    def test_what_is_not_an_operation_is_left_out_and_not_an_error(self):
        for data in (None, [], "x", {}, {"operations": None}, {"operations": "read"}, {"operations": {"operation": "read"}}):
            with self.subTest(data=data):
                self.assertEqual(mapping.operations_from(data), [])
        data = {"operations": [{"targetType": "page"}, {"operation": ""}, "read", None, {"operation": "update"}, {"operation": 7, "targetType": None}]}
        self.assertEqual(mapping.operations_from(data), [Operation("update", ""), Operation("7", "")])


class RestrictionAnswerTest(unittest.TestCase):
    def test_a_restriction_state(self):
        found = mapping.restriction_state_from({"state": "VIEW_RESTRICTED", "createdAt": "2026-10-03T09:00:00.000Z", "createdBy": ACCOUNT})
        self.assertEqual(found, RestrictionState("VIEW_RESTRICTED", "2026-10-03T09:00:00.000Z", ACCOUNT))

    def test_the_deprecated_name_of_who_set_it_is_read_when_the_new_one_is_missing(self):
        self.assertEqual(mapping.restriction_state_from({"state": "EDIT_RESTRICTED", "createdByAaid": ACCOUNT}).created_by, ACCOUNT)
        both = mapping.restriction_state_from({"state": "EDIT_RESTRICTED", "createdBy": "new", "createdByAaid": "old"})
        self.assertEqual(both.created_by, "new")

    def test_an_open_content_names_nobody_and_no_time(self):
        self.assertEqual(mapping.restriction_state_from({"state": "OPEN"}), RestrictionState("OPEN", "", ""))
        self.assertEqual(mapping.restriction_state_from(None), RestrictionState("", "", ""))
        self.assertEqual(mapping.restriction_state_from({"state": None, "createdBy": None}), RestrictionState("", "", ""))

    def test_a_direct_permission_has_its_words_in_lower_case(self):
        item = {"operation": "UPDATE", "principal": {"principalType": "GROUP", "principalId": "g1"}, "createdAt": "2026-10-03T09:00:00.000Z", "createdBy": ACCOUNT}
        self.assertEqual(mapping.content_permission_from(item), ContentPermission("update", "group", "g1", "2026-10-03T09:00:00.000Z", ACCOUNT))
        deprecated = {"operation": "read", "principal": {"principalType": "user", "principalId": ACCOUNT}, "createdByAaid": "somebody"}
        self.assertEqual(mapping.content_permission_from(deprecated), ContentPermission("read", "user", ACCOUNT, "", "somebody"))

    def test_a_direct_permission_without_an_operation_or_a_principal_is_left_out(self):
        for item in ({}, {"operation": "read"}, {"operation": "read", "principal": {"principalType": "user"}}, {"principal": {"principalId": "g1"}}, {"operation": "", "principal": {"principalId": "g1"}}):
            with self.subTest(item=item):
                self.assertIsNone(mapping.content_permission_from(item))
        self.assertIsNone(mapping.content_permission_from({"operation": "read", "principal": "g1"}))


class SpaceAnswerTest(unittest.TestCase):
    def test_a_permission_assignment_of_a_space(self):
        item = {"id": "sp-1", "principal": {"type": "group", "id": "g1"}, "operation": {"key": "create", "targetType": "page"}}
        self.assertEqual(mapping.space_permission_from(item), SpacePermission("sp-1", "group", "g1", "create", "page"))
        self.assertEqual(mapping.space_permission_from({"principal": {"type": "USER", "id": ACCOUNT}, "operation": {"key": "read"}}), SpacePermission("", "user", ACCOUNT, "read", ""))

    def test_an_assignment_without_a_principal_or_an_operation_is_left_out(self):
        for item in ({}, {"id": "x"}, {"principal": {"id": "g1"}}, {"operation": {"key": "read"}}, {"principal": {"type": "user"}, "operation": {"key": "read"}}):
            with self.subTest(item=item):
                self.assertIsNone(mapping.space_permission_from(item))

    def test_a_role_assignment_has_its_type_in_lower_case(self):
        item = {"principal": {"principalType": "ACCESS_CLASS", "principalId": "authenticated-users"}, "roleId": "r1"}
        self.assertEqual(mapping.role_assignment_from(item), RoleAssignment("access_class", "authenticated-users", "r1"))
        self.assertEqual(mapping.role_assignment_from({"principal": {"principalType": "USER", "principalId": ACCOUNT}, "roleId": 5}), RoleAssignment("user", ACCOUNT, "5"))

    def test_a_role_assignment_without_a_principal_or_a_role_is_left_out(self):
        for item in ({}, {"roleId": "r1"}, {"principal": {"principalId": ACCOUNT}}, {"principal": {"principalType": "USER"}, "roleId": "r1"}, {"principal": None, "roleId": "r1"}):
            with self.subTest(item=item):
                self.assertIsNone(mapping.role_assignment_from(item))

    def test_a_role_and_the_role_mode(self):
        self.assertEqual(mapping.role_from({"id": "r1", "type": "CUSTOM", "name": "Reviewers", "description": "x", "spacePermissions": ["read:space"]}), SpaceRole("r1", "Reviewers", "CUSTOM"))
        self.assertEqual(mapping.role_from({"id": "r2", "name": None}), SpaceRole("r2", "", ""))
        self.assertIsNone(mapping.role_from({"name": "No id"}))
        self.assertEqual(mapping.role_mode_from({"mode": "PRE_ROLES"}), "PRE_ROLES")
        self.assertEqual((mapping.role_mode_from({}), mapping.role_mode_from(None), mapping.role_mode_from({"mode": None})), ("", "", ""))


if __name__ == "__main__":
    unittest.main()
