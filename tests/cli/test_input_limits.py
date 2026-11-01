"""What is read through `@FILE`, `--file` and `-` is read to one byte beyond its limit and no further: a file whose size is not known (a device, a pipe,
a file that is still growing) cannot make a command read for ever, and a text that is longer than the limit is refused with a message that names it."""
import io
import unittest

from conflu_c_cli.adapters.driving.cli.main import run
from conflu_c_cli.adapters.driving.cli.registry import find_command
from conflu_c_cli.adapters.driving.cli.runtime import Context
from conflu_c_cli.domain.errors import UsageError
from conflu_c_cli.domain.textio import BODY_LIMIT, QUERY_LIMIT
from tests.support.cli import run_cli
from tests.support.fakes import FakeGateway, MemoryConfigStore, MemoryFiles, build_app, default_settings

QUERY_MESSAGE = "at most 1,048,576 bytes"
BODY_MESSAGE = "at most 16,777,216 bytes"


class LyingFiles(MemoryFiles):
    """Files that claim to be empty and are not: what `size()` says is not to be believed. They hold NUL bytes, as a device does (`/dev/zero`), so
    that a reader that does not refuse them fails at once on "is not text" instead of spending minutes on a text of 16 MiB."""

    def __init__(self, delivers: bytes) -> None:
        super().__init__()
        self.delivers = delivers

    def size(self, path: str) -> int:
        return 0

    def exists(self, path: str) -> bool:
        return True

    def read_bytes(self, path: str) -> bytes:
        return self.delivers


class EndlessFiles(MemoryFiles):
    """Files that have no end, as `/dev/zero`. Reading one to its end would never return, so that is an error here; reading a part hands over what
    was asked for (NUL bytes) and writes it down."""

    def __init__(self) -> None:
        super().__init__()
        self.asked: list[int] = []

    def size(self, path: str) -> int:
        return 0

    def exists(self, path: str) -> bool:
        return True

    def read_bytes(self, path: str) -> bytes:
        raise AssertionError("a file that has no end was read to its end")

    def read_up_to(self, path: str, count: int) -> bytes:
        self.asked.append(count)
        return b"\x00" * count


class EndlessStdin:
    """Standard input that never ends: a `read()` without a bound is an error, and every read is written down."""

    def __init__(self) -> None:
        self.asked: list[int | None] = []
        self.buffer = self

    def read(self, size: int | None = -1) -> bytes:
        self.asked.append(size)
        if size is None or size < 0:
            raise AssertionError("standard input was read without a bound")
        return b"\x00" * size

    def isatty(self) -> bool:
        return False


def run_endless(argv, stdin, files=None, gateway=None):
    """The command line with an input that never ends: (exit code, standard output, standard error)."""
    gateway = gateway or FakeGateway()
    out, err = io.StringIO(), io.StringIO()
    code = run(
        list(argv),
        app_factory=lambda diagnostics: build_app(gateway=gateway, files=files, store=MemoryConfigStore(), diagnostics=diagnostics),
        environ={},
        stdout=out,
        stderr=err,
        stdin=stdin,
    )
    return code, out.getvalue(), err.getvalue()


class SizeThatAFileClaimsIsNotBelievedTest(unittest.TestCase):
    def test_a_query_file_that_says_it_is_empty_and_is_not_is_refused_at_the_limit(self):
        files = LyingFiles(b"\x00" * (QUERY_LIMIT + 10))
        for argv in (("search", "--cql", "@query.txt"), ("search", "@query.txt")):
            with self.subTest(argv=argv):
                gateway = FakeGateway()
                result = run_cli(*argv, files=files, gateway=gateway)
                self.assertEqual(result.code, 2, result.err)
                self.assertIn(QUERY_MESSAGE, result.err)
                self.assertIn("query.txt", result.err)
                self.assertEqual(gateway.called("search"), [])

    def test_a_text_file_that_says_it_is_empty_and_is_not_is_refused_at_the_limit(self):
        files = LyingFiles(b"\x00" * (BODY_LIMIT + 10))
        for argv in (
            ("comment", "2002", "--file", "body.md"),
            ("create", "--space", "ENG", "--title", "T", "--file", "body.md"),
            ("update", "2005", "--file", "body.md"),
            ("convert", "body.md"),
            ("api", "PUT", "api/v2/pages/2005/title", "--data-file", "body.md", "--write"),
        ):
            with self.subTest(argv=argv[0]):
                gateway = FakeGateway()
                result = run_cli(*argv, files=files, gateway=gateway)
                self.assertEqual(result.code, 2, result.err)
                self.assertIn(BODY_MESSAGE, result.err)
                self.assertIn("body.md", result.err)
                self.assertEqual([call[0] for call in gateway.calls if call[0] in ("add_comment", "create_page", "update_page", "request")], [])

    def test_a_file_of_exactly_the_limit_is_read(self):
        query = b"type = page"
        result = run_cli("search", "--cql", "@query.txt", "--json", files=LyingFiles(query + b" " * (QUERY_LIMIT - len(query))))
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(result.json()["cql"], "type = page")
        self.assertEqual(run_cli("search", "--cql", "@query.txt", files=LyingFiles(query + b" " * (QUERY_LIMIT - len(query) + 1))).code, 2)


