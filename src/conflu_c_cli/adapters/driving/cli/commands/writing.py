"""Commands that create pages: create, import-md, import-md-dir."""
from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from .....application.rendering import storage_from_input
from .....domain.drafts import PageDraft
from .....domain.frontmatter import split_list
from ..runtime import Context
from ..spec import Arg, Command, Example
from ._common import POWERSHELL_TEXT_NOTE, pretty, shortened, text_option
from .changes import BODY, DRY_RUN, FILE, FORMAT, write_json, write_text

if TYPE_CHECKING:
    from .....application.imports import BatchImport, ImportOutcome

GROUP = "Create and import"

SPACE = Arg(("--space",), "Space key. Default: the current space.", metavar="KEY")
PARENT = Arg(("--parent",), "The page to create it below (id or address). Default: below the home page of the space.", metavar="PAGE")
FORCE_IMPORT = Arg(
    ("--force",),
    "Replace the body of an existing page even though what Markdown cannot say (macros, mentions, layouts ...) is lost.",
    kind="flag",
)


# -- create --------------------------------------------------------------------------------------


def run_create(ctx: Context, args: argparse.Namespace) -> int:
    text = text_option(ctx, args.body, args.file, "body")
    draft = PageDraft(
        space=args.space or "",
        title=args.title,
        body=storage_from_input(text, args.format) if text is not None else "",
        parent=args.parent or "",
        labels=split_list(args.labels or ""),
    )
    result = ctx.app.create_page.execute(draft, dry_run=args.dry_run)
    ctx.print_json(write_json(result)) if ctx.json_mode else ctx.print(write_text(result))
    return 0


# -- imports -------------------------------------------------------------------------------------


def outcome_json(outcome: ImportOutcome) -> dict[str, Any]:
    return {
        "file": outcome.file,
        "action": outcome.action,
        "pageId": outcome.page_id or None,
        "title": outcome.title,
        "url": outcome.url or None,
        "dryRun": outcome.dry_run,
        "message": outcome.message or None,
        "lost": list(outcome.lost),
        "labels": list(outcome.labels),
        "payload": outcome.payload,
    }


def _outcome_line(outcome: ImportOutcome) -> str:
    if outcome.action == "failed":
        return f"FAILED        {outcome.file}: {outcome.message}"
    if outcome.action == "unchanged":
        return f"unchanged     {outcome.page_id} {outcome.file}"
    verb = {"created": "create", "updated": "update"}.get(outcome.action, outcome.action)
    label = f"would {verb}" if outcome.dry_run else outcome.action
    return f"{label:<14}{outcome.page_id + ' ' if outcome.page_id else ''}{outcome.file}"


def _batch_text(batch: BatchImport, dry_run: bool) -> str:
    lines = [_outcome_line(outcome) for outcome in batch.outcomes]
    summary = (
        f"Done: files={len(batch.outcomes)} created={batch.count('created')} updated={batch.count('updated')} "
        f"unchanged={batch.count('unchanged')} failed={batch.count('failed')}"
    )
    if dry_run:
        summary += " (dry run, nothing was sent)"
    return "\n".join([*lines, summary])


def run_import_md(ctx: Context, args: argparse.Namespace) -> int:
    outcome = ctx.app.import_markdown.execute(args.file, space=args.space or "", parent=args.parent or "", dry_run=args.dry_run, force=args.force)
    if ctx.json_mode:
        ctx.print_json(outcome_json(outcome))
        return 0
    if args.dry_run:
        verb = {"created": "create a page", "updated": f"update page {outcome.page_id}", "unchanged": f"leave page {outcome.page_id} as it is"}[outcome.action]
        ctx.print(f"Dry run: would {verb}; nothing was sent" + (f"\n{pretty(shortened(outcome.payload))}" if outcome.payload else ""))
        if outcome.labels:
            ctx.print(f"Labels it would add: {', '.join(outcome.labels)}")
    elif outcome.action == "unchanged":
        ctx.print(f"Nothing to change: page {outcome.page_id} is already as the file says.")
    else:
        ctx.print(f"{outcome.action.capitalize()} page {outcome.page_id}: {outcome.title}" + (f"\n{outcome.url}" if outcome.url else ""))
        if outcome.labels:
            ctx.print(f"Labels added: {', '.join(outcome.labels)}")
    if outcome.lost:
        ctx.diagnostics.warn(f"The body was replaced although it held what Markdown cannot say: {', '.join(outcome.lost)}.")
    return 0


def run_import_md_dir(ctx: Context, args: argparse.Namespace) -> int:
    batch = ctx.app.import_markdown_directory.execute(
        args.directory,
        space=args.space or "",
        parent=args.parent or "",
        dry_run=args.dry_run,
        force=args.force,
        continue_on_error=args.continue_on_error,
    )
    if ctx.json_mode:
        ctx.print_json(
            {
                "dryRun": args.dry_run,
                "created": batch.count("created"),
                "updated": batch.count("updated"),
                "unchanged": batch.count("unchanged"),
                "failed": batch.count("failed"),
                "outcomes": [outcome_json(outcome) for outcome in batch.outcomes],
            }
        )
    else:
        ctx.print(_batch_text(batch, args.dry_run))
    if batch.first_error is not None:
        raise batch.first_error
    return 0


