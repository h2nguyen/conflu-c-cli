"""Content properties: what an app, or a person, stores under a key on a page and on other content.

A property is a piece of JSON with a key and a version. Apps keep their settings and their marks in them, so a property is not a note of the
person who reads it: changing one that an app owns can change what the app does. The CLI reads them and sets them, and deletes none.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .content import describe, kind_named
from .errors import UsageError, ValidationError
from .privacy import EMAIL_MARKER, HIDDEN, LINK_MARKER, PERSONAL_SPACE, blanked_attributes, redact_text, strip_users

MAX_KEY = 255
MAX_VALUE_BYTES = 32 * 1024  # the value as it is sent: compact JSON, in UTF-8
MAX_DEPTH = 100  # arrays and objects inside each other; far more than any app writes, far less than what the interpreter can walk
MAX_EMBEDDED_CHARS = 1_000_000  # the longest text that is read as the JSON it may hold, when a reading hides the people in it
MAX_EMBEDDED_LAYERS = 3  # texts inside texts: JSON that was encoded twice is a text of a text; nobody does it three times on purpose
TOO_DEEP = "[nested too deeply to show]"
CUT_MARKER = "[value cut]"  # what ends the text of a value that a reading cut: it is the beginning of the value, not the value

_KEY = re.compile(r"[A-Za-z0-9_.:-]{1,255}")
_BARE_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_ .-]*")
_SURROGATE = re.compile("[\ud800-\udfff]")  # what no UTF-8 text can hold: a terminal that is asked to show it fails
_JSON_START = re.compile(r'\{\s*["}]|\[\s*["{\[\]\-0-9tfn]|"')  # how a text that may be JSON begins: `[hidden]` and `{{macro}}` are not tried
# The two forms of an Atlassian account id: 24 hexadecimal digits, and a number and a UUID behind a colon. One is taken for an account id wherever it stands
# in a text and is not part of a longer word (a hash of 40 digits is not one), because apps write them into links, wiki markup and sentences. Upper case counts
# too: a program that writes an id in capitals has written the id of a person all the same.
_ACCOUNT_ID = re.compile(
    r"(?<![0-9A-Za-z])(?:[0-9a-f]{24}|[0-9]{3,8}:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?![0-9A-Za-z])", re.IGNORECASE
)

# The kinds of content that have properties besides the kinds of the tree (`domain.content`): Confluence's own name for them, and the collection of the v2 API.
_OTHER_HOLDERS = {"attachment": "attachments", "footer-comment": "comments", "inline-comment": "comments"}
HOLDERS_SENTENCE = "a page, a blog post, a folder, a whiteboard, a database, a smart link, an attachment or a comment"

VALUE_HINT = (
    "Write the value as JSON: a text needs its own double quotes ('\"text\"'), a number, true, false, null, an array and an object do not. "
    "Windows PowerShell 5.1 removes the double quotes inside an argument, so put the value into a file and pass --file FILE (or - for standard input)."
)


@dataclass(frozen=True)
class ContentProperty:
    id: str
    key: str
    version: int = 1
    value: Any = None  # any JSON value
    updated: str = ""  # when this version was saved


def collection_of(type_name: str) -> str | None:
    """The collection of the v2 API that holds the properties of the content that Confluence calls `type_name` (`page`, `footer-comment` ...), or None."""
    kind = kind_named(type_name)
    return kind.collection if kind is not None else _OTHER_HOLDERS.get(type_name)


def named(type_name: str, content_id: str) -> str:
    """`the page 2002`, `the footer comment 4001`: how a message names the content that holds a property."""
    return f"the {describe(type_name).removeprefix('an ').removeprefix('a ')} {content_id}"


def validate_key(key: str) -> str:
    if not _KEY.fullmatch(key or ""):
        raise UsageError(
            f"A property key holds letters, digits and the characters _ . : - only, from 1 to {MAX_KEY} characters.",
            hint="For example team.review or my-app:state. Keys are case sensitive.",
        )
    return key


def compact(value: Any) -> str:
    """The value as one line of JSON without blanks."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def nesting(value: Any) -> int:
    """How deeply arrays and objects stand inside each other in the value (0 for a plain value). Counted without recursion, so that a value that
    nests too deeply for the interpreter can still be judged."""
    deepest = 0
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if isinstance(item, dict):
            children: Any = item.values()
        elif isinstance(item, list):
            children = item
        else:
            continue
        deepest = max(deepest, depth + 1)
        pending.extend((child, depth + 1) for child in children)
    return deepest


def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not JSON")


class _NumberTooLarge(ValueError):
    pass


