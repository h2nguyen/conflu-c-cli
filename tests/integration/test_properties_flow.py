"""The content properties of pages and other content, the real program against the mock Confluence: the requests that are sent, the versions, the guards, privacy, hostile input."""
import json
import unittest

from conflu_c_cli.domain.properties import CUT_MARKER
from tests.integration.test_end_to_end import ACCOUNT, EndToEnd
from tests.support.fakes import FakeGateway
from tests.support.mock_properties import PropertiesRoutes

TYPES = ("POST", "/api/v2/content/convert-ids-to-types")
PEOPLE = (ACCOUNT, "Alex Example", "alex@example.com")

# What holds properties in the mock: the collection of the API, the id, the type that Confluence calls it, and whether the id is asked what it is first.
HOLDERS = (
    ("pages", "2002", "page", True),
    ("blogposts", "7390", "blogpost", True),
    ("folders", "7391", "folder", True),
    ("whiteboards", "7392", "whiteboard", True),
    ("databases", "7393", "database", True),
    ("embeds", "7394", "embed", True),
    ("attachments", "att5001", "attachment", False),  # its id says what it is
    ("comments", "4001", "footer-comment", True),
    ("comments", "4003", "inline-comment", True),
)


class PropertiesFlow(EndToEnd):
    def setUp(self):
        super().setUp()
        self.area = self.mock.area(PropertiesRoutes)

    def calls(self):
        """Every request that was made, as (method, path)."""
        return [(item.method, item.path) for item in self.mock.requests]

    def property_requests(self, method=None):
        return [item for item in self.mock.requests if "/properties" in item.path and (method is None or item.method == method)]

    def writes(self):
        return [item for item in self.mock.requests if item.method in ("POST", "PUT", "DELETE") and item.path != TYPES[1]]

    def nothing_unknown(self):
        self.assertEqual((self.mock.unknown_endpoints, self.mock.deprecated_endpoints), ([], []))

    def keys(self, result):
        return [item["key"] for item in result.json()["properties"]]


