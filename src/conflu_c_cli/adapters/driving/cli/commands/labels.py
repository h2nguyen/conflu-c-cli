"""Commands about the labels of a page and of a space: labels, label."""
from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Sequence

from .....domain.errors import UsageError, ValidationError
from .....domain.frontmatter import split_list
from .....domain.model import Label, parse_page_id
from ..listing import FORMAT, SELECT, print_list
from ..render import table
from ..runtime import Context
from ..spec import Arg, Command, Example
from ._common import check_limit
from .changes import DRY_RUN

if TYPE_CHECKING:
    from .....application.labels import LabelsResult

GROUP = "Read"
WORK = "Work on a page"
LABEL_COLUMNS = [("NAME", "name"), ("PREFIX", "prefix")]
SPACE_PAGE = 25  # labels in a piece of the list of a space, as the API gives them when it is not asked for more


def label_rows(labels: Sequence[Label]) -> list[dict[str, str]]:
    return [{"name": label.name, "prefix": label.prefix} for label in labels]


def labels_table(labels: Sequence[Label]) -> str:
    return table(["NAME", "PREFIX"], [(label.name, label.prefix) for label in labels]) if labels else "No labels."


def run_labels(ctx: Context, args: argparse.Namespace) -> int:
    if args.ref is not None and args.space is not None:
        raise UsageError(
            "Name a page or a space, not both.",
            hint="`conflu labels PAGE` lists the labels of one page, `conflu labels --space KEY` those that the content of a space carries.",
        )
    if args.ref is None and args.space is None:
        raise UsageError(
            "Name a page or a space.",
            hint="`conflu labels PAGE` lists the labels of one page, `conflu labels --space KEY` those that the content of a space carries. "
            "The current space of `conflu use` is not assumed here.",
        )
    if args.space is None:
        for flag, given in (("--limit", args.limit is not None), ("--cursor", args.cursor is not None), ("--all", args.all)):
            if given:
                raise UsageError(f"{flag} applies to --space: the labels of a page are always listed whole.", hint="Leave it out, or name a space with --space KEY.")
        labels = ctx.app.list_labels.execute(args.ref)
        rows = label_rows(labels)
        print_list(ctx, args, payload={"pageId": parse_page_id(args.ref), "labels": rows}, rows=rows, list_key="labels", columns=LABEL_COLUMNS, plain=lambda: labels_table(labels))
        return 0
    limit = SPACE_PAGE if args.limit is None else args.limit
    check_limit(limit)
    result = ctx.app.labels.in_space.execute(args.space, limit=limit, cursor=args.cursor or "", fetch_everything=args.all)
    rows = label_rows(result.labels)
    document = {"space": result.space.key, "spaceId": result.space.id, "count": len(rows), "nextCursor": result.next_cursor or None, "truncated": result.truncated, "labels": rows}
    if print_list(ctx, args, payload=document, rows=rows, list_key="labels", columns=LABEL_COLUMNS, plain=lambda: labels_table(result.labels)):
        return 0
    if result.truncated:
        ctx.diagnostics.warn(f"The list was cut after {len(rows)} labels: there are more.")
    elif result.next_cursor:
        ctx.diagnostics.info(f"More labels follow. Continue with --cursor {result.next_cursor}, or use --all.")
    return 0


def labels_text(result: LabelsResult) -> str:
    changes = []
    if result.added:
        changes.append(f"{'would add' if result.dry_run else 'added'}: {', '.join(result.added)}")
    if result.removed:
        changes.append(f"{'would remove' if result.dry_run else 'removed'}: {', '.join(result.removed)}")
    head = "; ".join(changes) if changes else "nothing to change, the labels are as asked"
    now = ", ".join(label.name for label in result.labels) or "(none)"
    prefix = "Dry run (nothing was sent): " if result.dry_run else ""
    return f"{prefix}page {result.page_id}: {head}\nLabels{' now' if not result.dry_run else ''}: {now}"


def label_names(option: str, text: str | None) -> list[str]:
    """The label names that an option holds. An option that is given and names no label is an error, never "not given"."""
    if text is None:
        return []
    names = split_list(text)
    if not names:
        raise ValidationError(f"{option} is empty: it needs label names, comma separated.", hint=f"Leave {option} out if you mean none.")
    return names


def run_label(ctx: Context, args: argparse.Namespace) -> int:
    result = ctx.app.change_labels.execute(args.ref, add=label_names("--add", args.add), remove=label_names("--remove", args.remove), dry_run=args.dry_run)
    if ctx.json_mode:
        ctx.print_json(
            {
                "pageId": result.page_id,
                "dryRun": result.dry_run,
                "added": result.added,
                "removed": result.removed,
                "labels": [label.name for label in result.labels],
            }
        )
    else:
        ctx.print(labels_text(result))
    return 0


COMMANDS = (
    Command(
        name="labels",
        group=GROUP,
        summary="List the labels of a page or of a space",
        when="Use to see how one page is tagged, or with --space which labels the content of a space carries. To find the pages that carry a label, "
        "use `search` with its label option.",
        description="With a page: its labels. With --space KEY: the labels that the pages and blog posts of the space carry, by name, one page of "
        "the list at a time (--limit, --cursor) or all of it (--all). Name a page or a space, not both.",
        args=(
            Arg(("ref",), "Page id, or the address of the page. Leave it out to list the labels of a space.", metavar="PAGE"),
            Arg(("--space",), "List the labels that the content of this space carries.", metavar="KEY"),
            Arg(("--limit",), "With --space: labels per page of the list (1 to 250, default 25).", kind="int", metavar="N"),
            Arg(("--cursor",), "With --space: continue after the end of the previous answer: pass its nextCursor.", metavar="TOKEN"),
            Arg(("--all",), "With --space: fetch every page of the list instead of one (ignores --limit and --cursor).", kind="flag"),
            SELECT,
            FORMAT,
        ),
        examples=(
            Example("conflu labels 123456"),
            Example("conflu labels 123456 --json"),
            Example("conflu labels 123456 --select name --format tsv", "only the names, one per line"),
            Example("conflu labels --space ENG --all --json", "every label that the content of the space carries"),
        ),
        json_output=True,
        notes=(
            "`conflu search --label NAME` finds the pages that carry a label. --space lists the labels of the content of a space, not the labels of the "
            "space itself; the current space of `conflu use` is not assumed, name the page or the space.",
        ),
        output="with a page: pageId and labels[]: name, prefix. With --space: space (key, [hidden] for a personal space), spaceId, count, nextCursor, truncated and labels[]: name, prefix; "
        "with --select only those (dotted) keys of every label.",
        handler=run_labels,
    ),
    Command(
        name="label",
        group=WORK,
        summary="Add or remove labels of a page",
        when="Use to add or remove labels of one page. Preview with --dry-run.",
        description="Adds the labels of --add and removes those of --remove (comma separated). A label that is on the page already, or "
        "not on it, is skipped. Labels are written in lower case.",
        args=(
            Arg(("ref",), "Page id, or the address of the page.", required=True, metavar="PAGE"),
            Arg(("--add",), "Labels to add, comma separated.", metavar="a,b"),
            Arg(("--remove",), "Labels to remove, comma separated.", metavar="a,b"),
            DRY_RUN,
        ),
        examples=(Example("conflu label 123456 --add reviewed,adr --dry-run"), Example("conflu label 123456 --remove draft")),
        writes=True,
        json_output=True,
        output="pageId, dryRun, added[], removed[] and labels[] (the names after the change; the current ones in a dry run).",
        destructive=True,
        idempotent=True,
        handler=run_label,
    ),
)
