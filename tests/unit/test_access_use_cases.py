"""Use cases around what the user may do, restrictions on content, and the permissions and roles of a space, with the in-memory Confluence."""
import unittest

from conflu_c_cli.application.access import INHERITED, READ_PAGE, check_window, looks_like_a_space_key, resolve_content, window
from conflu_c_cli.domain.access import ContentPermission, Operation, SpacePermission, SpaceRole, Subject
from conflu_c_cli.domain.errors import ConfluCliError, NotFoundError, RejectedError, UsageError, ValidationError
from conflu_c_cli.domain.model import Space
from tests.support import data_access as data
from tests.support.fakes import FakeGateway, build_app, default_settings


def app_with(gateway=None, **settings):
    gateway = gateway or FakeGateway()
    return build_app(gateway=gateway, settings=default_settings(**settings)), gateway


def names(gateway):
    return [call[0] for call in gateway.calls]


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()

    def test_the_id_of_an_attachment_says_what_it_is_and_nothing_is_asked(self):
        self.assertEqual(resolve_content(self.gateway, "att5001"), ("attachment", "att5001"))
        self.assertEqual(resolve_content(self.gateway, " att5001 "), ("attachment", "att5001"))
        self.assertEqual(self.gateway.calls, [])

    def test_any_other_id_is_looked_up_once_for_its_type(self):
        self.assertEqual(resolve_content(self.gateway, "2002"), ("page", "2002"))
        self.assertEqual(self.gateway.calls, [("content_types", ("2002",))])
        for content_id, kind in data.KINDS.items():
            with self.subTest(id=content_id):
                self.assertEqual(resolve_content(self.gateway, content_id), (kind, content_id))

    def test_a_comment_is_known_when_the_type_lookup_knows_it(self):
        self.gateway.content_kinds.update({"4001": "footer-comment", "4003": "inline-comment"})
        self.assertEqual(resolve_content(self.gateway, "4001"), ("footer-comment", "4001"))
        self.assertEqual(resolve_content(self.gateway, "4003"), ("inline-comment", "4003"))

    def test_an_address_is_understood_and_only_its_id_is_used(self):
        self.assertEqual(resolve_content(self.gateway, " https://example.atlassian.net/wiki/spaces/ENG/pages/2002/Release+notes "), ("page", "2002"))
        self.assertEqual(resolve_content(self.gateway, "https://example.atlassian.net/wiki/spaces/ENG/folder/7501"), ("folder", "7501"))
        self.assertEqual(resolve_content(self.gateway, "https://elsewhere.example.com/wiki/spaces/ENG/pages/2002/x"), ("page", "2002"))
        self.assertEqual({call[1] for call in self.gateway.calls}, {("2002",), ("7501",)})

    def test_an_id_that_nobody_has_is_not_found_with_the_id_in_the_details(self):
        with self.assertRaises(NotFoundError) as caught:
            resolve_content(self.gateway, "99999")
        self.assertEqual(caught.exception.message, "No content with the id 99999 that this account can see.")
        self.assertEqual(caught.exception.details, {"id": "99999"})

    def test_what_is_no_id_is_refused_before_anything_is_asked(self):
        for text in ("", "abc", "ENG", "../2002", "2002/../1", "12 34", "att", "https://example.atlassian.net/wiki/x/AbCd"):
            with self.subTest(text=text), self.assertRaises(ValidationError):
                resolve_content(self.gateway, text)
        self.assertEqual(self.gateway.calls, [])

    def test_a_text_that_may_be_a_space_key_is_told_apart_from_the_rest(self):
        self.assertTrue(looks_like_a_space_key("ENG"))
        self.assertTrue(looks_like_a_space_key("~5b10ac8d82e05b22cc7d4ef5"))
        for text in ("2002", "", "../ENG", "https://example.atlassian.net/wiki", "a b"):
            with self.subTest(text=text):
                self.assertFalse(looks_like_a_space_key(text))


