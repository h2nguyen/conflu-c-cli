"""HTTP(S) to Confluence Cloud on the standard library: keep-alive, retries, TLS, gzip, and redirects for downloads.

It speaks bytes and status codes only. Turning a status into an error and a body into domain objects is the job of
`confluence_rest.py`.

`http.client`, `ssl` and `zlib` are imported when the first request is made: they cost about 60 ms, which a command that
never talks to Confluence (`help`, `version`, `how-to`) should not pay.
"""
from __future__ import annotations

import base64
import time
import urllib.parse
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Mapping

from ...application.settings import Settings, is_local_host, wiki_root
from ...domain.certificates import untrusted_chain_note
from ...domain.errors import ConfigError, UnavailableError
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
MAX_DOWNLOAD = 512 * 1024 * 1024  # bytes; a file is held in memory before it is written
MAX_RESPONSE = 64 * 1024 * 1024  # bytes of an ordinary answer, once decoded; real answers are a few MiB at most


def _size_text(count: int) -> str:
    return f"{count // (1024 * 1024)} MiB" if count >= 1024 * 1024 else f"{count} bytes"


def _too_big(limit: int) -> UnavailableError:
    return UnavailableError(
        f"The answer is larger than {_size_text(limit)}; it was not read.",
        hint="Download a file in the browser. For a list, ask for less: a narrower search or a smaller --limit.",
    )


