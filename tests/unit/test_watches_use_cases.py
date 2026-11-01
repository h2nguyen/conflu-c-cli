"""The use cases around the watches of the user, against the fake Confluence: say whether you watch, start and stop, dry run, read-back."""
import inspect
import unittest
from dataclasses import replace

from conflu_c_cli.application.watches import ChangeWatch, ShowWatching, check_command
from conflu_c_cli.domain.errors import NotFoundError, RejectedError, UnavailableError, UsageError, ValidationError
from conflu_c_cli.domain.model import Space
from conflu_c_cli.domain.watches import SPACE, WatchChange, WatchTarget
from tests.support.fakes import BASE, FakeGateway, RecordingDiagnostics, build_app, default_settings

BLOG_POST = "7561"  # content of a kind that no other fixture has, registered where this test needs it
FOLDER = "7562"


def fresh(**settings):
    gateway = FakeGateway()
    gateway.content_kinds[BLOG_POST] = "blogpost"
    gateway.content_kinds[FOLDER] = "folder"
    diagnostics = RecordingDiagnostics()
    return build_app(gateway=gateway, settings=default_settings(**settings), diagnostics=diagnostics), gateway, diagnostics


def steps(gateway):
    """The calls that matter for a watch, in order."""
    return [call for call in gateway.calls if call[0] in ("watch_status", "change_watch")]


