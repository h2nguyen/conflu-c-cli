"""`conflu doctor`: check the setup step by step and say how to fix what is wrong.

It can leave out the last request (`quick`) and can reuse the online checks of a recent successful run (`cached_for`). That is the one
thing the CLI remembers between two runs, and only a person who asks for it with `--cached` gets an answer from it: see `ports.Cache`.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Mapping

from ..domain.compat import written_for
from ..domain.errors import ConfluCliError
from ..domain.structure import shown_key
from .ports import Cache, Clock, ConfluenceGateway, Files
from .settings import Settings, host_of, is_local_host, wiki_root

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    hint: str = ""


@dataclass(frozen=True)
class DoctorRun:
    checks: list[Check]
    cached: bool = False  # the online checks come from an earlier run: nothing was asked of Confluence
    cached_at: str = ""


class Doctor:
    def __init__(
        self,
        gateway: ConfluenceGateway,
        settings: Settings,
        files: Files,
        config_path: str,
        runtime: Mapping[str, str],
        cache: Cache | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._gateway = gateway
        self._settings = settings
        self._files = files
        self._config_path = config_path
        self._runtime = runtime
        self._cache = cache
        self._clock = clock

    def execute(self, *, quick: bool = False, strict_privacy: bool = False) -> list[Check]:
        return self.run(quick=quick, strict_privacy=strict_privacy).checks

    def run(self, *, quick: bool = False, strict_privacy: bool = False, cached_for: float = 0.0) -> DoctorRun:
        """All checks. `quick` leaves out the check of the current space, so that Confluence is asked twice at most (the current user
        and the spaces); with `cached_for` seconds the online checks of a successful run that is not older are reused and nothing is
        asked of Confluence."""
        checks = [
            Check("runtime", OK, f"conflu-c-cli {self._runtime.get('version', '?')} on Python {self._runtime.get('python', '?')}"),
            self._config_file(),
            self._base_url(),
            self._email(),
            self._token(),
            self._tls(),
        ]
        launcher = self._launcher()
        if launcher is not None:
            checks.append(launcher)
        privacy = self._privacy(strict_privacy)
        if any(check.status == FAIL for check in checks):
            return DoctorRun([*checks, Check("connection", WARN, "skipped until the configuration above is fixed"), privacy])
        remembered = self._remembered(quick, cached_for)
        if remembered is not None:
            at, online = remembered
            return DoctorRun([*checks, *online, privacy], cached=True, cached_at=at)
        online = self._online(quick)
        self._remember(quick, online)
        return DoctorRun([*checks, *online, privacy])

    # -- what an earlier successful run left ------------------------------------------------------

    def _cache_key(self, quick: bool) -> str:
        """What a remembered run was about: the site, the account, the current space, the TLS settings and the version of the program, and
        whether it was the quick form, signed with the token as the key (an HMAC, as the anchors of comments are): another token is another
        key, and the token itself is never hashed, so the file name tells nothing about it."""
        settings = self._settings
        identity = "|".join(
            [
                settings.base_url,
                settings.email,
                settings.space,
                settings.ca_bundle,
                str(settings.insecure),
                str(settings.tls_strict),
                self._runtime.get("version", ""),
                "quick" if quick else "full",
            ]
        )
        return hmac.new(settings.api_token.encode("utf-8"), identity.encode("utf-8"), hashlib.sha256).hexdigest()[:16]

    def _remembered(self, quick: bool, max_age: float) -> tuple[str, list[Check]] | None:
        if self._cache is None or max_age <= 0:
            return None
        text = self._cache.get("doctor", self._cache_key(quick), max_age)
        try:
            record = json.loads(text) if text else None
            online = [Check(**item) for item in record["checks"]]
            if not online or any(check.status not in (OK, WARN) for check in online):  # a run with a failure is never kept: a record with one is not ours
                return None
            return str(record["at"]), online
        except (ValueError, KeyError, TypeError, RecursionError):  # a record that is not ours (or nests deeper than the decoder reads) is a run that was never remembered
            return None

    def _remember(self, quick: bool, online: list[Check]) -> None:
        """Only checks are kept, never the token or a person; and a run in which something failed is not worth reusing."""
        if self._cache is None or any(check.status == FAIL for check in online):
            return
        at = self._clock.now().isoformat(timespec="seconds") if self._clock else ""
        record = {"at": at, "checks": [{"name": c.name, "status": c.status, "detail": c.detail, "hint": c.hint} for c in online]}
        self._cache.put("doctor", self._cache_key(quick), json.dumps(record))

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
        if "@" in url:  # in the host part a user name and password; after it, a password with a / ? or # in it. Never repeated here.
            return Check("base url", FAIL, "CONFLUENCE_BASE_URL contains a user name or password (or an @ that looks like one)", "Take it out: the e-mail address and the token are set apart.")
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
                "API tokens are not accepted on a custom domain of a Confluence Cloud site. If the connection fails with 401 or 403, run "
                f"`conflu setup --discover`: it reads https://{host}/_edge/tenant_info (public: no credential is sent) and proposes to set "
                "CONFLUENCE_BASE_URL to https://api.atlassian.com/ex/confluence/CLOUD_ID. By hand: open that address in a browser and copy its cloudId.",
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

    def _launcher(self) -> Check | None:
        """Whether the program is found by name. Only when the runtime says (the installed program does): an agent that has to
        start `python ...conflu.py` by hand has found out the hard way. A local check: nothing is asked of Confluence."""
        launcher = self._runtime.get("launcher")
        if launcher is None:
            return None
        if launcher:
            batch = launcher.lower().endswith((".cmd", ".bat"))  # the one that a program that passes an argument list must not start
            return Check("launcher", OK, f"`conflu` is found on the PATH: {launcher}", self._program_note() if batch else "")
        program = self._runtime.get("program", "")
        installer = self._runtime.get("install_script", "")
        fix = f'python "{installer}" --bin-dir DIR' if installer else "python install.py --bin-dir DIR, run in the source folder of conflu-c-cli,"
        return Check(
            "launcher",
            WARN,
            "`conflu` is not found on the PATH of this shell" + (f" (this run was started as {program})" if program else ""),
            f"Put the launcher in a folder that is on the PATH: {fix} (DIR: a folder from your PATH), or add the folder of the launcher to the PATH. {self._program_note()}",
        )

    def _program_note(self) -> str:
        """What a program (an agent harness) runs instead of the launcher, and why: `conflu.cmd` forwards `%*`, and cmd.exe has split the command
        line before a batch file runs, so an argument with a quote in it, passed in an argument list, can run a second command."""
        entry = self._runtime.get("entry", "")
        command = f'python "{entry}" ARGS' if entry else 'python "<install folder>\\conflu.py" ARGS'
        return (
            f"On Windows, a program that starts commands from an argument list (an agent harness) should not run a launcher but `{command}`: cmd.exe splits "
            "the command line before `conflu.cmd` runs, so an argument that holds a quote can run a second command. The launchers are for people at a shell."
        )

    def _online(self, quick: bool = False) -> list[Check]:
        try:
            self._gateway.current_user()
        except ConfluCliError as error:
            return [Check("connection", FAIL, error.message, error.hint)]
        checks = [Check("connection", OK, "reachable, the credentials are accepted")]
        v2_answers = True
        try:
            spaces = self._gateway.list_spaces(limit=1)
            checks.append(Check("spaces", OK, "spaces can be read" if spaces.items else "spaces can be read, but none is visible to this account"))
        except ConfluCliError as error:
            v2_answers = False
            checks.append(Check("spaces", WARN, error.message, error.hint or "A token with scopes needs read:space:confluence and read:page:confluence."))
        checks.append(self._api(v2_answers))
        if quick:
            return checks
        if self._settings.space:
            shown = shown_key(self._settings.space)  # the key of a personal space is the account id of its owner: the check is printed and remembered in the cache
            try:
                self._gateway.get_space(self._settings.space)
                checks.append(Check("space", OK, f"{shown} is accessible"))
            except ConfluCliError as error:
                checks.append(Check("space", FAIL, f"{shown}: {error.message}", "Pick another with `conflu use KEY` or `conflu config unset CONFLUENCE_SPACE`."))
        else:
            checks.append(Check("space", WARN, "no current space", "Run `conflu use KEY` to avoid typing --space."))
        return checks

    def _api(self, v2_answers: bool) -> Check:
        """Which of the two APIs answered, from the two requests that were made anyway: the current user is v1, the list of spaces is v2."""
        if v2_answers:
            return Check("api", OK, f"REST API v2 and v1 answer; the CLI is written for {written_for()}")
        return Check(
            "api",
            WARN,
            f"REST API v1 answers and v2 does not (see `spaces`); the CLI is written for {written_for()}",
            "Most commands use v2 (/wiki/api/v2). Check that the address is a Confluence Cloud site (a Data Center site has no v2) and, for a token "
            "with scopes, that it may read spaces and pages.",
        )

    def _privacy(self, strict: bool = False) -> Check:
        profile = f" (profile {self._settings.profile})" if self._settings.profile else ""
        if self._settings.hide_users:
            return Check("privacy", OK, f"CONFLUENCE_HIDE_USERS=true: people are never printed{profile}")
        detail = "people can be shown (set CONFLUENCE_HIDE_USERS=true to forbid it)"
        if strict:
            return Check("privacy", FAIL, detail, "Set CONFLUENCE_HIDE_USERS=true, or CONFLUENCE_PROFILE=agent, so that people are never printed.")
        if self._settings.profile:
            return Check(
                "privacy",
                WARN,
                f"profile {self._settings.profile} is on, but people can still be shown: CONFLUENCE_HIDE_USERS is set to false",
                "Take that setting away so that the profile applies: conflu config unset CONFLUENCE_HIDE_USERS (and check the environment).",
            )
        return Check("privacy", OK, detail)
