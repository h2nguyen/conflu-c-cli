"""How the mock reads a parameter file, and what it says is wrong with a request that is measured against one (`tests/support/conformance.py`)."""
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from tests.support import conformance
from tests.support.conformance import (
    Call,
    check_rules,
    classify,
    deprecated_parameters,
    multipart_names,
    names_in_source,
    names_option,
    options_without_a_line,
    parse_rules,
    query_names,
    request_problems,
)

TEXT = """# a comment

GET /api/v2/things | query: cursor, limit<=250, status* | no body
GET /api/v2/things/{id} | no query | header: If-None-Match, X-Token* | no body
POST /api/v2/things | no query | body: {parentId, spaceId*, title*}
PUT /api/v2/things/{id} | query: draft (deprecated), version<=9 | optional body: {...}
POST /api/v2/things/{id}/labels | no query | body: [] or {name*, prefix*, ...}
POST /api/v2/things/{id}/upload | query: status | not JSON (multipart/form-data: comment, file*, minorEdit*)
PUT /api/v2/things/{id}/raw | no query | optional not JSON (text/plain)
POST /api/v2/things/{id}/anything | no query | body: any
DELETE /api/v2/things/{id}/purge | no query | no body
"""
JSON = "application/json"


def call(method: str = "POST", template: str = "/api/v2/things") -> Call:
    return Call(method, template, "v2", template, documented=True)


def part(name: str, value: bytes, filename: str = "") -> bytes:
    disposition = f'Content-Disposition: form-data; name="{name}"' + (f'; filename="{filename}"' if filename else "")
    return b"--b\r\n" + disposition.encode() + b"\r\n\r\n" + value + b"\r\n"


def multipart(*parts: bytes) -> bytes:
    return b"".join(parts) + b"--b--\r\n"


class ReadingAParameterFileTest(unittest.TestCase):
    rules = parse_rules(TEXT)

    def rule(self, method: str, template: str):
        return self.rules[(method, template)]

    def test_a_comment_and_a_blank_line_are_skipped_and_every_operation_is_read(self):
        self.assertEqual(len(self.rules), 9)
        self.assertEqual(self.rule("GET", "/api/v2/things").template, "/api/v2/things")

    def test_the_parts_of_a_query(self):
        query = self.rule("GET", "/api/v2/things").query
        self.assertEqual([(entry.name, entry.required, entry.maximum, entry.deprecated) for entry in query],
                         [("cursor", False, None, False), ("limit", False, 250, False), ("status", True, None, False)])
        self.assertEqual(self.rule("POST", "/api/v2/things").query, ())
        put = self.rule("PUT", "/api/v2/things/{id}").query
        self.assertEqual([(entry.name, entry.deprecated, entry.maximum) for entry in put], [("draft", True, None), ("version", False, 9)])

    def test_the_headers_of_an_operation(self):
        headers = self.rule("GET", "/api/v2/things/{id}").headers
        self.assertEqual([(entry.name, entry.required) for entry in headers], [("If-None-Match", False), ("X-Token", True)])
        self.assertEqual(self.rule("GET", "/api/v2/things").headers, ())

    def test_what_a_json_body_may_be(self):
        post = self.rule("POST", "/api/v2/things")
        self.assertEqual((post.body, post.body_required), ("json", True))
        self.assertEqual([(shape.kind, shape.properties, shape.open) for shape in post.shapes], [("object", (("parentId", False), ("spaceId", True), ("title", True)), False)])
        either = self.rule("POST", "/api/v2/things/{id}/labels").shapes
        self.assertEqual([(shape.kind, shape.properties, shape.open) for shape in either], [("array", (), False), ("object", (("name", True), ("prefix", True)), True)])
        self.assertEqual([(shape.kind, shape.open) for shape in self.rule("PUT", "/api/v2/things/{id}").shapes], [("object", True)])
        self.assertEqual([shape.kind for shape in self.rule("POST", "/api/v2/things/{id}/anything").shapes], ["any"])

    def test_a_body_that_may_be_left_out_and_one_that_is_not_json(self):
        self.assertEqual(self.rule("PUT", "/api/v2/things/{id}").body_required, False)
        upload = self.rule("POST", "/api/v2/things/{id}/upload")
        self.assertEqual((upload.body, upload.body_required, upload.media), ("other", True, "multipart/form-data"))
        self.assertEqual(upload.fields, (("comment", False), ("file", True), ("minorEdit", True)))
        raw = self.rule("PUT", "/api/v2/things/{id}/raw")
        self.assertEqual((raw.body, raw.body_required, raw.media, raw.fields), ("other", False, "text/plain", ()))
        self.assertEqual(self.rule("GET", "/api/v2/things").body, "none")

    def test_a_line_that_cannot_be_read_is_an_error_that_names_it(self):
        for line, said in (
            ("GET /api/v2/x | no query", "a line is METHOD path"),  # the body part is missing
            ("GET /api/v2/x | no body | no query", "a line is METHOD path"),  # the parts are in the wrong order
            ("get /api/v2/x | no query | no body", "starts with METHOD"),
            ("GET api/v2/x | no query | no body", "starts with METHOD"),
            ("GET /api/v2/x | query: a b | no body", "cannot read 'a b'"),
            ("GET /api/v2/x | query: | no body", "cannot read the part 'query:'"),
            ("GET /api/v2/x | no query | body: {a", "cannot read the body"),
            ("GET /api/v2/x | no query | something else", "cannot read the part"),
        ):
            with self.subTest(line=line), self.assertRaises(ValueError) as caught:
                parse_rules("# header\n" + line + "\n")
            self.assertIn("line 2 of the parameter file", str(caught.exception))
            self.assertIn(said, str(caught.exception))

    def test_the_files_of_the_repository_are_read_without_an_error(self):
        for version, count in (("v2", 252), ("v1", 130)):
            self.assertEqual(len(conformance.parameter_rules(version)), count)


