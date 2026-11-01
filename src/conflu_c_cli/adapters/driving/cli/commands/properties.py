"""Commands about the content properties of pages and other content: properties, property-set."""
from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from .....application.properties import MAX_CHARS
from .....domain.errors import UsageError, ValidationError
from .....domain.properties import CUT_MARKER, STAND_INS, named, parse_value, shown_text, validate_key
from ..render import table
from ..runtime import Context
from ..spec import READS_FILE, Arg, Command, Example
from ._common import LIMIT_HELP, check_limit
from .tasks import ALL, CURSOR

if TYPE_CHECKING:
    from .....application.properties import PropertyChange, PropertyList, PropertyView

GROUP = "Tasks and properties"
VALUE_FILE_LIMIT = 1024 * 1024  # a value is at most 32 KiB; a file is generous for the blanks of a pretty-printed one, and a bigger file is a mistake
REFUSED = ", ".join(f"`{mark}`" for mark in STAND_INS)  # what `property-set` refuses where a reading hid people; the help names them from the list that refuses them


def property_json(view: PropertyView) -> dict[str, Any]:
    return {
        "id": view.id,
        "key": view.key,
        "version": view.version,
        "updatedAt": view.updated or None,
        "value": view.value,
        "truncated": view.truncated,
        "totalChars": view.total_chars if view.truncated else None,
    }


def properties_text(result: PropertyList, key: str) -> str:
    where = named(result.target.type, result.target.id)
    if not result.properties:
        return f"No property with the key {key} on {where}." if key else f"No properties on {where}."
    rows = [[view.id, view.key, view.version, view.text] for view in result.properties]
    return f"Properties of {where}:\n" + table(["ID", "KEY", "VERSION", "VALUE"], rows)


def run_properties(ctx: Context, args: argparse.Namespace) -> int:
    check_limit(args.limit)
    result = ctx.app.properties.list_properties.execute(
        args.id,
        key=args.key or "",
        max_chars=args.max_chars,
        with_users=args.with_users,
        limit=args.limit,
        cursor=args.cursor or "",
        fetch_everything=args.all,
    )
    if ctx.json_mode:
        ctx.print_json(
            {
                "target": {"id": result.target.id, "type": result.target.type},
                "count": len(result.properties),
                "nextCursor": result.next_cursor or None,
                "truncated": result.truncated,
                "properties": [property_json(view) for view in result.properties],
            }
        )
        return 0
    ctx.print(properties_text(result, args.key or ""))
    cut = sum(1 for view in result.properties if view.truncated)
    if cut:
        ctx.diagnostics.info(
            f"{cut} {'value was' if cut == 1 else 'values were'} cut to {args.max_chars} characters and end in {CUT_MARKER}; --max-chars 0 shows them whole. A value that was cut cannot be written back."
        )
    if result.next_cursor:
        ctx.diagnostics.info(f"More properties follow. Continue with --cursor {result.next_cursor}, or use --all.")
    if result.truncated:
        ctx.diagnostics.warn("The list was cut short at its limit; ask for one key with --key.")
    return 0


def _read_value(ctx: Context, args: argparse.Namespace) -> Any:
    """The JSON value, from --value or from a file (`-`: standard input). A file that is far larger than any value is refused unread, and so is
    standard input that turns out to be."""
    if args.value is not None and args.file is not None:
        raise UsageError("Use either --value or --file, not both.")
    if args.value is None and args.file is None:
        raise UsageError("A value is needed.", hint="Pass --value JSON, or --file FILE (`-` is standard input).")
    if args.file is None:
        return parse_value(args.value, "--value")
    source = "standard input" if args.file == "-" else args.file
    if args.file != "-":
        size = ctx.app.files.size(args.file)
        if size > VALUE_FILE_LIMIT:
            raise ValidationError(f"{args.file} is {size:,} bytes: a file with a value holds at most {VALUE_FILE_LIMIT:,} bytes, and the value 32 KiB.")
    text = ctx.read_input(args.file)
    if len(text) > VALUE_FILE_LIMIT:
        raise ValidationError(f"{source} holds {len(text):,} characters: a value is at most 32 KiB, and the text that holds it at most {VALUE_FILE_LIMIT:,} characters.")
    return parse_value(text, source)


