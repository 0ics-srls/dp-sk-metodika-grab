"""The UVO robots gate (decision D141): uvo.gov.sk answers ``User-agent: * / Disallow: /``, so the adapter is off unless ``uvoRobotsAck`` is true.

The first tests cover the gate function; the run-level tests (zero requests to uvo.gov.sk through ``run_grab``) are in this file as well.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from conftest import fixture_bytes, fixture_text, html
from dp_sk_metodika_grab import uvo
from dp_sk_metodika_grab.errors import CONFIG_ERROR, GrabError
from harness import fs_item, mfsr_item, read_json, run, uvo_item, zavery_pages

EXTDOC_LEAF = "vseobecne-metodicke-usmernenia-k-zakonu-c-343-2015-zz"
DIRECT_LEAF = "prehlad-vykladovych-stanovisk-uradu-zakon-c-343-2015-z-z"
LAYOUT_C_LEAF = "metodicke-usmernenia-k-zakonu-c-25-2006-zz"
REAL_PDF = fixture_bytes("pdf/uvo-extdoc-53262.pdf")


def uvo_route(hub: str | None = None, body: bytes = REAL_PDF, content_type: str = "application/octet-stream") -> Any:
    """A recorded UVO: hub, leaf pages (page 2 is a 404) and octet-stream documents with a Content-Disposition file name."""
    pages = {
        uvo.HUB: hub if hub is not None else fixture_text("uvo-hub.html"),
        uvo.leaf_url(EXTDOC_LEAF): fixture_text("uvo-leaf-extdoc.html"),
        uvo.leaf_url(DIRECT_LEAF): fixture_text("uvo-leaf-direct.html"),
        uvo.leaf_url(LAYOUT_C_LEAF): fixture_text("uvo-leaf-layout-c.html"),
    }

    def route(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url in pages:
            return html(pages[url])
        if "/extdoc/" in request.url.path or request.url.path.endswith(".pdf"):
            return httpx.Response(
                200, content=body, headers={"content-type": content_type, "content-disposition": "attachment; filename=vmu_z3432015_7-2026_jed_aktualizacia.pdf"}
            )
        return html("not found", 404)

    return route


def uvo_requests(server: Any) -> list[str]:
    return [url for url in server.urls() if "uvo.gov.sk" in url]


@pytest.mark.unit
@pytest.mark.parametrize("ack", [None, False, "true", 1, 0, "", "yes"])
def test_should_refuse_uvo_unless_the_acknowledgement_is_exactly_true(ack: object) -> None:
    with pytest.raises(GrabError) as caught:
        uvo.require_ack(ack)

    error = caught.value
    assert error.code == CONFIG_ERROR
    assert "robots" in str(error)
    assert "User-agent: *" in str(error)
    assert "Disallow: /" in str(error)
    assert "D141" in str(error)
    assert "uvoRobotsAck" in str(error)


@pytest.mark.unit
def test_should_let_uvo_pass_when_the_acknowledgement_is_true() -> None:
    uvo.require_ack(True)  # noqa: FBT003


@pytest.mark.unit
def test_should_pace_uvo_at_two_seconds() -> None:
    assert uvo.HOST_DELAYS == {"www.uvo.gov.sk": 2.0}


# ------------------------------------------------------------ run level (through main.main, recording fake transport)


@pytest.mark.unit
@pytest.mark.parametrize("ack", [{}, {"uvoRobotsAck": None}, {"uvoRobotsAck": False}, {"uvoRobotsAck": "true"}])
def test_should_make_zero_requests_to_uvo_without_the_acknowledgement(tmp_path: Path, ack: dict[str, Any]) -> None:
    events, server = run({"items": [uvo_item(EXTDOC_LEAF)], **ack}, tmp_path, uvo_route())

    assert server.requests == []
    assert events[-1]["type"] == "error"
    assert events[-1]["code"] == "config_error"
    message = events[-1]["message"]
    assert "robots" in message
    assert "Disallow: /" in message
    assert "D141" in message
    assert not (tmp_path / "raw").exists()


@pytest.mark.unit
def test_should_refuse_the_whole_run_and_touch_no_site_when_a_uvo_item_comes_without_the_acknowledgement(tmp_path: Path) -> None:
    events, server = run({"items": [mfsr_item(2025), fs_item("zavery-komisii"), uvo_item(EXTDOC_LEAF)]}, tmp_path, uvo_route())

    assert server.requests == []
    assert events[-1]["code"] == "config_error"


@pytest.mark.unit
def test_should_grab_a_leaf_after_the_acknowledgement_paced_at_two_seconds_with_the_hub_read_first(tmp_path: Path) -> None:
    events, server = run({"items": [uvo_item(EXTDOC_LEAF)], "uvoRobotsAck": True, "maxDocs": 2}, tmp_path, uvo_route())

    assert events[-1]["type"] == "result", events
    assert events[-1]["data"]["listed"] == 20
    assert events[-1]["data"]["taken"] == 2
    urls = uvo_requests(server)
    assert urls[0] == uvo.HUB
    assert urls[1] == uvo.leaf_url(EXTDOC_LEAF)
    assert urls[2] == uvo.leaf_url(EXTDOC_LEAF) + "?page=2"
    assert all(gap >= 2.0 - 1e-6 for gap in server.gaps()), server.gaps()
    directory = tmp_path / "raw" / f"pdf_uvo-metodicke_{EXTDOC_LEAF}"
    sidecars = sorted(directory.glob("*.meta.json"))
    assert len(sidecars) == 2
    first = read_json(sidecars[0])
    assert first["fonte"] == first["section"] == "uvo-metodicke"
    assert first["group"] == EXTDOC_LEAF
    assert first["source_id"].startswith("extdoc_")
    assert first["source_filename"] == "vmu_z3432015_7-2026_jed_aktualizacia.pdf"
    assert first["published"] is not None
    assert first["code"]
    assert first["year"] == int(first["published"][:4])
    assert read_json(directory / "_coverage.json")["warnings"] == []


@pytest.mark.unit
def test_should_grab_the_direct_pdf_layout_with_the_fileadmin_ids(tmp_path: Path) -> None:
    events, _server = run({"items": [uvo_item(DIRECT_LEAF)], "uvoRobotsAck": True, "maxDocs": 20}, tmp_path, uvo_route(content_type="application/pdf"))

    assert events[-1]["data"]["taken"] == 20
    directory = tmp_path / "raw" / f"pdf_uvo-metodicke_{DIRECT_LEAF}"
    assert (directory / "fileadmin_dokumenty_vykladove_stanoviska_2015_vykladove_stanovisko_1-2021.pdf").is_file()


@pytest.mark.unit
def test_should_read_the_hub_once_per_run_and_warn_about_a_new_leaf_in_the_first_item_only(tmp_path: Path) -> None:
    hub = fixture_text("uvo-hub.html").replace("</body>", f'<a href="{uvo.HUB}/novy-zakon-c-1-2030-zz">novy</a></body>')

    events, server = run(
        {"items": [uvo_item(EXTDOC_LEAF), uvo_item(DIRECT_LEAF)], "uvoRobotsAck": True, "maxDocs": 1}, tmp_path, uvo_route(hub=hub)
    )

    assert events[-1]["type"] == "result", events
    assert uvo_requests(server).count(uvo.HUB) == 1
    first = read_json(tmp_path / "raw" / f"pdf_uvo-metodicke_{EXTDOC_LEAF}" / "_coverage.json")
    second = read_json(tmp_path / "raw" / f"pdf_uvo-metodicke_{DIRECT_LEAF}" / "_coverage.json")
    assert first["warnings"] == ["new_leaf:novy-zakon-c-1-2030-zz"]
    assert second["warnings"] == []


@pytest.mark.unit
def test_should_complete_layout_c_as_an_empty_item_with_the_marker_and_never_silently(tmp_path: Path) -> None:
    events, server = run({"items": [uvo_item(LAYOUT_C_LEAF)], "uvoRobotsAck": True}, tmp_path, uvo_route())

    assert events[-1]["type"] == "result", events
    assert events[-1]["data"]["taken"] == 0
    assert events[-1]["data"]["files"][0]["status"] == "empty"
    coverage = read_json(tmp_path / "raw" / f"pdf_uvo-metodicke_{LAYOUT_C_LEAF}" / "_coverage.json")
    assert coverage["warnings"] == ["layout_c_not_collected:20"]
    assert coverage["listed"] == 0
    assert uvo_requests(server) == [uvo.HUB, uvo.leaf_url(LAYOUT_C_LEAF)]


@pytest.mark.unit
def test_should_skip_an_html_answer_as_not_a_pdf_and_keep_the_octet_stream_pdf(tmp_path: Path) -> None:
    events, _server = run(
        {"items": [uvo_item(EXTDOC_LEAF)], "uvoRobotsAck": True, "maxDocs": 2}, tmp_path, uvo_route(body=b"<html>nope</html>", content_type="text/html")
    )

    assert events[-1]["data"]["taken"] == 0
    coverage = read_json(tmp_path / "raw" / f"pdf_uvo-metodicke_{EXTDOC_LEAF}" / "_coverage.json")
    assert {s["reason"] for s in coverage["skipped"]} == {"not_a_pdf"}


@pytest.mark.unit
def test_should_never_include_uvo_in_the_requests_of_other_sites(tmp_path: Path) -> None:
    _events, server = run({"items": [fs_item("zavery-komisii")], "uvoRobotsAck": False}, tmp_path, lambda r: html(zavery_pages().get(str(r.url), ""), 200))

    assert uvo_requests(server) == []
    assert server.requests, "the other site is grabbed normally"
