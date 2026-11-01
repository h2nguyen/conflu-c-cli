"""Test failures as annotations of the check: what is written, how it is escaped, and that nothing changes outside of GitHub Actions."""
from __future__ import annotations

import inspect
import io
import os
import unittest
from contextlib import redirect_stdout
from unittest import mock

from tests.support import github_annotations as annotated


def failing(message: str, name: str = "check"):
    def check():
        raise AssertionError(message)

    check.__name__ = name
    return check


def breaking(name: str = "breaks"):
    def check():
        raise KeyError("missing")

    check.__name__ = name
    return check


def run(*checks) -> unittest.TestResult:
    result = unittest.TestResult()
    unittest.TestSuite(unittest.FunctionTestCase(check) for check in checks).run(result)
    return result


def commands_for(*checks) -> list[str]:
    result = run(*checks)
    return annotated.annotations(result.failures, result.errors)


class AnnotationsTest(unittest.TestCase):
    def test_a_failure_becomes_an_error_command_with_what_went_wrong_as_its_title_and_the_traceback_in_the_message(self):
        (command,) = commands_for(failing("one != two"))
        self.assertTrue(command.startswith("::error title=FAIL%3A AssertionError%3A one != two::"), command)
        self.assertIn("1 test(s): check", command)
        self.assertIn("Traceback (most recent call last)", command.replace("%0A", "\n"))

    def test_the_failures_with_the_same_exception_line_are_one_command(self):
        commands = commands_for(failing("same", "first"), failing("same", "second"), failing("other", "third"))
        self.assertEqual(len(commands), 2)
        self.assertIn("2 test(s): first, second", commands[0])
        self.assertIn("1 test(s): third", commands[1])

    def test_an_error_is_told_from_a_failure(self):
        commands = commands_for(breaking(), failing("wrong"))
        self.assertEqual(len(commands), 2)
        self.assertTrue(any(command.startswith("::error title=ERROR%3A KeyError%3A 'missing'::") for command in commands), commands)
        self.assertTrue(any(command.startswith("::error title=FAIL%3A AssertionError%3A wrong::") for command in commands), commands)

    def test_the_title_is_the_exception_line_and_not_the_last_line_of_a_long_message(self):
        (command,) = commands_for(failing("'a' != 'b'\n- a\n+ b\n  same"))
        self.assertTrue(command.startswith("::error title=FAIL%3A AssertionError%3A 'a' != 'b'::"), command)
        self.assertIn("%0A- a%0A+ b%0A  same", command)

    def test_a_line_break_a_percent_sign_a_colon_and_a_comma_cannot_end_the_command_or_its_title(self):
        (command,) = commands_for(failing("100% done: a, b\nsecond line"))
        self.assertNotIn("\n", command)
        self.assertNotIn("\r", command)
        title, message = command[len("::error title=") :].split("::", 1)
        self.assertEqual(title, "FAIL%3A AssertionError%3A 100%25 done%3A a%2C b")
        self.assertIn("second line", message)
        self.assertIn("%0A", message)

    def test_no_more_commands_are_written_than_a_step_may_show(self):
        self.assertEqual(len(commands_for(*[failing(f"distinct {number}") for number in range(annotated.LIMIT + 5)])), annotated.LIMIT)

    def test_many_tests_of_one_group_are_named_by_a_few_and_counted(self):
        (command,) = commands_for(*[failing("same", f"check_{number}") for number in range(annotated.NAMES + 4)])
        self.assertIn(f"{annotated.NAMES + 4} test(s): check_0", command)
        self.assertIn(f"check_{annotated.NAMES - 1} and 4 more", command)
        self.assertNotIn(f"check_{annotated.NAMES},", command)

    def test_a_long_traceback_is_cut_to_its_end(self):
        (command,) = commands_for(failing("x" * 20000))
        self.assertLess(len(command), 3 * annotated.SAMPLE)

    def test_a_run_without_failures_has_nothing_to_write(self):
        self.assertEqual(commands_for(lambda: None), [])
        result = run(lambda: None)
        self.assertEqual(annotated.annotations(result.failures, result.errors, [("a_test", 99.0)]), [])  # the times are named when something failed

    def test_a_run_that_failed_names_its_slowest_tests_in_a_notice(self):
        result = run(failing("wrong"))
        times = [(f"test_{number}", float(number)) for number in range(annotated.SLOW + 5)]
        commands = annotated.annotations(result.failures, result.errors, times)
        self.assertEqual(len(commands), 2)
        title, message = commands[1][len("::notice title=") :].split("::", 1)
        self.assertEqual(title, f"The {annotated.SLOW} slowest tests")
        lines = message.split("%0A")
        self.assertEqual(len(lines), annotated.SLOW)
        self.assertTrue(lines[0].endswith("test_16") and "16.00 s" in lines[0], lines[0])  # the slowest first
        self.assertTrue(lines[-1].endswith("test_5"), lines[-1])

    def test_the_times_are_optional_because_python_before_3_12_has_none(self):
        result = run(failing("wrong"))
        self.assertEqual(len(annotated.annotations(result.failures, result.errors)), 1)
        self.assertEqual(len(annotated.annotations(result.failures, result.errors, [])), 1)


class InstallTest(unittest.TestCase):
    def report(self, **environment: str) -> str:
        """What a run with one failing test writes to standard output, after `install` was called in this environment. The run starts from the
        `printErrors` of unittest itself: on GitHub Actions the one in place is already the patched one."""
        plain = inspect.unwrap(unittest.TextTestResult.printErrors)
        out = io.StringIO()
        with mock.patch.dict(os.environ, environment), mock.patch.object(unittest.TextTestResult, "printErrors", plain):
            if "GITHUB_ACTIONS" not in environment:
                os.environ.pop("GITHUB_ACTIONS", None)
            annotated.install()
            suite = unittest.TestSuite([unittest.FunctionTestCase(failing("seen"))])
            with redirect_stdout(out):
                unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
        return out.getvalue()

    def test_on_github_actions_a_run_writes_its_failures_as_annotations(self):
        self.assertIn("::error title=FAIL%3A AssertionError%3A seen::", self.report(GITHUB_ACTIONS="true"))

    def test_anywhere_else_a_run_writes_nothing_more_than_before(self):
        self.assertEqual(self.report(), "")
        self.assertEqual(self.report(GITHUB_ACTIONS="false"), "")

    def test_the_patch_is_undone_when_the_test_ends(self):
        before = unittest.TextTestResult.printErrors
        self.report(GITHUB_ACTIONS="true")
        self.assertIs(unittest.TextTestResult.printErrors, before)


if __name__ == "__main__":
    unittest.main()
