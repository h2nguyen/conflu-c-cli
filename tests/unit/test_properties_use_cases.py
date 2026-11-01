"""The use cases around content properties, against the fake Confluence: read the properties of any content, and set one (create, the next version, nothing)."""
import dataclasses
import unittest

from conflu_c_cli.application.properties import resolve_target
from conflu_c_cli.domain.errors import ConflictError, NotFoundError, UsageError, ValidationError
from conflu_c_cli.domain.model import Chunk, User
from conflu_c_cli.domain.properties import CUT_MARKER, TOO_DEEP, ContentProperty, compact
from tests.support.fakes import ACCOUNT, BASE, FakeGateway, RecordingDiagnostics, build_app, default_settings

# What holds properties in the fake: a page, and one piece of content of every other kind (blog post, folder, whiteboard, database, smart link).
HOLDERS = (("2002", "page"), ("7390", "blogpost"), ("7391", "folder"), ("7392", "whiteboard"), ("7393", "database"), ("7394", "embed"), ("att5001", "attachment"))


def fresh(**settings):
    gateway = FakeGateway()
    gateway.content_kinds.update({"4001": "footer-comment", "4003": "inline-comment"})  # the comments are known as content only when a test says so
    diagnostics = RecordingDiagnostics()
    app = build_app(gateway=gateway, settings=default_settings(**settings), diagnostics=diagnostics)
    return app, gateway, diagnostics


def keys(result):
    return [view.key for view in result.properties]


def deep(levels):
    value = None
    for _ in range(levels):
        value = [value]
    return value


class ResolveTargetTest(unittest.TestCase):
    def test_a_page_a_blog_post_and_the_other_kinds_are_found_by_asking_what_the_id_is_once(self):
        _, gateway, _ = fresh()
        for ref, kind in HOLDERS[:-1] + (("4001", "footer-comment"), ("4003", "inline-comment")):
            with self.subTest(ref=ref):
                gateway.calls.clear()
                target = resolve_target(gateway, ref)
                self.assertEqual((target.id, target.type), (ref, kind))
                self.assertEqual(gateway.calls, [("content_types", (ref,))])

    def test_an_attachment_is_known_by_its_id_and_nobody_is_asked(self):
        _, gateway, _ = fresh()
        for ref in ("att5001", " att5001 ", "att1"):
            with self.subTest(ref=ref):
                target = resolve_target(gateway, ref)
                self.assertEqual((target.id, target.type), (ref.strip(), "attachment"))
        self.assertEqual(gateway.calls, [])

    def test_the_number_of_an_attachment_is_written_with_the_prefix_the_api_uses(self):
        _, gateway, _ = fresh()
        gateway.content_kinds["5001"] = "attachment"
        target = resolve_target(gateway, "5001")
        self.assertEqual((target.id, target.type), ("att5001", "attachment"))

    def test_the_address_of_a_page_is_a_page(self):
        _, gateway, _ = fresh()
        self.assertEqual(resolve_target(gateway, f"{BASE}/spaces/ENG/pages/2002/Release+notes").id, "2002")

    def test_content_that_is_not_there_is_not_found(self):
        _, gateway, _ = fresh()
        with self.assertRaises(NotFoundError) as caught:
            resolve_target(gateway, "99999")
        self.assertEqual(caught.exception.details, {"id": "99999"})

    def test_content_that_has_no_properties_here_is_refused_and_named(self):
        _, gateway, _ = fresh()
        gateway.content_kinds["8001"] = "custom"
        with self.assertRaises(ValidationError) as caught:
            resolve_target(gateway, "8001")
        self.assertIn("custom content", caught.exception.message)
        self.assertEqual(caught.exception.details, {"id": "8001", "type": "custom"})

    def test_what_is_no_id_is_refused_and_nobody_is_asked(self):
        _, gateway, _ = fresh()
        for ref in ("", "page", "../2002", "2002 2003", "att", "attx", "https://example.com/x"):
            with self.subTest(ref=ref), self.assertRaises(ValidationError):
                resolve_target(gateway, ref)
        self.assertEqual(gateway.calls, [])


