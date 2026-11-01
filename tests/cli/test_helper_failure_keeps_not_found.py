"""The look at what an id could be (`content_types`) only explains a 404. When that look itself fails, the 404 stands: exit code 4 as in 1.0.0,
not the 5, 6 or 7 of a helper call that the person never made."""
import unittest

from conflu_c_cli.domain.errors import AuthError, RejectedError, UnavailableError
from tests.support.cli import run_cli
from tests.support.fakes import FakeGateway, MemoryFiles

FAILURES = (
    ("HTTP 400", RejectedError("the helper was refused")),
    ("HTTP 401", AuthError("the helper was not allowed")),
    ("HTTP 403", AuthError("the helper was forbidden")),
    ("HTTP 429", UnavailableError("the helper was rate limited")),
    ("HTTP 500", UnavailableError("the helper had a server error")),
)

COMMANDS = (
    ("tree", "99999"),
    ("move", "2005", "--to", "99999"),
    ("move", "2005", "--to", "99999", "--dry-run"),
    ("move", "99999", "--to", "2003"),
    ("create", "--space", "ENG", "--title", "T", "--parent", "99999"),
    ("create", "--space", "ENG", "--title", "T", "--parent", "99999", "--dry-run"),
    ("export", "--page", "99999", "--out", "out"),
    ("import-md", "a.md", "--space", "ENG", "--parent", "99999"),
    ("import-md-dir", "md", "--space", "ENG", "--parent", "99999"),
)


def files() -> MemoryFiles:
    return MemoryFiles({"a.md": "# From a file\n\nText.\n", "md/b.md": "# Page b\n\ntext\n"})


class HelperFailureKeepsNotFoundTest(unittest.TestCase):
    def test_without_a_failure_every_one_of_these_is_not_found(self):
        for argv in COMMANDS:
            with self.subTest(argv=argv):
                self.assertEqual(run_cli(*argv, gateway=FakeGateway(), files=files()).code, 4)

    def test_a_failing_look_does_not_change_the_exit_code(self):
        for argv in COMMANDS:
            for status, error in FAILURES:
                with self.subTest(argv=argv, helper=status):
                    gateway = FakeGateway()
                    gateway.errors["content_types"] = error
                    result = run_cli(*argv, gateway=gateway, files=files())
                    self.assertEqual(result.code, 4, result.err)
                    self.assertNotIn("helper", result.err)  # the message is that of the page that was not found
                    self.assertEqual(gateway.called("create_page"), [])
                    self.assertEqual(gateway.called("move_page"), [])

    def test_json_says_the_same(self):
        gateway = FakeGateway()
        gateway.errors["content_types"] = UnavailableError("the helper had a server error")
        result = run_cli("tree", "99999", "--json", gateway=gateway)
        self.assertEqual((result.code, result.error()["code"], result.error()["exitCode"]), (4, "NOT_FOUND", 4))

    def test_when_the_look_works_the_answer_is_as_before(self):
        gateway = FakeGateway()
        gateway.content_kinds["7201"] = "blogpost"
        result = run_cli("create", "--space", "ENG", "--title", "T", "--parent", "7201", gateway=gateway)
        self.assertEqual(result.code, 1)
        self.assertIn("blog post", result.err)


if __name__ == "__main__":
    unittest.main()
