"""HTTP(S) to Confluence Cloud on the standard library: keep-alive, retries, TLS, gzip, and redirects for downloads.

It speaks bytes and status codes only. Turning a status into an error and a body into domain objects is the job of
`confluence_rest.py`.

`http.client`, `ssl` and `zlib` are imported when the first request is made: they cost about 60 ms, which a command that
never talks to Confluence (`help`, `version`, `how-to`) should not pay.
"""
from __future__ import annotations

import base64
import math
import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Mapping

from ...application.settings import Settings, is_local_host, shown_address, wiki_root
from ...domain.certificates import untrusted_chain_note
from ...domain.errors import ConfigError, UnavailableError, UsageError
from ...version import __version__

if TYPE_CHECKING:
    import http.client
    import ssl

_RETRY_STATUSES = (429, 502, 503, 504)
_MAX_RETRY_WAIT = 30.0  # seconds; Confluence may ask for longer, but a command line tool should not hang for minutes
# OpenSSL's reasons for "no authority that this program trusts vouches for the certificate": unable to get issuer
# certificate (2), the local issuer (20) or the leaf signature (21), a self-signed certificate (18) or one at the end of a
# chain (19).
_UNTRUSTED_ISSUER = (2, 18, 19, 20, 21)
_REDIRECTS = (301, 302, 303, 307, 308)
_MAX_REDIRECTS = 5
_UNSENDABLE = re.compile(r"[\x00-\x20\x7f]")  # what http.client refuses in the address of a request: a space, a control character
MAX_DOWNLOAD = 512 * 1024 * 1024  # bytes; a file is held in memory before it is written
MAX_RESPONSE = 64 * 1024 * 1024  # bytes of an ordinary answer, once decoded; real answers are a few MiB at most
MAX_GZIP_MEMBERS = 16  # a gzip body is a row of members, and what is left of the body is copied again for each one: 100 000 empty ones took minutes


def _size_text(count: int) -> str:
    return f"{count // (1024 * 1024)} MiB" if count >= 1024 * 1024 else f"{count} bytes"


class AnswerTooBig(UnavailableError):
    """The answer is larger than the limit of its request. It is an UnavailableError, with the same code and exit code; a request that
    expects a small answer can tell this one apart."""


def _too_big(limit: int) -> AnswerTooBig:
    return AnswerTooBig(
        f"The answer is larger than {_size_text(limit)}; it was not read.",
        hint="Download a file in the browser. For a list, ask for less: a narrower search or a smaller --limit.",
    )


def _gunzip(data: bytes, limit: int) -> bytes:
    """What `gzip.decompress` gives, but never more than `limit` bytes: a few kilobytes on the wire must not be able to
    grow into gigabytes in memory. The output is counted while it is produced. More than MAX_GZIP_MEMBERS members is a `zlib.error`:
    the loop copies the rest of the body once for every member, so a body of empty ones would take time that grows with its square."""
    import zlib

    pieces: list[bytes] = []
    total = 0
    members = 0
    while data:  # a gzip file may hold several members one after the other; NUL padding between them is allowed
        members += 1
        if members > MAX_GZIP_MEMBERS:
            raise zlib.error(f"the answer holds more than {MAX_GZIP_MEMBERS} gzip members")
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        pending = data
        while pending and not decoder.eof:
            piece = decoder.decompress(pending, 65536)
            total += len(piece)
            if total > limit:
                raise _too_big(limit)
            pieces.append(piece)
            pending = decoder.unconsumed_tail
        piece = decoder.flush()
        total += len(piece)
        if total > limit:
            raise _too_big(limit)
        pieces.append(piece)
        if not decoder.eof:
            raise EOFError("Compressed data ended before the end-of-stream marker was reached")
        data = decoder.unused_data.lstrip(b"\x00")
    return b"".join(pieces)


def _retry_delay(attempt: int, retry_after: str | None) -> float:
    """The server's `Retry-After` (whole seconds), else one second more for every attempt. A value that is not a finite number (an HTTP
    date, garbage, `nan`, `inf`) is ignored: `time.sleep(nan)` raises."""
    try:
        asked = float(retry_after) if retry_after else None
    except ValueError:
        asked = None
    if asked is None or not math.isfinite(asked):
        return float(attempt)
    return min(max(asked, 0.0), _MAX_RETRY_WAIT)


