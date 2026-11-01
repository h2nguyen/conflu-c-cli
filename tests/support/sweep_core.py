"""The sweep lines of the commands that were there from 1.0.0: pages, spaces, comments, labels, attachments, search, export and import.

The mock of this module has a personal space besides the two of the default data (`PREPARE`, see personal_space.py): it is named after its owner and keyed by the
owner's account id, which `spaces`, `space` and `use` must not print without `--with-users`."""
from __future__ import annotations

from .personal_space import PERSONAL, add_personal_space
from .sweeps import line

PREPARE = add_personal_space

LINES = (
    line("doctor", "--json"),
    line("ping"),
    line("spaces", "--all"),
    line("space", "ENG"),
    # the personal space: masked as it is, and as Confluence names it with --with-users (which the strict policy refuses); a search cannot find its owner by name
    line("spaces", "--type", "personal"),
    line("spaces", "--type", "personal", "--with-users"),
    line("spaces", "--search", "alex", "--all"),
    line("spaces", "--status", "archived"),
    line("spaces", "--limit", "1", "--cursor", "1", "--select", "key,name", "--format", "tsv"),
    line("space", PERSONAL),
    line("space", PERSONAL, "--with-users"),
    line("use", PERSONAL),
    line("use", "ENG"),
    line("pages", "--space", "ENG", "--all"),
    line("pages", "--space", "ENG", "--title", "Release notes"),
    line("pages", "--space", "ENG", "--root"),
    line("pages", "--space", "ENG", "--status", "archived", "--sort", "modified-date", "--desc"),
    line("pages", "--space", "ENG", "--limit", "1", "--all", "--json"),  # every request after the first carries the cursor
    line("pages", "--space", "ENG", "--limit", "1", "--cursor", "1"),  # the second piece of the list
    line("page", "2002", "--comments", "--ancestors"),
    line("page", "2002", "--outline"),
    line("page", "2002", "--body-only", "--out", "{work}/page.md"),
    line("page", "2002", "--body-only", "--out", "{work}/page.md", code=1),  # the file is there
    line("page", "2002", "--body-only", "--out", "{work}/page.md", "--force"),
    line("page", "2002", "--comments", "--with-users"),
    line("tree", "2001", "--depth", "3"),
    line("versions", "2002", "--all"),
    line("versions", "2002", "--limit", "1", "--cursor", "1", "--select", "number,message", "--format", "md"),
    line("diff", "2002", "--from", "1", "--max-chars", "60"),  # cut after the last whole line
    line("search", "release notes", "--space", "ENG", "--snippets", "2"),
    line("search", "release notes", "--space", "ENG", "--limit", "1", "--start", "1"),
    line("search", "--phrase", "release notes", "--phrase", "october", "--space", "ENG", "--select", "id,title", "--format", "tsv"),
    line("search", "--title", "Architecture", "--since", "2026-10-01", "--space", "ENG"),
    line("search", "zzzunknownword", "release", "--match", "auto", "--space", "ENG"),  # no page holds both words: the second request asks for either
    line("search", "zzzunknownword", "release", "--match", "all", "--space", "ENG"),
    line("search", "zzzunknownword", "release", "--match", "any", "--space", "ENG"),
    line("search", "--cql", 'type = page AND space = "ENG"'),
    # The search index lists people and spaces besides pages: without --with-users no person (their names and account ids), and a personal space without the name of its owner.
    line("search", "--cql", 'type = user AND user.fullname ~ "a*"', "--all"),
    line("search", "--cql", "type = space AND space.type = personal", "--all"),
    line("export", "--space", "ENG", "--out", "{work}/space"),
    line("export", "--page", "2003", "--out", "{work}/tree"),
    line("export", "--space", "ENG", "--out", "{work}/space", code=1),  # the files are there
    line("export", "--space", "ENG", "--out", "{work}/space", "--force"),
    line("comments", "2002", "--inline"),
    line("comments", "2002", "--with-users"),
    line("labels", "2002"),
    line("attachments", "2002", "--all"),
    line("download", "2002", "--all", "--out", "{work}/files"),
    line("download", "att5001", "--out", "{work}/one"),
    line("download", "att5001", "--out", "{work}/one", code=1),  # the file is there
    line("download", "att5001", "--out", "{work}/one", "--force"),
    line("download", "att5001", "--out", "{work}/small", "--max-bytes", "5", code=1),  # judged by its size, before it is fetched
    line("download", "att5001", "--out", "{work}/big", "--max-bytes", "100000"),
    line("update", "2002", "--title", "Release notes (swept)"),
    line("update", "2003", "--body", "More text.", "--append", "--message", "Swept"),
    # the text from a file and in storage format, in front of the body, and the guards of an update (the page 2003 is at version 2, and each real line below makes the next one)
    line("update", "2003", "--file", "{work}/update.md", "--message", "From a file", "--force", files=(("update.md", "# Updated\n\nFrom a file.\n"),)),
    line("update", "2003", "--body", "<p>In storage format.</p>", "--format", "storage", "--dry-run"),
    line("update", "2003", "--body", "<p>In storage format.</p>", "--format", "storage"),
    line("update", "2003", "--body", "Front.", "--prepend", "--dry-run"),
    line("update", "2003", "--body", "Front.", "--prepend"),
    line("update", "2003", "--body", "Guarded.", "--append", "--if-version", "5", "--if-unchanged-since", "2030-01-01T00:00:00Z"),
    line("update", "2003", "--body", "Late.", "--append", "--if-version", "5", code=3),  # it is at version 6 now
    line("update", "2003", "--body", "Early.", "--append", "--if-unchanged-since", "2020-01-01T00:00:00Z", code=3),
    # What a dry run shows: the request that would be sent, with the page as it is now (the privacy sweep reads it).
    line("update", "2002", "--body", "More text.", "--append", "--dry-run"),
    line("update", "2002", "--title", "Another title", "--dry-run"),
    line("update", "2002", "--body", "A new body.", "--force", "--dry-run"),
    line("update", "2002", "--body", "More text.", "--append", "--with-users", "--dry-run"),  # the request as it is, with the people in the body
    line("move", "2005", "--to", "2003", "--position", "before", "--dry-run"),
    line("move", "2005", "--to", "2003", "--position", "before"),
    line("move", "2005", "--to", "2003", "--position", "after", "--if-version", "99", code=3),
    line("move", "2005", "--to", "2003", "--position", "after", "--if-version", "1", "--if-unchanged-since", "2030-01-01T00:00:00Z"),
    line("move", "2005", "--to", "2003", "--position", "after", "--if-unchanged-since", "2020-01-01T00:00:00Z", code=3),
    line("move", "2005", "--to", "7001", "--with-users", "--dry-run"),  # below a folder the move saves the page: the request holds its body
    line("comment", "2002", "--text", "Reviewed.", "--dry-run"),
    line("comment", "2002", "--text", "Reviewed."),
    line("comment", "2002", "--text", "A reply.", "--reply-to", "4001"),
    line("label", "2002", "--add", "reviewed", "--remove", "notes", "--dry-run"),
    line("label", "2002", "--add", "reviewed", "--remove", "notes"),
    line("attach", "2002", "{work}/report.txt", "--dry-run", files=(("report.txt", "report"),)),
    line("attach", "2002", "{work}/report.txt", files=(("report.txt", "report"),)),
    line("attach", "2002", "{work}/report.txt", "--if-unchanged-since", "2030-01-01T00:00:00Z", files=(("report.txt", "report"),)),
    line("attach", "2002", "{work}/report.txt", "--if-unchanged-since", "2020-01-01T00:00:00Z", code=3, files=(("report.txt", "report"),)),
    line("create", "--title", "Dry page", "--space", "ENG", "--body", "Text.", "--labels", "swept", "--dry-run"),
    line("create", "--title", "Swept page", "--space", "ENG", "--body", "Text.", "--labels", "swept"),
    line("create", "--title", "Page from a file", "--space", "ENG", "--file", "{work}/new.md", files=(("new.md", "# From a file\n\nText.\n"),)),
    line("create", "--title", "Page in storage format", "--space", "ENG", "--body", "<p>Storage.</p>", "--format", "storage", "--dry-run"),
    line("create", "--title", "Page in storage format", "--space", "ENG", "--body", "<p>Storage.</p>", "--format", "storage"),
    line("import-md", "{work}/note.md", "--space", "ENG", "--dry-run", files=(("note.md", "---\ntitle: Imported by the sweep\n---\nText.\n"),)),
    line("import-md", "{work}/note.md", "--space", "ENG", files=(("note.md", "---\ntitle: Imported by the sweep\n---\nText.\n"),)),
    line("import-md", "{work}/note.md", "--space", "ENG", "--force", files=(("note.md", "---\ntitle: Imported by the sweep\n---\nChanged text.\n"),)),
    line("import-md-dir", "{work}/md", "--space", "ENG", "--dry-run", files=(("md/a.md", "# Sweep A\n\ntext\n"), ("md/b.md", "# Sweep B\n\ntext\n"))),
    line("import-md-dir", "{work}/md", "--space", "ENG", files=(("md/a.md", "# Sweep A\n\ntext\n"), ("md/b.md", "# Sweep B\n\ntext\n"))),
    line("import-md-dir", "{work}/md", "--space", "ENG", "--force", files=(("md/a.md", "# Sweep A\n\nchanged\n"), ("md/b.md", "# Sweep B\n\nchanged\n"))),
    line(
        "import-md-dir", "{work}/mixed", "--space", "ENG", "--continue-on-error", code=1,  # the file without a title fails, and the next one is imported all the same
        files=(("mixed/a-untitled.md", "Just text.\n"), ("mixed/b-titled.md", "# Titled by the sweep\n\nText.\n")),
    ),
    line("api", "GET", "api/v2/pages/2002"),
    line("api", "PUT", "api/v2/pages/2002/title", "--data", '{"status":"current","title":"Raw title"}', "--write"),
    line("api", "PUT", "api/v2/pages/2002/title", "--data", '{"status":"current","title":"Raw title"}', "--write", "--dry-run", "--json"),
    # The one call that is in neither document: the public tenant information, asked for without any credential (see OUTSIDE_THE_REFERENCE).
    # Last, because it saves the gateway address in the configuration file of this sweep.
    line("setup", "--discover", "--dry-run"),
    line("setup", "--discover", "--yes"),
)
