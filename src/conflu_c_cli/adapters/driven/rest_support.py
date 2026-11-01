"""What the REST adapter and its feature areas share: building a request address, reading Confluence's own explanation of a refusal,
keeping secrets out of what is shown, and a multipart body. The areas (`rest_*.py`) are mixins of `RestConfluenceGateway`."""
from __future__ import annotations

import re
import urllib.parse
from typing import Any, Sequence

from ...domain.errors import UnavailableError

V2 = "/api/v2"  # the paths below the wiki address, as the OpenAPI documents write them (see docs/reference/compatibility.md)
V1 = "/rest/api"


def quote(value: str) -> str:
    """One segment of a path: everything that is not unreserved is percent-encoded, and so is a segment of nothing but dots (`..`), which a server
    or a proxy may read as a step up out of the path."""
    text = urllib.parse.quote(str(value), safe="")
    return text.replace(".", "%2E") if text and set(text) == {"."} else text


def request_target(path: str) -> str:
    """A path and query as a person typed them, made fit for a request line: the fragment goes (no server ever sees one),
    a space, a quote or a non-ASCII character becomes %XX, and an escape that is there already stays as it is."""
    path = re.sub(r"%(?![0-9A-Fa-f]{2})", "%25", path.split("#", 1)[0])
    return urllib.parse.quote(path, safe="%!$&'()*+,/:;=?@[]~-._")


def query(**params: Any) -> str:
    """A query string from the parameters that have a value (`True` becomes `true`)."""
    pairs = []
    for name, value in params.items():
        if value is None or value == "" or (isinstance(value, (list, tuple)) and not value):
            continue
        text = "true" if value is True else "false" if value is False else ",".join(map(str, value)) if isinstance(value, (list, tuple)) else str(value)
        pairs.append((name.replace("_", "-"), text))
    return urllib.parse.urlencode(pairs, quote_via=urllib.parse.quote)


def messages(body: Any) -> str:
    """Confluence's own explanation of a refusal, in the shapes both APIs use."""
    if not isinstance(body, dict):
        return ""
    parts: list[str] = []
    errors = body.get("errors")
    if isinstance(errors, list):
        for item in errors:
            if isinstance(item, dict):
                text = item.get("detail") or item.get("title") or item.get("message")
                if isinstance(text, dict):
                    text = text.get("translation") or text.get("key")
                if text:
                    parts.append(str(text))
            elif item:
                parts.append(str(item))
    data = body.get("data")
    if isinstance(data, dict) and isinstance(data.get("errors"), list):
        for item in data["errors"]:
            text = item.get("message") if isinstance(item, dict) else item
            if isinstance(text, dict):
                text = text.get("translation") or text.get("key")
            if text:
                parts.append(str(text))
    for key in ("message", "reason"):
        if isinstance(body.get(key), str) and body[key] and body[key] not in parts:
            parts.append(body[key])
    return "; ".join(dict.fromkeys(parts))


def without_secrets(value: Any, secrets: Sequence[str]) -> Any:
    """The value with every occurrence of a secret replaced, in strings at any depth."""
    usable = [secret for secret in secrets if len(secret) >= 6]  # too short to be a secret; replacing it would only damage the text
    if not usable:
        return value
    if isinstance(value, str):
        for secret in usable:
            value = value.replace(secret, "********")
        return value
    if isinstance(value, dict):
        return {key: without_secrets(item, usable) for key, item in value.items()}
    if isinstance(value, list):
        return [without_secrets(item, usable) for item in value]
    return value


def multipart(fields: dict[str, str], filename: str, data: bytes) -> tuple[bytes, str]:
    """A multipart/form-data body with the text fields and one file; its content type carries the boundary."""
    import mimetypes
    import uuid  # an upload is the only call that needs them

    boundary = "----conflu" + uuid.uuid4().hex
    safe_name = re.sub(r'[\r\n"]', "_", filename)
    guessed = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    parts: list[bytes] = []
    for name, value in fields.items():
        # The comment is text of any language: Confluence asks for it to be sent as `text/plain; charset=utf-8`, else it may read the bytes in another encoding.
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{value}\r\n'.encode("utf-8")
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{safe_name}"\r\nContent-Type: {guessed}\r\n\r\n'.encode("utf-8")
        + data
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def next_cursor(data: Any) -> str:
    """The cursor of the next piece of a v2 list: the `cursor` parameter of `_links.next`, or an empty text on the last one. A link that no parser
    takes is an error: a list that cannot go on must not be taken for a list that ended."""
    links = data.get("_links") if isinstance(data, dict) else None
    link = links.get("next") if isinstance(links, dict) else None
    if not isinstance(link, str) or not link:
        return ""
    try:
        values = urllib.parse.parse_qs(urllib.parse.urlsplit(link).query).get("cursor") or [""]
    except ValueError:
        raise UnavailableError(
            "Confluence answered with a link to the next piece of the list that cannot be read.",
            hint="Try again. If it stays, something between you and Confluence is changing its answers.",
        ) from None
    return values[0]
