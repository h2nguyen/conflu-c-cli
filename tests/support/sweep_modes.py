"""The output modes and the failures that the lines of the areas do not reach, for the JSON sweep (tests/integration/test_json_sweep.py) only.

Like sweep_local.py it is not in tests/support/sweeps_all.py, so the conformance and the privacy sweep are what they were. An option that changes what a command
prints (a body for a file or a pipe, a short answer, a cut text, the cheap checks of `doctor`) is as much a part of the promise of JSON as the lines of the areas,
and the JSON sweep runs it. So are the two exit codes that no line of an area ends with, 6 (the server refuses the request) and 7 (nothing answers): their JSON error
is run in every pass. The mock has the default data, as for every module."""
from __future__ import annotations

from .sweeps import line

# Nothing listens on port 1 of this computer. A line that goes there makes no request that the mock sees, so it is never counted as a call; no retry and a short
# connection time keep it quick (a refused connection on Windows takes a second or two to be reported, and the time limit says it first).
UNREACHABLE = (("CONFLUENCE_BASE_URL", "http://127.0.0.1:1"), ("CONFLUENCE_RETRY", "0"), ("CONFLUENCE_CONNECT_TIMEOUT", "0.3"))

LINES = (
    # What wins over --json: the body of a page, a blog post or a template, for a file or a pipe.
    line("page", "2002", "--body-only"),
    line("blogpost", "7101", "--body-only"),
    line("template", "7402", "--body-only"),
    line("page", "2002", "--max-chars", "20"),  # a cut text: the note about it goes to standard error
    line("ping", "--quiet"),
    line("doctor", "--quick"),
    line("doctor", "--quick", "--cached", "10m"),  # reads what the line before saved
    line("doctor", "--strict-privacy", code=1),  # people can be shown: it fails, and it answers all the same
    line("export", "--space", "ENG", "--format", "storage", "--out", "{work}/storage"),
    line("api", "GET", "api/v2/pages", "--param", "limit=1"),
    line("api", "POST", "api/v2/pages", "--data-file", "{work}/body.json", "--write", "--dry-run", files=(("body.json", '{"spaceId":"1","title":"Raw page"}'),)),
    line("skill", "install", "--dir", "{work}/skills", "--force"),
    # Exit code 6, the server understood the request and refuses it (HTTP 400): a query it cannot parse, and a limit above the maximum of the operation.
    line("search", "--cql", "type = page AND (((", code=6),
    line("api", "GET", "api/v2/spaces", "--param", "limit=251", code=6),
    # Exit code 7, nothing answers.
    line("ping", code=7, env=UNREACHABLE),
)