def _shown(value: Any, limit: int = 500) -> str:
    text, cut, total = shown_text(value, limit)
    return f"{text} ({total - limit:,} more characters)" if cut else text


def change_text(result: PropertyChange) -> str:
    where = named(result.target.type, result.target.id)
    key = result.key
    if result.action == "unchanged":
        return f"Nothing to change: the property {key} of {where} holds that value already (version {result.version_to})."
    if result.dry_run:
        if result.action == "created":
            return f"Dry run: the property {key} would be created on {where}; nothing was sent\nvalue: {_shown(result.value)}"
        steps = f"from version {result.version_from} to {result.version_to}"
        return f"Dry run: the property {key} of {where} would go {steps}; nothing was sent\ncurrent: {_shown(result.current)}\nnew:     {_shown(result.value)}"
    if result.action == "created":
        known = f" (id {result.property_id}, version {result.version_to})" if result.property_id else ""  # an answer that names no id says nothing about the new property
        return f"Created the property {key} on {where}{known}."
    return f"Updated the property {key} of {where} (version {result.version_from} -> {result.version_to}).\nIt held: {_shown(result.current)}"


def run_property_set(ctx: Context, args: argparse.Namespace) -> int:
    key = validate_key(args.key)
    value = _read_value(ctx, args)
    result = ctx.app.properties.set_property.execute(
        args.id, key, value, message=(args.message or "").strip(), if_version=args.if_version, dry_run=args.dry_run
    )
    if ctx.json_mode:
        ctx.print_json(
            {
                "action": result.action,
                "dryRun": result.dry_run,
                "target": {"id": result.target.id, "type": result.target.type},
                "key": result.key,
                "propertyId": result.property_id or None,
                "versionFrom": result.version_from or None,
                "versionTo": result.version_to,
                "value": result.value,
                "current": result.current,
                "payload": result.payload,
                "notes": result.notes,
            }
        )
        return 0
    ctx.print(change_text(result))
    for note in result.notes:  # the notes are in the JSON; for a person they stand below the answer
        ctx.diagnostics.info(note)
    return 0


