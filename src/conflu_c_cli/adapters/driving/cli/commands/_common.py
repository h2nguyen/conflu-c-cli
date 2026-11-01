"""Helpers shared by the command modules."""
from __future__ import annotations

import copy
import json
import re
from typing import TYPE_CHECKING, Any, Sequence

from .....domain.errors import UsageError, ValidationError
from .....domain.textio import QUERY_LIMIT, check_length, decode_input
from ..runtime import Context

if TYPE_CHECKING:
    from .....application.comments import CommentView
    from .....application.rendering import Body
    from .....domain.model import User


def text_option(ctx: Context, text: str | None, file: str | None, what: str) -> str | None:
    """Text given inline or from a file (`-` is standard input). None when neither was given."""
    if text is not None and file is not None:
        raise UsageError(f"Use either the {what} text or its file, not both.")
    if file is not None:
        return ctx.read_input(file)
    return text


def replacing_text_option(ctx: Context, text: str | None, file: str | None, what: str) -> str | None:
    """Like `text_option`, for a text that REPLACES what Confluence holds (`update --file`). An empty file or empty standard input is refused:
    it is nearly always a mistake (an editor that saved nothing, a pipe that failed), and it would clear the body. An empty value given
    on the command line (`--body ''`) clears it on purpose."""
    value = text_option(ctx, text, file, what)
    if file is not None and value is not None and not value.strip():
        raise UsageError(
            f"The {what} is empty: {'standard input' if file == '-' else file} holds no text.",
            hint=f"Check the file or the pipe. To clear the {what} on purpose, give --{what} '' on the command line.",
        )
    return value


POWERSHELL_JSON_NOTE = (
    "In Windows PowerShell 5.1 pass the body with --data-file: PowerShell removes double quotes inside an argument."
)
POWERSHELL_TEXT_NOTE = (
    "Text with quotes or $ is easiest in a file: --file notes.md. In Windows PowerShell 5.1 double quotes inside an "
    "argument are removed."
)
QUERY_NOTE = (
    "In Windows PowerShell 5.1 a search text or a CQL query with double quotes (title ~ \"a b\") arrives broken, because PowerShell removes "
    "them inside an argument: put it in a file and pass it in single quotes, '@query.txt' (a bare @name is splatting in PowerShell), pipe it "
    "in with `-`, or give exact phrases with --phrase 'exact words'."
)

AT_HINT = "A value that starts with @ is read from the file of that name. To search for a text that starts with @, put a space in front of it (or use --phrase)."


def query_option(ctx: Context, value: str | None, what: str = "query", *, text_without_file: bool = False) -> str | None:
    """A query (CQL or search text) given inline, as `@FILE` (read from a file) or as `-` (read from standard input).

    A file is the form that survives every shell: Windows PowerShell 5.1 removes the double quotes inside an argument. The file
    may be UTF-8, UTF-8 with a byte order mark, UTF-16 (which is what PowerShell writes) or Windows-1252. Of a file or of standard input at most
    `QUERY_LIMIT` bytes are read (one more is read to see that there is more): a device or a pipe has no end. None when no query was given.

    With `text_without_file` (the text of a search, which is any words: `@alex` and `@example.com` were searched for as they stand before files were
    read) an `@NAME` that names no file is the text itself, and a warning says so, because a mistyped file name looks the same; when the file is there
    a note says that it was read. A CQL never starts with `@`, so there a missing file is an error."""
    if value is None:
        return None
    if value in ("-", "@-"):
        text = ctx.read_stdin(QUERY_LIMIT, what)
    elif value.startswith("@") and len(value) > 1:
        name = value[1:]
        if text_without_file and not ctx.app.files.is_file(name):
            ctx.diagnostics.warn(
                f"The {what} starts with @ and no file of that name was found, so it is searched for as text. To read the text from a file, check the "
                "name: it is looked for in the working folder."
            )
            return value
        text = _read_query_file(ctx, name, what)
        if text_without_file:
            ctx.diagnostics.info(
                f"The {what} was read from the file {name}, because it starts with @ and a file of that name is there. To search for the text itself, put a "
                "space in front of it or use --phrase."
            )
    else:
        return value
    query = text.strip()
    if not query:
        raise UsageError(f"The {what} is empty: {'standard input' if value in ('-', '@-') else value[1:]} holds no text.")
    return query


def _read_query_file(ctx: Context, path: str, what: str) -> str:
    try:
        data = ctx.app.files.read_up_to(path, QUERY_LIMIT + 1)  # the size that a file claims is not believed: a device says 0 and has no end
        check_length(len(data), QUERY_LIMIT, path, what)
        return decode_input(data, path)
    except ValidationError as error:
        raise ValidationError(error.message, hint=error.hint or AT_HINT) from error


