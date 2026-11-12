"""The polite HTTP client: browser UA, pacing through an injected clock, retries, 403/429 as config errors, redirects inside the allow-list."""
from __future__ import annotations

import httpx
import pytest

from conftest import FakeTime, Server, html
from dp_sk_metodika_grab.errors import CONFIG_ERROR, TRANSIENT_ERROR, GrabError
from dp_sk_metodika_grab.http import MIN_DELAY, Client, TooLargeError

URL = "https://www.mfsr.sk/page"


def client_for(server: Server, **kwargs: object) -> Client:
    return Client(server.transport(), server.time.clock, server.time.sleep, **kwargs)  # type: ignore[arg-type]


def ok(_request: httpx.Request) -> httpx.Response:
    return html("<p>ok</p>")


@pytest.mark.unit
def test_should_send_a_browser_user_agent_and_slovak_accept_language() -> None:
    server = Server(ok, FakeTime())

    client_for(server).get(URL)

    headers = server.requests[0].headers
    assert headers["user-agent"].startswith("Mozilla/5.0")
    assert "Headless" not in headers["user-agent"]
    assert headers["accept-language"].startswith("sk")


@pytest.mark.unit
def test_should_pace_requests_at_least_06_seconds_apart_on_the_fake_clock() -> None:
    server = Server(ok, FakeTime())
    client = client_for(server)

    for n in range(4):
        client.get(f"{URL}/{n}")

    assert len(server.requests) == 4
    assert all(gap >= 0.6 - 1e-6 for gap in server.gaps()), server.gaps()
    assert MIN_DELAY == 0.6


@pytest.mark.unit
def test_should_refuse_a_delay_below_the_minimum() -> None:
    with pytest.raises(GrabError) as caught:
        Client(None, delay=0.5)
    assert caught.value.code == CONFIG_ERROR


@pytest.mark.unit
def test_should_use_the_configured_delay_and_a_longer_per_host_delay() -> None:
    server = Server(ok, FakeTime())
    client = client_for(server, delay=1.5, host_delays={"www.uvo.gov.sk": 2.0})

    client.get("https://www.mfsr.sk/a")
    client.get("https://www.mfsr.sk/b")
    client.get("https://www.uvo.gov.sk/c")
    client.get("https://www.uvo.gov.sk/d")

    gaps = server.gaps()
    assert gaps[0] >= 1.5 - 1e-6
    assert gaps[2] >= 2.0 - 1e-6
    assert gaps[1] >= 2.0 - 1e-6, "the gap before a uvo request is the uvo delay"


@pytest.mark.unit
def test_should_retry_a_500_and_return_the_following_200() -> None:
    answers = iter([httpx.Response(500, text="boom"), httpx.Response(200, text="fine", headers={"content-type": "text/html"})])
    server = Server(lambda _r: next(answers), FakeTime())

    response = client_for(server).get(URL)

    assert response.status == 200
    assert response.text() == "fine"
    assert len(server.requests) == 2
    assert server.time.sleeps, "a back-off pause separates the attempts"
    assert all(gap >= 0.6 for gap in server.gaps())


@pytest.mark.unit
def test_should_retry_a_connection_reset_and_a_timeout() -> None:
    errors: list[Exception] = [httpx.ReadError("connection reset by peer"), httpx.ConnectTimeout("timed out")]

    def route(_request: httpx.Request) -> httpx.Response:
        if errors:
            raise errors.pop(0)
        return html("later")

    server = Server(route, FakeTime())

    response = client_for(server).get(URL)

    assert response.text() == "later"
    assert len(server.requests) == 3


@pytest.mark.unit
def test_should_give_up_with_a_transient_error_after_three_retries() -> None:
    server = Server(lambda _r: httpx.Response(503, text="down"), FakeTime())

    with pytest.raises(GrabError) as caught:
        client_for(server).get(URL)

    assert caught.value.code == TRANSIENT_ERROR
    assert len(server.requests) == 4
    assert "503" in str(caught.value)


