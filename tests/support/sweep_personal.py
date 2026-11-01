"""The sweep lines of what lies in a personal space: see sweeps.py. Each module runs its lines in order against a mock of its own.

A personal space is keyed by `~` and the account id of its owner and named after them (see personal_space.py), so the key, the name, an address with the key in
it and a path made from either are a person, and the privacy sweep fails when the account id or the name comes out of any line below. The mock has, below the
home page of the space (20000, titled `Start`): a page (20001) with three versions, a label, two footer comments and an inline one, a file (att50000) with two
versions, and a property; a page below it (20002); a blog post (7191) with a label, a comment, a file and a property; and a folder, a whiteboard, a database and
a smart link; two tasks (7207 on the page, 7208 in the blog post) and two templates in the space (7409 a page template that links to the page, 7410 a blueprint's). A page of the
space ENG (20003) links into the personal space in every way that a body can: to a page, to a blog post, to the space, by its address and from a macro. Each kind is read
by every command that can print where it is; the dry runs of the writes come last (the real ones, which name the same places, are in the sweeps of their areas, and in
`sweep_structure` for pages).

`PREPARE` makes the mock refuse three requests with HTTP 403, each once, and the explanation of each holds the address of a person, as Confluence's can: the first read
of the list of tasks and the first reads of the lists of page templates and of blueprint templates. The lines that meet them stand first among the lines of their
commands (`tasks --space`, `templates --space`, `templates --blueprints --space`), and the message of the two about the templates names the space.
"""
from __future__ import annotations

from typing import Any

from .attachment_data import Edition
from .mock_attachments import AttachmentsRoutes
from .mock_blogposts import BlogpostsRoutes
from .mock_properties import PropertiesRoutes
from .mock_structure import StructureRoutes
from .mock_tasks import TasksRoutes
from .mock_templates import TemplatesRoutes
from .personal_space import PERSONAL, add_personal_space
from .sweeps import line

SPACE_ID, HOME = "10000", "20000"
PAGE, BELOW, LINKING, BLOGPOST = "20001", "20002", "20003", "7191"
FOOTER, INLINE, REPLY, BLOGPOST_COMMENT = "40010", "40011", "40012", "40013"
ATTACHMENT, BLOGPOST_ATTACHMENT = "att50000", "att50001"
FOLDER, WHITEBOARD, DATABASE, SMARTLINK = "7081", "7082", "7083", "7084"
TASK, POST_TASK = "7207", "7208"
TEMPLATE, BLUEPRINT_TEMPLATE = "7409", "7410"
PROPERTY_KEY = "note.state"
RETROSPECTIVE = "com.atlassian.confluence.plugins.confluence-software-blueprints:retrospectives-blueprint"
TASKS_REFUSAL = {"errors": [{"status": 403, "code": "FORBIDDEN", "title": "Forbidden", "detail": "alex@example.com may not see the tasks"}]}
TEMPLATES_REFUSAL = {"statusCode": 403, "message": "alex@example.com may not see the templates", "reason": "Forbidden"}

PAGE_LINK = f'<ac:link><ri:page ri:space-key="{PERSONAL}" ri:content-title="Personal notes" /><ac:plain-text-link-body><![CDATA[the notes]]></ac:plain-text-link-body></ac:link>'
LINKS = (
    f"<p>See {PAGE_LINK}, "
    f'<ac:link><ri:page ri:space-key="{PERSONAL}" ri:content-title="Personal old notes" /></ac:link>, '
    f'<ac:link><ri:blog-post ri:space-key="{PERSONAL}" ri:content-title="Personal news" ri:posting-day="2026/10/12" /></ac:link> and '
    f'<ac:link><ri:space ri:space-key="{PERSONAL}" /></ac:link>.</p>'
    f'<p>Also <a href="https://example.atlassian.net/wiki/spaces/{PERSONAL}/pages/{PAGE}/Personal+notes">the same page</a>.</p>'
    f'<ac:structured-macro ac:name="include" ac:schema-version="1"><ac:parameter ac:name="">{PAGE_LINK}</ac:parameter></ac:structured-macro>'
)


