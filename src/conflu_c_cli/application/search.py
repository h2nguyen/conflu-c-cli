"""Use cases around search."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Sequence

from ..domain import cql as cql_builder
from ..domain.errors import ConfluCliError, UsageError
from ..domain.model import SearchHit, Space, parse_page_id, parse_space_key, space_key_from_link
from ..domain.privacy import PERSONAL_SPACE, hide_hit, hide_space, is_personal_space, redact_query, strip_users
from ..domain.searchterms import Term, Terms, parse_terms, terms_from_cql
from ..domain.snippets import find_passages, lead, matched_terms
from .paging import ensure_users_allowed
from .ports import ConfluenceGateway
from .rendering import render_body
from .settings import Settings

SEARCH_PAGE = 50
MAX_HITS = 5000
MAX_SNIPPETS = 25
MATCH_MODES = ("all", "any", "auto")


@dataclass
class SearchResult:
    hits: list[SearchHit]
    total: int
    start: int
    cql: str
    truncated: bool = False
    raw_results: list[dict[str, Any]] = field(default_factory=list)
    excerpts_shown: bool = False  # they can name people: only with `with_users`
    terms: tuple[str, ...] = ()  # what was searched for, as it went into the query
    ignored: tuple[str, ...] = ()  # filler words that were left out of the query
    match: str = "all"  # all | any | cql
    relaxed: bool = False  # no page held every word, so the pages that hold some of them are shown
    notes: list[str] = field(default_factory=list)  # for the person at the terminal


@dataclass
class _Found:
    hits: list[SearchHit]
    raw: list[dict[str, Any]]
    total: int
    truncated: bool
    start: int


PERSON = "user"  # what the search index calls a person among its results: `type = user` finds people, not pages


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _is_person(item: dict[str, Any]) -> bool:
    """A raw result that is a person (`entityType: user`)."""
    return item.get("entityType") == PERSON or _object(item.get("content")).get("type") == PERSON


def _shown(hit: SearchHit) -> SearchHit:
    """A hit as it may be printed when people are not shown. A hit about a space goes through the rule of the space commands (`hide_space`): a personal
    space is named after its owner and keyed by the owner's account id, so it comes out with the key `[hidden]`, the name `[personal space]` and no address."""
    if hit.type == "space":
        space = hide_space(Space(id=hit.id, key=hit.space_key, name=hit.title, url=hit.url))
        hit = replace(hit, space_key=space.key, title=space.name, url=space.url)
    return hide_hit(hit)


def _in_personal_space(item: dict[str, Any]) -> bool:
    """A raw result that is a personal space, or lies in one."""
    inner, space, container = _object(_object(item.get("content")).get("space")), _object(item.get("space")), _object(item.get("resultGlobalContainer"))
    return any(
        is_personal_space(key, kind)
        for key, kind in (
            (inner.get("key"), inner.get("type")),
            (space.get("key"), space.get("type")),
            (space_key_from_link(str(item.get("url") or "")), ""),
            (space_key_from_link(str(container.get("displayUrl") or "")), ""),
        )
    )


def _shown_item(item: dict[str, Any]) -> dict[str, Any]:
    """The raw answer for one result as it may be printed when people are not shown: its people, texts and addresses cleaned as `conflu api` cleans them,
    and where the result is a personal space or lies in one, the name of the space (the name of its owner) replaced as `hide_space` does."""
    shown = {**strip_users(item), "excerpt": None}
    if _in_personal_space(item):
        container = _object(shown.get("resultGlobalContainer"))
        if container:
            shown["resultGlobalContainer"] = {**container, "title": PERSONAL_SPACE, "displayUrl": ""}
        if item.get("entityType") == "space":
            shown["title"], shown["url"] = PERSONAL_SPACE, ""
    return shown


