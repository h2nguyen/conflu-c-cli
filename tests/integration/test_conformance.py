"""What the CLI sends is what the two Confluence Cloud REST API documents list.

`tests/support/confluence_cloud_v2_endpoints.txt` and `confluence_cloud_v1_endpoints.txt` hold the operations of the two OpenAPI documents
(read on 2026-10-30). The mock Confluence answers HTTP 404 to a call that the matching document does not list and records it. This module
checks the lists themselves, the refusal, and then sweeps every command (`tests/support/sweeps_all.py`): no command may make a call that
is undocumented or deprecated, v2 is the default, every call to v1 has a reason of its own (`V1_CALLS` of the driven adapters), and
`docs/reference/compatibility.md` names the calls of every command. The sweep also runs with the mock's `strict_parameters` on, which answers
HTTP 400 to a request whose query parameters, headers or body the matching parameter file (`confluence_cloud_v2_parameters.txt`,
`confluence_cloud_v1_parameters.txt`) does not allow: no command line may cause one. The source of the REST adapters is read as well
(`names_in_source`): every query parameter that an adapter can put into a request is a name of the documents, and some line of the sweep sends it. In the same way every
option of every command is named by some line of a sweep module, or has its reason in `NOT_SWEPT` (`options_without_a_line`).
"""
import importlib
import pkgutil
import re
import types
import unittest
from pathlib import Path

from conflu_c_cli.adapters import driven
from conflu_c_cli.adapters.driving.cli.registry import all_commands
from tests.integration.test_end_to_end import EndToEnd
from tests.support.conformance import (
    ACCEPTED_BUT_UNDOCUMENTED,
    NEVER_SENT_IN_A_SWEEP,
    NOT_SWEPT,
    OUTSIDE_THE_REFERENCE,
    V1_LIST,
    V2_LIST,
    classify,
    documented_calls,
    is_documented,
    names_in_source,
    options_without_a_line,
    parameter_rules,
    query_names,
    template_of,
    version_of,
)
from tests.support.json_sweep import MODULES
from tests.support.sweep_runner import SweepResult, run_sweep, run_sweeps, table_rows
from tests.support.sweeps import LOCAL, line
from tests.support.sweeps_all import SWEEPS

ROOT = Path(__file__).resolve().parents[2]
COMPATIBILITY = ROOT / "docs" / "reference" / "compatibility.md"
OUTSIDE_ALLOWED = {"setup": {"GET /_edge/tenant_info"}}  # the commands that may make a call that is no REST call, and which


def v1_calls() -> dict[str, str]:
    """Every call to the v1 API that a driven adapter makes, with why v2 does not do: the `V1_CALLS` of its modules."""
    found: dict[str, str] = {}
    for info in pkgutil.iter_modules(driven.__path__):
        module = importlib.import_module(f"{driven.__name__}.{info.name}")
        found.update(getattr(module, "V1_CALLS", {}))
    return found


def named_by_the_adapters() -> dict[str, list[str]]:
    """Every query parameter that `confluence_rest.py` and the `rest_*.py` modules put into a request, with the places: `{"space-id": ["rest_tasks.py:35"]}`."""
    folder = Path(driven.__path__[0])
    found: dict[str, list[str]] = {}
    for path in sorted([folder / "confluence_rest.py", *folder.glob("rest_*.py")]):
        for name, lines in names_in_source(path.read_text(encoding="utf-8")).items():
            found.setdefault(name, []).extend(f"{path.name}:{line}" for line in lines)
    return dict(sorted(found.items()))


def sweep_lines() -> list[tuple[str, ...]]:
    """The arguments of every line of every sweep module: those of the areas, and the lines of the commands that ask Confluence nothing and of the output modes
    (`sweep_local.py` and `sweep_modes.py`, which the JSON sweep runs)."""
    return [item.argv for module in MODULES for item in module.LINES]


