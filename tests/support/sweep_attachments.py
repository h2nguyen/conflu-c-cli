"""The sweep lines of the files attached to a page or a blog post: one attachment with its versions and labels, a version of a file, the text of a document,
the files of a blog post, and what `attach` reads before it writes: see sweeps.py. Each module runs its lines in order against a mock of its own.

Page 2004 holds att5101 (three versions) to att5106, blog post 7102 holds att5111 and att5112 (see tests/support/attachment_data.py). A write comes last: `attach`
gives att5101 a fourth version."""
from __future__ import annotations

from .sweeps import line

LINES = (
    line("attachments", "2004", "--all"),
    line("attachments", "7102", "--all"),  # the id of a blog post: a page is asked for first, then the type of the id, then the blog post's files
    line("attachments", "7102", "--name", "agenda.txt", "--with-users"),
    line("attachments", "7001", code=4),  # the id of a folder: the answer names what it is
    line("attachment", "att5101"),
    line("attachment", "att5101", "--versions", "--labels", "--all"),  # the size of each version is asked for with `?version=N`
    line("attachment", "att5111", "--versions", "--limit", "1", "--with-users"),
    line("download", "att5101", "--version", "2", "--out", "{work}/version"),
    line("download", "att5111", "--out", "{work}/blog-one"),
    line("download", "7102", "--all", "--out", "{work}/blog"),
    line("download", "7102", "--name", "agenda.txt", "--version", "1", "--out", "{work}/blog-version"),
    line("download", "2004", "--all", "--text"),
    line("download", "att5102", "--text", "--max-chars", "40", "--with-users"),
    line("download", "7102", "--all", "--text", "--dry-run"),
    line("download", "att5101", "--version", "9", "--out", "{work}/none", code=4),
    line("attach", "2004", "{work}/plan.txt", "--dry-run", files=(("plan.txt", "A new plan.\n"),)),
    line("attach", "2004", "{work}/leak.txt", "--dry-run", code=2, files=(("leak.txt", "The token is test-token, do not publish it.\n"),)),
    line("attach", "2004", "{work}/plan.txt", "--if-version", "1", code=3, files=(("plan.txt", "A new plan.\n"),)),
    line("attach", "7102", "{work}/plan.txt", code=4, files=(("plan.txt", "A new plan.\n"),)),  # a blog post is no page
    line("attach", "2004", "{work}/plan.txt", "--if-version", "3", "--comment", "Swept", "--minor", files=(("plan.txt", "A new plan.\n"),)),
    # the second piece of a list, the columns of a list, a version that is read up to a size, and the guard by time (att5101 is at version 4 now)
    line("attachments", "2004", "--limit", "1", "--cursor", "1", "--select", "id,title,mediaType", "--format", "tsv"),
    line("attachments", "7102", "--limit", "1", "--cursor", "1"),
    line("attachment", "att5101", "--versions", "--limit", "1", "--cursor", "1", "--select", "number,message", "--format", "tsv"),
    line("attachment", "att5101", "--labels", "--select", "name", "--format", "md"),
    line("download", "att5101", "--version", "2", "--max-bytes", "100000", "--out", "{work}/older"),
    line("download", "att5101", "--version", "2", "--max-bytes", "5", "--out", "{work}/older-small", code=1),
    line("download", "att5101", "--text", "--max-bytes", "5", code=1),
    line("attach", "2004", "{work}/plan.txt", "--if-unchanged-since", "2030-01-01T00:00:00Z", files=(("plan.txt", "Another plan.\n"),)),
    line("attach", "2004", "{work}/plan.txt", "--if-unchanged-since", "2020-01-01T00:00:00Z", code=3, files=(("plan.txt", "Another plan.\n"),)),
)
