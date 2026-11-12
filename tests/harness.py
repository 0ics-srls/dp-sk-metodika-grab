"""Helpers for the entrypoint tests: item builders, a scripted multi-site route and a runner that drives ``main.main`` with the fake clock."""
from __future__ import annotations

import io
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

import main as grab_main
from conftest import PDF_BYTES, FakeTime, Server, fixture_text, html
from dp_sk_metodika_grab import fs, nbs, uvo
from dp_sk_metodika_grab.grab import GrabDeps

NOW = datetime(2026, 11, 12, 10, 30, 5, tzinfo=UTC)
ZAVERY = fs.sections()["zavery-komisii"]
POKYNY = fs.sections()["metodicke-pokyny"]


def fs_item(section: str, version: str = "1") -> dict[str, Any]:
    return {"key": f"fs:{section}|v{version}", "meta": {"kind": "fs", "itemId": f"fs:{section}", "version": version, "section": section}}


def mfsr_item(year: int, version: str = "1") -> dict[str, Any]:
    item_id = f"pdf:mfsr-spravodajca:{year}"
    return {"key": f"{item_id}|v{version}", "meta": {"kind": "pdf", "itemId": item_id, "version": version, "site": "mfsr-spravodajca", "year": year}}


def nbs_item(version: str = "1") -> dict[str, Any]:
    return {"key": f"pdf:nbs-metodicke:all|v{version}", "meta": {"kind": "pdf", "itemId": "pdf:nbs-metodicke:all", "version": version, "site": "nbs-metodicke"}}


def uvo_item(leaf: str, version: str = "1") -> dict[str, Any]:
    item_id = f"pdf:uvo-metodicke:{leaf}"
    return {"key": f"{item_id}|v{version}", "meta": {"kind": "pdf", "itemId": item_id, "version": version, "site": "uvo-metodicke", "leaf": leaf}}


def zavery_pages() -> dict[str, str]:
    page = fixture_text("fs-zavery.html")
    return {ZAVERY: page, fs.page_url(ZAVERY, 2): page}  # the site repeats page 1 on page 2


def zavery_docs() -> list[fs.FsDocument]:
    return fs.parse_listing(fixture_text("fs-zavery.html"), ZAVERY, "zavery-komisii")


def site_route(pages: dict[str, str], failing: set[str] | None = None, pdf_body: bytes = PDF_BYTES) -> Callable[[httpx.Request], httpx.Response]:
    """Listing pages by exact URL; every PDF-ish URL answers a PDF unless it is in ``failing`` (404); anything else is a 404."""
    failing = failing or set()

    def route(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url in pages:
            return html(pages[url])
        if url in failing:
            return httpx.Response(404, text="gone")
        path = request.url.path.lower()
        if path.endswith(".pdf") or "/extdoc/" in path or "/dokument/" in path:
            return httpx.Response(200, content=pdf_body, headers={"content-type": "application/pdf"})
        return html("not found", 404)

    return route


def request_line(params: dict[str, Any], action: str = "execute") -> str:
    return json.dumps({"_action": action, "_meta": {"executionId": "e1"}, **params})


def run(
    params: dict[str, Any], tmp_path: Path, route: Callable[[httpx.Request], httpx.Response], clock: FakeTime | None = None
) -> tuple[list[dict[str, Any]], Server]:
    """Runs one ``execute`` through ``main.main``; returns the protocol events and the recording server."""
    clock = clock or FakeTime()
    server = Server(route, clock)
    deps = GrabDeps(transport=server.transport(), sleep=clock.sleep, clock=clock.clock, now=lambda: NOW)
    out = io.StringIO()
    grab_main.main(io.StringIO(request_line({"dir": str(tmp_path / "raw"), **params}) + "\n"), out, deps)
    return [json.loads(line) for line in out.getvalue().splitlines()], server


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


NBS_PAGE = nbs.PAGE_URL
UVO_HUB = uvo.HUB