class DocumentedEndpointsTest(unittest.TestCase):
    def test_the_lists_say_where_they_come_from_and_how_many_operations_they_hold(self):
        for path, version, url, count in (
            (V2_LIST, "v2", "https://dac-static.atlassian.com/cloud/confluence/openapi-v2.v3.json", 252),
            (V1_LIST, "v1", "https://dac-static.atlassian.com/cloud/confluence/swagger.v3.json", 130),
        ):
            with self.subTest(version=version):
                text = path.read_text(encoding="utf-8")
                header = "\n".join(line for line in text.splitlines() if line.startswith("#"))
                self.assertIn(url, header)
                self.assertIn("2026-10-30", header)
                self.assertIn(f"{count} operations", header)
                self.assertEqual(len(documented_calls(version)), count)

    def test_what_the_documents_mark_as_deprecated(self):
        deprecated = {
            "v2": {"GET /api/v2/pages/{id}/children"},
            "v1": {"GET /rest/api/content/{id}/descendant", "GET /rest/api/content/{id}/descendant/{type}"},
        }
        for version, expected in deprecated.items():
            with self.subTest(version=version):
                self.assertEqual({f"{method} {template}" for method, template, flagged in documented_calls(version) if flagged}, expected)

    def test_every_entry_is_a_method_and_a_path_of_its_api(self):
        for version, prefix in (("v2", "/api/v2/"), ("v1", "/rest/")):
            seen = set()
            for method, template, _ in documented_calls(version):
                with self.subTest(call=f"{method} {template}"):
                    self.assertIn(method, {"GET", "POST", "PUT", "DELETE", "PATCH"})
                    self.assertTrue(template.startswith(prefix))
                    self.assertNotIn((method, template), seen)
                    seen.add((method, template))

    def test_calls_that_the_documents_list(self):
        for method, path in (
            ("GET", "/api/v2/pages/123"),
            ("PUT", "/api/v2/pages/123/title"),
            ("POST", "/api/v2/folders"),
            ("GET", "/api/v2/folders/77/direct-children"),
            ("POST", "/api/v2/footer-comments"),
            ("GET", "/api/v2/footer-comments/456/children"),
            ("POST", "/api/v2/content/convert-ids-to-types"),
            ("GET", "/api/v2/attachments/att1/versions/2"),
            ("GET", "/rest/api/search"),
            ("GET", "/rest/api/user/current"),
            ("PUT", "/rest/api/content/123/move/append/456"),
            ("PUT", "/rest/api/content/123/child/attachment"),
            ("DELETE", "/rest/api/content/123/label/draft"),
        ):
            with self.subTest(call=f"{method} {path}"):
                self.assertTrue(is_documented(method, path))

    def test_calls_that_they_do_not_list(self):
        for method, path in (
            ("GET", "/api/v2/pages/123/unknown"),
            ("POST", "/api/v2/spaces/1/pages"),  # the method is not offered there
            ("GET", "/rest/api/content/123"),  # the v1 document has no read of content: v2 has it
            ("GET", "/rest/api/content/123/child/attachment"),
            ("GET", "/api/v3/pages/123"),
            ("GET", "/wiki/api/v2/pages/123"),  # the address is below the wiki address already
            ("GET", "/pages/123"),
        ):
            with self.subTest(call=f"{method} {path}"):
                self.assertFalse(is_documented(method, path))
        self.assertFalse(is_documented("GET", "/api/v2/pages/"))  # a trailing slash makes it another path
        self.assertTrue(is_documented("GET", "/api/v2/pages"))

    def test_a_deprecated_call_is_documented_and_flagged(self):
        call = classify("GET", "/api/v2/pages/123/children")
        self.assertEqual((call.documented, call.deprecated, call.version), (True, True, "v2"))
        self.assertFalse(classify("GET", "/api/v2/pages/123/direct-children").deprecated)

    def test_what_is_no_rest_call(self):
        for method, template in OUTSIDE_THE_REFERENCE:
            path = template.replace("{pageId}", "1").replace("{name}", "x.png")
            with self.subTest(call=f"{method} {path}"):
                call = classify(method, path)
                self.assertEqual((call.outside, call.documented, call.version), (True, False, ""))
        self.assertFalse(classify("POST", "/_edge/tenant_info").outside)
        self.assertFalse(classify("GET", "/_edge/other").outside)

    def test_the_template_and_the_version_of_a_call(self):
        self.assertEqual(template_of("GET", "/api/v2/footer-comments/12"), "/api/v2/footer-comments/{comment-id}")
        self.assertEqual(template_of("PUT", "/rest/api/content/5/move/before/6"), "/rest/api/content/{pageId}/move/{position}/{targetId}")
        self.assertIsNone(template_of("GET", "/api/v2/nothing"))
        self.assertEqual([version_of(path) for path in ("/api/v2/pages", "/rest/api/search", "/download/x")], ["v2", "v1", ""])


