"""The request bodies of the write operations.

One place builds them, so a dry run shows exactly what a real run sends.
"""
from __future__ import annotations

from typing import Any, Sequence


def storage_body(value: str) -> dict[str, str]:
    return {"representation": "storage", "value": value}


def create_page_payload(space_id: str, title: str, body: str, parent_id: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {"spaceId": space_id, "status": "current", "title": title}
    if parent_id:
        payload["parentId"] = parent_id
    payload["body"] = storage_body(body)
    return payload


def update_page_payload(
    page_id: str, title: str, body: str, version_number: int, message: str = "", status: str = "current"
) -> dict[str, Any]:
    """`version_number` is the number the page gets, which is the current one plus one."""
    version: dict[str, Any] = {"number": version_number}
    if message.strip():
        version["message"] = message.strip()
    return {"id": page_id, "status": status, "title": title, "body": storage_body(body), "version": version}


def title_payload(title: str, status: str = "current") -> dict[str, Any]:
    return {"status": status, "title": title}


def comment_payload(page_id: str, body: str, parent_comment_id: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {"pageId": page_id, "body": storage_body(body)}
    if parent_comment_id:
        payload["parentCommentId"] = parent_comment_id
    return payload


def label_payload(names: Sequence[str]) -> list[dict[str, str]]:
    return [{"prefix": "global", "name": name} for name in names]
