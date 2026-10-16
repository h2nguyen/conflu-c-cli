"""Settings: every key the CLI understands, with its type, default and meaning.

The definitions are the single source for parsing, `conflu config show` and the generated reference.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from ..domain.errors import ConfigError


@dataclass(frozen=True)
class SettingDef:
    name: str
    attr: str
    kind: str  # str | bool | int | float
    default: Any
    description: str
    secret: bool = False
    personal: bool = False
    example: str = ""


SETTING_DEFS: tuple[SettingDef, ...] = (
    SettingDef("CONFLUENCE_BASE_URL", "base_url", "str", "", "Address of the Confluence Cloud site, ending in /wiki. The /wiki is added when it is left out of an atlassian.net address.", example="https://example.atlassian.net/wiki"),
    SettingDef("CONFLUENCE_EMAIL", "email", "str", "", "E-mail address of the Atlassian account that owns the API token. It is shown masked.", personal=True, example="user@example.com"),
    SettingDef("CONFLUENCE_API_TOKEN", "api_token", "str", "", "API token of that account. Save it with `conflu setup-token`; it is never printed.", secret=True),
    SettingDef("CONFLUENCE_SPACE", "space", "str", "", "Current space; used when --space is left out. Set it with `conflu use KEY`.", example="ENG"),
    SettingDef("CONFLUENCE_CA_BUNDLE", "ca_bundle", "str", "", "PEM file with certificate authorities to trust in addition to the system store: a private company CA, or a public one that the system store lacks. Empty: the system store alone.", example="C:/certs/company-ca.pem"),
    SettingDef("CONFLUENCE_TLS_STRICT", "tls_strict", "bool", False, "Apply Python's strict X.509 checks on top of the normal verification of the certificate chain and the host name, which always happen. Off by default: the TLS-inspecting proxy of many companies issues certificates that fail them (`Missing Authority Key Identifier`)."),
    SettingDef("CONFLUENCE_INSECURE", "insecure", "bool", False, "Do not verify TLS certificates. Only as a temporary diagnostic."),
    SettingDef("CONFLUENCE_ALLOW_HTTP", "allow_http", "bool", False, "Allow a plain http:// CONFLUENCE_BASE_URL. The credentials then travel unencrypted, so use it only on an isolated network. Addresses on this computer (localhost) are always allowed."),
    SettingDef("CONFLUENCE_HIDE_USERS", "hide_users", "bool", False, "Policy: never print people (names, account ids, e-mail addresses). `--with-users` is then refused."),
    SettingDef("CONFLUENCE_CONNECT_TIMEOUT", "connect_timeout", "float", 10.0, "Seconds to wait for the connection."),
    SettingDef("CONFLUENCE_MAX_TIME", "max_time", "float", 120.0, "Seconds to wait for an answer."),
    SettingDef("CONFLUENCE_RETRY", "retry", "int", 2, "Retries of a read request after a network error or HTTP 429/502/503/504. Writes are never retried."),
    SettingDef("CONFLUENCE_OUTPUT", "output", "str", "text", "`json` makes every command that supports it print JSON, as if --json was given. Meant for scripts and agents.", example="json"),
)

_BY_NAME = {definition.name: definition for definition in SETTING_DEFS}
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"", "0", "false", "no", "off"}


def setting_definition(name: str) -> SettingDef | None:
    return _BY_NAME.get(name)


def is_local_host(host: str) -> bool:
    """An address on this computer: what is sent to it does not leave it."""
    return host == "localhost" or host == "::1" or host.startswith("127.")


def host_of(url: str) -> str:
    """The host name of a web address, without credentials, port and brackets."""
    match = re.match(r"^[a-z]+://(?:[^/@]*@)?(\[[^\]]*\]|[^/:?#]*)", url.strip(), re.IGNORECASE)
    return match.group(1).strip("[]").lower() if match else ""


def wiki_root(url: str) -> str:
    """The address of the wiki. An atlassian.net address, or the one of the API gateway that tokens with scopes use,
    gets the `/wiki` that people leave out."""
    text = url.strip().rstrip("/")
    if re.match(r"^https?://[^/?#]+$", text, re.IGNORECASE) and host_of(text).endswith(".atlassian.net"):
        return text + "/wiki"
    if re.match(r"^https://api\.atlassian\.com/ex/confluence/[^/?#]+$", text, re.IGNORECASE):
        return text + "/wiki"
    return text


def mask_secret(value: str) -> str:
    return "(not set)" if not value else f"******** ({len(value)} characters)"


def mask_personal(value: str) -> str:
    """`u***@example.com` for an e-mail address: enough to recognise it, not to use it."""
    if not value:
        return "(not set)"
    local, separator, domain = value.partition("@")
    return f"{local[:1]}***@{domain}" if separator and local else "***"


def _parse(definition: SettingDef, raw: str) -> Any:
    text = (raw or "").strip()
    if definition.kind == "str":
        return text if text or not definition.default else definition.default
    if definition.kind == "bool":
        lowered = text.lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
        raise ConfigError(f"{definition.name} must be true or false, not '{text}'.")
    if definition.kind == "int":
        try:
            return int(text) if text else definition.default
        except ValueError as error:
            raise ConfigError(f"{definition.name} must be a whole number, not '{text}'.") from error
    try:
        return float(text) if text else definition.default
    except ValueError as error:
        raise ConfigError(f"{definition.name} must be a number, not '{text}'.") from error


@dataclass(frozen=True)
class Settings:
    base_url: str = ""
    email: str = field(default="", repr=False)
    api_token: str = field(default="", repr=False)
    space: str = ""
    ca_bundle: str = ""
    tls_strict: bool = False
    insecure: bool = False
    allow_http: bool = False
    hide_users: bool = False
    connect_timeout: float = 10.0
    max_time: float = 120.0
    retry: int = 2
    output: str = "text"

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> "Settings":
        parsed = {definition.attr: _parse(definition, values.get(definition.name, "")) for definition in SETTING_DEFS}
        if parsed["output"] not in ("text", "json"):
            raise ConfigError(f"CONFLUENCE_OUTPUT must be text or json, not '{parsed['output']}'.")
        for name, attr in (("CONFLUENCE_CONNECT_TIMEOUT", "connect_timeout"), ("CONFLUENCE_MAX_TIME", "max_time")):
            if not math.isfinite(parsed[attr]) or parsed[attr] <= 0:
                raise ConfigError(f"{name} must be a number of seconds greater than 0, not '{values.get(name, '')}'.")
        if parsed["retry"] < 0:
            raise ConfigError(f"CONFLUENCE_RETRY must be 0 or more, not '{values.get('CONFLUENCE_RETRY', '')}'.")
        return cls(**parsed)

    @property
    def wiki_url(self) -> str:
        return wiki_root(self.base_url)

    @property
    def json_by_default(self) -> bool:
        return self.output == "json"
