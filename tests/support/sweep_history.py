"""The sweep lines of earlier versions of a page, the difference between two of them, and restoring one: see sweeps.py. Each module runs its lines in order against a mock of its own.

The page 2002 has three versions in the mock (the first two with a body of their own, see `mock_history.py`); a restore makes a fourth and a fifth."""
from __future__ import annotations

from .sweeps import line

LINES = (
    line("page", "2002", "--version", "1"),
    line("page", "2002", "--version", "2", "--attachments", "--outline"),
    line("page", "2002", "2003", "2004", "--outline"),  # one request for the three
    line("page", "2002", "999", "--no-body", code=4),  # the one that is not there is asked for on its own
    line("page", "2002", "--attachments", "--no-body"),
    line("page", "7001", code=4),  # the id of a folder: the answer names what it is
    line("create", "--title", "Swept below a folder", "--space", "ENG", "--parent", "7001", "--body", "Text."),  # 20000
    line("page", "20000", "--ancestors", "--no-body"),  # the folder in the path has no title in the answer of the ancestors: it is asked for
    line("page", "2005", "--ancestors", "--no-body"),
    line("diff", "2002"),
    line("diff", "2002", "--from", "1", "--to", "2", "--context", "0"),
    line("diff", "2005"),  # one version only: nothing to compare
    line("restore", "2002", "--version", "1", "--dry-run"),
    line("restore", "2002", "--version", "2", "--message", "Swept", "--if-version", "3"),
    line("restore", "2002", "--version", "1", "--restore-title"),
)