class TheQueryTest(unittest.TestCase):
    rules = parse_rules(TEXT)

    def problems(self, method: str, template: str, query: dict[str, list[str]]) -> list[str]:
        return check_rules(call(method, template), self.rules[(method, template)], query)

    def test_a_request_that_fits_has_no_problem(self):
        self.assertEqual(self.problems("GET", "/api/v2/things", {"status": ["current"], "limit": ["250"], "cursor": ["abc"]}), [])

    def test_a_query_parameter_that_is_not_the_operations_is_named_with_those_that_are(self):
        found = self.problems("GET", "/api/v2/things", {"status": ["current"], "bogus": ["1"]})
        self.assertEqual(found, ["the query parameter bogus is not one of the operation's (cursor, limit, status)"])

    def test_an_operation_without_query_parameters_says_so(self):
        found = self.problems("DELETE", "/api/v2/things/{id}/purge", {"draft": ["true"]})
        self.assertEqual(found, ["the query parameter draft is not one of the operation's (it has none)"])

    def test_a_required_query_parameter_that_is_missing(self):
        self.assertEqual(self.problems("GET", "/api/v2/things", {}), ["the required query parameter status is missing"])

    def test_a_limit_above_the_documented_maximum(self):
        found = self.problems("GET", "/api/v2/things", {"status": ["current"], "limit": ["251"]})
        self.assertEqual(found, ["limit 251 is above the documented maximum of 250"])
        self.assertEqual(self.problems("GET", "/api/v2/things", {"status": ["current"], "limit": ["1", "999"]}), ["limit 999 is above the documented maximum of 250"])

    def test_a_limit_that_is_no_number_is_left_to_the_routes_of_the_mock(self):
        self.assertEqual(self.problems("GET", "/api/v2/things", {"status": ["current"], "limit": ["many"]}), [])

    def test_several_problems_are_all_named(self):
        found = self.problems("GET", "/api/v2/things", {"bogus": [""], "limit": ["300"]})
        self.assertEqual(len(found), 3)

    def test_what_the_document_marks_as_deprecated_is_no_problem_but_is_found(self):
        query = {"draft": ["true"], "version": ["2"]}
        self.assertEqual(self.problems("PUT", "/api/v2/things/{id}", query), [])
        rules = self.rules[("PUT", "/api/v2/things/{id}")]
        with mock.patch.object(conformance, "rules_for", return_value=rules):
            self.assertEqual(deprecated_parameters(call("PUT", "/api/v2/things/{id}"), query), ["draft"])
            self.assertEqual(deprecated_parameters(call("PUT", "/api/v2/things/{id}"), {"version": ["2"]}), [])