class WindowTest(unittest.TestCase):
    def test_a_piece_of_a_list_and_where_the_next_one_starts(self):
        items = list(range(5))
        self.assertEqual(window(items, limit=2, cursor="", everything=False), ([0, 1], "2"))
        self.assertEqual(window(items, limit=2, cursor="2", everything=False), ([2, 3], "4"))
        self.assertEqual(window(items, limit=2, cursor="4", everything=False), ([4], ""))
        self.assertEqual(window(items, limit=5, cursor="", everything=False), (items, ""))
        self.assertEqual(window(items, limit=2, cursor="9", everything=False), ([], ""))
        self.assertEqual(window(items, limit=2, cursor="2", everything=True), (items, ""))

    def test_the_limit_and_the_cursor_are_checked(self):
        check_window(1, "")
        check_window(250, "123")
        for limit in (0, -1, 251):
            with self.subTest(limit=limit), self.assertRaises(UsageError) as caught:
                check_window(limit, "")
            self.assertEqual(caught.exception.message, "--limit must be between 1 and 250.")
        for cursor in ("x", "-1", "1e3", "12.5", "0x10", "1" * 10, "２", " 1", "2\n"):
            with self.subTest(cursor=cursor), self.assertRaises(UsageError):
                check_window(25, cursor)


class PermissionsTest(unittest.TestCase):
    def test_what_may_be_done_with_a_page(self):
        app, gateway = app_with()
        result = app.access.permissions.execute("2002")
        self.assertEqual(result.subject, Subject("page", "2002"))
        self.assertEqual(result.can["read"] and result.can["update"] and result.can["delete"], True)
        self.assertIn(Operation("create", "comment"), result.operations)
        self.assertEqual(gateway.calls, [("content_types", ("2002",)), ("list_operations", "page", "2002")])

    def test_a_page_that_may_be_read_and_not_changed(self):
        app, _ = app_with()
        result = app.access.permissions.execute("2003")
        self.assertEqual(result.can, {"read": True, "update": False, "delete": False, "create": True})
        self.assertEqual(result.operations, [Operation("create", "comment"), Operation("read", "page")])

    def test_every_kind_is_asked_in_its_own_collection(self):
        app, gateway = app_with()
        gateway.content_kinds.update({"4001": "footer-comment", "4003": "inline-comment"})
        for content_id, kind in {**data.KINDS, "4001": "footer-comment", "4003": "inline-comment", "att5001": "attachment", "2002": "page"}.items():
            with self.subTest(kind=kind):
                gateway.calls.clear()
                result = app.access.permissions.execute(content_id)
                self.assertEqual(result.subject, Subject(kind, content_id))
                self.assertEqual(gateway.called("list_operations"), [("list_operations", kind, content_id)])
                self.assertTrue(result.can["read"])

    def test_only_the_named_operations_are_kept_and_answered(self):
        app, _ = app_with()
        result = app.access.permissions.execute("2002", only="delete, Update ,export")
        self.assertEqual(result.only, ["delete", "update", "export"])
        self.assertEqual(result.can, {"delete": True, "update": True, "export": False})
        self.assertEqual(result.operations, [Operation("delete", "page"), Operation("update", "page")])

    def test_a_typo_in_only_is_refused_before_anything_is_asked(self):
        app, gateway = app_with()
        with self.assertRaises(UsageError):
            app.access.permissions.execute("2002", only="updat")
        with self.assertRaises(UsageError):
            app.access.permissions.execute(space="ENG", only="updat")
        self.assertEqual(gateway.calls, [])

    def test_what_may_be_done_in_a_space(self):
        app, gateway = app_with()
        result = app.access.permissions.execute(space="ENG")
        self.assertEqual(result.subject, Subject("space", "1001", "ENG", "Engineering"))
        self.assertEqual(result.can["read"], True)
        self.assertEqual(result.can["update"], False)  # the account may delete pages in it, which is another thing
        self.assertEqual(gateway.calls, [("get_space", "ENG"), ("list_operations", "space", "1001")])

    def test_without_an_id_the_current_space_is_asked_about(self):
        app, gateway = app_with(space="DOCS")
        self.assertEqual(app.access.permissions.execute().subject.key, "DOCS")
        self.assertEqual(app.access.permissions.execute(space="ENG").subject.key, "ENG")  # --space wins
        self.assertEqual(gateway.called("get_space"), [("get_space", "DOCS"), ("get_space", "ENG")])

    def test_neither_nor_both_is_a_usage_error_that_says_what_to_give(self):
        app, gateway = app_with()
        with self.assertRaises(UsageError) as caught:
            app.access.permissions.execute()
        self.assertIn("conflu use KEY", caught.exception.hint)
        with self.assertRaises(UsageError) as caught:
            app.access.permissions.execute("2002", space="ENG")
        self.assertIn("not both", caught.exception.message)
        self.assertEqual(gateway.calls, [])

    def test_the_key_of_a_space_given_as_an_id_is_told_how_to_ask_for_a_space(self):
        app, gateway = app_with()
        with self.assertRaises(ValidationError) as caught:
            app.access.permissions.execute("ENG")
        self.assertEqual(caught.exception.message, "Invalid id: ENG")
        self.assertEqual(caught.exception.hint, "If ENG is the key of a space, use --space ENG.")
        with self.assertRaises(ValidationError) as caught:
            app.access.permissions.execute("../ENG")
        self.assertNotIn("--space", caught.exception.hint)
        self.assertEqual(gateway.calls, [])

    def test_content_of_a_type_that_the_cli_does_not_ask_for_is_said_so(self):
        app, gateway = app_with()
        gateway.content_kinds["7600"] = "ac:example:thing"
        with self.assertRaises(ValidationError) as caught:
            app.access.permissions.execute("7600")
        self.assertEqual(caught.exception.message, "7600 is content of the type ac:example:thing: this CLI does not ask what may be done with that.")
        self.assertEqual(caught.exception.details, {"id": "7600", "type": "ac:example:thing"})
        self.assertEqual(gateway.called("list_operations"), [])

    def test_an_unknown_id_or_space_is_not_found(self):
        app, _ = app_with()
        with self.assertRaises(NotFoundError):
            app.access.permissions.execute("99999")
        with self.assertRaises(NotFoundError):
            app.access.permissions.execute(space="NOSUCH")
        with self.assertRaises(ValidationError):
            app.access.permissions.execute(space="../x")

    def test_what_confluence_refuses_passes_through(self):
        app, gateway = app_with()
        gateway.errors["list_operations"] = NotFoundError("Not found: GET /api/v2/pages/2002/operations")
        with self.assertRaises(NotFoundError):
            app.access.permissions.execute("2002")

    def test_the_title_of_a_space_is_redacted_and_a_personal_space_comes_out_without_its_owner(self):
        app, gateway = app_with()
        gateway.spaces["ENG"] = Space("1001", "ENG", "Team of alex@example.com", "global", "current")
        key = f"~{data.ACCOUNT}"
        gateway.spaces[key] = Space("1003", key, "Alex Example", "personal", "current")
        self.assertEqual(app.access.permissions.execute(space="ENG").subject.title, "Team of [email]")
        personal = app.access.permissions.execute(space=key).subject
        self.assertEqual(personal, Subject("space", "1003", "[hidden]", "[personal space]"))  # this command cannot show people
        self.assertEqual(gateway.called("list_operations")[-1], ("list_operations", "space", "1003"))  # Confluence is asked by the id


