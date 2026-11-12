"""UVO metodicke usmernenia: the legacy Uvo_* case, the three recorded layouts (extdoc rows, direct PDFs, detail records) and the hub cross-check.

Nothing here (or anywhere) is fetched from uvo.gov.sk: every page is a recorded fixture served by an httpx MockTransport (decision D141).
"""
from __future__ import annotations

import httpx
import pytest

from conftest import FakeTime, Server, fixture_text, html
from dp_sk_metodika_grab import ids, uvo
from dp_sk_metodika_grab.http import Client

HUB = "https://www.uvo.gov.sk/metodika-vzdelavanie/metodicke-usmernenia-a-vykladove-stanoviska"
EXTDOC_LEAF = "vseobecne-metodicke-usmernenia-k-zakonu-c-343-2015-zz"
DIRECT_LEAF = "prehlad-vykladovych-stanovisk-uradu-zakon-c-343-2015-z-z"
LAYOUT_C_LEAF = "metodicke-usmernenia-k-zakonu-c-25-2006-zz"
MIXED_LEAF = "prehlad-vykladovych-stanovisk-uradu-zakon-c-25-2006-z-z"


def client_for(server: Server) -> Client:
    return Client(server.transport(), server.time.clock, server.time.sleep, host_delays=uvo.HOST_DELAYS)


@pytest.mark.unit
def test_should_discover_the_leaf_without_the_duplicate_page_link_and_build_the_next_page_url() -> None:
    hub = """
        <a href="/metodika-vzdelavanie/metodicke-usmernenia-a-vykladove-stanoviska/zakon-343">zákon 343</a>
        <a href="/metodika-vzdelavanie/metodicke-usmernenia-a-vykladove-stanoviska/zakon-343?page=2">dup</a>
        <a href="/ine">iné</a>
        """

    seeds = uvo.parse_hub(hub)

    assert seeds == [f"{HUB}/zakon-343"]
    assert uvo.page_url(seeds[0], 1) == seeds[0]
    assert uvo.page_url(seeds[0], 2) == f"{seeds[0]}?page=2"


@pytest.mark.unit
def test_should_parse_code_group_and_date_of_an_extdoc_row() -> None:
    leaf = """<table><tr><td><a href="/extdoc/999/dokument.pdf">2/2026</a></td><td>zverejnené 5.3.2026</td></tr></table>"""

    docs = uvo.parse(leaf, f"{HUB}/zakon-343")

    assert len(docs) == 1
    assert docs[0].group == "zakon-343"
    assert docs[0].code == "2/2026"
    assert docs[0].published == "2026-03-05"
    assert docs[0].pdf_url == "https://www.uvo.gov.sk/extdoc/999/dokument.pdf"
    assert docs[0].site == "uvo-metodicke"


@pytest.mark.unit
def test_should_read_a_date_that_is_not_a_calendar_day_as_unknown() -> None:
    leaf = '<tr><td><a href="/extdoc/1">1/2026</a></td><td>31.2.2026</td></tr>'

    assert uvo.parse(leaf, f"{HUB}/z")[0].published is None


@pytest.mark.unit
def test_should_know_the_seven_leaves_the_recorded_hub_links_to() -> None:
    assert len(uvo.LEAVES) == 7
    assert len(set(uvo.LEAVES)) == 7

    discovered = uvo.parse_hub(fixture_text("uvo-hub.html"))

    assert sorted(discovered) == sorted(f"{HUB}/{slug}" for slug in uvo.LEAVES)
    assert uvo.hub_warnings(fixture_text("uvo-hub.html")) == []


@pytest.mark.unit
def test_should_warn_about_a_leaf_that_is_not_one_of_the_constants() -> None:
    page = fixture_text("uvo-hub.html").replace("</body>", f'<a href="{HUB}/novy-zakon-c-1-2030-zz">novy</a></body>')
    assert "novy-zakon-c-1-2030-zz" in page

    assert uvo.hub_warnings(page) == ["new_leaf:novy-zakon-c-1-2030-zz"]


@pytest.mark.unit
def test_should_take_the_20_rows_of_the_recorded_extdoc_layout() -> None:
    docs = uvo.parse(fixture_text("uvo-leaf-extdoc.html"), f"{HUB}/{EXTDOC_LEAF}")

    assert len(docs) == 20
    assert all("/extdoc/" in d.pdf_url for d in docs)
    assert {d.group for d in docs} == {EXTDOC_LEAF}
    first = docs[0]
    assert first.pdf_url == "https://www.uvo.gov.sk/extdoc/53262"
    assert first.code == "7\N{EN DASH}2026"
    assert first.published == "2026-10-02"
    assert first.title.startswith("7\N{EN DASH}2026 02.10.2026 § 39 Pravidlá predkladania jednotného európskeho dokumentu")
    assert ids.source_id(first.pdf_url) == "extdoc_53262"
    assert first.doc_id == "53262"
    assert all(d.published is not None for d in docs)
    assert uvo.count_detail_rows(fixture_text("uvo-leaf-extdoc.html")) == 0


