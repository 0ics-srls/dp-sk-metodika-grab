"""The polite HTTP client of the grab: browser User-Agent, pacing through an injected clock, retries, redirects inside the allow-list.

Politeness (P81b-14): at least 0.6 s between two requests (more for a host with its own delay, UVO: 2 s), one request at a time, 5xx, timeouts and
connection resets retried 3 times with a growing back-off, a 403 or 429 ends the run with a config_error that names the answer's body type (never retried
blindly), redirects followed only to hosts of the allow-list. TLS context = certifi plus ``certs/*.pem`` (empty today, the loader is unit-tested).
The clock and the sleep are injected, so tests do not wait; ``replay_base`` sends every request to a replay origin (the Source setting ``baseUrl``).
"""
from __future__ import annotations

import re
import ssl
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

import certifi
import httpx

from dp_sk_metodika_grab.errors import CONFIG_ERROR, TRANSIENT_ERROR, GrabError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

CERTS_DIR = Path(__file__).resolve().parent / "certs"
DEFAULT_ALLOWED_HOSTS: tuple[str, ...] = ("www.financnasprava.sk", "www.mfsr.sk", "nbs.sk", "www.uvo.gov.sk")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
DEFAULT_HEADERS = {"User-Agent": USER_AGENT, "Accept": "*/*", "Accept-Language": "sk,cs;q=0.8,en;q=0.5"}
MIN_DELAY = 0.6
RETRIES = 3
BACKOFF_SEC = 5.0
MAX_REDIRECTS = 5
TIMEOUT_SEC = 120.0
CHUNK = 64 * 1024
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
_RETRYABLE_STATUS = 500
_BLOCKED = frozenset({403, 429})
_CHARSET = re.compile(r"charset=\"?([A-Za-z0-9_.:-]+)", re.IGNORECASE)


class TooLargeError(Exception):
    """A download passed the size cap; carries the limit."""

    def __init__(self, url: str, limit: int) -> None:
        super().__init__(f"{url} is larger than {limit} bytes")
        self.url = url
        self.limit = limit


