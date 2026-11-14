# dp-sk-metodika-grab

Proc-protocol class (Python 3.12, stdin NDJSON, Protocol 1.1) of the `dp-sk-metodika` package: downloads the Slovak guidance PDFs of four sources into
`<dir>/<safe itemId>/` for the convert class.

| Item (`itemId`) | `meta` | Source |
|---|---|---|
| `fs:<section>` | `kind fs`, `section` = `metodicke-pokyny` / `metodicke-usmernenia` / `zavery-komisii` / `prehlady-zmluv-zdz` | financnasprava.sk listings, `/_N` pages until an empty page or no fresh PDF (cap 500) |
| `pdf:mfsr-spravodajca:<yyyy>` | `kind pdf`, `site`, `year` | one MF SR year page (the redirecting index is never requested) |
| `pdf:nbs-metodicke:all` | `kind pdf`, `site` | the single NBS page |
| `pdf:uvo-metodicke:<leaf>` | `kind pdf`, `site`, `leaf` (one of 7 constants) | UVO leaf pages, `?page=N`; OFF unless `uvoRobotsAck` is true |

`meta.version` (`1` or `1-<hash8 of refreshToken>`) is written into every sidecar; a PDF on disk with a valid `%PDF-` magic and a sidecar of the same version is
not requested again.

## Output per item

`<source_id>.pdf`, `<source_id>.meta.json`, `_coverage.json` (`fonte, itemId, listed, taken, skipped[{item_ref, reason}], warnings[], sample_filter`).
`source_id` = slug of the PDF URL path (`ids.py`). A failed PDF (HTTP error, `not_a_pdf`, `too_large`, `fetch_failed`) keeps its sidecar with `pdf_file` and
`pdf_bytes` null and `skip_reason` set, and is listed in `skipped`; a PDF the robots rules forbid (`robots`) or with an unsafe id has no sidecar. The sidecar has
the contract keys (`fonte, source_id, legacy_doc_id, section, group, title, pdf_url, listing_url, code, number, dept, year, doc_type, category, published,
pdf_file, pdf_bytes, fetched, version`) plus `source_filename` (Content-Disposition) and `skip_reason`; unknown values are JSON null.
Coverage markers in `warnings`: `zip_archives_only` (MF SR year with archives only), `layout_c_not_collected:<rows>` and `new_leaf:<slug>` (UVO), `listing_http_<status>`.

## Settings (JSON null = absent)

`items`, `dir`, `only` (`[{section|site, docId}]`, docId = source_id), `maxDocs` (per item, ascending source_id), `delaySeconds` (>= 0.6, UVO always >= 2),
`verifyTls`, `maxPdfBytes` (default 40 MB), `baseUrl` (replay origin that stands in for all four sites), `uvoRobotsAck`, `dryRun`, `allowedHosts`.
Allowed hosts: `www.financnasprava.sk`, `www.mfsr.sk`, `nbs.sk`, `www.uvo.gov.sk` (+ the host of `baseUrl`); redirects only inside that list. HTTP 403/429 is a
`config_error` naming the body type, 5xx and resets are retried 3 times with back-off.

## Robots posture

mfsr.sk disallows `/components` and `/thumb` (refused, skip reason `robots`, the rule is logged); nbs.sk allows all; financnasprava.sk has no robots.txt (404);
uvo.gov.sk answers `User-agent: * / Disallow: /`, so the run is refused with a `config_error` (before any request) unless `uvoRobotsAck` is true (decision D141).

## Document URL encoding (v0.1.2)

The URL of a Financna sprava document (`pdf_url`, `source_url` in the package) has its path percent-encoded: a space becomes `%20`, an existing `%XX` stays (no double encoding). `source_id` (decoded path slug) and `legacy_doc_id` (derived from the href as written) do not change, so a re-run creates no duplicates (D151, D156; `tests/unit/test_fs_encoding.py`). MF SR, NBS and UVO URLs are untouched.

## Tests

```
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest -m "not integration" tests
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m mypy .
docker build -f Dockerfile.test .          # then: docker run --rm --network none <image>
```

No test touches the network: httpx `MockTransport`, a socket guard in `tests/conftest.py`, recorded answers in `tests/fixtures` (see `PROVENANCE.md`).
Nothing is ever fetched from uvo.gov.sk by the tests (D141).

Test image (2026-11-12, Windows Docker Desktop, base layers cached): `docker build -f Dockerfile.test .` about 15 s, image 85.8 MB; the container runs the 188
tests in 2.5 s offline. Production image `Dockerfile`: 48.3 MB.