@pytest.mark.unit
def test_should_take_the_20_anchors_of_the_recorded_direct_pdf_layout() -> None:
    docs = uvo.parse(fixture_text("uvo-leaf-direct.html"), f"{HUB}/{DIRECT_LEAF}")

    assert len(docs) == 20
    assert all("/fileadmin/dokumenty/" in d.pdf_url and d.pdf_url.endswith(".pdf") for d in docs)
    first = docs[0]
    assert first.pdf_url == "https://www.uvo.gov.sk/fileadmin/dokumenty/vykladove_stanoviska_2015/vykladove_stanovisko_1-2021.pdf"
    assert first.code == "1_2021"
    assert first.published == "2021-02-05"
    assert ids.source_id(first.pdf_url) == "fileadmin_dokumenty_vykladove_stanoviska_2015_vykladove_stanovisko_1-2021"
    assert len({ids.source_id(d.pdf_url) for d in docs}) == 20


@pytest.mark.unit
def test_should_take_both_kinds_when_one_leaf_page_carries_extdoc_and_direct_links() -> None:
    docs = uvo.parse(fixture_text("uvo-leaf-mixed.html"), f"{HUB}/{MIXED_LEAF}")

    assert sum("/extdoc/" in d.pdf_url for d in docs) == 6
    assert sum("/fileadmin/dokumenty/" in d.pdf_url for d in docs) == 20
    assert len({d.pdf_url for d in docs}) == len(docs) == 26
    assert docs[0].code == "8_2015", "the .pdf suffix of an anchor text is not part of the code"


@pytest.mark.unit
def test_should_count_the_detail_rows_of_the_recorded_layout_c_and_take_no_document() -> None:
    page = fixture_text("uvo-leaf-layout-c.html")

    assert uvo.parse(page, f"{HUB}/{LAYOUT_C_LEAF}") == []
    assert uvo.count_detail_rows(page) == 20


@pytest.mark.unit
def test_should_record_layout_c_in_the_coverage_instead_of_a_silent_zero() -> None:
    server = Server(lambda _r: html(fixture_text("uvo-leaf-layout-c.html")), FakeTime())

    listing = uvo.list_leaf(client_for(server), LAYOUT_C_LEAF)

    assert listing.docs == []
    assert listing.warnings == ["layout_c_not_collected:20"]
    assert server.urls() == [f"{HUB}/{LAYOUT_C_LEAF}"], "the walk does not page through 187 pages of detail records"


@pytest.mark.unit
def test_should_walk_pages_until_a_page_repeats_and_pace_at_two_seconds() -> None:
    first = fixture_text("uvo-leaf-extdoc.html")
    second = "".join(f'<tr><td><a href="/extdoc/{900 + n}">{n}\N{EN DASH}2020</a></td><td>0{n}.01.2020</td></tr>' for n in range(1, 4))
    pages = {f"{HUB}/{EXTDOC_LEAF}": first, f"{HUB}/{EXTDOC_LEAF}?page=2": second, f"{HUB}/{EXTDOC_LEAF}?page=3": first}
    server = Server(lambda r: html(pages[str(r.url)]) if str(r.url) in pages else html("", 404), FakeTime())

    listing = uvo.list_leaf(client_for(server), EXTDOC_LEAF)

    assert len(listing.docs) == 23
    assert server.urls() == list(pages)
    assert all(gap >= 2.0 - 1e-6 for gap in server.gaps()), server.gaps()
    assert listing.warnings == []


@pytest.mark.unit
def test_should_stop_at_an_empty_or_missing_page() -> None:
    first = fixture_text("uvo-leaf-direct.html")
    server = Server(lambda r: html(first) if "page=" not in str(r.url) else httpx.Response(404, text="x"), FakeTime())

    listing = uvo.list_leaf(client_for(server), DIRECT_LEAF)

    assert len(listing.docs) == 20
    assert len(server.requests) == 2


@pytest.mark.unit
def test_should_read_the_hub_with_one_request() -> None:
    server = Server(lambda _r: html(fixture_text("uvo-hub.html")), FakeTime())

    assert uvo.read_hub(client_for(server)) == []
    assert server.urls() == [HUB]