@pytest.mark.unit
@pytest.mark.parametrize("status", [403, 429])
def test_should_end_with_a_config_error_naming_the_body_type_on_403_and_429(status: int) -> None:
    server = Server(lambda _r: httpx.Response(status, text="<html>blocked</html>", headers={"content-type": "text/html; charset=utf-8"}), FakeTime())

    with pytest.raises(GrabError) as caught:
        client_for(server).get(URL)

    assert caught.value.code == CONFIG_ERROR
    assert str(status) in str(caught.value)
    assert "text/html" in str(caught.value)
    assert len(server.requests) == 1, "never retried blindly"


@pytest.mark.unit
def test_should_return_a_404_to_the_caller_without_retrying() -> None:
    server = Server(lambda _r: httpx.Response(404, text="gone"), FakeTime())

    response = client_for(server).get(URL)

    assert response.status == 404
    assert len(server.requests) == 1


@pytest.mark.unit
def test_should_follow_a_redirect_inside_the_allowed_hosts_and_pace_it() -> None:
    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "/sk/new/"})
        return html("moved")

    server = Server(route, FakeTime())

    response = client_for(server).get("https://www.mfsr.sk/old")

    assert response.text() == "moved"
    assert server.urls() == ["https://www.mfsr.sk/old", "https://www.mfsr.sk/sk/new/"]
    assert server.gaps()[0] >= 0.6 - 1e-6


@pytest.mark.unit
def test_should_refuse_a_redirect_to_a_host_outside_the_allow_list() -> None:
    server = Server(lambda _r: httpx.Response(302, headers={"location": "https://evil.example/x"}), FakeTime())

    with pytest.raises(GrabError) as caught:
        client_for(server).get(URL)

    assert caught.value.code == CONFIG_ERROR
    assert "evil.example" in str(caught.value)
    assert len(server.requests) == 1


@pytest.mark.unit
def test_should_stop_a_redirect_loop() -> None:
    server = Server(lambda _r: httpx.Response(302, headers={"location": URL}), FakeTime())

    with pytest.raises(GrabError) as caught:
        client_for(server).get(URL)

    assert caught.value.code == CONFIG_ERROR
    assert len(server.requests) <= 7


@pytest.mark.unit
def test_should_refuse_a_host_that_is_not_allowed_before_any_request() -> None:
    server = Server(ok, FakeTime())

    with pytest.raises(GrabError) as caught:
        client_for(server).get("https://www.example.com/x")

    assert caught.value.code == CONFIG_ERROR
    assert server.requests == []


@pytest.mark.unit
def test_should_send_every_request_to_the_replay_origin_and_allow_its_host() -> None:
    server = Server(ok, FakeTime())
    client = client_for(server, replay_base="http://replay.test:8765")

    client.get("https://www.financnasprava.sk/sk/x/y?z=1")

    assert server.urls() == ["http://replay.test:8765/sk/x/y?z=1"]


@pytest.mark.unit
def test_should_stop_a_download_that_exceeds_the_size_cap() -> None:
    server = Server(lambda _r: httpx.Response(200, content=b"%PDF-" + b"0" * 5000, headers={"content-type": "application/pdf"}), FakeTime())

    with pytest.raises(TooLargeError):
        client_for(server).get(URL, max_bytes=1000)
    assert client_for(Server(lambda _r: httpx.Response(200, content=b"%PDF-1234"), FakeTime())).get(URL, max_bytes=1000).body == b"%PDF-1234"


@pytest.mark.unit
def test_should_decode_text_with_the_declared_charset() -> None:
    server = Server(lambda _r: httpx.Response(200, content="Zápis".encode("cp1250"), headers={"content-type": "text/html; charset=windows-1250"}), FakeTime())

    assert client_for(server).get(URL).text() == "Zápis"