class SearchContent:
    def __init__(self, gateway: ConfluenceGateway, settings: Settings) -> None:
        self._gateway = gateway
        self._settings = settings

    def execute(
        self,
        *,
        text: str = "",
        space: str = "",
        content_type: str = "page",
        label: str = "",
        title: str = "",
        under: str = "",
        since: str = "",
        cql: str = "",
        limit: int = 25,
        start: int = 0,
        fetch_everything: bool = False,
        with_users: bool = False,
        match: str = "auto",
        snippets: int = 0,
    ) -> SearchResult:
        ensure_users_allowed(with_users, self._settings)
        if match not in MATCH_MODES:
            raise UsageError(f"Unknown match mode: {match}", hint=f"Use one of: {', '.join(MATCH_MODES)}.")
        if not 0 <= snippets <= MAX_SNIPPETS:
            raise UsageError(f"--snippets must be between 0 and {MAX_SNIPPETS}.")
        by_hand = bool(cql.strip())
        parsed = Terms(terms_from_cql(cql), ()) if by_hand else parse_terms(text)
        options: dict[str, Any] = dict(
            space=parse_space_key(space) if space else "",
            content_type=content_type,
            label=label.strip(),
            title=title.strip(),
            under=parse_page_id(under) if under else "",
            since=since.strip(),
            cql=cql,
        )
        mode = "cql" if by_hand else ("any" if match == "any" else "all")
        query = cql_builder.content_search(terms=parsed, match="any" if mode == "any" else "all", **options)
        found = self._find(query, limit=limit, start=start, everything=fetch_everything)
        relaxed = False
        if match == "auto" and not by_hand and found.total == 0 and len(parsed.used) > 1:
            mode, relaxed = "any", True
            query = cql_builder.content_search(terms=parsed, match="any", **options)
            found = self._find(query, limit=limit, start=start, everything=fetch_everything)
        searched = found.total  # what the search found, people included
        left_out = 0
        if not with_users:
            found, left_out = self._without_people(found)
        notes: list[str] = []
        shown = [term.display for term in parsed.used]
        if relaxed:
            notes.append(f"No page holds all of these words ({', '.join(shown)}); these pages hold some of them. `--match all` makes the search strict again.")
        if parsed.ignored:
            notes.append(f"Left out as filler: {', '.join(parsed.ignored)}. Put a word in quotes to keep it.")
        if left_out:
            notes.append(self._left_out_note(left_out))
        if searched == 0:
            notes.append(
                "Nothing found. The pages may be written in another language than your words (the search does not translate): try the words "
                "of the pages, fewer or shorter words, a wildcard such as rol*, or `--match any`. `conflu how-to find-information` says more."
            )
        hits = found.hits
        if snippets and hits:
            hits, note = self._add_snippets(hits, parsed.used, snippets, with_users=with_users)
            if note:
                notes.append(note)
        common = dict(terms=tuple(shown), ignored=parsed.ignored, match=mode, relaxed=relaxed, notes=notes)
        if with_users:
            return SearchResult(hits, found.total, found.start, query, found.truncated, found.raw, excerpts_shown=True, **common)
        return SearchResult(
            [_shown(hit) for hit in hits],
            found.total,
            found.start,
            redact_query(query),  # the query that ran names the personal space that was searched: the key is the account id of its owner
            found.truncated,
            [_shown_item(item) for item in found.raw],
            **common,
        )

    @staticmethod
    def _without_people(found: _Found) -> tuple[_Found, int]:
        """What the search index finds is not only pages: `type = user` finds people, with their names and account ids in the address. They are listed
        only with `--with-users`, as everywhere else, so without it they are left out of the hits and of the raw answer, and counted (`total` still
        says what was found). Returns what is left, and how many hits were left out."""
        hits = [hit for hit in found.hits if hit.type != PERSON]
        raw = [item for item in found.raw if not _is_person(item)]
        return replace(found, hits=hits, raw=raw), len(found.hits) - len(hits)

    def _left_out_note(self, count: int) -> str:
        """For the person at the terminal, without a name: how many hits are missing, and why."""
        many = count != 1
        head = f"{count} {'hits' if many else 'hit'} about people {'were' if many else 'was'} left out"
        if self._settings.hide_users:
            return f"{head}: CONFLUENCE_HIDE_USERS=true keeps people out of every answer."
        return f"{head}: people are listed only with --with-users. Add it to see them."

    def _find(self, query: str, *, limit: int, start: int, everything: bool) -> _Found:
        if not everything:
            page = self._gateway.search(query, limit=limit, start=start)
            return _Found(page.hits, page.raw_results, page.total, False, start)
        hits: list[SearchHit] = []
        raw: list[dict[str, Any]] = []
        total, truncated, position = 0, False, 0
        while True:
            page = self._gateway.search(query, limit=SEARCH_PAGE, start=position)
            total = page.total
            hits.extend(page.hits)
            raw.extend(page.raw_results)
            position += len(page.hits)
            if not page.hits or position >= total:
                break
            if position >= MAX_HITS:
                truncated = True
                break
        return _Found(hits, raw, total, truncated, 0)

    def _add_snippets(self, hits: list[SearchHit], terms: Sequence[Term], count: int, *, with_users: bool) -> tuple[list[SearchHit], str]:
        """The passage around the words for the first `count` pages, from one request that reads them all.

        The passage is cut from the page as `conflu page` shows it, so people stay out of it exactly as they do there. The excerpt of
        the search index cannot do that: it writes the name of a mentioned person into the text."""
        selected = [hit for hit in hits[:count] if hit.type == "page" and hit.id]
        if not selected:
            return hits, ""
        try:
            pages = self._gateway.list_pages(ids=[hit.id for hit in selected], status="current", with_body=True, limit=len(selected)).items
        except ConfluCliError as error:
            return hits, f"The passages could not be read: {error.message}"
        bodies = {page.id: page.body or "" for page in pages}
        result: list[SearchHit] = []
        for hit in hits:
            body = bodies.get(hit.id)
            if body is None:
                result.append(hit)
                continue
            text = render_body(body, "text", with_users=with_users).text
            passages = find_passages(text, terms)
            seen = set(passages.matched) | set(matched_terms(hit.title, terms))
            result.append(replace(hit, snippet=passages.text or lead(text), matched=tuple(term.display for term in terms if term.display in seen)))
        return result, ""
