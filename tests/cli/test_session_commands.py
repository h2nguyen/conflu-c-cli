"""The commands of the setup through the command line, with fakes behind it: `doctor` with its options, `config show` with a profile, `ping`
with an address that holds credentials, and `setup --discover`."""
import io
import json
import unittest

from conflu_c_cli.adapters.driving.cli.main import run
from conflu_c_cli.adapters.driving.cli.registry import all_commands, find_command
from conflu_c_cli.application.settings import Settings
from conflu_c_cli.domain.errors import ConfigError, UnavailableError
from tests.support.cli import run_cli
from tests.support.fakes import BASE, FakeGateway, MemoryCache, MemoryConfigStore, MemoryFiles, default_settings

GATEWAY = "https://api.atlassian.com/ex/confluence/"
CLOUD_ID = FakeGateway().cloud_id
STORED = {"CONFLUENCE_BASE_URL": BASE, "CONFLUENCE_EMAIL": "user@example.com", "CONFLUENCE_API_TOKEN": "secret-token"}
WITH_CREDENTIALS = "https://" + "alex:s3cr3tpw" + "@example.atlassian.net/wiki"


def configured(**values):
    return Settings.from_mapping({**STORED, **values})


class DoctorCommandTest(unittest.TestCase):
    def doctor(self, *argv, **options):
        options.setdefault("files", MemoryFiles({"memory://config": "x"}))
        return run_cli("doctor", *argv, **options)

    def test_the_json_has_the_cached_keys(self):
        report = self.doctor("--json").json()
        self.assertEqual((report["ok"], report["cached"], report["cachedAt"]), (True, False, None))
        self.assertEqual(set(report), {"ok", "checks", "cached", "cachedAt"})
        self.assertEqual(set(report["checks"][0]), {"name", "status", "detail", "hint"})  # nothing that was there is gone

    def test_a_broken_configuration_has_the_cached_keys_too(self):
        def factory(diagnostics):
            raise ConfigError("CONFLUENCE_RETRY must be a whole number, not 'x'.", hint="Fix it.")

        out = io.StringIO()
        code = run(["doctor", "--json"], app_factory=factory, environ={}, stdout=out, stderr=io.StringIO(), stdin=io.StringIO())
        report = json.loads(out.getvalue())
        self.assertEqual((code, report["ok"], report["cached"], report["cachedAt"]), (1, False, False, None))

    def test_cached_reuses_the_checks_and_the_text_says_so(self):
        cache, gateway = MemoryCache(), FakeGateway()
        first = self.doctor("--cached", "10m", cache=cache, gateway=gateway)
        self.assertNotIn("nothing was asked", first.out)
        asked = len(gateway.calls)
        text = self.doctor("--cached", "10m", cache=cache, gateway=gateway)
        self.assertEqual(text.code, 0, text.out)
        self.assertIn("(the online checks are from a run at 2026-10-15T08:00:00+00:00: nothing was asked of Confluence)", text.out)
        self.assertEqual(len(gateway.calls), asked)
        report = self.doctor("--cached", "10m", "--json", cache=cache, gateway=gateway).json()
        self.assertEqual((report["cached"], report["cachedAt"]), (True, "2026-10-15T08:00:00+00:00"))
        self.assertEqual(len(gateway.calls), asked)

    def test_the_age_may_be_written_in_seconds_minutes_hours_and_days_and_a_bare_number_counts_in_minutes(self):
        for age in ("30s", "10m", "2h", "1d", "5", "1.5h"):
            with self.subTest(age=age):
                cache = MemoryCache()
                self.doctor("--cached", age, cache=cache)
                self.assertTrue(self.doctor("--cached", age, "--json", cache=cache).json()["cached"])

    def test_a_run_that_is_older_than_the_age_asks_again(self):
        cache, gateway = MemoryCache(), FakeGateway()
        self.doctor(cache=cache, gateway=gateway)
        ((key, _),) = cache.values.items()
        cache.ages[key] = 3601.0
        self.assertFalse(self.doctor("--cached", "30m", "--json", cache=cache, gateway=gateway).json()["cached"])
        cache.ages[key] = 1.0
        self.assertTrue(self.doctor("--cached", "30m", "--json", cache=cache, gateway=gateway).json()["cached"])

    def test_a_bad_age_is_a_usage_error_and_nothing_is_asked(self):
        gateway = FakeGateway()
        for age in ("soon", "", "10x", "m10", "1e3m", "5 5"):
            with self.subTest(age=age):
                result = self.doctor("--cached", age, gateway=gateway)
                self.assertEqual(result.code, 2)
                self.assertIn("Not a length of time", result.err)
                self.assertIn("10m", result.err)
        self.assertEqual(self.doctor("--cached", "-5m", gateway=gateway).code, 2)  # the parser takes it for an option
        self.assertEqual(gateway.calls, [])
        error = self.doctor("--cached", "soon", "--json").error()
        self.assertEqual((error["code"], error["exitCode"]), ("USAGE", 2))

    def test_quick_asks_twice_at_most(self):
        gateway = FakeGateway()
        result = self.doctor("--quick", gateway=gateway, settings=default_settings(space="ENG"))
        self.assertEqual(result.code, 0, result.out)
        self.assertEqual([call[0] for call in gateway.calls], ["current_user", "list_spaces"])
        self.assertNotIn(" space ", result.out)
        names = [check["name"] for check in self.doctor("--quick", "--json").json()["checks"]]
        self.assertEqual(names[-4:], ["connection", "spaces", "api", "privacy"])

    def test_quick_and_cached_together(self):
        cache, gateway = MemoryCache(), FakeGateway()
        self.doctor("--quick", "--cached", "10m", cache=cache, gateway=gateway)
        asked = len(gateway.calls)
        again = self.doctor("--quick", "--cached", "10m", "--json", cache=cache, gateway=gateway).json()
        self.assertTrue(again["cached"])
        self.assertEqual(len(gateway.calls), asked)
        self.assertFalse(self.doctor("--cached", "10m", "--json", cache=cache, gateway=gateway).json()["cached"])  # the full form is another run

    def test_strict_privacy_sets_the_exit_code(self):
        result = self.doctor("--strict-privacy", "--json")
        self.assertEqual(result.code, 1)
        report = result.json()
        privacy = next(check for check in report["checks"] if check["name"] == "privacy")
        self.assertEqual((report["ok"], privacy["status"]), (False, "fail"))
        self.assertIn("CONFLUENCE_PROFILE=agent", privacy["hint"])
        text = self.doctor("--strict-privacy")
        self.assertEqual(text.code, 1)
        self.assertIn("[FAIL] privacy", text.out)
        for settings in (default_settings(hide_users=True), configured(CONFLUENCE_PROFILE="agent")):
            self.assertEqual(self.doctor("--strict-privacy", "--json", settings=settings).code, 0)
        self.assertEqual(self.doctor().code, 0)  # without the option nothing changes

    def test_a_profile_that_people_can_still_get_around_is_a_warning(self):
        result = self.doctor("--json", settings=configured(CONFLUENCE_PROFILE="agent", CONFLUENCE_HIDE_USERS="false"))
        self.assertEqual(result.code, 0)
        privacy = next(check for check in result.json()["checks"] if check["name"] == "privacy")
        self.assertEqual(privacy["status"], "warn")
        text = self.doctor(settings=configured(CONFLUENCE_PROFILE="agent", CONFLUENCE_HIDE_USERS="false", CONFLUENCE_OUTPUT="text"))
        self.assertIn("[warn] privacy", text.out)
        self.assertIn("Hint: Take that setting away", text.out)

    def test_the_launcher_is_checked_when_the_runtime_says(self):
        found = self.doctor(runtime={"version": "1.0.0", "python": "3.13", "launcher": "/opt/tools/bin/conflu"})
        self.assertIn("[ok]   launcher", found.out)
        self.assertIn("/opt/tools/bin/conflu", found.out)
        missing = self.doctor(runtime={"version": "1.0.0", "python": "3.13", "launcher": "", "program": "/work/conflu.py", "install_script": "/work/install.py"})
        self.assertEqual(missing.code, 0)  # a warning is advice
        self.assertIn("[warn] launcher", missing.out)
        self.assertIn('python "/work/install.py" --bin-dir DIR', missing.out)
        self.assertNotIn("launcher", self.doctor().out)  # the fakes' runtime makes no statement

    def test_the_options_are_described_for_a_reader_and_for_a_program(self):
        command = find_command("doctor")
        self.assertEqual([arg.names[0] for arg in command.args], ["--quick", "--cached", "--strict-privacy"])
        self.assertIn("cached", command.output)
        self.assertIn("cachedAt", command.output)
        self.assertFalse(command.writes)


