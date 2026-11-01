"""The mock Confluence refuses a request that the parameter file of its API does not allow, when `strict_parameters` is on, and records it."""
from __future__ import annotations

import base64
import http.client
import json
import unittest
from typing import Any
from urllib.parse import urlencode, urlsplit

from tests.support.mock_confluence import MockConfluence

BOUNDARY = "----sweep"


def form(*fields: tuple[str, str], file_name: str = "report.txt", with_file: bool = True) -> bytes:
    parts = []
    if with_file:
        parts.append(f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="{file_name}"\r\nContent-Type: text/plain\r\n\r\nreport\r\n')
    for name, value in fields:
        parts.append(f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n')
    return ("".join(parts) + f"--{BOUNDARY}--\r\n").encode("utf-8")


class StrictParametersTest(unittest.TestCase):
    def setUp(self):
        self.mock = MockConfluence()
        self.mock.strict_parameters = True
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def send(self, method: str, path: str, *, query: dict[str, Any] | None = None, body: Any = None, raw: bytes | None = None,
             content_type: str | None = None, headers: dict[str, str] | None = None, mock: MockConfluence | None = None) -> tuple[int, Any]:
        mock = mock or self.mock
        token = base64.b64encode(f"{mock.email}:{mock.token}".encode("utf-8")).decode("ascii")
        sent = {"Authorization": f"Basic {token}", **(headers or {})}
        data = raw
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            sent["Content-Type"] = content_type or "application/json"
        elif content_type:
            sent["Content-Type"] = content_type
        target = f"{mock.context_path}{path}" + (f"?{urlencode(query, doseq=True)}" if query else "")
        split = urlsplit(mock.base_url)
        connection = http.client.HTTPConnection(split.hostname, split.port, timeout=10)
        try:
            connection.request(method, target, body=data, headers=sent)
            response = connection.getresponse()
            payload = response.read()
            return response.status, json.loads(payload) if payload else None
        finally:
            connection.close()

    def refused(self, status: int, payload: Any, *needles: str) -> str:
        self.assertEqual(status, 400, payload)
        text = json.dumps(payload)
        for needle in needles:
            self.assertIn(needle, text)
        return text

    def test_it_is_off_unless_a_test_turns_it_on_and_then_a_request_that_the_document_does_not_allow_is_answered_as_before(self):
        quiet = MockConfluence()
        self.assertFalse(quiet.strict_parameters)
        quiet.start()
        self.addCleanup(quiet.stop)
        status, _ = self.send("PUT", "/api/v2/pages/2002/title", body={"status": "current", "title": "Quiet", "colour": "red"}, mock=quiet)
        self.assertEqual(status, 200)
        self.assertEqual((quiet.invalid_requests, quiet.deprecated_parameters), ([], []))

    def test_an_unknown_query_parameter_is_a_400_in_the_style_of_v2_and_is_recorded(self):
        status, payload = self.send("GET", "/api/v2/pages/2002", query={"bogus": "1"})
        self.refused(status, payload, "bogus", "is not one of the operation's")
        error = payload["errors"][0]
        self.assertEqual((error["status"], error["code"], error["title"]), (400, "INVALID_REQUEST_PARAMETER", "Invalid request parameter"))
        self.assertEqual(len(self.mock.invalid_requests), 1)
        self.assertTrue(self.mock.invalid_requests[0].startswith("GET /api/v2/pages/2002 (v2 document): the query parameter bogus"))

    def test_the_same_in_the_style_of_v1(self):
        status, payload = self.send("GET", "/rest/api/search", query={"cql": "type = page", "bogus": "1"})
        self.refused(status, payload, "bogus")
        self.assertEqual((payload["statusCode"], payload["data"]["errors"][0]["message"]["key"], payload["data"]["successful"]), (400, "BAD_REQUEST", False))
        self.assertTrue(self.mock.invalid_requests[0].startswith("GET /rest/api/search (v1 document):"))

    def test_a_required_query_parameter_that_is_missing(self):
        status, payload = self.send("GET", "/rest/api/search", query={"limit": "5"})
        self.refused(status, payload, "the required query parameter cql is missing")
        status, payload = self.send("GET", "/api/v2/pages/2002/custom-content")
        self.refused(status, payload, "the required query parameter type is missing")
        self.assertEqual(len(self.mock.invalid_requests), 2)

    def test_a_limit_above_the_documented_maximum(self):
        status, payload = self.send("GET", "/api/v2/pages", query={"limit": "251"})
        self.refused(status, payload, "limit 251 is above the documented maximum of 250")
        status, _ = self.send("GET", "/api/v2/pages", query={"limit": "250"})
        self.assertEqual(status, 200)
        status, payload = self.send("GET", "/rest/api/space/ENG/state/content", query={"limit": "101", "state-id": "1"})
        self.refused(status, payload, "limit 101 is above the documented maximum of 100")
        self.assertEqual(len(self.mock.invalid_requests), 2)

    def test_a_json_body_with_a_property_that_the_schema_does_not_list(self):
        status, payload = self.send("PUT", "/api/v2/pages/2002/title", body={"status": "current", "title": "Coloured", "colour": "red"})
        self.refused(status, payload, "the request body has the property colour", "(status, title)")
        self.assertEqual(self.mock.pages["2002"]["title"], "Release notes")  # the page was not changed

    def test_a_json_body_that_lacks_a_required_property(self):
        status, payload = self.send("PUT", "/api/v2/pages/2002/title", body={"status": "current"})
        self.refused(status, payload, "the request body lacks the required property title")

    def test_a_json_body_of_the_wrong_kind(self):
        status, payload = self.send("PUT", "/api/v2/pages/2002/title", body=["status"])
        self.refused(status, payload, "the request body is a JSON array, and the document describes an object")
        status, payload = self.send("POST", "/api/v2/spaces/1001/role-assignments", body={"principal": {}})
        self.refused(status, payload, "the request body is a JSON object, and the document describes an array")

    def test_a_body_for_an_operation_that_has_none_and_a_missing_body_that_the_document_requires(self):
        status, payload = self.send("GET", "/api/v2/pages/2002", body={"title": "x"})
        self.refused(status, payload, "lists no request body for this operation")
        status, payload = self.send("PUT", "/api/v2/pages/2002/title")
        self.refused(status, payload, "requires a request body, and the request has none")

    def test_a_json_body_that_is_not_sent_as_json(self):
        status, payload = self.send("PUT", "/api/v2/pages/2002/title", raw=b'{"status": "current", "title": "Plain"}', content_type="text/plain")
        self.refused(status, payload, "sent as text/plain, and the document describes JSON")

    def test_a_form_field_that_is_missing_or_not_the_documents(self):
        path = "/rest/api/content/2002/child/attachment"
        multipart = f"multipart/form-data; boundary={BOUNDARY}"
        status, payload = self.send("POST", path, raw=form(), content_type=multipart, headers={"X-Atlassian-Token": "nocheck"})
        self.refused(status, payload, "the required form field minorEdit is missing")
        status, payload = self.send("POST", path, raw=form(("minorEdit", "false"), ("colour", "red")), content_type=multipart, headers={"X-Atlassian-Token": "nocheck"})
        self.refused(status, payload, "the form field colour is not one of the operation's (comment, file, minorEdit)")
        status, payload = self.send("POST", path, raw=form(("minorEdit", "false"), ("comment", "A comment")), content_type=multipart, headers={"X-Atlassian-Token": "nocheck"})
        self.assertEqual(status, 200, payload)
        self.assertEqual(len(self.mock.invalid_requests), 2)

    def test_a_required_header_that_is_missing(self):
        status, payload = self.send("POST", "/rest/api/user/watch/space/ENG", query={"accountId": "5b10ac8d82e05b22cc7d4ef5"})
        self.refused(status, payload, "the required header X-Atlassian-Token is missing")

    def test_a_query_parameter_that_the_document_marks_as_deprecated_is_answered_and_recorded_apart(self):
        self.send("GET", "/rest/api/user/watch/content/2002", query={"username": "alex"})
        self.assertEqual(self.mock.invalid_requests, [])
        self.assertEqual(self.mock.deprecated_parameters, ["GET /rest/api/user/watch/content/2002 (v1 document): the query parameter username is deprecated"])

    def test_a_request_that_fits_is_answered_and_leaves_no_record(self):
        for method, path, options in (
            ("GET", "/api/v2/pages/2002", {"query": {"body-format": "storage"}}),
            ("GET", "/api/v2/spaces", {"query": {"limit": "25", "sort": "key"}}),
            ("PUT", "/api/v2/pages/2002/title", {"body": {"status": "current", "title": "A fitting title"}}),
        ):
            with self.subTest(call=f"{method} {path}"):
                status, payload = self.send(method, path, **options)
                self.assertEqual(status, 200, payload)
        self.assertEqual((self.mock.invalid_requests, self.mock.deprecated_parameters), ([], []))

    def test_a_call_that_the_documents_do_not_list_stays_the_404_it_was(self):
        status, _ = self.send("GET", "/api/v2/pages/2002/nothing", query={"bogus": "1"})
        self.assertEqual(status, 404)
        self.assertEqual(self.mock.unknown_endpoints, ["GET /api/v2/pages/2002/nothing (v2 document)"])
        self.assertEqual(self.mock.invalid_requests, [])

    def test_a_refusal_of_one_request_does_not_stop_the_next(self):
        self.send("GET", "/api/v2/pages/2002", query={"bogus": "1"})
        status, _ = self.send("GET", "/api/v2/pages/2002")
        self.assertEqual(status, 200)
        self.assertEqual(len(self.mock.invalid_requests), 1)

    def test_a_failure_that_a_test_injects_still_wins_over_a_fitting_request(self):
        self.mock.fail_next("/api/v2/pages/2002", 503)
        status, _ = self.send("GET", "/api/v2/pages/2002")
        self.assertEqual(status, 503)

    def test_the_names_of_the_query_of_a_documented_call_are_recorded_for_the_sweep_to_say_which_names_it_sent(self):
        self.send("GET", "/api/v2/pages", query={"limit": "5", "body-format": "storage"})
        self.send("GET", "/api/v2/pages", query={"bogus": "1"})  # it was sent, and refused
        self.send("GET", "/api/v2/nothing", query={"never": "1"})  # no call of the document
        self.send("GET", "/_edge/tenant_info", query={"outside": "1"})  # no REST call
        self.assertEqual(self.mock.seen_query_names, {"limit", "body-format", "bogus"})
        quiet = MockConfluence()  # without the strictness the record is the same
        self.assertEqual(quiet.seen_query_names, set())
        quiet.start()
        self.addCleanup(quiet.stop)
        self.send("GET", "/api/v2/pages", query={"limit": "5", "bogus": "1"}, mock=quiet)
        self.assertEqual(quiet.seen_query_names, {"limit", "bogus"})


if __name__ == "__main__":
    unittest.main()