class V1CallsTest(unittest.TestCase):
    """v2 is the API to use. A call to v1 stands in `V1_CALLS` of its adapter with the reason why v2 does not do."""

    def test_every_v1_call_is_in_the_v1_document_and_not_deprecated(self):
        listed = {f"{method} {template}": flagged for method, template, flagged in documented_calls("v1")}
        for call, reason in v1_calls().items():
            with self.subTest(call=call):
                self.assertIn(call, listed)
                self.assertFalse(listed[call], "the document marks it as deprecated")
                self.assertGreater(len(reason), 20)
                self.assertTrue(reason.endswith("."))

    def test_the_reason_is_about_what_v2_lacks(self):
        for call, reason in v1_calls().items():
            with self.subTest(call=call):
                self.assertIn("v2", reason)
                self.assertTrue(call.split(" ", 1)[1].startswith("/rest/"))


class TheMockRefusesWhatTheDocumentsDoNotKnow(EndToEnd):
    def test_an_undocumented_v2_call_is_a_404_and_is_listed(self):
        result = self.cli("api", "GET", "api/v2/pages/2002/nothing")
        self.assertEqual(result.code, 4)
        self.assertIn("is not in the Confluence Cloud REST API v2 document", result.err)
        self.assertEqual(self.mock.unknown_endpoints, ["GET /api/v2/pages/2002/nothing (v2 document)"])

    def test_the_v1_document_has_no_read_of_content(self):
        result = self.cli("api", "GET", "rest/api/content/2002")
        self.assertEqual(result.code, 4)
        self.assertIn("is not in the Confluence Cloud REST API v1 document", result.err)
        self.assertEqual(self.mock.unknown_endpoints, ["GET /rest/api/content/2002 (v1 document)"])

    def test_a_documented_call_is_answered_as_usual(self):
        self.assertEqual(self.cli("api", "GET", "api/v2/pages/2002").code, 0)
        self.assertEqual(self.mock.unknown_endpoints, [])
        self.assertEqual(self.mock.used_endpoints, ["GET /api/v2/pages/{id}"])

    def test_a_deprecated_call_is_answered_and_listed(self):
        self.cli("api", "GET", "api/v2/pages/2002/children")
        self.assertEqual(self.mock.deprecated_endpoints, ["GET /api/v2/pages/2002/children (v2 document)"])
        self.assertEqual(self.mock.unknown_endpoints, [])

    def test_the_public_tenant_information_needs_no_credentials(self):
        import urllib.request

        root = self.mock.base_url.removesuffix(self.mock.context_path)
        direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # a proxy of the machine must not get a request meant for the mock
        with direct.open(f"{root}/_edge/tenant_info", timeout=10) as answer:
            self.assertIn(self.mock.cloud_id, answer.read().decode("utf-8"))
        self.assertEqual(self.mock.outside_calls, ["GET /_edge/tenant_info"])
        self.assertEqual(self.mock.unknown_endpoints, [])

    def test_the_refusal_can_be_switched_off_for_a_test_of_the_mock_itself(self):
        self.mock.strict = False
        self.cli("api", "GET", "api/v2/pages/2002/nothing")
        self.assertEqual(self.mock.unknown_endpoints, [])

    def test_what_the_parameter_files_do_not_allow_is_refused_only_when_a_test_asks_for_it(self):
        extra = '{"status":"current","title":"Coloured","colour":"red"}'  # a property that the document does not list
        self.assertFalse(self.mock.strict_parameters)
        self.assertEqual(self.cli("api", "PUT", "api/v2/pages/2002/title", "--data", extra, "--write").code, 0)
        self.assertEqual(self.mock.invalid_requests, [])
        self.mock.strict_parameters = True
        refused = self.cli("api", "PUT", "api/v2/pages/2002/title", "--data", extra.replace("Coloured", "Again"), "--write")
        self.assertEqual(refused.code, 6)
        self.assertIn("the request body has the property colour", refused.err)
        self.assertEqual(len(self.mock.invalid_requests), 1)