class ShowWatchingTest(unittest.TestCase):
    def test_content_is_watched_or_it_is_not(self):
        app, gateway, _ = fresh()
        self.assertFalse(app.watches.watching.execute("2002").watching)
        gateway.watching.add(("content", "2002"))
        state = app.watches.watching.execute("2002")
        self.assertTrue(state.watching)
        self.assertEqual((state.target.type, state.target.id, state.target.key, state.target.title), ("page", "2002", "", ""))
        self.assertEqual(gateway.called("watch_status")[-1], ("watch_status", "content", "2002"))

    def test_the_kind_is_what_confluence_calls_the_content(self):
        app, gateway, _ = fresh()
        gateway.watching.add(("content", BLOG_POST))
        for content_id, kind, watched in ((BLOG_POST, "blogpost", True), (FOLDER, "folder", False)):
            with self.subTest(kind=kind):
                state = app.watches.watching.execute(content_id)
                self.assertEqual((state.target.type, state.watching), (kind, watched))

    def test_the_address_of_a_page_names_it_as_well(self):
        app, _, _ = fresh()
        for ref in (f"{BASE}/spaces/ENG/pages/2002/Release+notes", " 2002 ", f"{BASE}/pages/viewpage.action?pageId=2002"):
            with self.subTest(ref=ref):
                self.assertEqual(app.watches.watching.execute(ref).target.id, "2002")

    def test_a_space_is_named_by_its_key_and_the_call_gets_the_key(self):
        app, gateway, _ = fresh()
        gateway.watching.add(("space", "ENG"))
        state = app.watches.watching.execute(space="eng")
        self.assertTrue(state.watching)
        self.assertEqual((state.target.type, state.target.id, state.target.key, state.target.title), ("space", "1001", "ENG", "Engineering"))
        self.assertEqual(state.target.shown_key, "ENG")
        self.assertEqual(gateway.called("watch_status")[-1], ("watch_status", "space", "ENG"))

    def test_a_read_assumes_the_current_space_when_nothing_is_named(self):
        app, _, _ = fresh(space="DOCS")
        self.assertEqual(app.watches.watching.execute().target.key, "DOCS")
        self.assertEqual(app.watches.watching.execute(space="ENG").target.key, "ENG")  # what is named wins
        app, _, _ = fresh()
        with self.assertRaises(UsageError) as caught:
            app.watches.watching.execute()
        self.assertIn("conflu use", caught.exception.hint)

    def test_a_page_and_a_space_together_are_a_usage_error_that_asks_nothing(self):
        app, gateway, _ = fresh()
        with self.assertRaises(UsageError):
            app.watches.watching.execute("2002", space="ENG")
        self.assertEqual(gateway.calls, [])

    def test_content_that_is_not_there_is_not_found_and_its_watch_is_never_asked(self):
        app, gateway, _ = fresh()
        with self.assertRaises(NotFoundError) as caught:
            app.watches.watching.execute("99999")
        self.assertEqual(caught.exception.details, {"id": "99999"})
        self.assertEqual(gateway.called("watch_status"), [])

    def test_a_bad_id_is_invalid_and_the_hint_says_how_a_space_is_named(self):
        app, gateway, _ = fresh()
        for ref in ("../etc", "2002/../1", "page", "https://example.com/x"):
            with self.subTest(ref=ref), self.assertRaises(ValidationError) as caught:
                app.watches.watching.execute(ref)
            self.assertIn("--space KEY", caught.exception.hint)
        self.assertEqual(gateway.calls, [])

    def test_a_bad_or_unknown_space_key(self):
        app, gateway, _ = fresh()
        with self.assertRaises(ValidationError):
            app.watches.watching.execute(space="../x")
        with self.assertRaises(NotFoundError):
            app.watches.watching.execute(space="NOSUCH")
        self.assertEqual(gateway.called("watch_status"), [])

    def test_the_name_of_a_space_goes_through_the_redaction_like_every_title(self):
        app, gateway, _ = fresh()
        gateway.spaces["ENG"] = replace(gateway.spaces["ENG"], name="Team of alex@example.com")
        self.assertEqual(app.watches.watching.execute(space="ENG").target.title, "Team of [email]")

    def test_a_personal_space_is_printed_as_everywhere_and_the_call_still_gets_its_key(self):
        """It is named after its owner and keyed by the owner's account id: it comes out as `conflu spaces` prints it (`privacy.hide_space`)."""
        app, gateway, _ = fresh()
        gateway.spaces["~alexe"] = Space("1003", "~alexe", "Alex Example", "personal", "current")
        gateway.spaces["~5b10ac8d82e05b22cc7d4ef5"] = Space("1004", "~5b10ac8d82e05b22cc7d4ef5", "Alex Example", "", "current")  # recognised by its key as well
        for key in ("~alexe", "~5b10ac8d82e05b22cc7d4ef5"):
            with self.subTest(key=key):
                state = app.watches.watching.execute(space=key)
                self.assertEqual((state.target.type, state.target.key, state.target.shown_key, state.target.title), ("space", key, "[hidden]", "[personal space]"))
                self.assertEqual(gateway.called("watch_status")[-1], ("watch_status", "space", key))  # the call needs the real key
        for result in (app.watches.watch.execute(space="~alexe", dry_run=True), app.watches.watch.execute(space="~alexe")):
            self.assertEqual((result.target.shown_key, result.target.title), ("[hidden]", "[personal space]"))
        self.assertEqual(gateway.watching, {("space", "~alexe")})

    def test_what_a_message_sends_a_person_to_does_not_carry_the_key_of_a_personal_space(self):
        self.assertEqual(check_command(WatchTarget(SPACE, "1003", "~alexe", "[personal space]", "[hidden]")), "conflu watching --space [hidden]")
        self.assertEqual(check_command(WatchTarget(SPACE, "1001", "ENG", "Engineering", "ENG")), "conflu watching --space ENG")
        self.assertEqual(check_command(WatchTarget("page", "2002")), "conflu watching 2002")

    def test_an_answer_that_fails_is_an_error_and_not_a_no(self):
        app, gateway, _ = fresh()
        gateway.errors["watch_status"] = UnavailableError("busy")
        with self.assertRaises(UnavailableError):
            app.watches.watching.execute("2002")


