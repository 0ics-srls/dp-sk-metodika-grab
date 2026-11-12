"""Shared test ports: a fake clock (sleep advances time), a recording scripted transport and fixture loaders.

No test uses the real network: the socket connect is refused for every unit test. The recorded real answers live in tests/fixtures (see PROVENANCE.md).
"""
from __future__ import annotations

import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PDF_BYTES = b"%PDF-1.4\n" + b"0" * 4000


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("integration") is not None:
        return

    def refuse(*_args: object, **_kwargs: object) -> None:
        msg = "tests must not use the network"
        raise AssertionError(msg)

    monkeypatch.setattr(socket.socket, "connect", refuse)


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakeTime:
    """clock() and sleep(): sleeping advances the clock, so pacing is asserted without waiting."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@dataclass
class Recorded:
    method: str
    url: str
    headers: httpx.Headers
    at: float


@dataclass
class Server:
    """A scripted transport: ``route`` maps a request to a response; every request is recorded with the fake time it was made."""

    route: Callable[[httpx.Request], httpx.Response]
    time: FakeTime
    requests: list[Recorded] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(Recorded(request.method, str(request.url), request.headers, self.time.now))
        self.time.now += 0.05  # a request takes a little time, like a real one
        return self.route(request)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def urls(self) -> list[str]:
        return [r.url for r in self.requests]

    def gaps(self) -> list[float]:
        return [b.at - a.at for a, b in zip(self.requests, self.requests[1:], strict=False)]


def html(text: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, content=text.encode("utf-8"), headers={"content-type": "text/html; charset=utf-8"})


def pdf(data: bytes = PDF_BYTES, content_type: str = "application/pdf", extra: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(200, content=data, headers={"content-type": content_type, **(extra or {})})
