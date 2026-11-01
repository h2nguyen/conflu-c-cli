"""`update` refuses an empty guard, and a page that came back without its body is not changed blind."""
import unittest
from dataclasses import replace

from conflu_c_cli.domain.drafts import PageChanges
from conflu_c_cli.domain.errors import UnavailableError, ValidationError
from tests.support.cli import run_cli
from tests.support.fakes import FakeGateway, build_app


class EmptyGuardTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway()
        self.app = build_app(gateway=self.gateway)

    def test_an_empty_time_is_an_error_and_sends_nothing(self):
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run):
                with self.assertRaises(ValidationError):
                    self.app.update_page.execute("2002", PageChanges(title="T"), if_unchanged_since="", dry_run=dry_run)
        self.assertEqual((self.gateway.called("update_page"), self.gateway.called("update_title")), ([], []))

    def test_the_command_exits_with_1_and_names_the_problem(self):
        result = run_cli("update", "2002", "--title", "T", "--if-unchanged-since", "", gateway=self.gateway)
        self.assertEqual(result.code, 1)
        self.assertIn("--if-unchanged-since", result.err)  # the option is named, as `move`, `attach`, `restore` and `blogpost-update` name it
        self.assertEqual((self.gateway.called("update_page"), self.gateway.called("update_title")), ([], []))

    def test_an_empty_or_unreadable_time_is_refused_before_anything_is_asked_in_a_dry_run_too(self):
        for value in ("", "   ", "yesterday", "2026-13-45"):
            for dry in ((), ("--dry-run",)):
                with self.subTest(value=value, dry=dry):
                    gateway = FakeGateway()
                    result = run_cli("update", "2002", "--title", "T", "--if-unchanged-since", value, *dry, gateway=gateway)
                    self.assertEqual((result.code, result.out), (1, ""))
                    self.assertIn("--if-unchanged-since", result.err)
                    self.assertEqual(gateway.calls, [])  # not even the page was read

    def test_no_guard_given_is_no_guard(self):
        result = run_cli("update", "2002", "--title", "T", "--dry-run", gateway=self.gateway)
        self.assertEqual(result.code, 0, result.err)

    def test_a_time_after_the_last_change_passes_and_one_before_it_is_a_conflict(self):
        self.assertEqual(run_cli("update", "2002", "--title", "T", "--if-unchanged-since", "2026-10-16T00:00:00Z", "--dry-run", gateway=self.gateway).code, 0)
        self.assertEqual(run_cli("update", "2002", "--title", "T", "--if-unchanged-since", "2026-10-01T00:00:00Z", "--dry-run", gateway=self.gateway).code, 3)


class BodyThatWasNotAnsweredTest(unittest.TestCase):
    def test_an_append_to_a_page_that_came_back_without_its_body_is_refused(self):
        gateway = FakeGateway()

        class WithoutBody(type(gateway)):  # a Confluence (or a proxy) that leaves the body out of its answer
            def get_page(self, page_id, *args, **kwargs):
                return replace(super().get_page(page_id, *args, **kwargs), body=None)

        gateway.__class__ = WithoutBody
        app = build_app(gateway=gateway)
        for mode in ("append", "prepend", "replace"):
            with self.subTest(mode=mode):
                with self.assertRaises(UnavailableError):
                    app.update_page.execute("2005", PageChanges(body="<p>x</p>", body_mode=mode))
        self.assertEqual(gateway.called("update_page"), [])
        app.update_page.execute("2005", PageChanges(title="Only the title"))  # a title change does not need the body
        self.assertEqual(len(gateway.called("update_title")), 1)


if __name__ == "__main__":
    unittest.main()
