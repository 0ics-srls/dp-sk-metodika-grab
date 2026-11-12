"""NBS metodicke usmernenia page: the legacy Nbs_* case plus the recorded page (9 /_img PDFs and 3 /dokument/<uuid>/stiahnut)."""
from __future__ import annotations

import pytest

from conftest import FakeTime, Server, fixture_text, html
from dp_sk_metodika_grab import ids, nbs
from dp_sk_metodika_grab.http import Client

UUID_A = "8a55d8a5-dea0-43a3-a164-96201563e0f5"
UUID_B = "b6012d22-b140-49d0-9eee-84e16c2cbaf6"


@pytest.mark.unit
def test_should_capture_pdf_and_dokument_links_with_uuid_override_and_without_the_trailing_label() -> None:
    page = """
        <p>Stanovisko k niečomu <a href="/_img/stanovisko.pdf">Stanovisko</a></p>
        <li>Odporúčanie <a href="/dokument/abc123-def/stiahnut">Stiahnuť</a></li>
        <a href="/other/skip.pdf">no _img</a>
        """

    docs = nbs.parse(page, "https://nbs.sk/page/")

    assert len(docs) == 2
    assert [d.pdf_url for d in docs] == ["https://nbs.sk/_img/stanovisko.pdf", "https://nbs.sk/dokument/abc123-def/stiahnut"]
    assert docs[1].id_override == "abc123-def"
    assert docs[1].doc_id == "abc123-def"
    assert docs[0].title == "Stanovisko k niečomu"  # trailing "Stanovisko" label dropped
    assert docs[1].title == "Odporúčanie"
    assert docs[0].site == "nbs-metodicke"
    assert docs[0].group is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "href",
    [
        f"/dokument/{UUID_A}/stiahnut?force=false?force=false",
        f"https://nbs.sk/dokument/{UUID_A}/stiahnut/?force=true",
        f"/dokument/{UUID_A}/stiahnut/",
        f"/dokument/{UUID_A}/stiahnut",
    ],
)
def test_should_normalise_the_doubled_query_and_the_trailing_slash(href: str) -> None:
    docs = nbs.parse(f'<p>Dokument <a href="{href}">Stiahnuť</a></p>', "https://nbs.sk/page/")

    assert [d.pdf_url for d in docs] == [f"https://nbs.sk/dokument/{UUID_A}/stiahnut"]
    assert docs[0].id_override == UUID_A


@pytest.mark.unit
def test_should_count_one_document_when_the_same_link_is_written_in_two_forms() -> None:
    page = f'<p>A <a href="/dokument/{UUID_A}/stiahnut?force=false?force=false">x</a></p><p>A <a href="https://nbs.sk/dokument/{UUID_A}/stiahnut/?force=true">x</a></p>'

    assert len(nbs.parse(page, "https://nbs.sk/page/")) == 1


@pytest.mark.unit
def test_should_parse_the_recorded_page_into_12_documents() -> None:
    docs = nbs.parse(fixture_text("nbs.html"), nbs.PAGE_URL)

    assert len(docs) == 12
    images = [d for d in docs if "/_img/" in d.pdf_url]
    dokuments = [d for d in docs if "/dokument/" in d.pdf_url]
    assert (len(images), len(dokuments)) == (9, 3)
    assert all(d.pdf_url.lower().endswith(".pdf") for d in images)
    assert all(d.id_override is None for d in images)
    for doc in dokuments:
        assert doc.pdf_url == f"https://nbs.sk/dokument/{doc.id_override}/stiahnut"
        assert doc.doc_id == doc.id_override
        assert ids.source_id(doc.pdf_url) == f"dokument_{doc.id_override}"
    assert {d.id_override for d in dokuments} >= {UUID_A, UUID_B}
    assert all(d.title and "?force" not in d.title for d in docs)
    by_url = {d.pdf_url: d for d in docs}
    assert by_url[f"https://nbs.sk/dokument/{UUID_B}/stiahnut"].title.startswith("Stanovisko odboru ochrany finančných spotrebiteľov Národnej banky Slovenska č. 2/2022")
    assert len({ids.source_id(d.pdf_url) for d in docs}) == 12


@pytest.mark.unit
def test_should_list_the_single_page_with_one_request() -> None:
    server = Server(lambda _r: html(fixture_text("nbs.html")), FakeTime())

    listing = nbs.list_all(Client(server.transport(), server.time.clock, server.time.sleep))

    assert len(listing.docs) == 12
    assert server.urls() == [nbs.PAGE_URL]
