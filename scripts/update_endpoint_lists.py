#!/usr/bin/env python3
"""Rewrites the endpoint lists and the parameter files of the compatibility checks from the two OpenAPI documents of Confluence Cloud.

Download the documents yourself (their addresses are in docs/reference/compatibility.md), then:

    python scripts/update_endpoint_lists.py --v2 openapi-v2.v3.json --v1 swagger.v3.json --read-on 2026-11-30
    python scripts/update_endpoint_lists.py --v2 ... --v1 ... --dry-run     # only say what would change

It reads the two files that you name and writes four files in `tests/support`: the lists `confluence_cloud_v2_endpoints.txt` and
`confluence_cloud_v1_endpoints.txt` (method and path of every operation), and `confluence_cloud_v2_parameters.txt` and
`confluence_cloud_v1_parameters.txt` (the same operations, one per line, with the query parameters, the required headers and the request body
that the document gives them). It never contacts a server. Afterwards `git diff tests/support` shows which operations were added, removed or
newly deprecated and which ones changed their parameters: read that before you keep the change, and bring the numbers that the tests and the
compatibility page state up to date (the script lists them).
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
SUPPORT = ROOT / "tests" / "support"
METHODS = ("get", "post", "put", "delete", "patch", "head", "options")
COMMON = (
    "# Paths are relative to the wiki address (https://SITE/wiki, or the gateway address that ends in /wiki), which is what the CLI's requests are made below.\n"
    "# A trailing `deprecated` marks an operation that the document itself marks as deprecated: the mock still answers it, and the tests fail when a command calls it.\n"
    "# tests/support/conformance.py reads this file. The mock Confluence answers HTTP 404 to a call that is not listed and records it, so that the CLI cannot come to depend\n"
    "# on an endpoint that the document does not know. Keep the list as the document has it: it is the reference, not what the CLI uses.\n"
)


@dataclass(frozen=True)
class Api:
    version: str
    file: str
    parameters_file: str
    url: str
    guide: str
    where: str  # what the header says about the paths of the document and of this list
    prefix: str  # what is put in front of a path of the document (v2: its server URL ends in /wiki/api/v2)
    strip: str  # what is taken off the front of a path of the document (v1 writes /wiki/rest/api/...)


V2 = Api(
    "v2",
    "confluence_cloud_v2_endpoints.txt",
    "confluence_cloud_v2_parameters.txt",
    "https://dac-static.atlassian.com/cloud/confluence/openapi-v2.v3.json",
    "https://developer.atlassian.com/cloud/confluence/rest/v2/intro/",
    "The document's server URL is https://{your-domain}/wiki/api/v2, so every path here starts with /api/v2.",
    "/api/v2",
    "",
)
V1 = Api(
    "v1",
    "confluence_cloud_v1_endpoints.txt",
    "confluence_cloud_v1_parameters.txt",
    "https://dac-static.atlassian.com/cloud/confluence/swagger.v3.json",
    "https://developer.atlassian.com/cloud/confluence/rest/v1/intro/",
    "The document writes the paths with the /wiki prefix; it is left off here, so every path starts with /rest/.",
    "",
    "/wiki",
)


def walk(api: Api, document: dict) -> list[tuple[str, str, dict, dict]]:
    """`(METHOD, path template, path item, operation)` of every operation, sorted by path and then method."""
    found = []
    for path, item in document["paths"].items():
        if api.strip:
            if not path.startswith(api.strip + "/"):
                raise SystemExit(f"The {api.version} document has a path that does not start with {api.strip}/: {path}")
            path = path[len(api.strip):]
        for method in METHODS:
            if method in item:
                found.append((method.upper(), api.prefix + path, item, item[method]))
    return sorted(found, key=lambda entry: (entry[1], entry[0]))


def operations(api: Api, document: dict) -> list[tuple[str, str, bool]]:
    """`(METHOD, path template, deprecated)` of every operation, sorted by path and then method."""
    return [(method, path, bool(operation.get("deprecated"))) for method, path, _, operation in walk(api, document)]


def render(api: Api, document: dict, read_on: str) -> str:
    entries = operations(api, document)
    version = document["info"]["version"]
    lines = [
        f"# The REST calls that the Confluence Cloud REST API {api.version} document lists: method and path template, nothing else.",
        f"# Derived from {api.url} (info.version {version}, read on {read_on}): {len(entries)} operations.",
        f"# {api.where} Guide: {api.guide}",
    ]
    body = "".join(f"{method} {path}{' deprecated' if deprecated else ''}\n" for method, path, deprecated in entries)
    return "\n".join(lines) + "\n" + COMMON + body


def parse(text: str) -> dict[tuple[str, str], bool]:
    found = {}
    for line in text.splitlines():
        if line.strip() and not line.startswith("#"):
            method, template, *flags = line.split()
            found[(method, template)] = "deprecated" in flags
    return found


PARAMETER_COMMON = (
    "# A line is `METHOD path | QUERY | BODY`, or `METHOD path | QUERY | header: HEADERS | BODY` when the document names a header parameter. The method and the path template are\n"
    "# those of the endpoint list of this API, in the same order. Only top-level names are listed, each part sorted by name.\n"
    "# QUERY is `no query`, or `query: ` and the parameters: `*` after a name marks a required one, `<=N` the documented maximum of `limit`, `(deprecated)` one that the document marks as deprecated.\n"
    "# BODY is `no body`; `body: ` and what a JSON body may be; or `not JSON (media type: form fields)` for a request that is not JSON, such as a multipart upload. `optional ` in front says that a request may have none.\n"
    "# A JSON body is `{properties}` for an object (`*` marks a required property, `...` that other properties are accepted as well), `[]` for an array or `any` for anything; the alternatives of a oneOf are joined by ` or `.\n"
    "# tests/support/conformance.py reads this file. When `strict_parameters` is on (the sweep of the commands turns it on) the mock Confluence answers HTTP 400 to a request that does not fit its line and\n"
    "# records it, so that the CLI cannot come to send a parameter or a body that the document does not know. Keep the file as the document has it: it is the reference, not what the CLI uses.\n"
)
NAME = re.compile(r"[^\s,*<>(){}|]+")  # what the parameter files can write as the name of a parameter, a header, a property or a form field
MEDIA = re.compile(r"[^\s,(){}|:]+")  # ... and as a media type
LIMIT = "limit"
DEPTH = 12  # how far a schema may nest through $ref, allOf and oneOf before the script gives up on it and says "any"


@dataclass(frozen=True)
class Parameter:
    name: str
    required: bool = False
    deprecated: bool = False
    maximum: int | None = None  # the documented maximum, read for `limit` only


@dataclass(frozen=True)
class Shape:
    """One thing that a JSON body may be: an object with these top-level properties `(name, required)`, an array, or anything."""

    kind: str  # "object", "array" or "any"
    properties: tuple[tuple[str, bool], ...] = ()
    open: bool = False  # other properties are accepted as well


@dataclass(frozen=True)
class Body:
    kind: str  # "none", "json", or "other": a request that is not JSON, such as a multipart upload
    required: bool = False
    shapes: tuple[Shape, ...] = ()  # what a JSON body may be
    media: str = ""  # the media type of a body that is not JSON
    fields: tuple[tuple[str, bool], ...] = ()  # its form fields `(name, required)`


@dataclass(frozen=True)
class Rules:
    query: tuple[Parameter, ...]
    headers: tuple[Parameter, ...]
    body: Body


def resolve(document: dict, node: Any) -> Any:
    """Follows the local `$ref`s of a node until it is the thing itself."""
    for _ in range(50):
        if not (isinstance(node, dict) and "$ref" in node):
            return node
        reference = node["$ref"]
        if not isinstance(reference, str) or not reference.startswith("#/"):
            raise ValueError(f"a $ref that is not a local one: {reference!r}")
        target: Any = document
        for part in reference[2:].split("/"):
            part = unquote(part).replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or part not in target:
                raise ValueError(f"a $ref that points nowhere: {reference}")
            target = target[part]
        node = target
    raise ValueError(f"a $ref that never ends: {node['$ref']}")


def is_json(media: str) -> bool:
    kind = media.split(";")[0].strip().lower()
    return kind == "application/json" or kind.endswith("+json")


def written(name: str, pattern: "re.Pattern[str]" = NAME) -> str:
    if not pattern.fullmatch(name):
        raise ValueError(f"a name that the parameter files cannot write: {name!r}")
    return name


def maximum_of(document: dict, parameter: dict) -> int | None:
    schema = resolve(document, parameter.get("schema") or {})
    maximum = schema.get("maximum") if isinstance(schema, dict) else None
    if isinstance(maximum, bool) or not isinstance(maximum, (int, float)) or maximum != int(maximum):
        return None
    return int(maximum)


def read_parameters(document: dict, item: dict, operation: dict) -> tuple[tuple[Parameter, ...], tuple[Parameter, ...]]:
    """The query parameters and the headers of an operation: those of its path item, then its own, which win. Path parameters are in the template."""
    found: dict[tuple[str, str], dict] = {}
    for raw in [*(item.get("parameters") or []), *(operation.get("parameters") or [])]:
        parameter = resolve(document, raw)
        place, name = parameter["in"], parameter["name"]
        found[(place, name.lower() if place == "header" else name)] = parameter
    query: list[Parameter] = []
    headers: list[Parameter] = []
    for (place, _), parameter in found.items():
        if place not in ("query", "header"):
            continue
        name = written(parameter["name"])
        maximum = maximum_of(document, parameter) if place == "query" and name == LIMIT else None
        (query if place == "query" else headers).append(Parameter(name, parameter.get("required") is True, parameter.get("deprecated") is True, maximum))
    return tuple(sorted(query, key=lambda entry: entry.name)), tuple(sorted(headers, key=lambda entry: entry.name.lower()))


def own_shape(schema: dict) -> Shape | None:
    """The object or the array that a schema describes by itself, leaving its allOf, oneOf and anyOf aside; None for anything else."""
    kind = schema.get("type")
    if kind == "array" or (kind is None and "items" in schema):
        return Shape("array")
    properties, required, additional = schema.get("properties"), schema.get("required"), schema.get("additionalProperties")
    if kind != "object" and not isinstance(properties, dict) and not isinstance(required, list) and additional is None:
        return None
    names = {name: False for name in properties} if isinstance(properties, dict) else {}
    for name in required if isinstance(required, list) else []:
        names[name] = True
    return Shape("object", tuple(sorted((written(name), flag) for name, flag in names.items())), additional is True or isinstance(additional, dict))


def merge(shapes: tuple[Shape, ...]) -> Shape:
    """What a body must be to satisfy every member of an allOf: the properties add up, and a required one stays required."""
    kinds = {shape.kind for shape in shapes} - {"any"}
    if not kinds:
        return Shape("any")
    if kinds == {"array"}:
        return Shape("array")
    if kinds != {"object"}:
        return Shape("any")  # an array and an object at once: nothing can be said
    required: dict[str, bool] = {}
    for shape in shapes:
        for name, flag in shape.properties:
            required[name] = required.get(name, False) or flag
    return Shape("object", tuple(sorted(required.items())), any(shape.open for shape in shapes if shape.kind == "object"))


def alternatives(document: dict, schema: Any, depth: int = 0) -> tuple[Shape, ...]:
    """What a JSON body of this schema may be: one shape, or one for each branch of a oneOf or anyOf."""
    schema = resolve(document, schema)
    if not isinstance(schema, dict) or depth > DEPTH:
        return (Shape("any"),)
    groups: list[tuple[Shape, ...]] = [alternatives(document, member, depth + 1) for member in schema.get("allOf") or []]
    for key in ("oneOf", "anyOf"):
        if schema.get(key):
            branches: list[Shape] = []
            for member in schema[key]:
                branches.extend(shape for shape in alternatives(document, member, depth + 1) if shape not in branches)
            groups.append(tuple(branches))
    own = own_shape(schema)
    if own is not None and (own.kind == "array" or own.properties or own.open):
        groups.insert(0, (own,))
    elif own is not None and not groups:
        groups.append((Shape("object", (), True),))  # an object that lists no property: any object
    if not groups:
        return (Shape("any"),)
    found: list[Shape] = []
    for combination in itertools.product(*groups):
        shape = merge(combination)
        if shape not in found:
            found.append(shape)
    return tuple(found)


def read_body(document: dict, operation: dict) -> Body:
    if operation.get("requestBody") is None:
        return Body("none")
    request = resolve(document, operation["requestBody"])
    required = request.get("required") is True
    content = request.get("content") or {}
    media = next((name for name in content if is_json(name)), None)
    if media is not None:
        return Body("json", required, shapes=alternatives(document, (content[media] or {}).get("schema") or {}))
    if not content:
        return Body("other", required, media="unspecified")
    media = next(iter(content))
    objects = [shape for shape in alternatives(document, (content[media] or {}).get("schema") or {}) if shape.kind == "object"]
    return Body("other", required, media=written(media, MEDIA), fields=objects[0].properties if len(objects) == 1 else ())


def render_parameter(parameter: Parameter) -> str:
    maximum = f"<={parameter.maximum}" if parameter.maximum is not None else ""
    return f"{parameter.name}{'*' if parameter.required else ''}{maximum}{' (deprecated)' if parameter.deprecated else ''}"


def render_names(items: tuple[tuple[str, bool], ...], more: bool = False) -> str:
    return ", ".join([name + ("*" if required else "") for name, required in items] + (["..."] if more else []))


def render_shape(shape: Shape) -> str:
    if shape.kind == "array":
        return "[]"
    if shape.kind == "any":
        return "any"
    return "{" + render_names(shape.properties, shape.open) + "}"


def render_body(body: Body) -> str:
    if body.kind == "none":
        return "no body"
    optional = "" if body.required else "optional "
    if body.kind == "other":
        return f"{optional}not JSON ({body.media}{': ' + render_names(body.fields) if body.fields else ''})"
    return f"{optional}body: " + " or ".join(render_shape(shape) for shape in body.shapes)


def render_rules(rules: Rules) -> str:
    parts = ["query: " + ", ".join(render_parameter(entry) for entry in rules.query) if rules.query else "no query"]
    if rules.headers:
        parts.append("header: " + ", ".join(render_parameter(entry) for entry in rules.headers))
    parts.append(render_body(rules.body))
    return " | ".join(parts)


def parameter_lines(api: Api, document: dict) -> list[tuple[str, str]]:
    """`(METHOD path, the rest of its line)` of every operation, in the order of the endpoint list."""
    found = []
    for method, path, item, operation in walk(api, document):
        try:
            found.append((f"{method} {path}", render_rules(Rules(*read_parameters(document, item, operation), read_body(document, operation)))))
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise SystemExit(f"The {api.version} document has an operation that the script cannot read: {method} {path}: {type(error).__name__}: {error}")
    return found


def render_parameters(api: Api, document: dict, read_on: str) -> str:
    entries = parameter_lines(api, document)
    version = document["info"]["version"]
    lines = [
        f"# The query parameters, the headers and the request body that the Confluence Cloud REST API {api.version} document gives each of its operations, one operation per line.",
        f"# Derived from {api.url} (info.version {version}, read on {read_on}): {len(entries)} operations, those of {api.file}.",
        f"# {api.where} Guide: {api.guide}",
    ]
    return "\n".join(lines) + "\n" + PARAMETER_COMMON + "".join(f"{call} | {rest}\n" for call, rest in entries)


def parse_parameters(text: str) -> dict[str, str]:
    """`METHOD path` -> the rest of its line."""
    found = {}
    for line in text.splitlines():
        if line.strip() and not line.startswith("#"):
            call, _, rest = line.partition(" | ")
            found[call] = rest
    return found


def describe_parameters(api: Api, old: dict[str, str] | None, new: dict[str, str]) -> list[str]:
    if old is None:
        return [f"{api.version} parameters: {len(new)} operations (the file is new)."]
    changed = sorted(call for call in new if call in old and old[call] != new[call])
    return [f"{api.version} parameters: {len(new)} operations (before: {len(old)}); {len(changed)} of them changed their parameters or their body.",
            *(f"  changed: {call}" for call in changed)]


def describe(api: Api, old: dict[tuple[str, str], bool], new: dict[tuple[str, str], bool]) -> list[str]:
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    newly_deprecated = sorted(key for key in new if new[key] and old.get(key) is False)
    no_longer = sorted(key for key in new if not new[key] and old.get(key) is True)
    lines = [f"{api.version}: {len(new)} operations, {sum(new.values())} of them deprecated "
             f"(before: {len(old)}, {sum(old.values())}); added {len(added)}, removed {len(removed)}, newly deprecated {len(newly_deprecated)}, no longer deprecated {len(no_longer)}."]
    for label, keys in (("added", added), ("removed", removed), ("newly deprecated", newly_deprecated), ("no longer deprecated", no_longer)):
        lines.extend(f"  {label}: {method} {template}" for method, template in keys)
    return lines


def load(path: Path, api: Api) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SystemExit(f"Cannot read the {api.version} document {path}: {error}")
    if not isinstance(document, dict) or not isinstance(document.get("paths"), dict) or not isinstance(document.get("info"), dict):
        raise SystemExit(f"{path} is not an OpenAPI document: it has no `paths` or no `info`.")
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rewrite the endpoint lists and the parameter files of the compatibility checks from the two OpenAPI documents.")
    parser.add_argument("--v2", required=True, type=Path, help="the v2 OpenAPI document that you downloaded")
    parser.add_argument("--v1", required=True, type=Path, help="the v1 OpenAPI (swagger) document that you downloaded")
    parser.add_argument("--read-on", default=date.today().isoformat(), help="the day you downloaded them (YYYY-MM-DD, default: today)")
    parser.add_argument("--out-dir", type=Path, default=SUPPORT, help="where the lists and the parameter files are (default: tests/support)")
    parser.add_argument("--dry-run", action="store_true", help="say what would change and write nothing")
    args = parser.parse_args(argv)
    try:
        date.fromisoformat(args.read_on)
    except ValueError:
        raise SystemExit(f"--read-on must be a day like 2026-11-30, not {args.read_on!r}.")
    versions = {}
    planned = []
    for api, source in ((V2, args.v2), (V1, args.v1)):
        document = load(source, api)
        target = args.out_dir / api.file
        text = render(api, document, args.read_on)
        old = parse(target.read_text(encoding="utf-8")) if target.is_file() else {}
        planned.append((target, text, describe(api, old, parse(text))))
        parameters = args.out_dir / api.parameters_file
        rules = render_parameters(api, document, args.read_on)
        before = parse_parameters(parameters.read_text(encoding="utf-8")) if parameters.is_file() else None
        planned.append((parameters, rules, describe_parameters(api, before, parse_parameters(rules))))
        versions[api.version] = document["info"]["version"]
    for target, text, summary in planned:  # both documents are read and checked before the first file is written
        print("\n".join(summary))
        if not args.dry_run:
            args.out_dir.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode("utf-8"))
    print(("Would write" if args.dry_run else "Wrote") + f" the two lists and the two parameter files in {args.out_dir}.")
    print(
        "Now bring up to date what states them, then run the tests: DOCUMENTS_READ, V2_VERSION and V1_VERSION in src/conflu_c_cli/domain/compat.py "
        f"(now {args.read_on}, v2 {versions['v2']}, v1 {versions['v1']}), the counts, the date and the deprecated operations in "
        "tests/integration/test_conformance.py, and the table of the two documents in docs/reference/compatibility.md. "
        "A command that calls something removed or deprecated fails its sweep: move it to the call that replaces it (v2 first)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
