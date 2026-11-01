"""Setting up the address of the site: the public tenant information. A mixin of `RestConfluenceGateway`, which provides `_transport` and
`_settings`.

`/_edge/tenant_info` is neither of the two REST APIs: it is in no OpenAPI document, it sits at the root of the host (not below `/wiki`) and
it is read without any credential. The conformance sweep names the one command that may ask for it (`setup`).
"""
from __future__ import annotations

import json
import re
import urllib.parse

from ...application.settings import host_of
from ...domain.errors import ConfigError, UnavailableError
from .http_transport import AnswerTooBig

# The calls of this area that use the v1 API, each with why v2 does not do (see docs/reference/compatibility.md).
V1_CALLS: dict[str, str] = {}

TENANT_INFO = "/_edge/tenant_info"
MAX_TENANT_INFO = 64 * 1024  # bytes; the real answer is one line
_CLOUD_ID = re.compile(r"[0-9A-Za-z-]{8,64}")
_NOT_CLOUD = "The address may not be a Confluence Cloud site. Check CONFLUENCE_BASE_URL: open it in a browser."


class RestSetup:
    def tenant_info(self, base_url: str) -> str:
        host = host_of(base_url)
        try:
            response = self._transport.get_public(base_url, TENANT_INFO, limit=MAX_TENANT_INFO)
        except AnswerTooBig:
            raise ConfigError(f"The answer of {host} is larger than 64 KiB: it is not the tenant information of a Confluence Cloud site.", hint=_NOT_CLOUD) from None
        status = response.status
        if 300 <= status < 400:
            try:
                elsewhere = urllib.parse.urlsplit(response.headers.get("location", "")).hostname
            except ValueError:  # a Location that no URL parser takes
                elsewhere = None
            where = f" to {elsewhere}" if elsewhere else ""
            raise ConfigError(
                f"{host} answered with a redirect (HTTP {status}){where} instead of its tenant information. It was not followed: nothing is sent to another host.",
                hint="Set CONFLUENCE_BASE_URL to the address where the site answers itself, then run `conflu setup --discover` again.",
            )
        if status == 429 or status >= 500:
            raise UnavailableError(f"{host} answered HTTP {status} when asked for its tenant information.", hint="Try again in a moment.")
        if status != 200:
            raise ConfigError(f"{host} has no tenant information (HTTP {status}).", hint=_NOT_CLOUD)
        try:
            data = json.loads(response.body.decode("utf-8"))
        except RecursionError:  # sixty thousand `[` fit into the limit of the answer, and the decoder gives up long before the end of them
            raise UnavailableError(
                f"The answer of {host} nests arrays or objects too deeply to be read: it is not the tenant information of a Confluence Cloud site.",
                hint=_NOT_CLOUD,
            ) from None
        except ValueError:  # not JSON, or not UTF-8
            data = None
        cloud_id = data.get("cloudId") if isinstance(data, dict) else None
        if not isinstance(cloud_id, str) or not _CLOUD_ID.fullmatch(cloud_id):
            raise ConfigError(f"The answer of {host} does not hold the cloud id of a Confluence Cloud site.", hint=_NOT_CLOUD)
        return cloud_id
