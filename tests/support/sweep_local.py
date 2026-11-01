"""The sweep lines of the commands that never ask Confluence (`LOCAL` in sweeps.py): the conformance sweep has no use for them, the JSON sweep has.

The lines of the other areas are in tests/support/sweep_<area>.py. These stand apart so that the conformance and the privacy sweep, which run every module
of tests/support/sweeps_all.py, are what they were; tests/integration/test_json_sweep.py runs them as well. They run in the order they stand, against a
configuration file of their own: the ones that save a setting come before the ones that read it."""
from __future__ import annotations

from .sweeps import line

TOKEN = "sweep-token-0123456789"  # not a credential: the mock accepts whatever it was configured with, and no command prints it

LINES = (
    line("version"),
    line("commands"),
    line("commands", "--format", "json"),
    line("commands", "--format", "mcp", "--only", "all"),
    line("commands", "--group", "Read", code=2),  # --group is for --format mcp
    line("help"),
    line("help", "update"),
    line("help", "--brief"),
    line("help", "no-such-command", code=2),
    line("changelog"),
    line("how-to"),
    line("how-to", "readme"),
    line("how-to", "find-information"),
    line("how-to", "no-such-guide", code=4),
    line("skill"),
    line("skill", "install", "--dir", "{work}/skills", "--dry-run"),
    line("skill", "install", "--dir", "{work}/skills"),
    line("skill", "install", "--dir", "{work}/skills"),
    line("convert", "{work}/note.md", files=(("note.md", "---\ntitle: Converted\n---\n# Heading\n\nText with `code`.\n"),)),
    line("convert", "-", stdin="# Heading\n\nText.\n"),
    line("convert", "--source", "storage", "-", stdin="<h1>Heading</h1><p>Text.</p>"),
    line("convert", "{work}/missing.md", code=1),
    line("config", "path"),
    line("config"),
    line("config", "show"),
    line("config", "set", "CONFLUENCE_RETRY", "3"),
    line("config", "set", "CONFLUENCE_RETRY", code=2),  # a setting needs a value
    line("config", "set", "NO_SUCH_SETTING", "x", code=2),
    line("config", "unset", "CONFLUENCE_RETRY"),
    line("config", "unset", "CONFLUENCE_RETRY"),  # it is not there any more
    line("config", "frobnicate", code=2),
    line("current", code=1),  # no current space: it answers and asks for a non-zero exit code
    line("config", "set", "CONFLUENCE_SPACE", "ENG"),
    line("current"),
    line("clear-space"),
    line("clear-space"),
    line("setup-token", "--stdin", stdin=TOKEN),
    line("remove-token"),
    line("remove-token"),
    # The server of `conflu mcp` talks on standard input and output: one JSON-RPC message per line, never an envelope.
    line("mcp", stdin='{"jsonrpc":"2.0","id":1,"method":"ping"}\n'),
)
