"""Which Confluence Cloud REST APIs this CLI is written for, and what to say about it.

Confluence Cloud has no release number to compare with: Atlassian changes the service in place and publishes two OpenAPI documents.
The CLI is written against them (v2 is the default; v1 is used only where v2 has no equivalent), and the tests check every call it sends
against them (see `tests/support/conformance.py` and `docs/reference/compatibility.md`).
"""
from __future__ import annotations

from typing import Any

V2_VERSION = "2.0.0"  # `info.version` of the v2 document
V1_VERSION = "1.0.0"  # `info.version` of the v1 document
DOCUMENTS_READ = "2026-10-30"
V2_BASE = "/wiki/api/v2"
V1_BASE = "/wiki/rest/api"
V2_GUIDE = "https://developer.atlassian.com/cloud/confluence/rest/v2/intro/"
V1_GUIDE = "https://developer.atlassian.com/cloud/confluence/rest/v1/intro/"


def facts() -> dict[str, Any]:
    """What `conflu version --json` says under `confluenceCloud`."""
    return {
        "default": "v2",
        "documentsRead": DOCUMENTS_READ,
        "apis": {
            "v2": {"base": V2_BASE, "version": V2_VERSION, "guide": V2_GUIDE},
            "v1": {"base": V1_BASE, "version": V1_VERSION, "guide": V1_GUIDE},
        },
    }


def written_for() -> str:
    return f"the documents of {DOCUMENTS_READ} (v2 {V2_VERSION}, v1 {V1_VERSION})"
