"""The ``execute`` action through the Proc protocol: per item a directory with ``<source_id>.pdf``, ``<source_id>.meta.json`` and ``_coverage.json``."""
from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest

import main as grab_main
from conftest import PDF_BYTES, FakeTime, fixture_bytes, fixture_text, html
from dp_sk_metodika_grab import fs, ids
from dp_sk_metodika_grab.grab import GrabDeps
from dp_sk_metodika_grab.http import Client
from harness import NOW, ZAVERY, fs_item, mfsr_item, nbs_item, read_json, request_line, run, site_route, zavery_docs, zavery_pages

SIDECAR_KEYS = [
    "fonte", "source_id", "legacy_doc_id", "section", "group", "title", "pdf_url", "listing_url", "code", "number", "dept", "year", "doc_type", "category",
    "published", "pdf_file", "pdf_bytes", "fetched", "version", "source_filename", "skip_reason",
]  # fmt: skip
ITEM_DIR = "fs_zavery-komisii"


def pdf_requests(server: Any) -> list[str]:
    return [url for url in server.urls() if url.lower().endswith(".pdf")]


def item_path(tmp_path: Path, name: str = ITEM_DIR) -> Path:
    return tmp_path / "raw" / name


@pytest.mark.unit
def test_should_speak_the_protocol_terminate_unknown_action_and_malformed_input() -> None:
    out = io.StringIO()
    stdin = io.StringIO("not json\n" + request_line({}, "dance") + "\n" + request_line({}, "terminate") + "\n" + request_line({}, "execute") + "\n")

    code = grab_main.main(stdin, out)

    events = [json.loads(line) for line in out.getvalue().splitlines()]
    assert code == 1
    assert [e["type"] for e in events] == ["error", "error"]
    assert all(e["code"] == "config_error" for e in events)
    assert "unknown action" in events[1]["message"]


@pytest.mark.unit
def test_should_write_two_pdfs_three_sidecars_and_the_coverage_when_one_pdf_is_a_404(tmp_path: Path) -> None:
    docs = zavery_docs()
    assert len(docs) == 3
    failing_doc = sorted(docs, key=lambda d: ids.source_id(d.pdf_url))[1]
    failing_id = ids.source_id(failing_doc.pdf_url)

    events, server = run({"items": [fs_item("zavery-komisii")]}, tmp_path, site_route(zavery_pages(), failing={failing_doc.pdf_url}))

    assert events[-1]["type"] == "result", events
    result = events[-1]["data"]
    assert (result["listed"], result["taken"], result["skipped"], result["skipped_existing"]) == (3, 2, 1, 0)
    assert any(e["type"] == "progress" for e in events)
    directory = item_path(tmp_path)
    assert sorted(p.name for p in directory.glob("*.pdf")) == sorted(f"{ids.source_id(d.pdf_url)}.pdf" for d in docs if d is not failing_doc)
    assert len(list(directory.glob("*.meta.json"))) == 3
    assert (directory / "_coverage.json").is_file()
    assert not list(directory.glob("*.tmp"))
    assert len(server.requests) == 2 + 3, "two listing pages and three PDFs"

    coverage = read_json(directory / "_coverage.json")
    assert coverage == {
        "fonte": "financnasprava", "itemId": "fs:zavery-komisii", "listed": 3, "taken": 2, "sample_filter": False,
        "skipped": [{"item_ref": failing_id, "reason": "http_404"}], "warnings": [],
    }  # fmt: skip

    failed = read_json(directory / f"{failing_id}.meta.json")
    assert (failed["pdf_file"], failed["pdf_bytes"], failed["skip_reason"]) == (None, None, "http_404")
    assert failed["pdf_url"] == failing_doc.pdf_url


