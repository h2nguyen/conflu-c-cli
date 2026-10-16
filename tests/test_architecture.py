"""The architecture as tests: layering (hexagonal), stdlib only, and the composition root.

A violation names the file and the import, so the rule can be read from the failure.
"""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PACKAGE = "conflu_c_cli"

# What the inner layers must not touch: the outside world.
IO_MODULES = {"os", "sys", "pathlib", "socket", "ssl", "http", "urllib", "subprocess", "shutil", "tempfile", "getpass", "platform", "time", "glob", "logging", "threading"}


def modules():
    for path in sorted((SRC / PACKAGE).rglob("*.py")):
        relative = path.relative_to(SRC).with_suffix("")
        parts = list(relative.parts)
        is_package = parts[-1] == "__init__"
        if is_package:
            parts.pop()
        yield path, ".".join(parts), is_package


def imports_of(path: Path, name: str, is_package: bool) -> set[str]:
    """Every module a file imports, as absolute dotted names (relative imports resolved)."""
    package = name if is_package else name.rpartition(".")[0]
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")[: len(package.split(".")) - (node.level - 1)]
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            found.add(target)
            found.update(f"{target}.{alias.name}" for alias in node.names)
    return found


def layer(name: str) -> str:
    parts = name.split(".")
    if len(parts) >= 3 and parts[1] == "adapters":
        return f"adapters.{parts[2]}"
    return parts[1] if len(parts) > 1 else "root"


class LayeringTest(unittest.TestCase):
    def violations(self, layer_name: str, allowed_prefixes: tuple[str, ...], forbidden_io: bool) -> list[str]:
        problems = []
        for path, name, is_package in modules():
            if layer(name) != layer_name:
                continue
            for imported in sorted(imports_of(path, name, is_package)):
                top = imported.split(".")[0]
                if top == PACKAGE and not any(imported == prefix or imported.startswith(prefix + ".") for prefix in allowed_prefixes):
                    problems.append(f"{name} imports {imported}")
                if forbidden_io and top in IO_MODULES:
                    problems.append(f"{name} imports {imported}, which does I/O")
        return problems

    def test_domain_depends_on_nothing_else(self):
        self.assertEqual(self.violations("domain", (f"{PACKAGE}.domain",), forbidden_io=True), [])

    def test_application_depends_on_the_domain_only(self):
        self.assertEqual(self.violations("application", (f"{PACKAGE}.domain", f"{PACKAGE}.application"), forbidden_io=True), [])

    def test_driven_adapters_implement_ports_and_know_no_other_adapter(self):
        allowed = (f"{PACKAGE}.domain", f"{PACKAGE}.application", f"{PACKAGE}.adapters.driven", f"{PACKAGE}.version")
        self.assertEqual(self.violations("adapters.driven", allowed, forbidden_io=False), [])

    def test_the_command_line_uses_the_application_and_never_an_adapter_behind_it(self):
        allowed = (f"{PACKAGE}.domain", f"{PACKAGE}.application", f"{PACKAGE}.adapters.driving", f"{PACKAGE}.version")
        self.assertEqual(self.violations("adapters.driving", allowed, forbidden_io=False), [])

    def test_only_the_composition_root_knows_both_sides(self):
        for path, name, is_package in modules():
            imported = imports_of(path, name, is_package)
            sees_driven = any(item.startswith(f"{PACKAGE}.adapters.driven") for item in imported)
            sees_driving = any(item.startswith(f"{PACKAGE}.adapters.driving") for item in imported)
            if sees_driven and sees_driving:
                self.assertEqual(name, f"{PACKAGE}.bootstrap")

    def test_nothing_imports_the_composition_root_but_the_entry_points(self):
        for path, name, is_package in modules():
            if name in (f"{PACKAGE}.__main__", f"{PACKAGE}.bootstrap"):
                continue
            self.assertFalse(any(item.startswith(f"{PACKAGE}.bootstrap") for item in imports_of(path, name, is_package)), name)

    def test_the_layers_exist(self):
        seen = {layer(name) for _, name, _ in modules()}
        self.assertTrue({"domain", "application", "adapters.driven", "adapters.driving"} <= seen)


