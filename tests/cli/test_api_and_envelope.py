"""`conflu api`: JSON dry run and `--param`; `--json-envelope`: one JSON object on stdout whatever happens."""
import json
import unittest
from unittest import mock

from conflu_c_cli.adapters.driving.cli.spec import Arg, Command, Example
from conflu_c_cli.domain.errors import ConfigError
from tests.support.cli import run_cli
from tests.support.fakes import FakeGateway, default_settings

BODY = '{"status": "current", "title": "New"}'
TRUE_WORDS = ("1", "true", "TRUE", "yes", "on")


class ApiDryRunTest(unittest.TestCase):
    def dry_run(self, *extra, gateway=None, environ=None):
        return run_cli("api", "PUT", "api/v2/pages/2005/title", "--data", BODY, "--write", "--dry-run", *extra, gateway=gateway or FakeGateway(), environ=environ)

    def test_the_text_dry_run_is_unchanged(self):
        result = self.dry_run()
        self.assertEqual(result.code, 0)
        self.assertTrue(result.out.startswith("Dry run: PUT /api/v2/pages/2005/title; nothing was sent\n"))
        self.assertIn('"title": "New"', result.out)

    def test_the_json_dry_run_is_one_json_object_and_nothing_else(self):
        gateway = FakeGateway()
        result = self.dry_run("--json", gateway=gateway)
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(
            result.json(),
            {"dryRun": True, "method": "PUT", "path": "/api/v2/pages/2005/title", "query": {}, "body": {"status": "current", "title": "New"}},
        )
        self.assertEqual(len(result.out.splitlines()), 1)
        self.assertEqual(result.err, "")
        self.assertEqual(gateway.called("request"), [])

    def test_the_query_of_the_path_is_in_the_json_dry_run(self):
        result = run_cli("api", "GET", "rest/api/search?cql=type=page&limit=5", "--dry-run", "--json")
        data = result.json()
        self.assertEqual(data["query"], {"cql": "type=page", "limit": "5"})
        self.assertEqual((data["path"], data["method"]), ("/rest/api/search", "GET"))
        self.assertIsNone(data["body"])

    def test_json_output_of_the_environment_works_as_well(self):
        self.assertFalse(self.dry_run().out.startswith("{"))
        self.assertEqual(self.dry_run(environ={"CONFLUENCE_OUTPUT": "json"}).json()["dryRun"], True)

    def test_a_dry_run_still_needs_the_confirmation_for_a_write(self):
        self.assertEqual(run_cli("api", "PUT", "api/v2/pages/2005/title", "--data", BODY, "--dry-run", "--json").code, 2)


