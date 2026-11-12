"""MF SR Financny spravodajca year pages: the legacy PdfAdaptersTests.Mfsr_* parse case plus the recorded 2025 page (108 hrefs = 36 documents) and 2005 (zips only)."""
from __future__ import annotations

import httpx
import pytest

from conftest import FakeTime, Server, fixture_text, html
from dp_sk_metodika_grab import ids, mfsr
from dp_sk_metodika_grab.http import Client

YEAR_2025 = "https://www.mfsr.sk/sk/financie/financny-spravodajca/2025/"


@pytest.mark.unit
def test_should_parse_code_group_and_a_clean_title_from_a_card_header() -> None:
    page = """<div class="card-header">Opatrenie MF/012345/2026-36 (1,2 MB) <a href="/x/opatrenie.pdf">Stiahnuť</a></div>"""

    docs = mfsr.parse(page, "https://www.mfsr.sk/sk/financie/financny-spravodajca/2026/")

    assert len(docs) == 1
    assert docs[0].group == "2026"
    assert docs[0].code == "MF/012345/2026-36"
    assert docs[0].title == "Opatrenie MF/012345/2026-36"  # size + label stripped
    assert docs[0].pdf_url == "https://www.mfsr.sk/x/opatrenie.pdf"  # relative href resolved
    assert docs[0].site == "mfsr-spravodajca"


@pytest.mark.unit
def test_should_build_the_year_urls_from_the_range_and_not_from_the_index() -> None:
    assert mfsr.year_url(2025) == YEAR_2025
    assert mfsr.year_url(2024, "http://replay.test:8765") == "http://replay.test:8765/sk/financie/financny-spravodajca/2024/"


@pytest.mark.unit
def test_should_fall_back_to_h3_h4_li_and_then_to_the_anchor_for_the_title() -> None:
    page = (
        '<h3>Metodické usmernenie MF/000001/2024-1 (300 kB) <a href="/a.PDF">Otvoriť</a></h3>'
        '<ul><li>Oznámenie k dani Archívny dokument <a href="/b.pdf">Stiahnuť</a></li></ul>'
        '<p><a href="/c.pdf">Samostatný odkaz</a></p>'
    )

    docs = mfsr.parse(page, YEAR_2025)

    assert [d.title for d in docs] == ["Metodické usmernenie MF/000001/2024-1", "Oznámenie k dani", "Samostatný odkaz"]
    assert docs[0].pdf_url == "https://www.mfsr.sk/a.PDF"  # the selector is case-insensitive
    assert docs[2].code is None


@pytest.mark.unit
def test_should_take_36_unique_documents_from_the_108_hrefs_of_the_recorded_2025_page() -> None:
    page = fixture_text("mfsr-2025.html")
    assert page.lower().count('.pdf"') >= 108

    docs = mfsr.parse(page, YEAR_2025)

    assert len(docs) == 36
    assert len({d.pdf_url for d in docs}) == 36
    assert {d.group for d in docs} == {"2025"}
    assert all(d.pdf_url.startswith("https://www.mfsr.sk/files/archiv/") for d in docs)
    assert all(d.title for d in docs)
    for doc in docs:
        for noise in ("kB)", "MB)", "Stiahnuť", "Aktuálny dokument", "Archívny dokument"):
            assert noise not in doc.title, (noise, doc.title)
    first = docs[0]
    assert first.code == "MF/016959/2025-724"
    assert first.title.startswith("Usmernenie Ministerstva financií Slovenskej republiky č. MF/016959/2025-724")
    assert len({ids.source_id(d.pdf_url) for d in docs}) == 36


@pytest.mark.unit
def test_should_list_a_year_with_one_request_and_never_request_the_redirecting_index() -> None:
    server = Server(lambda r: html(fixture_text("mfsr-2025.html")) if r.url.path.endswith("/2025/") else html("", 404), FakeTime())

    listing = mfsr.list_year(Client(server.transport(), server.time.clock, server.time.sleep), 2025)

    assert len(listing.docs) == 36
    assert listing.warnings == []
    assert server.urls() == [YEAR_2025]


@pytest.mark.unit
def test_should_yield_an_empty_item_and_a_zip_archives_only_marker_for_a_year_without_pdfs() -> None:
    page = fixture_text("mfsr-2005-zips.html")
    assert ".zip" in page
    server = Server(lambda _r: html(page), FakeTime())

    listing = mfsr.list_year(Client(server.transport(), server.time.clock, server.time.sleep), 2005)

    assert listing.docs == []
    assert listing.warnings == ["zip_archives_only"]
    assert len(server.requests) == 1


@pytest.mark.unit
def test_should_not_warn_when_an_empty_year_has_no_archives_either() -> None:
    server = Server(lambda _r: html("<html><body><h1>2001</h1></body></html>"), FakeTime())

    listing = mfsr.list_year(Client(server.transport(), server.time.clock, server.time.sleep), 2001)

    assert listing.docs == []
    assert listing.warnings == []


@pytest.mark.unit
def test_should_warn_when_the_year_page_is_gone() -> None:
    server = Server(lambda _r: httpx.Response(404, text="no"), FakeTime())

    listing = mfsr.list_year(Client(server.transport(), server.time.clock, server.time.sleep), 2030)

    assert listing.docs == []
    assert listing.warnings == ["listing_http_404"]
