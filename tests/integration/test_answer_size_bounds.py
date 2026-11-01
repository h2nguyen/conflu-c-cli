"""An answer that holds more objects than any answer of Confluence holds is not read.

The size of an answer is bounded (64 MiB), the memory that it takes once it is read is not: 400,000 empty objects are a text of 1.2 MB (a gzip answer of
1.2 KB), and every one of them became a result that was mapped, so that `pages --limit 25` took eight seconds and half a gigabyte, and printed 400,000
results. A request returns 250 results at most (100 for the older API), so more than a thousand is no answer of Confluence, and neither is an answer of
more than a quarter of a million objects. Here: the real gateway and the real program against a small server on this computer.
"""
import json
import time
import unittest

from conflu_c_cli.adapters.driven.confluence_rest import MAX_OBJECTS, MAX_RESULTS
from conflu_c_cli.domain.errors import UnavailableError
from tests.integration.test_unreadable_answers import StubbedCase

JSON = {"Content-Type": "application/json"}


def properties(count: int) -> bytes:
    return json.dumps({"results": [{"id": str(number), "key": f"k{number}", "value": number} for number in range(count)]}).encode("utf-8")


class ResultsTest(StubbedCase):
    def test_a_thousand_results_are_read_as_they_always_were(self):
        answers = self.serve(properties(MAX_RESULTS), headers=JSON)
        self.assertEqual(len(self.gateway(answers).list_properties("page", "2002").items), MAX_RESULTS)

    def test_one_more_is_no_answer_of_confluence(self):
        answers = self.serve(properties(MAX_RESULTS + 1), headers=JSON)
        with self.assertRaises(UnavailableError) as caught:
            self.gateway(answers).list_properties("page", "2002")
        self.assertIn("1,001 results", caught.exception.message)
        self.assertIn("1,000 at most", caught.exception.message)
        self.assertEqual(caught.exception.details["status"], 200)
        self.assertEqual(caught.exception.details["request"], "GET /api/v2/pages/2002/properties")

    def test_it_holds_for_what_is_not_a_list_of_properties_too(self):
        answers = self.serve(b'{"results":[' + b"{}," * 5000 + b"{}]}", headers=JSON)
        gateway = self.gateway(answers)
        for name, read in self.reads(gateway).items():
            with self.subTest(name), self.assertRaises(UnavailableError) as caught:
                read()
            self.assertIn("5,001 results", caught.exception.message)

    def test_a_refusal_with_such_a_body_is_not_read_either(self):
        answers = self.serve(properties(MAX_RESULTS + 1), status=404, headers=JSON)
        with self.assertRaises(UnavailableError):
            self.gateway(answers).list_properties("page", "2002")


class ObjectsTest(StubbedCase):
    def test_the_answer_of_the_report_is_refused_at_once(self):
        answers = self.serve(b'{"results":[' + b"{}," * 400_000 + b"{}]}", headers=JSON)
        code, out, err = self.program(answers, "pages", "--space", "ENG", "--limit", "25", "--json")
        self.assertEqual((code, out), (7, ""))
        self.assertIn("more than 250,000 JSON objects", err)
        self.assertEqual(json.loads(err.strip().splitlines()[-1])["error"]["code"], "UNAVAILABLE")

    def test_it_is_quick(self):
        answers = self.serve(b'{"results":[' + b"{}," * 400_000 + b"{}]}", headers=JSON)
        started = time.monotonic()
        code, out, err = self.program(answers, "pages", "--space", "ENG", "--limit", "25")
        self.assertEqual((code, out), (7, ""))
        self.assertLess(time.monotonic() - started, 8)

    def test_objects_that_hide_in_a_list_of_every_result_are_counted_too(self):
        nested = b'{"id":"1","version":{"number":1},"labels":{"results":[' + b"{}," * 300_000 + b"{}]}}"
        answers = self.serve(b'{"results":[' + nested + b"]}", headers=JSON)
        with self.assertRaises(UnavailableError) as caught:
            self.gateway(answers).list_properties("page", "2002")
        self.assertIn("more than 250,000 JSON objects", caught.exception.message)

    def test_so_are_arrays_which_the_decoder_has_no_hook_for(self):
        answers = self.serve(b'{"results":[' + b"[]," * (8 * MAX_OBJECTS) + b"[]]}", headers=JSON)
        with self.assertRaises(UnavailableError) as caught:
            self.gateway(answers).list_properties("page", "2002")
        self.assertIn("more than 250,000 JSON objects", caught.exception.message)

    def test_an_answer_just_under_the_limit_is_read(self):
        body = b'{"results":[{"id":"1","key":"k","value":[' + b"{}," * (MAX_OBJECTS - 10) + b'{}]}]}'
        answers = self.serve(body, headers=JSON)
        found = self.gateway(answers).list_properties("page", "2002")
        self.assertEqual(len(found.items), 1)

    def test_the_message_has_nothing_of_the_answer(self):
        answers = self.serve(b'{"results":[' + b'{"secret":"sign in to the network"},' * 5000 + b"{}]}", headers=JSON)
        with self.assertRaises(UnavailableError) as caught:
            self.gateway(answers).list_properties("page", "2002")
        text = json.dumps([caught.exception.message, caught.exception.hint, caught.exception.details])
        self.assertNotIn("sign in", text)
        self.assertNotIn("secret", text)


if __name__ == "__main__":
    unittest.main()
