"""The sweep lines of blog posts: see sweeps.py. Each module runs its lines in order against a mock of its own.

The mock starts with the blog posts 7101 to 7105 of `mock_blogposts.py`; a blog post that is created gets the next id of the pages (20000, then 20001 and 20002). The lines that
read 7101 stand before the last two, which replace its body (a mention and a macro are in it), and the lines with `--with-users` are refused under the strict policy of the privacy sweep."""
from __future__ import annotations

from .sweeps import line

LINES = (
    line("blogposts", "--space", "ENG", "--all"),
    line("blogposts", "--space", "ENG", "--title", "Weekly update", "--sort", "created-date", "--desc"),
    line("blogposts", "--sort", "modified-date", "--limit", "2"),  # the whole site: no space is asked for
    line("blogposts", "--space", "ENG", "--limit", "1", "--cursor", "1", "--select", "id,title,status", "--format", "tsv"),  # the second piece of the list, shaped for a script
    line("blogposts", "--space", "ENG", "--status", "trashed"),
    line("blogpost", "7101", "--comments", "--with-users"),  # the footer comments and the inline ones, the replies of each, and the names of the people
    line("blogpost", "7101", "--outline"),
    line("blogpost", "7101", "--section", "Known issues"),  # one part of the body
    line("blogpost", "7101", "--max-chars", "60"),  # cut at the end of a paragraph, and the answer says so
    line("blogpost", "7102", "--no-body"),
    line("blogpost", "7101", "--body-only", "--out", "{work}/post.md"),  # the body into a file, as `page --body-only --out` does: the privacy sweep reads the file
    line("blogpost", "7101", "--body-only", "--out", "{work}/post.md", code=1),  # the file is there
    line("blogpost", "7101", "--body-only", "--out", "{work}/post.md", "--force"),
    line("blogpost", "2002", code=4),  # the id of a page: the answer names what it is
    line("blogpost-create", "--space", "ENG", "--title", "Swept post", "--body", "Text.", "--labels", "swept", "--dry-run"),
    line("blogpost-create", "--space", "ENG", "--title", "Swept post", "--body", "Text.", "--labels", "swept,news"),  # 20000
    line("blogpost-create", "--space", "ENG", "--title", "Swept from a file", "--file", "{work}/create.md", files=(("{work}/create.md", "# Swept heading\n\nText from a file.\n"),)),  # 20001
    line("blogpost-create", "--space", "ENG", "--title", "Swept as storage", "--body", "<p>Raw storage.</p>", "--format", "storage"),  # 20002
    line("blogpost-update", "7102", "--title", "Weekly update (swept)", "--dry-run"),
    line("blogpost-update", "7102", "--title", "Weekly update (swept)", "--if-version", "1"),
    line("blogpost-update", "7102", "--body", "More text.", "--append", "--message", "Swept"),
    line("blogpost-update", "7102", "--title", "Weekly update (guarded)", "--if-unchanged-since", "2030-01-01T00:00:00Z"),  # nobody saved after that time
    line("blogpost-update", "7102", "--title", "Weekly update (late)", "--if-unchanged-since", "2000-01-01T00:00:00Z", code=3),  # somebody did: nothing is sent
    line("blogpost-update", "20000", "--body", "<p>Replaced.</p>", "--format", "storage"),
    line("blogpost-update", "20001", "--file", "{work}/update.md", "--append", "--message", "From a file", files=(("{work}/update.md", "# Added heading\n\nAdded from a file.\n"),)),
    line("blogpost-update", "20001", "--body", "Before.", "--prepend"),
    line("blogpost-update", "7101", "--title", "Release 2026.10 is out (people)", "--dry-run", "--with-users"),  # the payload with the people of the body, as it is sent; refused under CONFLUENCE_HIDE_USERS
    line("blogpost-update", "7101", "--body", "Replaced.", code=1),  # a mention and a macro would be lost
    line("blogpost-update", "7101", "--body", "Replaced on purpose.", "--force"),
)