class TheHeadersTest(unittest.TestCase):
    rules = parse_rules(TEXT)

    def test_a_required_header_that_is_missing_is_named_and_the_case_of_its_name_does_not_matter(self):
        rule = self.rules[("GET", "/api/v2/things/{id}")]
        target = call("GET", "/api/v2/things/{id}")
        self.assertEqual(check_rules(target, rule, {}, {"accept": "application/json"}), ["the required header X-Token is missing"])
        self.assertEqual(check_rules(target, rule, {}, {"x-token": "1"}), [])
        self.assertEqual(check_rules(target, rule, {}, {"X-TOKEN": "1"}), [])


class TheBodyTest(unittest.TestCase):
    rules = parse_rules(TEXT)

    def problems(self, method: str, template: str, body=None, *, content_type: str = JSON, raw: bytes | None = None) -> list[str]:
        sent = raw if raw is not None else b"" if body is None else json.dumps(body).encode("utf-8")
        return check_rules(call(method, template), self.rules[(method, template)], {}, {}, content_type, sent)

    def test_a_body_that_fits_has_no_problem(self):
        self.assertEqual(self.problems("POST", "/api/v2/things", {"spaceId": "1", "title": "t", "parentId": "2"}), [])

    def test_a_property_that_the_schema_does_not_list(self):
        found = self.problems("POST", "/api/v2/things", {"spaceId": "1", "title": "t", "colour": "red"})
        self.assertEqual(found, ["the request body has the property colour, which is not one of the operation's (parentId, spaceId, title)"])

    def test_a_required_property_that_is_missing(self):
        self.assertEqual(self.problems("POST", "/api/v2/things", {"title": "t"}), ["the request body lacks the required property spaceId"])

    def test_an_object_that_accepts_other_properties_still_has_its_required_ones(self):
        self.assertEqual(self.problems("POST", "/api/v2/things/{id}/labels", {"name": "a", "prefix": "global", "extra": 1}), [])
        self.assertEqual(self.problems("POST", "/api/v2/things/{id}/labels", {"extra": 1}),
                         ["the request body lacks the required property name", "the request body lacks the required property prefix",
                          "(the document offers 2 shapes of body, and this is the closest)"])

    def test_an_array_where_the_document_has_one_among_its_shapes(self):
        self.assertEqual(self.problems("POST", "/api/v2/things/{id}/labels", [{"name": "a", "prefix": "global"}]), [])

    def test_the_kind_of_json_must_be_the_documented_one(self):
        self.assertEqual(self.problems("POST", "/api/v2/things", [1]), ["the request body is a JSON array, and the document describes an object"])
        self.assertEqual(self.problems("POST", "/api/v2/things", "text"), ["the request body is a JSON value, and the document describes an object"])
        self.assertEqual(self.problems("POST", "/api/v2/things/{id}/anything", [1]), [])

    def test_a_body_that_the_operation_does_not_have(self):
        found = check_rules(call("GET", "/api/v2/things"), self.rules[("GET", "/api/v2/things")], {"status": ["x"]}, {}, JSON, b"{}")
        self.assertEqual(found, ["the document lists no request body for this operation, and the request has one (2 bytes)"])

    def test_a_required_body_that_is_missing_and_one_that_may_be_left_out(self):
        self.assertEqual(self.problems("POST", "/api/v2/things"), ["the document requires a request body, and the request has none"])
        self.assertEqual(self.problems("PUT", "/api/v2/things/{id}"), [])

    def test_a_body_that_is_not_sent_as_json(self):
        found = self.problems("POST", "/api/v2/things", raw=b'{"title": "t", "spaceId": "1"}', content_type="text/plain; charset=utf-8")
        self.assertEqual(found, ["the request body is sent as text/plain, and the document describes JSON"])
        found = self.problems("POST", "/api/v2/things", raw=b'{"title": "t", "spaceId": "1"}', content_type="")
        self.assertEqual(found, ["the request body is sent as no content type, and the document describes JSON"])
        self.assertEqual(self.problems("POST", "/api/v2/things", {"title": "t", "spaceId": "1"}, content_type="application/vnd.api+json; charset=utf-8"), [])

    def test_a_body_that_is_no_json_is_left_to_the_mock_to_answer(self):
        self.assertEqual(self.problems("POST", "/api/v2/things", raw=b"{oops"), [])

    def test_a_form_field_that_is_not_the_operations_and_one_that_is_missing(self):
        body = multipart(part("file", b"hello", "a.txt"), part("oops", b"x"))
        found = self.problems("POST", "/api/v2/things/{id}/upload", raw=body, content_type="multipart/form-data; boundary=b")
        self.assertEqual(found, ["the form field oops is not one of the operation's (comment, file, minorEdit)", "the required form field minorEdit is missing"])
        fine = multipart(part("file", b"hello", "a.txt"), part("minorEdit", b"false"), part("comment", b"c"))
        self.assertEqual(self.problems("POST", "/api/v2/things/{id}/upload", raw=fine, content_type='multipart/form-data; boundary="b"'), [])

    def test_a_multipart_body_that_is_sent_as_something_else(self):
        found = self.problems("POST", "/api/v2/things/{id}/upload", raw=b"file=x", content_type="application/x-www-form-urlencoded")
        self.assertEqual(found, ["the request body is sent as application/x-www-form-urlencoded, and the document describes multipart/form-data"])

    def test_a_body_of_another_media_type_is_not_looked_into(self):
        self.assertEqual(self.problems("PUT", "/api/v2/things/{id}/raw", raw=b"plain text", content_type="text/plain"), [])

    def test_the_names_of_a_multipart_body_do_not_mistake_a_file_name_or_the_content_of_a_file_for_a_field(self):
        content = b'Content-Disposition: form-data; name="fake"\r\n\r\nnot a part'
        body = multipart(part("file", content, "name=\"other\".txt"), part("comment", b"c"))
        self.assertEqual(multipart_names(body, "multipart/form-data; boundary=b"), ["file", "comment"])
        self.assertIsNone(multipart_names(body, "multipart/form-data"))