def _finite_float(text: str) -> float:
    """Every number with a fraction or an exponent that the value holds, at any depth, comes through here: `1e999` is a number to the grammar, and `Infinity` to
    the interpreter, which prints it as `Infinity` (not JSON) and sends it so."""
    number = float(text)
    if math.isinf(number):
        raise _NumberTooLarge(text)
    return number


def parse_value(text: str, where: str) -> Any:
    """The JSON value that a person typed (`where` names the place: `--value`, or the file) and that may be sent: valid JSON, at most 32 KiB, of a
    depth that no app writes."""
    body = (text or "").strip()
    if not body:
        raise UsageError(f"The value is empty: {where} holds no JSON.", hint=VALUE_HINT)
    try:
        value = json.loads(body, parse_float=_finite_float, parse_constant=_no_constant)
    except RecursionError:
        raise ValidationError(f"The value nests arrays and objects too deeply (more than {MAX_DEPTH} levels).") from None
    except _NumberTooLarge as error:
        raise UsageError(
            f"The value is not valid JSON: {str(error)[:40]} is too large for a number (the most is about 1.8e308).",
            hint="JSON has no infinity: write a number that a program can store, or a text in double quotes.",
        ) from None
    except ValueError as error:
        if _BARE_WORD.fullmatch(body):
            problem = f"'{body[:40]}' is a word, and a text needs double quotes"
        elif isinstance(error, json.JSONDecodeError):
            problem = f"{error.msg} (position {error.pos})"
        else:
            problem = str(error)
        raise UsageError(f"The value is not valid JSON: {problem}.", hint=VALUE_HINT) from None
    if nesting(value) > MAX_DEPTH:
        raise ValidationError(f"The value nests arrays and objects too deeply (more than {MAX_DEPTH} levels).")
    try:
        size = len(compact(value).encode("utf-8"))
    except UnicodeEncodeError:
        raise ValidationError("The value holds a character that is not valid Unicode (half of a surrogate pair).", hint="Write the character itself, or leave it out.") from None
    if size > MAX_VALUE_BYTES:
        raise ValidationError(
            f"The value is {size:,} bytes as compact JSON; a property holds at most {MAX_VALUE_BYTES // 1024} KiB.",
            hint="Keep the data in a page or an attachment, and the property for a key and a small value.",
        )
    return value