@pytest.mark.unit
def test_should_write_a_sidecar_with_the_contract_keys_and_null_for_unknowns(tmp_path: Path) -> None:
    doc = zavery_docs()[0]
    sid = ids.source_id(doc.pdf_url)

    run({"items": [fs_item("zavery-komisii", "1-abcd1234")]}, tmp_path, site_route(zavery_pages()))

    sidecar = read_json(item_path(tmp_path) / f"{sid}.meta.json")
    assert list(sidecar) == SIDECAR_KEYS
    assert sidecar["fonte"] == "financnasprava"
    assert sidecar["source_id"] == sid
    assert sidecar["legacy_doc_id"] == doc.doc_id
    assert sidecar["section"] == "zavery-komisii"
    assert sidecar["group"] is None
    assert sidecar["title"] == doc.title
    assert sidecar["pdf_url"] == doc.pdf_url
    assert sidecar["listing_url"] == ZAVERY
    assert (sidecar["code"], sidecar["number"], sidecar["dept"], sidecar["doc_type"]) == (None, None, None, None)
    assert sidecar["year"] == doc.year
    assert sidecar["published"] == doc.published
    assert sidecar["pdf_file"] == f"{sid}.pdf"
    assert sidecar["pdf_bytes"] == len(PDF_BYTES)
    assert sidecar["fetched"] == "2026-11-12T10:30:05Z"
    assert sidecar["version"] == "1-abcd1234"
    assert sidecar["source_filename"] is None
    assert sidecar["skip_reason"] is None
    assert "" not in sidecar.values()
    assert 0 not in [v for v in sidecar.values() if not isinstance(v, bool)]


@pytest.mark.unit
def test_should_carry_the_code_number_dept_and_type_of_a_coded_financna_sprava_title(tmp_path: Path) -> None:
    pages = {fs.sections()["metodicke-pokyny"]: fixture_text("fs-pokyny-1.html"), fs.page_url(fs.sections()["metodicke-pokyny"], 2): fixture_text("fs-pokyny-3-empty.html")}
    first = fs.parse_listing(pages[fs.sections()["metodicke-pokyny"]], "https://www.financnasprava.sk/x", "metodicke-pokyny")[0]

    wanted = ids.source_id(first.pdf_url)

    run({"items": [fs_item("metodicke-pokyny")], "only": [{"section": "metodicke-pokyny", "docId": wanted}]}, tmp_path, site_route(pages))

    sidecar = read_json(item_path(tmp_path, "fs_metodicke-pokyny") / f"{wanted}.meta.json")
    assert sidecar["code"] == "12/DZPaU/2026/MP"
    assert (sidecar["number"], sidecar["dept"], sidecar["year"], sidecar["doc_type"]) == (12, "DZPaU", 2026, "MP")
    assert sidecar["category"] == "Priame_dane_uct"
    assert sidecar["published"] == "2026-08-18"
    assert sidecar["legacy_doc_id"] == "12_DZPaU_2026_MP"


@pytest.mark.unit
def test_should_make_no_pdf_request_when_the_same_version_runs_again(tmp_path: Path) -> None:
    route = site_route(zavery_pages())
    run({"items": [fs_item("zavery-komisii")]}, tmp_path, route)

    events, server = run({"items": [fs_item("zavery-komisii")]}, tmp_path, route)

    result = events[-1]["data"]
    assert (result["listed"], result["taken"], result["skipped_existing"], result["skipped"]) == (3, 3, 3, 0)
    assert pdf_requests(server) == []
    assert len(server.requests) == 2, "only the listing pages are read again"


@pytest.mark.unit
def test_should_retry_only_the_failed_pdf_when_the_same_version_runs_again(tmp_path: Path) -> None:
    docs = zavery_docs()
    run({"items": [fs_item("zavery-komisii")]}, tmp_path, site_route(zavery_pages(), failing={docs[0].pdf_url}))

    events, server = run({"items": [fs_item("zavery-komisii")]}, tmp_path, site_route(zavery_pages()))

    assert pdf_requests(server) == [docs[0].pdf_url]
    assert events[-1]["data"]["taken"] == 3
    assert read_json(item_path(tmp_path) / f"{ids.source_id(docs[0].pdf_url)}.meta.json")["skip_reason"] is None