class ApiParamTest(unittest.TestCase):
    def test_param_adds_encoded_query_parameters_without_an_ampersand_in_the_path(self):
        gateway = FakeGateway()
        result = run_cli("api", "GET", "rest/api/search", "--param", "cql=type = page AND space = ENG", "--param", "limit=5", gateway=gateway)
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(gateway.called("request"), [("request", "GET", "/rest/api/search?cql=type+%3D+page+AND+space+%3D+ENG&limit=5", None)])

    def test_param_is_added_to_the_query_that_the_path_has(self):
        gateway = FakeGateway()
        run_cli("api", "GET", "rest/api/search?cql=type=page", "--param", "limit=1", gateway=gateway)
        self.assertEqual(gateway.called("request")[0][2], "/rest/api/search?cql=type%3Dpage&limit=1")

    def test_a_name_that_repeats_is_a_list_in_the_dry_run(self):
        result = run_cli("api", "GET", "api/v2/pages", "--param", "id=2001", "--param", "id=2002", "--dry-run", "--json")
        self.assertEqual(result.json()["query"], {"id": ["2001", "2002"]})
        self.assertEqual(run_cli("api", "GET", "api/v2/pages?id=1&id=2&id=3", "--dry-run", "--json").json()["query"], {"id": ["1", "2", "3"]})

    def test_a_value_with_special_characters_survives(self):
        value = 'title ~ "a & b" AND label = "x=y"'
        result = run_cli("api", "GET", "rest/api/search", "--param", f"cql={value}", "--dry-run", "--json")
        self.assertEqual(result.json()["query"], {"cql": value})
        gateway = FakeGateway()
        run_cli("api", "GET", "rest/api/search", "--param", f"cql={value}", gateway=gateway)
        sent = gateway.called("request")[0][2]
        self.assertNotIn(" ", sent)
        self.assertEqual(sent.count("&"), 0)  # the one & of the value is encoded: it is not a second parameter

    def test_a_value_may_be_empty_and_a_name_may_have_dots_dashes_and_brackets(self):
        result = run_cli("api", "GET", "api/v2/pages", "--param", "body-format=", "--param", "a.b_c=1", "--param", "ids[]=7", "--dry-run", "--json")
        self.assertEqual(result.json()["query"], {"body-format": "", "a.b_c": "1", "ids[]": "7"})

    def test_a_value_with_unicode_is_encoded_for_the_request(self):
        gateway = FakeGateway()
        run_cli("api", "GET", "rest/api/search", "--param", "cql=title ~ \"Größe\"", gateway=gateway)
        self.assertTrue(gateway.called("request")[0][2].isascii())

    def test_param_needs_a_plain_name_and_a_value(self):
        for bad in ("nokey", "=value", "a b=c", "a&b=c", "a#b=c"):
            with self.subTest(bad=bad):
                gateway = FakeGateway()
                result = run_cli("api", "GET", "rest/api/search", "--param", bad, gateway=gateway)
                self.assertEqual(result.code, 2)
                self.assertIn("KEY=VALUE", result.err)
                self.assertEqual(gateway.called("request"), [])

    def test_a_response_with_json_is_compact_when_piped(self):
        gateway = FakeGateway()
        gateway.responses[("GET", "/api/v2/pages/2005")] = {"name": "x", "n": [1, 2]}
        result = run_cli("api", "GET", "api/v2/pages/2005", "--json", gateway=gateway)
        self.assertEqual(result.out, '{"name":"x","n":[1,2]}\n')

    def test_a_response_without_json_is_indented_as_before(self):
        gateway = FakeGateway()
        gateway.responses[("GET", "/api/v2/pages/2005")] = {"name": "x", "n": [1, 2]}
        self.assertEqual(run_cli("api", "GET", "api/v2/pages/2005", gateway=gateway).out, json.dumps({"name": "x", "n": [1, 2]}, indent=2) + "\n")


