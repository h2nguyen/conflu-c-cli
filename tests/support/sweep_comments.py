"""The sweep lines of the comments of a page: reading one, editing one, resolving and filtering: see sweeps.py. Each module runs its lines in order against a mock of its own.

The mock starts with the comments 4001 (a footer comment of the user of the token), 4002 (its answer) and 4003 (an inline comment, open) on page 2002.
The versions in the guards follow from the lines before them: 4001 is at version 1 until the first change of its text, 4003 at 1 until its text changes,
at 2 after that, at 3 when it is resolved and at 4 when it is opened again."""
from __future__ import annotations

from .sweeps import line

LINES = (
    # the list with its filters
    line("comments", "2002", "--inline", "--since", "2026-10-01", "--last", "5"),
    line("comments", "2002", "--resolution", "open", "--with-users"),
    line("comments", "2002", "--inline", "--select", "id,authorRef,byMe", "--list-format", "tsv"),
    line("comments", "2003"),
    line("comments", "2002", "--format", "text"),
    line("comments", "2002", "--inline", "--format", "storage"),
    line("comments", "2002", "--since", "5000w", "--json"),
    # one comment: a footer comment is found by the first request, an inline comment by the second
    line("comment", "2002", "--get", "4001"),
    line("comment", "2002", "--get", "4003", "--with-users"),
    line("comment", "2002", "--get", "4002", "--format", "storage", "--json"),
    line("comment", "2002", "--get", "9999", code=4),
    line("comment", "2003", "--get", "4001", code=4),  # a comment of another page is none
    line("comment", "2002", "--get", "4001/../4003", code=1),  # not an id: nothing is asked
    # a change of the text, previewed first. `--force` is for the mock of the privacy sweep, whose comments all hold an address that Markdown cannot say: without it
    # these lines would be refused there and the sweep would never see what they print
    line("comment", "2002", "--edit", "4001", "--text", "Looks good to me.", "--dry-run", "--force"),
    line("comment", "2002", "--edit", "4001", "--text", "Looks good to me.", "--if-version", "1", "--force"),
    line("comment", "2002", "--edit", "4001", "--text", "Looks good to me.", "--if-version", "1", "--force", code=3),  # it is at version 2 now: the guard refuses
    line("comment", "2002", "--edit", "4001", "--text", "Looks good to me.", "--if-unchanged-since", "2026-10-03T00:00:00Z", "--force", code=3),
    line("comment", "2002", "--edit", "4001", "--text", "Looks good to me.", "--force"),  # the text it has: nothing is sent
    line(
        "comment", "2002", "--edit", "4003", "--file", "{work}/edit.md", "--if-unchanged-since", "2026-10-03T09:00:00Z", "--force",
        files=(("edit.md", "Check this phrase again.\n"),),
    ),
    line("comment", "2002", "--edit", "4002", "--file", "-", "--dry-run", "--force", stdin="From a pipe.\n"),
    line("comment", "2002", "--edit", "4002", "--format", "storage", "--text", "<p>In storage format.</p>"),
    line("comment", "2002", "--edit", "4001", "--text", "Write to [email].", code=1),  # what a reading put in place of an address
    line("comment", "2002", "--edit", "4001", "--text", "  ", code=1),
    line("comment", "2002", "--edit", "4001", code=2),  # no text
    # an inline comment is resolved and opened again
    line("comment", "2002", "--resolve", "4003", "--dry-run"),
    line("comment", "2002", "--resolve", "4003", "--if-version", "2"),
    line("comment", "2002", "--resolve", "4003"),  # resolved already: nothing is sent
    line("comment", "2002", "--reopen", "4003", "--dry-run"),
    line("comment", "2002", "--reopen", "4003", "--dry-run", "--with-users"),  # the request as it is, with the people in the text
    line("comment", "2002", "--reopen", "4003", "--if-version", "3", "--if-unchanged-since", "2026-10-30T00:00:00Z"),
    line("comment", "2002", "--resolve", "4001", code=2),  # a footer comment cannot be resolved
    line("comment", "2002", "--get", "4003", "--edit", "4003", "--text", "x", code=2),
    # adding, with the dry run and the answer to a comment
    line("comment", "2002", "--text", "Added by the sweep.", "--dry-run"),
    line("comment", "2002", "--text", "An answer.", "--reply-to", "4002"),
)