def prepare(mock: Any) -> None:
    """The personal space with one thing of every kind that a command reads, and the ids that the lines below name (the mock hands out the next free one)."""
    space_id, home = add_personal_space(mock)
    page = mock.add_page(PERSONAL, "Personal notes", f"<h1>Notes</h1><p>Notes of the owner, with {PAGE_LINK}.</p>", parent_id=home, labels=("diary",), versions=3)
    mock.pages[page]["versions"][0]["body"] = "<p>First notes.</p>"
    mock.pages[page]["versions"][1]["body"] = "<h1>Notes</h1><p>Notes of the owner.</p>"
    below = mock.add_page(PERSONAL, "Personal old notes", "<p>Old notes.</p>", parent_id=page)
    linking = mock.add_page("ENG", "Links into a personal space", LINKS, parent_id="2001")
    blogposts = mock.area(BlogpostsRoutes)
    post = blogposts.add_blogpost(PERSONAL, "Personal news", "<p>News of the owner.</p>", labels=("diary",), versions=2, blogpost_id=BLOGPOST)
    footer = mock.add_comment(page, f"<p>See {PAGE_LINK}.</p>")
    inline = mock.add_comment(page, "<p>Check this phrase.</p>", kind="inline")
    reply = mock.add_comment(page, "<p>Done.</p>", parent_id=footer)
    post_comment = blogposts.add_comment(post, "<p>Good news.</p>")
    files = mock.area(AttachmentsRoutes)
    attachment = files.add_attachment(page, "notes.txt", (Edition(b"hello notes\n"), Edition(b"hello again\n", message="Second")), "text/plain", labels=("diary",))
    post_attachment = files.add_attachment(post, "agenda.txt", (Edition(b"agenda\n"),), "text/plain")
    properties = mock.area(PropertiesRoutes)
    properties.add_property("pages", page, PROPERTY_KEY, {"state": "draft"})
    properties.add_property("blogposts", post, PROPERTY_KEY, "draft")
    structure = mock.area(StructureRoutes)
    structure.add("folder", FOLDER, "Personal archive", home, space_id=space_id)
    structure.add("whiteboard", WHITEBOARD, "Personal sketch", home, space_id=space_id)
    structure.add("database", DATABASE, "Personal list", home, space_id=space_id)
    structure.add("embed", SMARTLINK, "Personal link", home, space_id=space_id, embed_url="https://example.com/personal")
    tasks = mock.area(TasksRoutes)
    task = tasks.add_task("Call the owner", page_id=page, storage=f"<span>Call the owner, see {PAGE_LINK}</span>", due="2026-11-30T00:00:00.000Z")
    post_task = tasks.add_task("Announce the news", blogpost_id=post)
    tasks.tasks[post_task]["spaceId"] = space_id  # the mock puts the tasks of a blog post into ENG
    templates = mock.area(TemplatesRoutes)
    template = templates.add_template(
        "Personal checklist", f'<h2>Checklist</h2><p>See {PAGE_LINK}</p><p><at:var at:name="topic" /></p>', space_key=PERSONAL, description="Notes of the owner", labels=("diary",)
    )
    blueprint = templates.add_template("Personal retrospective", "<p>Went well</p>", kind="blueprint", space_key=PERSONAL, description="What went well", blueprint=RETROSPECTIVE)
    mock.fail_next("/api/v2/tasks", 403, method="GET", body=TASKS_REFUSAL)  # the first read of the list: `tasks --space`
    mock.fail_next("/rest/api/template/page", 403, method="GET", body=TEMPLATES_REFUSAL)  # the first list of page templates: `templates --space`
    mock.fail_next("/rest/api/template/blueprint", 403, method="GET", body=TEMPLATES_REFUSAL)  # and of the templates of blueprints
    made = (space_id, home, page, below, linking, post, footer, inline, reply, post_comment, attachment, post_attachment, task, post_task, template, blueprint)
    expected = (SPACE_ID, HOME, PAGE, BELOW, LINKING, BLOGPOST, FOOTER, INLINE, REPLY, BLOGPOST_COMMENT, ATTACHMENT, BLOGPOST_ATTACHMENT, TASK, POST_TASK, TEMPLATE, BLUEPRINT_TEMPLATE)
    if made != expected:
        raise RuntimeError(f"The personal space has the ids {made}, not {expected}: the lines below name them")