def _gunzip(data: bytes, limit: int) -> bytes:
    """What `gzip.decompress` gives, but never more than `limit` bytes: a few kilobytes on the wire must not be able to
    grow into gigabytes in memory. The output is counted while it is produced."""
    import zlib

    pieces: list[bytes] = []
    total = 0
    while data:  # a gzip file may hold several members one after the other; NUL padding between them is allowed
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
    """The server's `Retry-After` (whole seconds), else one second more for every attempt."""
    try:
        return min(max(float(retry_after), 0.0), _MAX_RETRY_WAIT) if retry_after else float(attempt)
    except ValueError:
        return float(attempt)  # an HTTP date or garbage: use the default


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

    def download(self, path: str, *, timeout: float | None = None) -> HttpResponse:
        """A file below the wiki address. Attachments are served by a media service on another host after a redirect:
        the redirect is followed, and the credentials go only to the host they were meant for."""
        scheme, host, port, prefix = self._target()
        home = _origin(scheme, host, port)
        response = self.request(
            "GET", path, accept="*/*", headers={"Accept-Encoding": "identity"}, timeout=timeout, limit=MAX_DOWNLOAD
        )
        here = f"{scheme}://{host}{f':{port}' if port else ''}{prefix}{path}"
        hops = 0
        while response.status in _REDIRECTS and response.headers.get("location"):
            hops += 1
            if hops > _MAX_REDIRECTS:
                raise UnavailableError("Confluence redirected the download too many times.", hint="Try again later.")
            here = urllib.parse.urljoin(here, response.headers["location"])
            parts = urllib.parse.urlsplit(here)
            if not parts.hostname or parts.username or parts.password:
                raise UnavailableError("Confluence redirected the download to an address that cannot be used.")
            if parts.scheme != "https" and not (parts.scheme == "http" and is_local_host(parts.hostname)):
                raise UnavailableError(
                    f"Confluence redirected the download to a plain http address ({parts.hostname}); that was refused.",
                    hint="The credentials and the file must not travel unencrypted.",
                )
            target = parts.path + (f"?{parts.query}" if parts.query else "")
            if _origin(parts.scheme, parts.hostname, parts.port) == home:
                sent = {
                    "Authorization": self._authorization(),
                    "Accept": "*/*",
                    "Accept-Encoding": "identity",
                    "User-Agent": f"conflu-c-cli/{__version__}",
                }
                response = self._send(scheme, host, port, "GET", target, sent, None, 1, timeout, MAX_DOWNLOAD, shared=True)
            else:
                sent = {"Accept": "*/*", "Accept-Encoding": "identity", "User-Agent": f"conflu-c-cli/{__version__}"}
                attempts = 1 + max(self._settings.retry, 0)
                response = self._send(parts.scheme, parts.hostname, parts.port, "GET", target, sent, None, attempts, timeout, MAX_DOWNLOAD, shared=False)
        return response

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
        last_problem = ""
        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            connection = None
            try:
                connection = self._connect(scheme, host, port) if shared else self._open(scheme, host, port)
                if connection.sock is not None:
                    connection.sock.settimeout(timeout if timeout is not None else self._settings.max_time)
                connection.request(method, target, body=body, headers=dict(headers))
                response = connection.getresponse()
                data = self._read(response, limit)
                if shared and response.will_close:
                    self._close()  # the next request opens a new connection with the right timeouts
                if data and response.getheader("Content-Encoding", "").lower() == "gzip":
                    data = _gunzip(data, limit)
            except (OSError, EOFError, zlib.error, http.client.HTTPException) as error:
                if shared:
                    self._close()
                last_problem = f"{type(error).__name__}: {error}"
                self._debug(f"{method} {shown} failed: {last_problem}")
                refused_certificate = isinstance(error, ssl.SSLCertVerificationError)  # asking again gets the same answer
                if attempt < attempts and not refused_certificate:
                    self._sleep(float(attempt))
                    continue
                if isinstance(error, (EOFError, zlib.error)):
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
    def _read(response: http.client.HTTPResponse, limit: int) -> bytes:
        declared = response.getheader("Content-Length", "")
        if declared.isascii() and declared.isdigit() and int(declared) > limit:  # `²`.isdigit() is True and int() refuses it
            raise _too_big(limit)  # no need to read what is refused anyway
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(65536)
            if not chunk:
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
        return "Check CONFLUENCE_BASE_URL and the network or VPN. `conflu doctor` checks all of it."

    def _authorization(self) -> str:
        credentials = f"{self._settings.email}:{self._settings.api_token}".encode("utf-8")
        return "Basic " + base64.b64encode(credentials).decode("ascii")

    def _target(self) -> tuple[str, str, int | None, str]:
        if self._site is None:
            example = "https://example.atlassian.net/wiki"
            if not self._settings.base_url:
                raise ConfigError("CONFLUENCE_BASE_URL is not set.", hint=f"Run `conflu config set CONFLUENCE_BASE_URL {example}`.")
            if not self._settings.email:
                raise ConfigError("CONFLUENCE_EMAIL is not set.", hint="Run `conflu config set CONFLUENCE_EMAIL user@example.com`.")
            if not self._settings.api_token:
                raise ConfigError("CONFLUENCE_API_TOKEN is not set.", hint="Run `conflu setup-token`.")
            parts = urllib.parse.urlsplit(wiki_root(self._settings.base_url))
            if parts.scheme not in ("http", "https") or not parts.hostname:
                raise ConfigError(
                    f"CONFLUENCE_BASE_URL is not a valid web address: {self._settings.base_url}",
                    hint=f"It must look like {example}",
                )
            if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
                raise ConfigError(
                    "CONFLUENCE_BASE_URL must not contain a user name, a password, a query or a fragment.",
                    hint=f"It must look like {example}; the e-mail address and the token are set apart.",
                )
            if parts.scheme == "http" and not self._settings.allow_http and not is_local_host(parts.hostname):
                raise ConfigError(
                    "CONFLUENCE_BASE_URL uses plain http: the credentials would travel unencrypted with every request.",
                    hint="Use the https address of the site. On an isolated network you can accept the risk with `conflu config set CONFLUENCE_ALLOW_HTTP true`.",
                )
            self._site = (parts.scheme, parts.hostname, parts.port, parts.path.rstrip("/"))
        return self._site

    def _connect(self, scheme: str, host: str, port: int | None) -> http.client.HTTPConnection:
        if self._connection is None:
            self._connection = self._open(scheme, host, port)
        return self._connection

    def _open(self, scheme: str, host: str, port: int | None) -> http.client.HTTPConnection:
        import http.client

        if scheme == "https":
            connection: http.client.HTTPConnection = http.client.HTTPSConnection(
                host, port, context=self._context(), timeout=self._settings.connect_timeout
            )
        else:
            connection = http.client.HTTPConnection(host, port, timeout=self._settings.connect_timeout)
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