_DOUBLE_QUOTES = '"\u201c\u201d\u201e\u201f\u00ab\u00bb'  # the ones the search turns into a quote as well (domain.searchterms)
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def with_phrases(text: str, phrases: Sequence[str]) -> str:
    """The search text with exact phrases added, each in double quotes that nobody has to type: Windows PowerShell 5.1 removes the double
    quotes inside an argument. The phrases come first, so that an unbalanced quote in the text cannot swallow them."""
    quoted: list[str] = []
    for phrase in phrases:
        if _CONTROL.search(phrase) or any(mark in phrase for mark in _DOUBLE_QUOTES):
            raise UsageError(
                "A --phrase must not contain a double quote or a control character.",
                hint="Give the words as they are, for example --phrase 'access request': the CLI puts the quotes around them.",
            )
        words = " ".join(phrase.split())
        if not words:
            raise UsageError("--phrase needs the words of the phrase.", hint="For example --phrase 'access request'.")
        quoted.append(f'"{words}"')
    return " ".join(part for part in (*quoted, text.strip()) if part)


LIMIT_HELP = "Items per page (1 to 250)."


def pretty(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


# What a person who reads a dry run must not miss in the part that is cut: a macro can run or embed something, and `ri:url` is an address that is fetched or linked.
_MACRO_TAG = re.compile(r"<ac:(?:structured-)?macro(?=[\s/>])", re.IGNORECASE)
_ADDRESS_TAG = re.compile(r"<ri:url(?=[\s/>])", re.IGNORECASE)
_WIDEST_TAG = len("<ac:structured-macro")


def _hidden(pattern: re.Pattern[str], text: str, limit: int) -> int:
    """How many tags of the kind that `pattern` finds are not shown whole by the first `limit` characters of `text`: those that begin after it, and the one that the cut is in."""
    return sum(1 for found in pattern.finditer(text, max(0, limit - _WIDEST_TAG)) if found.end() > limit)


def _hidden_note(text: str, limit: int) -> str:
    """What the cut part of a body holds that goes beyond text, as a count (never as the text itself): `, among them 2 macros and 1 external address`."""
    macros, addresses = _hidden(_MACRO_TAG, text, limit), _hidden(_ADDRESS_TAG, text, limit)
    parts = []
    if macros:
        parts.append(f"{macros} macro{'s' if macros != 1 else ''}")
    if addresses:
        parts.append(f"{addresses} external address{'es' if addresses != 1 else ''}")
    return f", among them {' and '.join(parts)}" if parts else ""


def shortened(payload: Any, limit: int = 1500) -> Any:
    """A payload for a person to read: a page body longer than `limit` characters is cut, and the cut says how many macros and external addresses
    are in the part that is left out, so that nothing that reaches beyond the page is hidden without a word. The JSON of a dry run
    is never cut; this is only for the text."""
    clone = copy.deepcopy(payload)
    body = clone.get("body") if isinstance(clone, dict) else None
    if isinstance(body, dict) and isinstance(body.get("value"), str) and len(body["value"]) > limit:
        body["value"] = f"{body['value'][:limit]}... ({len(body['value']) - limit} more characters{_hidden_note(body['value'], limit)})"
    return clone


def user_json(user: User | None) -> dict[str, str] | None:
    return None if user is None else {"accountId": user.account_id, "displayName": user.display_name, "email": user.email}


def check_limit(limit: int) -> None:
    if not 1 <= limit <= 250:
        raise UsageError("--limit must be between 1 and 250.")


def user_name(user: User | None) -> str:
    return "" if user is None else user.display_name or user.account_id


def body_json(body: Body | None) -> dict[str, Any] | None:
    return None if body is None else {"format": body.format, "value": body.text, "dropped": list(body.dropped)}


def page_body_json(body: Body | None) -> dict[str, Any] | None:
    """The body of a page: `section` names the part when one section was asked for, `truncated` says that the text was cut to
    --max-chars (then `totalChars` is the size of the whole text)."""
    if body is None:
        return None
    return {
        "format": body.format,
        "value": body.text,
        "dropped": list(body.dropped),
        "section": body.section or None,
        "truncated": body.truncated,
        "totalChars": body.total_chars or None,
    }


def comment_json(view: CommentView) -> dict[str, Any]:
    comment = view.comment
    return {
        "id": comment.id,
        "kind": comment.kind,
        "updated": comment.updated,
        "parentId": comment.parent_id or None,
        "resolution": comment.resolution or None,
        "author": user_json(comment.author),
        "body": body_json(view.body),
    }


def comments_text(views: Sequence[CommentView], *, users_shown: bool) -> str:
    """Each comment under a line with its id and date; a reply is indented below the comment it answers."""
    lines: list[str] = []
    for view in views:
        comment = view.comment
        indent = "    " if comment.parent_id else ""
        who = f"  {user_name(comment.author)}" if users_shown and comment.author else ""
        reply = f" (reply to #{comment.parent_id})" if comment.parent_id else ""
        state = f" [{comment.resolution}]" if comment.resolution else ""
        lines.append(f"{indent}--- #{comment.id} {comment.kind}{state} {comment.updated}{reply}{who}")
        lines.extend(f"{indent}{line}".rstrip() for line in view.body.text.strip().splitlines())
    return "\n".join(lines)
