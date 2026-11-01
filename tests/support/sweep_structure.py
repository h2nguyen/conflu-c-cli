"""The sweep lines of folders, whiteboards, databases and smart links, and where content sits in the tree: see sweeps.py. Each module runs its lines in order against a mock of its own.

The mock starts with the folders, whiteboard, database and smart link of `mock_structure.py` (ids 7001 to 7061) and no page below them; what is
made here (folders 7090 and up, pages from 20000) is made by lines that stand before the lines that read it.

It also has a personal space (`PREPARE`), which is keyed by `~` and the account id of its owner: the last lines read, tree, export, move, create and
change what is in it, and the privacy sweep fails when a key, an address with the key in it or the account id comes out of one of them."""
from __future__ import annotations

from typing import Any

from .mock_structure import StructureRoutes
from .sweeps import line

PERSONAL = "~5b10ac8d82e05b22cc7d4ef5"
# What `prepare` makes: the home page of the space is 20000, then a page with two versions, a folder below the home page (outside the ids that the
# mock hands out for new folders, 7090 to 7099) and a page in the folder.
PERSONAL_PAGE, PERSONAL_FOLDER, PERSONAL_BELOW = "20001", "7071", "20002"


def prepare(mock: Any) -> None:
    """A personal space with a page, a folder and a page below it. It is no part of the default data of the mock, which other tests count. Its home page
    has a title of its own: Confluence titles the home page of a personal space with the name of its owner, and no line could print that."""
    space = mock._space_by_key(PERSONAL)
    space_id = space["id"] if space else mock.add_space(PERSONAL, "Alex Example", "personal")
    home = mock.spaces[space_id]["homepageId"]
    mock.pages[home]["title"] = "Start"
    page = mock.add_page(PERSONAL, "Personal notes", "<p>Notes.</p>", parent_id=home, versions=2)
    folder = mock.area(StructureRoutes).add("folder", PERSONAL_FOLDER, "Personal archive", home, space_id=space_id)
    below = mock.add_page(PERSONAL, "Personal old notes", "<p>Old.</p>", parent_id=folder["id"])
    if (page, below) != (PERSONAL_PAGE, PERSONAL_BELOW):
        raise RuntimeError(f"The ids of the personal space are {page} and {below}, not {PERSONAL_PAGE} and {PERSONAL_BELOW}: the lines below name them")


PREPARE = prepare

