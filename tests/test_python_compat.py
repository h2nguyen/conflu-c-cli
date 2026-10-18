"""The README promises Python 3.10: nothing in the tree may need a newer interpreter.

Only 3.13 may be at hand when the tests run, so these checks read the sources instead of running them on 3.10:
the syntax is parsed as 3.10 would, the f-string forms that arrived with 3.12 are searched for in the token
stream, and the library names that arrived after 3.10 are searched for in the syntax tree.
"""
from __future__ import annotations

import ast
import io
import tokenize
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Names that exist only after Python 3.10; the comment gives the first version that has them.
NEWER_NAMES = {
    "UTC": "3.11 (datetime.UTC: use timezone.utc)",
    "StrEnum": "3.11",
    "Self": "3.11 (typing.Self)",
    "tomllib": "3.11",
    "ExceptionGroup": "3.11",
    "BaseExceptionGroup": "3.11",
    "TaskGroup": "3.11",
    "add_note": "3.11",
    "file_digest": "3.11 (hashlib.file_digest)",
    "getLevelNamesMapping": "3.11",
    "chdir": "3.11 (contextlib.chdir)",
    "HTTPMethod": "3.11",
    "NOFLAG": "3.11 (re.NOFLAG)",
    "batched": "3.12 (itertools.batched)",
    "is_junction": "3.12",
    "isjunction": "3.12",
    "onexc": "3.12 (shutil.rmtree)",
    "delete_on_close": "3.12 (tempfile.NamedTemporaryFile)",
    "walk_up": "3.12 (Path.relative_to)",
    "case_sensitive": "3.12 (Path.glob)",
}


def python_files() -> list[Path]:
    found = [ROOT / "conflu.py", ROOT / "install.py"]
    for folder in ("src", "tests", "scripts"):
        found.extend(sorted((ROOT / folder).rglob("*.py")))
    return [path for path in found if "__pycache__" not in path.parts]


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


class SyntaxTest(unittest.TestCase):
    def test_every_file_parses_as_python_3_10(self):
        for path in python_files():
            with self.subTest(file=relative(path)):
                try:
                    ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 10))
                except SyntaxError as error:
                    self.fail(f"{relative(path)}:{error.lineno}: {error.msg}")

    @unittest.skipUnless(
        hasattr(tokenize, "FSTRING_START"),
        "before 3.12 the tokenizer returns an f-string as one STRING token, and the parser itself rejects the 3.12 forms",
    )
    def test_no_f_string_needs_python_3_12(self):
        """3.12 allows the outer quote and backslashes inside the braces of an f-string; 3.10 does not."""
        for path in python_files():
            with self.subTest(file=relative(path)):
                source = path.read_text(encoding="utf-8")
                open_strings: list[str] = []  # the quote characters of the f-strings being read
                for token in tokenize.generate_tokens(io.StringIO(source).readline):
                    text = token.string
                    if token.type == tokenize.FSTRING_START:
                        quote = text.lstrip("rRfFbBuU")
                        if open_strings and quote == open_strings[-1]:
                            self.fail(f"{relative(path)}:{token.start[0]}: an f-string reuses the quote of the f-string around it")
                        open_strings.append(quote)
                    elif token.type == tokenize.FSTRING_END:
                        open_strings.pop()
                    elif open_strings and token.type == tokenize.STRING:
                        body = text.lstrip("rRfFbBuU")
                        if body[:3] in ('"""', "'''") or body[:1] == open_strings[-1]:
                            self.fail(f"{relative(path)}:{token.start[0]}: a string inside an f-string reuses its quote")
                        if "\\" in text:
                            self.fail(f"{relative(path)}:{token.start[0]}: a backslash inside the braces of an f-string")
                    elif open_strings and token.type == tokenize.COMMENT:
                        self.fail(f"{relative(path)}:{token.start[0]}: a comment inside an f-string")
                self.assertEqual(open_strings, [])


def version_gated_lines(tree: ast.AST) -> set[int]:
    """The lines inside an `if sys.version_info ...` block: code that only runs on the interpreters that have it."""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "version_info" in ast.unparse(node.test):
            for statement in node.body + node.orelse:
                lines.update(range(statement.lineno, (statement.end_lineno or statement.lineno) + 1))
    return lines


class LibraryTest(unittest.TestCase):
    def test_no_library_name_needs_python_3_11_or_newer(self):
        for path in python_files():
            if path.name == Path(__file__).name:
                continue  # this file lists the names
            with self.subTest(file=relative(path)):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                gated = version_gated_lines(tree)
                for node in ast.walk(tree):
                    if getattr(node, "lineno", None) in gated:
                        continue
                    names: list[str] = []
                    if isinstance(node, ast.Name):
                        names = [node.id]
                    elif isinstance(node, ast.Attribute):
                        names = [node.attr]
                    elif isinstance(node, ast.ImportFrom):
                        names = [alias.name for alias in node.names] + [node.module or ""]
                    elif isinstance(node, ast.Import):
                        names = [alias.name for alias in node.names]
                    elif isinstance(node, ast.keyword) and node.arg:
                        names = [node.arg]
                    for name in names:
                        for part in name.split("."):
                            if part in NEWER_NAMES:
                                self.fail(f"{relative(path)}:{getattr(node, 'lineno', '?')}: `{part}` needs Python {NEWER_NAMES[part]}")


if __name__ == "__main__":
    unittest.main()
