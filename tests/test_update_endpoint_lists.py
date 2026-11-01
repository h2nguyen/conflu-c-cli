"""scripts/update_endpoint_lists.py writes the two endpoint lists and the two parameter files of the compatibility checks from two OpenAPI documents, and says what changed."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support.conformance import V1_LIST, V1_PARAMETERS, V2_LIST, V2_PARAMETERS, documented_calls, parameter_rules, parse_rules

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "update_endpoint_lists.py"


def document(version: str, paths: dict) -> dict:
    return {"openapi": "3.0.1", "info": {"title": "Confluence", "version": version}, "paths": paths}


def v2_document(*extra: str) -> dict:
    paths = {
        "/pages/{id}": {"get": {}, "put": {}},
        "/pages/{id}/children": {"get": {"deprecated": True}},
        "/spaces": {"get": {}},
    }
    paths.update({path: {"get": {}} for path in extra})
    return document("2.0.1", paths)


def v1_document(*paths: str) -> dict:
    return document("1.0.0", {path: {"get": {}} for path in ("/wiki/rest/api/search", "/wiki/rest/api/user/current", *paths)})


class UpdateEndpointListsTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.out = self.folder / "lists"

    def write(self, name: str, content) -> Path:
        path = self.folder / name
        path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
        return path

    def run_script(self, v2: Path, v1: Path, *more: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--v2", str(v2), "--v1", str(v1), "--out-dir", str(self.out), *more],
            capture_output=True, text=True, encoding="utf-8", timeout=60,
        )

    def lists(self, v2_content=None, v1_content=None) -> tuple[Path, Path]:
        return self.write("v2.json", v2_content or v2_document()), self.write("v1.json", v1_content or v1_document())

    def test_it_writes_both_lists_in_the_format_the_tests_read(self):
        done = self.run_script(*self.lists(), "--read-on", "2026-11-30")
        self.assertEqual(done.returncode, 0, done.stderr)
        v2 = (self.out / "confluence_cloud_v2_endpoints.txt").read_bytes().decode("utf-8")
        v1 = (self.out / "confluence_cloud_v1_endpoints.txt").read_bytes().decode("utf-8")
        self.assertIn("(info.version 2.0.1, read on 2026-11-30): 4 operations.", v2)
        self.assertIn("(info.version 1.0.0, read on 2026-11-30): 2 operations.", v1)
        self.assertIn("https://dac-static.atlassian.com/cloud/confluence/openapi-v2.v3.json", v2)
        self.assertEqual(
            [line for line in v2.splitlines() if not line.startswith("#")],
            ["GET /api/v2/pages/{id}", "PUT /api/v2/pages/{id}", "GET /api/v2/pages/{id}/children deprecated", "GET /api/v2/spaces"],
        )
        self.assertEqual([line for line in v1.splitlines() if not line.startswith("#")], ["GET /rest/api/search", "GET /rest/api/user/current"])
        self.assertNotIn("\r", v2 + v1)

    def test_the_lists_in_the_repository_have_the_format_that_it_writes(self):
        for path in (V2_LIST, V1_LIST):
            text = path.read_bytes().decode("utf-8")
            with self.subTest(list=path.name):
                self.assertNotIn("\r", text)
                self.assertTrue(text.startswith("# The REST calls that the Confluence Cloud REST API"))
        self.assertTrue(documented_calls("v2") and documented_calls("v1"))

    def test_it_says_what_changed(self):
        self.run_script(*self.lists(), "--read-on", "2026-11-30")
        newer = self.lists(v2_document("/folders/{id}"), v1_document("/wiki/rest/api/space"))
        done = self.run_script(*newer, "--read-on", "2026-12-31")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("v2: 5 operations, 1 of them deprecated (before: 4, 1); added 1, removed 0", done.stdout)
        self.assertIn("added: GET /api/v2/folders/{id}", done.stdout)
        self.assertIn("added: GET /rest/api/space", done.stdout)
        self.assertIn("DOCUMENTS_READ", done.stdout)  # what to bring up to date by hand

    def test_a_removed_and_a_newly_deprecated_operation_are_named(self):
        self.run_script(*self.lists(), "--read-on", "2026-11-30")
        newer = {"/pages/{id}": {"get": {"deprecated": True}}, "/spaces": {"get": {}}}
        done = self.run_script(*self.lists(document("2.1.0", newer)), "--read-on", "2026-12-31")
        self.assertIn("removed: PUT /api/v2/pages/{id}", done.stdout)
        self.assertIn("removed: GET /api/v2/pages/{id}/children", done.stdout)
        self.assertIn("newly deprecated: GET /api/v2/pages/{id}", done.stdout)

    def test_a_dry_run_writes_nothing(self):
        done = self.run_script(*self.lists(), "--dry-run")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Would write", done.stdout)
        self.assertFalse(self.out.exists())

    def test_what_is_no_openapi_document_is_refused(self):
        done = self.run_script(self.write("v2.json", {"hello": "world"}), self.write("v1.json", v1_document()))
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("is not an OpenAPI document", done.stderr)
        done = self.run_script(self.write("v2.json", "not json"), self.write("v1.json", v1_document()))
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("Cannot read the v2 document", done.stderr)
        self.assertFalse(self.out.exists())

    def test_a_v1_path_without_the_wiki_prefix_is_refused_and_nothing_is_written(self):
        done = self.run_script(*self.lists(v1_content=v1_document("/rest/api/oops")))
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("does not start with /wiki/", done.stderr)
        self.assertFalse(self.out.exists())

    def test_a_day_that_is_no_day_is_refused(self):
        done = self.run_script(*self.lists(), "--read-on", "yesterday")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("--read-on must be a day", done.stderr)

    def test_it_writes_the_two_parameter_files_next_to_the_lists_and_says_so(self):
        done = self.run_script(*self.lists(), "--read-on", "2026-11-30")
        self.assertEqual(sorted(path.name for path in self.out.iterdir()), [
            "confluence_cloud_v1_endpoints.txt", "confluence_cloud_v1_parameters.txt",
            "confluence_cloud_v2_endpoints.txt", "confluence_cloud_v2_parameters.txt",
        ])
        self.assertIn("v2 parameters: 4 operations (the file is new).", done.stdout)
        self.assertIn("v1 parameters: 2 operations (the file is new).", done.stdout)
        self.assertIn("the two lists and the two parameter files", done.stdout)
        text = (self.out / "confluence_cloud_v2_parameters.txt").read_bytes().decode("utf-8")
        self.assertIn("(info.version 2.0.1, read on 2026-11-30): 4 operations, those of confluence_cloud_v2_endpoints.txt.", text)
        self.assertNotIn("\r", text)

    def test_a_dry_run_of_the_parameter_files_writes_nothing_either(self):
        done = self.run_script(*self.lists(), "--dry-run")
        self.assertIn("v2 parameters: 4 operations (the file is new).", done.stdout)
        self.assertFalse(self.out.exists())

    def test_a_changed_parameter_is_named_and_an_unchanged_file_is_not_reported_as_changed(self):
        self.run_script(*self.lists(), "--read-on", "2026-11-30")
        again = self.run_script(*self.lists(), "--read-on", "2026-11-30")
        self.assertIn("v2 parameters: 4 operations (before: 4); 0 of them changed their parameters or their body.", again.stdout)
        paths = v2_document()["paths"]
        paths["/spaces"] = {"get": {"parameters": [{"name": "keys", "in": "query", "schema": {"type": "array"}}]}}
        newer = self.run_script(self.write("v2.json", document("2.0.2", paths)), self.write("v1.json", v1_document()), "--read-on", "2026-12-31")
        self.assertIn("v2 parameters: 4 operations (before: 4); 1 of them changed their parameters or their body.", newer.stdout)
        self.assertIn("  changed: GET /api/v2/spaces", newer.stdout)
        self.assertIn("v1 parameters: 2 operations (before: 2); 0 of them changed", newer.stdout)

    def test_a_reference_that_leads_nowhere_is_refused_with_the_operation_and_nothing_is_written(self):
        for label, parameter, said in (
            ("points nowhere", {"$ref": "#/components/parameters/Nope"}, "a $ref that points nowhere"),
            ("not local", {"$ref": "other.json#/components/parameters/Cursor"}, "a $ref that is not a local one"),
            ("never ends", {"$ref": "#/components/parameters/A"}, "a $ref that never ends"),
            ("a name it cannot write", {"name": "bad name", "in": "query", "schema": {"type": "string"}}, "cannot write"),
            ("a parameter without a name", {"in": "query"}, "KeyError"),
        ):
            with self.subTest(case=label):
                paths = {"/things": {"get": {"parameters": [parameter]}}}
                broken = document("2.0.1", paths)
                broken["components"] = {"parameters": {"A": {"$ref": "#/components/parameters/B"}, "B": {"$ref": "#/components/parameters/A"}}}
                done = self.run_script(self.write("v2.json", broken), self.write("v1.json", v1_document()))
                self.assertNotEqual(done.returncode, 0)
                self.assertIn("the script cannot read: GET /api/v2/things", done.stderr)
                self.assertIn(said, done.stderr)
                self.assertFalse(self.out.exists())


def rich_v2() -> dict:
    """One operation for each thing that a parameter line can say; the lines they must give are in RICH_V2."""
    named = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}
    tagged = {"type": "object", "properties": {"tag": {"type": "string"}, "name": {"type": "string"}}}

    def body(schema: dict, *, required: bool = True, media: str = "application/json") -> dict:
        return {"requestBody": {"required": required, "content": {media: {"schema": schema}}}}

    paths = {
        "/things": {"post": body({"type": "object", "required": ["title", "spaceId", "undeclared"], "properties": {"title": {}, "spaceId": {}, "parentId": {}}})},
        "/things/{id}": {
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}},
                {"name": "body-format", "in": "query", "schema": {"type": "string"}},
                {"name": "sort", "in": "query", "schema": {"type": "string"}},
            ],
            "get": {"parameters": [
                {"$ref": "#/components/parameters/Cursor"},
                {"$ref": "#/components/parameters/Limit"},
                {"$ref": "#/components/parameters/Match"},
                {"name": "status", "in": "query", "required": True, "schema": {"type": "string"}},
                {"name": "sort", "in": "query", "required": True, "schema": {"type": "string"}},  # the operation's own wins over the path item's
                {"name": "X-Trace", "in": "header", "required": True, "schema": {"type": "string"}},
                {"name": "session", "in": "cookie", "schema": {"type": "string"}},
            ]},
        },
        "/things/{id}/title": {"put": {"requestBody": {"$ref": "#/components/requestBodies/Title"}}},
        "/things/{id}/versions": {"get": {"parameters": [
            {"name": "limit", "in": "query", "schema": {"type": "integer"}},
            {"name": "depth", "in": "query", "schema": {"type": "integer", "maximum": 10}},
            {"name": "username", "in": "query", "deprecated": True, "schema": {"type": "string"}},
        ]}},
        "/things/{id}/odd-limit": {"get": {"parameters": [{"name": "limit", "in": "query", "schema": {"type": "integer", "maximum": 2.5}}]}},
        "/things/{id}/labels": {"post": body({"type": "array", "items": named})},
        "/things/{id}/merge": {"post": body({"allOf": [named, tagged, {"$ref": "#/components/schemas/Odd~1Name"}]})},
        "/things/{id}/open": {"post": body({"type": "object", "required": ["name"], "additionalProperties": True, "properties": {"note": {}}})},
        "/things/{id}/free": {"post": body({"type": "object", "example": {"anything": 1}})},
        "/things/{id}/choice": {"post": body({"oneOf": [{"type": "array", "items": named}, named]})},
        "/things/{id}/either": {"post": body({"anyOf": [named, tagged]})},
        "/things/{id}/maybe": {"post": body(named, required=False)},
        "/things/{id}/upload": {"post": body({"type": "object", "required": ["file"], "properties": {"file": {"type": "string", "format": "binary"}, "comment": {"type": "string"}}}, media="multipart/form-data")},
        "/things/{id}/raw": {"put": body({"type": "string"}, media="text/plain")},
        "/things/{id}/anything": {"post": body({})},
        "/things/{id}/vendor": {"post": body(named, media="application/vnd.example+json; charset=utf-8")},
        "/things/{id}/both": {"post": {"requestBody": {"required": True, "content": {
            "multipart/form-data": {"schema": {"type": "object", "properties": {"file": {}}}},
            "application/json": {"schema": named},
        }}}},
        "/things/{id}/purge": {"delete": {}},
    }
    result = document("2.0.1", paths)
    result["components"] = {
        "parameters": {
            "Cursor": {"name": "cursor", "in": "query", "schema": {"type": "string"}},
            "Limit": {"name": "limit", "in": "query", "schema": {"$ref": "#/components/schemas/Limit"}},
            "Match": {"name": "If-None-Match", "in": "header", "schema": {"type": "string"}},
        },
        "requestBodies": {"Title": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Title"}}}}},
        "schemas": {
            "Limit": {"type": "integer", "minimum": 1, "maximum": 250, "default": 25},
            "Title": {"type": "object", "required": ["status", "title"], "properties": {"title": {"type": "string"}, "status": {"type": "string"}, "version": {"type": "object"}}},
            "Odd/Name": {"type": "object", "required": ["odd"], "properties": {"odd": {}}},
        },
    }
    return result


RICH_V2 = {
    "POST /api/v2/things": "no query | body: {parentId, spaceId*, title*, undeclared*}",
    "GET /api/v2/things/{id}": "query: body-format, cursor, limit<=250, sort*, status* | header: If-None-Match, X-Trace* | no body",
    "PUT /api/v2/things/{id}/title": "no query | body: {status*, title*, version}",
    "GET /api/v2/things/{id}/versions": "query: depth, limit, username (deprecated) | no body",
    "GET /api/v2/things/{id}/odd-limit": "query: limit | no body",
    "POST /api/v2/things/{id}/labels": "no query | body: []",
    "POST /api/v2/things/{id}/merge": "no query | body: {name*, odd*, tag}",
    "POST /api/v2/things/{id}/open": "no query | body: {name*, note, ...}",
    "POST /api/v2/things/{id}/free": "no query | body: {...}",
    "POST /api/v2/things/{id}/choice": "no query | body: [] or {name*}",
    "POST /api/v2/things/{id}/either": "no query | body: {name*} or {name, tag}",
    "POST /api/v2/things/{id}/maybe": "no query | optional body: {name*}",
    "POST /api/v2/things/{id}/upload": "no query | not JSON (multipart/form-data: comment, file*)",
    "PUT /api/v2/things/{id}/raw": "no query | not JSON (text/plain)",
    "POST /api/v2/things/{id}/anything": "no query | body: any",
    "POST /api/v2/things/{id}/vendor": "no query | body: {name*}",
    "POST /api/v2/things/{id}/both": "no query | body: {name*}",
    "DELETE /api/v2/things/{id}/purge": "no query | no body",
}


def rich_v1() -> dict:
    return document("1.0.0", {
        "/wiki/rest/api/search": {"get": {"parameters": [
            {"name": "cql", "in": "query", "required": True, "schema": {"type": "string"}},
            {"name": "limit", "in": "query", "schema": {"type": "integer", "maximum": 100}},
            {"name": "expand", "in": "query", "style": "form", "explode": False, "schema": {"type": "array", "items": {"type": "string"}}},
        ]}},
        "/wiki/rest/api/user/watch/space/{spaceKey}": {"post": {"parameters": [
            {"name": "spaceKey", "in": "path", "required": True, "schema": {"type": "string"}},
            {"name": "X-Atlassian-Token", "in": "header", "required": True, "schema": {"type": "string", "default": "no-check"}},
        ]}},
    })


class ParameterFilesTest(unittest.TestCase):
    """What the script writes into the two parameter files, for a document that has one of everything."""

    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(folder.cleanup)
        root = Path(folder.name)
        (root / "v2.json").write_text(json.dumps(rich_v2()), encoding="utf-8")
        (root / "v1.json").write_text(json.dumps(rich_v1()), encoding="utf-8")
        cls.done = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--v2", str(root / "v2.json"), "--v1", str(root / "v1.json"), "--out-dir", str(root / "out"), "--read-on", "2026-11-30"],
            capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        cls.v2 = (root / "out" / "confluence_cloud_v2_parameters.txt").read_bytes().decode("utf-8")
        cls.v1 = (root / "out" / "confluence_cloud_v1_parameters.txt").read_bytes().decode("utf-8")
        cls.endpoints = (root / "out" / "confluence_cloud_v2_endpoints.txt").read_text(encoding="utf-8")

    @staticmethod
    def lines(text: str) -> dict[str, str]:
        found = {}
        for line in text.splitlines():
            if line and not line.startswith("#"):
                call, _, rest = line.partition(" | ")
                found[call] = rest
        return found

    def test_it_ran(self):
        self.assertEqual(self.done.returncode, 0, self.done.stderr)

    def test_every_operation_has_the_line_that_the_document_gives_it(self):
        found = self.lines(self.v2)
        for call, expected in RICH_V2.items():
            with self.subTest(call=call):
                self.assertEqual(found.get(call), expected)
        self.assertEqual(set(found), set(RICH_V2))

    def test_the_lines_are_in_the_order_of_the_endpoint_list(self):
        listed = [line.rsplit(" deprecated", 1)[0] for line in self.endpoints.splitlines() if not line.startswith("#")]
        self.assertEqual(list(self.lines(self.v2)), listed)
        self.assertEqual(len(listed), len(RICH_V2))

    def test_the_header_says_where_the_file_comes_from_and_how_to_read_a_line(self):
        header = "\n".join(line for line in self.v2.splitlines() if line.startswith("#"))
        self.assertIn("(info.version 2.0.1, read on 2026-11-30): 18 operations, those of confluence_cloud_v2_endpoints.txt.", header)
        self.assertIn("https://dac-static.atlassian.com/cloud/confluence/openapi-v2.v3.json", header)
        for needle in ("`no query`", "`no body`", "`not JSON (", "`optional `", "`<=N`", "`(deprecated)`", "`...`", "strict_parameters"):
            self.assertIn(needle, header)
        self.assertNotIn("\r", self.v2 + self.v1)

    def test_a_v1_document_gives_its_lines_without_the_wiki_prefix(self):
        self.assertEqual(self.lines(self.v1), {
            "GET /rest/api/search": "query: cql*, expand, limit<=100 | no body",
            "POST /rest/api/user/watch/space/{spaceKey}": "no query | header: X-Atlassian-Token* | no body",
        })

    def test_the_maximum_is_read_for_limit_only_and_only_when_it_is_a_whole_number(self):
        found = self.lines(self.v2)
        self.assertEqual(found["GET /api/v2/things/{id}/versions"], "query: depth, limit, username (deprecated) | no body")  # a maximum of `depth` is none of the limit
        self.assertEqual(found["GET /api/v2/things/{id}/odd-limit"], "query: limit | no body")  # 2.5 is no maximum that a limit can have
        self.assertEqual(found["GET /api/v2/things/{id}"].split(" | ")[0], "query: body-format, cursor, limit<=250, sort*, status*")  # one that a $ref gives

    def test_the_mock_side_reads_what_the_script_wrote(self):
        rules = parse_rules(self.v2)
        read = rules[("GET", "/api/v2/things/{id}")]
        self.assertEqual([(entry.name, entry.required, entry.maximum) for entry in read.query],
                         [("body-format", False, None), ("cursor", False, None), ("limit", False, 250), ("sort", True, None), ("status", True, None)])
        self.assertEqual([(entry.name, entry.required) for entry in read.headers], [("If-None-Match", False), ("X-Trace", True)])
        self.assertEqual(rules[("GET", "/api/v2/things/{id}/versions")].query[-1].deprecated, True)
        self.assertEqual(rules[("POST", "/api/v2/things/{id}/choice")].shapes[0].kind, "array")
        self.assertEqual(rules[("POST", "/api/v2/things/{id}/open")].shapes[0].open, True)
        self.assertEqual(rules[("POST", "/api/v2/things/{id}/maybe")].body_required, False)
        upload = rules[("POST", "/api/v2/things/{id}/upload")]
        self.assertEqual((upload.body, upload.media, upload.fields), ("other", "multipart/form-data", (("comment", False), ("file", True))))
        self.assertEqual(rules[("DELETE", "/api/v2/things/{id}/purge")].body, "none")
        self.assertEqual(len(rules), len(RICH_V2))


class ParameterFilesInTheRepositoryTest(unittest.TestCase):
    """The two files that the script wrote from the two documents, as the tests of the mock read them."""

    def test_they_have_the_format_that_the_script_writes_and_say_where_they_come_from(self):
        for path, version, url, count in (
            (V2_PARAMETERS, "v2", "https://dac-static.atlassian.com/cloud/confluence/openapi-v2.v3.json", 252),
            (V1_PARAMETERS, "v1", "https://dac-static.atlassian.com/cloud/confluence/swagger.v3.json", 130),
        ):
            with self.subTest(file=path.name):
                text = path.read_bytes().decode("utf-8")
                self.assertNotIn("\r", text)
                self.assertTrue(text.startswith("# The query parameters, the headers and the request body that the Confluence Cloud REST API"))
                header = "\n".join(line for line in text.splitlines() if line.startswith("#"))
                self.assertIn(url, header)
                self.assertIn("read on 2026-10-30", header)
                self.assertIn(f"{count} operations, those of confluence_cloud_{version}_endpoints.txt", header)
                self.assertEqual(len(parameter_rules(version)), count)

    def test_they_describe_the_operations_of_the_lists_in_the_same_order(self):
        for version, path in (("v2", V2_PARAMETERS), ("v1", V1_PARAMETERS)):
            with self.subTest(version=version):
                lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
                self.assertEqual([line.split(" | ")[0] for line in lines], [f"{method} {template}" for method, template, _ in documented_calls(version)])


if __name__ == "__main__":
    unittest.main()
