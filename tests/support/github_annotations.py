"""A failed test is also an annotation of the check in a pull request.

Where `GITHUB_ACTIONS` is `true` (a runner of GitHub Actions) the failures of a run are written once more, as `::error` workflow commands. GitHub
shows those with the job, so what failed can be read without opening the log. The failures are grouped by what went wrong (the line of the
exception that ends a traceback), and no more groups are written than a step may show. A run that failed also names the tests that took the
longest (Python 3.12 and later keep the times), as a `::notice`: what is slow on a runner is as hard to find in a log as what failed. Nowhere
else is anything changed.
"""
from __future__ import annotations

import functools
import os
import re
import unittest
from typing import Iterable

LIMIT = 10  # the error annotations that GitHub shows for one step
NAMES = 6  # the tests that are named for a group
SAMPLE = 2400  # the characters of the first traceback of a group
SLOW = 12  # the slowest tests that are named when a run failed
_EXCEPTION = re.compile(r"[A-Za-z_][\w.]*(?:: .*|:)?")  # `AssertionError: 1 != 2`, `KeyError: 'x'`, `StopIteration`


def _data(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _property(text: str) -> str:
    return _data(text).replace(":", "%3A").replace(",", "%2C")


def _what_went_wrong(trace: str) -> str:
    """The line of the exception that a traceback ends with: the lines that follow it (the rest of a message, a diff) are not it."""
    lines = trace.strip().splitlines()
    for line in reversed(lines):
        if _EXCEPTION.fullmatch(line):
            return line
    return lines[-1] if lines else ""


def annotations(
    failures: Iterable[tuple[unittest.TestCase, str]],
    errors: Iterable[tuple[unittest.TestCase, str]],
    durations: Iterable[tuple[str, float]] = (),
) -> list[str]:
    """The workflow commands for the failures and the errors of a run: one for each thing that went wrong, at most `LIMIT`; and, when
    something went wrong and the times of the tests are known, one that names the `SLOW` slowest."""
    groups: dict[str, list[tuple[str, str]]] = {}
    for kind, found in (("FAIL", failures), ("ERROR", errors)):
        for test, trace in found:
            groups.setdefault(f"{kind}: {_what_went_wrong(trace)}", []).append((test.id(), trace.strip()))
    commands = []
    for title, tests in list(groups.items())[:LIMIT]:
        names = ", ".join(name for name, _ in tests[:NAMES]) + (f" and {len(tests) - NAMES} more" if len(tests) > NAMES else "")
        message = f"{len(tests)} test(s): {names}\n\n{tests[0][1][-SAMPLE:]}"
        commands.append(f"::error title={_property(title[:150])}::{_data(message)}")
    slowest = sorted(durations, key=lambda item: item[1], reverse=True)[:SLOW]
    if commands and slowest:
        title = f"The {len(slowest)} slowest tests"
        listing = "\n".join(f"{seconds:7.2f} s  {name}" for name, seconds in slowest)
        commands.append(f"::notice title={_property(title)}::{_data(listing)}")
    return commands


def install() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    original = unittest.TextTestResult.printErrors

    @functools.wraps(original)
    def print_errors(self: unittest.TextTestResult) -> None:
        original(self)
        try:
            for command in annotations(self.failures, self.errors, getattr(self, "collectedDurations", ())):
                print(command, flush=True)
        except Exception:  # noqa: BLE001 - a report that cannot be made must not hide the failures that it is about
            pass

    unittest.TextTestResult.printErrors = print_errors  # type: ignore[method-assign]