class ListTest(PropertiesFlow):
    def test_a_page_is_asked_what_it_is_and_then_for_its_properties_sorted_by_key(self):
        result = self.cli("properties", "2002", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.calls(), [TYPES, ("GET", "/api/v2/pages/2002/properties")])
        self.assertEqual(self.mock.requests[0].body, {"contentIds": ["2002"]})
        self.assertEqual(self.mock.requests[1].query, {"sort": ["key"], "limit": ["25"]})
        self.assertEqual((self.keys(result), result.json()["nextCursor"], result.json()["target"]), (["content-appearance-published", "editor"], "2", {"id": "2002", "type": "page"}))
        self.assertEqual(self.mock.used_endpoints, ["POST /api/v2/content/convert-ids-to-types", "GET /api/v2/pages/{page-id}/properties"])
        self.nothing_unknown()

    def test_every_kind_of_content_has_its_own_collection_and_only_an_attachment_is_known_without_asking(self):
        for collection, holder, kind, asked in HOLDERS:
            self.mock.requests.clear()
            result = self.cli("properties", holder, "--json")
            with self.subTest(holder=holder):
                self.assertEqual(result.code, 0, result.err)
                self.assertEqual(self.calls(), ([TYPES] if asked else []) + [("GET", f"/api/v2/{collection}/{holder}/properties")])
                self.assertEqual(result.json()["target"], {"id": holder, "type": kind})
                self.assertGreaterEqual(result.json()["count"], 1)
        self.nothing_unknown()

    def test_the_number_of_an_attachment_gets_the_prefix_that_the_api_uses(self):
        self.mock.content_kinds["5001"] = "attachment"
        result = self.cli("properties", "5001", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.calls(), [TYPES, ("GET", "/api/v2/attachments/att5001/properties")])

    def test_one_key_is_the_key_parameter_and_is_case_sensitive(self):
        result = self.cli("properties", "2002", "--key", "team.review", "--json")
        self.assertEqual(self.keys(result), ["team.review"])
        self.assertEqual(self.mock.requests[1].query["key"], ["team.review"])
        self.assertEqual(self.keys(self.cli("properties", "2002", "--key", "Team.Review", "--json")), [])

    def test_the_cursor_that_was_given_back_is_the_next_piece_and_all_of_them_are_read_in_pieces_of_a_hundred(self):
        self.assertEqual(self.keys(self.cli("properties", "2002", "--cursor", "2", "--json")), ["team.review"])
        self.mock.requests.clear()
        result = self.cli("properties", "2002", "--all", "--json")
        self.assertEqual(self.keys(result), ["content-appearance-published", "editor", "team.review"])
        requests = self.property_requests()
        self.assertEqual([item.query.get("cursor", [""])[0] for item in requests], ["", "2"])
        self.assertEqual({item.query["limit"][0] for item in requests}, {"100"})
        self.assertEqual((result.json()["nextCursor"], result.json()["truncated"]), (None, False))

    def test_a_long_value_is_cut_and_the_whole_of_it_comes_with_max_chars_zero(self):
        cut = self.cli("properties", "2003", "--json").json()["properties"][0]
        self.assertEqual((cut["truncated"], len(cut["value"]), cut["totalChars"]), (True, 2000 + len(CUT_MARKER), 4411))
        self.assertTrue(cut["value"].endswith(CUT_MARKER))
        whole = self.cli("properties", "2003", "--max-chars", "0", "--json").json()["properties"][0]
        self.assertEqual((whole["truncated"], whole["value"]["items"][399]), (False, "item-399"))

    def test_people_in_a_value_are_hidden_unless_they_are_asked_for(self):
        for argv in (("properties", "2002", "--all"), ("properties", "2002", "--all", "--json"), ("properties", "2002", "--key", "team.review")):
            result = self.cli(*argv)
            with self.subTest(argv=argv):
                for text in PEOPLE:
                    self.assertNotIn(text, result.out + result.err)
        shown = self.cli("properties", "2002", "--key", "team.review", "--with-users", "--json").json()["properties"][0]["value"]
        self.assertEqual((shown["reviewer"], shown["owners"], shown["note"]), ({"accountId": ACCOUNT, "displayName": "Alex Example"}, [ACCOUNT], "Ask alex@example.com"))

    def test_the_policy_that_hides_people_refuses_before_any_request(self):
        strict = {"CONFLUENCE_HIDE_USERS": "true"}
        refused = self.cli("properties", "2002", "--with-users", env=strict)
        self.assertEqual((refused.code, refused.out), (1, ""))
        self.assertEqual(self.mock.requests, [])
        self.assertEqual(self.cli("properties", "2002", "--json", env=strict).code, 0)

    def test_what_the_mock_adds_to_every_text_does_not_get_through(self):
        self.mock.taint = True
        for argv in (("properties", "2002", "--all"), ("properties", "2002", "--all", "--json"), ("properties", "att5001", "--json")):
            result = self.cli(*argv)
            with self.subTest(argv=argv):
                self.assertEqual(result.code, 0, result.err)
                self.assertNotIn("alex@example.com", result.out + result.err)
        self.assertIn("[email]", self.cli("properties", "2002", "--key", "editor").out)  # the text that the mock marked: its marker is gone, a place for it is left

    def test_a_property_that_is_not_where_it_is_asked_for_is_an_empty_list_and_content_that_is_not_there_is_not_found(self):
        self.assertEqual(self.cli("properties", "2005", "--json").json()["count"], 0)
        self.assertEqual(self.cli("properties", "99999").code, 4)
        self.assertEqual(self.cli("properties", "att99999").code, 4)
        self.assertEqual(self.cli("properties", "att99999").out, "")

    def test_what_is_refused_is_refused_before_any_request(self):
        self.mock.requests.clear()
        for argv, code in ((("page",), 1), (("2002/../1",), 1), (("2002", "--max-chars", "-1"), 2), (("2002", "--limit", "0"), 2), (("2002", "--limit", "251"), 2)):
            with self.subTest(argv=argv):
                self.assertEqual(self.cli("properties", *argv).code, code)
        self.assertEqual(self.mock.requests, [])

    def test_content_that_has_no_properties_here_is_refused_and_said_so(self):
        self.mock.content_kinds["8001"] = "custom"
        result = self.cli("properties", "8001")
        self.assertEqual(result.code, 1)
        self.assertIn("custom content", result.err)
        self.assertEqual(self.property_requests(), [])

    def test_a_cursor_cannot_change_the_path_or_the_other_parameters(self):
        result = self.cli("properties", "2002", "--cursor", "../../x?key=a&limit=1#y")
        self.assertEqual(result.code, 6)
        (request,) = self.property_requests()
        self.assertEqual((request.path, request.query["key"] if "key" in request.query else None, request.query["limit"]), ("/api/v2/pages/2002/properties", None, ["25"]))

    def test_a_key_with_characters_that_mean_something_in_an_address_is_sent_as_text(self):
        result = self.cli("properties", "2002", "--key", "a&limit=1#x y/z")
        self.assertEqual(result.code, 0, result.err)
        (request,) = self.property_requests()
        self.assertEqual((request.path, request.query["key"]), ("/api/v2/pages/2002/properties", ["a&limit=1#x y/z"]))

    def test_what_the_server_refuses_is_an_exit_code(self):
        for status, code in ((401, 5), (403, 5), (404, 4), (429, 7), (500, 7), (400, 6)):
            self.mock.fail_next("/api/v2/pages/2002/properties", status, method="GET", body={"errors": [{"status": status, "title": "No", "detail": "Not this time"}]})
            with self.subTest(status=status):
                self.assertEqual(self.cli("properties", "2002", env={"CONFLUENCE_RETRY": "0"}).code, code)