@pytest.mark.unit
def test_should_refetch_everything_when_the_version_changes(tmp_path: Path) -> None:
    route = site_route(zavery_pages())
    run({"items": [fs_item("zavery-komisii", "1")]}, tmp_path, route)

    events, server = run({"items": [fs_item("zavery-komisii", "1-0a0a0a0a")]}, tmp_path, route)

    assert len(pdf_requests(server)) == 3
    assert events[-1]["data"]["skipped_existing"] == 0
    sid = ids.source_id(zavery_docs()[0].pdf_url)
    assert read_json(item_path(tmp_path) / f"{sid}.meta.json")["version"] == "1-0a0a0a0a"


@pytest.mark.unit
def test_should_refetch_a_pdf_on_disk_that_has_lost_its_magic(tmp_path: Path) -> None:
    route = site_route(zavery_pages())
    run({"items": [fs_item("zavery-komisii")]}, tmp_path, route)
    victim = item_path(tmp_path) / f"{ids.source_id(zavery_docs()[1].pdf_url)}.pdf"
    victim.write_bytes(b"<html>truncated")

    _events, server = run({"items": [fs_item("zavery-komisii")]}, tmp_path, route)

    assert len(pdf_requests(server)) == 1
    assert victim.read_bytes().startswith(b"%PDF-")


@pytest.mark.unit
def test_should_honour_only_and_mark_the_run_as_a_sample(tmp_path: Path) -> None:
    docs = zavery_docs()
    wanted = ids.source_id(docs[1].pdf_url)

    events, server = run({"items": [fs_item("zavery-komisii")], "only": [{"section": "zavery-komisii", "docId": wanted}]}, tmp_path, site_route(zavery_pages()))

    assert events[-1]["data"]["taken"] == 1
    assert [p.name for p in item_path(tmp_path).glob("*.pdf")] == [f"{wanted}.pdf"]
    assert len(pdf_requests(server)) == 1
    assert read_json(item_path(tmp_path) / "_coverage.json")["sample_filter"] is True
    assert read_json(item_path(tmp_path) / "_coverage.json")["listed"] == 3


@pytest.mark.unit
def test_should_take_nothing_of_a_section_the_only_list_does_not_name(tmp_path: Path) -> None:
    events, server = run({"items": [fs_item("zavery-komisii")], "only": [{"section": "metodicke-pokyny", "docId": "x"}]}, tmp_path, site_route(zavery_pages()))

    assert events[-1]["data"]["taken"] == 0
    assert pdf_requests(server) == []


@pytest.mark.unit
def test_should_take_the_first_documents_in_ascending_source_id_with_max_docs(tmp_path: Path) -> None:
    expected = sorted(ids.source_id(d.pdf_url) for d in zavery_docs())[:2]

    events, _server = run({"items": [fs_item("zavery-komisii")], "maxDocs": 2}, tmp_path, site_route(zavery_pages()))

    assert events[-1]["data"]["taken"] == 2
    assert sorted(p.stem for p in item_path(tmp_path).glob("*.pdf")) == expected
    assert read_json(item_path(tmp_path) / "_coverage.json")["sample_filter"] is True


@pytest.mark.unit
@pytest.mark.parametrize("bad", [0.59, 0, -1, "1", True])
def test_should_refuse_a_delay_below_the_minimum_or_of_a_wrong_type(tmp_path: Path, bad: object) -> None:
    events, server = run({"items": [fs_item("zavery-komisii")], "delaySeconds": bad}, tmp_path, site_route(zavery_pages()))

    assert events[-1]["type"] == "error"
    assert events[-1]["code"] == "config_error"
    assert "delaySeconds" in events[-1]["message"]
    assert server.requests == []


@pytest.mark.unit
def test_should_pace_requests_at_the_configured_delay(tmp_path: Path) -> None:
    _events, server = run({"items": [fs_item("zavery-komisii")], "delaySeconds": 1.5}, tmp_path, site_route(zavery_pages()))

    assert len(server.requests) == 5
    assert all(gap >= 1.5 - 1e-6 for gap in server.gaps()), server.gaps()


@pytest.mark.unit
def test_should_pace_at_least_06_seconds_by_default(tmp_path: Path) -> None:
    _events, server = run({"items": [fs_item("zavery-komisii")]}, tmp_path, site_route(zavery_pages()))

    assert all(gap >= 0.6 - 1e-6 for gap in server.gaps()), server.gaps()