class ConfigShowTest(unittest.TestCase):
    def test_the_profile_and_what_it_sets_are_listed(self):
        store = MemoryConfigStore({**STORED, "CONFLUENCE_PROFILE": "agent"})
        data = run_cli("config", "show", "--json", store=store, settings=configured(CONFLUENCE_PROFILE="agent")).json()
        entries = {item["name"]: item for item in data["settings"]}
        self.assertEqual((entries["CONFLUENCE_PROFILE"]["value"], entries["CONFLUENCE_PROFILE"]["source"]), ("agent", "config file"))
        self.assertEqual((entries["CONFLUENCE_HIDE_USERS"]["value"], entries["CONFLUENCE_HIDE_USERS"]["source"]), ("true", "profile"))
        self.assertEqual((entries["CONFLUENCE_OUTPUT"]["value"], entries["CONFLUENCE_OUTPUT"]["source"]), ("json", "profile"))
        self.assertEqual(set(entries["CONFLUENCE_HIDE_USERS"]), {"name", "value", "source", "description", "secret"})  # no key was added or removed
        self.assertEqual(set(data), {"file", "settings"})

    def test_the_text_has_the_source_column(self):
        store = MemoryConfigStore({**STORED, "CONFLUENCE_PROFILE": "agent", "CONFLUENCE_OUTPUT": "text"})
        shown = run_cli("config", store=store, settings=configured(CONFLUENCE_PROFILE="agent", CONFLUENCE_OUTPUT="text")).out
        hide = next(line for line in shown.splitlines() if line.startswith("CONFLUENCE_HIDE_USERS"))
        self.assertEqual(hide.split(), ["CONFLUENCE_HIDE_USERS", "true", "profile"])
        output = next(line for line in shown.splitlines() if line.startswith("CONFLUENCE_OUTPUT"))
        self.assertEqual(output.split(), ["CONFLUENCE_OUTPUT", "text", "config", "file"])

    def test_an_address_with_credentials_is_never_shown_by_config(self):
        store = MemoryConfigStore({**STORED, "CONFLUENCE_BASE_URL": WITH_CREDENTIALS})
        for argv in (("config",), ("config", "show", "--json")):
            result = run_cli(*argv, store=store, settings=configured(CONFLUENCE_BASE_URL=WITH_CREDENTIALS))
            with self.subTest(argv=argv):
                self.assertNotIn("s3cr3tpw", result.out + result.err)
                self.assertNotIn("alex:", result.out)
                self.assertIn("https://********@example.atlassian.net/wiki", result.out)

    def test_an_address_with_an_at_after_the_host_is_not_shown_at_all(self):
        address = "https://" + "alex:pa/s3cr3tpw" + "@example.atlassian.net/wiki"
        result = run_cli("config", store=MemoryConfigStore({**STORED, "CONFLUENCE_BASE_URL": address}), settings=configured())
        self.assertNotIn("s3cr3tpw", result.out)
        self.assertNotIn("pa/", result.out)
        self.assertIn("(not shown: it holds an @ after the host name)", result.out)

    def test_config_set_refuses_such_an_address_and_does_not_repeat_it(self):
        for address in (WITH_CREDENTIALS, "https://" + "alex:pa/s3cr3tpw" + "@example.atlassian.net/wiki", "https://" + "alex:pa?s3cr3tpw" + "@example.atlassian.net/wiki", "https://" + "alex:pa#s3cr3tpw" + "@example.atlassian.net/wiki"):
            store = MemoryConfigStore()
            result = run_cli("config", "set", "CONFLUENCE_BASE_URL", address, store=store)
            with self.subTest(address=address.replace("s3cr3tpw", "<secret>")):
                self.assertEqual(result.code, 1)
                self.assertEqual(store.values, {})
                self.assertNotIn("s3cr3tpw", result.out + result.err)
                self.assertNotIn("alex", result.err)
                self.assertIn("user name or password", result.err)