class DependenciesTest(unittest.TestCase):
    def test_only_the_standard_library_is_used(self):
        """No third-party package, in the program or in its tools: nothing to install."""
        problems = []
        files = [(path, name, is_package) for path, name, is_package in modules()]
        extra = [ROOT / "conflu.py", ROOT / "install.py", *sorted((ROOT / "scripts").glob("*.py"))]
        files += [(path, path.stem, False) for path in extra if path.is_file()]
        siblings = {path.stem for path in (ROOT / "scripts").glob("*.py")}  # the scripts import each other
        for path, name, is_package in files:
            for imported in imports_of(path, name if path.is_relative_to(SRC) else "tool", is_package):
                top = imported.split(".")[0]
                if top and top != PACKAGE and top not in siblings and top not in sys.stdlib_module_names:
                    problems.append(f"{path.relative_to(ROOT)} imports {imported}")
        self.assertEqual(problems, [])

    def test_no_dependency_manifest_sneaks_in(self):
        for name in ("requirements.txt", "pyproject.toml", "setup.py", "Pipfile", "poetry.lock", "package.json"):
            self.assertFalse((ROOT / name).exists(), f"{name} would add something to install")


class PortsTest(unittest.TestCase):
    def test_every_port_has_a_real_adapter_and_a_test_double(self):
        import inspect

        from conflu_c_cli.adapters.driven import confluence_rest, file_config, local_docs, system
        from conflu_c_cli.application import ports
        from tests.support import fakes

        abstract = {cls for _, cls in inspect.getmembers(ports, inspect.isclass) if inspect.isabstract(cls) and cls.__module__ == ports.__name__}
        real = {base for module in (confluence_rest, file_config, local_docs, system) for _, cls in inspect.getmembers(module, inspect.isclass) if cls.__module__ == module.__name__ for base in cls.__mro__ if base in abstract}
        doubles = {base for _, cls in inspect.getmembers(fakes, inspect.isclass) if cls.__module__ == fakes.__name__ for base in cls.__mro__ if base in abstract}
        self.assertEqual({cls.__name__ for cls in abstract} - {cls.__name__ for cls in real} - {"Diagnostics"}, set())  # Diagnostics lives with the command line
        self.assertEqual({cls.__name__ for cls in abstract} - {cls.__name__ for cls in doubles}, set())

    def test_every_command_module_is_registered(self):
        from conflu_c_cli.adapters.driving.cli.commands import MODULES

        folder = SRC / PACKAGE / "adapters" / "driving" / "cli" / "commands"
        on_disk = {path.stem for path in folder.glob("*.py") if not path.stem.startswith("_")}
        self.assertEqual(on_disk, {module.__name__.rpartition(".")[2] for module in MODULES})


def strings_of(tree: ast.AST) -> list[str]:
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]


class HygieneTest(unittest.TestCase):
    def test_no_module_leaves_an_unused_import(self):
        """A leftover import hides what a module really depends on."""
        problems = []
        for path, name, _ in modules():
            if path.name == "__init__.py":
                continue
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            imported: dict[str, int] = {}
            exported: set[str] = set()
            used: set[str] = set()
            type_only: set[str] = set()  # imported only for annotations, which may be written as strings
            for guard in ast.walk(tree):
                if isinstance(guard, ast.If) and isinstance(guard.test, ast.Name) and guard.test.id == "TYPE_CHECKING":
                    for node in ast.walk(guard):
                        if isinstance(node, (ast.Import, ast.ImportFrom)):
                            type_only.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imported[(alias.asname or alias.name).split(".")[0]] = node.lineno
                elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
                    for alias in node.names:
                        imported[alias.asname or alias.name] = node.lineno
                elif isinstance(node, ast.Name):
                    used.add(node.id)
                elif isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
                    exported = {element.value for element in node.value.elts if isinstance(element, ast.Constant)}
            quoted = {symbol for symbol in type_only if any(symbol in text for text in strings_of(tree))}
            problems += [f"{name}:{line} imports {symbol} and never uses it" for symbol, line in imported.items() if symbol not in used | exported | quoted]
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
