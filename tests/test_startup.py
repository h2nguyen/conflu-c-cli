"""What a start of the program loads: a call to `conflu` should cost what it uses.

On a computer where every file that Python opens costs a virus scan, the code that a call loads without using it is most of what the call takes: once the
program had grown from 36 to 63 commands, `conflu version` took a third longer than before, because the application, every use case, every feature area of the
REST adapter and all of their models were imported for it. The use cases are built when they are first asked for (`application/app.py`), the gateway to Confluence
when a use case first calls it (`bootstrap.py`), and the models and the mapper of a feature area where its REST calls are made (`rest_*.py`).

These tests start the real program as a child process with `-X importtime`, which names every module that gets imported, and hold the result:

- `conflu version` and `conflu help COMMAND` load no application, no use case, no gateway and no TLS code,
- a command that never asks Confluence (`conflu config show`) builds its application, but not the code that talks to Confluence,
- a command that reads a page loads no models and no mapper of an area that it does not read, and `conflu search` not even the code that reads a page,
- and the commands of those areas do load theirs (so that the tests above would notice if the imports were moved back to the top of the modules).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from functools import cached_property
from pathlib import Path

from tests.support.fakes import build_app
from tests.support.mock_confluence import MockConfluence

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "conflu_c_cli"
TALKS_TO_CONFLUENCE = (f"{PACKAGE}.adapters.driven.confluence_rest", f"{PACKAGE}.adapters.driven.http_transport", "ssl", "http.client")


class StartupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock = MockConfluence()
        cls.mock.start()
        cls.addClassCleanup(cls.mock.stop)
        holder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(holder.cleanup)
        home = Path(holder.name)
        base = {key: value for key, value in os.environ.items() if not key.startswith(("CONFLUENCE_", "PYTHON"))}
        cls.env = {
            **base,
            "CONFLUENCE_CONFIG_FILE": str(home / "config"),
            "HOME": str(home),
            "USERPROFILE": str(home),
            "XDG_CACHE_HOME": str(home / "cache"),
            "CONFLUENCE_BASE_URL": cls.mock.base_url,
            "CONFLUENCE_EMAIL": cls.mock.email,
            "CONFLUENCE_API_TOKEN": cls.mock.token,
            "CONFLUENCE_SPACE": "ENG",
        }

    def loaded(self, *argv: str) -> set[str]:
        """The names of the modules that the real program imports for this command line, and the command must have worked."""
        done = subprocess.run(
            [sys.executable, "-I", "-X", "importtime", str(ROOT / "conflu.py"), *argv],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=self.env,
            timeout=120,
        )
        self.assertEqual(done.returncode, 0, f"conflu {' '.join(argv)}: {done.stderr[-600:]}")
        names = set()
        for line in done.stderr.splitlines():
            match = re.match(r"import time:\s+\d+ \|\s+\d+ \| (\s*)(\S+)", line)
            if match:
                names.add(match.group(2))
        self.assertIn(f"{PACKAGE}.bootstrap", names)  # the output of -X importtime was read
        return names

    def assertNotLoaded(self, loaded: set[str], names: tuple[str, ...] | list[str], what: str) -> None:
        self.assertEqual(sorted(set(names) & loaded), [], f"{what} loaded what it does not use")

    def test_version_and_help_load_no_application_no_gateway_and_no_tls(self):
        forbidden = {
            ("version",): (f"{PACKAGE}.application.app", f"{PACKAGE}.application.ports", f"{PACKAGE}.application.pages"),
            ("help", "page"): (f"{PACKAGE}.application.app", f"{PACKAGE}.application.pages"),  # the options of `search` name their choices in `application/search.py`
            ("help", "--brief"): (f"{PACKAGE}.application.app",),  # it reads the description of every command, which is every command module
        }
        for argv, modules in forbidden.items():
            with self.subTest(argv=argv):
                self.assertNotLoaded(self.loaded(*argv), (*TALKS_TO_CONFLUENCE, *modules), f"conflu {' '.join(argv)}")

    def test_a_command_that_never_asks_confluence_builds_its_application_and_loads_no_gateway(self):
        for argv in (("config", "show"), ("current",)):
            with self.subTest(argv=argv):
                loaded = self.loaded(*argv)
                self.assertIn(f"{PACKAGE}.application.app", loaded)
                self.assertIn(f"{PACKAGE}.application.session", loaded)
                self.assertNotLoaded(loaded, (*TALKS_TO_CONFLUENCE, f"{PACKAGE}.application.ports", f"{PACKAGE}.application.pages"), f"conflu {' '.join(argv)}")

    def test_a_page_loads_no_models_and_no_mapper_of_the_areas_that_it_does_not_read(self):
        loaded = self.loaded("page", "2002", "--json")
        self.assertIn(f"{PACKAGE}.adapters.driven.confluence_rest", loaded)
        self.assertIn(f"{PACKAGE}.application.pages", loaded)
        other_areas = [f"{PACKAGE}.domain.{name}" for name in ("access", "templates", "tasks", "watches", "users", "properties", "comments")]
        other_areas += [f"{PACKAGE}.application.comments"]
        other_areas += sorted(name for name in loaded if name.startswith(f"{PACKAGE}.adapters.driven.map_"))  # not one mapper: `page` needs none of them
        self.assertNotLoaded(loaded, other_areas, "conflu page")

    def test_a_search_does_not_load_the_code_that_reads_a_page(self):
        loaded = self.loaded("search", "budget", "--json")
        self.assertNotLoaded(loaded, (f"{PACKAGE}.application.pages", f"{PACKAGE}.application.comments", f"{PACKAGE}.domain.access"), "conflu search")

    def test_the_commands_of_an_area_load_the_models_and_the_mapper_of_that_area(self):
        wanted = {
            ("permissions", "2002", "--json"): ("adapters.driven.map_access", "domain.access"),
            ("tasks", "--json"): ("adapters.driven.map_tasks", "domain.tasks"),
            ("templates", "--json"): ("adapters.driven.map_templates", "domain.templates"),
            ("page", "2002", "--comments", "--json"): ("application.comments", "domain.comments"),
        }
        for argv, modules in wanted.items():
            with self.subTest(argv=argv):
                loaded = self.loaded(*argv)
                for module in modules:
                    self.assertIn(f"{PACKAGE}.{module}", loaded)


class LazyApplicationTest(unittest.TestCase):
    def test_a_use_case_is_built_when_it_is_first_asked_for_and_only_once(self):
        app = build_app()
        self.assertEqual(sorted(name for name in vars(app) if not name.startswith("_")), ["closers", "diagnostics", "docs", "files", "settings"])
        first = app.view_page
        self.assertIs(app.view_page, first)
        self.assertIn("view_page", vars(app))
        self.assertNotIn("list_pages", vars(app))
        self.assertNotIn("structure", vars(app))

    def test_the_attachment_use_cases_are_the_objects_of_the_area(self):
        app = build_app()
        self.assertIs(app.list_attachments, app.attachments.list_attachments)
        self.assertIs(app.download_attachments, app.attachments.download)
        self.assertIs(app.upload_attachments, app.attachments.upload)

    def test_every_use_case_can_be_built(self):
        """What the commands ask the application for is there, and its wiring needs nothing that is missing: a slip in a lazy builder would show only
        when a command asks for that use case."""
        app = build_app()
        names = [name for name, attribute in vars(type(app)).items() if isinstance(attribute, (cached_property, property)) and not name.startswith("_")]
        self.assertGreaterEqual(len(names), 40)
        for name in names:
            with self.subTest(use_case=name):
                self.assertIsNotNone(getattr(app, name))


if __name__ == "__main__":
    unittest.main()
