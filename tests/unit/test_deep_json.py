"""The helper for the tests of deeply nested JSON: what it makes the decoder do, and what it says of the decoder of this Python."""
from __future__ import annotations

import json
import unittest
from unittest import mock

from tests.support import deep_json


class GivingUpTest(unittest.TestCase):
    def test_a_text_that_nests_as_deep_as_the_levels_or_deeper_is_refused_as_the_decoder_refuses_it(self):
        for text in ("[" * deep_json.LEVELS + "]" * deep_json.LEVELS, '{"a":' * (deep_json.LEVELS + 1) + "1" + "}" * (deep_json.LEVELS + 1), "[" * 60000):
            with self.subTest(size=len(text)), deep_json.giving_up():
                with self.assertRaises(RecursionError):
                    json.loads(text)
                with self.assertRaises(RecursionError):
                    json.loads(text.encode("utf-8"))  # the body of an answer, as it comes

    def test_every_other_text_is_decoded_as_it_is_with_the_options_it_is_given(self):
        shallow = "[" * (deep_json.LEVELS - 1) + "]" * (deep_json.LEVELS - 1)
        with deep_json.giving_up():
            self.assertEqual(json.loads('{"cloudId": "abc", "x": [1, 2]}'), {"cloudId": "abc", "x": [1, 2]})
            self.assertEqual(json.loads(shallow.encode()), json.loads(shallow))
            self.assertEqual(json.loads('{"a": 1}', object_hook=lambda value: sorted(value)), ["a"])
            with self.assertRaises(ValueError):
                json.loads("not json")

    def test_the_patch_ends_with_the_block(self):
        before = json.loads
        with deep_json.giving_up():
            self.assertIsNot(json.loads, before)
        self.assertIs(json.loads, before)


class TheDecoderOfThisPythonTest(unittest.TestCase):
    def test_a_decoder_that_raises_recursion_error_gives_up(self):
        with mock.patch.object(deep_json, "_REAL_LOADS", side_effect=RecursionError):
            self.assertTrue(deep_json.decoder_gives_up_on(b"[[["))

    def test_a_decoder_that_reads_the_body_or_refuses_it_as_no_json_does_not(self):
        with mock.patch.object(deep_json, "_REAL_LOADS", return_value=[]):
            self.assertFalse(deep_json.decoder_gives_up_on(b"[]"))
        with mock.patch.object(deep_json, "_REAL_LOADS", side_effect=ValueError("Expecting value")):
            self.assertFalse(deep_json.decoder_gives_up_on(b"[[["))

    def test_the_question_is_asked_of_the_real_decoder_also_while_it_is_made_to_give_up(self):
        with deep_json.giving_up():
            self.assertFalse(deep_json.decoder_gives_up_on(b'{"a": [1]}'))


if __name__ == "__main__":
    unittest.main()
