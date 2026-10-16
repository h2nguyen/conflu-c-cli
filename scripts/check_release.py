#!/usr/bin/env python3
"""Checks that a release is consistent. Run it before tagging a version.

    python scripts/check_release.py

It checks that VERSION, the code, the changelog and the README agree, that the generated reference is
current, that the skill names every command, that every link in the documentation leads somewhere, and that
the community files GitHub looks for (license, contributing guide, code of conduct, security policy, templates)
are there. Exit code 0: ready. 1: it lists what to fix.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import generate_docs  # noqa: E402
from conflu_c_cli.adapters.driving.cli.registry import all_commands  # noqa: E402
from conflu_c_cli.version import __version__  # noqa: E402

VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
CODE = re.compile(r"```.*?```|`[^`\n]*`", re.DOTALL)  # a link that is only shown as an example, inside code, leads nowhere on purpose
ROOT_DOCUMENTS = ("CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md")
COMMUNITY_FILES = ("LICENSE", *ROOT_DOCUMENTS, ".github/PULL_REQUEST_TEMPLATE.md")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def version_problems() -> list[str]:
    problems = []
    declared = read(ROOT / "VERSION").strip()
    if not VERSION_PATTERN.match(declared):
        problems.append(f"VERSION must look like 1.2.3, not '{declared}'")
    if declared != __version__:
        problems.append(f"VERSION says {declared}, src/conflu_c_cli/version.py says {__version__}")
    return problems


def changelog_problems() -> list[str]:
    text = read(ROOT / "CHANGELOG.md")
    entries = re.findall(r"^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})$", text, re.MULTILINE)
    if not entries:
        return ["CHANGELOG.md has no '## [x.y.z] - YYYY-MM-DD' entry"]
    problems = []
    if entries[0][0] != __version__:
        problems.append(f"the newest CHANGELOG.md entry is {entries[0][0]}, the version is {__version__}")
    if "## [Unreleased]" not in text:
        problems.append("CHANGELOG.md lost its '## [Unreleased]' section")
    versions = [tuple(int(part) for part in version.split(".")) for version, _ in entries]
    if versions != sorted(versions, reverse=True):
        problems.append("CHANGELOG.md entries are not in descending version order")
    return problems


def generated_problems() -> list[str]:
    return [f"{path.relative_to(ROOT)} is out of date: run python scripts/generate_docs.py" for path in generate_docs.out_of_date()]


def skill_problems() -> list[str]:
    path = ROOT / "skills" / "conflu-c-cli" / "SKILL.md"
    if not path.is_file():
        return ["skills/conflu-c-cli/SKILL.md is missing"]
    text = read(path)
    problems = []
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return ["SKILL.md has no front matter"]
    fields = dict(line.split(":", 1) for line in match.group(1).splitlines() if ":" in line)
    if fields.get("name", "").strip() != "conflu-c-cli":
        problems.append("SKILL.md front matter needs `name: conflu-c-cli`")
    if len(fields.get("description", "").strip()) < 40:
        problems.append("SKILL.md front matter needs a useful `description`")
    body = text[match.end():]
    problems += [f"SKILL.md does not mention `conflu {command.name}`" for command in all_commands() if f"conflu {command.name}" not in body]
    return problems


def link_problems() -> list[str]:
    problems = []
    files = [ROOT / "README.md", ROOT / "CHANGELOG.md", ROOT / "skills" / "conflu-c-cli" / "SKILL.md", *sorted((ROOT / "docs").rglob("*.md"))]
    files += [ROOT / name for name in ROOT_DOCUMENTS if (ROOT / name).is_file()]  # a missing one is reported by community_problems
    for path in files:
        for target in LINK.findall(CODE.sub("", read(path))):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            location = target.split("#", 1)[0]
            if location and not (path.parent / location).exists():
                problems.append(f"{path.relative_to(ROOT)} links to {target}, which does not exist")
    return problems


def readme_problems() -> list[str]:
    text = read(ROOT / "README.md")
    needles = ("python install.py", "conflu doctor", "docs/how-to", "LICENSE", *ROOT_DOCUMENTS)
    return [f"README.md does not mention `{needle}`" for needle in needles if needle not in text]


def community_problems() -> list[str]:
    """GitHub's community profile lists a project without these files as incomplete."""
    problems = [f"{name} is missing" for name in COMMUNITY_FILES if not (ROOT / name).is_file()]
    forms = [path for path in sorted((ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.yml")) if path.name != "config.yml"]
    if not forms:
        problems.append(".github/ISSUE_TEMPLATE holds no issue form")
    for path in forms:
        for key in ("name", "description"):  # without both keys GitHub does not offer the form
            if not re.search(rf"^{key}:\s*\S", read(path), re.MULTILINE):
                problems.append(f".github/ISSUE_TEMPLATE/{path.name} has no `{key}:` key")
    return problems


def problems() -> list[str]:
    found: list[str] = []
    for check in (version_problems, changelog_problems, generated_problems, readme_problems, skill_problems, link_problems, community_problems):
        found += check()
    return found


def main() -> int:
    found = problems()
    for problem in found:
        print(f"- {problem}", file=sys.stderr)
    if found:
        print(f"{len(found)} problem(s). Not ready to release.", file=sys.stderr)
        return 1
    print(f"conflu-c-cli {__version__}: consistent, ready to release.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
