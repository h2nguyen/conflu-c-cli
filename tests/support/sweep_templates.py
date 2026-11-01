"""The sweep lines of the templates of a space: see sweeps.py. Each module runs its lines in order against a mock of its own.

The mock starts with the page templates 7401 (global), 7402, 7403 and 7404 (the space ENG) and 7405 (DOCS), and the blueprint templates 7406 and 7407 (global) and
7408a0b1-c2d3-4e5f-8a6b-7c8d9e0f1a2b (ENG). 7403 has a mention and an address in its body; 7402 and 7404 declare variables. Templates are v1 calls only.

`PREPARE` makes the mock refuse two requests with HTTP 403, each once, and the explanation of each holds the address of a person, as Confluence's can: the first list
of page templates and the template 7498. The two lines that meet them stand first, in this order, and the lines below are not refused: a refusal is made for the first
request of its kind, so a line that is put before them would take one."""
from __future__ import annotations

from typing import Any

from .sweeps import line

BLUEPRINT = "7408a0b1-c2d3-4e5f-8a6b-7c8d9e0f1a2b"
REFUSAL = {"statusCode": 403, "message": "alex@example.com may not see the templates", "reason": "Forbidden"}


def prepare(mock: Any) -> None:
    mock.fail_next("/rest/api/template/7498", 403, method="GET", body=REFUSAL)  # a template that this account may not see
    mock.fail_next("/rest/api/template/page", 403, method="GET", body=REFUSAL)  # the templates of a space that it may not see


PREPARE = prepare

LINES = (
    # what Confluence refuses with HTTP 403, and says an address in its explanation: a list and one template (see PREPARE; they stand first)
    line("templates", "--space", "ENG", code=5),
    line("template", "7498", code=5),
    # the page templates: the global ones, those of a space, a piece, the next piece, all of them, shaped for a script
    line("templates"),
    line("templates", "--all", "--json"),
    line("templates", "--space", "ENG"),
    line("templates", "--space", "eng", "--limit", "1", "--start", "1"),
    line("templates", "--space", "ENG", "--all", "--select", "id,name,description", "--format", "tsv"),
    line("templates", "--space", "DOCS", "--json"),
    # the templates that blueprints provide
    line("templates", "--blueprints"),
    line("templates", "--blueprints", "--space", "ENG", "--all"),
    line("templates", "--blueprints", "--all", "--json"),
    # what is refused: a space that is not there is "not found" (the call for its templates would say HTTP 403 for it, as for a space that may not be seen)
    line("templates", "--space", "NOPE", code=4),
    line("templates", "--space", "E N G", code=1),
    line("templates", "--start", "-1", code=2),
    # one template: in every format, with its variables, a blueprint's, and what is not there
    line("template", "7402"),
    line("template", "7402", "--format", "storage"),
    line("template", "7403", "--format", "text"),
    line("template", "7404", "--json"),
    line("template", "7403", "--json"),
    line("template", BLUEPRINT),
    line("template", BLUEPRINT, "--json"),
    # the body into a file, as `page --body-only --out` does: the privacy sweep reads the file (7403 has a mention and an address in its body)
    line("template", "7403", "--body-only", "--out", "{work}/incident.md"),
    line("template", "7403", "--body-only", "--out", "{work}/incident.md", code=1),  # the file is there
    line("template", "7403", "--body-only", "--out", "{work}/incident.md", "--force"),
    line("template", "99999", code=5),
    line("template", "page", code=1),
    line("template", "../x", code=1),
)
