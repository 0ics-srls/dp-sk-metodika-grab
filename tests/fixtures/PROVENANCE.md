# Fixtures

All HTML files are real answers recorded by the planning session of phase 81b on 2026-11-12 (browser User-Agent, 0.7 s apart), trimmed to stay below 100 KB:
scripts, styles, svg, comments and inline styles removed, whitespace collapsed; the MF SR pages additionally lose the site header/menu/footer and all but two
of the hidden `archivToolbar` rows. The recorded structure of the lists (anchors, rows, titles, hrefs) is untouched. Nothing here was fetched by the class
tests or by the executor; the tests never touch the network (httpx `MockTransport`, a socket guard in `conftest.py`).

| File | Source answer |
|---|---|
| `fs-pokyny-1.html`, `fs-pokyny-2.html` | financnasprava.sk `metodicke-pokyny` pages 1 and 2 (10 documents each, single-quoted hrefs) |
| `fs-pokyny-3-empty.html` | page 3: HTTP 200 with no documents (stops the walk) |
| `fs-usmernenia-1.html` | `metodicke-usmernenia` page 1 (10 of 41 documents; the live pages 2-5 are rebuilt synthetically in `test_fs_walk.py`) |
| `fs-zavery.html` | `zavery-zo-zasadnuti-MFSR` (3 documents; `_2` repeats it) |
| `fs-prehlady-1.html`, `fs-prehlady-2.html` | `prehlady-zmluv-zdz` filtered-results URL, pages `_1` and `_2` (7 documents, identical) |
| `mfsr-2025.html` | mfsr.sk year page 2025 (108 `.pdf` hrefs = 36 unique, `card-header` titles, hidden `/components/` toolbar rows) |
| `mfsr-2005-zips.html` | mfsr.sk year page 2005 (only `FS_nn_yy.zip` archives, no PDF) |
| `mfsr-urls-715.json` | the 715 PDF hrefs of the years 1999-2026 as listed on the year pages (`{year: [href...]}`), used for the distinct-id test |
| `nbs.html` | nbs.sk page of metodicke usmernenia, stanoviska a odporucania (9 `/_img/` PDFs, 3 `/dokument/<uuid>/stiahnut`) |
| `uvo-hub.html` | uvo.gov.sk hub `metodicke-usmernenia-a-vykladove-stanoviska` (7 leaf links) |
| `uvo-leaf-extdoc.html` | leaf `vseobecne-metodicke-usmernenia-k-zakonu-c-343-2015-zz`, page 1: layout (a), 20 `/extdoc/<id>` rows |
| `uvo-leaf-direct.html` | leaf `prehlad-vykladovych-stanovisk-uradu-zakon-c-343-2015-z-z`, page 1: layout (b), 20 direct `/fileadmin/dokumenty/...pdf` anchors |
| `uvo-leaf-layout-c.html` | leaf `metodicke-usmernenia-k-zakonu-c-25-2006-zz`, page 1: layout (c), 20 `usmernenie-detail` rows |
| `uvo-leaf-mixed.html` | leaf `prehlad-vykladovych-stanovisk-uradu-zakon-c-25-2006-z-z`, page 1: direct anchors and `/extdoc/` anchors on one page |
| `pdf/fs-zapis-2014.pdf`, `pdf/mfsr-poucenie.pdf`, `pdf/nbs-dokument.pdf`, `pdf/uvo-extdoc-53262.pdf` | real small PDFs (216,549 / 193,673 / 213,240 / 242,321 bytes) for the download tests; the UVO one answered `application/octet-stream` with `Content-Disposition: attachment; filename=vmu_z3432015_7-2026_jed_aktualizacia.pdf` |

Synthetic (documented in the tests where they are built): FS usmernenia pages 2-5 and the 500-page cap listing, the UVO hub with an eighth leaf, the UVO
page that mixes a layout (c) row with documents, a MF SR page with a `/components/` PDF link, NBS pages with a trailing-label title, and every legacy test
HTML snippet.
