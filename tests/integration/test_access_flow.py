"""The commands of the access area against the mock Confluence, through the real adapters: the requests that are sent, what is read in pieces, what is refused before a request is made."""
import json
import unittest

from tests.integration.test_end_to_end import EndToEnd
from tests.support import data_access as data
from tests.support.mock_access import AccessRoutes

PEOPLE = (data.ACCOUNT, data.SECOND, data.GROUP, data.GROUP_TWO, "authenticated-users", "alex@example.com", "Alex Example")
COLLECTIONS = {  # the content of the mock, with the collection of the REST API v2 that answers for its kind
    "2002": ("page", "pages"),
    "7501": ("folder", "folders"),
    "7511": ("blogpost", "blogposts"),
    "7521": ("whiteboard", "whiteboards"),
    "7531": ("database", "databases"),
    "7541": ("embed", "embeds"),
    "7551": ("custom", "custom-content"),
    "4001": ("footer-comment", "footer-comments"),
    "4003": ("inline-comment", "inline-comments"),
    "att5001": ("attachment", "attachments"),
}
LOOKUP = ("POST", "/api/v2/content/convert-ids-to-types")


class AccessFlow(EndToEnd):
    def setUp(self):
        super().setUp()
        self.area = self.mock.area(AccessRoutes)

    def calls(self):
        return [(item.method, item.path) for item in self.mock.requests]

    def reads(self, suffix):
        """The requests for one path of the API, in the order they were made."""
        return [item for item in self.mock.requests if item.path.endswith(suffix)]


