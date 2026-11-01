"""Use cases around the shipped documentation, the skill, Markdown conversion and raw API calls."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..domain.errors import UsageError, ValidationError
from ..domain.frontmatter import parse_markdown_page
from ..domain.markdown import markdown_to_storage
from ..domain.privacy import strip_users
from ..domain.storage import storage_to_markdown
from .ports_local import DocTopic, Docs, Files
from .settings import Settings

if TYPE_CHECKING:
    from .ports import ConfluenceGateway  # only the raw API talks to Confluence: the documents and the conversion never load its code

SKILL_FOLDER = "conflu-c-cli"
SKILL_FILE = "SKILL.md"

# What may not stand in the path of a raw call. A segment of two dots leaves the folder of the API on a server (or a proxy in front of it) that collapses
# dot segments, and it can be written in many ways: `..`, `%2e%2e`, `.%2e`, `%2E.`, and with a path parameter (`..;x`, which some servers drop before
# they collapse). A separator that is written as a code (`%2f`, `%5c`) or the other way round (`\`) is refused as well.
_FORBIDDEN_IN_PATH = re.compile(r"(?:^|/)(?:\.|%2e){2}(?:;[^/]*)?(?:/|$)|%2e%2e|%2f|%5c|\\", re.IGNORECASE)


class ReadDocs:
    def __init__(self, docs: Docs) -> None:
        self._docs = docs

    def topics(self) -> list[DocTopic]:
        return self._docs.topics()

    def topic(self, name: str) -> str:
        return self._docs.topic(name)

    def readme(self) -> str:
        return self._docs.readme()

    def changelog(self) -> str:
        return self._docs.changelog()

    def skill(self) -> str:
        return self._docs.skill()


@dataclass(frozen=True)
class SkillInstall:
    path: str
    dry_run: bool
    action: str  # installed | replaced | unchanged


class InstallSkill:
    """Copies the skill that ships with the CLI into a folder of agent skills."""

    def __init__(self, docs: Docs, files: Files) -> None:
        self._docs = docs
        self._files = files

    def execute(self, directory: str, *, dry_run: bool = False, force: bool = False) -> SkillInstall:
        target = self._files.join(directory, SKILL_FOLDER, SKILL_FILE)
        skill = self._docs.skill()
        existing = self._files.read_text(target) if self._files.exists(target) else None
        if existing == skill:
            return SkillInstall(target, dry_run, "unchanged")
        if existing is not None and not force:
            raise ValidationError(
                f"{target} exists and differs from the skill of this version (an older one, or one you changed).",
                hint="Use --force to replace it.",
            )
        if not dry_run:
            self._files.write_text(target, skill)
        return SkillInstall(target, dry_run, "installed" if existing is None else "replaced")


@dataclass(frozen=True)
class Conversion:
    text: str
    source: str  # markdown | storage
    dropped: tuple[str, ...] = ()


class ConvertText:
    """Markdown to storage format, or storage format to Markdown, for a look at what the other commands send and read."""

    def execute(self, text: str, source: str = "markdown") -> Conversion:
        if source == "markdown":
            return Conversion(markdown_to_storage(parse_markdown_page(text).body), source)
        if source == "storage":
            converted = storage_to_markdown(text)
            return Conversion(converted.text, source, converted.dropped)
        raise UsageError(f"Unknown source format: {source}", hint="Use markdown or storage.")


@dataclass(frozen=True)
class RawResult:
    method: str
    path: str
    dry_run: bool
    body: Any = None
    response: Any = None


class RawApi:
    """An escape hatch for what no command covers yet. GET is free; writing must be asked for."""

    METHODS = ("GET", "POST", "PUT")

    def __init__(self, gateway: ConfluenceGateway, settings: Settings) -> None:
        self._gateway = gateway
        self._settings = settings

    @staticmethod
    def _checked_path(path: str) -> str:
        text = path.strip()
        if not text:
            raise UsageError("A path is required.", hint="Example: api/v2/pages/123456 or rest/api/search?cql=type=page")
        if re.search(r"[\x00-\x1f\x7f]", text):
            raise UsageError("The path must not contain control characters.", hint="A space or a quote is fine; a line break is not.")
        if "://" in text or text.startswith("//"):
            raise UsageError("The path must not contain a host.", hint="It is relative to the wiki address, for example api/v2/pages/123456.")
        text = text if text.startswith("/") else "/" + text
        route = text.split("#", 1)[0].split("?", 1)[0]  # what is sent: no fragment, and the path before the query
        if _FORBIDDEN_IN_PATH.search(route):
            raise UsageError("The path must not contain `..` (written in any way, `%2e%2e` and `.%2e` too) or an encoded separator.")
        if not (route.startswith("/api/") or route.startswith("/rest/")):
            raise UsageError(
                f"The path must start with api/ or rest/: {path}",
                hint="Confluence Cloud has api/v2/... and rest/api/...; the wiki address is added for you.",
            )
        return text

    def execute(self, method: str, path: str, body_text: str = "", *, write: bool = False, dry_run: bool = False) -> RawResult:
        method = method.upper()
        if method not in self.METHODS:
            raise UsageError(f"Method {method} is not supported.", hint="Use GET, POST or PUT. DELETE is deliberately not offered.")
        if method != "GET" and not write:
            raise UsageError(f"{method} changes Confluence.", hint="Add --write to confirm, and preview with --dry-run first.")
        path = self._checked_path(path)
        body: Any = None
        if body_text.strip():
            try:
                body = json.loads(body_text)
            except ValueError as error:
                raise ValidationError(
                    f"The request body is not valid JSON: {error}",
                    hint="Windows PowerShell 5.1 removes the double quotes inside an argument. Put the body in a file and pass --data-file FILE.",
                ) from error
        if method != "GET" and body is None:
            raise UsageError(f"{method} needs a body.", hint="Pass --data JSON or --data-file FILE.")
        if dry_run:
            return RawResult(method, path, True, body)
        response = self._gateway.request(method, path, body)
        return RawResult(method, path, False, body, strip_users(response) if self._settings.hide_users else response)
