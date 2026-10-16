"""CQL, the query language of Confluence search, built from the options of `conflu search`."""
from __future__ import annotations

import re
from typing import Sequence

from .errors import ValidationError
from .searchterms import Term, Terms, parse_terms

CONTENT_TYPES = ("page", "blogpost", "attachment", "comment", "any")
MATCH_MODES = ("all", "any")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def quote(value: str) -> str:
    """A CQL string: in double quotes, with the quote and the backslash escaped."""
    cleaned = _CONTROL.sub(" ", value)
    return '"' + cleaned.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _value(term: Term) -> str:
    return f'"{term.text}"' if term.phrase else term.text


def text_clause(terms: Sequence[Term], match: str = "all") -> str:
    """The clause for the words and phrases of a search.

    `all`: every word and phrase must occur (`text ~ "a b"`; each phrase is a clause of its own). `any`: one is enough
    (`(text ~ "a" OR text ~ "b")`). Confluence ranks by relevance, so with `any` the pages that hold most of them come first."""
    if match not in MATCH_MODES:
        raise ValidationError(f"Unknown match mode: {match}", hint=f"Use one of: {', '.join(MATCH_MODES)}.")
    if not terms:
        return ""
    if match == "any" and len(terms) > 1:
        return "(" + " OR ".join(f"text ~ {quote(_value(term))}" for term in terms) + ")"
    words = [term.text for term in terms if not term.phrase]
    parts = [f"text ~ {quote(' '.join(words))}"] if words else []
    parts += [f"text ~ {quote(_value(term))}" for term in terms if term.phrase]
    return " AND ".join(parts)


def content_search(
    *,
    text: str = "",
    terms: Terms | None = None,
    match: str = "all",
    space: str = "",
    content_type: str = "page",
    label: str = "",
    title: str = "",
    under: str = "",
    since: str = "",
    cql: str = "",
) -> str:
    """The query for the options given. A query written by hand (`cql`) is used as it is.

    The words come from `terms` when the caller has parsed them (to report what was left out), else from `text`."""
    if cql.strip():
        return cql.strip()
    if since and not _DATE.fullmatch(since):
        raise ValidationError(f"Not a date: {since}", hint="Write the date as YYYY-MM-DD, for example 2026-10-01.")
    if under and not re.fullmatch(r"[0-9]+", under):
        raise ValidationError(f"Not a page id: {under}", hint="--under takes the numeric id of the page whose descendants to search.")
    if content_type not in CONTENT_TYPES:
        raise ValidationError(f"Unknown content type: {content_type}", hint=f"Use one of: {', '.join(CONTENT_TYPES)}.")
    parsed = terms if terms is not None else parse_terms(text)
    clauses: list[str] = []
    if space:
        clauses.append(f"space = {quote(space)}")
    if parsed:
        clauses.append(text_clause(parsed.used, match))
    if title:
        clauses.append(f"title ~ {quote(title)}")
    if label:
        clauses.append(f"label = {quote(label)}")
    if under:
        clauses.append(f"ancestor = {under}")
    if since:
        clauses.append(f"lastmodified >= {quote(since)}")
    if not clauses:
        raise ValidationError("Nothing to search for.", hint="Give a text, or --space, --title, --label, --under, --since or --cql.")
    if content_type != "any":
        clauses.insert(0, f"type = {content_type}")
    query = " AND ".join(clauses)
    return query if parsed else f"{query} ORDER BY lastmodified DESC"