class WhatIsSentTest(AccessFlow):
    def test_what_may_be_done_is_asked_in_the_collection_of_the_kind_after_one_lookup_of_the_type(self):
        for ref, (kind, collection) in COLLECTIONS.items():
            with self.subTest(ref=ref):
                self.mock.requests.clear()
                result = self.cli("permissions", ref, "--json")
                self.assertEqual(result.code, 0, result.err)
                expected = [("GET", f"/api/v2/{collection}/{ref}/operations")]
                if not ref.startswith("att"):  # the id of an attachment says what it is
                    expected.insert(0, LOOKUP)
                    self.assertEqual(self.mock.requests[0].body, {"contentIds": [ref]})
                self.assertEqual(self.calls(), expected)
                self.assertEqual(result.json()["target"], {"id": ref, "type": kind, "key": None, "title": None})
                self.assertTrue(result.json()["can"]["read"])
                self.assertEqual(self.mock.requests[-1].query, {})

    def test_a_space_is_asked_by_its_id_after_its_key_was_looked_up(self):
        result = self.cli("permissions", "--space", "ENG", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.calls(), [("GET", "/api/v2/spaces"), ("GET", "/api/v2/spaces/1001/operations")])
        self.assertEqual(self.mock.requests[0].query["keys"], ["ENG"])
        self.assertEqual(result.json()["target"], {"id": "1001", "type": "space", "key": "ENG", "title": "Engineering"})

    def test_a_restricted_page_is_read_by_its_state_and_all_its_direct_permissions_following_the_cursor(self):
        result = self.cli("restrictions", "2002", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(
            self.calls(),
            [LOOKUP, ("GET", "/api/v2/pages/2002/restriction-state")] + [("GET", "/api/v2/pages/2002/permissions")] * 3,
        )
        self.assertEqual([item.query for item in self.reads("/permissions")], [{"limit": ["250"]}, {"limit": ["250"], "cursor": ["2"]}, {"limit": ["250"], "cursor": ["4"]}])
        self.assertEqual(self.reads("/restriction-state")[0].query, {})
        self.assertEqual(result.json()["total"], 5)

    def test_every_kind_that_has_a_restriction_state_is_read_in_its_collection(self):
        for ref, collection in (("2002", "pages"), ("7501", "folders"), ("7511", "blogposts"), ("7521", "whiteboards"), ("7531", "databases")):
            with self.subTest(collection=collection):
                self.mock.requests.clear()
                self.assertEqual(self.cli("restrictions", ref).code, 0)
                paths = {path for _, path in self.calls()}
                self.assertEqual(paths, {LOOKUP[1], f"/api/v2/{collection}/{ref}/restriction-state", f"/api/v2/{collection}/{ref}/permissions"})

    def test_both_models_of_a_site_in_the_transition_are_read_and_the_roles_are_those_of_the_space(self):
        result = self.cli("space-access", "ENG", "--json")
        self.assertEqual(result.code, 0, result.err)
        order = list(dict.fromkeys(path for _, path in self.calls()))
        self.assertEqual(order, ["/api/v2/spaces", "/api/v2/space-role-mode", "/api/v2/spaces/1001/permissions", "/api/v2/spaces/1001/role-assignments", "/api/v2/space-roles"])
        self.assertEqual(self.reads("/space-roles")[0].query, {"space-id": ["1001"], "limit": ["250"]})
        self.assertEqual(self.reads("/permissions")[1].query, {"limit": ["250"], "cursor": ["2"]})

    def test_only_reads_and_the_one_lookup_of_the_type_are_sent_and_all_of_them_are_documented(self):
        for argv in (
            ("permissions", "2002"),
            ("permissions", "--space", "ENG"),
            ("restrictions", "2002", "--with-users", "--all"),
            ("restrictions", "7501"),
            ("space-access", "ENG", "--with-users", "--all"),
            ("space-access", "DOCS"),
        ):
            self.assertEqual(self.cli(*argv).code, 0, argv)
        self.assertEqual({(method, path) for method, path in self.calls() if method != "GET"}, {LOOKUP})
        self.assertEqual((self.mock.unknown_endpoints, self.mock.deprecated_endpoints, self.mock.outside_calls), ([], [], []))
        self.assertTrue(all(call.startswith(("GET /api/v2/", "POST /api/v2/content/convert-ids-to-types")) for call in self.mock.used_endpoints))
        self.assertTrue(all(item.headers.get("authorization", "").startswith("Basic ") for item in self.mock.requests))


class RefusedBeforeARequestTest(AccessFlow):
    def test_a_command_line_that_is_wrong_sends_nothing(self):
        for argv in (
            ("permissions", "../2002"),
            ("permissions", "2002/../1001"),
            ("permissions", "2002?x=1"),
            ("permissions", "2002%2f.."),
            ("permissions", "2002 ", "--only", "update;rm"),
            ("permissions", "2002", "--only", "../delete"),
            ("permissions", "--space", "../x"),
            ("permissions", "--space", "ENG/../DOCS"),
            ("permissions", "ENG"),
            ("permissions", "2002", "--space", "ENG"),
            ("permissions",),
            ("restrictions", "abc"),
            ("restrictions", "ENG"),
            ("restrictions", "2002", "--with-users", "--cursor", "../x"),
            ("restrictions", "2002", "--with-users", "--limit", "251"),
            ("restrictions", "2002", "--limit", "5"),
            ("restrictions", "2002", "--format", "tsv"),
            ("space-access", "../x"),
            ("space-access", "ENG", "--with-users", "--cursor", "1; DROP"),
            ("space-access", "ENG", "--cursor", "1"),
            ("space-access",),
        ):
            with self.subTest(argv=argv):
                result = self.cli(*argv)
                self.assertIn(result.code, (1, 2), result.err)
                self.assertEqual(self.mock.requests, [])

    def test_people_refused_by_the_policy_send_nothing_and_the_counts_still_come(self):
        strict = {"CONFLUENCE_HIDE_USERS": "true"}
        for argv in (("restrictions", "2002", "--with-users"), ("space-access", "ENG", "--with-users", "--all")):
            with self.subTest(argv=argv):
                result = self.cli(*argv, env=strict)
                self.assertEqual((result.code, result.out), (1, ""))
                self.assertIn("CONFLUENCE_HIDE_USERS=true", result.err)
                self.assertEqual(self.mock.requests, [])
        counts = self.cli("restrictions", "2002", "--json", env=strict)
        self.assertEqual((counts.code, counts.json()["total"]), (0, 5))
        self.assertEqual(self.cli("space-access", "ENG", "--json", env=strict).json()["total"], 12)

    def test_an_address_of_another_site_is_the_source_of_an_id_and_nothing_else(self):
        result = self.cli("permissions", "https://elsewhere.example.com/wiki/spaces/ENG/pages/2002/Release+notes", "--json")
        self.assertEqual(result.code, 0, result.err)  # a request to that site could not have been answered
        self.assertEqual(self.calls(), [LOOKUP, ("GET", "/api/v2/pages/2002/operations")])
        self.assertEqual(self.mock.requests[0].body, {"contentIds": ["2002"]})

    def test_an_id_that_nobody_has_is_not_found_and_so_is_an_unknown_space(self):
        self.assertEqual(self.cli("permissions", "99999").code, 4)
        self.assertEqual(self.cli("restrictions", "99999").code, 4)
        self.assertEqual(self.cli("permissions", "--space", "NOSUCH").code, 4)
        self.assertEqual(self.cli("space-access", "NOSUCH").code, 4)
        self.assertEqual(self.cli("permissions", "att9999").code, 4)  # an attachment that is not there: the call says so
        self.assertEqual(self.mock.unknown_endpoints, [])


class WhatConfluenceAnswersTest(AccessFlow):
    def test_a_refusal_has_its_exit_code_and_nothing_is_made_up(self):
        for status, code in ((404, 4), (403, 5), (401, 5), (400, 6)):
            with self.subTest(status=status):
                self.mock.fail_next("/api/v2/pages/2002/restriction-state", status)
                result = self.cli("restrictions", "2002")
                self.assertEqual((result.code, result.out), (code, ""))
                self.assertIn("ERROR", result.err)

    def test_a_refusal_that_names_a_person_is_not_printed_under_the_policy(self):
        body = {"errors": [{"status": 403, "code": "FORBIDDEN", "title": "Forbidden", "detail": "alex@example.com may not see this page"}]}
        self.mock.fail_next("/api/v2/pages/2002/restriction-state", 403, body=body)
        strict = self.cli("restrictions", "2002", env={"CONFLUENCE_HIDE_USERS": "true"})
        self.assertEqual(strict.code, 5)
        self.assertNotIn("alex@example.com", strict.err)
        self.assertIn("[email]", strict.err)

    def test_a_refusal_while_the_list_is_read_is_the_error_and_not_a_short_count(self):
        self.mock.fail_next("/api/v2/pages/2002/permissions", 403, times=1)
        result = self.cli("restrictions", "2002")
        self.assertEqual((result.code, result.out), (5, ""))

    def test_the_role_names_that_cannot_be_read_do_not_stop_the_answer(self):
        self.mock.fail_next("/api/v2/space-roles", 404)
        data_json = self.cli("space-access", "ENG", "--json").json()
        self.assertEqual(sorted(item["name"] for item in data_json["roleCounts"]), sorted([data.ROLE_ADMIN, data.ROLE_CONTRIBUTOR, data.ROLE_VIEWER]))
        self.assertTrue(any(note.startswith("The names of the roles could not be read, so a role is shown by its id") for note in data_json["notes"]))

    def test_the_role_assignments_that_cannot_be_read_on_a_site_in_the_transition_leave_the_permissions(self):
        self.mock.fail_next("/api/v2/spaces/1001/role-assignments", 400)
        data_json = self.cli("space-access", "ENG", "--json").json()
        self.assertEqual((data_json["models"], data_json["roleCounts"], data_json["permissionTotal"]), (["permissions"], None, 7))
        self.assertEqual(len(data_json["notes"]), 2)

    def test_the_permissions_that_cannot_be_read_are_the_error(self):
        self.mock.fail_next("/api/v2/spaces/1001/permissions", 403)
        self.assertEqual(self.cli("space-access", "ENG").code, 5)

    def test_a_mode_that_the_token_may_not_read_is_the_error_and_not_a_guess(self):
        self.mock.fail_next("/api/v2/space-role-mode", 403)
        result = self.cli("space-access", "ENG")
        self.assertEqual((result.code, result.out), (5, ""))
        self.assertEqual(self.reads("/permissions") + self.reads("/role-assignments"), [])


class RoleModesTest(AccessFlow):
    def paths(self):
        return {path for _, path in self.calls()}

    def test_the_permission_model_alone(self):
        self.area.role_mode = "PRE_ROLES"
        data_json = self.cli("space-access", "ENG", "--json").json()
        self.assertEqual((data_json["mode"], data_json["models"], data_json["roleCounts"], data_json["roleTotal"], data_json["total"]), ("PRE_ROLES", ["permissions"], None, None, 7))
        self.assertEqual(data_json["notes"], [])
        self.assertEqual(self.paths() & {"/api/v2/spaces/1001/role-assignments", "/api/v2/space-roles"}, set())

    def test_the_role_model_alone(self):
        self.area.role_mode = "ROLES"
        data_json = self.cli("space-access", "ENG", "--json").json()
        self.assertEqual((data_json["mode"], data_json["models"], data_json["permissionCounts"], data_json["permissionTotal"], data_json["total"]), ("ROLES", ["roles"], None, None, 5))
        self.assertNotIn("/api/v2/spaces/1001/permissions", self.paths())

    def test_a_site_without_space_roles_has_the_permissions_and_two_notes(self):
        self.area.role_mode = None
        result = self.cli("space-access", "ENG", "--json")
        self.assertEqual(result.code, 0, result.err)
        data_json = result.json()
        self.assertEqual((data_json["mode"], data_json["models"], data_json["roleCounts"], data_json["permissionTotal"]), (None, ["permissions"], None, 7))
        self.assertEqual(len(data_json["notes"]), 2)
        self.assertEqual(self.mock.unknown_endpoints, [])
        self.assertNotIn("/api/v2/space-roles", self.paths())  # no assignments came, so nothing needed a name
        text = self.cli("space-access", "ENG")
        self.assertEqual(text.out.splitlines()[1], "Role mode: not reported by this site")

    def test_a_mode_that_is_refused_is_a_mode_that_is_not_reported_and_the_roles_are_still_read(self):
        self.mock.fail_next("/api/v2/space-role-mode", 400)
        data_json = self.cli("space-access", "ENG", "--json").json()
        self.assertEqual((data_json["mode"], data_json["models"], len(data_json["roleCounts"])), (None, ["permissions", "roles"], 3))

    def test_a_mode_that_the_cli_does_not_know_reads_both_models(self):
        self.area.role_mode = "SOMETHING_NEW"
        data_json = self.cli("space-access", "ENG", "--json").json()
        self.assertEqual((data_json["mode"], data_json["models"]), ("SOMETHING_NEW", ["permissions", "roles"]))
        self.assertIn("SOMETHING_NEW is not one this CLI knows", data_json["notes"][0])


class VolumeTest(AccessFlow):
    def test_a_long_list_of_direct_permissions_is_counted_whole_and_shown_in_pieces(self):
        self.mock.page_cap = 250
        grants = tuple(("read", "user", f"user-{number:04d}") for number in range(300)) + tuple(("update", "group", f"group-{number:04d}") for number in range(300))
        self.area.restrict("7511", "VIEW_RESTRICTED", grants)
        counted = self.cli("restrictions", "7511", "--json").json()
        self.assertEqual((counted["total"], counted["counts"]), (600, {"read": {"user": 300, "group": 0}, "update": {"user": 0, "group": 300}}))
        self.assertEqual([item.query for item in self.reads("/permissions")], [{"limit": ["250"]}, {"limit": ["250"], "cursor": ["250"]}, {"limit": ["250"], "cursor": ["500"]}])
        piece = self.cli("restrictions", "7511", "--with-users", "--limit", "25", "--json").json()
        self.assertEqual((piece["count"], piece["nextCursor"], piece["total"], piece["permissions"][0]["principalId"]), (25, "25", 600, "user-0000"))
        last = self.cli("restrictions", "7511", "--with-users", "--limit", "25", "--cursor", "575", "--json").json()
        self.assertEqual((last["count"], last["nextCursor"], last["permissions"][-1]["principalId"]), (25, None, "group-0299"))
        everything = self.cli("restrictions", "7511", "--with-users", "--all", "--json").json()
        self.assertEqual((everything["count"], everything["nextCursor"]), (600, None))

    def test_a_big_space_is_counted_whole(self):
        self.mock.page_cap = 250
        self.area.space_permissions["1001"] += [
            {"id": f"extra-{number}", "principal": {"type": "user", "id": f"user-{number:04d}"}, "operation": {"key": "read", "targetType": "space"}} for number in range(600)
        ]
        data_json = self.cli("space-access", "ENG", "--json").json()
        self.assertEqual(data_json["permissionTotal"], 607)
        read = next(item for item in data_json["permissionCounts"] if (item["operation"], item["targetType"]) == ("read", "space"))
        self.assertEqual((read["user"], read["group"]), (602, 1))
        self.assertEqual(len(self.reads("/spaces/1001/permissions")), 3)

    def test_a_list_that_goes_on_for_ever_is_cut_and_says_so(self):
        self.mock.page_cap = 250
        self.area.restrict("7511", "VIEW_RESTRICTED", tuple(("read", "user", f"user-{number}") for number in range(20100)))
        data_json = self.cli("restrictions", "7511", "--json").json()
        self.assertEqual((data_json["truncated"], data_json["total"]), (True, 20000))
        self.assertTrue(any("Only the first 20000 direct permissions were read" in note for note in data_json["notes"]))


class PeopleTest(AccessFlow):
    def test_nobody_is_named_without_with_users_and_somebody_is_with_it(self):
        for argv in (
            ("permissions", "2002"),
            ("restrictions", "2002"),
            ("restrictions", "2002", "--json"),
            ("restrictions", "7501"),
            ("space-access", "ENG"),
            ("space-access", "ENG", "--json"),
        ):
            with self.subTest(argv=argv):
                result = self.cli(*argv)
                self.assertEqual(result.code, 0, result.err)
                for person in PEOPLE:
                    self.assertNotIn(person, result.out + result.err)
        with_users = self.cli("restrictions", "2002", "--with-users", "--all").out + self.cli("space-access", "ENG", "--with-users", "--all").out
        for person in (data.ACCOUNT, data.SECOND, data.GROUP, data.GROUP_TWO, "authenticated-users"):
            self.assertIn(person, with_users)

    def test_a_personal_space_comes_out_without_its_owner_and_the_address_in_a_name_stays_out_unless_people_are_shown(self):
        key = f"~{data.ACCOUNT}"
        space_id = self.mock.add_space(key, "Alex Example", "personal")
        hidden = self.cli("space-access", key, "--json")
        self.assertEqual(hidden.code, 0, hidden.err)
        self.assertEqual(hidden.json()["target"], {"id": space_id, "type": "space", "key": "[hidden]", "title": "[personal space]"})
        self.assertNotIn("Alex Example", hidden.out + self.cli("permissions", "--space", key).out)
        self.assertEqual(self.reads(f"/spaces/{space_id}/permissions")[0].path, f"/api/v2/spaces/{space_id}/permissions")  # Confluence is asked by the id
        self.assertEqual(self.cli("space-access", key, "--with-users", "--json").json()["target"], {"id": space_id, "type": "space", "key": key, "title": "Alex Example"})
        self.mock.spaces["1001"]["name"] = "Team of alex@example.com"
        self.assertEqual(self.cli("space-access", "ENG", "--json").json()["target"]["title"], "Team of [email]")
        self.assertEqual(self.cli("permissions", "--space", "ENG", "--json").json()["target"]["title"], "Team of [email]")

    def test_the_name_of_a_role_is_redacted_and_cannot_move_the_cursor(self):
        self.area.roles[2]["name"] = "Readers\x1b[2J of alex@example.com"
        text = self.cli("space-access", "ENG").out
        self.assertNotIn("\x1b", text)
        self.assertNotIn("alex@example.com", text)
        self.assertNotIn("alex@example.com", self.cli("space-access", "ENG", "--json").out)
        shown = self.cli("space-access", "ENG", "--with-users", "--all", "--json").json()
        self.assertIn("Readers\x1b[2J of alex@example.com", {item["roleName"] for item in shown["principals"] if item["model"] == "roles"})


class AsAProgramTest(AccessFlow):
    def test_as_a_separate_program(self):
        result = self.child("restrictions", "2002", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(json.loads(result.out)["state"], "VIEW_RESTRICTED")
        self.assertEqual(self.child("permissions", "2002", "--only", "update", "--json").json()["can"], {"update": True})
        self.assertEqual(self.child("space-access", "ENG").code, 0)
        self.assertEqual(self.child("permissions", "ENG").code, 1)
        self.assertEqual(self.child("restrictions", "99999").code, 4)


if __name__ == "__main__":
    unittest.main()