class ConfigActionsTest(unittest.TestCase):
    """`config path`, `set` and `unset` answer in JSON whenever JSON is on, as `config show` does, and print what they always did otherwise."""

    FILE = "memory://config"

    def way_to_json(self):
        """Every way that makes JSON the answer: the switch, the environment, the profile, the settings, the envelope is a case of its own."""
        return (
            ("--json", (("--json",), {})),
            ("CONFLUENCE_OUTPUT in the environment", ((), {"environ": {"CONFLUENCE_OUTPUT": "json"}})),
            ("the agent profile in the environment", ((), {"environ": {"CONFLUENCE_PROFILE": "agent"}})),
            ("the agent profile in the settings", ((), {"settings": configured(CONFLUENCE_PROFILE="agent")})),
            ("CONFLUENCE_OUTPUT in the settings", ((), {"settings": configured(CONFLUENCE_OUTPUT="json")})),
        )

    def test_the_three_actions_answer_in_json_in_every_json_mode(self):
        for how, (flags, options) in self.way_to_json():
            with self.subTest(how=how):
                store = MemoryConfigStore(dict(STORED))
                path = run_cli("config", "path", *flags, store=store, **options)
                self.assertEqual((path.code, path.json()), (0, {"file": self.FILE}))
                saved = run_cli("config", "set", "CONFLUENCE_SPACE", "ENG", *flags, store=store, **options)
                self.assertEqual((saved.code, saved.json()), (0, {"saved": "CONFLUENCE_SPACE", "file": self.FILE}))
                self.assertEqual(store.values["CONFLUENCE_SPACE"], "ENG")
                removed = run_cli("config", "unset", "CONFLUENCE_SPACE", *flags, store=store, **options)
                self.assertEqual((removed.code, removed.json()), (0, {"name": "CONFLUENCE_SPACE", "removed": True, "file": self.FILE}))
                self.assertNotIn("CONFLUENCE_SPACE", store.values)
                again = run_cli("config", "unset", "CONFLUENCE_SPACE", *flags, store=store, **options)
                self.assertEqual((again.code, again.json()), (0, {"name": "CONFLUENCE_SPACE", "removed": False, "file": self.FILE}))
                for result in (path, saved, removed, again):
                    self.assertEqual(result.out.count("\n"), 1)  # one line of JSON and nothing else on standard output

    def test_the_text_is_what_it_was(self):
        store = MemoryConfigStore(dict(STORED))
        self.assertEqual(run_cli("config", "path", store=store).out, "memory://config\n")
        self.assertEqual(run_cli("config", "set", "CONFLUENCE_SPACE", "ENG", store=store).out, "CONFLUENCE_SPACE saved to memory://config\n")
        self.assertEqual(run_cli("config", "unset", "CONFLUENCE_SPACE", store=store).out, "CONFLUENCE_SPACE removed from memory://config\n")
        self.assertEqual(run_cli("config", "unset", "CONFLUENCE_SPACE", store=store).out, "CONFLUENCE_SPACE was not set in memory://config\n")

    def test_the_envelope_holds_the_same_objects(self):
        store = MemoryConfigStore(dict(STORED))
        for argv, data in (
            (("path",), {"file": self.FILE}),
            (("set", "CONFLUENCE_SPACE", "ENG"), {"saved": "CONFLUENCE_SPACE", "file": self.FILE}),
            (("unset", "CONFLUENCE_SPACE"), {"name": "CONFLUENCE_SPACE", "removed": True, "file": self.FILE}),
        ):
            with self.subTest(argv=argv):
                result = run_cli("config", *argv, "--json-envelope", store=store)
                self.assertEqual((result.code, result.json()), (0, {"ok": True, "data": data}))

    def test_no_value_and_no_secret_is_ever_in_the_answer(self):
        """The name of a setting and the file are all that the answers hold: not what was written, not the token, not the e-mail address."""
        store = MemoryConfigStore({**STORED, "CONFLUENCE_CA_BUNDLE": "C:/certs/stored-bundle.pem"})
        secrets = ("company-ca-bundle", "ENGINEERING", "secret-token", "user@example.com", "stored-bundle")
        for argv in (
            ("set", "CONFLUENCE_CA_BUNDLE", "C:/certs/company-ca-bundle.pem"),
            ("set", "CONFLUENCE_SPACE", "ENGINEERING"),
            ("unset", "CONFLUENCE_CA_BUNDLE"),
            ("unset", "CONFLUENCE_API_TOKEN"),
            ("unset", "CONFLUENCE_EMAIL"),
            ("path",),
        ):
            for flags, options in ((("--json",), {}), ((), {"settings": configured(CONFLUENCE_PROFILE="agent")})):
                result = run_cli("config", *argv, *flags, store=store, **options)
                with self.subTest(argv=argv, flags=flags):
                    self.assertEqual(result.code, 0, result.err)
                    for secret in secrets:
                        self.assertNotIn(secret, result.out + result.err)
                    self.assertTrue(set(result.json()) <= {"file", "saved", "name", "removed"}, result.out)

    def test_a_refused_change_is_still_an_error_and_prints_no_result(self):
        for argv, code in (
            (("set", "CONFLUENCE_NOPE", "x"), 2),
            (("set", "CONFLUENCE_HIDE_USERS"), 2),
            (("set", "CONFLUENCE_API_TOKEN", "abc123"), 2),
            (("set", "CONFLUENCE_EMAIL", "not-an-address"), 1),
            (("unset", "CONFLUENCE_NOPE"), 2),
            (("unset",), 2),
        ):
            with self.subTest(argv=argv):
                store = MemoryConfigStore(dict(STORED))
                result = run_cli("config", *argv, "--json", store=store)
                self.assertEqual((result.code, result.out), (code, ""))
                self.assertEqual(json.loads(result.err.strip().splitlines()[-1])["error"]["exitCode"], code)
                self.assertEqual(store.values, STORED)

    def test_the_warning_about_the_environment_stays_on_standard_error(self):
        result = run_cli("config", "set", "CONFLUENCE_SPACE", "ENG", "--json", store=MemoryConfigStore(dict(STORED)), environ={"CONFLUENCE_SPACE": "DOCS"})
        self.assertEqual(result.json(), {"saved": "CONFLUENCE_SPACE", "file": self.FILE})
        self.assertIn("CONFLUENCE_SPACE is also set in the environment", result.err)
        removed = run_cli("config", "unset", "CONFLUENCE_SPACE", "--json", store=MemoryConfigStore({**STORED, "CONFLUENCE_SPACE": "ENG"}), environ={"CONFLUENCE_SPACE": "DOCS"})
        self.assertEqual(removed.json(), {"name": "CONFLUENCE_SPACE", "removed": True, "file": self.FILE})
        self.assertIn("CONFLUENCE_SPACE is also set in the environment", removed.err)

    def test_show_is_the_same_as_before(self):
        store = MemoryConfigStore(dict(STORED))
        for flags, options in ((("--json",), {}), ((), {"environ": {"CONFLUENCE_PROFILE": "agent"}})):
            data = run_cli("config", "show", *flags, store=store, **options).json()
            self.assertEqual(set(data), {"file", "settings"})
            self.assertEqual(data["file"], self.FILE)

    def test_the_catalog_says_what_each_action_prints(self):
        output = find_command("config").output
        for part in ("show: file, settings[", "path: file", "set: saved", "never its value", "unset: name, removed, file"):
            self.assertIn(part, output)


