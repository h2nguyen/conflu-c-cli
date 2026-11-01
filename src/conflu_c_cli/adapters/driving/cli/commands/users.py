"""Commands about looking up people: users (search, lookup)."""
from __future__ import annotations

import argparse
from typing import Any, Sequence

from .....application.users import ensure_people_allowed
from .....domain.errors import UsageError
from .....domain.users import Person
from ..listing import FORMAT, SELECT, print_list
from ..render import table
from ..runtime import Context
from ..spec import Arg, Command, Example
from ._common import check_limit, query_option

GROUP = "Access and people"
ACTIONS = ("search", "lookup")
SEARCH_PAGE = 25  # people per request when the person says nothing
COLUMNS = [("ACCOUNT ID", "accountId"), ("NAME", "displayName"), ("EMAIL", "email"), ("TYPE", "accountType")]

FILE_NOTE = (
    "In Windows PowerShell 5.1 a name with double quotes arrives broken, because PowerShell removes them inside an argument: put it in a file and pass it "
    "in single quotes, '@name.txt' (a bare @name is splatting in PowerShell), or pipe it in with `-`."
)


def person_json(person: Person) -> dict[str, Any]:
    """A person as Confluence describes one: what it does not say is null (the e-mail address depends on the privacy setting of the person)."""
    return {
        "accountId": person.account_id,
        "displayName": person.display_name or None,
        "email": person.email or None,
        "accountType": person.account_type or None,
    }


def people_text(people: Sequence[Person]) -> str:
    if not people:
        return "No people found."
    return table([header for header, _ in COLUMNS], [(item.account_id, item.display_name, item.email, item.account_type) for item in people])


def run_search(ctx: Context, args: argparse.Namespace) -> int:
    limit = SEARCH_PAGE if args.limit is None else args.limit
    check_limit(limit)
    text = query_option(ctx, args.text, "search text") or ""
    result = ctx.app.users.search.execute(text, with_users=args.with_users, limit=limit, start=args.start or 0, fetch_everything=args.all)
    rows = [person_json(item) for item in result.people]
    document = {
        "query": result.query,
        "cql": result.cql,
        "total": result.total,
        "count": len(rows),
        "start": result.start,
        "nextStart": result.next_start,
        "truncated": result.truncated,
        "users": rows,
    }
    if print_list(ctx, args, payload=document, rows=rows, list_key="users", columns=COLUMNS, plain=lambda: people_text(result.people)):
        return 0
    if result.truncated:
        ctx.diagnostics.warn(f"The search was cut short after {len(rows)} of {result.total} people; use a longer name.")
    elif result.next_start is not None:
        ctx.diagnostics.info(f"{result.total} people fit, {result.next_start} shown so far. Continue with --start {result.next_start}, or use --all.")
    return 0


def run_lookup(ctx: Context, args: argparse.Namespace) -> int:
    for flag, given in (("--limit", args.limit is not None), ("--start", args.start is not None), ("--all", args.all)):
        if given:
            raise UsageError(f"{flag} applies to the search: a lookup answers for the account ids it is given, all at once.", hint="Leave it out.")
    text = query_option(ctx, args.text, "list of account ids") or ""
    result = ctx.app.users.lookup.execute(text, with_users=args.with_users)
    rows = [person_json(item) for item in result.people]
    document = {"requested": result.requested, "count": len(rows), "notFound": result.not_found, "users": rows}
    if print_list(ctx, args, payload=document, rows=rows, list_key="users", columns=COLUMNS, plain=lambda: people_text(result.people)):
        return 0
    if result.not_found:
        ctx.diagnostics.warn(
            f"Confluence describes nobody for: {', '.join(result.not_found)}. The account id is wrong, or the person cannot be looked up by this account."
        )
    return 0


def run_users(ctx: Context, args: argparse.Namespace) -> int:
    # Refused before anything is read or sent: not even the file of an `@FILE` is opened for a command that shows people to nobody who asked for them.
    ensure_people_allowed(ctx.app.settings, args.with_users, f"conflu users {args.action}")
    return run_search(ctx, args) if args.action == "search" else run_lookup(ctx, args)


COMMANDS = (
    Command(
        name="users",
        group=GROUP,
        summary="Search for people by name, or look up account ids",
        when="Use to find the account id of a person by name (action search), or to see who is behind the account ids that other commands print (action lookup). "
        "Both show people, so both need --with-users and are refused when CONFLUENCE_HIDE_USERS=true: this is the one command where people are the point.",
        description="search shows the people whose name holds the text (the older API's user search; a name with a double quote or a backslash stays a text). "
        "lookup shows the people behind up to 250 account ids (the bulk lookup of API v2); an id that Confluence does not describe is left out and "
        "listed as notFound. Both print the account id, the display name, the e-mail address when Confluence returns one, and the account type.",
        args=(
            Arg(("action",), "search: people by (part of) a name. lookup: the people behind account ids.", kind="choice", choices=ACTIONS, required=True),
            Arg(
                ("text",),
                "With search the name, or part of it; several words need no quotes. With lookup the account ids, separated by blanks or commas, at most 250. "
                "`@FILE` reads it from a file, `-` from standard input.",
                kind="words",
                metavar="TEXT",
                required=True,
                at_file=True,
            ),
            Arg(("--limit",), "With search: people per request (1 to 250, default 25; Confluence may allow fewer).", kind="int", metavar="N"),
            Arg(("--start",), "With search: index of the first person (default 0).", kind="int", metavar="N"),
            Arg(("--all",), "With search: fetch every person instead of one request (ignores --limit and --start).", kind="flag"),
            Arg(("--with-users",), "Show the people. Without it the command is refused; it is refused when CONFLUENCE_HIDE_USERS=true as well.", kind="flag"),
            SELECT,
            FORMAT,
        ),
        examples=(
            Example("conflu users search alex --with-users"),
            Example("conflu users search Alex Example --with-users --json", "several words need no quotes"),
            Example("conflu users search '@name.txt' --with-users", "the name in a file: the form that survives Windows PowerShell 5.1"),
            Example("conflu users search alex --with-users --all --select accountId,displayName --format tsv"),
            Example("conflu users lookup 5b10ac8d82e05b22cc7d4ef5 --with-users"),
            Example("conflu users lookup 5b10ac8d82e05b22cc7d4ef5 557058:00000000-0000-4000-8000-000000000001 --with-users --json"),
        ),
        notes=(
            "The name goes into a CQL string (user.fullname ~ \"...\") with its double quotes and backslashes escaped, so that whatever it holds stays a text.",
            "The e-mail address is shown only when Confluence returns one: it depends on the privacy setting of each person. A person who hides their name shows "
            "the public name.",
            "An account id that is not described is not an error: Confluence leaves it out, and `notFound` lists it. Without --with-users nothing is sent at all.",
            "The search is the v1 call GET /rest/api/search/user (API v2 has no search for people); the lookup is the v2 call POST /api/v2/users-bulk.",
            FILE_NOTE,
        ),
        json_output=True,
        output="search: query (the words), cql (what was sent), total (people that fit), count, start, nextStart (null on the last request and with --all), "
        "truncated and users[]. lookup: requested (different ids asked for), count, notFound[] (ids Confluence did not describe) and users[]. users[]: "
        "accountId, displayName, email, accountType; null for what Confluence does not say; with --select only those (dotted) keys of every person.",
        handler=run_users,
    ),
)