@pytest.mark.unit
def test_should_treat_every_null_setting_as_absent(tmp_path: Path) -> None:
    nulls = dict.fromkeys(("sections", "sites", "annoFrom", "annoTo", "uvoRobotsAck", "only", "maxDocs", "baseUrl", "delaySeconds", "verifyTls", "refreshToken", "tokenBudget", "dryRun", "state", "maxPdfBytes", "allowedHosts"))  # fmt: skip

    events, _server = run({"items": [fs_item("zavery-komisii")], **nulls}, tmp_path, site_route(zavery_pages()))

    assert events[-1]["type"] == "result", events[-1]
    assert events[-1]["data"]["taken"] == 3


@pytest.mark.unit
def test_should_drop_a_hostile_source_id_and_write_nothing_outside_the_item_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = ids.source_id
    docs = zavery_docs()
    hostile_url = docs[0].pdf_url
    monkeypatch.setattr("dp_sk_metodika_grab.grab.ids.source_id", lambda url: "../../evil" if url == hostile_url else real(url))

    events, _server = run({"items": [fs_item("zavery-komisii")]}, tmp_path, site_route(zavery_pages()))

    assert events[-1]["data"]["taken"] == 2
    coverage = read_json(item_path(tmp_path) / "_coverage.json")
    assert coverage["skipped"] == [{"item_ref": hostile_url, "reason": "unsafe_source_id"}]
    written = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}
    assert all(name.startswith(f"raw/{ITEM_DIR}/") for name in written), written
    assert not (tmp_path / "evil.pdf").exists()
    assert not (tmp_path.parent / "evil.pdf").exists()


@pytest.mark.unit
@pytest.mark.parametrize("item_id", ["..", "../../outside", "a/../../b", "fs:/abs/olute"])
def test_should_keep_the_item_directory_inside_dir_whatever_the_item_id_says(tmp_path: Path, item_id: str) -> None:
    item = {"key": "k", "meta": {"kind": "fs", "itemId": item_id, "version": "1", "section": "zavery-komisii"}}

    run({"items": [item]}, tmp_path, site_route(zavery_pages()))

    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert written, "the run still works with a sanitised directory name"
    assert all((tmp_path / "raw").resolve() in p.resolve().parents for p in written), written


@pytest.mark.unit
def test_should_not_collide_when_two_items_share_one_dir_and_even_one_document(tmp_path: Path) -> None:
    pages = zavery_pages()
    other = fs.sections()["metodicke-usmernenia"]
    pages[other] = fixture_text("fs-zavery.html")  # the same three documents listed under a second section
    pages[fs.page_url(other, 2)] = fixture_text("fs-zavery.html")

    events, _server = run({"items": [fs_item("zavery-komisii"), fs_item("metodicke-usmernenia")]}, tmp_path, site_route(pages))

    assert events[-1]["data"]["taken"] == 6
    first, second = item_path(tmp_path), item_path(tmp_path, "fs_metodicke-usmernenia")
    assert len(list(first.glob("*.pdf"))) == len(list(second.glob("*.pdf"))) == 3
    assert read_json(first / "_coverage.json")["itemId"] == "fs:zavery-komisii"
    assert read_json(second / "_coverage.json")["itemId"] == "fs:metodicke-usmernenia"
    sid = ids.source_id(zavery_docs()[0].pdf_url)
    assert read_json(first / f"{sid}.meta.json")["section"] == "zavery-komisii"
    assert read_json(second / f"{sid}.meta.json")["section"] == "metodicke-usmernenia"


@pytest.mark.unit
def test_should_complete_a_listing_without_documents_as_an_empty_item(tmp_path: Path) -> None:
    pages = {fs.sections()["metodicke-pokyny"]: fixture_text("fs-pokyny-3-empty.html")}

    events, server = run({"items": [fs_item("metodicke-pokyny")]}, tmp_path, site_route(pages))

    assert events[-1]["type"] == "result", events
    data = events[-1]["data"]
    assert (data["listed"], data["taken"]) == (0, 0)
    assert data["files"][0]["status"] == "empty"
    coverage = read_json(item_path(tmp_path, "fs_metodicke-pokyny") / "_coverage.json")
    assert (coverage["listed"], coverage["taken"], coverage["skipped"], coverage["warnings"]) == (0, 0, [], [])
    assert len(server.requests) == 1