class PingAddressTest(unittest.TestCase):
    def test_the_address_in_the_result_has_no_credentials(self):
        settings = configured(CONFLUENCE_BASE_URL=WITH_CREDENTIALS)
        for argv in (("ping",), ("ping", "--json"), ("ping", "--quiet", "--json")):
            result = run_cli(*argv, settings=settings)
            with self.subTest(argv=argv):
                self.assertEqual(result.code, 0, result.err)
                self.assertNotIn("s3cr3tpw", result.out + result.err)
        self.assertEqual(run_cli("ping", "--json", settings=settings).json()["baseUrl"], "https://********@example.atlassian.net/wiki")


class SetupCommandTest(unittest.TestCase):
    def setup_discover(self, *argv, settings=None, store=None, gateway=None, **options):
        store = store if store is not None else MemoryConfigStore()
        gateway = gateway or FakeGateway()
        result = run_cli("setup", *argv, store=store, gateway=gateway, settings=settings or default_settings(), **options)
        return result, store, gateway

    def test_it_is_a_command_for_the_person_that_writes_the_configuration_only(self):
        command = find_command("setup")
        self.assertIn(command, all_commands())
        self.assertEqual((command.group, command.writes, command.for_person, command.local, command.json_output), ("Setup and information", True, True, False, True))
        self.assertTrue(any("--dry-run" in arg.names for arg in command.args))

    def test_it_has_to_be_told_what_to_set_up(self):
        result, store, gateway = self.setup_discover()
        self.assertEqual(result.code, 2)
        self.assertIn("--discover", result.err)
        self.assertEqual((store.values, gateway.calls), ({}, []))

    def test_yes_saves_the_gateway_address_and_reminds_of_the_token(self):
        result, store, gateway = self.setup_discover("--discover", "--yes")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(store.values, {"CONFLUENCE_BASE_URL": GATEWAY + CLOUD_ID})
        self.assertEqual(gateway.called("tenant_info"), [("tenant_info", BASE)])
        self.assertIn(f"Site: example.atlassian.net, cloud id {CLOUD_ID}", result.out)
        self.assertIn("saved to memory://config", result.out)
        self.assertIn("API token with scopes", result.out)
        self.assertIn("a token without scopes works on the site address", result.out)
        self.assertIn("conflu doctor", result.out)
        self.assertEqual(result.err, "")

    def test_without_a_terminal_and_without_yes_nothing_is_written_and_the_command_is_printed(self):
        result, store, _ = self.setup_discover("--discover")
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(store.values, {})
        self.assertIn(f"Gateway address: {GATEWAY}{CLOUD_ID}", result.out)
        self.assertIn("Nothing was written", result.out)
        self.assertIn(f"conflu config set CONFLUENCE_BASE_URL {GATEWAY}{CLOUD_ID}", result.out)
        self.assertNotIn("[y/N]", result.err)  # nobody was asked

    def test_on_a_terminal_it_asks_and_y_saves(self):
        for answer in ("y\n", "Y\n", "yes\n", " YES \n"):
            with self.subTest(answer=answer):
                result, store, _ = self.setup_discover("--discover", stdin=answer, stdin_tty=True)
                self.assertEqual(result.code, 0, result.err)
                self.assertEqual(store.values, {"CONFLUENCE_BASE_URL": GATEWAY + CLOUD_ID})
                self.assertEqual(result.err, f"Set CONFLUENCE_BASE_URL to {GATEWAY}{CLOUD_ID}? [y/N] ")  # the question is on standard error
                self.assertNotIn("[y/N]", result.out)

    def test_on_a_terminal_anything_but_yes_writes_nothing(self):
        for answer in ("", "\n", "n\n", "no\n", "maybe\n", "yy\n"):
            with self.subTest(answer=answer):
                result, store, _ = self.setup_discover("--discover", stdin=answer, stdin_tty=True)
                self.assertEqual(result.code, 0, result.err)
                self.assertEqual(store.values, {})
                self.assertIn("Nothing was written.", result.out)
                self.assertNotIn("conflu config set", result.out)  # the person was asked and said no: no lecture

    def test_a_dry_run_says_what_would_be_written_and_writes_and_asks_nothing(self):
        result, store, _ = self.setup_discover("--discover", "--dry-run", "--yes", stdin="y\n", stdin_tty=True)
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(store.values, {})
        self.assertIn(f"Would set CONFLUENCE_BASE_URL to {GATEWAY}{CLOUD_ID}", result.out)
        self.assertIn("Dry run: nothing was written.", result.out)
        self.assertEqual(result.err, "")

    def test_the_json_result(self):
        result, store, _ = self.setup_discover("--discover", "--yes", "--json")
        self.assertEqual(
            result.json(),
            {"current": BASE, "cloudId": CLOUD_ID, "gatewayAddress": GATEWAY + CLOUD_ID, "written": True, "dryRun": False, "changed": True},
        )
        dry = self.setup_discover("--discover", "--dry-run", "--json")[0].json()
        self.assertEqual((dry["written"], dry["dryRun"], dry["changed"]), (False, True, True))
        silent = self.setup_discover("--discover", "--json")[0].json()
        self.assertEqual((silent["written"], silent["dryRun"], silent["changed"]), (False, False, True))
        self.assertEqual(store.values, {"CONFLUENCE_BASE_URL": GATEWAY + CLOUD_ID})

    def test_an_address_that_is_the_gateway_address_already_is_said_and_nothing_is_asked_or_written(self):
        for address in (GATEWAY + CLOUD_ID, GATEWAY + CLOUD_ID + "/wiki", GATEWAY + CLOUD_ID + "/"):
            with self.subTest(address=address):
                result, store, gateway = self.setup_discover("--discover", "--yes", settings=default_settings(base_url=address))
                self.assertEqual(result.code, 0, result.err)
                self.assertIn("is the gateway address already", result.out)
                self.assertIn("Nothing was written.", result.out)
                self.assertEqual((store.values, gateway.calls), ({}, []))
        data = self.setup_discover("--discover", "--yes", "--json", settings=default_settings(base_url=GATEWAY + CLOUD_ID + "/wiki"))[0].json()
        self.assertEqual(
            data,
            {"current": GATEWAY + CLOUD_ID + "/wiki", "cloudId": CLOUD_ID, "gatewayAddress": GATEWAY + CLOUD_ID, "written": False, "dryRun": False, "changed": False},
        )

    def test_a_custom_domain_is_told_why_the_gateway_is_the_way(self):
        result, _, gateway = self.setup_discover("--discover", settings=default_settings(base_url="https://wiki.example.org/wiki"))
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("Site: wiki.example.org", result.out)
        self.assertIn("custom domain", result.out)
        self.assertEqual(gateway.called("tenant_info"), [("tenant_info", "https://wiki.example.org/wiki")])

    def test_an_atlassian_net_address_is_proposed_the_same_and_told_that_the_site_address_works_too(self):
        result, _, _ = self.setup_discover("--discover", settings=default_settings(base_url="https://example.atlassian.net"))
        self.assertIn(f"Gateway address: {GATEWAY}{CLOUD_ID}", result.out)
        self.assertIn("The site address (example.atlassian.net) works too, with an API token without scopes", result.out)

    def test_no_credential_is_needed_to_ask(self):
        result, store, gateway = self.setup_discover("--discover", "--yes", settings=Settings.from_mapping({"CONFLUENCE_BASE_URL": BASE}))
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(store.values, {"CONFLUENCE_BASE_URL": GATEWAY + CLOUD_ID})

    def test_without_an_address_it_says_how_to_set_one(self):
        result, store, gateway = self.setup_discover("--discover", "--yes", settings=Settings())
        self.assertEqual(result.code, 1)
        self.assertIn("CONFLUENCE_BASE_URL is not set", result.err)
        self.assertIn("conflu config set CONFLUENCE_BASE_URL", result.err)
        self.assertEqual((store.values, gateway.calls), ({}, []))

    def test_an_address_with_credentials_is_refused_and_not_repeated_and_nothing_is_asked(self):
        for address in (WITH_CREDENTIALS, "https://" + "alex:pa/s3cr3tpw" + "@example.atlassian.net/wiki"):
            result, store, gateway = self.setup_discover("--discover", "--yes", settings=Settings.from_mapping({"CONFLUENCE_BASE_URL": address}))
            with self.subTest(address=address.replace("s3cr3tpw", "<secret>")):
                self.assertEqual(result.code, 1)
                self.assertIn("user name or password", result.err)
                self.assertNotIn("s3cr3tpw", result.out + result.err)
                self.assertNotIn("alex", result.err)
                self.assertEqual((store.values, gateway.calls), ({}, []))

    def test_the_value_checks_of_config_set_apply(self):
        gateway = FakeGateway()
        gateway.cloud_id = "not a cloud id"
        result, store, _ = self.setup_discover("--discover", "--yes", gateway=gateway)
        self.assertEqual(result.code, 1)
        self.assertIn("Not a web address", result.err)
        self.assertEqual(store.values, {})

    def test_a_failure_to_ask_is_the_error_of_the_gateway_and_writes_nothing(self):
        gateway = FakeGateway()
        gateway.errors["tenant_info"] = UnavailableError("Cannot reach Confluence (the network).", hint="Check the VPN.")
        result, store, _ = self.setup_discover("--discover", "--yes", gateway=gateway)
        self.assertEqual(result.code, 7)
        self.assertIn("Check the VPN.", result.err)
        self.assertEqual(store.values, {})

    def test_a_variable_that_overrides_the_file_is_pointed_out(self):
        result, store, _ = self.setup_discover("--discover", "--yes", environ={"CONFLUENCE_BASE_URL": BASE})
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(store.values, {"CONFLUENCE_BASE_URL": GATEWAY + CLOUD_ID})
        self.assertIn("CONFLUENCE_BASE_URL is also set in the environment", result.err)

    def test_the_agent_profile_gets_json_and_no_question(self):
        result, store, _ = self.setup_discover("--discover", settings=configured(CONFLUENCE_PROFILE="agent"))
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(result.json()["written"], False)
        self.assertEqual(store.values, {})


if __name__ == "__main__":
    unittest.main()