LINES = (
    line("folder", "7001", "--children", "--ancestors"),
    line("folder", "7011", "--ancestors"),
    line("whiteboard", "7021", "--children", "--ancestors"),
    line("database", "7041", "--fields"),
    line("database", "7041", "--views"),
    line("database", "7041", "--entries", "--all", "--with-users"),
    line("database", "7041", "--children"),
    line("database", "7041", "--ancestors"),
    line("smartlink", "7061", "--children", "--ancestors"),
    line("folder", "2002", code=4),  # the id of a page: the answer names what it is
    line("folder-create", "--title", "Swept folder", "--space", "ENG", "--dry-run"),
    line("folder-create", "--title", "Swept folder", "--space", "ENG", "--parent", "7001"),  # 7090
    line("folder-create", "--title", "Swept below a folder", "--space", "ENG", "--parent", "7090", "--dry-run"),
    line("folder-create", "--title", "Swept below a folder", "--space", "ENG", "--parent", "7090"),  # 7091
    line("smartlink-create", "--url", "https://example.com/swept", "--title", "Swept link", "--space", "ENG", "--dry-run"),
    line("smartlink-create", "--url", "https://example.com/swept", "--title", "Swept link", "--space", "ENG", "--parent", "7090"),  # 7092
    # pages below a folder: create, import-md and import-md-dir name the parent by its id, which may be that of a folder
    line("create", "--title", "Swept below a folder", "--space", "ENG", "--parent", "7001", "--body", "Text.", "--dry-run"),
    line("create", "--title", "Swept below a folder", "--space", "ENG", "--parent", "7001", "--body", "Text."),
    line("create", "--title", "Swept below a database", "--space", "ENG", "--parent", "7041", "--body", "Text."),
    line("import-md", "{work}/note.md", "--space", "ENG", "--parent", "7090", files=(("note.md", "# Swept note\n\nText.\n"),)),
    line("import-md-dir", "{work}/md", "--space", "ENG", "--parent", "7091", files=(("md/a.md", "# Swept A\n\ntext\n"), ("md/b.md", "# Swept B\n\ntext\n"))),
    line("tree", "7001", "--depth", "4"),
    line("tree", "7041"),
    line("tree", "7021"),
    line("tree", "7061"),
    line("export", "--page", "7001", "--out", "{work}/folder-export"),
    # a page below a folder: the version that the move saves, and a move that is none
    line("move", "2005", "--to", "7001", "--dry-run"),
    line("move", "2005", "--to", "7001"),
    line("move", "2005", "--to", "7001"),
    line("move", "7001", "--to", "2003", code=1),  # a folder cannot be moved
    line("create", "--title", "Not below a comment", "--space", "ENG", "--parent", "4001", code=1),
    # the personal space (see PREPARE): read, tree, export, move, create and change what is in it
    line("page", PERSONAL_PAGE),
    line("page", PERSONAL_PAGE, "--json"),
    line("tree", PERSONAL_PAGE),
    line("tree", PERSONAL_FOLDER, "--json"),
    line("folder", PERSONAL_FOLDER, "--children", "--ancestors"),
    line("folder", PERSONAL_FOLDER, "--json"),
    line("folder", PERSONAL_FOLDER, "--with-users"),  # as Confluence names it, which the strict policy refuses
    line("export", "--space", PERSONAL, "--out", "{work}/personal-space"),
    line("export", "--page", PERSONAL_PAGE, "--out", "{work}/personal-page", "--json"),
    line("export", "--page", PERSONAL_FOLDER, "--out", "{work}/personal-folder"),
    line("update", PERSONAL_PAGE, "--title", "Personal notes (swept)", "--dry-run"),
    line("update", PERSONAL_PAGE, "--title", "Personal notes (swept)"),
    line("update", PERSONAL_PAGE, "--title", "Personal notes (swept again)", "--json"),
    line("restore", PERSONAL_PAGE, "--version", "1", "--dry-run"),
    line("move", PERSONAL_BELOW, "--to", PERSONAL_PAGE, "--dry-run", "--json"),
    line("move", PERSONAL_BELOW, "--to", PERSONAL_PAGE),
    line("move", PERSONAL_PAGE, "--to", PERSONAL_FOLDER, "--dry-run"),
    line("move", PERSONAL_PAGE, "--to", PERSONAL_FOLDER, "--json"),
    line("folder-create", "--title", "Personal swept folder", "--space", PERSONAL, "--dry-run"),
    line("folder-create", "--title", "Personal swept folder", "--space", PERSONAL, "--parent", PERSONAL_FOLDER),
    line("smartlink-create", "--url", "https://example.com/personal", "--title", "Personal link", "--space", PERSONAL, "--parent", PERSONAL_FOLDER, "--json"),
    line("create", "--title", "Personal swept page", "--space", PERSONAL, "--parent", PERSONAL_FOLDER, "--body", "Text."),
    line("import-md", "{work}/personal.md", "--space", PERSONAL, "--parent", PERSONAL_FOLDER, files=(("personal.md", "# Personal imported\n\nText.\n"),)),
    line("import-md-dir", "{work}/personal-md", "--space", PERSONAL, files=(("personal-md/a.md", "# Personal A\n\ntext\n"),)),
    # the lists of a folder, a whiteboard, a smart link and a database: the second piece (the cursor belongs to the --limit that made it), the columns, and the people
    line("folder", "7001", "--children", "--limit", "1"),
    line("folder", "7001", "--children", "--limit", "1", "--cursor", "1"),
    line("folder", "7001", "--children", "--all", "--select", "id,type,title", "--format", "tsv"),
    line("create", "--title", "Swept below a whiteboard", "--space", "ENG", "--parent", "7021", "--body", "Text."),
    line("create", "--title", "Swept again below a whiteboard", "--space", "ENG", "--parent", "7021", "--body", "Text."),
    line("create", "--title", "Swept below a smart link", "--space", "ENG", "--parent", "7061", "--body", "Text."),
    line("create", "--title", "Swept again below a smart link", "--space", "ENG", "--parent", "7061", "--body", "Text."),
    line("whiteboard", "7021", "--children", "--limit", "1", "--cursor", "1"),
    line("whiteboard", "7021", "--children", "--all", "--select", "id,type,title", "--format", "md"),
    line("whiteboard", "7021", "--with-users"),
    line("smartlink", "7061", "--children", "--limit", "1", "--cursor", "1"),
    line("smartlink", "7061", "--children", "--all", "--select", "id,title", "--format", "tsv"),
    line("smartlink", "7061", "--with-users"),
    line("database", "7041", "--entries", "--limit", "1", "--cursor", "1"),
    line("database", "7041", "--fields", "--limit", "1", "--cursor", "1", "--select", "id,name,type", "--format", "tsv"),
    line("database", "7041", "--views", "--select", "id,name,type", "--format", "md"),
    line("tree", "7001", "--depth", "2", "--select", "id,type,title", "--format", "tsv"),
    # the guards of a restore, and of a move that saves the page
    line("restore", PERSONAL_PAGE, "--version", "1", "--if-unchanged-since", "2030-01-01T00:00:00Z", "--dry-run"),
    line("restore", PERSONAL_PAGE, "--version", "1", "--if-unchanged-since", "2020-01-01T00:00:00Z", code=3),
    line("restore", PERSONAL_PAGE, "--version", "1", "--if-unchanged-since", "2030-01-01T00:00:00Z"),
    line("move", "2004", "--to", "7001", "--if-version", "99", code=3),
    line("move", "2004", "--to", "7001", "--with-users", "--dry-run"),  # the request as it is, with the people in the body
    line("move", "2004", "--to", "7001", "--if-version", "2", "--if-unchanged-since", "2030-01-01T00:00:00Z"),
)
