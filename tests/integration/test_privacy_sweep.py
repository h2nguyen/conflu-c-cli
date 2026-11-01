"""People stay out of every command's output, whatever Confluence puts into its free text.

The sweep of the commands (tests/support/sweeps_all.py) runs every command of every feature area against a mock that adds an e-mail address
to every title, name, message, description, comment and body it answers, and to the address of a page (tests/support/taint.py). A command that
prints one of those texts without the redaction, or a person, when people are not shown, is a leak, and this module fails and names it.
"""
import unittest
from functools import lru_cache

from conflu_c_cli.adapters.driving.cli.registry import all_commands
from tests.support.sweep_runner import SweepResult, run_sweeps
from tests.support.sweeps_all import SWEEPS
from tests.support.taint import ADDRESS_MARKERS, MARKERS, PEOPLE_MARKERS, TAINT

STRICT = {"CONFLUENCE_HIDE_USERS": "true"}
# What a command shows by design when the policy does not forbid it: the person who owns the token, and Confluence's own answer to `conflu api`.
OWNER_OR_RAW = frozenset({"ping", "doctor", "api"})


@lru_cache(maxsize=None)
def strict_run() -> SweepResult:
    return run_sweeps(SWEEPS, env=STRICT, taint=True)


@lru_cache(maxsize=None)
def default_run() -> SweepResult:
    return run_sweeps(SWEEPS, taint=True)


def leaks(result: SweepResult, markers: tuple[str, ...], skip: frozenset[str] = frozenset(), asked_for_people: bool = False) -> list[str]:
    """The lines whose output holds a marker, in what they print and in the files that `export` writes. A line that asks for people with `--with-users` is looked at only when `asked_for_people`."""
    found = []
    for output in result.outputs:
        if output.argv[0] in skip or ("--with-users" in output.argv and not asked_for_people):
            continue
        text = (output.out + output.err + output.written).lower()
        found.extend(f"{output.area}: conflu {' '.join(output.argv)} printed {marker!r}" for marker in markers if marker in text)
    return found


class PrivacySweepTest(unittest.TestCase):
    def test_the_sweep_is_not_empty_and_the_mock_does_taint(self):
        result = default_run()
        self.assertGreater(len(result.outputs), 100)
        shown = [output for output in result.outputs if "--with-users" in output.argv and TAINT in output.out.lower()]
        self.assertTrue(shown, "no command that shows people printed the text that the mock marked: the taint does not reach the commands")

    def test_under_the_strict_policy_no_command_prints_a_person_or_the_marked_text(self):
        self.assertEqual(leaks(strict_run(), MARKERS, asked_for_people=True), [])

    def test_under_the_strict_policy_every_with_users_request_is_refused(self):
        refused = [
            f"{output.area}: conflu {' '.join(output.argv)} ended with {output.code}"
            for output in strict_run().outputs
            if "--with-users" in output.argv and output.code != 1
        ]
        self.assertEqual(refused, [])

    def test_without_with_users_no_command_prints_the_marked_text(self):
        self.assertEqual(leaks(default_run(), ADDRESS_MARKERS, skip=frozenset({"api"})), [])

    def test_without_with_users_no_command_prints_a_person_unless_it_is_the_owner_or_the_raw_answer(self):
        self.assertEqual(leaks(default_run(), PEOPLE_MARKERS, skip=OWNER_OR_RAW), [])

    def test_every_command_that_changes_confluence_is_swept_with_a_dry_run(self):
        """A dry run prints the request, which holds what was read from the page: the privacy sweep has to see it."""
        swept = {output.argv[0] for output in default_run().outputs if "--dry-run" in output.argv}
        writers = {command.name for command in all_commands() if command.writes and any("--dry-run" in arg.names for arg in command.args)}
        self.assertEqual(sorted(writers - swept), [])


if __name__ == "__main__":
    unittest.main()