class WhatIsAcceptedAlthoughUndocumentedTest(unittest.TestCase):
    rules = parse_rules(TEXT)

    def test_a_listed_exception_is_accepted_for_that_operation_only(self):
        table = {
            ("GET /api/v2/things", "query", "legacy"): "an older name that Confluence still reads.",
            ("POST /api/v2/things", "body", "colour"): "a property that Confluence ignores.",
        }
        with mock.patch.dict(conformance.ACCEPTED_BUT_UNDOCUMENTED, table):
            self.assertEqual(check_rules(call("GET", "/api/v2/things"), self.rules[("GET", "/api/v2/things")], {"status": ["x"], "legacy": ["1"]}), [])
            self.assertEqual(len(check_rules(call("GET", "/api/v2/things/{id}"), self.rules[("GET", "/api/v2/things/{id}")], {"legacy": ["1"]}, {"x-token": "1"})), 1)
            body = json.dumps({"title": "t", "spaceId": "1", "colour": "red"}).encode()
            self.assertEqual(check_rules(call("POST", "/api/v2/things"), self.rules[("POST", "/api/v2/things")], {}, {}, JSON, body), [])
            self.assertEqual(len(check_rules(call("POST", "/api/v2/things"), self.rules[("POST", "/api/v2/things")], {"colour": ["red"]}, {}, JSON, body)), 1)