def _origin(scheme: str, host: str, port: int | None) -> tuple[str, str, int]:
    return scheme, host.lower(), port or (443 if scheme == "https" else 80)


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class HttpTransport:
    def __init__(
        self,
        settings: Settings,
        debug: Callable[[str], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._debug = debug or (lambda message: None)
        self._sleep = sleep
        self._connection: http.client.HTTPConnection | None = None
        self._site: tuple[str, str, int | None, str] | None = None

    # -- requests ---------------------------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        content_type: str = "application/json",
        headers: Mapping[str, str] | None = None,
        accept: str = "application/json",
        timeout: float | None = None,
        retries: int | None = None,
        limit: int | None = None,
    ) -> HttpResponse:
        """`path` is below the wiki address. Reads are retried after a network error or HTTP 429/502/503/504; writes never are."""
        scheme, host, port, prefix = self._target()
        limit = MAX_RESPONSE if limit is None else limit
        sent = {
            "Authorization": self._authorization(),
            "Accept": accept,
            "Accept-Encoding": "gzip",
            "User-Agent": f"conflu-c-cli/{__version__}",
        }
        if body is not None:
            sent["Content-Type"] = content_type
        sent.update(headers or {})
        attempts = 1 + max(self._settings.retry if retries is None else retries, 0) if method == "GET" else 1
        return self._send(scheme, host, port, method, prefix + path, sent, body, attempts, timeout, limit, shared=True)

    def download(self, path: str, *, timeout: float | None = None, limit: int | None = None) -> HttpResponse:
        """A file below the wiki address. Attachments are served by a media service on another host after a redirect:
        the redirect is followed, and the credentials go only to the host they were meant for. `limit` is the most that the caller takes (never
        more than MAX_DOWNLOAD): a longer file raises AnswerTooBig as soon as that is seen, and the rest of it is not read."""
        scheme, host, port, prefix = self._target()
        home = _origin(scheme, host, port)
        cap = min(limit, MAX_DOWNLOAD) if limit else MAX_DOWNLOAD
        response = self.request(
            "GET", path, accept="*/*", headers={"Accept-Encoding": "identity"}, timeout=timeout, limit=cap
        )
        here = f"{scheme}://{host}{f':{port}' if port else ''}{prefix}{path}"
        hops = 0
        while response.status in _REDIRECTS and response.headers.get("location"):
            hops += 1
            if hops > _MAX_REDIRECTS:
                raise UnavailableError("Confluence redirected the download too many times.", hint="Try again later.")
            try:
                here = urllib.parse.urljoin(here, response.headers["location"])
                parts = urllib.parse.urlsplit(here)
                target_port = parts.port  # a port that is no number raises here
            except ValueError:  # `Location: http://[`: what the answer says is the problem, not the address that was asked for
                raise UnavailableError(
                    "Confluence redirected the download to an address that cannot be read.",
                    hint="Try again. If it stays, something between you and Confluence is changing its answers.",
                ) from None
            if not parts.hostname or parts.username or parts.password:
                raise UnavailableError("Confluence redirected the download to an address that cannot be used.")
            if parts.scheme != "https" and not (parts.scheme == "http" and is_local_host(parts.hostname)):
                raise UnavailableError(
                    f"Confluence redirected the download to a plain http address ({parts.hostname}); that was refused.",
                    hint="The credentials and the file must not travel unencrypted.",
                )
            target = parts.path + (f"?{parts.query}" if parts.query else "")
            if not target.isascii() or _UNSENDABLE.search(target):  # no request can be made for it, and the answer made it: nothing was sent
                raise UnavailableError(
                    "Confluence redirected the download to an address that cannot be used: it holds a space, a control character or a letter that no address can hold.",
                    hint="Nothing was sent to it. Try again. If it stays, something between you and Confluence is changing its answers.",
                )
            if _origin(parts.scheme, parts.hostname, target_port) == home:
                sent = {
                    "Authorization": self._authorization(),
                    "Accept": "*/*",
                    "Accept-Encoding": "identity",
                    "User-Agent": f"conflu-c-cli/{__version__}",
                }
                response = self._send(scheme, host, port, "GET", target, sent, None, 1, timeout, cap, shared=True)
            else:
                sent = {"Accept": "*/*", "Accept-Encoding": "identity", "User-Agent": f"conflu-c-cli/{__version__}"}
                attempts = 1 + max(self._settings.retry, 0)
                response = self._send(parts.scheme, parts.hostname, target_port, "GET", target, sent, None, attempts, timeout, cap, shared=False)
        return response

    def get_public(self, base_url: str, path: str, *, limit: int, timeout: float | None = None) -> HttpResponse:
        """`path` at the root of the host that `base_url` names (not below `/wiki`), asked for without any credential, and the answer is
        taken as it comes: a redirect is not followed, so nothing is ever sent to another host. For public information that is read before
        the credentials work (`conflu setup --discover`). The TLS settings, the timeouts, the retries of a read and the explanation of a
        refused certificate are those of every other request, and so are the rules for the address of the site."""
        scheme, host, port, _ = self._address(base_url)
        sent = {"Accept": "application/json", "Accept-Encoding": "gzip", "User-Agent": f"conflu-c-cli/{__version__}"}
        attempts = 1 + max(self._settings.retry, 0)
        return self._send(scheme, host, port, "GET", path, sent, None, attempts, timeout, limit, shared=False)

    def close(self) -> None:
        self._close()

    # -- plumbing ---------------------------------------------------------------------------

    def _send(
        self,
        scheme: str,
        host: str,
        port: int | None,
        method: str,
        target: str,
        headers: Mapping[str, str],
        body: bytes | None,
        attempts: int,
        timeout: float | None,
        limit: int,
        *,
        shared: bool,
    ) -> HttpResponse:
        import http.client
        import ssl
        import zlib

        shown = target.split("?")[0] if shared else f"{host}{target.split('?')[0]}"  # a media address carries a token in its query
        budget = timeout if timeout is not None else self._settings.max_time
        last_problem = ""
        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            connection = None
            try:
                connection = self._connect(scheme, host, port) if shared else self._open(scheme, host, port)
                if connection.sock is not None:
                    connection.sock.settimeout(budget)  # the time to wait for the next bytes; the deadline below is the time for the whole answer
                connection.request(method, target, body=body, headers=dict(headers))
                deadline = time.monotonic() + budget  # counted from the end of the request: a slow upload has not used up the time of the answer
                response = connection.getresponse()
                data = self._read(response, limit, deadline)
                if shared and response.will_close:
                    self._close()  # the next request opens a new connection with the right timeouts
                if data and response.getheader("Content-Encoding", "").lower() == "gzip":
                    data = _gunzip(data, limit)
            except http.client.InvalidURL:  # before HTTPException, which it is one of. Its text repeats the address, which may hold a token: not shown
                if shared:
                    self._close()  # the library stops half-way into the request
                self._debug(f"{method} {shown} was not sent: no address can hold a space or a control character")
                raise UsageError(
                    "The address of the request holds a space or a control character, which no address can hold: nothing was sent.",
                    hint="Write a space as %20 and leave line breaks and other control characters out.",
                ) from None
            except (OSError, EOFError, zlib.error, ValueError, http.client.HTTPException) as error:  # a ValueError: what came in or an address in it, which no parser or socket takes
                if shared:
                    self._close()
                last_problem = f"{type(error).__name__}: {error}"
                self._debug(f"{method} {shown} failed: {last_problem}")
                refused_certificate = isinstance(error, ssl.SSLCertVerificationError)  # asking again gets the same answer
                if attempt < attempts and not refused_certificate:
                    self._sleep(float(attempt))
                    continue
                if isinstance(error, (EOFError, zlib.error)) or (isinstance(error, ValueError) and not isinstance(error, OSError)):  # a refused certificate is both a ValueError and an OSError: it is the network's
                    raise UnavailableError(
                        f"Confluence sent an answer that could not be read ({last_problem}).",
                        hint="Try again; if it stays, a proxy between you and Confluence may be damaging the response.",
                    ) from error
                note = ""
                if refused_certificate and getattr(error, "verify_code", None) in _UNTRUSTED_ISSUER and scheme == "https":
                    note = untrusted_chain_note(self._presented_chain(host, port))
                raise UnavailableError(f"Cannot reach Confluence ({last_problem}).", hint=self._reach_hint(last_problem, note)) from error
            except UnavailableError:
                if shared:
                    self._close()
                raise
            finally:
                if not shared and connection is not None:
                    connection.close()
            self._debug(f"{method} {shown} -> {response.status} ({(time.perf_counter() - started) * 1000:.0f} ms)")
            if response.status in _RETRY_STATUSES and attempt < attempts:
                if shared:
                    self._close()
                self._sleep(_retry_delay(attempt, response.getheader("Retry-After")))
                continue
            return HttpResponse(response.status, {key.lower(): value for key, value in response.getheaders()}, data)
        raise UnavailableError(f"Cannot reach Confluence ({last_problem}).")  # pragma: no cover

    @staticmethod
    def _read(response: http.client.HTTPResponse, limit: int, deadline: float | None = None) -> bytes:
        """The body of an answer, never more than `limit` bytes and, with a `deadline` (a `time.monotonic()` reading), not for longer than that.
        The socket times out when no byte comes for CONFLUENCE_MAX_TIME seconds, which a server that sends one byte in each of them never
        causes: a body is read piece by piece (`read1` is one system call, where `read(65536)` waits for 64 KiB), and the clock is looked at
        between the pieces. A deadline that passed is a `TimeoutError`, which is what a socket that timed out raises."""
        declared = response.getheader("Content-Length", "")
        if declared.isascii() and declared.isdigit() and (len(declared) > 18 or int(declared) > limit):  # `²`.isdigit() is True and int() refuses it, and so does a number of 5000 digits
            raise _too_big(limit)  # no need to read what is refused anyway
        read = getattr(response, "read1", None) or response.read
        chunks: list[bytes] = []
        total = 0
        while True:
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError("the answer was still coming in when the time allowed for it (CONFLUENCE_MAX_TIME) was up")
            chunk = read(65536)
            if not chunk:
                response.close()  # `read1` of Python 3.10, and of 3.11 and 3.12 before their fix of December 2023 (gh-113199), leaves an answer that it read to its Content-Length open, and the connection takes no new request while one is
                return b"".join(chunks)
            total += len(chunk)
            if total > limit:
                raise _too_big(limit)
            chunks.append(chunk)

    def _presented_chain(self, host: str, port: int | None) -> list[bytes]:
        """The certificates a server sends, for an error message. It is a handshake without verification and nothing is
        sent over it, so no credential leaves; what comes back is only ever read for names. Never raises."""
        import socket
        import ssl

        try:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            with socket.create_connection((host, port or 443), timeout=self._settings.connect_timeout) as raw:
                with context.wrap_socket(raw, server_hostname=host) as tls:
                    chain_of = getattr(tls, "get_unverified_chain", None)  # Python 3.13; before it only the first one is known
                    if chain_of is None:
                        leaf = tls.getpeercert(binary_form=True)
                        return [leaf] if leaf else []
                    return [bytes(item) if isinstance(item, (bytes, bytearray)) else ssl.PEM_cert_to_DER_cert(item.public_bytes()) for item in chain_of()]
        except Exception:  # an explanation that cannot be had must not hide the error it explains
            return []

    def _reach_hint(self, problem: str, chain_note: str = "") -> str:
        if "CERTIFICATE_VERIFY_FAILED" in problem and chain_note:
            return (
                f"{chain_note} None of the authorities in it is in the certificate store that this program uses (the operating system's). "
                "Get the certificate of the authority from the organisation that runs it or from your IT department, check its SHA-256 "
                "fingerprint with them, save it as a PEM file and run `conflu config set CONFLUENCE_CA_BUNDLE C:/certs/authority.pem`: "
                "it is trusted in addition to the system store. `conflu doctor` checks all of it."
            )
        if "CERTIFICATE_VERIFY_FAILED" in problem:
            text = "The certificate of the server was not accepted. On a company network with TLS inspection, name the certificate authority with CONFLUENCE_CA_BUNDLE."
            if self._settings.tls_strict:
                text += " CONFLUENCE_TLS_STRICT is on: unsetting it accepts certificates that lack the extensions Python 3.13 insists on."
            return text + " `conflu doctor` checks all of it."
        if "timed out" in problem or "CONFLUENCE_MAX_TIME" in problem:
            return (
                f"Nothing came in time: the connection may take {self._settings.connect_timeout:g} seconds (CONFLUENCE_CONNECT_TIMEOUT) and the whole answer "
                f"{self._settings.max_time:g} (CONFLUENCE_MAX_TIME). Check the network or VPN; for a slow link or a big file allow more, for example "
                "`conflu config set CONFLUENCE_MAX_TIME 600`. `conflu doctor` checks all of it."
            )
        return "Check CONFLUENCE_BASE_URL and the network or VPN. `conflu doctor` checks all of it."

    def _authorization(self) -> str:
        credentials = f"{self._settings.email}:{self._settings.api_token}".encode("utf-8")
        return "Basic " + base64.b64encode(credentials).decode("ascii")

    def _address(self, base_url: str) -> tuple[str, str, int | None, str]:
        """The address of the site as (scheme, host, port, path), checked: a web address with a host and no user name, password, query or
        fragment, and not plain http unless it is on this computer or CONFLUENCE_ALLOW_HTTP says so. What a refusal says never repeats an
        address that holds credentials, and an `@` anywhere in the address is taken for the start of them."""
        example = "https://example.atlassian.net/wiki"
        invalid = ConfigError(f"CONFLUENCE_BASE_URL is not a valid web address: {shown_address(base_url)}", hint=f"It must look like {example}")
        try:
            parts = urllib.parse.urlsplit(wiki_root(base_url))
            host, port = parts.hostname, parts.port  # a port that is no number raises here, and its text would repeat part of the address
        except ValueError:
            raise invalid from None
        if parts.scheme not in ("http", "https") or not host:
            raise invalid
        if parts.username is not None or parts.password is not None or "@" in base_url or parts.query or parts.fragment:
            raise ConfigError(
                "CONFLUENCE_BASE_URL must not contain a user name, a password, a query or a fragment.",
                hint=f"It must look like {example}; the e-mail address and the token are set apart.",
            )
        if parts.scheme == "http" and not self._settings.allow_http and not is_local_host(host):
            raise ConfigError(
                "CONFLUENCE_BASE_URL uses plain http: the credentials would travel unencrypted with every request.",
                hint="Use the https address of the site. On an isolated network you can accept the risk with `conflu config set CONFLUENCE_ALLOW_HTTP true`.",
            )
        return parts.scheme, host, port, parts.path.rstrip("/")

    def _target(self) -> tuple[str, str, int | None, str]:
        if self._site is None:
            example = "https://example.atlassian.net/wiki"
            if not self._settings.base_url:
                raise ConfigError("CONFLUENCE_BASE_URL is not set.", hint=f"Run `conflu config set CONFLUENCE_BASE_URL {example}`.")
            if not self._settings.email:
                raise ConfigError("CONFLUENCE_EMAIL is not set.", hint="Run `conflu config set CONFLUENCE_EMAIL user@example.com`.")
            if not self._settings.api_token:
                raise ConfigError("CONFLUENCE_API_TOKEN is not set.", hint="Run `conflu setup-token`.")
            self._site = self._address(self._settings.base_url)
        return self._site

    def _connect(self, scheme: str, host: str, port: int | None) -> http.client.HTTPConnection:
        if self._connection is None:
            self._connection = self._open(scheme, host, port)
        return self._connection

    def _open(self, scheme: str, host: str, port: int | None) -> http.client.HTTPConnection:
        import http.client

        name = f"[{host}]" if ":" in host else host  # http.client wants an IPv6 address in brackets: else it reads the last group as a port
        if scheme == "https":
            connection: http.client.HTTPConnection = http.client.HTTPSConnection(
                name, port, context=self._context(), timeout=self._settings.connect_timeout
            )
        else:
            connection = http.client.HTTPConnection(name, port, timeout=self._settings.connect_timeout)
        connection.connect()
        return connection

    def _context(self) -> ssl.SSLContext:
        import ssl

        context = ssl.create_default_context()  # the operating system's authorities
        if self._settings.ca_bundle:
            try:
                context.load_verify_locations(cafile=self._settings.ca_bundle)  # more of them, not instead of those
            except OSError as error:  # an SSLError (a file that holds no certificate) is one too
                raise ConfigError(
                    f"Cannot read CONFLUENCE_CA_BUNDLE ({self._settings.ca_bundle}): {error}",
                    hint="Fix the path, or unset CONFLUENCE_CA_BUNDLE to use the system certificate store alone. The file holds certificates in PEM form.",
                ) from error
        if not self._settings.tls_strict:  # the chain and the host name are still verified
            strict = int(getattr(ssl, "VERIFY_X509_STRICT", 0))
            context.verify_flags = ssl.VerifyFlags(int(context.verify_flags) & ~strict)
        if self._settings.insecure:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        return context

    def _close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            finally:
                self._connection = None
