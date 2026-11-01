"""No function of the program uses a name that nothing defines when it runs.

Some imports are made where they are used, so that the program starts sooner (see `tests/test_startup.py`). A name that is imported in one function only, or under
`if TYPE_CHECKING:` (which never runs), is a `NameError` in every other function that still uses it, at the moment a command reaches it, perhaps on a branch that no
test takes. This test reads the byte code of every module of the program: a name that a function (or a class body) looks up as a global must be one of the builtins, or
be bound by the code of the module when it is loaded (an import that runs, a definition, an assignment), or be assigned through `global` in a function. A name that the
module imports only under `TYPE_CHECKING` does not count: an annotation may use it, and nothing else.
"""
import ast
import builtins
import dis
import inspect
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "conflu_c_cli"
IMPLICIT = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__package__", "__spec__", "__loader__", "__builtins__", "__cached__", "__class__", "__path__"}
BODY_OF_A_CLASS = {"__module__", "__qualname__", "__firstlineno__", "__static_attributes__", "__classdictcell__", "__annotations__", "__annotate__", "__annotate_func__", "__conditional_annotations__"}


def is_type_checking(node: ast.AST) -> bool:
    if not isinstance(node, ast.If):
        return False
    test = node.test
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")


def bound_when_the_module_runs(tree: ast.Module) -> tuple[set[str], set[str]]:
    """(the names that the module-level code binds, the names that it imports only under `if TYPE_CHECKING:`)."""
    runs: set[str] = set()
    guarded: set[str] = set()

    def visit(node: ast.AST, inside_guard: bool) -> None:
        if is_type_checking(node):
            for child in node.body:
                visit(child, True)
            for child in node.orelse:
                visit(child, inside_guard)
            return
        target = guarded if inside_guard else runs
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            target.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            target.add(node.name)
            return  # what is inside is another scope
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            target.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            target.add(node.name)
        elif isinstance(node, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            return  # their names live in a scope of their own
        for child in ast.iter_child_nodes(node):
            visit(child, inside_guard)

    for statement in tree.body:
        visit(statement, False)
    return runs, guarded - runs


def code_objects(code: types.CodeType, path: str = ""):
    yield path or "<module>", code
    for constant in code.co_consts:
        if isinstance(constant, types.CodeType):
            yield from code_objects(constant, f"{path}.{constant.co_name}" if path else constant.co_name)


def problems_of(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    runs, guarded = bound_when_the_module_runs(tree)
    objects = list(code_objects(compile(source, str(path), "exec")))
    assigned_by_global = {
        instruction.argval for _, code in objects for instruction in dis.get_instructions(code) if instruction.opname == "STORE_GLOBAL"
    }
    problems = []
    for where, code in objects[1:]:  # the code of the module itself runs when it is imported: a name that is missing there fails every test
        is_function = bool(code.co_flags & inspect.CO_OPTIMIZED)
        stores = set() if is_function else {instruction.argval for instruction in dis.get_instructions(code) if instruction.opname == "STORE_NAME"}
        for instruction in dis.get_instructions(code):
            if instruction.opname == "LOAD_GLOBAL" or (not is_function and instruction.opname == "LOAD_NAME" and instruction.argval not in stores | BODY_OF_A_CLASS):
                name = instruction.argval
                if name in runs or name in assigned_by_global or name in IMPLICIT:
                    continue
                reason = "is imported for type checking only" if name in guarded else "is defined nowhere"
                problems.append(f"{path.relative_to(ROOT).as_posix()}: {where} uses {name}, which {reason}")
    return sorted(set(problems))


class UndefinedNamesTest(unittest.TestCase):
    def test_no_function_uses_a_name_that_nothing_defines(self):
        problems = []
        for path in sorted(PACKAGE.rglob("*.py")):
            if "__pycache__" not in path.parts:
                problems += problems_of(path)
        self.assertEqual(problems, [])

    def test_the_check_notices_what_it_is_for(self):
        """The three ways to get it wrong, in one module that is made up here: a name imported in another function, a name imported under TYPE_CHECKING, a typo."""
        source = (
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n    from os import path as only_for_types\n"
            "def one():\n    from json import dumps\n    return dumps({})\n"
            "def two():\n    return dumps({})\n"
            "def three() -> 'only_for_types':\n    return only_for_types\n"
            "def four():\n    return lenn([])\n"
            "def five():\n    return len([])\n"
        )
        folder = ROOT / "tests" / "__pycache__"  # nothing is written: the path only names the module in the messages
        tree = ast.parse(source)
        runs, guarded = bound_when_the_module_runs(tree)
        self.assertEqual(guarded, {"only_for_types"})
        self.assertNotIn("dumps", runs)
        found = {}
        for where, code in list(code_objects(compile(source, str(folder / "made_up.py"), "exec")))[1:]:
            for instruction in dis.get_instructions(code):
                if instruction.opname == "LOAD_GLOBAL" and instruction.argval not in runs | IMPLICIT:
                    found.setdefault(where, set()).add(instruction.argval)
        self.assertEqual(found, {"two": {"dumps"}, "three": {"only_for_types"}, "four": {"lenn"}})


if __name__ == "__main__":
    unittest.main()