class ListPropertiesTest(unittest.TestCase):
    def test_the_properties_of_a_page_by_key_a_piece_at_a_time(self):
        app, gateway, _ = fresh()
        first = app.properties.list_properties.execute("2002")
        self.assertEqual((keys(first), first.next_cursor, first.truncated), (["content-appearance-published", "editor"], "2", False))
        self.assertEqual((first.target.id, first.target.type), ("2002", "page"))
        self.assertEqual(gateway.called("list_properties")[-1], ("list_properties", "page", "2002", "", 25, ""))
        second = app.properties.list_properties.execute("2002", cursor="2")
        self.assertEqual((keys(second), second.next_cursor), (["team.review"], ""))

    def test_all_of_them_in_big_pieces(self):
        app, gateway, _ = fresh()
        result = app.properties.list_properties.execute("2002", fetch_everything=True, limit=1)
        self.assertEqual((keys(result), result.next_cursor, result.truncated), (["content-appearance-published", "editor", "team.review"], "", False))
        self.assertEqual({call[-2] for call in gateway.called("list_properties")}, {100})

    def test_a_property_is_its_id_key_version_time_and_value(self):
        app, _, _ = fresh()
        view = app.properties.list_properties.execute("2002", key="content-appearance-published").properties[0]
        self.assertEqual((view.id, view.key, view.version, view.updated, view.value, view.text, view.truncated), ("7302", "content-appearance-published", 2, "2026-10-05T08:00:00.000Z", "full-width", '"full-width"', False))

    def test_one_key_is_asked_for_with_the_key_and_is_case_sensitive(self):
        app, gateway, _ = fresh()
        self.assertEqual(keys(app.properties.list_properties.execute("2002", key="editor")), ["editor"])
        self.assertEqual(gateway.called("list_properties")[-1][3], "editor")
        self.assertEqual(keys(app.properties.list_properties.execute("2002", key="Editor")), [])
        self.assertEqual(keys(app.properties.list_properties.execute("2005")), [])  # a page without any

    def test_every_other_kind_of_content_has_its_properties(self):
        app, gateway, _ = fresh()
        for ref, kind in HOLDERS[1:] + (("4001", "footer-comment"), ("4003", "inline-comment")):
            with self.subTest(ref=ref):
                result = app.properties.list_properties.execute(ref)
                self.assertEqual((result.target.type, len(result.properties)), (kind, 1))
                self.assertEqual(gateway.called("list_properties")[-1][1:3], (kind, ref))

    def test_a_long_value_is_cut_at_the_number_of_characters_asked_for_and_says_so(self):
        app, _, _ = fresh()
        view = app.properties.list_properties.execute("2003").properties[0]  # 2000 characters is the default
        self.assertEqual((view.truncated, len(view.text), view.total_chars), (True, 2000 + len(CUT_MARKER), 4411))
        self.assertEqual(view.value, view.text)  # a value that was cut is the text of its beginning
        self.assertTrue(view.text.endswith(CUT_MARKER))  # and it says in itself that it is no value, so that `property-set` can refuse it
        whole = app.properties.list_properties.execute("2003", max_chars=0).properties[0]
        self.assertEqual((whole.truncated, whole.total_chars, whole.value["items"][399]), (False, 4411, "item-399"))
        self.assertNotIn(CUT_MARKER, whole.text)
        self.assertEqual(len(app.properties.list_properties.execute("2003", max_chars=100).properties[0].text), 100 + len(CUT_MARKER))

    def test_a_value_that_fits_is_the_value_itself_and_not_its_text(self):
        app, _, _ = fresh()
        view = app.properties.list_properties.execute("7392").properties[0]
        self.assertEqual((view.value, view.text, view.truncated), ({"zoom": 1.5}, '{"zoom":1.5}', False))

    def test_a_negative_number_of_characters_is_a_usage_error_and_nothing_is_asked(self):
        app, gateway, _ = fresh()
        with self.assertRaises(UsageError) as caught:
            app.properties.list_properties.execute("2002", max_chars=-1)
        self.assertIn("--max-chars", caught.exception.message)
        self.assertEqual(gateway.calls, [])

    def test_people_in_a_value_are_hidden_unless_they_are_asked_for(self):
        app, _, _ = fresh()
        hidden = app.properties.list_properties.execute("2002", key="team.review").properties[0].value
        self.assertEqual(hidden, {"status": "open", "reviewer": {"hidden": True}, "owners": ["[hidden]"], "note": "Ask [email]"})
        shown = app.properties.list_properties.execute("2002", key="team.review", with_users=True).properties[0].value
        self.assertEqual(shown["reviewer"], {"accountId": ACCOUNT, "displayName": "Alex Example"})
        self.assertEqual(shown["owners"], [ACCOUNT])

    def test_a_key_that_holds_an_address_is_hidden_too(self):
        app, gateway, _ = fresh()
        gateway.property_store[("pages", "2005")] = [ContentProperty("7399", "alex@example.com", 1, "x")]
        self.assertEqual(keys(app.properties.list_properties.execute("2005")), ["[email]"])
        self.assertEqual(keys(app.properties.list_properties.execute("2005", with_users=True)), ["alex@example.com"])

    def test_the_cut_is_made_after_the_people_are_hidden(self):
        app, gateway, _ = fresh()
        gateway.property_store[("pages", "2005")] = [ContentProperty("7399", "note", 1, "x" * 15 + "alex@example.com")]
        view = app.properties.list_properties.execute("2005", max_chars=22).properties[0]
        self.assertNotIn("example.com", view.text)
        self.assertNotIn("alex", view.text)

    def test_the_people_are_not_available_under_the_policy_that_hides_them(self):
        app, gateway, _ = fresh(hide_users=True)
        with self.assertRaises(ValidationError) as caught:
            app.properties.list_properties.execute("2002", with_users=True)
        self.assertIn("CONFLUENCE_HIDE_USERS", caught.exception.message)
        self.assertEqual(gateway.calls, [])

    def test_a_value_nested_too_deeply_to_walk_is_not_shown_and_does_not_break_the_list(self):
        app, gateway, _ = fresh()
        gateway.property_store[("pages", "2005")] = [ContentProperty("7399", "deep", 1, deep(5000)), ContentProperty("7398", "fine", 1, 1)]
        result = app.properties.list_properties.execute("2005", fetch_everything=True)
        self.assertEqual({view.key: view.value for view in result.properties}, {"deep": TOO_DEEP, "fine": 1})

    def test_a_value_with_half_of_a_surrogate_pair_can_be_printed(self):
        app, gateway, _ = fresh()
        gateway.property_store[("pages", "2005")] = [ContentProperty("7399", "k\ud800", 1, {"a": "b\udc00"})]
        view = app.properties.list_properties.execute("2005").properties[0]
        compact(view.value).encode("utf-8")
        view.key.encode("utf-8")
        view.text.encode("utf-8")

    def test_content_that_is_not_there_is_not_found_and_no_property_is_asked_for(self):
        app, gateway, _ = fresh()
        with self.assertRaises(NotFoundError):
            app.properties.list_properties.execute("99999")
        self.assertEqual(gateway.called("list_properties"), [])
        with self.assertRaises(NotFoundError):
            app.properties.list_properties.execute("att99999")  # the fake knows no such attachment: the list says so