class NamesInSourceTest(unittest.TestCase):
    """The query parameters that the source of an adapter puts into a request, found by reading it: `_query(include_labels=True)` is `include-labels`."""

    @staticmethod
    def read(*lines: str) -> dict[str, list[int]]:
        return names_in_source("\n".join(lines) + "\n")

    def test_the_keywords_of_a_query_builder_are_names_and_an_underscore_is_a_hyphen(self):
        found = self.read(
            "def read(self, page_id, fmt, key):",
            "    data = self._call('GET', f'{V2}/pages/{page_id}?{_query(body_format=fmt, include_labels=True, spaceKey=key)}')",
            "    return self._call('GET', _with_query(path, limit=5))",
            "    query(cursor=c)",
        )
        self.assertEqual(found, {"body-format": [2], "cursor": [4], "include-labels": [2], "limit": [3], "spaceKey": [2]})

    def test_the_keywords_of_any_other_call_are_no_names(self):
        found = self.read(
            "def read(self, page, labels):",
            "    page = replace(page, labels=labels, title='x')",
            "    print(limit=3)",
            "    return Chunk(items=[], next_cursor=None, status=1)",
        )
        self.assertEqual(found, {})

    def test_a_dict_that_is_spread_into_a_query_builder_gives_its_names(self):
        found = self.read(
            "def a(self, s):",
            "    common = dict(title=t, body_format=b, status='current')",
            "    return _query(sort=s, **common)",
            "def b(self, s):",
            "    common = {'cursor': c}",
            "    common['limit'] = n",
            "    return _query(**common)",
            "def c(self, e):",
            "    return _query(**{'expand': e}, **dict(depth=1))",
        )
        self.assertEqual(found, {"body-format": [2], "cursor": [5], "depth": [9], "expand": [9], "limit": [6], "sort": [3], "status": [2], "title": [2]})

    def test_a_dict_is_judged_in_its_own_function_only(self):
        found = self.read(
            "def body(self, name):",
            "    params = {'name': name, 'type': 'x'}",
            "    return self._call('POST', path, params)",
            "def read(self):",
            "    params = dict(limit=1)",
            "    return _query(**params)",
        )
        self.assertEqual(found, {"limit": [5]})

    def test_a_name_written_into_a_string_is_found_where_it_follows_a_question_mark_or_an_ampersand(self):
        found = self.read(
            "def read(self, c, n):",
            "    first = f'{V2}/pages?cursor={c}&limit={n}'",
            "    second = '/rest/api/search?cql=type=page&expand=space'",
        )
        self.assertEqual(found, {"cql": [3], "cursor": [2], "expand": [3], "limit": [2]})

    def test_a_string_that_is_read_or_is_a_value_or_a_message_is_no_name(self):
        found = self.read(
            '"""Reads `GET /attachments/{id}?version=N` and sends ?depth=2."""',
            "def read(self, data):",
            '    """The answer holds ?start=0 and &limit=5."""',
            "    link = data.get('next')",
            "    pairs = name.replace('_', '-')",
            "    chunk = _query(sort='name', title=title)",
            "    body = {'key': key, 'value': value, 'version': 1}",
            "    return 'Use --limit=5 and --space=ENG', link, pairs, chunk, body",
        )
        self.assertEqual(found, {"sort": [6], "title": [6]})

    def test_the_names_are_in_order_with_their_lines(self):
        found = self.read("def read(self):", "    _query(b=1)", "    _query(a=1, b=2)", "    _query(b=3)")
        self.assertEqual(list(found.items()), [("a", [3]), ("b", [2, 3, 4])])

    def test_a_source_without_a_query_names_nothing(self):
        self.assertEqual(self.read("x = 1"), {})
        self.assertEqual(self.read(""), {})