@pytest.mark.unit
def test_should_skip_a_pdf_above_max_pdf_bytes_and_still_write_its_sidecar(tmp_path: Path) -> None:
    events, _server = run({"items": [fs_item("zavery-komisii")], "maxPdfBytes": 1000}, tmp_path, site_route(zavery_pages()))

    assert events[-1]["data"]["taken"] == 0
    assert events[-1]["data"]["skipped"] == 3
    coverage = read_json(item_path(tmp_path) / "_coverage.json")
    assert {s["reason"] for s in coverage["skipped"]} == {"too_large"}
    assert not list(item_path(tmp_path).glob("*.pdf"))
    assert len(list(item_path(tmp_path).glob("*.meta.json"))) == 3


@pytest.mark.unit
def test_should_plan_only_on_a_dry_run(tmp_path: Path) -> None:
    events, server = run({"items": [fs_item("zavery-komisii")], "dryRun": True}, tmp_path, site_route(zavery_pages()))

    assert events[-1]["data"]["dryRun"] is True
    assert {f["status"] for f in events[-1]["data"]["files"]} == {"planned"}
    assert server.requests == []
    assert not (tmp_path / "raw").exists()


@pytest.mark.unit
def test_should_send_every_request_to_the_replay_server_when_base_url_is_set(tmp_path: Path) -> None:
    pages = {url.replace("https://www.financnasprava.sk", "http://replay.test:8765"): text for url, text in zavery_pages().items()}
    seen: list[str] = []

    def route(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return site_route(pages)(request)

    events, _server = run({"items": [fs_item("zavery-komisii")], "baseUrl": "http://replay.test:8765"}, tmp_path, route)

    assert events[-1]["data"]["taken"] == 3
    assert seen
    assert all(url.startswith("http://replay.test:8765/") for url in seen), seen
    sid = ids.source_id(zavery_docs()[0].pdf_url)
    assert read_json(item_path(tmp_path) / f"{sid}.meta.json")["pdf_url"] == zavery_docs()[0].pdf_url, "the sidecar keeps the canonical URL"


@pytest.mark.unit
def test_should_refuse_a_base_url_that_is_not_http(tmp_path: Path) -> None:
    events, _server = run({"items": [fs_item("zavery-komisii")], "baseUrl": "ftp://x"}, tmp_path, site_route(zavery_pages()))

    assert events[-1]["code"] == "config_error"


@pytest.mark.unit
def test_should_pass_verify_tls_to_the_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bool] = []
    real = Client

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(bool(kwargs["verify"]))
        return real(*args, **kwargs)

    monkeypatch.setattr("dp_sk_metodika_grab.grab.Client", spy)

    run({"items": [fs_item("zavery-komisii")], "verifyTls": False}, tmp_path, site_route(zavery_pages()))
    run({"items": [fs_item("zavery-komisii")]}, tmp_path / "again", site_route(zavery_pages()))

    assert seen == [False, True]


@pytest.mark.unit
def test_should_end_with_a_config_error_naming_the_item_when_a_listing_answers_403(tmp_path: Path) -> None:
    events, _server = run(
        {"items": [fs_item("zavery-komisii")]}, tmp_path, lambda _r: httpx.Response(403, text="denied", headers={"content-type": "text/html"})
    )

    assert (events[-1]["type"], events[-1]["code"]) == ("error", "config_error")
    assert "fs:zavery-komisii|v1" in events[-1]["message"]


