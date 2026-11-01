"""Which REST calls the two Confluence Cloud documents list, and what a request is, measured against them.

The mock Confluence answers HTTP 404 to a call that the matching document does not list and records it, so that a command cannot
come to depend on an endpoint of another API or of an older one. The lists (`confluence_cloud_v2_endpoints.txt`,
`confluence_cloud_v1_endpoints.txt`) say where they come from. A request is judged by its path below the wiki address: `/api/v2/...` is
measured against the v2 document, `/rest/...` against the v1 document, and anything else against `OUTSIDE_THE_REFERENCE`.

The parameter files (`confluence_cloud_v2_parameters.txt`, `confluence_cloud_v1_parameters.txt`) give each of those operations its query
parameters, its required headers and its request body. `request_problems` says what is wrong with a request that is measured against them; the
mock refuses such a request when its `strict_parameters` is on. The files are written by `scripts/update_endpoint_lists.py`, which says in their
header what a line means; `parse_rules` is the reader of that format. The mock judges only what is sent, so `names_in_source` reads the source of the REST
adapters for the query parameters that they can put into a request, and the conformance test asks that some line of the sweep sends each one. In the same way
`options_without_a_line` lists the options of the commands that no line names, and the test asks for a line or a reason (`NOT_SWEPT`) for each.
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

HERE = Path(__file__).parent
V2_LIST = HERE / "confluence_cloud_v2_endpoints.txt"
V1_LIST = HERE / "confluence_cloud_v1_endpoints.txt"
V2_PARAMETERS = HERE / "confluence_cloud_v2_parameters.txt"
V1_PARAMETERS = HERE / "confluence_cloud_v1_parameters.txt"
V2_PREFIX = "/api/v2/"
V1_PREFIX = "/rest/"

# What is no REST call, so in neither document: the address of a file that a media service serves (the transport follows it from a
# documented download), and the public tenant information that `conflu setup --discover` reads. The mock serves them, and records them
# in `outside_calls`: the sweep of the commands names the command that may make each one.
OUTSIDE_THE_REFERENCE: tuple[tuple[str, str], ...] = (
    ("GET", "/download/attachments/{pageId}/{name}"),
    ("GET", "/_edge/tenant_info"),
)

# What Confluence accepts although the matching document does not list it, so that the mock does not refuse it either:
# `(call as the lists write it, "query" or "body", name)` -> why it is believed to be accepted. Keep it empty unless there is a reason: the
# document wins, and a parameter that is only missing from the document is a finding to report, not to hide here.
ACCEPTED_BUT_UNDOCUMENTED: dict[tuple[str, str, str], str] = {}

# A query parameter that the adapters put into a request and that no line of a sweep can send, with why: `name -> reason`. Keep it empty: a name that is
# only missing from the sweep gets a line that sends it, in the sweep module of its area (`tests/support/sweep_<area>.py`).
NEVER_SENT_IN_A_SWEEP: dict[str, str] = {}

# The options of the commands that no line of any sweep module names, each with why: `(command, the option as its spec names it first) -> reason`. A line is what
# makes the strict mock judge the request of an option and the privacy sweep read its output, so an option gets a line (in `tests/support/sweep_<area>.py`) unless
# no line could show anything of it. The table is to shrink: an entry that a line has made redundant is refused, and so is an option that is in neither place.
_CONVERT = (
    "A local conversion: it reads a file or standard input and asks Confluence for nothing, so a sweep has no request to judge and no Confluence text to read; "
    "tests/cli/test_out_option.py and tests/integration/test_out_flow.py run the option."
)
_MCP = (
    "It decides which tools the server offers (the ones that write, the ones that write files, people in the answers); the line of `mcp` in the sweep only pings the "
    "server, and tests/cli/test_mcp_server.py and tests/integration/test_mcp_process.py start it with each switch."
)
NOT_SWEPT: dict[tuple[str, str], str] = {
    ("convert", "--out"): _CONVERT,
    ("convert", "--force"): _CONVERT,
    ("mcp", "--allow-write"): _MCP,
    ("mcp", "--allow-files"): _MCP,
    ("mcp", "--show-users"): _MCP,
    ("mcp", "--group"): _MCP,
}


@dataclass(frozen=True)
class Call:
    """A request as the documents see it."""

    method: str
    path: str
    version: str  # v2, v1, or empty when the path is below neither API
    template: str = ""  # the documented path template that it matches, such as /api/v2/pages/{id}
    documented: bool = False
    deprecated: bool = False
    outside: bool = False  # no REST call, and allowed as such (see OUTSIDE_THE_REFERENCE)

    @property
    def text(self) -> str:
        return f"{self.method} {self.path}" + (f" ({self.version} document)" if self.version else "")

    @property
    def key(self) -> str:
        """`GET /api/v2/pages/{id}`: the call as the documents write it."""
        return f"{self.method} {self.template or self.path}"


def _regex(template: str) -> "re.Pattern[str]":
    parts = re.split(r"(\{[^}]+\})", template)
    return re.compile("^" + "".join("[^/]+" if part.startswith("{") else re.escape(part) for part in parts) + "$")


@lru_cache(maxsize=None)
def _read(version: str) -> tuple[tuple[str, str, bool, "re.Pattern[str]"], ...]:
    found = []
    for line in (V2_LIST if version == "v2" else V1_LIST).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        method, template, *flags = line.split()
        found.append((method, template, "deprecated" in flags, _regex(template)))
    return tuple(found)


def documented_calls(version: str) -> list[tuple[str, str, bool]]:
    """`(method, path template, deprecated)` of every operation of the document."""
    return [(method, template, deprecated) for method, template, deprecated, _ in _read(version)]


def version_of(path: str) -> str:
    if path.startswith(V2_PREFIX):
        return "v2"
    if path.startswith(V1_PREFIX):
        return "v1"
    return ""


def classify(method: str, path: str) -> Call:
    """The call that a request is. `path` is below the wiki address and has no query."""
    method = method.upper()
    version = version_of(path)
    if version:
        for known, template, deprecated, pattern in _read(version):
            if known == method and pattern.match(path):
                return Call(method, path, version, template, documented=True, deprecated=deprecated)
        return Call(method, path, version)
    for known, template in OUTSIDE_THE_REFERENCE:
        if known == method and _regex(template).match(path):
            return Call(method, path, "", template, outside=True)
    return Call(method, path, "")


def is_documented(method: str, path: str) -> bool:
    return classify(method, path).documented


def template_of(method: str, path: str) -> str | None:
    call = classify(method, path)
    return call.template or None


# --- the parameter files ----------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ParameterRule:
    """A query parameter or a header of an operation."""

    name: str
    required: bool = False
    deprecated: bool = False
    maximum: int | None = None  # the documented maximum of `limit`


@dataclass(frozen=True)
class BodyShape:
    """One thing that a JSON body may be: an object with these top-level properties `(name, required)`, an array, or anything."""

    kind: str  # "object", "array" or "any"
    properties: tuple[tuple[str, bool], ...] = ()
    open: bool = False  # other properties are accepted as well


@dataclass(frozen=True)
class OperationRules:
    """What the document says about the parameters and the body of one operation."""

    method: str
    template: str
    query: tuple[ParameterRule, ...] = ()
    headers: tuple[ParameterRule, ...] = ()
    body: str = "none"  # "none", "json", or "other" (a request that is not JSON, such as a multipart upload)
    body_required: bool = False
    shapes: tuple[BodyShape, ...] = ()  # what a JSON body may be
    media: str = ""  # the media type of a body that is not JSON
    fields: tuple[tuple[str, bool], ...] = ()  # its form fields `(name, required)`


_ITEM = re.compile(r"(?P<name>[^\s,*<>(){}|]+)(?P<required>\*)?(?:<=(?P<maximum>\d+))?(?P<deprecated> \(deprecated\))?")


def _items(text: str) -> tuple[ParameterRule, ...]:
    found = []
    for token in text.split(", "):
        match = _ITEM.fullmatch(token)
        if match is None:
            raise ValueError(f"cannot read {token!r}")
        found.append(ParameterRule(match["name"], bool(match["required"]), bool(match["deprecated"]), int(match["maximum"]) if match["maximum"] else None))
    return tuple(found)


def _names(text: str) -> tuple[tuple[str, bool], ...]:
    return tuple((item.name, item.required) for item in _items(text)) if text else ()


def _shape(text: str) -> BodyShape:
    if text == "[]":
        return BodyShape("array")
    if text == "any":
        return BodyShape("any")
    if not (text.startswith("{") and text.endswith("}")):
        raise ValueError(f"cannot read the body {text!r}")
    inner = text[1:-1]
    tokens = inner.split(", ") if inner else []
    return BodyShape("object", _names(", ".join(token for token in tokens if token != "...")), "..." in tokens)


def _body(segment: str) -> dict[str, Any]:
    required = not segment.startswith("optional ")
    text = segment if required else segment[len("optional "):]
    if text.startswith("body: "):
        return {"body": "json", "body_required": required, "shapes": tuple(_shape(part) for part in text[len("body: "):].split(" or "))}
    if text.startswith("not JSON (") and text.endswith(")"):
        media, _, names = text[len("not JSON ("):-1].partition(": ")
        return {"body": "other", "body_required": required, "media": media, "fields": _names(names)}
    raise ValueError(f"cannot read the part {segment!r}")


def _rules(line: str) -> OperationRules:
    call, *segments = line.split(" | ")
    method, _, template = call.partition(" ")
    if not method.isupper() or not template.startswith("/"):
        raise ValueError("a line starts with METHOD and the path template")
    found: dict[str, Any] = {}
    seen: list[str] = []
    for segment in segments:
        if segment == "no query" or segment.startswith("query: "):
            part = "query"
            found["query"] = _items(segment[len("query: "):]) if segment != "no query" else ()
        elif segment.startswith("header: "):
            part = "header"
            found["headers"] = _items(segment[len("header: "):])
        else:
            part = "body"
            if segment != "no body":
                found.update(_body(segment))
        seen.append(part)
    if seen not in (["query", "body"], ["query", "header", "body"]):
        raise ValueError("a line is METHOD path | QUERY | BODY, with a header part before the body when there is one")
    return OperationRules(method, template, **found)


def parse_rules(text: str) -> dict[tuple[str, str], OperationRules]:
    """The lines of a parameter file, by `(METHOD, path template)`. A line that cannot be read is an error, not a missing rule."""
    found = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        try:
            rules = _rules(line)
        except ValueError as error:
            raise ValueError(f"line {number} of the parameter file: {error}: {line}") from None
        found[(rules.method, rules.template)] = rules
    return found


@lru_cache(maxsize=None)
def parameter_rules(version: str) -> dict[tuple[str, str], OperationRules]:
    """What the parameter file of the API says about each of its operations."""
    return parse_rules((V2_PARAMETERS if version == "v2" else V1_PARAMETERS).read_text(encoding="utf-8"))


def rules_for(call: Call) -> OperationRules | None:
    """The line of the parameter file for a documented call, or None for any other."""
    return parameter_rules(call.version).get((call.method, call.template)) if call.documented else None


def _listed(names: Sequence[str]) -> str:
    return ", ".join(names) if names else "it has none"


def _is_json(media: str) -> bool:
    return media == "application/json" or media.endswith("+json")


def multipart_names(raw: bytes, content_type: str) -> list[str] | None:
    """The names of the parts of a multipart body, or None when its boundary cannot be found."""
    boundary = re.search(r'boundary="?([^";]+)"?', content_type)
    if boundary is None:
        return None
    names = []
    for part in raw.split(b"--" + boundary.group(1).encode("utf-8"))[1:]:
        if part.startswith(b"--"):
            break
        head = part.lstrip(b"\r\n").split(b"\r\n\r\n", 1)[0].decode("utf-8", "replace")
        name = re.search(r'(?<![A-Za-z])name="([^"]*)"', head)
        if name is not None:
            names.append(name.group(1))
    return names


def _accepted(call: Call, place: str) -> set[str]:
    return {name for (key, where, name) in ACCEPTED_BUT_UNDOCUMENTED if key == call.key and where == place}


def _query_problems(call: Call, rules: OperationRules, query: Mapping[str, Sequence[str]]) -> list[str]:
    known = [entry.name for entry in rules.query]
    allowed = set(known) | _accepted(call, "query")
    found = [f"the query parameter {name} is not one of the operation's ({_listed(known)})" for name in query if name not in allowed]
    found += [f"the required query parameter {entry.name} is missing" for entry in rules.query if entry.required and entry.name not in query]
    for entry in rules.query:
        for value in query.get(entry.name, ()):
            if entry.maximum is not None and value.isdigit() and int(value) > entry.maximum:
                found.append(f"{entry.name} {value} is above the documented maximum of {entry.maximum}")
    return found


def _header_problems(rules: OperationRules, headers: Mapping[str, str]) -> list[str]:
    present = {name.lower() for name in headers}
    return [f"the required header {entry.name} is missing" for entry in rules.headers if entry.required and entry.name.lower() not in present]


_ARTICLE = {"array": "an array", "object": "an object"}


def _kind_of(value: Any) -> str:
    return "array" if isinstance(value, list) else "object" if isinstance(value, dict) else "value"


def _shape_problems(call: Call, shape: BodyShape, value: Any) -> list[str]:
    if shape.kind == "any":
        return []
    kind = _kind_of(value)
    if kind != shape.kind:
        return [f"the request body is a JSON {kind}, and the document describes {_ARTICLE[shape.kind]}"]
    if shape.kind == "array":
        return []
    known = [name for name, _ in shape.properties]
    allowed = set(known) | _accepted(call, "body")
    found = [] if shape.open else [f"the request body has the property {name}, which is not one of the operation's ({_listed(known)})" for name in value if name not in allowed]
    return found + [f"the request body lacks the required property {name}" for name, required in shape.properties if required and name not in value]


def _body_problems(call: Call, rules: OperationRules, content_type: str, raw: bytes) -> list[str]:
    if rules.body == "none":
        return [f"the document lists no request body for this operation, and the request has one ({len(raw)} bytes)"] if raw else []
    if not raw:
        return ["the document requires a request body, and the request has none"] if rules.body_required else []
    media = content_type.split(";")[0].strip().lower()
    if rules.body == "json":
        if not _is_json(media):
            return [f"the request body is sent as {media or 'no content type'}, and the document describes JSON"]
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return []  # the mock answers a body that is no JSON by itself
        verdicts = [_shape_problems(call, shape, value) for shape in rules.shapes]
        if any(not verdict for verdict in verdicts):
            return []
        kind = _kind_of(value)
        likely = [verdict for shape, verdict in zip(rules.shapes, verdicts) if shape.kind == kind] or verdicts  # a shape of the kind that was sent is the closer one
        closest = min(likely, key=len)
        return closest + ([f"(the document offers {len(verdicts)} shapes of body, and this is the closest)"] if len(verdicts) > 1 else [])
    if rules.media.startswith("multipart/"):
        if not media.startswith("multipart/"):
            return [f"the request body is sent as {media or 'no content type'}, and the document describes {rules.media}"]
        names = multipart_names(raw, content_type)
        if names is None or not rules.fields:
            return []
        known = [name for name, _ in rules.fields]
        allowed = set(known) | _accepted(call, "body")
        found = [f"the form field {name} is not one of the operation's ({_listed(known)})" for name in names if name not in allowed]
        return found + [f"the required form field {name} is missing" for name, required in rules.fields if required and name not in names]
    return []


def check_rules(
    call: Call, rules: OperationRules, query: Mapping[str, Sequence[str]], headers: Mapping[str, str] | None = None, content_type: str = "", raw: bytes = b""
) -> list[str]:
    """What the rules of an operation do not allow in a request, as sentences: a query parameter that is not the operation's or is missing, a `limit`
    above the documented maximum, a required header that is missing, and a body that is of another kind, has a property that the schema does not
    list or lacks a required one. `query` has the names and values of the query, `headers` the headers of the request, `raw` its body."""
    return _query_problems(call, rules, query) + _header_problems(rules, headers or {}) + _body_problems(call, rules, content_type, raw)


def request_problems(
    call: Call, query: Mapping[str, Sequence[str]], headers: Mapping[str, str] | None = None, content_type: str = "", raw: bytes = b""
) -> list[str]:
    """What the parameter file of the call's API does not allow in a request (see `check_rules`). Empty when the request fits, or when the
    document gives the call no line."""
    rules = rules_for(call)
    return [] if rules is None else check_rules(call, rules, query, headers, content_type, raw)


def deprecated_parameters(call: Call, query: Mapping[str, Sequence[str]]) -> list[str]:
    """The query parameters of a request that the document marks as deprecated: they are answered, and no command may send one."""
    rules = rules_for(call)
    return [] if rules is None else [entry.name for entry in rules.query if entry.deprecated and entry.name in query]


# --- the names that the code puts into a query -------------------------------------------------------------------------------------------

# What the REST adapters write a query with: `rest_support.query(**params)` (imported as `_query`) turns `include_labels=True` into `include-labels=true`,
# and `_with_query(path, **params)` of the blog posts does the same for a path.
_QUERY_BUILDERS = frozenset({"query", "_query", "_with_query"})
_FRAGMENT = re.compile(r"[?&]([A-Za-z][A-Za-z0-9_.-]*)=")
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def query_names() -> frozenset[str]:
    """The name of every query parameter of any operation of the two documents."""
    return frozenset(entry.name for version in ("v2", "v1") for rules in parameter_rules(version).values() for entry in rules.query)


def _callee(node: ast.Call) -> str:
    return node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""


def _text_of(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _dict_names(node: ast.AST) -> list[tuple[str, int]]:
    """The names that a dict display `{"a": 1}` or a call `dict(a=1)` holds, with their lines."""
    if isinstance(node, ast.Dict):
        return [(name, key.lineno) for key in node.keys if key is not None and (name := _text_of(key)) is not None]
    if isinstance(node, ast.Call) and _callee(node) == "dict":
        return [(keyword.arg, node.lineno) for keyword in node.keywords if keyword.arg]
    return []


def _own_nodes(scope: ast.AST) -> list[ast.AST]:
    """The nodes of a module or a function without those inside the functions below it: they are scopes of their own."""
    found: list[ast.AST] = []
    todo = list(ast.iter_child_nodes(scope))
    while todo:
        node = todo.pop()
        found.append(node)
        if not isinstance(node, _FUNCTIONS):
            todo.extend(ast.iter_child_nodes(node))
    return found


def names_in_source(source: str) -> dict[str, list[int]]:
    """The query parameters that Python source puts into a request, each with the lines that name it. A name counts when it is
    a keyword of a query builder (`_query(include_labels=True)` is `include-labels`, as the builder writes it),
    a key of a dict that is spread into one (`_query(**common)` after `common = dict(a=1)` or `common = {"a": 1}`, or `common["a"] = 1`),
    or written as `?name=` or `&name=` in a string. The literals of a docstring are no names, nor is a string that is read (`.get("next")`) or
    a value (`sort="name"`): only the places where a name is put into a query count."""
    tree = ast.parse(source)
    found: dict[str, set[int]] = {}

    def add(name: str, line: int) -> None:
        found.setdefault(name.replace("_", "-"), set()).add(line)

    scopes = [node for node in ast.walk(tree) if isinstance(node, (ast.Module, ast.ClassDef, *_FUNCTIONS))]
    docstrings = {id(scope.body[0].value) for scope in scopes if scope.body and isinstance(scope.body[0], ast.Expr)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            for name in _FRAGMENT.findall(node.value):
                add(name, node.lineno)
    for scope in [tree, *(node for node in scopes if isinstance(node, _FUNCTIONS))]:
        nodes = _own_nodes(scope)
        spread: dict[str, list[tuple[str, int]]] = {}  # the names that the dicts of this scope hold, by variable
        for node in nodes:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    spread.setdefault(target.id, []).extend(_dict_names(node.value))
                elif isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) and (name := _text_of(target.slice)) is not None:
                    spread.setdefault(target.value.id, []).append((name, node.lineno))
        for node in nodes:
            if isinstance(node, ast.Call) and _callee(node) in _QUERY_BUILDERS:
                for keyword in node.keywords:
                    if keyword.arg:
                        add(keyword.arg, node.lineno)
                    else:
                        held = spread.get(keyword.value.id, []) if isinstance(keyword.value, ast.Name) else _dict_names(keyword.value)
                        for name, line in held:
                            add(name, line)
    return {name: sorted(lines) for name, lines in sorted(found.items())}


# --- the options that a sweep line names -------------------------------------------------------------------------------------------------


def names_option(argv: Sequence[str], names: Sequence[str]) -> bool:
    """Whether the arguments name an option under one of its names: `--cursor 2` and `--cursor=2` do."""
    return any(token == name or token.startswith(f"{name}=") for token in argv for name in names)


def options_without_a_line(commands: Iterable[Any], lines: Iterable[Sequence[str]]) -> list[tuple[str, str]]:
    """The options (not the positional arguments) of the commands that no sweep line names, as `(command, the option's first name)`, in the order of the specs.
    A command is anything with `name`, `aliases` and `args` (each with `names` and `positional`: the specs of the CLI); a line is its arguments, the command first."""
    by_command: dict[str, list[Sequence[str]]] = {}
    for argv in lines:
        by_command.setdefault(argv[0], []).append(argv[1:])
    found = []
    for command in commands:
        used = [argv for name in (command.name, *command.aliases) for argv in by_command.get(name, ())]
        for arg in command.args:
            if not arg.positional and not any(names_option(argv, arg.names) for argv in used):
                found.append((command.name, arg.names[0]))
    return found
