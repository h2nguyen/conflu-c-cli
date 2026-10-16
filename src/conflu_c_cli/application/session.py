"""Use cases around the CLI's own configuration and a quick connection check."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from ..domain.errors import UsageError, ValidationError
from ..domain.model import Space, User, parse_space_key
from .ports import ConfigStore, ConfluenceGateway
from .settings import SETTING_DEFS, Settings, mask_personal, mask_secret, setting_definition

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ADDRESS = re.compile(r"^https?://[^/@\s?#]+(/[^\s?#]*)?$", re.IGNORECASE)


@dataclass(frozen=True)
class ConfigEntry:
    name: str
    value: str
    source: str  # environment | config file | default
    description: str
    secret: bool = False


def _check_value(name: str, value: str) -> None:
    """The settings that would be dangerous or useless when wrong are checked when they are set."""
    text = value.strip()
    if name == "CONFLUENCE_BASE_URL":
        if re.match(r"^https?://[^/]*@", text, re.IGNORECASE):
            raise ValidationError(
                "The address must not contain a user name or password.",
                hint="Credentials are kept apart: `conflu config set CONFLUENCE_EMAIL ...` and `conflu setup-token`.",
            )
        if not _ADDRESS.match(text):
            raise ValidationError(f"Not a web address: {value}", hint="It must look like https://example.atlassian.net/wiki (no query, no fragment).")
    elif name == "CONFLUENCE_EMAIL" and text and not _EMAIL.match(text):
        raise ValidationError(f"Not an e-mail address: {value}", hint="Use the e-mail address of your Atlassian account.")


class ConfigService:
    def __init__(self, store: ConfigStore, settings: Settings, environ: Mapping[str, str], gateway: ConfluenceGateway) -> None:
        self._store = store
        self._settings = settings
        self._environ = environ
        self._gateway = gateway

    @property
    def path(self) -> str:
        return self._store.path

    def entries(self) -> list[ConfigEntry]:
        stored = self._store.load()
        rows = []
        for definition in SETTING_DEFS:
            if self._environ.get(definition.name):
                value, source = self._environ[definition.name], "environment"
            elif definition.name in stored:
                value, source = stored[definition.name], "config file"
            else:
                value, source = str(definition.default), "default"
            if definition.kind == "bool" and source == "default":
                value = "false" if not definition.default else "true"
            if definition.secret:
                shown = mask_secret(value)
            elif definition.personal and value:
                shown = mask_personal(value)
            else:
                shown = value
            rows.append(ConfigEntry(definition.name, shown, source, definition.description, definition.secret))
        return rows

    def set_value(self, name: str, value: str) -> None:
        definition = setting_definition(name)
        if definition is None:
            known = ", ".join(sorted(item.name for item in SETTING_DEFS if not item.secret))
            raise UsageError(f"Unknown setting: {name}", hint=f"Known settings: {known}")
        if definition.secret:
            raise UsageError(
                f"{name} is a secret and is not set on the command line (it would stay in the shell history).",
                hint="Use `conflu setup-token`.",
            )
        _check_value(name, value)
        Settings.from_mapping({name: value})  # rejects a value of the wrong type
        self._store.set(name, value.strip())

    def unset_value(self, name: str) -> bool:
        if setting_definition(name) is None:
            raise UsageError(f"Unknown setting: {name}")
        return self._store.unset(name)

    def save_token(self, token: str) -> None:
        text = token.strip()
        if not text:
            raise ValidationError("The token is empty.", hint="Create an API token at https://id.atlassian.com/manage-profile/security/api-tokens and paste it.")
        if re.search(r"\s", text):
            raise ValidationError("The token contains spaces or line breaks.", hint="Paste only the token itself.")
        self._store.set("CONFLUENCE_API_TOKEN", text)

    def remove_token(self) -> bool:
        return self._store.unset("CONFLUENCE_API_TOKEN")

    def select_space(self, key: str) -> Space:
        space = self._gateway.get_space(parse_space_key(key))  # proves access before saving
        self._store.set("CONFLUENCE_SPACE", space.key)
        return space

    def current_space(self) -> str:
        return self._settings.space

    def clear_space(self) -> bool:
        return self._store.unset("CONFLUENCE_SPACE")


@dataclass(frozen=True)
class PingResult:
    ok: bool
    user: User | None


class Ping:
    def __init__(self, gateway: ConfluenceGateway, settings: Settings) -> None:
        self._gateway = gateway
        self._settings = settings

    def execute(self, *, quiet: bool = False) -> PingResult:
        user = self._gateway.current_user()
        return PingResult(True, None if quiet or self._settings.hide_users else user)
