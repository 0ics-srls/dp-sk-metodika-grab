"""Walking the Financna sprava listings with a scripted transport: pages repeat after the end, an empty page stops, the pace and the retries hold."""
from __future__ import annotations

import httpx
import pytest

from conftest import FakeTime, Server, fixture_text, html
from dp_sk_metodika_grab import fs
from dp_sk_metodika_grab.errors import CONFIG_ERROR, GrabError
from dp_sk_metodika_grab.http import Client

SECTIONS = fs.sections()


def listing_page(first: int, count: int, year: int = 2020) -> str:
    """A synthetic page shaped like the recorded ones (single-quoted hrefs, title in the anchor text)."""
    anchors = "".join(
        f"<a href='https://www.financnasprava.sk//_img/pfsedit/Dokumenty_PFS/Zverejnovanie_dok/Dane/Metodicke_usmernenia/{year}/{year}.01.{n % 28 + 1:02d}_{n:03d}.pdf'"
        f' class="title__link" title="{n}/DZPaU/{year}/MU - t [.pdf; 100 KB; nové okno]">{n}/DZPaU/{year}/MU - Usmernenie {n}\n</a>'
        for n in range(first, first + count)
    )
    return f"<html><body><div class='list'>{anchors}</div></body></html>"


def served(pages: dict[str, str], clock: FakeTime) -> Server:
    def route(request: httpx.Request) -> httpx.Response:
        text = pages.get(str(request.url))
        return html(text) if text is not None else html("not found", 404)

    return Server(route, clock)


def walk(server: Server, section: str) -> fs.Walk:
    return fs.walk_section(Client(server.transport(), server.time.clock, server.time.sleep), section, SECTIONS[section])


@pytest.mark.unit
def test_should_collect_41_documents_when_usmernenia_has_five_pages_and_then_repeats() -> None:
    base = SECTIONS["metodicke-usmernenia"]
    first = fixture_text("fs-usmernenia-1.html")
    pages = {
        base: first,
        fs.page_url(base, 2): listing_page(100, 10),
        fs.page_url(base, 3): listing_page(200, 10),
        fs.page_url(base, 4): listing_page(300, 10),
        fs.page_url(base, 5): listing_page(400, 1),
        fs.page_url(base, 6): first,  # the site wraps around after the last page
    }
    server = served(pages, FakeTime())

    result = walk(server, "metodicke-usmernenia")

    assert len(result.docs) == 41
    assert len({d.pdf_url for d in result.docs}) == 41
    assert server.urls() == [base, *[fs.page_url(base, n) for n in range(2, 7)]]
    assert all(d.section == "metodicke-usmernenia" for d in result.docs)
    assert {d.listing_url for d in result.docs} <= set(pages)


@pytest.mark.unit
def test_should_collect_3_documents_when_zavery_repeats_page_one_on_page_two() -> None:
    base = SECTIONS["zavery-komisii"]
    page = fixture_text("fs-zavery.html")
    server = served({base: page, fs.page_url(base, 2): page}, FakeTime())

    result = walk(server, "zavery-komisii")

    assert len(result.docs) == 3
    assert len(server.requests) == 2


@pytest.mark.unit
def test_should_walk_the_prehlady_url_with_the_embedded_page_marker() -> None:
    base = SECTIONS["prehlady-zmluv-zdz"]
    server = served({base: fixture_text("fs-prehlady-1.html"), fs.page_url(base, 2): fixture_text("fs-prehlady-2.html")}, FakeTime())

    result = walk(server, "prehlady-zmluv-zdz")

    assert len(result.docs) == 7
    assert "/_2/" in server.urls()[1]
    assert "D%c3%a1tum%20publikovania" in server.urls()[1]


@pytest.mark.unit
def test_should_stop_when_page_three_of_pokyny_has_no_documents() -> None:
    base = SECTIONS["metodicke-pokyny"]
    server = served(
        {base: fixture_text("fs-pokyny-1.html"), fs.page_url(base, 2): fixture_text("fs-pokyny-2.html"), fs.page_url(base, 3): fixture_text("fs-pokyny-3-empty.html")},
        FakeTime(),
    )

    result = walk(server, "metodicke-pokyny")

    assert len(result.docs) == 20
    assert len(server.requests) == 3


@pytest.mark.unit
def test_should_pace_every_request_at_least_06_seconds_apart() -> None:
    base = SECTIONS["metodicke-pokyny"]
    server = served({base: fixture_text("fs-pokyny-1.html"), fs.page_url(base, 2): fixture_text("fs-pokyny-2.html"), fs.page_url(base, 3): fixture_text("fs-pokyny-3-empty.html")}, FakeTime())

    walk(server, "metodicke-pokyny")

    assert len(server.gaps()) == 2
    assert all(gap >= 0.6 - 1e-6 for gap in server.gaps()), server.gaps()


@pytest.mark.unit
def test_should_retry_a_500_on_a_listing_page_and_go_on() -> None:
    base = SECTIONS["zavery-komisii"]
    page = fixture_text("fs-zavery.html")
    calls: list[str] = []

    def route(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(500, text="oops")
        return html(page)

    server = Server(route, FakeTime())

    result = walk(server, "zavery-komisii")

    assert len(result.docs) == 3
    assert calls[:2] == [base, base]


@pytest.mark.unit
def test_should_retry_a_connection_reset_on_a_listing_page() -> None:
    base = SECTIONS["zavery-komisii"]
    page = fixture_text("fs-zavery.html")
    state = {"resets": 1}

    def route(request: httpx.Request) -> httpx.Response:
        if state["resets"]:
            state["resets"] -= 1
            raise httpx.ReadError("connection reset", request=request)
        return html(page)

    server = Server(route, FakeTime())

    result = walk(server, "zavery-komisii")

    assert len(result.docs) == 3
    assert server.urls()[0] == base


@pytest.mark.unit
def test_should_end_with_a_config_error_on_403() -> None:
    server = Server(lambda _r: httpx.Response(403, text="denied", headers={"content-type": "text/html"}), FakeTime())

    with pytest.raises(GrabError) as caught:
        walk(server, "metodicke-pokyny")

    assert caught.value.code == CONFIG_ERROR


@pytest.mark.unit
def test_should_return_an_empty_walk_with_a_warning_when_the_first_page_is_gone() -> None:
    server = served({}, FakeTime())

    result = walk(server, "metodicke-pokyny")

    assert result.docs == []
    assert result.warnings == ["listing_http_404"]


@pytest.mark.unit
def test_should_cap_the_walk_at_500_pages() -> None:
    counter = {"n": 0}

    def route(_request: httpx.Request) -> httpx.Response:
        counter["n"] += 1
        return html(listing_page(counter["n"] * 10, 1))  # every page brings a fresh document: only the cap stops the walk

    server = Server(route, FakeTime())

    result = walk(server, "metodicke-pokyny")

    assert len(server.requests) == fs.PAGE_CAP == 500
    assert len(result.docs) == 500