@pytest.mark.unit
def test_should_go_on_with_the_other_items_when_one_fails(tmp_path: Path) -> None:
    pages = zavery_pages()  # metodicke-pokyny is not served: its first page is a 404 = an empty item, not a failure
    events, _server = run({"items": [fs_item("metodicke-pokyny"), fs_item("zavery-komisii")]}, tmp_path, site_route(pages))

    assert events[-1]["data"]["taken"] == 3
    coverage = read_json(item_path(tmp_path, "fs_metodicke-pokyny") / "_coverage.json")
    assert coverage["warnings"] == ["listing_http_404"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "item",
    [
        {"key": "x", "meta": {"kind": "gazzetta", "itemId": "x"}},
        {"key": "x", "meta": {"kind": "fs", "itemId": "fs:nope", "section": "nope"}},
        {"key": "x", "meta": {"kind": "pdf", "itemId": "pdf:mfsr-spravodajca:x", "site": "mfsr-spravodajca"}},
        {"key": "x", "meta": {"kind": "pdf", "itemId": "pdf:nope", "site": "nope"}},
        {"key": "x", "meta": {"kind": "pdf", "itemId": "pdf:uvo-metodicke:nope", "site": "uvo-metodicke", "leaf": "nope"}},
        {"key": "x", "meta": {"kind": "fs", "section": "zavery-komisii"}},
        {"meta": {"kind": "fs", "itemId": "a", "section": "zavery-komisii"}},
    ],
)
def test_should_refuse_a_malformed_item_as_a_config_error(tmp_path: Path, item: dict[str, Any]) -> None:
    events, server = run({"items": [item]}, tmp_path, site_route(zavery_pages()))

    assert events[-1]["code"] == "config_error"
    assert server.requests == []


@pytest.mark.unit
def test_should_refuse_missing_dir_and_empty_items() -> None:
    clock = FakeTime()
    out = io.StringIO()

    grab_main.main(io.StringIO(request_line({"items": [fs_item("zavery-komisii")]}) + "\n" + request_line({"dir": "x", "items": []}) + "\n"), out, GrabDeps(sleep=clock.sleep, clock=clock.clock))

    assert [json.loads(line)["code"] for line in out.getvalue().splitlines()] == ["config_error", "config_error"]


# ---------------------------------------------------------------- MF SR


def mfsr_pages(year: int = 2025) -> dict[str, str]:
    return {f"https://www.mfsr.sk/sk/financie/financny-spravodajca/{year}/": fixture_text("mfsr-2025.html")}


@pytest.mark.unit
def test_should_grab_a_mfsr_year_with_year_as_group_and_the_code(tmp_path: Path) -> None:
    events, server = run({"items": [mfsr_item(2025)], "maxDocs": 3}, tmp_path, site_route(mfsr_pages()))

    data = events[-1]["data"]
    assert (data["listed"], data["taken"]) == (36, 3)
    directory = item_path(tmp_path, "pdf_mfsr-spravodajca_2025")
    first = min(directory.glob("*.meta.json"))
    sidecar = read_json(first)
    assert sidecar["fonte"] == "mfsr-spravodajca"
    assert sidecar["section"] == "mfsr-spravodajca"
    assert (sidecar["group"], sidecar["year"]) == ("2025", 2025)
    assert sidecar["listing_url"] == "https://www.mfsr.sk/sk/financie/financny-spravodajca/2025/"
    assert sidecar["source_id"].startswith("files_archiv_")
    assert sidecar["pdf_url"].startswith("https://www.mfsr.sk/files/archiv/")
    assert server.urls()[0] == "https://www.mfsr.sk/sk/financie/financny-spravodajca/2025/"
    assert "https://www.mfsr.sk/sk/financie/financny-spravodajca/" not in server.urls(), "the redirecting index is never requested"


@pytest.mark.unit
def test_should_complete_a_year_with_zip_archives_only_as_an_empty_item_with_the_marker(tmp_path: Path) -> None:
    pages = {"https://www.mfsr.sk/sk/financie/financny-spravodajca/2005/": fixture_text("mfsr-2005-zips.html")}

    events, _server = run({"items": [mfsr_item(2005)]}, tmp_path, site_route(pages))

    assert events[-1]["data"]["taken"] == 0
    coverage = read_json(item_path(tmp_path, "pdf_mfsr-spravodajca_2005") / "_coverage.json")
    assert coverage["warnings"] == ["zip_archives_only"]
    assert coverage["listed"] == 0
    assert not list(item_path(tmp_path, "pdf_mfsr-spravodajca_2005").glob("*.pdf"))


