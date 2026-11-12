"""PDF download: magic bytes decide (UVO serves application/octet-stream), the Content-Disposition file name is kept, the size cap and 404 are skips."""
from __future__ import annotations

import httpx
import pytest

from conftest import PDF_BYTES, FakeTime, Server, fixture_bytes, html, pdf
from dp_sk_metodika_grab.download import content_disposition_filename, download_pdf
from dp_sk_metodika_grab.errors import CONFIG_ERROR, GrabError
from dp_sk_metodika_grab.http import Client

URL = "https://www.uvo.gov.sk/extdoc/53262"


def client_for(server: Server) -> Client:
    return Client(server.transport(), server.time.clock, server.time.sleep)


@pytest.mark.unit
def test_should_accept_an_octet_stream_body_that_starts_with_the_pdf_magic_and_keep_the_file_name() -> None:
    real = fixture_bytes("pdf/uvo-extdoc-53262.pdf")
    headers = {"content-disposition": "attachment; filename=vmu_z3432015_7-2026_jed_aktualizacia.pdf"}
    server = Server(lambda _r: pdf(real, "application/octet-stream", headers), FakeTime())

    result = download_pdf(client_for(server), URL, 40_000_000)

    assert result.reason is None
    assert result.body == real
    assert result.filename == "vmu_z3432015_7-2026_jed_aktualizacia.pdf"
    assert result.content_type == "application/octet-stream"


@pytest.mark.unit
def test_should_skip_an_html_body_as_not_a_pdf_even_when_the_type_says_pdf() -> None:
    server = Server(lambda _r: pdf(b"<html>interstitial</html>", "application/pdf"), FakeTime())

    result = download_pdf(client_for(server), URL, 40_000_000)

    assert result.body is None
    assert result.reason == "not_a_pdf"


@pytest.mark.unit
def test_should_skip_an_html_page_as_not_a_pdf() -> None:
    server = Server(lambda _r: html("<html>Chyba</html>"), FakeTime())

    assert download_pdf(client_for(server), URL, 40_000_000).reason == "not_a_pdf"


@pytest.mark.unit
def test_should_skip_a_404_with_its_status_as_the_reason() -> None:
    server = Server(lambda _r: httpx.Response(404, text="gone"), FakeTime())

    result = download_pdf(client_for(server), URL, 40_000_000)

    assert (result.body, result.reason) == (None, "http_404")


@pytest.mark.unit
def test_should_skip_a_pdf_above_the_size_cap_as_too_large() -> None:
    server = Server(lambda _r: pdf(PDF_BYTES), FakeTime())

    result = download_pdf(client_for(server), URL, 1000)

    assert (result.body, result.reason) == (None, "too_large")


@pytest.mark.unit
def test_should_skip_a_source_that_keeps_failing_with_5xx_after_the_retries() -> None:
    server = Server(lambda _r: httpx.Response(503, text="down"), FakeTime())

    result = download_pdf(client_for(server), URL, 40_000_000)

    assert result.body is None
    assert result.reason == "fetch_failed"
    assert len(server.requests) == 4


@pytest.mark.unit
def test_should_not_swallow_a_403() -> None:
    server = Server(lambda _r: httpx.Response(403, text="no"), FakeTime())

    with pytest.raises(GrabError) as caught:
        download_pdf(client_for(server), URL, 40_000_000)

    assert caught.value.code == CONFIG_ERROR


@pytest.mark.unit
@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("attachment; filename=a.pdf", "a.pdf"),
        ('attachment;filename="Stanovisko OFS č. 2_2022.pdf";', "Stanovisko OFS č. 2_2022.pdf"),
        ("attachment; filename*=UTF-8''Metodick%C3%BD%20pokyn.pdf", "Metodický pokyn.pdf"),
        ("inline", None),
        ("", None),
    ],
)
def test_should_read_the_file_name_of_a_content_disposition_header(header: str, expected: str | None) -> None:
    assert content_disposition_filename(header) == expected