COMMANDS = (
    Command(
        name="create",
        group=GROUP,
        summary="Create one page",
        when="Use to create one new page below a parent. Preview with --dry-run; a title must be unique in its space.",
        description="Creates a page in a space, below the home page or below --parent. The body is Markdown (converted to storage format) unless "
        "--format says storage; a page without a body is fine. The dry run proves that the space and the parent exist and that the title is free. "
        "A title is unique in a space: an existing one is refused (exit code 3).",
        args=(
            SPACE,
            Arg(("--title",), "The title of the page.", required=True, metavar="TEXT"),
            PARENT,
            BODY,
            FILE,
            FORMAT,
            Arg(("--labels",), "Labels to put on the page, comma separated.", metavar="a,b"),
            DRY_RUN,
        ),
        examples=(
            Example("conflu create --space ENG --title 'Release notes 2026.10' --file notes.md --dry-run"),
            Example("conflu create --title 'Meeting 2026-10-15' --parent 123456 --body 'Agenda: ...' --labels meeting"),
        ),
        notes=(POWERSHELL_TEXT_NOTE, "Read the id of the new page from `--json` (`pageId`); never guess it."),
        writes=True,
        json_output=True,
        output="action (created), dryRun, pageId (null in a dry run), title, url, versionTo, labels[] and payload (exactly what is sent).",
        handler=run_create,
    ),
    Command(
        name="import-md",
        group=GROUP,
        summary="Create or update a page from a Markdown file",
        when="Use to publish one Markdown file as a page, or to update the page that it names. Preview with --dry-run.",
        description="Reads a Markdown file with an optional front matter (title, space, parent, page_id, labels, message) and publishes it. "
        "With `page_id` it updates that page; otherwise it looks for a page with the same title in the space and updates it, or creates the page. "
        "The title comes from the front matter, else from a first `# Heading`, which is then not repeated in the body. The space and parent of "
        "the front matter win over --space and --parent, which win over the current space. Labels are added, never removed. "
        "`export` writes files that this command reads again.",
        args=(
            Arg(("file",), "The Markdown file.", required=True, metavar="FILE.md"),
            SPACE,
            PARENT,
            FORCE_IMPORT,
            DRY_RUN,
        ),
        examples=(Example("conflu import-md notes.md --space ENG --dry-run"), Example("conflu import-md notes.md --space ENG --parent 123456")),
        notes=(
            "Front matter lines are `key: value`; a list goes on one line (`labels: adr, backend`).",
            "It replaces the body of the page as it is in Confluence now. The `version` and `updated` lines that `export` writes are not compared, "
            "so a change made in Confluence after the export is overwritten (it stays in the page history).",
            "It never deletes a page, moves one or removes a label; `parent` counts only when a page is created.",
            "A title with `[email]` or `[personal link]` (what `export` writes for an address or a link) is refused; take the `title:` line out and the page keeps its title.",
        ),
        writes=True,
        json_output=True,
        output="file, action (created, updated or unchanged; a label that is new makes it updated), pageId, title, url, dryRun, message, lost[], labels[] (added, or in a dry run to be added) and payload.",
        handler=run_import_md,
    ),
    Command(
        name="import-md-dir",
        group=GROUP,
        summary="Publish all Markdown files of a folder",
        when="Use to publish a folder of Markdown files. It overwrites what somebody changed in a page after the export: preview with --dry-run and compare with a fresh export first.",
        description="Runs `import-md` for every *.md file of the folder (not its subfolders) in the order of the names. It stops at the first "
        "failure unless --continue-on-error is given, and then exits with the code of the first failure. It is the way from a folder to "
        "Confluence; `export` is the way back. There is no `sync` command, and neither direction looks at what the other changed meanwhile.",
        args=(
            Arg(("directory",), "The folder.", required=True, metavar="DIR"),
            SPACE,
            PARENT,
            Arg(("--continue-on-error",), "Go on with the next file after a failure.", kind="flag"),
            FORCE_IMPORT,
            DRY_RUN,
        ),
        examples=(Example("conflu import-md-dir docs/confluence --space ENG --dry-run"), Example("conflu import-md-dir docs/confluence --space ENG --continue-on-error")),
        notes=(
            "Every file replaces its page as it is in Confluence now: a page that somebody changed after the export loses that change (it stays in the page history). "
            "Export again and read the diff before you import a folder that is not fresh; `--dry-run` shows created, updated, unchanged and failed.",
            "Nothing is deleted or moved and no label is removed. Only the `*.md` files of the folder itself are read.",
        ),
        writes=True,
        json_output=True,
        output="dryRun, created, updated, unchanged, failed and outcomes[] (the output of import-md for each file).",
        handler=run_import_md_dir,
    ),
)