class ReadToOneByteBeyondTheLimitTest(unittest.TestCase):
    def test_a_query_file_is_asked_for_one_byte_beyond_the_limit_and_no_more(self):
        files = EndlessFiles()
        code, _, err = run_endless(("search", "--cql", "@/dev/zero"), io.StringIO(), files=files)
        self.assertEqual(code, 2, err)
        self.assertIn(QUERY_MESSAGE, err)
        self.assertEqual(files.asked, [QUERY_LIMIT + 1])

    def test_a_text_file_is_asked_for_one_byte_beyond_the_limit_and_no_more(self):
        for argv in (("comment", "2002", "--file", "/dev/zero"), ("convert", "/dev/zero"), ("update", "2005", "--file", "/dev/zero")):
            with self.subTest(argv=argv[0]):
                files = EndlessFiles()
                code, _, err = run_endless(argv, io.StringIO(), files=files)
                self.assertEqual(code, 2, err)
                self.assertIn(BODY_MESSAGE, err)
                self.assertEqual(files.asked, [BODY_LIMIT + 1])

    def test_standard_input_is_read_to_one_byte_beyond_the_limit_and_no_more(self):
        for argv, limit, message in (
            (("search", "-"), QUERY_LIMIT, QUERY_MESSAGE),
            (("search", "--cql", "@-"), QUERY_LIMIT, QUERY_MESSAGE),
            (("comment", "2002", "--file", "-"), BODY_LIMIT, BODY_MESSAGE),
            (("convert",), BODY_LIMIT, BODY_MESSAGE),
            (("setup-token", "--stdin"), BODY_LIMIT, BODY_MESSAGE),
        ):
            with self.subTest(argv=argv):
                stdin = EndlessStdin()
                code, out, err = run_endless(argv, stdin)
                self.assertEqual(code, 2, err)
                self.assertIn("Standard input holds more than", err)
                self.assertIn(message, err)
                self.assertEqual(stdin.asked, [limit + 1])
                self.assertEqual(out, "")

    def test_a_pipe_of_exactly_the_limit_is_read_and_one_byte_more_is_refused(self):
        words = b"roles"
        exactly = words + b" " * (QUERY_LIMIT - len(words))
        self.assertEqual(run_cli("search", "-", "--json", stdin=exactly).code, 0)
        refused = run_cli("search", "-", stdin=exactly + b" ")
        self.assertEqual(refused.code, 2)
        self.assertIn(QUERY_MESSAGE, refused.err)

    def test_a_text_stream_without_a_binary_layer_is_bounded_too(self):
        refused = run_cli("search", "-", stdin="x" * (QUERY_LIMIT + 1))
        self.assertEqual(refused.code, 2)
        self.assertIn(QUERY_MESSAGE, refused.err)
        self.assertEqual(run_cli("search", "-", "--json", stdin="roles" + " " * (QUERY_LIMIT - 5)).code, 0)

    def test_a_token_that_is_too_long_is_refused_and_not_printed(self):
        store = MemoryConfigStore()
        result = run_cli("setup-token", "--stdin", store=store, stdin=b"SECRET" * (BODY_LIMIT // 6 + 1))
        self.assertEqual(result.code, 2)
        self.assertNotIn("SECRET", result.out + result.err)
        self.assertEqual(store.values, {})


class TheLimitOfOneReadTest(unittest.TestCase):
    """The same rule at the level of the reader, with a limit of a few bytes, so that the boundary can be tried exactly."""

    def context(self, files, stdin=None):
        return Context(
            command=find_command("convert"),
            app_factory=lambda diagnostics: build_app(files=files, settings=default_settings(), diagnostics=diagnostics),
            out=io.StringIO(),
            err=io.StringIO(),
            stdin=stdin or io.StringIO(),
            json_flag=False,
            verbose=False,
            environ={},
        )

    def test_a_file_of_the_limit_is_read_and_one_byte_more_is_refused(self):
        files = MemoryFiles({"ten.txt": b"0123456789", "eleven.txt": b"0123456789a"})
        context = self.context(files)
        self.assertEqual(context.read_input("ten.txt", limit=10), "0123456789")
        with self.assertRaises(UsageError) as caught:
            context.read_input("eleven.txt", limit=10, what="query")
        self.assertEqual(caught.exception.exit_code, 2)
        self.assertIn("eleven.txt holds more than 10 bytes: a query may hold at most 10 bytes.", caught.exception.message)
        self.assertIn("Check that it is the file you meant", caught.exception.hint)

    def test_standard_input_of_the_limit_is_read_and_one_byte_more_is_refused(self):
        self.assertEqual(self.context(MemoryFiles(), io.TextIOWrapper(io.BytesIO(b"0123456789"), encoding="utf-8")).read_stdin(10), "0123456789")
        with self.assertRaises(UsageError) as caught:
            self.context(MemoryFiles(), io.TextIOWrapper(io.BytesIO(b"0123456789a"), encoding="utf-8")).read_stdin(10)
        self.assertIn("Standard input holds more than 10 bytes", caught.exception.message)

    def test_what_is_read_is_still_decoded(self):
        files = MemoryFiles({"mark.txt": b"\xef\xbb\xbfab\r\n"})
        self.assertEqual(self.context(files).read_input("mark.txt", limit=10), "ab\n")  # the byte order mark is part of the bytes that count


if __name__ == "__main__":
    unittest.main()
