"""The sweep lines of what the user may do, restrictions on content, and the permissions and roles of a space: see sweeps.py. Each module runs its lines in order against a mock of its own.

The mock starts with the content of `data_access.py` (ids 7501 to 7551: a folder, a blog post, a whiteboard, a database, a smart link and a piece of custom
content), a restricted page (2002), a page that this account may read and comment on and not change (2003), and the permission and the role model of ENG.
It has a personal space besides (`PREPARE`, see personal_space.py): named after its owner and keyed by the owner's account id. The three commands that
name a space (`permissions`, `space-access` and, though it belongs to the watches, `watching`/`watch`) print it as `privacy.hide_space` says, and no more.
"""
from __future__ import annotations

from .personal_space import PERSONAL, add_personal_space
from .sweeps import line

PREPARE = add_personal_space

LINES = (
    # what this account may do: one line for each kind that has its own collection, then a space
    line("permissions", "2002"),
    line("permissions", "2003", "--only", "update,delete,read"),
    line("permissions", "7501", "--json"),  # a folder
    line("permissions", "7511"),  # a blog post
    line("permissions", "7521"),  # a whiteboard
    line("permissions", "7531"),  # a database
    line("permissions", "7541"),  # a smart link
    line("permissions", "7551"),  # custom content
    line("permissions", "4001"),  # a footer comment
    line("permissions", "4003"),  # an inline comment
    line("permissions", "att5001"),  # an attachment: its id says what it is
    line("permissions", "https://example.atlassian.net/wiki/spaces/ENG/pages/2002/Release+notes", "--only", "update"),
    line("permissions", "--space", "ENG"),
    line("permissions", "--space", "ENG", "--only", "create,export", "--json"),
    line("permissions", "99999", code=4),
    line("permissions", "--space", "NOSUCH", code=4),
    # the restriction on content, and the direct permissions that go with it
    line("restrictions", "2002"),
    line("restrictions", "2002", "--with-users", "--all"),
    line("restrictions", "2002", "--with-users", "--limit", "2", "--json"),
    line("restrictions", "2002", "--with-users", "--limit", "1", "--cursor", "1"),  # the second piece of the principals
    line("restrictions", "2002", "--with-users", "--select", "principalType,principalId", "--format", "tsv"),
    line("restrictions", "2003", "--with-users"),
    line("restrictions", "2001"),  # open
    line("restrictions", "7501", "--with-users"),  # a folder
    line("restrictions", "7511"),  # a blog post
    line("restrictions", "7521"),  # a whiteboard
    line("restrictions", "7531"),  # a database
    line("restrictions", "7541", code=1),  # a smart link has no restriction of its own
    line("restrictions", "4001", code=1),  # a comment has none either
    line("restrictions", "2002", "--with-users", env=(("CONFLUENCE_HIDE_USERS", "true"),), code=1),
    # who may use a space: the site is in the transition, so both models are read
    line("space-access", "ENG"),
    line("space-access", "ENG", "--with-users", "--all"),
    line("space-access", "ENG", "--with-users", "--limit", "4", "--select", "model,principalType,principalId", "--format", "tsv"),
    line("space-access", "ENG", "--with-users", "--limit", "1", "--cursor", "1"),
    line("space-access", "DOCS", "--json"),
    line("space-access", "NOSUCH", code=4),
    # a personal space: `[hidden]` and `[personal space]` in every command that names a space; --with-users shows it as Confluence names it, and the strict policy refuses that
    line("permissions", "--space", PERSONAL),
    line("space-access", PERSONAL),
    line("space-access", PERSONAL, "--json"),
    line("space-access", PERSONAL, "--with-users"),
    line("watching", "--space", PERSONAL),
    line("watch", "--space", PERSONAL, "--dry-run"),
    line("watch", "--space", PERSONAL, "--json"),
    line("watch", "--space", PERSONAL, "--remove"),
)