def _comparable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _comparable(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_comparable(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)  # 1.0 and 1 are one number in JSON
    return value


def same_value(first: Any, second: Any) -> bool:
    """Whether two values are the same JSON: objects have no order, 1 and 1.0 are the same number, and 1 and true are not (Python says they are)."""
    try:
        return json.dumps(_comparable(first), sort_keys=True) == json.dumps(_comparable(second), sort_keys=True)
    except (RecursionError, TypeError, ValueError):
        return False


def _clean(text: str, hide_people: bool) -> str:
    text = _SURROGATE.sub("\ufffd", text)
    if not hide_people:
        return text
    return redact_text(_ACCOUNT_ID.sub(HIDDEN, text))


def _embedded_json(text: str, depth: int) -> tuple[int, Any] | None:
    """`(layers, value)` for a text that holds an object or an array as JSON text (`layers` counts the texts that are in the way: an app that encodes twice by
    mistake stores the text of a text), else None. A text that is not JSON, one that is too long, and one that would nest the value deeper than `MAX_DEPTH`
    stay what they are: a text."""
    layers = 0
    held = text
    while layers <= MAX_EMBEDDED_LAYERS:
        held = held.strip()
        if len(held) > MAX_EMBEDDED_CHARS or not _JSON_START.match(held):
            return None
        try:
            value = json.loads(held, parse_float=_finite_float, parse_constant=_no_constant)
        except (ValueError, RecursionError):
            return None
        if isinstance(value, str):
            held, layers = value, layers + 1
            continue
        return (layers, value) if isinstance(value, (dict, list)) and depth + nesting(value) <= MAX_DEPTH else None
    return None


def _shown_text(text: str, hide_people: bool, depth: int) -> str:
    """A text of a value as it may be printed. JSON that an app stored as a text (`JSON.stringify` makes one) is read as JSON, so that a user object in it is
    hidden for what it is: a display name is neither an address nor an id, and a text rule cannot see it. It is printed as compact JSON again when something
    in it was hidden, and as it is when nothing was."""
    if hide_people:
        embedded = _embedded_json(text, depth)
        if embedded is not None:
            layers, parsed = embedded
            tidied = _tidy(strip_users(parsed), True, depth + 1)
            if tidied != parsed:
                shown = compact(tidied)
                for _ in range(layers):
                    shown = json.dumps(shown, ensure_ascii=False)
                return shown
    return _clean(text, hide_people)


def _tidy(value: Any, hide_people: bool, depth: int = 0) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        seen: dict[str, int] = {}
        for key, child in value.items():
            base = _clean(str(key), hide_people)
            seen[base] = seen.get(base, 0) + 1
            name = base if seen[base] == 1 else f"{base} ({seen[base]})"  # two keys that look alike once they are hidden stay two
            while name in result:
                name += "+"
            result[name] = _tidy(child, hide_people, depth + 1)
        return result
    if isinstance(value, list):
        return [_tidy(item, hide_people, depth + 1) for item in value]
    if isinstance(value, str):
        return _shown_text(value, hide_people, depth)
    return value


def shown_value(value: Any, *, with_users: bool) -> Any:
    """The value as it may be printed. Without `with_users` no person is in it: user objects, account ids (as a value, inside a text and as the key of an
    object), e-mail addresses and personal links are hidden. With it, or without it, no text of it holds half of a surrogate pair, which no
    terminal can show."""
    if nesting(value) > MAX_DEPTH:
        return TOO_DEEP
    return _tidy(value if with_users else strip_users(value), not with_users)


def shown_key(key: str, *, with_users: bool) -> str:
    """A key as it may be printed: it is free text, so without `with_users` an e-mail address or an account id in it is hidden too."""
    return _clean(key, not with_users)


def shown_text(value: Any, max_chars: int) -> tuple[str, bool, int]:
    """`(text, cut, size)`: the value as compact JSON and the size of the whole. A value longer than `max_chars` characters (0 cuts nothing) is its beginning
    followed by `CUT_MARKER`: a copy that was cut says so in itself, so that it cannot pass for the value, and `property-set` refuses it."""
    text = compact(value)
    if max_chars and len(text) > max_chars:
        return text[:max_chars] + CUT_MARKER, True, len(text)
    return text, False, len(text)


USER_OBJECT = '{"hidden": true}'  # what a reading shows in the place of a user object
# What a reading shows in the place of people (and of a value that is too deep to show), in the order in which a message names it. The rest of the stand-ins
# are the attributes that `redact_storage` blanks in a text that is storage format (`ri:account-id="hidden"`, `data-userkey="hidden"`, `ri:space-key="[hidden]"`),
# read with `privacy.blanked_attributes` so that this list cannot fall behind the one that blanks them, and `CUT_MARKER`, which no person is behind.
STAND_INS = (HIDDEN, EMAIL_MARKER, LINK_MARKER, PERSONAL_SPACE, USER_OBJECT, TOO_DEEP)
_TEXT_MARKERS = (HIDDEN, EMAIL_MARKER, LINK_MARKER, PERSONAL_SPACE, TOO_DEEP, CUT_MARKER)
_FIXED = frozenset((*STAND_INS, CUT_MARKER))


def markers_in(value: Any) -> Counter[str]:
    """How often a value holds each stand-in for people, and the end mark of a cut value, in its texts, in its keys and as an object: every occurrence, the
    blanked attributes of a text each by itself. Walked without recursion, like `nesting`."""
    found: Counter[str] = Counter()
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            if len(item) == 1 and item.get("hidden") is True:
                found[USER_OBJECT] += 1
            pending.extend(item.values())
            texts: list[str] = [key for key in item if isinstance(key, str)]
        elif isinstance(item, list):
            pending.extend(item)
            continue
        elif isinstance(item, str):
            texts = [item]
        else:
            continue
        for text in texts:
            for mark in _TEXT_MARKERS:
                if mark in text:
                    found[mark] += text.count(mark)
            found.update(blanked_attributes(text))
    return found


def markers_written_back(new: Any, current: Any, shown: Any) -> list[str]:
    """The stand-ins for people that `new` holds more often than the property `current` holds them itself, where a reading of it (`shown`, see `shown_value`)
    holds them more often too: somebody read the property, changed what they saw and wants to write it back, and saving that would overwrite the
    people with the stand-ins. A stand-in that the property holds itself (an app's flag `{"hidden": true}`, a text with `[email]` in it) is none of them.
    The end mark of a cut value (`CUT_MARKER`) comes last when `new` holds it more often than `current` does: it needs no reading of the property, because
    a value that was cut is never what the property holds, and it is refused when the property is new as well (`current` and `shown` are then None)."""
    read, held, written = markers_in(shown), markers_in(current), markers_in(new)
    blanked = sorted(mark for mark in written if mark not in _FIXED)
    found = [mark for mark in (*STAND_INS, *blanked) if written[mark] > held[mark] and read[mark] > held[mark]]
    if written[CUT_MARKER] > held[CUT_MARKER]:
        found.append(CUT_MARKER)
    return found


def texts_in(value: Any) -> set[str]:
    """Every text of a value: its strings and the keys of its objects, but the key of the object that stands for a person (`{"hidden": true}`): that one is a
    stand-in and no text of the property. Walked without recursion, like `nesting`."""
    found: set[str] = set()
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            if not (len(item) == 1 and item.get("hidden") is True):
                found.update(key for key in item if isinstance(key, str))
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, str):
            found.add(item)
    return found