class TheSweepNamesTheCommandLineThatSentWhatTheDocumentsDoNotAllow(unittest.TestCase):
    def test_a_request_that_the_mock_refused_is_named_with_the_line_that_sent_it(self):
        module = types.ModuleType("sweep_example")
        module.LINES = (
            line("api", "GET", "api/v2/pages/2002", "--param", "body-format=storage"),
            line("api", "GET", "api/v2/pages/2002", "--param", "bogus=1", code=6),
            line("api", "GET", "api/v2/spaces", "--param", "limit=251", code=6),
        )
        result = SweepResult()
        run_sweep(module, result)
        self.assertEqual(result.failures, [])
        self.assertEqual(len(result.invalid_requests), 2)
        self.assertTrue(result.invalid_requests[0].startswith(
            "sweep_example: conflu api GET api/v2/pages/2002 --param bogus=1: GET /api/v2/pages/2002 (v2 document): the query parameter bogus is not one of the operation's"
        ), result.invalid_requests[0])
        self.assertTrue(result.invalid_requests[1].startswith(
            "sweep_example: conflu api GET api/v2/spaces --param limit=251: GET /api/v2/spaces (v2 document): limit 251 is above the documented maximum of 250"
        ), result.invalid_requests[1])
        self.assertEqual(result.deprecated_parameters, [])

    def test_a_query_parameter_that_the_document_marks_as_deprecated_is_named_with_the_line_that_sent_it(self):
        module = types.ModuleType("sweep_example")
        module.LINES = (line("api", "GET", "rest/api/user/watch/space/ENG", "--param", "accountId=5b10ac8d82e05b22cc7d4ef5"), line("api", "GET", "rest/api/user/watch/space/ENG", "--param", "username=alex"))
        result = SweepResult()
        run_sweep(module, result)
        self.assertEqual((result.failures, result.invalid_requests), ([], []))
        self.assertEqual(result.deprecated_parameters, [
            "sweep_example: conflu api GET rest/api/user/watch/space/ENG --param username=alex: GET /rest/api/user/watch/space/ENG (v1 document): the query parameter username is deprecated"
        ])

    def test_the_names_that_the_lines_sent_to_documented_calls_are_collected(self):
        module = types.ModuleType("sweep_example")
        module.LINES = (
            line("api", "GET", "api/v2/pages", "--param", "limit=5", "--param", "body-format=storage"),
            line("api", "GET", "api/v2/nothing", "--param", "never=1", code=4),
        )
        result = SweepResult()
        run_sweep(module, result)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.seen_query_names, {"limit", "body-format"})

    def test_the_file_that_a_line_with_out_wrote_is_part_of_what_it_printed(self):
        module = types.ModuleType("sweep_example")
        module.LINES = (line("page", "2002", "--body-only", "--out", "{work}/page.md"), line("page", "2002", "--outline"))
        result = SweepResult()
        run_sweep(module, result)
        self.assertEqual(result.failures, [])
        self.assertIn("# Release notes", result.outputs[0].written)  # the privacy sweep reads it as it reads what `export` writes
        self.assertEqual(result.outputs[1].written, "")


