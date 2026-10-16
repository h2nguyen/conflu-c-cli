"""`conflu doctor`: check the setup step by step and say how to fix what is wrong."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from ..domain.errors import ConfluCliError
from .ports import ConfluenceGateway, Files
from .settings import Settings, host_of, is_local_host, wiki_root

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    hint: str = ""


class Doctor:
    def __init__(self, gateway: ConfluenceGateway, settings: Settings, files: Files, config_path: str, runtime: Mapping[str, str]) -> None:
        self._gateway = gateway
        self._settings = settings
        self._files = files
        self._config_path = config_path
        self._runtime = runtime

    def execute(self) -> list[Check]:
        checks = [
            Check("runtime", OK, f"conflu-c-cli {self._runtime.get('version', '?')} on Python {self._runtime.get('python', '?')}"),
            self._config_file(),
            self._base_url(),
            self._email(),
            self._token(),
            self._tls(),
        ]
        if any(check.status == FAIL for check in checks):
            checks.append(Check("connection", WARN, "skipped until the configuration above is fixed"))
        else:
            checks.extend(self._online())
        checks.append(self._privacy())
        return checks

    def _config_file(self) -> Check:
        if self._files.exists(self._config_path):
            return Check("config file", OK, self._config_path)
        return Check(
            "config file",
            WARN,
            f"{self._config_path} does not exist",
            "Run `conflu config set CONFLUENCE_BASE_URL URL`, `conflu config set CONFLUENCE_EMAIL ADDRESS` and `conflu setup-token`.",
        )

    def _base_url(self) -> Check:
        url = self._settings.base_url
        example = "https://example.atlassian.net/wiki"
        if not url:
            return Check("base url", FAIL, "CONFLUENCE_BASE_URL is not set", f"Run `conflu config set CONFLUENCE_BASE_URL {example}`.")
        if not url.startswith(("http://", "https://")):
            return Check("base url", FAIL, "CONFLUENCE_BASE_URL must start with http:// or https://", "Include the scheme.")
        if re.match(r"^https?://[^/]*@", url, re.IGNORECASE):
            return Check("base url", FAIL, "CONFLUENCE_BASE_URL contains a user name or password", "Take it out: the e-mail address and the token are set apart.")
        if url.startswith("http://"):
            host = host_of(url)
            if is_local_host(host):
                return Check("base url", OK, "plain http, on this computer")
            if self._settings.allow_http:
                return Check("base url", WARN, "plain http, allowed by CONFLUENCE_ALLOW_HTTP: the credentials travel unencrypted", "Use https if the site offers it.")
            return Check(
                "base url",
                FAIL,
                "plain http: the CLI refuses to send the credentials unencrypted",
                "Use the https address, or on an isolated network `conflu config set CONFLUENCE_ALLOW_HTTP true`.",
            )
        used = wiki_root(url)
        host = host_of(used)
        if not (host.endswith(".atlassian.net") or host == "api.atlassian.com" or is_local_host(host)):
            return Check(
                "base url",
                WARN,
                f"{host} is not an atlassian.net address (a custom domain?)",
                "API tokens are not accepted on a custom domain of a Confluence Cloud site. If the connection fails with 401 or 403, open "
                f"https://{host}/_edge/tenant_info in a browser and set CONFLUENCE_BASE_URL to https://api.atlassian.com/ex/confluence/CLOUD_ID.",
            )
        if used != url.strip().rstrip("/"):
            return Check("base url", OK, f"https; {url} is used as {used}")
        return Check("base url", OK, "https")

    def _email(self) -> Check:
        if self._settings.email:
            return Check("email", OK, "set (not shown)")
        return Check("email", FAIL, "CONFLUENCE_EMAIL is not set", "Run `conflu config set CONFLUENCE_EMAIL user@example.com` with the address of your Atlassian account.")

    def _token(self) -> Check:
        if self._settings.api_token:
            return Check("token", OK, "set (not shown)")
        return Check("token", FAIL, "CONFLUENCE_API_TOKEN is not set", "Run `conflu setup-token`. Create the token at https://id.atlassian.com/manage-profile/security/api-tokens.")

    def _tls(self) -> Check:
        if self._settings.insecure:
            return Check("tls", WARN, "certificate checks are off (CONFLUENCE_INSECURE)", "Use CONFLUENCE_CA_BUNDLE for a company CA instead.")
        if self._settings.ca_bundle:
            if self._files.exists(self._settings.ca_bundle):
                return Check("tls", OK, "system certificate store plus the authorities in CONFLUENCE_CA_BUNDLE")
            return Check("tls", FAIL, f"CONFLUENCE_CA_BUNDLE does not exist: {self._settings.ca_bundle}", "Fix the path or unset it.")
        if self._settings.tls_strict:
            return Check("tls", OK, "system certificate store, strict X.509 checks on (CONFLUENCE_TLS_STRICT)")
        return Check("tls", OK, "system certificate store; the chain and the host name are verified, strict X.509 checks are off")

    def _online(self) -> list[Check]:
        try:
            self._gateway.current_user()
        except ConfluCliError as error:
            return [Check("connection", FAIL, error.message, error.hint)]
        checks = [Check("connection", OK, "reachable, the credentials are accepted")]
        try:
            spaces = self._gateway.list_spaces(limit=1)
            checks.append(Check("spaces", OK, "spaces can be read" if spaces.items else "spaces can be read, but none is visible to this account"))
        except ConfluCliError as error:
            checks.append(Check("spaces", WARN, error.message, error.hint or "A token with scopes needs read:space:confluence and read:page:confluence."))
        if self._settings.space:
            try:
                self._gateway.get_space(self._settings.space)
                checks.append(Check("space", OK, f"{self._settings.space} is accessible"))
            except ConfluCliError as error:
                checks.append(Check("space", FAIL, f"{self._settings.space}: {error.message}", "Pick another with `conflu use KEY` or `conflu config unset CONFLUENCE_SPACE`."))
        else:
            checks.append(Check("space", WARN, "no current space", "Run `conflu use KEY` to avoid typing --space."))
        return checks

    def _privacy(self) -> Check:
        if self._settings.hide_users:
            return Check("privacy", OK, "CONFLUENCE_HIDE_USERS=true: people are never printed")
        return Check("privacy", OK, "people can be shown (set CONFLUENCE_HIDE_USERS=true to forbid it)")