class SetPropertyTest(unittest.TestCase):
    def steps(self, gateway):
        return [call[0] for call in gateway.calls if call[0] in ("list_properties", "create_property", "update_property")]

    def test_a_new_key_is_created(self):
        app, gateway, _ = fresh()
        result = app.properties.set_property.execute("2002", "new.key", {"a": [1]})
        self.assertEqual((result.action, result.key, result.property_id, result.version_from, result.version_to, result.current, result.dry_run, result.notes), ("created", "new.key", "7313", 0, 1, None, False, []))
        self.assertEqual(result.payload, {"key": "new.key", "value": {"a": [1]}})
        self.assertEqual(self.steps(gateway), ["list_properties", "create_property"])
        self.assertEqual(gateway.called("create_property")[0], ("create_property", "page", "2002", {"key": "new.key", "value": {"a": [1]}}))
        self.assertEqual([item.key for item in gateway.property_store[("pages", "2002")]][-1], "new.key")

    def test_the_property_is_looked_for_by_its_key_before_anything_is_written(self):
        app, gateway, _ = fresh()
        app.properties.set_property.execute("2002", "new.key", 1)
        reads = gateway.called("list_properties")
        self.assertEqual(reads, [("list_properties", "page", "2002", "new.key", 100, "")])
        self.assertLess(gateway.calls.index(reads[0]), gateway.calls.index(gateway.called("create_property")[0]))

    def test_a_key_that_is_there_gets_its_next_version(self):
        app, gateway, _ = fresh()
        result = app.properties.set_property.execute("2002", "team.review", {"status": "closed"})
        self.assertEqual((result.action, result.property_id, result.version_from, result.version_to), ("updated", "7303", 3, 4))
        self.assertEqual(result.payload, {"key": "team.review", "value": {"status": "closed"}, "version": {"number": 4}})
        self.assertEqual(gateway.called("update_property")[0], ("update_property", "page", "2002", "7303", result.payload))
        self.assertEqual(self.steps(gateway), ["list_properties", "update_property"])
        stored = next(item for item in gateway.property_store[("pages", "2002")] if item.key == "team.review")
        self.assertEqual((stored.version, stored.value), (4, {"status": "closed"}))

    def test_what_confluence_held_is_shown_without_its_people(self):
        app, _, _ = fresh()
        result = app.properties.set_property.execute("2002", "team.review", {"status": "closed"})
        self.assertEqual(result.current, {"status": "open", "reviewer": {"hidden": True}, "owners": ["[hidden]"], "note": "Ask [email]"})
        self.assertNotIn(ACCOUNT, repr(result.current))

    def test_a_message_goes_with_the_new_version_and_a_new_property_has_none(self):
        app, gateway, _ = fresh()
        changed = app.properties.set_property.execute("2002", "team.review", 1, message="Reviewed")
        self.assertEqual(changed.payload["version"], {"number": 4, "message": "Reviewed"})
        self.assertEqual(changed.notes, [])
        created = app.properties.set_property.execute("2002", "other.key", 1, message="Hello")
        self.assertEqual(created.payload, {"key": "other.key", "value": 1})
        self.assertEqual(len(created.notes), 1)
        self.assertIn("--message was not sent", created.notes[0])

    def test_the_value_that_is_there_already_is_left_alone(self):
        app, gateway, _ = fresh()
        for value in ("v2",):
            result = app.properties.set_property.execute("2002", "editor", value)
            self.assertEqual((result.action, result.payload, result.version_from, result.version_to, result.property_id, result.dry_run), ("unchanged", None, 1, 1, "7301", False))
        self.assertEqual(self.steps(gateway), ["list_properties"] * 1)
        same = app.properties.set_property.execute("2002", "team.review", {"note": "Ask alex@example.com", "owners": [ACCOUNT], "reviewer": {"displayName": "Alex Example", "accountId": ACCOUNT}, "status": "open"})
        self.assertEqual(same.action, "unchanged")  # an object has no order of its keys
        self.assertNotIn("update_property", self.steps(gateway))

    def test_one_and_one_point_zero_are_the_same_number_and_one_and_true_are_not(self):
        app, gateway, _ = fresh()
        app.properties.set_property.execute("2002", "number", 1)
        self.assertEqual(app.properties.set_property.execute("2002", "number", 1.0).action, "unchanged")
        self.assertEqual(app.properties.set_property.execute("2002", "number", True).action, "updated")

    def test_a_message_that_could_not_be_sent_because_nothing_changed_is_noted(self):
        app, _, _ = fresh()
        result = app.properties.set_property.execute("2002", "editor", "v2", message="Again")
        self.assertEqual(result.action, "unchanged")
        self.assertIn("nothing was saved", result.notes[0])

    def test_a_dry_run_reads_and_sends_nothing_and_shows_what_would_be_sent(self):
        app, gateway, _ = fresh()
        update = app.properties.set_property.execute("2002", "team.review", [1], dry_run=True, message="Draft")
        create = app.properties.set_property.execute("2002", "new.key", [1], dry_run=True)
        same = app.properties.set_property.execute("2002", "editor", "v2", dry_run=True)
        self.assertEqual(self.steps(gateway), ["list_properties"] * 3)
        self.assertEqual((update.action, update.dry_run, update.version_from, update.version_to, update.payload), ("updated", True, 3, 4, {"key": "team.review", "value": [1], "version": {"number": 4, "message": "Draft"}}))
        self.assertEqual((create.action, create.dry_run, create.property_id, create.version_from, create.version_to, create.payload), ("created", True, "", 0, 1, {"key": "new.key", "value": [1]}))
        self.assertEqual((same.action, same.dry_run, same.payload), ("unchanged", True, None))
        self.assertEqual(len(gateway.property_store[("pages", "2002")]), 3)

    def test_what_is_sent_is_what_the_dry_run_showed(self):
        app, gateway, _ = fresh()
        preview = app.properties.set_property.execute("2002", "team.review", {"a": 1}, message="M", dry_run=True).payload
        app.properties.set_property.execute("2002", "team.review", {"a": 1}, message="M")
        self.assertEqual(gateway.called("update_property")[0][-1], preview)
        preview = app.properties.set_property.execute("2002", "fresh", {"a": 1}, dry_run=True).payload
        app.properties.set_property.execute("2002", "fresh", {"a": 1})
        self.assertEqual(gateway.called("create_property")[0][-1], preview)

    def test_the_hidden_form_of_a_property_is_refused_and_nothing_is_written(self):
        app, gateway, _ = fresh()
        hidden = {"status": "closed", "reviewer": {"hidden": True}, "owners": ["[hidden]"], "note": "Ask [email]"}
        with self.assertRaises(ValidationError) as caught:
            app.properties.set_property.execute("2002", "team.review", hidden)
        error = caught.exception
        self.assertEqual(error.exit_code, 1)
        self.assertIn("`[hidden]`, `[email]` and `{\"hidden\": true}`", error.message)
        self.assertIn("the property team.review of the page 2002", error.message)
        self.assertEqual(error.details, {"id": "2002", "key": "team.review", "markers": ["[hidden]", "[email]", '{"hidden": true}']})
        self.assertIn("conflu properties 2002 --key team.review --with-users --max-chars 0 --json", error.hint)
        self.assertEqual(self.steps(gateway), ["list_properties"])
        stored = next(item for item in gateway.property_store[("pages", "2002")] if item.key == "team.review")
        self.assertEqual((stored.version, stored.value["reviewer"]["accountId"]), (3, ACCOUNT))
        for text in (error.message, error.hint, repr(error.details)):
            self.assertNotIn(ACCOUNT, text)
            self.assertNotIn("alex@example.com", text)

    def test_a_dry_run_and_a_guard_do_not_let_it_pass_and_the_refusal_comes_first(self):
        app, gateway, _ = fresh()
        with self.assertRaises(ValidationError):
            app.properties.set_property.execute("2002", "team.review", {"owners": ["[hidden]"]}, dry_run=True)
        with self.assertRaises(ValidationError):
            app.properties.set_property.execute("2002", "team.review", {"owners": ["[hidden]"]}, if_version=99)  # the value is wrong before the version is
        self.assertEqual(self.steps(gateway), ["list_properties"] * 2)

    def test_one_stand_in_is_enough_and_a_refusal_names_only_what_is_in_the_value(self):
        app, gateway, _ = fresh()
        for value, marker in (({"status": "x", "note": "Ask [email]"}, "[email]"), ({"reviewer": {"hidden": True}}, '{"hidden": true}'), ("[hidden]", "[hidden]")):
            with self.subTest(marker=marker), self.assertRaises(ValidationError) as caught:
                app.properties.set_property.execute("2002", "team.review", value)
            self.assertEqual(caught.exception.details["markers"], [marker])
        self.assertEqual(self.steps(gateway), ["list_properties"] * 3)

    def test_the_value_that_was_read_with_the_people_is_written_back_changed_and_keeps_them(self):
        app, gateway, _ = fresh()
        real = next(item for item in gateway.property_store[("pages", "2002")] if item.key == "team.review").value
        result = app.properties.set_property.execute("2002", "team.review", {**real, "status": "closed"})
        self.assertEqual((result.action, result.version_to), ("updated", 4))
        sent = gateway.called("update_property")[0][-1]["value"]
        self.assertEqual((sent["reviewer"], sent["owners"], sent["note"]), (real["reviewer"], [ACCOUNT], "Ask alex@example.com"))

    def test_a_new_property_and_a_property_without_people_take_the_stand_ins_as_what_they_are(self):
        app, gateway, _ = fresh()
        created = app.properties.set_property.execute("2002", "legend", {"hidden": True, "text": "[hidden] [email] [personal link]"})
        self.assertEqual(created.action, "created")
        updated = app.properties.set_property.execute("2002", "editor", "[email]")
        self.assertEqual(updated.action, "updated")
        flagged = app.properties.set_property.execute("2002", "legend", {"hidden": False})
        self.assertEqual(flagged.action, "updated")

    def test_a_value_that_was_too_deep_to_show_cannot_be_written_back_as_the_text_that_stands_for_it(self):
        app, gateway, _ = fresh()
        gateway.property_store[("pages", "2005")] = [ContentProperty("7399", "deep", 1, deep(5000))]
        with self.assertRaises(ValidationError) as caught:
            app.properties.set_property.execute("2005", "deep", TOO_DEEP)
        self.assertEqual(caught.exception.details["markers"], [TOO_DEEP])
        self.assertEqual(app.properties.set_property.execute("2005", "deep", {"flat": True}, dry_run=True).action, "updated")

    def test_a_stand_in_that_the_property_holds_itself_does_not_let_the_account_id_next_to_it_be_overwritten(self):
        app, gateway, _ = fresh()
        real = {"a": "[hidden]", "b": ACCOUNT}  # an app wrote the text `[hidden]`, and the account id of a person stands next to it
        gateway.property_store[("pages", "2005")] = [ContentProperty("7399", "swap", 1, real)]
        shown = app.properties.list_properties.execute("2005", key="swap").properties[0].value
        self.assertEqual(shown, {"a": "[hidden]", "b": "[hidden]"})
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run), self.assertRaises(ValidationError) as caught:
                app.properties.set_property.execute("2005", "swap", {"a": "changed", "b": "[hidden]"}, dry_run=dry_run)  # as many stand-ins as the property holds: the counts are equal
            self.assertEqual(caught.exception.details["markers"], ["[hidden]"])
        self.assertEqual((gateway.property_store[("pages", "2005")][0].value, gateway.called("update_property")), (real, []))
        done = app.properties.set_property.execute("2005", "swap", {"a": "changed", "b": ACCOUNT})  # the real value, changed where the app wants it
        self.assertEqual(done.action, "updated")

    def test_the_key_that_a_reading_made_of_an_account_id_is_not_written_back_either(self):
        app, gateway, _ = fresh()
        real = {ACCOUNT: "owner", "[hidden]": "an app's key"}
        gateway.property_store[("pages", "2005")] = [ContentProperty("7399", "keys", 1, real)]
        shown = app.properties.list_properties.execute("2005", key="keys").properties[0].value
        self.assertEqual(sorted(shown), ["[hidden]", "[hidden] (2)"])
        with self.assertRaises(ValidationError) as caught:
            app.properties.set_property.execute("2005", "keys", {"[hidden]": "owner", "[hidden] (2)": "edited"})
        self.assertEqual(caught.exception.details["markers"], ["[hidden]"])
        self.assertEqual(gateway.property_store[("pages", "2005")][0].value, real)

    def test_a_value_that_was_cut_by_a_reading_is_refused_and_nothing_is_written(self):
        app, gateway, _ = fresh()
        cut = app.properties.list_properties.execute("2003", key="inventory").properties[0]
        self.assertTrue(cut.truncated)
        before = list(gateway.property_store[("pages", "2003")])
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run), self.assertRaises(ValidationError) as caught:
                app.properties.set_property.execute("2003", "inventory", cut.value, dry_run=dry_run)
            error = caught.exception
            self.assertEqual((error.exit_code, error.details), (1, {"id": "2003", "key": "inventory", "markers": [CUT_MARKER]}))
            self.assertIn(f"`{CUT_MARKER}`", error.message)
            self.assertIn("replace the whole property inventory of the page 2003 with the beginning of it", error.message)
            self.assertIn("conflu properties 2003 --key inventory --max-chars 0 --json", error.hint)
        self.assertEqual(self.steps(gateway), ["list_properties"] * 3)  # the reading that made the cut value, and one read for each of the two refused writes
        self.assertEqual(gateway.property_store[("pages", "2003")], before)

    def test_a_cut_value_is_refused_before_the_guard_and_for_a_new_property_too(self):
        app, gateway, _ = fresh()
        cut = app.properties.list_properties.execute("2003", key="inventory").properties[0].value
        with self.assertRaises(ValidationError):
            app.properties.set_property.execute("2003", "inventory", cut, if_version=99)  # the value is wrong before the version is
        with self.assertRaises(ValidationError) as caught:
            app.properties.set_property.execute("2005", "inventory.copy", cut)  # a new property: nothing to overwrite, and still no cut copy
        self.assertIn("store the beginning of a value as the value of a new property", caught.exception.message)
        self.assertEqual(gateway.property_store.get(("pages", "2005"), []), [])
        self.assertEqual(self.steps(gateway), ["list_properties"] * 3)  # the reading that made the cut value, and one read for each of the two refused writes

    def test_the_whole_value_that_was_read_with_no_cut_is_written_back_changed(self):
        app, gateway, _ = fresh()
        whole = app.properties.list_properties.execute("2003", key="inventory", max_chars=0).properties[0].value
        whole["items"].append("item-new")
        result = app.properties.set_property.execute("2003", "inventory", whole)
        self.assertEqual((result.action, result.version_from, result.version_to), ("updated", 1, 2))
        stored = next(item for item in gateway.property_store[("pages", "2003")] if item.key == "inventory")
        self.assertEqual((len(stored.value["items"]), stored.value["items"][-1]), (401, "item-new"))

    def test_a_blanked_account_attribute_is_refused_in_every_attribute_and_nothing_is_written(self):
        app, gateway, _ = fresh()
        for attribute in ("data-account-id", "data-userkey", "data-username", "ri:account-id", "ri:userkey", "ri:username"):
            key = "snippet." + attribute.replace(":", ".")
            real = {"html": f'<a {attribute}="{ACCOUNT}">@Alex</a> reviewed', "n": 1}
            gateway.property_store[("pages", "2005")] = [ContentProperty("7399", key, 1, real)]
            shown = app.properties.list_properties.execute("2005", key=key).properties[0].value
            with self.subTest(attribute=attribute), self.assertRaises(ValidationError) as caught:
                app.properties.set_property.execute("2005", key, {**shown, "n": 2})
            self.assertEqual(shown["html"], f'<a {attribute}="hidden">@Alex</a> reviewed')
            self.assertEqual(caught.exception.details["markers"], [f'{attribute}="hidden"'])
            self.assertIn(f'`{attribute}="hidden"`', caught.exception.message)
            self.assertEqual(gateway.property_store[("pages", "2005")][0].value, real)
        self.assertEqual(gateway.called("update_property"), [])

    def test_an_address_that_a_reading_showed_without_its_title_is_refused_and_the_message_shows_which(self):
        app, gateway, _ = fresh()
        url = "https://example.atlassian.net/wiki/spaces/ENG/pages/124/Contact+alex%40example.com"
        gateway.property_store[("pages", "2005")] = [ContentProperty("7399", "link", 1, {"url": url, "n": 1})]
        shown = app.properties.list_properties.execute("2005", key="link").properties[0].value
        with self.assertRaises(ValidationError) as caught:
            app.properties.set_property.execute("2005", "link", {**shown, "n": 2})
        error = caught.exception
        self.assertEqual(error.details, {"id": "2005", "key": "link", "texts": ["https://example.atlassian.net/wiki/spaces/ENG/pages/124"]})
        self.assertIn("`https://example.atlassian.net/wiki/spaces/ENG/pages/124`", error.message)
        self.assertIn("conflu properties 2005 --key link --with-users --max-chars 0 --json", error.hint)
        self.assertNotIn("alex", error.message + error.hint + repr(error.details))
        self.assertEqual(gateway.called("update_property"), [])
        real = app.properties.list_properties.execute("2005", key="link", with_users=True).properties[0].value  # read with the people shown: the address is whole
        self.assertEqual(real["url"], url)
        self.assertEqual(app.properties.set_property.execute("2005", "link", {**real, "n": 2}).action, "updated")

    def test_a_refusal_for_texts_names_how_many_and_cuts_the_long_ones(self):
        app, gateway, _ = fresh()
        slug = "Contact+alex%40example.com"
        base = "https://example.atlassian.net/wiki/" + "d" * 100 + "/pages/"  # a long address, as the reading shows it: without the slug
        urls = {name: f"{base}{number}/{slug}" for number, name in enumerate(("a", "b", "c", "d"), start=100)}
        gateway.property_store[("pages", "2005")] = [ContentProperty("7399", "links", 1, urls)]
        shown = app.properties.list_properties.execute("2005", key="links").properties[0].value
        with self.assertRaises(ValidationError) as caught:
            app.properties.set_property.execute("2005", "links", {**shown, "n": 2})
        error = caught.exception
        self.assertIn("holds 4 texts that", error.message)
        self.assertEqual(len(error.details["texts"]), 3)  # for example three of them
        self.assertTrue(all(len(text) == 80 and text.endswith("...") for text in error.details["texts"]))

    def test_the_key_is_looked_for_in_every_piece_of_the_answer(self):
        app, gateway, _ = fresh()
        real, asked = gateway.list_properties, []

        def pieces(kind, content_id, *, key="", limit=25, cursor=""):
            asked.append(cursor)
            if not cursor:  # a piece that holds other keys only, and points to the next one
                return Chunk([ContentProperty("7301", "editor", 1, "v2")], "more")
            return real(kind, content_id, key=key, limit=limit, cursor="")

        gateway.list_properties = pieces
        result = app.properties.set_property.execute("2002", "team.review", {"status": "closed"})
        self.assertEqual((result.action, asked), ("updated", ["", "more"]))

    def test_the_version_that_confluence_answers_is_the_one_that_is_reported(self):
        app, gateway, _ = fresh()
        create, update = gateway.create_property, gateway.update_property
        gateway.create_property = lambda kind, content_id, payload: dataclasses.replace(create(kind, content_id, payload), version=5)
        gateway.update_property = lambda kind, content_id, property_id, payload: dataclasses.replace(update(kind, content_id, property_id, payload), version=9)
        self.assertEqual(app.properties.set_property.execute("2002", "fresh.key", 1).version_to, 5)
        self.assertEqual(app.properties.set_property.execute("2002", "team.review", 1).version_to, 9)

    def test_the_guard_says_the_version_the_property_must_have(self):
        app, gateway, _ = fresh()
        done = app.properties.set_property.execute("2002", "team.review", 1, if_version=3)
        self.assertEqual((done.action, done.version_to), ("updated", 4))
        with self.assertRaises(ConflictError) as caught:
            app.properties.set_property.execute("2002", "team.review", 2, if_version=3)
        self.assertEqual(caught.exception.exit_code, 3)
        self.assertIn("at version 4, not 3", caught.exception.message)
        self.assertEqual(caught.exception.details, {"id": "2002", "key": "team.review", "version": 4, "expected": 3})
        self.assertIn("conflu properties 2002 --key team.review", caught.exception.hint)
        self.assertEqual(len(gateway.called("update_property")), 1)  # the second was refused before anything was sent

    def test_zero_says_that_the_property_must_not_be_there_yet(self):
        app, gateway, _ = fresh()
        self.assertEqual(app.properties.set_property.execute("2002", "brand.new", 1, if_version=0).action, "created")
        with self.assertRaises(ConflictError) as caught:
            app.properties.set_property.execute("2002", "editor", "v3", if_version=0)
        self.assertIn("exists already (version 1)", caught.exception.message)
        with self.assertRaises(ConflictError) as missing:
            app.properties.set_property.execute("2002", "never.there", 1, if_version=2)
        self.assertIn("does not exist", missing.exception.message)

    def test_a_guard_refuses_in_a_dry_run_too_and_before_any_write(self):
        app, gateway, _ = fresh()
        with self.assertRaises(ConflictError):
            app.properties.set_property.execute("2002", "team.review", 1, if_version=9, dry_run=True)
        with self.assertRaises(ConflictError):
            app.properties.set_property.execute("2002", "editor", "v2", if_version=9)  # not even a value that is there already gets past it
        self.assertEqual(self.steps(gateway), ["list_properties"] * 2)

    def test_a_guard_below_zero_is_a_usage_error_and_nothing_is_asked(self):
        app, gateway, _ = fresh()
        with self.assertRaises(UsageError):
            app.properties.set_property.execute("2002", "k", 1, if_version=-1)
        self.assertEqual(gateway.calls, [])

    def test_a_save_that_lost_against_somebody_else_is_a_conflict_that_speaks_of_the_property(self):
        app, gateway, _ = fresh()
        gateway.errors["update_property"] = ConflictError(
            "Confluence reports a conflict (HTTP 409): version.", hint="The page changed meanwhile. Read it again and review the current state before writing.", details={"status": 409}
        )
        with self.assertRaises(ConflictError) as caught:
            app.properties.set_property.execute("2002", "team.review", 1)
        self.assertEqual(caught.exception.exit_code, 3)
        self.assertEqual(caught.exception.message, "Confluence reports a conflict (HTTP 409): version.")
        self.assertNotIn("page changed", caught.exception.hint)
        self.assertIn("conflu properties 2002 --key team.review", caught.exception.hint)
        self.assertEqual(caught.exception.details, {"status": 409, "id": "2002", "key": "team.review"})

    def test_a_creation_that_lost_is_a_conflict_too(self):
        app, gateway, _ = fresh()
        gateway.errors["create_property"] = ConflictError("Confluence reports a conflict (HTTP 409).", hint="The page changed meanwhile.")
        with self.assertRaises(ConflictError) as caught:
            app.properties.set_property.execute("2002", "new.key", 1)
        self.assertIn("conflu properties 2002 --key new.key", caught.exception.hint)

    def test_an_invalid_key_is_a_usage_error_and_nothing_is_asked(self):
        app, gateway, _ = fresh()
        for key in ("", "bad key", "a/b", "x" * 256, "a\nb"):
            with self.subTest(key=key[:20]), self.assertRaises(UsageError):
                app.properties.set_property.execute("2002", key, 1)
        self.assertEqual(gateway.calls, [])

    def test_content_that_is_not_there_is_not_found_and_nothing_is_written(self):
        app, gateway, _ = fresh()
        with self.assertRaises(NotFoundError):
            app.properties.set_property.execute("99999", "k", 1)
        self.assertEqual(self.steps(gateway), [])

    def test_every_kind_of_content_takes_a_property_and_a_new_version_of_it(self):
        app, gateway, _ = fresh()
        for ref, kind in HOLDERS + (("4001", "footer-comment"), ("4003", "inline-comment")):
            with self.subTest(ref=ref):
                created = app.properties.set_property.execute(ref, "kind.test", {"n": 1})
                updated = app.properties.set_property.execute(ref, "kind.test", {"n": 2})
                self.assertEqual((created.action, created.target.type, updated.action, updated.version_from, updated.version_to), ("created", kind, "updated", 1, 2))
                self.assertEqual(gateway.called("create_property")[-1][1:3], (kind, ref))
                self.assertEqual(gateway.called("update_property")[-1][1:3], (kind, ref))

    def test_a_key_is_case_sensitive(self):
        app, gateway, _ = fresh()
        self.assertEqual(app.properties.set_property.execute("2002", "Editor", "v2").action, "created")
        self.assertEqual(len(gateway.property_store[("pages", "2002")]), 4)

    def test_the_value_that_is_there_nested_too_deeply_to_compare_is_replaced_and_shown_as_such(self):
        app, gateway, _ = fresh()
        gateway.property_store[("pages", "2005")] = [ContentProperty("7399", "deep", 1, deep(5000))]
        result = app.properties.set_property.execute("2005", "deep", {"flat": True}, dry_run=True)
        self.assertEqual((result.action, result.current), ("updated", TOO_DEEP))

    def test_no_use_case_deletes_a_property(self):
        app, gateway, _ = fresh()
        self.assertFalse([name for name in dir(gateway) if "delete" in name or "remove_prop" in name])
        self.assertFalse([name for name in dir(app.properties.set_property) if "delete" in name])

    def test_somebody_else_may_hold_the_same_key_on_another_page(self):
        app, gateway, _ = fresh()
        result = app.properties.set_property.execute("2003", "editor", "v2")
        self.assertEqual((result.action, result.version_from), ("created", 0))  # 2002 has `editor` and 2003 has not
        self.assertEqual(len(gateway.property_store[("pages", "2003")]), 2)

    def test_the_user_of_the_token_is_not_needed_and_not_asked(self):
        app, gateway, _ = fresh()
        gateway.user = User("")
        app.properties.set_property.execute("2002", "x.y", 1)
        self.assertEqual(gateway.called("current_user"), [])


if __name__ == "__main__":
    unittest.main()
