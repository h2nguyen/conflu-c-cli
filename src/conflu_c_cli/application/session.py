"""Use cases around the CLI's own configuration and a quick connection check."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping

from ..domain.errors import UnavailableError, UsageError, ValidationError
from ..domain.model import Space, User, parse_space_key
from ..domain.structure import shown_key
from .ports_local import ConfigStore
from .settings import PROFILE_DEFAULTS, SETTING_DEFS, Settings, mask_personal, mask_secret, setting_definition, shown_address

if TYPE_CHECKING:
    from .ports import ConfluenceGateway  # the gateway is only handed on: a command that never asks Confluence does not load its code

_ADDRESS = re.compile(r"^https?://[^/@\s?#]+(/[^\s?#]*)?$", re.IGNORECASE)


def _is_email(text: str) -> bool:
    """One `@` with something before it, and behind it a name with a dot that has a character on each side; no blank anywhere. The shape that
    `^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$` describes, without its backtracking: that pattern splits a long run of dots in every way."""
    local, at, domain = text.partition("@")
    return bool(local) and bool(at) and "@" not in domain and "." in domain[1:-1] and not any(char.isspace() for char in text)


@dataclass(frozen=True)
class ConfigEntry:
    name: str
    value: str
    source: str  # environment | config file | profile | default
    description: str
    secret: bool = False


def _check_value(name: str, value: str) -> None:
    """The settings that would be dangerous or useless when wrong are checked when they are set. A refusal never repeats an address
    that holds an @: a password in it would end up on the screen and in the log of whoever reads it."""
    text = value.strip()
    if name == "CONFLUENCE_BASE_URL":
        if re.match(r"^https?://[^/]*@", text, re.IGNORECASE):
            raise ValidationError(
                "The address must not contain a user name or password.",
                hint="Credentials are kept apart: `conflu config set CONFLUENCE_EMAIL ...` and `conflu setup-token`.",
            )
        if "@" in text:
            raise ValidationError(
                "The address has an @ after the host name, which looks like a user name or password with a / ? or # in it: it was not saved.",
                hint="Credentials are kept apart: `conflu config set CONFLUENCE_EMAIL ...` and `conflu setup-token`.",
            )
        if not _ADDRESS.match(text):
            raise ValidationError(f"Not a web address: {value}", hint="It must look like https://example.atlassian.net/wiki (no query, no fragment).")
    elif name == "CONFLUENCE_EMAIL" and text and not _is_email(text):
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
        implied = PROFILE_DEFAULTS.get(self._settings.profile, {})  # what the profile sets where the setting itself is not set
        rows = []
        for definition in SETTING_DEFS:
            name = definition.name
            if self._environ.get(name):
                value, source = self._environ[name], "environment"
            elif name in stored and (stored[name].strip() or name not in implied):
                value, source = stored[name], "config file"
            elif name in implied:
                value, source = implied[name], "profile"
            else:
                value, source = str(definition.default), "default"
            if definition.kind == "bool" and source == "default":
                value = "false" if not definition.default else "true"
            if definition.secret:
                shown = mask_secret(value)
            elif definition.personal and value:
                shown = mask_personal(value)
            elif name == "CONFLUENCE_BASE_URL":
                shown = shown_address(value)
            elif name == "CONFLUENCE_SPACE":
                shown = shown_key(value)  # the key of a personal space is the account id of its owner: `[hidden]`, as `use` and `spaces` print it
            else:
                shown = value
            rows.append(ConfigEntry(name, shown, source, definition.description, definition.secret))
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
        try:
            saved = parse_space_key(space.key)  # what the server answers is held to the rule that what a person types is: it is written into the file
        except ValidationError:
            raise UnavailableError(
                "Confluence answered with a space whose key cannot be saved as the current space.",
                hint="Nothing was saved. The key of a space is letters and digits (and ~ : _ . -); if the answer is wrong, something between you and Confluence changed it.",
            ) from None
        self._store.set("CONFLUENCE_SPACE", saved)
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