COMMANDS = (
    Command(
        name="properties",
        group=GROUP,
        summary="Show the content properties of a page or other content",
        when="Use to read what apps and people keep under keys on a page, a blog post, a folder, a whiteboard, a database, a smart link, an attachment "
        "(its id starts with att) or a comment. To set one use `property-set`.",
        description="A content property is a small piece of JSON with a key and a version. Apps keep their settings and their marks in them. The kind of the "
        f"content is looked up from its id. A value is shown as compact JSON and cut at --max-chars characters (a cut value ends in `{CUT_MARKER}`; 0 cuts nothing); "
        "with --json it is the JSON value itself. People in a value (user objects, account ids, e-mail addresses, personal links) are hidden unless you add "
        "--with-users. To change a value read it whole and real first (--with-users --max-chars 0), because `property-set` refuses the cut and the hidden form.",
        args=(
            Arg(("id",), "The id of the content, or the address of it as copied from the browser. An attachment's id starts with att.", required=True, metavar="ID"),
            Arg(("--key",), "Only the property with this key (case sensitive).", metavar="KEY"),
            Arg(
                ("--max-chars",),
                f"Cut a value that is longer than N characters as compact JSON: it ends in `{CUT_MARKER}` and `truncated` says so. 0 cuts nothing; read a value that you will write back with 0.",
                kind="int",
                default=MAX_CHARS,
                metavar="N",
            ),
            Arg(("--with-users",), "Show the people in the values. Refused when CONFLUENCE_HIDE_USERS=true.", kind="flag"),
            Arg(("--limit",), LIMIT_HELP, kind="int", default=25, metavar="N"),
            CURSOR,
            Arg(("--all",), ALL, kind="flag"),
        ),
        examples=(
            Example("conflu properties 123456"),
            Example("conflu properties 123456 --key team.review --json", "one property, for a script or an agent"),
            Example("conflu properties att5001 --all --max-chars 0", "every property of an attachment, every value whole"),
            Example("conflu properties 123456 --with-users"),
        ),
        notes=(
            "With --json `value` is the JSON value as it is. Only a value that was cut (`truncated` is true) is a text instead: the beginning of its compact JSON and then "
            f"`{CUT_MARKER}`, which `property-set` refuses; `totalChars` is the size of the whole. To edit a value read it with --max-chars 0.",
            "Apps use properties: do not change one that an app owns without knowing what the app does with it.",
        ),
        json_output=True,
        output="target{id,type} (type is what Confluence calls the content: page, blogpost, folder, whiteboard, database, embed, attachment, footer-comment "
        "or inline-comment), count, nextCursor (null on the last page), truncated (an --all that stopped at its limit) and properties[]: id, key, version, "
        f"updatedAt, value (any JSON; when truncated the beginning of its compact text and `{CUT_MARKER}`), truncated, totalChars (the size of the whole text when truncated, else null).",
        handler=run_properties,
    ),
    Command(
        name="property-set",
        group=GROUP,
        summary="Create or update a content property",
        when="Use to store a small JSON value under a key on a page or other content. The property is created when the key is new, else its next version "
        "is saved. Preview with --dry-run, and guard an update with --if-version.",
        description="The property is read first. A value that is there already is left alone (`unchanged`); a value that differs becomes the next version "
        "(the current one plus one), which Confluence refuses with exit code 3 when somebody saved the property in between; with --if-version N the "
        "command refuses before it sends anything unless the property is at version N now (0: it must not exist yet). The value must be valid JSON of at "
        "most 32 KiB (a number must be finite: 1e999 is refused), and the key may hold letters, digits and _ . : - only. A value that is a copy of what `properties` "
        f"shows is refused with exit code 1, because saving it would overwrite what the property holds: one with the stand-ins for people ({REFUSED}, or a "
        "blanked attribute such as `ri:account-id=\"hidden\"`), one with a text that was changed (an address shown without its title), and one that holds "
        f"`{CUT_MARKER}`, the mark of a value that was cut at --max-chars (refused for a new property too). Read the whole real value with --with-users "
        "--max-chars 0. No command deletes a property.",
        args=(
            Arg(("id",), "The id of the content, or the address of it as copied from the browser. An attachment's id starts with att.", required=True, metavar="ID"),
            Arg(("--key",), "The key of the property: letters, digits and _ . : - , up to 255 characters.", required=True, metavar="KEY"),
            Arg(
                ("--value",),
                "The value as JSON: 42, true, null, \"text\" (a text needs its own double quotes), [1,2] or {\"a\":1}. Windows PowerShell 5.1 removes the double quotes inside an argument: use --file then.",
                metavar="JSON",
                not_a_path="the value itself, written as JSON on the command line; the option that names a path is --file",
            ),
            Arg(("--file",), "Read the value (JSON) from a file (`-` is standard input).", metavar="FILE", path=READS_FILE),
            Arg(("--message",), "A message stored with the new version (an update only: a new property has none).", metavar="TEXT"),
            Arg(("--if-version",), "Refuse (exit code 3) unless the property is at this version now; 0 means that it must not exist yet.", kind="int", metavar="N"),
            Arg(("--dry-run",), "Show whether the property would be created or updated, with its current and its new value, and send nothing.", kind="flag"),
        ),
        examples=(
            Example("conflu property-set 123456 --key team.review --value '{\"status\":\"open\"}' --dry-run"),
            Example("conflu property-set 123456 --key team.review --file value.json --if-version 3 --message 'Reviewed'"),
            Example("conflu property-set 123456 --key my-app:flag --value true"),
            Example("conflu property-set 123456 --key note --value '\"a text\"' --json"),
        ),
        notes=(
            "A text is JSON only with double quotes around it: --value '\"text\"'. In Windows PowerShell 5.1 the quotes are lost on the way to the program: "
            "put the value into a file (--file value.json) or pipe it in (--file -).",
            "Apps keep their settings in properties. Changing a property that an app owns can change what the app does; there is no undo in this CLI, and no "
            "command deletes a property.",
        ),
        writes=True,
        json_output=True,
        output="action (created, updated or unchanged), dryRun, target{id,type}, key, propertyId (null in a dry run of a creation, and when Confluence's answer to it named "
        "no id), versionFrom (null for a "
        "creation), versionTo, value (the value that is set), current (what Confluence held, without people; null for a creation), payload (exactly what is "
        "sent; null when nothing is) and notes[].",
        destructive=True,
        idempotent=True,
        handler=run_property_set,
    ),
)
