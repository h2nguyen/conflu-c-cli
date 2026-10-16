"""What Confluence's JSON means: the answers of the REST API as domain objects. The one place that knows their shape."""
from __future__ import annotations

import html
import re
from typing import Any

from ...domain.model import (
    Attachment,
    Comment,
    Label,
    Page,
    SearchHit,
    Space,
    TreeNode,
    User,
    VersionInfo,
    space_key_from_link,
)

_HIGHLIGHT = re.compile(r"@@@(?:end)?hl@@@")


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _number(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def results_of(data: Any) -> list[dict[str, Any]]:
    items = _object(data).get("results")
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def base_of(data: Any, fallback: str = "") -> str:
    """The address of the wiki as the answer states it (`_links.base`), else the one that was configured."""
    return _text(_object(_object(data).get("_links")).get("base")) or fallback


def user_from_id(account_id: Any) -> User | None:
    return User(account_id=_text(account_id)) if account_id else None


def user_from(item: Any) -> User | None:
    """A user as the older API and the bulk lookup describe it."""
    data = _object(item)
    if not data:
        return None
    return User(_text(data.get("accountId")), _text(data.get("displayName") or data.get("publicName")), _text(data.get("email")))


def version_from(item: Any) -> VersionInfo | None:
    data = _object(item)
    if not data:
        return None
    return VersionInfo(
        number=_number(data.get("number")),
        created=_text(data.get("createdAt")),
        message=_text(data.get("message")),
        minor_edit=bool(data.get("minorEdit")),
        author=user_from_id(data.get("authorId")),
    )


def label_from(item: dict[str, Any]) -> Label:
    return Label(_text(item.get("name")), _text(item.get("prefix")) or "global")


def storage_of(item: dict[str, Any]) -> str | None:
    """The body in storage format, or None when the answer has none."""
    body = _object(item.get("body"))
    storage = body.get("storage")
    if isinstance(storage, dict):
        return _text(storage.get("value"))
    return None


def page_from(data: dict[str, Any], fallback_base: str = "") -> Page:
    links = _object(data.get("_links"))
    webui = _text(links.get("webui"))
    base = _text(links.get("base")) or fallback_base
    return Page(
        id=_text(data.get("id")),
        title=_text(data.get("title")),
        status=_text(data.get("status")),
        space_id=_text(data.get("spaceId")),
        space_key=space_key_from_link(webui),
        parent_id=_text(data.get("parentId")),
        position=data.get("position") if isinstance(data.get("position"), int) else None,
        created=_text(data.get("createdAt")),
        version=version_from(data.get("version")),
        author=user_from_id(data.get("authorId")),
        owner=user_from_id(data.get("ownerId")),
        labels=[label_from(item) for item in results_of(data.get("labels"))],
        body=storage_of(data),
        url=base.rstrip("/") + webui if webui else "",
        raw=data,
    )


def space_from(data: dict[str, Any], fallback_base: str = "") -> Space:
    links = _object(data.get("_links"))
    webui = _text(links.get("webui"))
    description = _object(data.get("description"))
    plain = _object(description.get("plain")) or _object(description.get("view"))
    return Space(
        id=_text(data.get("id")),
        key=_text(data.get("key")),
        name=_text(data.get("name")),
        type=_text(data.get("type")),
        status=_text(data.get("status")),
        description=_text(plain.get("value")),
        homepage_id=_text(data.get("homepageId")),
        created=_text(data.get("createdAt")),
        url=(_text(links.get("base")) or fallback_base).rstrip("/") + webui if webui else "",
    )


def tree_node_from(data: dict[str, Any]) -> TreeNode:
    return TreeNode(
        id=_text(data.get("id")),
        title=_text(data.get("title")),
        type=_text(data.get("type")) or "page",
        parent_id=_text(data.get("parentId")),
        depth=_number(data.get("depth"), 1),
        status=_text(data.get("status")),
        position=data.get("childPosition") if isinstance(data.get("childPosition"), int) else None,
    )


def comment_from(data: dict[str, Any], kind: str) -> Comment:
    version = _object(data.get("version"))
    return Comment(
        id=_text(data.get("id")),
        kind=kind,
        updated=_text(version.get("createdAt")),
        body=storage_of(data) or "",
        version=_number(version.get("number"), 1),
        author=user_from_id(version.get("authorId")),
        parent_id=_text(data.get("parentCommentId")),
        resolution=_text(data.get("resolutionStatus")),
    )


def attachment_from(data: dict[str, Any]) -> Attachment:
    links = _object(data.get("_links"))
    return Attachment(
        id=_text(data.get("id")),
        title=_text(data.get("title")),
        media_type=_text(data.get("mediaType")),
        size=_number(data.get("fileSize")),
        created=_text(data.get("createdAt")),
        version=_number(_object(data.get("version")).get("number"), 1),
        page_id=_text(data.get("pageId")),
        download_link=_text(data.get("downloadLink") or links.get("download")),
        comment=_text(data.get("comment")),
    )


def attachment_from_content(data: dict[str, Any]) -> Attachment:
    """An attachment as the older content API describes it, which is what an upload answers with."""
    extensions = _object(data.get("extensions"))
    metadata = _object(data.get("metadata"))
    container = _object(data.get("container"))
    return Attachment(
        id=_text(data.get("id")),
        title=_text(data.get("title")),
        media_type=_text(extensions.get("mediaType") or metadata.get("mediaType")),
        size=_number(extensions.get("fileSize")),
        created=_text(_object(data.get("version")).get("when")),
        version=_number(_object(data.get("version")).get("number"), 1),
        page_id=_text(container.get("id")),
        download_link=_text(_object(data.get("_links")).get("download")),
        comment=_text(extensions.get("comment") or metadata.get("comment")),
    )


def _without_markers(text: Any) -> str:
    return _HIGHLIGHT.sub("", _text(text))


def _search_text(text: Any) -> str:
    """A title or an excerpt as the search answers it: with highlight markers and HTML-escaped (`Q&amp;A`)."""
    return html.unescape(_without_markers(text))


def _search_path(item: dict[str, Any], content: dict[str, Any]) -> str:
    """The parent pages of a hit from the top, as titles. The expanded ancestors have them; the breadcrumbs are a fallback."""
    titles = [_text(entry.get("title")) for entry in content.get("ancestors") or [] if isinstance(entry, dict)]
    if not any(titles):
        titles = [html.unescape(_text(entry.get("label"))) for entry in item.get("breadcrumbs") or [] if isinstance(entry, dict)]
    return " > ".join(title for title in titles if title)


def _search_labels(content: dict[str, Any]) -> tuple[str, ...]:
    results = _object(_object(content.get("metadata")).get("labels")).get("results") or []
    return tuple(dict.fromkeys(_text(entry.get("name")).lower() for entry in results if isinstance(entry, dict) and entry.get("name")))


def search_hit_from(item: dict[str, Any], base: str = "") -> SearchHit:
    content = _object(item.get("content"))
    container = _object(item.get("resultGlobalContainer"))
    relative = _text(item.get("url") or _object(content.get("_links")).get("webui"))
    space_key = _text(_object(content.get("space")).get("key")) or space_key_from_link(relative) or space_key_from_link(_text(container.get("displayUrl")))
    return SearchHit(
        id=_text(content.get("id")),
        type=_text(content.get("type") or item.get("entityType")),
        title=_text(content.get("title")) or _search_text(item.get("title")),  # the content's own title is not escaped
        space_key=space_key,
        url=base.rstrip("/") + relative if relative.startswith("/") else relative,
        excerpt=re.sub(r"\s+", " ", _search_text(item.get("excerpt"))).strip(),
        last_modified=_text(item.get("lastModified")),
        path=_search_path(item, content),
        labels=_search_labels(content),
        version=_number(_object(content.get("version")).get("number"), 0) or None,
    )