class WhatIsAcceptedAlthoughUndocumentedTest(unittest.TestCase):
    """The one table of exceptions says why each is there, and cannot go stale: the document is the reference, and the table is not to grow."""

    def test_every_entry_is_a_documented_operation_and_a_name_that_the_document_does_not_list_and_has_its_reason(self):
        for (call, place, name), reason in ACCEPTED_BUT_UNDOCUMENTED.items():
            with self.subTest(entry=f"{call} {place} {name}"):
                method, _, template = call.partition(" ")
                rules = parameter_rules(version_of(template)).get((method, template))
                self.assertIsNotNone(rules, "the call is not in the document")
                self.assertIn(place, {"query", "body"})
                listed = {entry.name for entry in rules.query} if place == "query" else {n for shape in rules.shapes for n, _ in shape.properties} | {n for n, _ in rules.fields}
                self.assertNotIn(name, listed, "the document lists it now: remove the entry")
                self.assertGreater(len(reason), 20)
                self.assertTrue(reason.endswith("."))

    def test_there_are_very_few(self):
        self.assertLessEqual(len(ACCEPTED_BUT_UNDOCUMENTED), 3)


class WhatTheAdaptersNameIsDocumentedTest(unittest.TestCase):
    """The mock judges a query parameter only when some line sends it. These read the source of the adapters, so that a name typed wrong in a branch that
    no line reaches is found as well."""

    def test_the_adapters_are_read_and_name_what_they_send(self):
        named = named_by_the_adapters()
        self.assertGreater(len(named), 20)
        for name in ("limit", "cursor", "body-format", "space-id", "expand", "cql"):
            self.assertIn(name, named)

    def test_every_query_parameter_that_the_adapters_name_is_one_of_the_documents(self):
        accepted = {name for (_, place, name) in ACCEPTED_BUT_UNDOCUMENTED if place == "query"}
        unknown = {name: places for name, places in named_by_the_adapters().items() if name not in query_names() | accepted}
        self.assertEqual(
            unknown, {}, "an adapter puts a name into a query that no operation of the two documents has: a typing mistake, or a parameter that the document lacks (ACCEPTED_BUT_UNDOCUMENTED)"
        )


class WhatNoSweepLineCanSendTest(unittest.TestCase):
    """The one table of query parameters that no line of the sweep sends says why each is there, and cannot go stale."""

    def test_every_entry_is_a_documented_name_that_the_adapters_name_and_has_its_reason(self):
        named = named_by_the_adapters()
        for name, reason in NEVER_SENT_IN_A_SWEEP.items():
            with self.subTest(name=name):
                self.assertIn(name, query_names())
                self.assertIn(name, named, "the adapters do not name it any more: remove the entry")
                self.assertGreater(len(reason), 20)
                self.assertTrue(reason.endswith("."))

    def test_there_are_none_or_very_few(self):
        self.assertLessEqual(len(NEVER_SENT_IN_A_SWEEP), 3)