PREPARE = prepare

ADDRESS = f"https://example.atlassian.net/wiki/spaces/{PERSONAL}/pages/{PAGE}/Personal+notes"  # as it is copied from the browser
REFERENCE = f"page:{PERSONAL}/Personal notes"  # the other way to name a page: its space and its title
MISSING = f"page:{PERSONAL}/No page has this title"

LINES = (
    # the pages of the space, and one page with everything that belongs to it
    line("pages", "--space", PERSONAL),
    line("pages", "--space", PERSONAL, "--all", "--json"),
    line("pages", "--space", PERSONAL, "--title", "Personal notes"),
    line("pages", "--space", PERSONAL, "--root"),
    line("pages", "--space", PERSONAL, "--status", "archived", "--sort", "modified-date", "--desc"),
    line("pages", "--space", PERSONAL, "--limit", "1", "--select", "id,title", "--format", "tsv"),
    line("pages", "--space", PERSONAL, "--title", "No page has this title"),
    line("page", PAGE),
    line("page", PAGE, "--json"),
    line("page", PAGE, "--ancestors", "--attachments", "--comments", "--outline"),
    line("page", PAGE, "--section", "Notes"),
    line("page", BELOW, "--ancestors", "--no-body"),
    line("page", BELOW, "--ancestors", "--no-body", "--json"),
    line("page", PAGE, "--version", "2"),
    line("page", PAGE, "--raw"),
    line("page", PAGE, "--format", "storage"),
    line("page", ADDRESS),
    line("page", PAGE, BELOW, "--outline"),
    line("page", PAGE, BELOW, "--json"),
    line("page", PAGE, "--attachments", "--no-body", "--json"),
    line("page", REFERENCE),
    line("page", "page:Personal notes", "--space", PERSONAL),
    line("page", MISSING, code=4),
    line("page", PAGE, "--with-users"),
    line("page", PAGE, "--ancestors", "--comments", "--with-users", "--json"),
    # a page of a team space whose body links into the personal space
    line("page", LINKING),
    line("page", LINKING, "--json"),
    line("page", LINKING, "--format", "text"),
    line("page", LINKING, "--format", "storage"),
    line("page", LINKING, "--raw"),
    line("page", LINKING, "--outline"),
    line("page", LINKING, "--with-users"),
    line("versions", PAGE),
    line("versions", PAGE, "--all", "--json"),
    line("versions", PAGE, "--with-users"),
    line("diff", PAGE),
    line("diff", PAGE, "--from", "1", "--to", "3"),
    line("diff", PAGE, "--json"),
    line("tree", PAGE),
    line("tree", PAGE, "--json"),
    line("tree", HOME, "--depth", "3"),
    line("tree", REFERENCE, "--depth", "2"),
    line("tree", "page:Personal notes", "--space", PERSONAL),
    line("tree", MISSING, code=4),
    # blog posts
    line("blogposts", "--space", PERSONAL),
    line("blogposts", "--space", PERSONAL, "--all", "--json"),
    line("blogposts", "--space", PERSONAL, "--title", "Personal news", "--sort", "created-date", "--desc"),
    line("blogposts", "--space", PERSONAL, "--status", "trashed"),
    line("blogposts", "--sort", "created-date", "--desc", "--all"),
    line("blogposts", "--space", PERSONAL, "--title", "No post has this title"),
    line("blogpost", BLOGPOST),
    line("blogpost", BLOGPOST, "--json", "--comments"),
    line("blogpost", BLOGPOST, "--outline"),
    line("blogpost", BLOGPOST, "--no-body", "--json"),
    line("blogpost", BLOGPOST, "--raw"),
    line("blogpost", BLOGPOST, "--format", "storage"),
    line("blogpost", BLOGPOST, "--comments", "--with-users"),
    # labels, comments and files
    line("labels", "--space", PERSONAL),
    line("labels", "--space", PERSONAL, "--all", "--json"),
    line("labels", PAGE),
    line("comments", PAGE),
    line("comments", PAGE, "--inline", "--json"),
    line("comments", PAGE, "--with-users"),
    line("comment", PAGE, "--get", FOOTER),
    line("comment", PAGE, "--get", FOOTER, "--format", "storage", "--json"),
    line("comment", PAGE, "--get", INLINE, "--json"),
    line("attachments", PAGE, "--all"),
    line("attachments", PAGE, "--json"),
    line("attachments", BLOGPOST),
    line("attachment", ATTACHMENT),
    line("attachment", ATTACHMENT, "--versions", "--labels", "--json"),
    line("attachment", ATTACHMENT, "--versions", "--with-users"),
    line("download", ATTACHMENT, "--out", "{work}/personal-file"),
    line("download", PAGE, "--all", "--out", "{work}/personal-files"),
    line("download", BLOGPOST, "--all", "--out", "{work}/personal-blog-files"),
    line("download", PAGE, "--all", "--text"),
    line("download", PAGE, "--all", "--text", "--dry-run"),
    # who may see and do what, and who watches
    line("restrictions", PAGE),
    line("restrictions", PAGE, "--json"),
    line("restrictions", BLOGPOST),
    line("restrictions", PAGE, "--with-users"),
    line("permissions", PAGE),
    line("permissions", BLOGPOST, "--json"),
    line("permissions", "--space", PERSONAL, "--json"),
    line("watching", PAGE),
    line("watching", BLOGPOST, "--json"),
    line("watching", "--space", PERSONAL),
    line("watching", "--space", PERSONAL, "--json"),
    # properties
    line("properties", PAGE),
    line("properties", PAGE, "--all", "--json"),
    line("properties", PAGE, "--key", PROPERTY_KEY),
    line("properties", BLOGPOST),
    line("properties", PAGE, "--with-users"),
    # tasks: the first read of the list is refused with the address of a person in the explanation (see PREPARE), then the list in every form, one task, and its change
    line("tasks", "--space", PERSONAL, code=5),
    line("tasks", "--space", PERSONAL),
    line("tasks", "--space", PERSONAL, "--json"),
    line("tasks", "--space", PERSONAL, "--all", "--select", "id,pageId,spaceId", "--format", "tsv"),
    line("tasks", "--space", PERSONAL, "--status", "incomplete", "--due-before", "2026-12-31"),
    line("tasks", "--page", PAGE),
    line("tasks", "--page", PAGE, "--json"),
    line("tasks", "--page", BLOGPOST, "--json"),
    line("tasks", "--task", TASK, "--task", POST_TASK, "--json"),
    line("tasks", "--all", "--json"),
    line("tasks", "--space", PERSONAL, "--with-users"),
    line("tasks", "--space", PERSONAL, "--with-users", "--json"),
    line("task", TASK),
    line("task", TASK, "--json"),
    line("task", POST_TASK),
    line("task", TASK, "--complete", "--dry-run"),
    line("task", TASK, "--complete"),
    line("task", TASK, "--reopen", "--json"),
    line("task", POST_TASK, "--complete", "--json"),
    # templates: the first lists of the space are refused with the address of a person in the explanation (see PREPARE), then the global ones, those of the space, and one template
    line("templates", "--space", PERSONAL, code=5),
    line("templates", "--blueprints", "--space", PERSONAL, code=5),
    line("templates", "--space", PERSONAL),
    line("templates", "--space", PERSONAL, "--json"),
    line("templates", "--space", PERSONAL, "--all", "--select", "id,name,spaceKey", "--format", "tsv"),
    line("templates", "--blueprints", "--space", PERSONAL),
    line("templates", "--blueprints", "--space", PERSONAL, "--all", "--json"),
    line("templates"),
    line("templates", "--blueprints"),
    line("templates", "--all", "--json"),
    line("template", TEMPLATE),
    line("template", TEMPLATE, "--json"),
    line("template", TEMPLATE, "--format", "storage"),
    line("template", TEMPLATE, "--format", "text"),
    line("template", TEMPLATE, "--body-only"),
    line("template", TEMPLATE, "--format", "storage", "--body-only"),
    line("template", BLUEPRINT_TEMPLATE),
    line("template", BLUEPRINT_TEMPLATE, "--json"),
    line("template", "7401"),
    line("template", "7401", "--json"),
    # the other kinds of content in the space
    line("folder", FOLDER, "--children", "--ancestors"),
    line("folder", FOLDER, "--json"),
    line("whiteboard", WHITEBOARD, "--ancestors"),
    line("whiteboard", WHITEBOARD, "--json"),
    line("database", DATABASE, "--fields", "--ancestors"),
    line("database", DATABASE, "--json"),
    line("smartlink", SMARTLINK, "--ancestors"),
    line("smartlink", SMARTLINK, "--json"),
    # the search index: pages, blog posts, files, comments, labels and the space itself
    line("search", "Personal notes", "--space", PERSONAL),
    line("search", "Personal", "--space", PERSONAL, "--snippets", "2", "--json"),
    line("search", "Personal", "--space", PERSONAL, "--type", "blogpost"),
    line("search", "notes", "--space", PERSONAL, "--under", PAGE),
    line("search", "diary", "--label", "diary", "--space", PERSONAL, "--excerpts"),
    line("search", "--cql", f'space = "{PERSONAL}"', "--all"),
    line("search", "--cql", f'space = "{PERSONAL}" AND type = page', "--json"),
    line("search", "--cql", f'space = "{PERSONAL}" AND type = page', "--raw"),
    line("search", "Personal", "--space", PERSONAL, "--with-users"),
    # what is written out: the files are named by the page and what it holds, never by the space
    line("export", "--page", PAGE, "--out", "{work}/personal-page"),
    line("export", "--page", PAGE, "--out", "{work}/personal-page-json", "--json"),
    line("export", "--page", LINKING, "--out", "{work}/personal-links"),
    line("export", "--page", HOME, "--out", "{work}/personal-home"),
    line("export", "--space", PERSONAL, "--out", "{work}/personal-space"),
    line("export", "--space", PERSONAL, "--out", "{work}/personal-dry", "--dry-run"),
    line("export", "--page", ADDRESS, "--out", "{work}/personal-address"),
    # the dry runs of the writes: the request that would be sent, with what was read from the space
    line("blogpost-create", "--space", PERSONAL, "--title", "A new post", "--body", "Text.", "--dry-run"),
    line("blogpost-update", BLOGPOST, "--title", "Personal news (swept)", "--dry-run"),
    line("comment", PAGE, "--text", "Reviewed.", "--dry-run"),
    line("label", PAGE, "--add", "swept", "--dry-run"),
    line("attach", PAGE, "{work}/report.txt", "--dry-run", files=(("report.txt", "report"),)),
    line("property-set", PAGE, "--key", PROPERTY_KEY, "--value", '{"state":"final"}', "--dry-run"),
    line("watch", PAGE, "--dry-run"),
    # and the writes themselves, which say where they wrote
    line("blogpost-create", "--space", PERSONAL, "--title", "A new post", "--body", "Text.", "--labels", "swept"),
    line("blogpost-update", BLOGPOST, "--title", "Personal news (swept)"),
    line("comment", PAGE, "--text", "Reviewed."),
    line("comment", PAGE, "--text", "A reply.", "--reply-to", FOOTER),
    line("label", PAGE, "--add", "swept"),
    line("label", PAGE, "--remove", "swept"),
    line("attach", PAGE, "{work}/report.txt", files=(("report.txt", "report"),)),
    line("property-set", PAGE, "--key", PROPERTY_KEY, "--value", '{"state":"final"}'),
    line("watch", PAGE),
    line("watch", PAGE, "--remove"),
    # the space that the person works in is their own: what names the current space prints the key as `[hidden]`, and a space that is not there is named `[hidden]`
    line("current", env=(("CONFLUENCE_SPACE", PERSONAL),)),
    line("current", "--json", env=(("CONFLUENCE_SPACE", PERSONAL),)),
    line("config", "show", env=(("CONFLUENCE_SPACE", PERSONAL),)),
    line("config", "show", "--json", env=(("CONFLUENCE_SPACE", PERSONAL),)),
    line("doctor", env=(("CONFLUENCE_SPACE", PERSONAL),)),
    line("doctor", "--json", env=(("CONFLUENCE_SPACE", PERSONAL),)),
    line("pages", "--space", "~no-such-account", code=4),
)
