"""What Confluence's JSON means for folders, whiteboards, databases and smart links, and where content sits in the tree: the answers as domain objects."""
from __future__ import annotations

from typing import Any

from ...domain.model import PageRef, TreeNode, space_key_from_link
from ...domain.structure import Container, DatabaseEntry, DatabaseField, DatabaseView, FieldValue
from .confluence_mapper import user_from_id, version_from

_LIST_KEYS = {  # the key that names each item of a cell that holds a list of references
    "select": "label",
    "user": "accountId",
    "attachment": "mediaId",
    "jiraIssue": "key",
    "pageLink": "contentId",
    "entryLink": "entryId",
}


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def container_from(data: dict[str, Any], kind: str, fallback_base: str = "") -> Container:
    """A folder, a whiteboard, a database or a smart link as the single-item calls of API v2 describe it."""
    links = _object(data.get("_links"))
    webui = _text(links.get("webui"))
    base = _text(links.get("base")) or fallback_base
    parent_id = _text(data.get("parentId"))
    return Container(
        id=_text(data.get("id")),
        type=kind,
        title=_text(data.get("title")),
        status=_text(data.get("status")),
        space_id=_text(data.get("spaceId")),
        space_key=space_key_from_link(webui),
        parent_id=parent_id,
        parent_type=_text(data.get("parentType")) if parent_id else "",
        position=data.get("position") if isinstance(data.get("position"), int) else None,
        created=_text(data.get("createdAt")),
        version=version_from(data.get("version")),
        author=user_from_id(data.get("authorId")),
        owner=user_from_id(data.get("ownerId")),
        url=base.rstrip("/") + webui if webui else "",
        embed_url=_text(data.get("embedUrl")),
        raw=data,
    )


def child_from(data: dict[str, Any], parent_id: str) -> TreeNode:
    """One item of `direct-children`: it names no parent, because the call was made for one."""
    return TreeNode(
        id=_text(data.get("id")),
        title=_text(data.get("title")),
        type=_text(data.get("type")) or "page",
        parent_id=parent_id,
        depth=1,
        status=_text(data.get("status")),
        position=data.get("childPosition") if isinstance(data.get("childPosition"), int) else None,
    )


def ancestor_from(data: dict[str, Any]) -> PageRef:
    """An ancestor has an id and a type and no title: the title is asked for separately."""
    return PageRef(_text(data.get("id")), "", _text(data.get("type")) or "page")


def field_from(data: dict[str, Any]) -> DatabaseField:
    options = _object(data.get("settings")).get("options")
    labels = tuple(_text(_object(item).get("label")) for item in options) if isinstance(options, list) else ()
    return DatabaseField(_text(data.get("id")), _text(data.get("name")), _text(data.get("type")), _text(data.get("description")), labels)


def view_from(data: dict[str, Any]) -> DatabaseView:
    return DatabaseView(_text(data.get("id")), _text(data.get("name")), _text(data.get("type")))


def value_from(data: Any) -> FieldValue:
    """One cell of an entry. The cells are typed objects; what they hold is reduced to what `FieldValue` documents."""
    item = _object(data)
    kind = _text(item.get("type"))
    if kind in ("text", "aiSummary"):
        raw = item.get("plain")
    else:
        raw = item.get("value")
    if raw is None:
        return FieldValue(kind)
    if kind == "hyperlink" and isinstance(raw, list):
        return FieldValue(kind, [{"url": _text(_object(entry).get("url")), "label": _text(_object(entry).get("label"))} for entry in raw])
    if kind in _LIST_KEYS and isinstance(raw, list):
        return FieldValue(kind, [_text(_object(entry).get(_LIST_KEYS[kind])) for entry in raw])
    if kind == "checkbox":
        return FieldValue(kind, raw if isinstance(raw, bool) else None)
    return FieldValue(kind, _text(raw) if isinstance(raw, (str, int, float)) else None)


def entry_from(data: dict[str, Any]) -> DatabaseEntry:
    values = _object(data.get("values"))
    return DatabaseEntry(_text(data.get("id")), _text(data.get("databaseId")), {str(key): value_from(item) for key, item in values.items()})