class RestrictionsTest(unittest.TestCase):
    def test_the_counts_are_always_there_and_the_people_are_not(self):
        app, gateway = app_with()
        result = app.access.restrictions.execute("2002")
        self.assertEqual(result.subject, Subject("page", "2002"))
        self.assertEqual(result.state.state, "VIEW_RESTRICTED")
        self.assertEqual(result.state.created, "2026-10-03T09:00:00.000Z")
        self.assertEqual(result.state.created_by, "")  # a person
        self.assertEqual(result.counts, {"read": {"user": 2, "group": 1}, "update": {"user": 1, "group": 1}})
        self.assertEqual((result.total, result.users_shown, result.permissions, result.next_cursor, result.truncated), (5, False, None, "", False))
        self.assertEqual(result.notes, [INHERITED])
        self.assertEqual(len(gateway.called("list_content_permissions")), 3)  # all of them were read for the counts, two at a time

    def test_who_they_are_comes_with_people_one_piece_at_a_time_in_a_fixed_order(self):
        app, _ = app_with()
        first = app.access.restrictions.execute("2002", with_users=True, limit=2)
        self.assertEqual(first.state.created_by, data.ACCOUNT)
        self.assertEqual([(item.operation, item.principal_type, item.principal_id) for item in first.permissions], [("read", "group", data.GROUP), ("read", "user", data.ACCOUNT)])
        self.assertEqual(first.next_cursor, "2")
        second = app.access.restrictions.execute("2002", with_users=True, limit=2, cursor=first.next_cursor)
        self.assertEqual([(item.operation, item.principal_id) for item in second.permissions], [("read", data.SECOND), ("update", data.GROUP)])
        last = app.access.restrictions.execute("2002", with_users=True, limit=2, cursor=second.next_cursor)
        self.assertEqual([(item.operation, item.principal_id) for item in last.permissions], [("update", data.ACCOUNT)])
        self.assertEqual(last.next_cursor, "")
        self.assertEqual(first.counts, last.counts)  # the counts are of all of them, whatever the piece

    def test_all_of_them_at_once(self):
        app, _ = app_with()
        result = app.access.restrictions.execute("2002", with_users=True, limit=1, cursor="3", fetch_everything=True)
        self.assertEqual(len(result.permissions), 5)
        self.assertEqual(result.next_cursor, "")

    def test_a_piece_beyond_the_end_is_empty(self):
        app, _ = app_with()
        result = app.access.restrictions.execute("2002", with_users=True, cursor="99")
        self.assertEqual((result.permissions, result.next_cursor), ([], ""))

    def test_open_content_has_no_restriction_and_no_direct_permission(self):
        app, _ = app_with()
        result = app.access.restrictions.execute("2001", with_users=True)
        self.assertEqual((result.state.state, result.state.created, result.total, result.permissions), ("OPEN", "", 0, []))
        self.assertEqual(result.counts, {"read": {"user": 0, "group": 0}, "update": {"user": 0, "group": 0}})

    def test_every_kind_that_has_a_restriction_state_is_asked_in_its_own_collection(self):
        app, gateway = app_with()
        for content_id, kind in {"2002": "page", "7501": "folder", "7511": "blogpost", "7521": "whiteboard", "7531": "database"}.items():
            with self.subTest(kind=kind):
                gateway.calls.clear()
                result = app.access.restrictions.execute(content_id)
                self.assertEqual(result.subject, Subject(kind, content_id))
                self.assertEqual(gateway.called("get_restriction_state"), [("get_restriction_state", kind, content_id)])
                self.assertEqual(gateway.called("list_content_permissions")[0][:3], ("list_content_permissions", kind, content_id))

    def test_the_restriction_that_a_folder_has_is_read_as_it_is(self):
        app, _ = app_with()
        result = app.access.restrictions.execute("7501", with_users=True)
        self.assertEqual((result.state.state, result.state.created_by), ("VIEW_RESTRICTED", data.SECOND))
        self.assertEqual(result.counts, {"read": {"user": 0, "group": 1}, "update": {"user": 0, "group": 1}})

    def test_content_that_has_no_restriction_of_its_own_is_said_to_have_none_and_nothing_is_asked_for_it(self):
        app, gateway = app_with()
        gateway.content_kinds["4001"] = "footer-comment"
        for ref, what in (("7541", "a smart link"), ("4001", "a footer comment"), ("att5001", "an attachment"), ("7551", "a piece of custom content of an app")):
            with self.subTest(ref=ref), self.assertRaises(ValidationError) as caught:
                app.access.restrictions.execute(ref)
            self.assertEqual(caught.exception.message, f"{ref} is {what}, which has no restrictions of its own.")
            self.assertIn("follows the content it belongs to", caught.exception.hint)
        self.assertEqual(gateway.called("get_restriction_state") + gateway.called("list_content_permissions"), [])

    def test_the_policy_refuses_people_before_anything_is_asked_and_leaves_the_counts(self):
        app, gateway = app_with(hide_users=True)
        with self.assertRaises(ValidationError) as caught:
            app.access.restrictions.execute("2002", with_users=True)
        self.assertIn("CONFLUENCE_HIDE_USERS=true", caught.exception.message)
        self.assertEqual(gateway.calls, [])
        self.assertEqual(app.access.restrictions.execute("2002").total, 5)

    def test_a_window_that_makes_no_sense_is_refused_before_anything_is_asked(self):
        app, gateway = app_with()
        for kwargs in ({"limit": 0}, {"limit": 251}, {"cursor": "abc"}, {"cursor": "-1"}):
            with self.subTest(**kwargs), self.assertRaises(UsageError):
                app.access.restrictions.execute("2002", with_users=True, **kwargs)
        self.assertEqual(gateway.calls, [])

    def test_an_unknown_id_is_not_found_and_a_bad_one_is_invalid(self):
        app, _ = app_with()
        with self.assertRaises(NotFoundError):
            app.access.restrictions.execute("99999")
        with self.assertRaises(ValidationError):
            app.access.restrictions.execute("abc")

    def test_what_confluence_refuses_passes_through(self):
        app, gateway = app_with()
        for name in ("get_restriction_state", "list_content_permissions"):
            gateway.errors[name] = ConfluCliError("down")
            with self.subTest(name=name), self.assertRaises(ConfluCliError):
                app.access.restrictions.execute("2002")
            del gateway.errors[name]

    def test_a_list_that_never_ends_is_cut_and_the_counts_say_of_what(self):
        app, gateway = app_with()
        gateway.page_cap = READ_PAGE
        gateway.content_permissions["2002"] = [ContentPermission("read", "user", f"u{number}") for number in range(20001)]
        result = app.access.restrictions.execute("2002")
        self.assertEqual((result.truncated, result.total, result.counts["read"]["user"]), (True, 20000, 20000))
        self.assertEqual(len(result.notes), 2)
        self.assertIn("Only the first 20000 direct permissions were read", result.notes[1])


