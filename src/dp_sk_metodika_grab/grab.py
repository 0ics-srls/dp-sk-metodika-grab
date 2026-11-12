"""Per-item grab into ``<dir>/<safe itemId>/``; the item's ``meta.kind`` picks the source: ``fs`` (a Financna sprava section listing) or ``pdf``
(one MF SR year, the NBS page or one UVO leaf).

Output per item: ``<source_id>.pdf``, ``<source_id>.meta.json`` (sidecar for the convert class) and ``_coverage.json``. A PDF already on disk with a valid magic
and a sidecar of the same ``version`` is not requested again (idempotent restart). Source config keys the Host resolved to JSON null count as absent.
UVO is refused unless ``uvoRobotsAck`` is true (decision D141); the check runs before the first request of the run.
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from dp_sk_metodika_grab import download, entries, fs, ids, mfsr, nbs, robots, uvo
from dp_sk_metodika_grab.errors import CONFIG_ERROR, TRANSIENT_ERROR, GrabError
from dp_sk_metodika_grab.http import DEFAULT_ALLOWED_HOSTS, MIN_DELAY, Client
from dp_sk_metodika_grab.model import SITE_MFSR, SITE_NBS, SITE_UVO, SITES

if TYPE_CHECKING:
    import httpx

log = logging.getLogger("dp_sk_metodika_grab")
Progress = Callable[[int, str], None]
KIND_FS = "fs"
KIND_PDF = "pdf"
KINDS = (KIND_FS, KIND_PDF)
_MIN_YEAR, _MAX_YEAR = 1990, 2100
_PROGRESS_EVERY = 10


@dataclass(frozen=True)
class GrabDeps:
    """The ports of a run: transport (None = real network), sleep and clock (pacing) and the wall clock for the ``fetched`` stamp."""

    transport: httpx.BaseTransport | None = None
    sleep: Callable[[float], None] = field(default=time.sleep)
    clock: Callable[[], float] = field(default=time.monotonic)
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class Item:
    """A validated item of the detect step."""

    key: str
    item_id: str
    version: str
    kind: str
    scope: str  # the FS section or the pdf site: what ``only`` names
    year: int | None = None
    leaf: str | None = None

    @property
    def directory_name(self) -> str:
        return ids.safe_name(self.item_id)


@dataclass(frozen=True)
class Settings:
    items: tuple[Item, ...]
    directory: Path
    only: tuple[tuple[str, str], ...]
    max_docs: int | None
    delay: float
    verify_tls: bool
    max_pdf_bytes: int
    base_url: str | None
    uvo_ack: bool
    dry_run: bool
    hosts: tuple[str, ...]


def _number(params: dict[str, Any], name: str, *, minimum: float) -> float | None:
    value = params.get(name)
    if value is None:
        return None
    if not isinstance(value, int | float) or isinstance(value, bool) or value < minimum:
        raise GrabError(CONFIG_ERROR, f"{name} must be a number >= {minimum}, got {value!r}")
    return float(value)


def _item(entry: Any) -> Item:
    if not isinstance(entry, dict) or not entry.get("key"):
        raise GrabError(CONFIG_ERROR, f"item needs a key: {entry!r}")
    key, meta = entry["key"], entry.get("meta")
    if not isinstance(meta, dict) or meta.get("kind") not in KINDS:
        raise GrabError(CONFIG_ERROR, f"item {key}: meta.kind must be one of {list(KINDS)}")
    item_id = meta.get("itemId")
    if not isinstance(item_id, str) or not item_id:
        raise GrabError(CONFIG_ERROR, f"item {key}: meta.itemId is required")
    version = meta.get("version", "1")
    if not isinstance(version, str) or not version:
        raise GrabError(CONFIG_ERROR, f"item {key}: meta.version must be a non-empty string")
    if meta["kind"] == KIND_FS:
        section = meta.get("section")
        if section not in fs.SECTION_NAMES:
            raise GrabError(CONFIG_ERROR, f"item {key}: meta.section must be one of {list(fs.SECTION_NAMES)}, got {section!r}")
        return Item(key, item_id, version, KIND_FS, section)
    return _pdf_item(key, item_id, version, meta)


def _pdf_item(key: str, item_id: str, version: str, meta: dict[str, Any]) -> Item:
    site = meta.get("site")
    if site not in SITES:
        raise GrabError(CONFIG_ERROR, f"item {key}: meta.site must be one of {list(SITES)}, got {site!r}")
    year, leaf = meta.get("year"), meta.get("leaf")
    if site == SITE_MFSR and (not isinstance(year, int) or isinstance(year, bool) or not _MIN_YEAR <= year <= _MAX_YEAR):
        raise GrabError(CONFIG_ERROR, f"item {key}: meta.year must be a year for {SITE_MFSR}, got {year!r}")
    if site == SITE_UVO and leaf not in uvo.LEAVES:
        raise GrabError(CONFIG_ERROR, f"item {key}: meta.leaf must be one of the UVO leaves, got {leaf!r}")
    return Item(key, item_id, version, KIND_PDF, site, year=year if site == SITE_MFSR else None, leaf=leaf if site == SITE_UVO else None)


def _only(raw: Any) -> tuple[tuple[str, str], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise GrabError(CONFIG_ERROR, "only must be an array of {section|site, docId}")
    pairs: list[tuple[str, str]] = []
    for entry in raw:
        scope = entry.get("section") or entry.get("site") if isinstance(entry, dict) else None
        doc_id = entry.get("docId") if isinstance(entry, dict) else None
        if not isinstance(scope, str) or not isinstance(doc_id, str) or not doc_id:
            raise GrabError(CONFIG_ERROR, f"only entries need section|site and docId (the source_id): {entry!r}")
        pairs.append((scope, doc_id))
    return tuple(pairs)


def parse_settings(raw_params: dict[str, Any]) -> Settings:
    params = {name: value for name, value in raw_params.items() if value is not None}  # the Host resolves an undeclared Source config key to null
    raw_items = params.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise GrabError(CONFIG_ERROR, "items must be a non-empty array")
    items = tuple(_item(entry) for entry in raw_items)
    directory = params.get("dir")
    if not isinstance(directory, str) or not directory:
        raise GrabError(CONFIG_ERROR, "dir is required")
    delay = _number(params, "delaySeconds", minimum=MIN_DELAY)
    max_docs = _number(params, "maxDocs", minimum=1)
    max_pdf = _number(params, "maxPdfBytes", minimum=1)
    verify_tls = params.get("verifyTls", True)
    if not isinstance(verify_tls, bool):
        raise GrabError(CONFIG_ERROR, "verifyTls must be a boolean")
    base_url = params.get("baseUrl")
    if base_url is not None and (not isinstance(base_url, str) or urlsplit(base_url).scheme not in {"http", "https"} or not urlsplit(base_url).hostname):
        raise GrabError(CONFIG_ERROR, f"baseUrl must be an http(s) URL, got {base_url!r}")
    hosts = params.get("allowedHosts", list(DEFAULT_ALLOWED_HOSTS))
    if not isinstance(hosts, list) or not all(isinstance(h, str) for h in hosts):
        raise GrabError(CONFIG_ERROR, "allowedHosts must be an array of host names")
    return Settings(
        items=items,
        directory=Path(directory),
        only=_only(params.get("only")),
        max_docs=int(max_docs) if max_docs is not None else None,
        delay=delay if delay is not None else MIN_DELAY,
        verify_tls=verify_tls,
        max_pdf_bytes=int(max_pdf) if max_pdf is not None else download.DEFAULT_MAX_PDF_BYTES,
        base_url=base_url,
        uvo_ack=params.get("uvoRobotsAck") is True,
        dry_run=params.get("dryRun") is True,
        hosts=tuple(hosts),
    )


def long_path(path: Path) -> Path:
    """On Windows the 260 character limit would break the 200 character ids below a deep ``dir``: use the extended-length form there (no-op elsewhere)."""
    if os.name != "nt":
        return path
    absolute = str(path.absolute())
    return path if absolute.startswith("\\\\") else Path("\\\\?\\" + absolute)


def write_atomic(path: Path, data: bytes) -> None:
    target = long_path(path)
    temp = target.with_name(target.name + ".tmp")
    try:
        temp.write_bytes(data)
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)


def write_json(path: Path, value: Any) -> None:
    write_atomic(path, json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))


def _confined(directory: Path, name: str) -> Path:
    target = directory / name
    if target.resolve().parent != directory.resolve():
        raise GrabError(CONFIG_ERROR, f"{name!r} would leave {directory}")
    return target


def _already_done(directory: Path, entry: entries.Entry, version: str) -> bool:
    """A valid PDF and a sidecar of the same version: nothing to fetch."""
    pdf, side = directory / f"{entry.source_id}.pdf", directory / f"{entry.source_id}.meta.json"
    try:
        with long_path(pdf).open("rb") as handle:
            if handle.read(len(download.PDF_MAGIC)) != download.PDF_MAGIC:
                return False
        sidecar = json.loads(long_path(side).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(sidecar, dict) and sidecar.get("version") == version and sidecar.get("pdf_file") == pdf.name


@dataclass
class _Run:
    """The state of one run: the client, the settings and what was read once per run (the UVO hub)."""

    settings: Settings
    client: Client
    now: Callable[[], datetime]
    hub_read: bool = False


def _log_robots(item: Item) -> None:
    if item.kind == KIND_FS:
        log.info("robots.txt of www.financnasprava.sk: none (404), no policy")
    elif item.scope == SITE_MFSR:
        log.info("robots.txt of mfsr.sk: %s -- paths under these prefixes are refused", robots.rule_text("www.mfsr.sk"))
    elif item.scope == SITE_NBS:
        log.info("robots.txt of nbs.sk: %s", robots.rule_text("nbs.sk"))
    else:
        log.warning("robots.txt of www.uvo.gov.sk says %r; running only because uvoRobotsAck is true (%s)", robots.UVO_RULE, robots.UVO_DECISION)


def _list_item(run: _Run, item: Item) -> tuple[list[entries.Entry], list[str]]:
    client = run.client
    if item.kind == KIND_FS:
        walk = fs.walk_section(client, item.scope, fs.sections()[item.scope])
        return [entries.from_fs(d) for d in walk.docs], walk.warnings
    warnings: list[str] = []
    if item.scope == SITE_MFSR:
        assert item.year is not None  # validated with the item
        listing = mfsr.list_year(client, item.year)
    elif item.scope == SITE_NBS:
        listing = nbs.list_all(client)
    else:
        assert item.leaf is not None  # validated with the item
        if not run.hub_read:
            run.hub_read = True  # the hub is cross-checked once per Run: its warnings belong to the first UVO item
            warnings.extend(uvo.read_hub(client))
        listing = uvo.list_leaf(client, item.leaf)
    return [entries.from_pdf(d) for d in listing.docs], [*warnings, *listing.warnings]


def _select(run: _Run, item: Item, listed: list[entries.Entry]) -> list[entries.Entry]:
    chosen = sorted(listed, key=lambda e: e.source_id)
    if run.settings.only:
        wanted = {doc_id for scope, doc_id in run.settings.only if scope == item.scope}
        chosen = [e for e in chosen if e.source_id in wanted]
    if run.settings.max_docs is not None:
        chosen = chosen[: run.settings.max_docs]
    return chosen


def _take(run: _Run, item: Item, directory: Path, entry: entries.Entry, coverage: dict[str, Any]) -> str:
    """Fetches (or recognises) one document; returns ``taken``, ``existing`` or ``skipped``."""
    settings = run.settings
    if not ids.is_safe_id(entry.source_id):
        coverage["skipped"].append({"item_ref": entry.pdf_url, "reason": "unsafe_source_id"})
        return "skipped"
    if robots.is_disallowed(entry.pdf_url):
        coverage["skipped"].append({"item_ref": entry.source_id, "reason": robots.SKIP_REASON})
        return "skipped"
    if _already_done(directory, entry, item.version):
        return "existing"
    fetched_at = run.now().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = download.download_pdf(run.client, entry.pdf_url, settings.max_pdf_bytes)
    side = _confined(directory, f"{entry.source_id}.meta.json")
    if result.body is None:
        write_json(side, entries.sidecar(entry, item.version, fetched_at, pdf_bytes=None, source_filename=result.filename, skip_reason=result.reason))
        coverage["skipped"].append({"item_ref": entry.source_id, "reason": result.reason})
        return "skipped"
    write_atomic(_confined(directory, f"{entry.source_id}.pdf"), result.body)  # the sidecar is written last: it marks the document complete
    write_json(side, entries.sidecar(entry, item.version, fetched_at, pdf_bytes=len(result.body), source_filename=result.filename))
    return "taken"


def grab_item(run: _Run, item: Item, on_document: Callable[[int, int], None]) -> dict[str, Any]:
    base = run.settings.directory
    directory = base / item.directory_name
    if directory.resolve().parent != base.resolve():
        raise GrabError(CONFIG_ERROR, f"item {item.key}: directory {item.directory_name!r} would leave {base}")
    _log_robots(item)
    listed, warnings = _list_item(run, item)
    chosen = _select(run, item, listed)
    directory.mkdir(parents=True, exist_ok=True)
    coverage: dict[str, Any] = {
        "fonte": listed[0].fonte if listed else (entries.FONTE_FS if item.kind == KIND_FS else item.scope),
        "itemId": item.item_id,
        "listed": len(listed),
        "taken": 0,
        "skipped": [],
        "warnings": warnings,
        "sample_filter": bool(run.settings.only or run.settings.max_docs is not None),
    }
    taken = existing = 0
    claimed: set[str] = set()
    for position, entry in enumerate(chosen, start=1):
        if entry.source_id in claimed:
            coverage["skipped"].append({"item_ref": entry.pdf_url, "reason": "duplicate_source_id"})
            continue
        claimed.add(entry.source_id)
        outcome = _take(run, item, directory, entry, coverage)
        taken += outcome == "taken"
        existing += outcome == "existing"
        if position % _PROGRESS_EVERY == 0:
            on_document(position, len(chosen))
    coverage["taken"] = taken + existing
    write_json(directory / "_coverage.json", coverage)
    return {
        "key": item.key, "itemId": item.item_id, "path": str(directory), "status": "done" if listed else "empty", "listed": len(listed),
        "taken": coverage["taken"], "skipped": len(coverage["skipped"]), "skipped_existing": existing, "warnings": warnings,
    }  # fmt: skip


def require_uvo_ack(settings: Settings) -> None:
    if any(item.scope == SITE_UVO for item in settings.items) and not settings.uvo_ack:
        uvo.require_ack(None)


def _document_progress(on_progress: Progress, position: int, total: int, key: str) -> Callable[[int, int], None]:
    def report(done: int, count: int) -> None:
        on_progress(int((position + done / max(count, 1)) * 100 / total), f"{key}: {done}/{count}")

    return report


def run_grab(raw_params: dict[str, Any], deps: GrabDeps, on_progress: Progress) -> dict[str, Any]:
    """Tries every item; if any failed raises GrabError (config_error if any failure is a config error, else transient)."""
    settings = parse_settings(raw_params)
    require_uvo_ack(settings)  # before the first request of the run
    if settings.dry_run:
        planned = [{"key": i.key, "path": str(settings.directory / i.directory_name), "status": "planned"} for i in settings.items]
        return {"listed": 0, "taken": 0, "skipped": 0, "skipped_existing": 0, "files": planned, "dryRun": True}
    client = Client(
        transport=deps.transport, clock=deps.clock, sleep=deps.sleep, delay=settings.delay, verify=settings.verify_tls, allowed_hosts=settings.hosts,
        host_delays=uvo.HOST_DELAYS, replay_base=settings.base_url,
    )  # fmt: skip
    run = _Run(settings, client, deps.now)
    files: list[dict[str, Any]] = []
    failures: list[tuple[str, GrabError]] = []
    total = len(settings.items)
    try:
        for position, item in enumerate(settings.items):
            try:
                files.append(grab_item(run, item, _document_progress(on_progress, position, total, item.key)))
            except GrabError as error:
                failures.append((item.key, error))
            on_progress(int((position + 1) * 100 / total), f"{position + 1}/{total} {item.key}")
    finally:
        client.close()
    if failures:
        code = CONFIG_ERROR if any(error.code == CONFIG_ERROR for _, error in failures) else TRANSIENT_ERROR
        detail = "; ".join(f"{key} ({error})" for key, error in failures)
        msg = f"{len(failures)} of {total} items failed: {detail}"
        raise GrabError(code, msg)
    return {
        "listed": sum(f["listed"] for f in files),
        "taken": sum(f["taken"] for f in files),
        "skipped": sum(f["skipped"] for f in files),
        "skipped_existing": sum(f["skipped_existing"] for f in files),
        "files": files,
    }