@pytest.mark.unit
def test_should_refuse_a_robots_disallowed_mfsr_path_without_requesting_it_and_log_the_rule(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    page = (
        '<li class="card"><h3 class="card-header"><a href="/components/mfsrweb/file_archiv/secret.pdf">Skryty dokument MF/000002/2025-1</a></h3></li>'
        '<li class="card"><h3 class="card-header"><a href="/files/archiv/9/Verejny.pdf">Verejny dokument MF/000001/2025-1</a></h3></li>'
    )
    pages = {"https://www.mfsr.sk/sk/financie/financny-spravodajca/2025/": page}
    caplog.set_level(logging.INFO, logger="dp_sk_metodika_grab")

    events, server = run({"items": [mfsr_item(2025)]}, tmp_path, site_route(pages))

    assert events[-1]["data"]["taken"] == 1
    assert not any("/components/" in url for url in server.urls())
    coverage = read_json(item_path(tmp_path, "pdf_mfsr-spravodajca_2025") / "_coverage.json")
    assert coverage["skipped"] == [{"item_ref": "components_mfsrweb_file_archiv_secret", "reason": "robots"}]
    assert coverage["listed"] == 2
    assert not list(item_path(tmp_path, "pdf_mfsr-spravodajca_2025").glob("components*"))
    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "Disallow: /components" in text
    assert "Disallow: /thumb" in text


# ---------------------------------------------------------------- NBS


@pytest.mark.unit
def test_should_grab_nbs_with_canonical_urls_and_uuid_ids(tmp_path: Path) -> None:
    from harness import NBS_PAGE  # noqa: PLC0415

    events, server = run({"items": [nbs_item()]}, tmp_path, site_route({NBS_PAGE: fixture_text("nbs.html")}))

    assert (events[-1]["data"]["listed"], events[-1]["data"]["taken"]) == (12, 12)
    directory = item_path(tmp_path, "pdf_nbs-metodicke_all")
    dokument = [read_json(p) for p in directory.glob("dokument_*.meta.json")]
    assert len(dokument) == 3
    for sidecar in dokument:
        uuid = sidecar["source_id"].removeprefix("dokument_")
        assert sidecar["pdf_url"] == f"https://nbs.sk/dokument/{uuid}/stiahnut"
        assert sidecar["legacy_doc_id"] == uuid
        assert (sidecar["fonte"], sidecar["section"], sidecar["group"]) == ("nbs-metodicke", "nbs-metodicke", None)
    assert all("?force" not in url for url in server.urls())
    assert len(list(directory.glob("*.pdf"))) == 12


# ---------------------------------------------------------------- Financna sprava drive-through with the real PDF


@pytest.mark.unit
def test_should_store_the_real_pdf_bytes_unchanged(tmp_path: Path) -> None:
    real = fixture_bytes("pdf/fs-zapis-2014.pdf")

    events, _server = run({"items": [fs_item("zavery-komisii")]}, tmp_path, site_route(zavery_pages(), pdf_body=real))

    sid = ids.source_id(zavery_docs()[0].pdf_url)
    assert (item_path(tmp_path) / f"{sid}.pdf").read_bytes() == real
    assert read_json(item_path(tmp_path) / f"{sid}.meta.json")["pdf_bytes"] == len(real) == 216549
    assert events[-1]["data"]["taken"] == 3


@pytest.mark.unit
def test_should_report_an_html_body_as_not_a_pdf(tmp_path: Path) -> None:
    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".pdf"):
            return html("<html>cookie wall</html>")
        return site_route(zavery_pages())(request)

    events, _server = run({"items": [fs_item("zavery-komisii")]}, tmp_path, route)

    assert events[-1]["data"]["taken"] == 0
    assert {s["reason"] for s in read_json(item_path(tmp_path) / "_coverage.json")["skipped"]} == {"not_a_pdf"}


@pytest.mark.unit
def test_should_have_the_fs_catalogue_for_every_section() -> None:
    assert set(fs.SECTION_NAMES) == set(fs.sections())
    assert NOW.isoformat().startswith("2026-11-12")