class HostileAnswerTest(PropertiesFlow):
    """What a stranger can store in a property: it comes back in the answer."""

    def answer(self, value, key="hostile"):
        return json.dumps({"results": [{"id": "7399", "key": key, "value": value, "version": {"number": 1}}], "_links": {}}).encode("utf-8")

    def test_a_value_nested_deeper_than_what_is_shown_is_said_so_and_one_that_the_decoder_cannot_read_is_an_error_with_a_reason(self):
        self.area.raw_answers.append(b'{"results":[{"id":"1","key":"deep","value":' + b"[" * 150 + b"]" * 150 + b',"version":{"number":1}}]}')
        shown = self.cli("properties", "2005")
        self.assertEqual(shown.code, 0, shown.err)
        self.assertIn("[nested too deeply to show]", shown.out)
        self.area.raw_answers.append(b'{"results":[{"id":"1","key":"deep","value":' + b"[" * 5000 + b"]" * 5000 + b',"version":{"number":1}}]}')
        refused = self.cli("properties", "2005")
        self.assertEqual((refused.code, refused.out), (7, ""))
        self.assertIn("nests arrays or objects too deeply", refused.err)
        self.assertNotIn("RecursionError", refused.err)

    def test_a_deep_value_that_is_in_the_way_of_a_change_is_replaced_and_not_compared(self):
        self.area.raw_answers.append(b'{"results":[{"id":"7399","key":"deep","value":' + b"[" * 150 + b"]" * 150 + b',"version":{"number":1}}]}')
        result = self.cli("property-set", "2005", "--key", "deep", "--value", '"flat"', "--dry-run", "--json")
        self.assertEqual(result.code, 0, result.err)
        data = result.json()
        self.assertEqual((data["action"], data["current"], data["payload"]["version"]), ("updated", "[nested too deeply to show]", {"number": 2}))

    def test_a_value_that_is_huge_is_cut_to_what_was_asked_for_and_never_longer(self):
        self.area.raw_answers.append(self.answer("x" * 3_000_000))
        result = self.cli("properties", "2005")
        self.assertEqual(result.code, 0, result.err)
        self.assertLess(len(result.out), 5000)
        self.area.raw_answers.append(self.answer("x" * 3_000_000))
        data = self.cli("properties", "2005", "--json").json()["properties"][0]
        self.assertEqual((data["truncated"], len(data["value"]), data["totalChars"]), (True, 2000 + len(CUT_MARKER), 3_000_002))

    def test_controls_and_half_surrogates_in_a_value_or_a_key_cannot_move_the_cursor_or_break_the_output(self):
        value = {"esc": "a\u001b[2Jb", "bel": "c\u0007d", "newline": "e\nf", "bidi": "\u202eg", "half": "h\ud800i", "c1": "j\u009bk"}
        self.area.raw_answers.append(self.answer(value, key="k\u001b[31m\ud800"))
        text = self.cli("properties", "2005")
        self.assertEqual(text.code, 0, text.err)
        self.assertNotIn("\x1b", text.out)
        self.assertNotIn("\x07", text.out)
        self.assertNotIn("\x9b", text.out)
        text.out.encode("utf-8")
        self.assertEqual(len(text.out.splitlines()), 3)  # the title, the header, and one row: a line break in a value is not a new row
        self.area.raw_answers.append(self.answer(value, key="k\u001b[31m\ud800"))
        data = self.cli("properties", "2005", "--json")
        self.assertEqual(data.code, 0, data.err)
        self.assertNotIn("\x1b", data.out)
        data.out.encode("utf-8")

    def test_keys_that_look_alike_once_hidden_are_two_keys(self):
        self.area.raw_answers.append(self.answer({ACCOUNT: 1, "5b10ac8d82e05b22cc7d4ef6": 2, "a@b.example": 3}))
        shown = self.cli("properties", "2005", "--json").json()["properties"][0]["value"]
        self.assertEqual(sorted(shown.values()), [1, 2, 3])

    def test_a_property_without_a_key_or_a_value_is_shown_as_what_it_is(self):
        self.mock.fail_next("/api/v2/pages/2005/properties", 200, method="GET", body={"results": [{"id": "1"}, {"key": "k"}, {}, None, 5, "x"]})
        result = self.cli("properties", "2005", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual([item["key"] for item in result.json()["properties"]], ["", "k", ""])


class SetTest(PropertiesFlow):
    def test_a_new_key_is_a_read_by_key_and_a_post_with_the_key_and_the_value_only(self):
        result = self.cli("property-set", "2002", "--key", "new.key", "--value", '{"a": [1, 2]}', "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.calls(), [TYPES, ("GET", "/api/v2/pages/2002/properties"), ("POST", "/api/v2/pages/2002/properties")])
        self.assertEqual(self.mock.requests[1].query, {"key": ["new.key"], "sort": ["key"], "limit": ["100"]})
        (post,) = self.writes()
        self.assertEqual((post.body, post.raw, post.headers.get("content-type")), ({"key": "new.key", "value": {"a": [1, 2]}}, b'{"key": "new.key", "value": {"a": [1, 2]}}', "application/json"))
        data = result.json()
        self.assertEqual((data["action"], data["propertyId"], data["versionFrom"], data["versionTo"]), ("created", "7313", None, 1))
        self.assertEqual(self.area.store[("pages", "2002")][-1]["value"], {"a": [1, 2]})
        self.assertEqual(self.area.saved, [("pages", "2002", "new.key", 1)])
        self.assertIn("POST /api/v2/pages/{page-id}/properties", self.mock.used_endpoints)
        self.nothing_unknown()

    def test_a_key_that_is_there_is_a_put_of_the_next_version_with_the_message(self):
        result = self.cli("property-set", "2002", "--key", "team.review", "--value", '"closed"', "--message", "Closed it", "--json")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(self.calls(), [TYPES, ("GET", "/api/v2/pages/2002/properties"), ("PUT", "/api/v2/pages/2002/properties/7303")])
        (put,) = self.writes()
        self.assertEqual(put.body, {"key": "team.review", "value": "closed", "version": {"number": 4, "message": "Closed it"}})
        stored = next(item for item in self.area.store[("pages", "2002")] if item["key"] == "team.review")
        self.assertEqual((stored["version"]["number"], stored["version"]["message"], stored["value"]), (4, "Closed it", "closed"))
        data = result.json()
        self.assertEqual((data["action"], data["propertyId"], data["versionFrom"], data["versionTo"]), ("updated", "7303", 3, 4))
        self.assertIn("PUT /api/v2/pages/{page-id}/properties/{property-id}", self.mock.used_endpoints)

    def test_every_kind_of_content_takes_a_property_in_its_own_collection(self):
        for collection, holder, kind, asked in HOLDERS:
            self.mock.requests.clear()
            created = self.cli("property-set", holder, "--key", "kind.test", "--value", '{"n":1}', "--json")
            updated = self.cli("property-set", holder, "--key", "kind.test", "--value", '{"n":2}', "--json")
            with self.subTest(holder=holder):
                self.assertEqual((created.code, updated.code), (0, 0), created.err + updated.err)
                self.assertEqual([call for call in self.calls() if call[0] in ("POST", "PUT") and call != TYPES], [("POST", f"/api/v2/{collection}/{holder}/properties"), ("PUT", f"/api/v2/{collection}/{holder}/properties/{created.json()['propertyId']}")])
                self.assertEqual((created.json()["target"], updated.json()["versionFrom"], updated.json()["versionTo"]), ({"id": holder, "type": kind}, 1, 2))
        self.nothing_unknown()

    def test_the_value_that_is_there_already_sends_nothing(self):
        result = self.cli("property-set", "2002", "--key", "editor", "--value", '"v2"', "--json")
        self.assertEqual((result.json()["action"], result.json()["payload"]), ("unchanged", None))
        self.assertEqual(self.writes(), [])
        object_with_other_order = self.cli("property-set", "2002", "--key", "inventory", "--value", "1", "--json")
        self.assertEqual(object_with_other_order.json()["action"], "created")  # another page's key: 2002 has no `inventory`
        again = self.cli("property-set", "2002", "--key", "team.review", "--value", json.dumps({"note": "Ask alex@example.com", "owners": [ACCOUNT], "status": "open", "reviewer": {"displayName": "Alex Example", "accountId": ACCOUNT}}), "--json")
        self.assertEqual(again.json()["action"], "unchanged")

    def test_a_dry_run_reads_and_sends_nothing_and_shows_what_the_real_run_sends(self):
        for argv in (("--key", "team.review", "--value", '{"a":1}'), ("--key", "brand.new", "--value", "[1]"), ("--key", "editor", "--value", '"v2"')):
            self.mock.requests.clear()
            saved = list(self.area.saved)
            dry = self.cli("property-set", "2002", *argv, "--message", "M", "--dry-run", "--json")
            with self.subTest(argv=argv):
                self.assertEqual(dry.code, 0, dry.err)
                self.assertEqual((self.writes(), self.area.saved), ([], saved))
                self.assertEqual(self.calls(), [TYPES, ("GET", "/api/v2/pages/2002/properties")])
                self.cli("property-set", "2002", *argv, "--message", "M", "--json")
                if dry.json()["payload"] is not None:
                    self.assertEqual(self.writes()[-1].body, dry.json()["payload"])
                else:
                    self.assertEqual(self.writes(), [])  # the value that is there already: nothing is sent, the dry run said so
                self.mock.requests.clear()

    def test_the_guard_refuses_before_anything_is_sent_and_says_the_version_it_found(self):
        result = self.cli("property-set", "2002", "--key", "team.review", "--value", "1", "--if-version", "2", "--json")
        self.assertEqual((result.code, result.out), (3, ""))
        self.assertEqual(self.calls(), [TYPES, ("GET", "/api/v2/pages/2002/properties")])
        self.assertEqual(json.loads(result.err.strip().splitlines()[-1])["error"]["details"], {"id": "2002", "key": "team.review", "version": 3, "expected": 2})
        dry = self.cli("property-set", "2002", "--key", "team.review", "--value", "1", "--if-version", "2", "--dry-run")
        self.assertEqual(dry.code, 3)
        self.assertEqual(self.writes(), [])

    def test_the_guard_that_is_right_lets_the_change_through_and_zero_means_new(self):
        self.assertEqual(self.cli("property-set", "2002", "--key", "team.review", "--value", "1", "--if-version", "3").code, 0)
        self.assertEqual(self.cli("property-set", "2002", "--key", "team.review", "--value", "2", "--if-version", "3").code, 3)  # it is at version 4 now
        self.assertEqual(self.cli("property-set", "2002", "--key", "brand.new", "--value", "1", "--if-version", "0").code, 0)
        self.assertEqual(self.cli("property-set", "2002", "--key", "brand.new", "--value", "2", "--if-version", "0").code, 3)  # it exists now

    def test_a_save_that_lost_against_somebody_else_is_exit_code_3_from_the_mock_and_from_the_server_alike(self):
        original = self.area._list  # noqa: SLF001

        def somebody_saves_meanwhile(handler, collection, holder_id, items, query, query_pairs):
            original(handler, collection, holder_id, items, query, query_pairs)
            for item in items:
                item["version"]["number"] += 1

        self.area._list = somebody_saves_meanwhile  # noqa: SLF001
        result = self.cli("property-set", "2002", "--key", "team.review", "--value", '"mine"')
        self.assertEqual((result.code, result.out), (3, ""))
        self.assertIn("HTTP 409", result.err)
        self.assertIn("conflu properties 2002 --key team.review", result.err)
        self.assertNotIn("The page changed", result.err)
        stored = next(item for item in self.area.store[("pages", "2002")] if item["key"] == "team.review")
        self.assertEqual(stored["value"]["status"], "open")  # the other person's save was not overwritten
        self.area._list = original  # noqa: SLF001
        self.mock.fail_next("/api/v2/pages/2002/properties/7301", 409, method="PUT", body={"errors": [{"status": 409, "title": "Conflict", "detail": "Version conflict"}]})
        self.assertEqual(self.cli("property-set", "2002", "--key", "editor", "--value", '"v3"').code, 3)

    def test_a_refusal_of_the_save_is_an_exit_code_and_leaves_the_property_as_it_was(self):
        for status, code in ((403, 5), (404, 4), (400, 6), (500, 7)):
            self.mock.fail_next("/api/v2/pages/2002/properties/7301", status, method="PUT", body={"errors": [{"status": status, "title": "No", "detail": "Not this time"}]})
            with self.subTest(status=status):
                self.assertEqual(self.cli("property-set", "2002", "--key", "editor", "--value", '"v3"').code, code)
        self.assertEqual(self.cli("property-set", "2002", "--key", "created.in.between", "--value", "1", "--dry-run").code, 0)
        self.mock.fail_next("/api/v2/pages/2002/properties", 400, method="POST", body={"errors": [{"status": 400, "title": "Bad", "detail": "A property with the key x exists already"}]})
        self.assertEqual(self.cli("property-set", "2002", "--key", "x", "--value", "1").code, 6)
        self.assertEqual(self.area.saved, [])

    def test_the_value_may_come_from_a_file_or_from_standard_input(self):
        path = self.root / "value.json"
        path.write_text('{"from": "a file", "list": [1, 2]}\n', encoding="utf-8")
        self.assertEqual(self.cli("property-set", "2002", "--key", "from.file", "--file", str(path)).code, 0)
        self.assertEqual(self.cli("property-set", "2002", "--key", "from.pipe", "--file", "-", stdin='[1, "two", null]').code, 0)
        values = {item["key"]: item["value"] for item in self.area.store[("pages", "2002")]}
        self.assertEqual((values["from.file"], values["from.pipe"]), ({"from": "a file", "list": [1, 2]}, [1, "two", None]))

    def test_a_file_that_windows_powershell_wrote_is_read(self):
        path = self.root / "value.json"
        path.write_bytes('{"text": "caf\u00e9 \u4e2d"}'.encode("utf-16"))
        self.assertEqual(self.cli("property-set", "2002", "--key", "from.ps", "--file", str(path)).code, 0)
        self.assertEqual(next(item for item in self.area.store[("pages", "2002")] if item["key"] == "from.ps")["value"], {"text": "caf\u00e9 \u4e2d"})

    def test_a_value_that_is_refused_is_refused_before_any_request(self):
        big = self.root / "big.json"
        big.write_text("[" + "1," * 600_000 + "1]", encoding="utf-8")
        cases = (
            (("--value", "open"), 2), (("--value", '{"a":}'), 2), (("--value", ""), 2), (("--value", '"' + "x" * 40_000 + '"'), 1), (("--value", "[" * 500 + "]" * 500), 1),
            (("--value", "[" * 50_000 + "]" * 50_000), 1), (("--value", '"\\ud800"'), 1), (("--value", "1", "--file", "-"), 2), ((), 2), (("--file", str(big)), 1),
            (("--file", str(self.root / "missing.json")), 1), (("--value", "1e999"), 2), (("--value=-1e999",), 2), (("--value", '{"a":[1,[2,{"b":1e400}]]}'), 2),
            (("--value", "NaN"), 2), (("--value", "Infinity"), 2),
        )
        for argv, code in cases:
            with self.subTest(argv=[text[:30] for text in argv]):
                self.assertEqual(self.cli("property-set", "2002", "--key", "x", *argv).code, code)
        self.assertEqual(self.mock.requests, [])

    def test_a_key_that_is_refused_is_refused_before_any_request(self):
        for key in ("bad key", "a/b", "x" * 256, "a\nb", "\u00e9", "", "../x", "a?b"):
            with self.subTest(key=key[:20]):
                self.assertEqual(self.cli("property-set", "2002", "--key", key, "--value", "1").code, 2)
        self.assertEqual(self.mock.requests, [])

    def test_content_that_is_not_there_is_not_found_and_nothing_is_written(self):
        self.assertEqual(self.cli("property-set", "99999", "--key", "x", "--value", "1").code, 4)
        self.assertEqual(self.cli("property-set", "att99999", "--key", "x", "--value", "1").code, 4)
        self.assertEqual([item for item in self.writes() if item.method != "GET"], [])

    def test_no_request_of_any_command_deletes_anything(self):
        for argv in (
            ("property-set", "2002", "--key", "a", "--value", "1"), ("property-set", "2002", "--key", "a", "--value", "2"), ("property-set", "7391", "--key", "a", "--value", "null"),
            ("properties", "2002", "--all"), ("properties", "att5001"),
        ):
            self.cli(*argv)
        self.assertEqual({item.method for item in self.mock.requests} - {"GET", "POST", "PUT"}, set())

    def test_the_people_in_the_old_value_are_not_shown_in_a_dry_run_or_a_change(self):
        self.mock.taint = True
        for extra in (("--dry-run",), (), ("--dry-run", "--json"), ("--json",)):
            result = self.cli("property-set", "2002", "--key", "team.review", "--value", '"closed"', *extra)
            with self.subTest(extra=extra):
                self.assertEqual(result.code, 0, result.err)
                for text in PEOPLE:
                    self.assertNotIn(text, result.out + result.err)

    def test_an_error_does_not_name_a_person_either(self):
        self.mock.taint = True
        for argv in (("property-set", "99999", "--key", "x", "--value", "1"), ("properties", "99999"), ("property-set", "2002", "--key", "team.review", "--value", "1", "--if-version", "1")):
            result = self.cli(*argv)
            with self.subTest(argv=argv):
                self.assertNotEqual(result.code, 0)
                for text in PEOPLE:
                    self.assertNotIn(text, result.err)

    def test_what_a_reading_shows_without_the_people_cannot_be_written_back_over_them(self):
        shown = self.cli("properties", "2002", "--key", "team.review", "--json").json()["properties"][0]["value"]
        self.mock.requests.clear()
        saved = list(self.area.saved)
        for extra in ((), ("--dry-run",), ("--if-version", "3")):
            result = self.cli("property-set", "2002", "--key", "team.review", "--file", "-", *extra, stdin=json.dumps(shown))
            with self.subTest(extra=extra):
                self.assertEqual((result.code, result.out), (1, ""))
                self.assertIn('`{"hidden": true}`', result.err)
        self.assertEqual((self.writes(), self.area.saved), ([], saved))
        stored = next(item for item in self.area.store[("pages", "2002")] if item["key"] == "team.review")
        self.assertEqual((stored["version"]["number"], stored["value"]["reviewer"]["accountId"]), (3, ACCOUNT))
        real = self.cli("properties", "2002", "--key", "team.review", "--with-users", "--json").json()["properties"][0]["value"]
        changed = self.cli("property-set", "2002", "--key", "team.review", "--file", "-", "--if-version", "3", "--json", stdin=json.dumps({**real, "status": "closed"}))
        self.assertEqual(changed.code, 0, changed.err)
        stored = next(item for item in self.area.store[("pages", "2002")] if item["key"] == "team.review")
        self.assertEqual((stored["version"]["number"], stored["value"]["status"], stored["value"]["reviewer"]["accountId"], stored["value"]["owners"]), (4, "closed", ACCOUNT, [ACCOUNT]))

    def test_a_value_that_a_reading_cut_cannot_be_written_back_and_the_whole_one_can(self):
        # the recipe that the refusal of a stand-in used to print read a value cut at 2000 characters, and `property-set` wrote that text over the property
        cut = self.cli("properties", "2003", "--key", "inventory", "--with-users", "--json").json()["properties"][0]
        self.assertEqual((cut["truncated"], cut["totalChars"]), (True, 4411))
        self.mock.requests.clear()
        for extra in ((), ("--dry-run",), ("--if-version", "1"), ("--json",)):
            result = self.cli("property-set", "2003", "--key", "inventory", "--file", "-", *extra, stdin=json.dumps(cut["value"]))
            with self.subTest(extra=extra):
                self.assertEqual((result.code, result.out), (1, ""))
                self.assertIn(f"`{CUT_MARKER}`", result.err)
                self.assertIn("--max-chars 0", result.err)
        self.assertEqual(self.writes(), [])
        stored = next(item for item in self.area.store[("pages", "2003")] if item["key"] == "inventory")
        self.assertEqual((stored["version"]["number"], len(stored["value"]["items"])), (1, 400))
        whole = self.cli("properties", "2003", "--key", "inventory", "--with-users", "--max-chars", "0", "--json").json()["properties"][0]
        self.assertEqual((whole["truncated"], len(whole["value"]["items"])), (False, 400))
        edited = {"items": [*whole["value"]["items"], "item-new"]}
        done = self.cli("property-set", "2003", "--key", "inventory", "--file", "-", "--if-version", "1", "--json", stdin=json.dumps(edited))
        self.assertEqual(done.code, 0, done.err)
        stored = next(item for item in self.area.store[("pages", "2003")] if item["key"] == "inventory")
        self.assertEqual((stored["version"]["number"], len(stored["value"]["items"]), stored["value"]["items"][-1]), (2, 401, "item-new"))

    def test_a_cut_value_is_not_stored_as_a_new_property_either(self):
        cut = self.cli("properties", "2003", "--key", "inventory", "--json").json()["properties"][0]["value"]
        self.mock.requests.clear()
        result = self.cli("property-set", "2005", "--key", "inventory.copy", "--file", "-", stdin=json.dumps(cut))
        self.assertEqual((result.code, result.out), (1, ""))
        self.assertIn("store the beginning of a value as the value of a new property", result.err)
        self.assertEqual((self.writes(), self.area.store.get(("pages", "2005"), [])), ([], []))

    def test_what_a_reading_shows_of_a_mention_in_any_attribute_cannot_be_written_back_over_the_account_id(self):
        for number, attribute in enumerate(("data-account-id", "data-userkey", "data-username", "ri:account-id", "ri:userkey", "ri:username")):
            key = f"snippet.{number}"
            real = {"html": f'<a {attribute}="{ACCOUNT}">@Alex</a> reviewed', "n": 1}
            self.area.add_property("pages", "2005", key, real)
            shown = self.cli("properties", "2005", "--key", key, "--json").json()["properties"][0]["value"]
            self.mock.requests.clear()
            result = self.cli("property-set", "2005", "--key", key, "--file", "-", stdin=json.dumps({**shown, "n": 2}))
            with self.subTest(attribute=attribute):
                self.assertEqual(shown["html"], f'<a {attribute}="hidden">@Alex</a> reviewed')
                self.assertEqual((result.code, result.out), (1, ""))
                self.assertIn(f'`{attribute}="hidden"`', result.err)
                self.assertEqual(self.writes(), [])
                stored = next(item for item in self.area.store[("pages", "2005")] if item["key"] == key)
                self.assertEqual((stored["value"], stored["version"]["number"]), (real, 1))
                for text in PEOPLE:
                    self.assertNotIn(text, result.err)
                read = self.cli("properties", "2005", "--key", key, "--with-users", "--max-chars", "0", "--json").json()["properties"][0]["value"]
                self.assertEqual(read, real)
                done = self.cli("property-set", "2005", "--key", key, "--file", "-", stdin=json.dumps({**read, "n": 2}))
                self.assertEqual(done.code, 0, done.err)
                self.assertEqual(next(item for item in self.area.store[("pages", "2005")] if item["key"] == key)["value"], {**real, "n": 2})

    def test_an_address_that_a_reading_showed_without_its_title_cannot_be_written_back(self):
        url = "https://example.atlassian.net/wiki/spaces/ENG/pages/124/Contact+alex%40example.com"
        self.area.add_property("pages", "2005", "link", {"url": url, "n": 1})
        shown = self.cli("properties", "2005", "--key", "link", "--json").json()["properties"][0]["value"]
        self.assertEqual(shown["url"], "https://example.atlassian.net/wiki/spaces/ENG/pages/124")
        self.mock.requests.clear()
        result = self.cli("property-set", "2005", "--key", "link", "--file", "-", stdin=json.dumps({**shown, "n": 2}))
        self.assertEqual((result.code, result.out), (1, ""))
        self.assertIn("`https://example.atlassian.net/wiki/spaces/ENG/pages/124`", result.err)
        self.assertNotIn("alex", result.err)
        self.assertEqual(self.writes(), [])
        real = self.cli("properties", "2005", "--key", "link", "--with-users", "--json").json()["properties"][0]["value"]
        self.assertEqual(real["url"], url)
        done = self.cli("property-set", "2005", "--key", "link", "--file", "-", stdin=json.dumps({**real, "n": 2}))
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(next(item for item in self.area.store[("pages", "2005")] if item["key"] == "link")["value"], {"url": url, "n": 2})

    def test_a_stand_in_that_the_property_holds_itself_does_not_let_the_account_id_next_to_it_be_overwritten(self):
        real = {"a": "[hidden]", "b": ACCOUNT}  # an app wrote the text `[hidden]`, and the account id of a person stands next to it
        self.area.add_property("pages", "2005", "swap", real)
        shown = self.cli("properties", "2005", "--key", "swap", "--json").json()["properties"][0]["value"]
        self.assertEqual(shown, {"a": "[hidden]", "b": "[hidden]"})
        self.mock.requests.clear()
        result = self.cli("property-set", "2005", "--key", "swap", "--file", "-", stdin=json.dumps({"a": "changed", "b": shown["b"]}))
        self.assertEqual((result.code, result.out), (1, ""))
        self.assertIn("`[hidden]`", result.err)
        self.assertEqual(self.writes(), [])
        self.assertEqual(next(item for item in self.area.store[("pages", "2005")] if item["key"] == "swap")["value"], real)
        done = self.cli("property-set", "2005", "--key", "swap", "--file", "-", stdin=json.dumps({"a": "changed", "b": ACCOUNT}))
        self.assertEqual(done.code, 0, done.err)

    def test_a_number_that_is_too_large_is_never_sent_and_never_printed_as_infinity(self):
        for argv, stdin in ((("--value", "1e999"), ""), (("--value", "[1,2,-1e999]", "--dry-run", "--json"), ""), (("--file", "-"), '{"a": 1e400}')):
            result = self.cli("property-set", "2005", "--key", "big.num", *argv, stdin=stdin)
            with self.subTest(argv=argv):
                self.assertEqual((result.code, result.out), (2, ""))
                self.assertNotIn("Infinity", result.out + result.err)
        self.assertEqual(self.mock.requests, [])
        largest = self.cli("property-set", "2005", "--key", "big.num", "--value", "[1.7976931348623157e308, 1e-999]", "--json")
        self.assertEqual(largest.code, 0, largest.err)
        self.assertEqual(self.mock.requests[-1].body, {"key": "big.num", "value": [1.7976931348623157e308, 0.0]})

    def test_the_whole_story_of_a_property_from_its_creation_to_a_guarded_change(self):
        self.assertEqual(self.cli("property-set", "2005", "--key", "story", "--value", '{"step": 1}', "--if-version", "0").code, 0)
        self.assertEqual(self.cli("property-set", "2005", "--key", "story", "--value", '{"step": 2}', "--if-version", "1", "--message", "Second").code, 0)
        shown = self.cli("properties", "2005", "--key", "story", "--json").json()["properties"][0]
        self.assertEqual((shown["version"], shown["value"]), (2, {"step": 2}))
        self.assertEqual(self.cli("property-set", "2005", "--key", "story", "--value", '{"step": 3}', "--if-version", "1").code, 3)
        self.assertEqual(self.area.saved, [("pages", "2005", "story", 1), ("pages", "2005", "story", 2)])


class FixturesTest(unittest.TestCase):
    """The fake and the mock hold the same properties, so that what a test shows against one holds against the other."""

    def test_the_mock_and_the_fake_agree(self):
        from tests.support.mock_confluence import MockConfluence

        mock = MockConfluence()
        try:
            area = mock.area(PropertiesRoutes)
            fake = FakeGateway()
            self.assertEqual(sorted(area.store), sorted(fake.property_store))
            for holder, items in fake.property_store.items():
                shown = {item["key"]: item for item in area.store[holder]}
                self.assertEqual(sorted(shown), sorted(item.key for item in items))
                for item in items:
                    with self.subTest(holder=holder, key=item.key):
                        self.assertEqual((shown[item.key]["id"], shown[item.key]["version"]["number"], shown[item.key]["value"], shown[item.key]["version"]["createdAt"]), (item.id, item.version, item.value, item.updated))
            for holder_id, kind in fake.content_kinds.items():
                if holder_id in ("7390", "7391", "7392", "7393", "7394"):
                    self.assertEqual(mock.content_kinds[holder_id], kind)
        finally:
            mock.stop()


if __name__ == "__main__":
    unittest.main()