class ChangeWatchTest(unittest.TestCase):
    def test_a_watch_is_read_then_sent_then_read_back(self):
        app, gateway, diagnostics = fresh()
        result = app.watches.watch.execute("2002")
        self.assertEqual((result.action, result.dry_run, result.was_watching, result.watching, result.confirmed), ("watched", False, False, True, True))
        self.assertEqual(result.change, WatchChange("content", "2002", True))
        self.assertEqual(result.message, "")
        self.assertEqual([call[0] for call in steps(gateway)], ["watch_status", "change_watch", "watch_status"])
        self.assertEqual(steps(gateway)[1], ("change_watch", WatchChange("content", "2002", True)))
        self.assertEqual(gateway.watching, {("content", "2002")})
        self.assertEqual(diagnostics.warnings, [])

    def test_a_watch_that_is_there_is_left_alone_and_nothing_is_sent(self):
        app, gateway, _ = fresh()
        app.watches.watch.execute("2002")
        again = app.watches.watch.execute("2002")
        self.assertEqual((again.action, again.was_watching, again.watching, again.confirmed, again.change), ("unchanged", True, True, None, None))
        self.assertEqual(len(gateway.called("change_watch")), 1)

    def test_stopping_takes_your_watch_off_and_stopping_again_changes_nothing(self):
        app, gateway, _ = fresh()
        gateway.watching.add(("content", "2002"))
        stopped = app.watches.watch.execute("2002", remove=True)
        self.assertEqual((stopped.action, stopped.was_watching, stopped.watching, stopped.confirmed), ("unwatched", True, False, True))
        self.assertEqual(stopped.change, WatchChange("content", "2002", False))
        self.assertEqual(stopped.change.method, "DELETE")
        self.assertEqual(gateway.watching, set())
        again = app.watches.watch.execute("2002", remove=True)
        self.assertEqual((again.action, again.change), ("unchanged", None))
        self.assertEqual(len(gateway.called("change_watch")), 1)

    def test_stopping_takes_off_nobody_elses_watch_and_leaves_the_other_watches(self):
        app, gateway, _ = fresh()
        gateway.watching.update({("content", "2002"), ("content", "2003"), ("space", "ENG")})
        app.watches.watch.execute("2002", remove=True)
        self.assertEqual(gateway.watching, {("content", "2003"), ("space", "ENG")})

    def test_a_space_is_watched_by_its_key(self):
        app, gateway, _ = fresh()
        result = app.watches.watch.execute(space="eng")
        self.assertEqual((result.action, result.target.key, result.confirmed), ("watched", "ENG", True))
        self.assertEqual(result.change, WatchChange("space", "ENG", True))
        self.assertEqual(gateway.watching, {("space", "ENG")})

    def test_any_kind_of_content_may_be_watched(self):
        app, gateway, _ = fresh()
        for content_id, kind in (("2002", "page"), (BLOG_POST, "blogpost"), (FOLDER, "folder")):
            with self.subTest(kind=kind):
                self.assertEqual(app.watches.watch.execute(content_id).target.type, kind)
        self.assertEqual(gateway.watching, {("content", "2002"), ("content", BLOG_POST), ("content", FOLDER)})

    def test_the_dry_run_reads_and_sends_nothing_and_shows_what_the_real_run_sends(self):
        app, gateway, _ = fresh()
        dry = app.watches.watch.execute("2002", dry_run=True)
        self.assertEqual((dry.action, dry.dry_run, dry.was_watching, dry.watching, dry.confirmed), ("watched", True, False, False, None))
        self.assertEqual(dry.change, WatchChange("content", "2002", True))
        self.assertEqual(gateway.called("change_watch"), [])
        self.assertEqual(gateway.watching, set())
        self.assertEqual([call[0] for call in steps(gateway)], ["watch_status"])  # the target was read, and nothing else
        real = app.watches.watch.execute("2002")
        self.assertEqual(gateway.called("change_watch")[0][1], dry.change)
        self.assertEqual(real.change, dry.change)

    def test_the_dry_run_of_a_watch_that_is_as_asked_has_nothing_to_send(self):
        app, gateway, _ = fresh()
        gateway.watching.add(("space", "ENG"))
        dry = app.watches.watch.execute(space="ENG", dry_run=True)
        self.assertEqual((dry.action, dry.dry_run, dry.change), ("unchanged", True, None))
        remove = app.watches.watch.execute("2002", remove=True, dry_run=True)  # not watched, so nothing to take off
        self.assertEqual((remove.action, remove.change), ("unchanged", None))

    def test_the_dry_run_of_a_stop_is_a_delete(self):
        app, gateway, _ = fresh()
        gateway.watching.add(("content", "2002"))
        dry = app.watches.watch.execute("2002", remove=True, dry_run=True)
        self.assertEqual((dry.action, dry.change.method, dry.watching), ("unwatched", "DELETE", True))
        self.assertEqual(gateway.watching, {("content", "2002")})

    def test_a_read_back_that_fails_after_the_write_is_no_failure(self):
        class ReadBackFails(FakeGateway):
            def change_watch(self, change):
                super().change_watch(change)
                self.errors["watch_status"] = UnavailableError("Confluence answered with a server error (HTTP 500).")

        gateway = ReadBackFails()
        diagnostics = RecordingDiagnostics()
        app = build_app(gateway=gateway, diagnostics=diagnostics)
        result = app.watches.watch.execute("2002")
        self.assertEqual((result.action, result.watching, result.confirmed), ("watched", None, None))
        self.assertEqual(gateway.watching, {("content", "2002")})  # the change was made
        self.assertIn("The watch was added, but reading the watch status afterwards failed", result.message)
        self.assertIn("HTTP 500", result.message)
        self.assertIn("`conflu watching 2002`", result.message)
        self.assertEqual(diagnostics.warnings, [result.message])

    def test_what_the_failed_read_says_is_what_confluence_said_and_is_redacted_like_every_text_of_it(self):
        class ReadBackFails(FakeGateway):
            def change_watch(self, change):
                super().change_watch(change)
                self.errors["watch_status"] = UnavailableError("Confluence answered with a server error (HTTP 500): no access for alex@example.com.")

        gateway = ReadBackFails()
        diagnostics = RecordingDiagnostics()
        result = build_app(gateway=gateway, diagnostics=diagnostics).watches.watch.execute("2002")
        self.assertEqual((result.action, result.confirmed), ("watched", None))
        self.assertIn("no access for [email]", result.message)
        self.assertNotIn("alex@example.com", result.message + " ".join(diagnostics.warnings))

    def test_the_read_back_of_a_space_says_how_to_check_it(self):
        class ReadBackFails(FakeGateway):
            def change_watch(self, change):
                super().change_watch(change)
                self.errors["watch_status"] = UnavailableError("busy")

        gateway = ReadBackFails()
        gateway.watching.add(("space", "ENG"))
        result = build_app(gateway=gateway).watches.watch.execute(space="ENG", remove=True)
        self.assertIn("The watch was taken off, but", result.message)
        self.assertIn("`conflu watching --space ENG`", result.message)

    def test_a_change_that_confluence_accepts_and_does_not_show_is_reported_as_not_confirmed(self):
        class Ignores(FakeGateway):
            def change_watch(self, change):
                self._enter("change_watch", change)

        gateway = Ignores()
        diagnostics = RecordingDiagnostics()
        result = build_app(gateway=gateway, diagnostics=diagnostics).watches.watch.execute("2002")
        self.assertEqual((result.action, result.watching, result.confirmed), ("watched", False, False))
        self.assertIn("still says that you do not watch it", result.message)
        self.assertEqual(diagnostics.warnings, [result.message])

    def test_a_write_that_is_refused_is_an_error_and_is_not_read_back(self):
        app, gateway, diagnostics = fresh()
        gateway.errors["change_watch"] = RejectedError("Confluence refused the request (HTTP 400): no")
        with self.assertRaises(RejectedError):
            app.watches.watch.execute("2002")
        self.assertEqual([call[0] for call in steps(gateway)], ["watch_status", "change_watch"])
        self.assertEqual((gateway.watching, diagnostics.warnings), (set(), []))

    def test_a_status_that_cannot_be_read_stops_before_anything_is_written(self):
        app, gateway, _ = fresh()
        gateway.errors["watch_status"] = UnavailableError("busy")
        with self.assertRaises(UnavailableError):
            app.watches.watch.execute("2002")
        self.assertEqual(gateway.called("change_watch"), [])

    def test_content_that_is_not_there_is_not_found_and_nothing_is_written(self):
        app, gateway, _ = fresh()
        with self.assertRaises(NotFoundError):
            app.watches.watch.execute("99999")
        with self.assertRaises(NotFoundError):
            app.watches.watch.execute(space="NOSUCH")
        self.assertEqual((gateway.called("change_watch"), gateway.called("watch_status")), ([], []))

    def test_a_change_names_what_it_changes_the_current_space_is_not_assumed(self):
        app, gateway, _ = fresh(space="ENG")
        with self.assertRaises(UsageError) as caught:
            app.watches.watch.execute()
        self.assertIn("never assumes the current space", caught.exception.hint)
        with self.assertRaises(UsageError):
            app.watches.watch.execute("2002", space="ENG")
        self.assertEqual((gateway.calls, gateway.watching), ([], set()))

    def test_there_is_no_way_to_name_another_person(self):
        self.assertEqual(list(inspect.signature(ChangeWatch.execute).parameters), ["self", "ref", "space", "remove", "dry_run"])
        self.assertEqual(list(inspect.signature(ShowWatching.execute).parameters), ["self", "ref", "space"])


if __name__ == "__main__":
    unittest.main()
