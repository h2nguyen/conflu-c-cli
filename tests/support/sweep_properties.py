"""The sweep lines of the content properties of pages and other content: see sweeps.py. Each module runs its lines in order against a mock of its own.

The mock starts with properties on the page 2002 (one of them, `team.review`, has people and an address in its value), on the page 2003 (a value that is long), and on
one piece of content of every other kind: the blog post 7390, the folder 7391, the whiteboard 7392, the database 7393, the smart link 7394, the attachment att5001
and the comments 4001 (a footer comment) and 4003 (an inline comment). Each kind has a collection of its own in the REST API, so each kind is read and written once.

`PREPARE` makes the mock refuse four requests with HTTP 403, each once, and the explanation of each holds the address of a person, as Confluence's can: the list of
the properties of the page 2005 (twice: for `properties` and for the read that `property-set` starts with), the creation of a property on it, and the change of the
property 7301 of the page 2002. The four lines that meet them stand first, in this order, and no other line names the page 2005 or changes the property 7301."""
from __future__ import annotations

from typing import Any

from .sweeps import line

REFUSAL = {"errors": [{"status": 403, "code": "FORBIDDEN", "title": "Forbidden", "detail": "alex@example.com may not see or change the properties"}]}


def prepare(mock: Any) -> None:
    mock.fail_next("/api/v2/pages/2005/properties", 403, times=2, method="GET", body=REFUSAL)  # the list: of `properties`, then of `property-set`
    mock.fail_next("/api/v2/pages/2005/properties", 403, method="POST", body=REFUSAL)  # the creation that this account may not make
    mock.fail_next("/api/v2/pages/2002/properties/7301", 403, method="PUT", body=REFUSAL)  # the change that it may not make


PREPARE = prepare

KINDS = ("2002", "7390", "7391", "7392", "7393", "7394", "att5001", "4001", "4003")  # a page, a blog post, a folder, a whiteboard, a database, a smart link, an attachment, two comments
HIDDEN_FORM = '{"status":"closed","reviewer":{"hidden":true},"owners":["[hidden]"],"note":"Ask [email]"}'  # `team.review` as `properties` shows it without people, and changed
CUT_COPY = '"the beginning of a value[value cut]"'  # what `properties` shows of a value that it cut, as a JSON text

LINES = (
    # what Confluence refuses with HTTP 403, and says an address in its explanation: a list, the read of `property-set`, a creation and a change (see PREPARE; they stand first)
    line("properties", "2005", code=5),
    line("property-set", "2005", "--key", "note", "--value", '"first"', code=5),
    line("property-set", "2005", "--key", "note", "--value", '"first"', code=5),
    line("property-set", "2002", "--key", "editor", "--value", '"v3"', code=5),
    # the properties of a page: a piece, the next piece, all of them, one key, cut and whole
    line("properties", "2002"),
    line("properties", "2002", "--limit", "1", "--cursor", "1"),
    line("properties", "2002", "--all", "--json"),
    line("properties", "2002", "--key", "team.review"),
    line("properties", "2002", "--key", "team.review", "--json"),
    line("properties", "2002", "--key", "nothing.here"),
    line("properties", "2003", "--max-chars", "100"),
    line("properties", "2003", "--max-chars", "0", "--json"),
    line("properties", "2002", "--with-users"),
    line("properties", "2002", "--key", "team.review", "--with-users", "--json"),
    # every other kind of content, each in its own collection
    *(line("properties", holder) for holder in KINDS[1:]),
    # what is refused
    line("properties", "99999", code=4),
    line("properties", "att99999", code=4),
    line("properties", "not-an-id", code=1),
    line("properties", "7001"),  # a folder of the structure area: nobody set a property on it, and the list is empty
    # a value is read first, then created or saved: the dry run, the creation, the same value again, the next version, a guard that is right and one that is wrong
    line("property-set", "2002", "--key", "team.review", "--value", '{"status":"closed"}', "--dry-run"),
    # what a reading shows in the place of people is not written back over them: refused in a dry run and in a real run, and nothing is sent
    line("property-set", "2002", "--key", "team.review", "--value", HIDDEN_FORM, "--dry-run", code=1),
    line("property-set", "2002", "--key", "team.review", "--value", HIDDEN_FORM, code=1),
    line("property-set", "2002", "--key", "sweep.note", "--value", '"first"', "--dry-run", "--json"),
    line("property-set", "2002", "--key", "sweep.note", "--value", '"first"', "--message", "ignored for a new property"),
    line("property-set", "2002", "--key", "sweep.note", "--value", '"first"'),
    line("property-set", "2002", "--key", "sweep.note", "--value", '{"second":[1,2,3]}', "--if-version", "1", "--message", "Second"),
    line("property-set", "2002", "--key", "sweep.note", "--value", "true", "--if-version", "1", code=3),
    line("property-set", "2002", "--key", "sweep.note", "--file", "{work}/value.json", "--json", files=(("value.json", '{"from": "a file", "n": 3}\n'),)),
    line("property-set", "2002", "--key", "sweep.note", "--file", "-", "--dry-run", stdin="[1, 2, 3]"),
    line("property-set", "2002", "--key", "never.there", "--value", "null", "--if-version", "0"),
    # every kind of content takes a property of its own
    *(line("property-set", holder, "--key", "sweep.kind", "--value", '{"kind":"%s"}' % holder) for holder in KINDS),
    *(line("property-set", holder, "--key", "sweep.kind", "--value", '{"kind":"again"}', "--json") for holder in KINDS),
    # what is refused before anything is sent
    line("property-set", "2002", "--key", "bad key", "--value", "1", code=2),
    line("property-set", "2002", "--key", "sweep.note", "--value", "word", code=2),
    line("property-set", "2002", "--key", "sweep.note", "--value", "1e999", code=2),
    line("property-set", "2002", "--key", "sweep.note", code=2),
    line("property-set", "2002", "--key", "sweep.note", "--value", "1", "--file", "-", code=2),
    line("property-set", "99999", "--key", "sweep.note", "--value", "1", code=4),
    # a value that a reading cut ends in its mark and is not the value either: refused for a property that is there (in a dry run first) and for a new one; the whole value is read with no cut
    line("properties", "2003", "--key", "inventory", "--with-users", "--max-chars", "0", "--json"),
    line("property-set", "2003", "--key", "inventory", "--value", CUT_COPY, "--dry-run", code=1),
    line("property-set", "2003", "--key", "inventory", "--value", CUT_COPY, code=1),
    line("property-set", "2002", "--key", "sweep.copy", "--value", CUT_COPY, code=1),
)
