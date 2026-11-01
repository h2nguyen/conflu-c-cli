"""`conflu config path`, `set` and `unset` answer in JSON when JSON is on: through the real configuration file, in this process and as a program of its own.

They printed plain text in every mode, although `config` declares JSON and `config show` prints it, so an agent (the agent profile makes JSON the default)
could not read what they said. The shapes are small and carry no value and no secret: `{"file"}`, `{"saved", "file"}` and `{"name", "removed", "file"}`.
"""
import json
import unittest

from tests.integration.test_end_to_end import EndToEnd


class ConfigJsonTest(EndToEnd):
    def setUp(self):
        super().setUp()
        self.env["XDG_CACHE_HOME"] = str(self.root / "cache")  # this test's own cache folder: the profile of the person who runs the tests is never touched

    def stored(self) -> str:
        return self.config.read_text(encoding="utf-8") if self.config.exists() else ""

    def test_the_three_actions_answer_in_json_with_the_switch_the_environment_and_the_profile(self):
        file = str(self.config)
        for how, flags, env in (
            ("--json", ("--json",), {}),
            ("the agent profile", (), {"CONFLUENCE_PROFILE": "agent"}),
            ("CONFLUENCE_OUTPUT", (), {"CONFLUENCE_OUTPUT": "json"}),
        ):
            with self.subTest(how=how):
                path = self.cli("config", "path", *flags, env=env)
                self.assertEqual((path.code, path.json()), (0, {"file": file}))
                saved = self.cli("config", "set", "CONFLUENCE_SPACE", "ENG", *flags, env=env)
                self.assertEqual((saved.code, saved.json()), (0, {"saved": "CONFLUENCE_SPACE", "file": file}))
                self.assertIn("CONFLUENCE_SPACE=ENG", self.stored())
                removed = self.cli("config", "unset", "CONFLUENCE_SPACE", *flags, env=env)
                self.assertEqual((removed.code, removed.json()), (0, {"name": "CONFLUENCE_SPACE", "removed": True, "file": file}))
                self.assertNotIn("CONFLUENCE_SPACE", self.stored())
                again = self.cli("config", "unset", "CONFLUENCE_SPACE", *flags, env=env)
                self.assertEqual((again.code, again.json()), (0, {"name": "CONFLUENCE_SPACE", "removed": False, "file": file}))
                for result in (path, saved, removed, again):
                    self.assertEqual((result.err, result.out.count("\n")), ("", 1))  # one line of JSON, and nothing on standard error

    def test_the_text_is_what_it_was(self):
        self.assertEqual(self.cli("config", "path").out, f"{self.config}\n")
        self.assertEqual(self.cli("config", "set", "CONFLUENCE_SPACE", "ENG").out, f"CONFLUENCE_SPACE saved to {self.config}\n")
        self.assertEqual(self.cli("config", "unset", "CONFLUENCE_SPACE").out, f"CONFLUENCE_SPACE removed from {self.config}\n")
        self.assertEqual(self.cli("config", "unset", "CONFLUENCE_SPACE").out, f"CONFLUENCE_SPACE was not set in {self.config}\n")

    def test_the_envelope_holds_the_same_objects(self):
        file = str(self.config)
        self.assertEqual(self.cli("config", "path", "--json-envelope").json(), {"ok": True, "data": {"file": file}})
        self.assertEqual(self.cli("config", "set", "CONFLUENCE_SPACE", "ENG", "--json-envelope").json(), {"ok": True, "data": {"saved": "CONFLUENCE_SPACE", "file": file}})
        self.assertEqual(
            self.cli("config", "unset", "CONFLUENCE_SPACE", "--json-envelope").json(),
            {"ok": True, "data": {"name": "CONFLUENCE_SPACE", "removed": True, "file": file}},
        )

    def test_neither_a_value_nor_a_secret_is_in_the_answer(self):
        self.assertEqual(self.cli("setup-token", "--stdin", stdin=self.mock.token + "\n").code, 0)
        bundle = "C:/certs/company-ca-bundle.pem"
        for argv in (("set", "CONFLUENCE_CA_BUNDLE", bundle), ("set", "CONFLUENCE_EMAIL", "alex@example.com"), ("unset", "CONFLUENCE_API_TOKEN"), ("unset", "CONFLUENCE_CA_BUNDLE")):
            with self.subTest(argv=argv):
                result = self.cli("config", *argv, "--json")
                self.assertEqual(result.code, 0, result.err)
                for secret in (self.mock.token, "company-ca-bundle", "alex@example.com", self.mock.email):
                    self.assertNotIn(secret, result.out + result.err)
                self.assertTrue(set(result.json()) <= {"file", "saved", "name", "removed"})
        self.assertNotIn("CONFLUENCE_API_TOKEN", self.stored())  # and the removal was real

    def test_a_refusal_is_an_error_in_json_too_and_nothing_is_changed(self):
        before = self.stored()
        for argv, code in (
            (("set", "CONFLUENCE_NOPE", "x"), 2),
            (("set", "CONFLUENCE_API_TOKEN", "abc123"), 2),
            (("set", "CONFLUENCE_SPACE", "ENG\nX"), 1),
            (("unset", "CONFLUENCE_NOPE"), 2),
        ):
            with self.subTest(argv=argv):
                result = self.cli("config", *argv, "--json")
                self.assertEqual((result.code, result.out), (code, ""))
                self.assertEqual(json.loads(result.err.strip().splitlines()[-1])["error"]["exitCode"], code)
        self.assertEqual(self.stored(), before)

    def test_the_repair_of_a_file_that_cannot_be_read_answers_in_json_too(self):
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_bytes(b"CONFLUENCE_SPACE='ENG\n")
        for flags, env in ((("--json",), {}), ((), {"CONFLUENCE_PROFILE": "agent"})):
            with self.subTest(flags=flags, env=env):
                mended = self.cli("config", "set", "CONFLUENCE_SPACE", "ENG", *flags, env=env)
                self.assertEqual((mended.code, mended.json()), (0, {"saved": "CONFLUENCE_SPACE", "file": str(self.config)}))
                self.config.write_bytes(b"CONFLUENCE_SPACE='ENG\n")
        self.assertEqual(self.cli("config", "path", "--json").json(), {"file": str(self.config)})

    def test_as_a_program_of_its_own(self):
        file = str(self.config)
        for flags, env in ((("--json",), {}), ((), {"CONFLUENCE_PROFILE": "agent"})):
            with self.subTest(flags=flags, env=env):
                path = self.child("config", "path", *flags, env=env)
                self.assertEqual((path.code, path.json()), (0, {"file": file}))
                saved = self.child("config", "set", "CONFLUENCE_SPACE", "ENG", *flags, env=env)
                self.assertEqual((saved.code, saved.json()), (0, {"saved": "CONFLUENCE_SPACE", "file": file}))
                removed = self.child("config", "unset", "CONFLUENCE_SPACE", *flags, env=env)
                self.assertEqual((removed.code, removed.json()), (0, {"name": "CONFLUENCE_SPACE", "removed": True, "file": file}))
        self.assertEqual(self.child("config", "path").out, f"{self.config}\n")  # and without JSON it is the path, as it was


if __name__ == "__main__":
    unittest.main()