def altered_texts_written_back(new: Any, current: Any, shown: Any) -> list[str]:
    """The texts of `new` that a reading of the property (`shown`) holds and the property (`current`) holds in no place: the reading changed them (the address
    of a page loses the title when that holds an e-mail address), and somebody who copied them back would overwrite the originals. A text that holds a
    stand-in of its own is counted by `markers_written_back` and is not in this list. It is the text that counts and not the place: a text that the property
    holds in another place as well is not found here (`copied_places` finds it where it stands in the place of the original)."""
    changed = texts_in(shown) - texts_in(current)
    return sorted(text for text in texts_in(new) & changed if not any(mark in text for mark in _TEXT_MARKERS) and not blanked_attributes(text))


def copied_places(new: Any, current: Any, shown: Any) -> list[tuple[Any, Any]]:
    """Where `new` holds what a reading (`shown`) shows and the property (`current`) does not, as `(what the reading shows there, what the property holds there)`.
    The three are walked together from the top, position by position, and only where the reading changed something: a reading keeps the order and the number of
    the members of an object and of a list, so the place of a member is the same in all three (an object is looked up by its own key, or by the key that the
    reading made of it). This is what the counts cannot see: a stand-in that the property holds itself somewhere else does not hide a person that was
    replaced by one, and a text that the property holds in another place does not hide the address that lost its title. A copy that was moved to another place is
    found by the counts and by the texts instead."""
    found: list[tuple[Any, Any]] = []
    pending = [(new, current, shown)]
    while pending:
        part, held, read = pending.pop()
        if same_value(read, held):
            continue  # the reading changed nothing here, so nothing that is written here is a copy of it
        if same_value(part, read):
            found.append((read, held))
            continue
        if isinstance(part, dict) and isinstance(held, dict) and isinstance(read, dict) and len(held) == len(read):
            for (real_key, held_child), (shown_key, read_child) in zip(held.items(), read.items()):
                if real_key in part:
                    pending.append((part[real_key], held_child, read_child))
                elif shown_key in part:
                    if shown_key != real_key:
                        found.append((shown_key, real_key))  # the key that the reading made of it stands where the key of the property was
                    pending.append((part[shown_key], held_child, read_child))
        elif isinstance(part, list) and isinstance(held, list) and isinstance(read, list) and len(held) == len(read):
            pending.extend(zip(part, held, read))
    return found


def copies_written_back(new: Any, current: Any, shown: Any) -> tuple[list[str], list[str]]:
    """`(markers, texts)`: everything that makes `new` a copy of what a reading showed of the property, where the reading is `shown` (`shown_value`) and the
    property is `current`. The markers are the stand-ins and the end mark of a cut value, in the order in which a message names them (`markers_written_back`,
    and those that a copied place holds); the texts are the changed texts that hold no marker (`altered_texts_written_back`, and those that a copied place holds).
    Both are empty for a value that is no copy, and for a property that is new (`current` and `shown` are None): only the end mark of a cut value is found there."""
    markers = markers_written_back(new, current, shown)
    texts = altered_texts_written_back(new, current, shown)
    places = copied_places(new, current, shown)
    for read, held in places:
        shown_marks, held_marks = markers_in(read), markers_in(held)
        markers += [mark for mark in shown_marks if mark != CUT_MARKER and shown_marks[mark] > held_marks[mark] and mark not in markers]  # the end mark of a cut: by its count alone
        texts += [text for text in sorted(texts_in(read) - texts_in(held)) if text not in texts and not any(mark in text for mark in _TEXT_MARKERS) and not blanked_attributes(text)]
    people = [mark for mark in markers if mark != CUT_MARKER]
    ordered = [mark for mark in STAND_INS if mark in people] + sorted(mark for mark in people if mark not in _FIXED)
    if places and not markers and not texts:
        texts = [compact(read)[:80] for read, _ in places[:3]]  # a change that this module does not know by a marker or a text: it is still a copy, and the message shows it
    return ordered + ([CUT_MARKER] if CUT_MARKER in markers else []), texts


def create_payload(key: str, value: Any) -> dict[str, Any]:
    return {"key": key, "value": value}


def update_payload(key: str, value: Any, number: int, message: str = "") -> dict[str, Any]:
    """What `PUT .../properties/{id}` takes. `number` is the current version plus one: Confluence refuses it when somebody saved the property meanwhile."""
    version: dict[str, Any] = {"number": number}
    if message:
        version["message"] = message
    return {"key": key, "value": value, "version": version}