class EveryOptionIsInALineOrHasItsReasonTest(unittest.TestCase):
    """An option that no sweep line names is one whose request the strict mock has never judged and whose output the privacy sweep has never read. A new option gets a
    line in the sweep module of its area (`tests/support/sweep_<area>.py`), or, when no line could show anything of it, its reason in `NOT_SWEPT`."""

    def test_every_option_of_every_command_is_in_a_line_or_in_the_table_of_reasons(self):
        left = [item for item in options_without_a_line(all_commands(), sweep_lines()) if item not in NOT_SWEPT]
        self.assertEqual(
            [f"conflu {command} {option}" for command, option in left],
            [],
            "these options are in no line of the sweep: add a line that uses each one to the sweep module of its area (tests/support/sweep_<area>.py), or give it its reason in NOT_SWEPT",
        )

    def test_every_entry_of_the_table_is_an_option_that_no_line_names_and_has_its_reason(self):
        options = {(command.name, arg.names[0]) for command in all_commands() for arg in command.args if not arg.positional}
        unswept = set(options_without_a_line(all_commands(), sweep_lines()))
        for (command, option), reason in NOT_SWEPT.items():
            with self.subTest(option=f"{command} {option}"):
                self.assertIn((command, option), options, "the command has no such option any more: remove the entry")
                self.assertIn((command, option), unswept, "a line names it now: remove the entry")
                self.assertGreater(len(reason), 20)
                self.assertTrue(reason.endswith("."))

    def test_the_table_is_short_and_is_not_to_grow(self):
        self.assertLessEqual(len(NOT_SWEPT), 6)

    def test_the_lines_that_are_read_are_those_of_every_module_of_the_sweeps(self):
        lines = sweep_lines()
        self.assertGreater(len(lines), 400)
        for expected in (("pages", "--cursor"), ("search", "--phrase"), ("page", "--body-only"), ("version",)):  # an area's line, and the lines of the output modes and of the local commands
            self.assertTrue(any(argv[0] == expected[0] and (len(expected) == 1 or expected[1] in argv) for argv in lines), expected)


class WhatTheCommandsSendIsDocumented(unittest.TestCase):
    """A sweep over every command, run through the real adapters against the mock."""

    result: SweepResult

    @classmethod
    def setUpClass(cls):
        cls.result = run_sweeps(SWEEPS)

    def test_every_line_ends_as_it_should(self):
        self.assertEqual(self.result.failures, [])
        self.assertGreater(self.result.runs, 30)

    def test_no_command_sends_a_call_that_the_document_does_not_list(self):
        self.assertEqual(self.result.unknown, [])

    def test_no_command_sends_a_call_that_the_document_marks_as_deprecated(self):
        self.assertEqual(self.result.deprecated, [])

    def test_no_command_sends_a_parameter_or_a_body_that_the_document_does_not_allow(self):
        """The sweep runs with `strict_parameters`: the mock answers HTTP 400 and records a query parameter that is not the operation's or is
        missing, a `limit` above the maximum, a required header that is missing, a form field or a property of the body that the schema does not
        list or requires. Every entry names the command line and what the document does not allow in its request."""
        self.assertEqual(self.result.invalid_requests, [])

    def test_no_command_sends_a_query_parameter_that_the_document_marks_as_deprecated(self):
        self.assertEqual(self.result.deprecated_parameters, [])

    def test_every_query_parameter_that_the_adapters_name_is_sent_by_some_line_of_the_sweep(self):
        """The mock judges what is sent. A name that no line sends (an option that no line uses, a branch that none reaches) is judged by nobody, so the
        source of the adapters is read for the names that they can put into a query (`names_in_source`), and the sweep has to send each at least once."""
        unsent = {name: places for name, places in named_by_the_adapters().items() if name not in self.result.seen_query_names and name not in NEVER_SENT_IN_A_SWEEP}
        self.assertEqual(
            unsent,
            {},
            "no line of the sweep sends these query parameters (name: where an adapter names it): add a line that sends each one to the sweep module of its area, tests/support/sweep_<area>.py",
        )

    def test_a_query_parameter_that_no_sweep_line_can_send_is_sent_by_none(self):
        self.assertEqual(sorted(set(NEVER_SENT_IN_A_SWEEP) & self.result.seen_query_names), [], "a line of the sweep sends it: remove the entry")

    def test_every_command_is_swept_or_never_asks_confluence(self):
        swept = set(self.result.calls)
        known = {command.name for command in all_commands()}
        self.assertEqual(swept - known, set(), "a sweep line names a command that does not exist")
        self.assertEqual(known - LOCAL - swept - set(OUTSIDE_ALLOWED), set(), "a command is in no sweep module: add lines to the module of its area")
        for name in LOCAL:
            self.assertEqual(self.result.calls.get(name, set()), set(), f"{name} is listed as local and asks Confluence")

    def test_a_call_that_is_no_rest_call_is_made_by_the_commands_that_may_make_it_only(self):
        for command, calls in self.result.outside.items():
            if calls:
                self.assertTrue(calls <= OUTSIDE_ALLOWED.get(command, set()), f"{command} made {sorted(calls)}")

    def test_every_call_to_v1_has_its_reason_and_every_reason_is_used(self):
        used = {call for calls in self.result.calls.values() for call in calls if version_of(call.partition(" ")[2]) == "v1"}
        explained = set(v1_calls())
        self.assertEqual(sorted(used - explained), [], "a command calls v1 where no V1_CALLS entry says why v2 does not do")
        self.assertEqual(sorted(explained - used), [], "a V1_CALLS entry that no command line of the sweep reaches")

    def test_v2_is_the_default(self):
        """Most of what the commands send is v2; a command uses v1 only for what the reasons name."""
        for command, calls in self.result.calls.items():
            if any(version_of(call.partition(" ")[2]) == "v2" for call in calls) or not calls:
                continue
            for call in calls:
                self.assertIn(call, v1_calls(), f"{command} sends only v1 calls, and {call} is not an explained one")