class OptionsWithoutALineTest(unittest.TestCase):
    """Which options of the commands no sweep line names: the spec of a command and the arguments of a line are all that it looks at."""

    @staticmethod
    def command(name: str, *options: str, aliases: tuple[str, ...] = ()):
        args = [SimpleNamespace(names=tuple(option.split("/")), positional=not option.startswith("-")) for option in options]
        return SimpleNamespace(name=name, aliases=aliases, args=tuple(args))

    def test_an_option_is_named_by_its_name_alone_or_with_a_value_or_with_an_equals_sign(self):
        self.assertTrue(names_option(("2002", "--cursor", "2"), ("--cursor",)))
        self.assertTrue(names_option(("2002", "--cursor=2"), ("--cursor",)))
        self.assertTrue(names_option(("2002", "--all"), ("--all",)))
        self.assertTrue(names_option(("2002", "-n", "5"), ("--limit", "-n")))  # under any of its names
        self.assertFalse(names_option(("2002", "--cursors", "2"), ("--cursor",)))
        self.assertFalse(names_option(("2002", "--cursor-x=2"), ("--cursor",)))
        self.assertFalse(names_option((), ("--cursor",)))

    def test_the_options_that_no_line_of_the_command_names_are_listed_in_the_order_of_the_spec(self):
        page = self.command("page", "ref", "--outline", "--out", "--force")
        found = options_without_a_line([page], [("page", "2002", "--outline"), ("page", "2002", "--force")])
        self.assertEqual(found, [("page", "--out")])

    def test_a_positional_argument_is_no_option(self):
        self.assertEqual(options_without_a_line([self.command("page", "ref", "files")], []), [])

    def test_an_option_in_the_line_of_another_command_does_not_count(self):
        found = options_without_a_line([self.command("page", "--out"), self.command("blogpost", "--out")], [("blogpost", "7101", "--out", "x")])
        self.assertEqual(found, [("page", "--out")])

    def test_a_line_that_names_the_command_by_an_alias_counts(self):
        found = options_without_a_line([self.command("diff", "--context", aliases=("compare",))], [("compare", "2002", "--context", "0")])
        self.assertEqual(found, [])

    def test_an_option_is_listed_by_its_first_name(self):
        found = options_without_a_line([self.command("diff", "--from-version/--from")], [("diff", "2002")])
        self.assertEqual(found, [("diff", "--from-version")])
        self.assertEqual(options_without_a_line([self.command("diff", "--from-version/--from")], [("diff", "2002", "--from", "1")]), [])

    def test_a_command_with_no_line_has_all_its_options_left(self):
        self.assertEqual(options_without_a_line([self.command("api", "--param", "--write")], []), [("api", "--param"), ("api", "--write")])


class TheRealFilesTest(unittest.TestCase):
    def test_every_query_parameter_of_either_document_is_a_name(self):
        names = query_names()
        for name in ("body-format", "space-id", "include-labels", "limit", "cursor", "cql", "expand", "spaceKey", "accountId", "_"):
            self.assertIn(name, names)
        for name in ("parentId", "representation", "spaceId", "storage", "File"):  # the names of bodies, which are no query parameter of an operation
            self.assertNotIn(name, names)

    def test_a_call_that_is_documented_is_measured_against_its_line(self):
        found = request_problems(classify("GET", "/api/v2/pages/1"), {"bogus": ["1"]})
        self.assertEqual(len(found), 1)
        self.assertIn("the query parameter bogus is not one of the operation's (body-format, get-draft,", found[0])
        self.assertEqual(request_problems(classify("GET", "/api/v2/pages"), {"limit": ["251"]}), ["limit 251 is above the documented maximum of 250"])

    def test_a_call_that_the_documents_do_not_list_has_no_line_to_be_measured_against(self):
        self.assertEqual(request_problems(classify("GET", "/api/v2/nothing"), {"bogus": ["1"]}), [])
        self.assertEqual(request_problems(classify("GET", "/_edge/tenant_info"), {"bogus": ["1"]}), [])
        self.assertEqual(deprecated_parameters(classify("GET", "/api/v2/nothing"), {"username": ["1"]}), [])

    def test_the_v1_document_marks_the_old_names_of_a_person_as_deprecated(self):
        target = classify("POST", "/rest/api/user/watch/space/ENG")
        self.assertEqual(deprecated_parameters(target, {"username": ["x"], "key": ["y"], "accountId": ["z"]}), ["key", "username"])
        self.assertEqual(request_problems(target, {"accountId": ["z"]}, {}), ["the required header X-Atlassian-Token is missing"])

    def test_the_upload_of_an_attachment_is_measured_against_the_form_that_the_document_describes(self):
        target = classify("POST", "/rest/api/content/2002/child/attachment")
        body = multipart(part("file", b"hello", "a.txt"))
        found = request_problems(target, {}, {}, "multipart/form-data; boundary=b", body)
        self.assertEqual(found, ["the required form field minorEdit is missing"])


if __name__ == "__main__":
    unittest.main()