class SpaceAccessTest(unittest.TestCase):
    def test_a_site_in_the_transition_has_both_models_and_says_so(self):
        app, gateway = app_with()
        result = app.access.space_access.execute("ENG")
        self.assertEqual((result.subject, result.mode, result.models), (Subject("space", "1001", "ENG", "Engineering"), "ROLES_TRANSITION", ("permissions", "roles")))
        self.assertEqual(
            [(item.operation, item.target_type, item.user, item.group, item.role) for item in result.permission_counts],
            [("administer", "space", 1, 0, 0), ("create", "comment", 0, 1, 0), ("create", "page", 1, 1, 0), ("read", "space", 2, 1, 0)],
        )
        self.assertEqual([(item.name, item.type, item.user, item.group, item.access_class) for item in result.role_counts], [("Admin", "SYSTEM", 1, 0, 0), ("Contributor", "SYSTEM", 0, 1, 0), ("Viewer", "SYSTEM", 1, 1, 1)])
        self.assertEqual((result.permission_total, result.role_total, result.total), (7, 5, 12))
        self.assertEqual((result.principals, result.users_shown, result.next_cursor, result.truncated), (None, False, "", False))
        self.assertEqual(len(result.notes), 1)
        self.assertIn("ROLES_TRANSITION", result.notes[0])
        order = list(dict.fromkeys(names(gateway)))  # each call, in the order in which it was first made
        self.assertEqual(order, ["get_space", "get_space_role_mode", "list_space_permissions", "list_space_role_assignments", "list_space_roles"])
        self.assertEqual(gateway.called("list_space_roles")[0], ("list_space_roles", "1001", READ_PAGE, ""))  # the roles that this space has

    def test_the_permission_model_alone(self):
        app, gateway = app_with()
        gateway.role_mode = "PRE_ROLES"
        result = app.access.space_access.execute("ENG")
        self.assertEqual((result.mode, result.models, result.role_counts, result.role_total), ("PRE_ROLES", ("permissions",), None, 0))
        self.assertIsNotNone(result.permission_counts)
        self.assertEqual(result.notes, [])
        self.assertEqual(gateway.called("list_space_role_assignments") + gateway.called("list_space_roles"), [])

    def test_the_role_model_alone(self):
        app, gateway = app_with()
        gateway.role_mode = "ROLES"
        result = app.access.space_access.execute("ENG")
        self.assertEqual((result.mode, result.models, result.permission_counts, result.permission_total), ("ROLES", ("roles",), None, 0))
        self.assertEqual(len(result.role_counts), 3)
        self.assertEqual(gateway.called("list_space_permissions"), [])

    def test_a_site_that_reports_no_role_mode_is_asked_for_both_models_and_has_permissions_only_when_it_has_no_roles(self):
        app, gateway = app_with()
        gateway.role_mode = None  # a site without space roles: the mode, the role assignments and the roles are all 404
        result = app.access.space_access.execute("ENG")
        self.assertEqual((result.mode, result.models, result.role_counts, result.role_total), (None, ("permissions",), None, 0))
        self.assertIsNotNone(result.permission_counts)
        self.assertIn("does not report a space role mode", result.notes[0])
        self.assertTrue(any("could not be read, so only its permission assignments are shown" in note for note in result.notes))
        self.assertEqual(len(gateway.called("list_space_role_assignments")), 1)  # asked once, and answered with 404
        self.assertEqual(gateway.called("list_space_roles"), [])

    def test_a_mode_that_cannot_be_read_on_a_site_that_has_roles_does_not_hide_them(self):
        app, gateway = app_with()
        for error in (NotFoundError("x"), RejectedError("y")):
            gateway.errors["get_space_role_mode"] = error
            result = app.access.space_access.execute("ENG")
            with self.subTest(error=type(error).__name__):
                self.assertEqual((result.mode, result.models), (None, ("permissions", "roles")))
                self.assertEqual(len(result.role_counts), 3)
                self.assertEqual(len(result.notes), 1)

    def test_a_mode_that_the_cli_does_not_know_reads_both_models_and_says_so(self):
        app, gateway = app_with()
        gateway.role_mode = "SOMETHING_NEW"
        result = app.access.space_access.execute("ENG")
        self.assertEqual((result.mode, result.models), ("SOMETHING_NEW", ("permissions", "roles")))
        self.assertIn("SOMETHING_NEW is not one this CLI knows", result.notes[0])

    def test_when_the_roles_of_a_site_in_the_transition_cannot_be_read_the_permissions_are_what_is_shown(self):
        app, gateway = app_with()
        gateway.errors["list_space_role_assignments"] = NotFoundError("Not found: GET /api/v2/spaces/1001/role-assignments")
        result = app.access.space_access.execute("ENG")
        self.assertEqual((result.models, result.role_counts, result.role_total), (("permissions",), None, 0))
        self.assertIsNotNone(result.permission_counts)
        self.assertTrue(any("could not be read, so only its permission assignments are shown" in note for note in result.notes))

    def test_when_the_roles_are_all_there_is_and_cannot_be_read_that_is_the_error(self):
        app, gateway = app_with()
        gateway.role_mode = "ROLES"
        gateway.errors["list_space_role_assignments"] = NotFoundError("Not found: GET /api/v2/spaces/1001/role-assignments")
        with self.assertRaises(NotFoundError):
            app.access.space_access.execute("ENG")

    def test_a_role_that_cannot_be_named_is_shown_by_its_id_and_the_note_says_why(self):
        app, gateway = app_with()
        gateway.errors["list_space_roles"] = ConfluCliError("down")
        result = app.access.space_access.execute("ENG")
        self.assertEqual([item.name for item in result.role_counts], sorted([data.ROLE_ADMIN, data.ROLE_CONTRIBUTOR, data.ROLE_VIEWER]))
        self.assertTrue(any(note.startswith("The names of the roles could not be read, so a role is shown by its id") for note in result.notes))

    def test_who_holds_what_comes_with_people_in_a_fixed_order_and_one_piece_at_a_time(self):
        app, _ = app_with()
        everything = app.access.space_access.execute("ENG", with_users=True, fetch_everything=True)
        self.assertEqual(len(everything.principals), 12)
        self.assertEqual(everything.next_cursor, "")
        first = everything.principals[0]
        self.assertEqual((first.model, first.principal_type, first.principal_id, first.operation, first.target_type), ("permissions", "user", data.ACCOUNT, "administer", "space"))
        roles = [item for item in everything.principals if item.model == "roles"]
        self.assertEqual([(item.role_name, item.principal_type) for item in roles], [("Admin", "user"), ("Contributor", "group"), ("Viewer", "access_class"), ("Viewer", "group"), ("Viewer", "user")])
        piece = app.access.space_access.execute("ENG", with_users=True, limit=5)
        self.assertEqual((piece.principals, piece.next_cursor), (everything.principals[:5], "5"))
        rest = app.access.space_access.execute("ENG", with_users=True, limit=5, cursor="10")
        self.assertEqual((rest.principals, rest.next_cursor), (everything.principals[10:], ""))
        self.assertEqual(piece.permission_counts, everything.permission_counts)

    def test_without_people_there_are_counts_and_names_of_roles_and_nothing_else(self):
        app, gateway = app_with()
        gateway.space_roles[2] = SpaceRole(data.ROLE_VIEWER, "Readers of alex@example.com", "CUSTOM")
        hidden = app.access.space_access.execute("ENG")
        self.assertIsNone(hidden.principals)
        self.assertIn("Readers of [email]", [item.name for item in hidden.role_counts])
        shown = app.access.space_access.execute("ENG", with_users=True, fetch_everything=True)
        self.assertIn("Readers of alex@example.com", [item.name for item in shown.role_counts])
        self.assertIn("Readers of alex@example.com", [item.role_name for item in shown.principals])

    def test_the_policy_refuses_people_before_anything_is_asked_and_leaves_the_counts(self):
        app, gateway = app_with(hide_users=True)
        with self.assertRaises(ValidationError):
            app.access.space_access.execute("ENG", with_users=True)
        self.assertEqual(gateway.calls, [])
        self.assertEqual(app.access.space_access.execute("ENG").total, 12)

    def test_the_space_is_the_current_one_when_none_is_named_and_a_missing_one_is_an_error(self):
        app, _ = app_with(space="DOCS")
        self.assertEqual(app.access.space_access.execute().subject.key, "DOCS")
        self.assertEqual(app.access.space_access.execute("ENG").subject.key, "ENG")
        bare, gateway = app_with()
        with self.assertRaises(UsageError) as caught:
            bare.access.space_access.execute()
        self.assertIn("conflu use KEY", caught.exception.hint)
        with self.assertRaises(NotFoundError):
            bare.access.space_access.execute("NOSUCH")
        with self.assertRaises(ValidationError):
            bare.access.space_access.execute("../x")
        self.assertEqual(gateway.called("get_space"), [("get_space", "NOSUCH")])

    def test_a_space_without_assignments_has_empty_counts_and_not_none(self):
        app, gateway = app_with()
        result = app.access.space_access.execute("DOCS")
        self.assertEqual((result.permission_counts, result.role_counts, result.total), ([], [], 0))
        self.assertEqual(result.models, ("permissions", "roles"))

    def test_a_personal_space_comes_out_without_its_owner_unless_people_are_shown(self):
        app, gateway = app_with()
        key = f"~{data.ACCOUNT}"
        gateway.spaces[key] = Space("1003", key, "Alex Example", "personal", "current")
        gateway.space_permissions["1003"] = [SpacePermission("p1", "user", data.ACCOUNT, "read", "space")]
        self.assertEqual(app.access.space_access.execute(key).subject, Subject("space", "1003", "[hidden]", "[personal space]"))
        self.assertEqual(app.access.space_access.execute(key, with_users=True).subject, Subject("space", "1003", key, "Alex Example"))
        self.assertEqual(gateway.called("list_space_permissions")[0][:2], ("list_space_permissions", "1003"))  # the calls name the space by its id

    def test_an_unknown_role_in_an_assignment_is_counted_by_its_id(self):
        app, gateway = app_with()
        gateway.space_roles.clear()
        gateway.space_roles.append(SpaceRole("other", "Other", "CUSTOM"))
        result = app.access.space_access.execute("ENG")
        self.assertEqual({item.role_id for item in result.role_counts}, {data.ROLE_ADMIN, data.ROLE_CONTRIBUTOR, data.ROLE_VIEWER})


class WiringTest(unittest.TestCase):
    def test_the_use_cases_are_reached_through_the_application(self):
        app, _ = app_with()
        self.assertEqual({name for name in vars(app.access)}, {"permissions", "restrictions", "space_access"})


if __name__ == "__main__":
    unittest.main()