class CompatibilityPageTest(unittest.TestCase):
    """`docs/reference/compatibility.md` says what each command sends, and why a call is v1. Rows: `python -m tests.support.sweep_runner`."""

    @classmethod
    def setUpClass(cls):
        cls.result = run_sweeps(SWEEPS)
        cls.text = COMPATIBILITY.read_text(encoding="utf-8")

    def test_the_page_names_both_documents_and_both_guides(self):
        for needle in (
            "https://dac-static.atlassian.com/cloud/confluence/openapi-v2.v3.json",
            "https://dac-static.atlassian.com/cloud/confluence/swagger.v3.json",
            "https://developer.atlassian.com/cloud/confluence/rest/v2/intro/",
            "https://developer.atlassian.com/cloud/confluence/rest/v1/intro/",
            "/wiki/api/v2",
            "/wiki/rest/api",
            "2026-10-30",
        ):
            self.assertIn(needle, self.text)

    def test_every_call_to_v1_is_explained_on_the_page(self):
        for call, reason in v1_calls().items():
            row = next((line for line in self.text.splitlines() if line.startswith(f"| `{call}`")), "")
            with self.subTest(call=call):
                self.assertTrue(row, f"the page has no row for {call}")
                self.assertIn(reason, row)

    def test_every_command_has_a_row_with_the_calls_it_makes(self):
        rows = {}
        for line in self.text.splitlines():
            match = re.match(r"^\| `([a-z][a-z-]*)` \| (v2|v1|v2 \+ v1) \| (.+) \|$", line)
            if match:
                rows[match.group(1)] = (match.group(2), set(re.findall(r"`([^`]+)`", match.group(3))))
        expected = {row.split("`")[1]: row for row in table_rows(self.result)}
        for command, row in sorted(expected.items()):
            with self.subTest(command=command):
                self.assertIn(command, rows, f"add this row to compatibility.md:\n{row}")
                api, calls = rows[command]
                wanted = set(re.findall(r"`([^`]+)`", row.split(" | ", 2)[2]))
                self.assertEqual((api, calls), (row.split(" | ")[1], wanted), f"the row of {command} should be:\n{row}")
        self.assertEqual(sorted(set(rows) - set(expected)), [], "the page has a row for a command that makes no call")


if __name__ == "__main__":
    unittest.main()