class EnvelopeTest(unittest.TestCase):
    def test_a_result_is_ok_and_data(self):
        result = run_cli("page", "2005", "--json-envelope")
        self.assertEqual(result.code, 0, result.err)
        message = result.json()
        self.assertEqual((message["ok"], message["data"]["id"]), (True, "2005"))
        self.assertEqual(set(message), {"ok", "data"})
        self.assertEqual(len(result.out.splitlines()), 1)
        self.assertEqual(result.err, "")

    def test_the_environment_switches_it_on(self):
        for word in TRUE_WORDS:
            with self.subTest(word):
                result = run_cli("page", "2005", environ={"CONFLUENCE_JSON_ENVELOPE": word})
                self.assertTrue(result.json()["ok"])
        for word in ("0", "false", "no", "off", ""):
            with self.subTest(word):
                self.assertNotIn("ok", run_cli("page", "2005", "--json", environ={"CONFLUENCE_JSON_ENVELOPE": word}).json())

    def test_an_error_is_ok_false_on_stdout_and_stderr_and_the_exit_code_stay(self):
        result = run_cli("page", "999", "--json-envelope")
        self.assertEqual(result.code, 4)
        message = result.json()
        self.assertEqual(message["ok"], False)
        self.assertEqual(set(message["error"]), {"code", "message", "hint", "exitCode", "details"})
        self.assertEqual((message["error"]["code"], message["error"]["exitCode"]), ("NOT_FOUND", 4))
        self.assertTrue(result.err.startswith("ERROR: Not found"))
        self.assertNotIn("data", message)

    def test_the_error_on_stderr_is_json_only_with_json(self):
        result = run_cli("page", "999", "--json-envelope", "--json")
        self.assertEqual(result.error()["code"], "NOT_FOUND")
        self.assertEqual(result.json()["error"]["code"], "NOT_FOUND")

    def test_a_usage_error_is_enveloped_too(self):
        for argv in (("page", "2005", "--nope", "--json-envelope"), ("pagez", "--json-envelope"), ("page", "--json-envelope")):
            with self.subTest(argv=argv):
                result = run_cli(*argv)
                self.assertEqual(result.code, 2)
                self.assertEqual((result.json()["ok"], result.json()["error"]["code"]), (False, "USAGE"))
                self.assertEqual(result.json()["error"]["exitCode"], 2)

    def test_a_command_without_json_has_its_text_as_data(self):
        result = run_cli("convert", "--json-envelope", stdin="# Title\n")
        self.assertEqual(result.json(), {"ok": True, "data": {"text": "<h1>Title</h1>"}})

    def test_a_mode_without_json_has_its_text_as_data(self):
        result = run_cli("page", "2005", "--body-only", "--json-envelope")
        self.assertEqual(result.json(), {"ok": True, "data": {"text": "Just a paragraph & text."}})

    def test_the_envelope_implies_json_for_the_command(self):
        data = run_cli("pages", "--space", "ENG", "--limit", "1", "--json-envelope").json()["data"]
        self.assertEqual((data["count"], data["space"]), (1, "ENG"))
        both = run_cli("pages", "--space", "ENG", "--limit", "1", "--json", "--json-envelope").json()
        self.assertEqual(both["data"], data)

    def test_the_dry_run_of_api_is_the_data(self):
        result = run_cli("api", "PUT", "api/v2/pages/2005/title", "--data", BODY, "--write", "--dry-run", "--json-envelope")
        self.assertEqual(result.json(), {"ok": True, "data": {"dryRun": True, "method": "PUT", "path": "/api/v2/pages/2005/title", "query": {}, "body": {"status": "current", "title": "New"}}})

    def test_the_short_version_flag_is_enveloped(self):
        for argv in (("-V", "--json-envelope"), ("version", "--json-envelope")):
            with self.subTest(argv=argv):
                self.assertEqual(run_cli(*argv).json()["data"]["name"], "conflu-c-cli")

    def test_a_non_zero_exit_code_without_an_error_is_ok_false_with_the_data(self):
        result = run_cli("current", "--json-envelope")
        self.assertEqual(result.code, 1)
        message = result.json()
        self.assertEqual((message["ok"], message["data"], message["error"]["code"], message["error"]["exitCode"]), (False, {"space": None}, "EXIT", 1))

    def test_a_doctor_with_a_failed_check_is_ok_false_with_its_report(self):
        from conflu_c_cli.application.settings import Settings

        result = run_cli("doctor", "--json-envelope", settings=Settings())
        self.assertEqual(result.code, 1)
        message = result.json()
        self.assertEqual((message["ok"], message["error"]["code"], message["error"]["exitCode"]), (False, "EXIT", 1))
        self.assertFalse(message["data"]["ok"])
        self.assertIn("fail", {check["status"] for check in message["data"]["checks"]})

    def test_help_is_not_wrapped(self):
        self.assertTrue(run_cli("page", "--help", "--json-envelope").out.startswith("conflu page - "))
        self.assertTrue(run_cli("--help", "--json-envelope").out.startswith("Confluence Cloud command line helper"))

    def test_a_bug_is_enveloped_as_well(self):
        gateway = FakeGateway()
        gateway.errors["get_page"] = RuntimeError("boom")
        result = run_cli("page", "2005", "--json-envelope", gateway=gateway)
        self.assertEqual(result.code, 1)
        message = result.json()
        self.assertEqual((message["ok"], message["error"]["code"], message["error"]["message"]), (False, "ERROR", "unexpected RuntimeError: boom"))
        self.assertIn("unexpected RuntimeError: boom", result.err)

    def test_a_bug_is_a_json_error_on_standard_error_when_json_is_asked_for_and_text_otherwise(self):
        gateway = FakeGateway()
        gateway.errors["get_page"] = RuntimeError("boom")
        for label, extra, options in (
            ("--json", ("--json",), {}),
            ("the environment", (), {"environ": {"CONFLUENCE_OUTPUT": "json"}}),
            ("the agent profile", (), {"environ": {"CONFLUENCE_PROFILE": "agent"}}),
            ("the settings", (), {"settings": default_settings(output="json")}),
            ("the envelope too", ("--json", "--json-envelope"), {}),
        ):
            with self.subTest(label):
                result = run_cli("page", "2005", *extra, gateway=gateway, **options)
                self.assertEqual(result.code, 1)
                error = result.error()
                self.assertEqual((error["code"], error["message"], error["exitCode"], error["details"]), ("ERROR", "unexpected RuntimeError: boom", 1, {}))
                self.assertIn("--verbose", error["hint"])
                self.assertEqual(len(result.err.strip().splitlines()), 1)
        text = run_cli("page", "2005", gateway=gateway)
        self.assertTrue(text.err.startswith("ERROR: unexpected RuntimeError: boom\nHint: Run again with --verbose"), text.err)

    def test_the_traceback_of_a_bug_comes_before_its_json_error(self):
        gateway = FakeGateway()
        gateway.errors["get_page"] = RuntimeError("boom")
        result = run_cli("page", "2005", "--json", "--verbose", gateway=gateway)
        self.assertIn("Traceback (most recent call last)", result.err)
        error = result.error()  # the last line of standard error, as for every error
        self.assertEqual((error["code"], error["hint"]), ("ERROR", ""))
        text = run_cli("page", "2005", "--verbose", gateway=gateway)
        self.assertIn("Traceback (most recent call last)", text.err)
        self.assertTrue(text.err.startswith("ERROR: unexpected RuntimeError: boom\n"))

    def test_what_a_failing_command_printed_before_the_error_is_not_in_the_envelope(self):
        gateway = FakeGateway()
        gateway.errors["list_comments"] = ConfigError("the comments cannot be read")
        result = run_cli("page", "2005", "--comments", "--json-envelope", gateway=gateway)
        self.assertEqual(result.code, 1)
        self.assertEqual(len(result.out.splitlines()), 1)
        self.assertEqual(result.json()["error"]["message"], "the comments cannot be read")

    def test_the_agent_profile_and_the_envelope_work_together(self):
        result = run_cli("page", "999", "--json-envelope", environ={"CONFLUENCE_PROFILE": "agent"})
        self.assertEqual(result.code, 4)
        self.assertEqual(result.error()["code"], "NOT_FOUND")  # the profile asks for JSON errors on stderr
        self.assertEqual(result.json()["error"]["code"], "NOT_FOUND")  # and the envelope is on stdout
        ok = run_cli("page", "2005", "--json-envelope", environ={"CONFLUENCE_PROFILE": "agent"})
        self.assertEqual((ok.json()["ok"], ok.err), (True, ""))

    def test_without_the_switch_nothing_changes(self):
        result = run_cli("page", "2005", "--json")
        self.assertNotIn("ok", result.json())
        self.assertEqual(result.json()["id"], "2005")

    def test_the_switch_is_in_the_help_of_every_command(self):
        for name in ("page", "convert", "search", "api"):
            with self.subTest(name):
                self.assertIn("--json-envelope", run_cli("help", name).out)
                self.assertIn("CONFLUENCE_JSON_ENVELOPE=1", run_cli(name, "--help").out)

    def test_a_command_that_streams_is_never_wrapped_not_even_when_it_fails(self):
        def handler(ctx, args):
            ctx.print("a protocol line")
            if args.fail:
                raise ConfigError("the server cannot go on")
            return 0

        command = Command(
            name="stream-demo",
            group="Tools",
            summary="Talk on the streams",
            handler=handler,
            streams=True,
            needs_app=False,
            args=(Arg(("--fail",), "Fail after the first line.", kind="flag"),),
            examples=(Example("conflu stream-demo"),),
        )
        with mock.patch("conflu_c_cli.adapters.driving.cli.main.find_command", lambda name: command if name == "stream-demo" else None):
            for env in ({"CONFLUENCE_JSON_ENVELOPE": "1"}, {}):
                ok = run_cli("stream-demo", "--json-envelope", environ=env)
                self.assertEqual((ok.code, ok.out), (0, "a protocol line\n"))
                failed = run_cli("stream-demo", "--fail", "--json-envelope", environ=env)
                self.assertEqual(failed.code, 1)
                self.assertEqual(failed.out, "a protocol line\n")  # no envelope appended to the protocol
                self.assertIn("the server cannot go on", failed.err)


class EnvelopeDocumentationTest(unittest.TestCase):
    """The reference shows the envelope as it is printed."""

    def documented(self):
        import re
        from pathlib import Path

        text = (Path(__file__).resolve().parents[2] / "docs" / "reference" / "json-output.md").read_text(encoding="utf-8")
        section = text.split("## The envelope: `--json-envelope`", 1)[1].split("\n## ", 1)[0]
        return [json.loads(block) for block in re.findall(r"```json\n(.*?)```", section, re.DOTALL)]

    def test_the_two_examples_have_the_keys_that_the_command_prints(self):
        result_example, failure_example = self.documented()
        printed = run_cli("page", "2005", "--json-envelope").json()
        self.assertEqual(set(result_example), set(printed))
        failed = run_cli("page", "999", "--json-envelope").json()
        self.assertEqual(set(failure_example), set(failed))
        self.assertEqual(set(failure_example["error"]), set(failed["error"]))
        self.assertEqual((failure_example["error"]["code"], failure_example["error"]["exitCode"]), (failed["error"]["code"], failed["error"]["exitCode"]))


if __name__ == "__main__":
    unittest.main()