@dataclass(frozen=True)
class Fetched:
    """A finished answer: the status and the whole body (the caller decides what a 404 means)."""

    url: str
    status: int
    headers: httpx.Headers
    body: bytes

    @property
    def content_type(self) -> str:
        return str(self.headers.get("content-type", ""))

    def text(self) -> str:
        found = _CHARSET.search(self.content_type)
        encoding = found.group(1) if found else "utf-8"
        try:
            return self.body.decode(encoding, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


def load_pinned(context: ssl.SSLContext, certs_dir: Path = CERTS_DIR) -> list[str]:
    """Adds every ``*.pem`` of ``certs_dir`` (sorted) to ``context``; returns the file names. A missing directory loads nothing."""
    loaded: list[str] = []
    if not certs_dir.is_dir():
        return loaded
    for pem in sorted(certs_dir.glob("*.pem")):
        try:
            context.load_verify_locations(cafile=str(pem))
        except (ssl.SSLError, OSError) as error:
            msg = f"pinned certificate {pem.name} cannot be loaded: {error}"
            raise GrabError(CONFIG_ERROR, msg) from error
        loaded.append(pem.name)
    return loaded


def ssl_context(*, verify: bool = True, certs_dir: Path = CERTS_DIR) -> ssl.SSLContext:
    """certifi roots plus the pinned certificates; ``verify=False`` gives a context that does not verify (the documented escape ``verifyTls``)."""
    context = ssl.create_default_context(cafile=certifi.where())
    if not verify:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    load_pinned(context, certs_dir)
    return context


class Client:
    """Paced, retried GETs: any status goes back to the caller except 403/429 (config_error) and 5xx/transport failures (transient_error after retries)."""

    def __init__(  # noqa: PLR0913
        self,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        delay: float = MIN_DELAY,
        verify: bool = True,  # noqa: FBT001, FBT002
        *,
        allowed_hosts: tuple[str, ...] | list[str] = DEFAULT_ALLOWED_HOSTS,
        host_delays: Mapping[str, float] | None = None,
        replay_base: str | None = None,
        certs_dir: Path = CERTS_DIR,
    ) -> None:
        if delay < MIN_DELAY:
            msg = f"delay must be >= {MIN_DELAY} seconds (respect for the source), got {delay}"
            raise GrabError(CONFIG_ERROR, msg)
        self._clock = clock
        self._sleep = sleep
        self._delay = delay
        self._host_delays = {host.lower(): max(value, delay) for host, value in (host_delays or {}).items()}
        self._allowed = {host.lower() for host in allowed_hosts}
        self._replay = urlsplit(replay_base) if replay_base else None
        if self._replay is not None:
            if self._replay.scheme not in {"http", "https"} or not self._replay.hostname:
                msg = f"baseUrl must be an http(s) URL, got {replay_base!r}"
                raise GrabError(CONFIG_ERROR, msg)
            self._allowed.add(self._replay.hostname.lower())
        self._last: float | None = None
        self._http = httpx.Client(
            transport=transport, follow_redirects=False, timeout=TIMEOUT_SEC, verify=ssl_context(verify=verify, certs_dir=certs_dir), headers=DEFAULT_HEADERS
        )

    def close(self) -> None:
        self._http.close()

    def _interval(self, host: str) -> float:
        return self._host_delays.get(host, self._delay)

    def _pace(self, host: str) -> None:
        if self._last is not None:
            remaining = self._interval(host) - (self._clock() - self._last)
            if remaining > 0:
                self._sleep(remaining)
        self._last = self._clock()

    def _target(self, url: str) -> str:
        """The URL actually requested: the replay origin stands in for every site."""
        if self._replay is None:
            return url
        parts = urlsplit(url)
        origin = f"{self._replay.scheme}://{self._replay.netloc}"
        return origin + parts.path + (f"?{parts.query}" if parts.query else "")

    def _check_host(self, url: str) -> str:
        host = (urlsplit(url).hostname or "").lower()
        if host not in self._allowed:
            msg = f"host {host or url!r} is not in the allowed hosts {sorted(self._allowed)}"
            raise GrabError(CONFIG_ERROR, msg)
        return host

    def get(self, url: str, *, max_bytes: int | None = None) -> Fetched:
        """GET ``url`` (redirects followed inside the allow-list). ``max_bytes`` makes a larger body raise ``TooLargeError``."""
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            host = self._check_host(current)
            response = self._get_with_retries(current, host, max_bytes)
            if response.status not in _REDIRECTS:
                return response
            location = response.headers.get("location")
            if not location:
                msg = f"redirect without Location from {current}"
                raise GrabError(CONFIG_ERROR, msg)
            current = urljoin(current, location)
        msg = f"more than {MAX_REDIRECTS} redirects from {url}"
        raise GrabError(CONFIG_ERROR, msg)

    def _get_with_retries(self, url: str, host: str, max_bytes: int | None) -> Fetched:
        last: GrabError | None = None
        for attempt in range(RETRIES + 1):
            if attempt:
                self._sleep(BACKOFF_SEC * attempt)
            self._pace(host)
            try:
                response = self._once(url, max_bytes)
            except httpx.TransportError as error:
                last = GrabError(TRANSIENT_ERROR, f"request to {url} failed: {error!r}")
                continue
            if response.status in _BLOCKED:
                kind = response.content_type or "unknown"
                msg = f"HTTP {response.status} from {url} (answer body type {kind}): the source refuses this client; lower the rate or stop"
                raise GrabError(CONFIG_ERROR, msg)
            if response.status >= _RETRYABLE_STATUS:
                last = GrabError(TRANSIENT_ERROR, f"HTTP {response.status} from {url}")
                continue
            return response
        assert last is not None  # the loop ran at least once
        raise last

    def _once(self, url: str, max_bytes: int | None) -> Fetched:
        with self._http.stream("GET", self._target(url)) as response:
            declared = response.headers.get("content-length")
            if max_bytes is not None and declared is not None and declared.isdigit() and int(declared) > max_bytes:
                raise TooLargeError(url, max_bytes)
            body = bytearray()
            for block in response.iter_bytes(CHUNK):
                body.extend(block)
                if max_bytes is not None and len(body) > max_bytes:
                    raise TooLargeError(url, max_bytes)
            return Fetched(url, response.status_code, response.headers, bytes(body))
