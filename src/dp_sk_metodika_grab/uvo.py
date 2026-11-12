"""UVO - metodicke usmernenia a vykladove stanoviska (``fonte`` uvo-metodicke), OFF by default (decision D141).

robots.txt of uvo.gov.sk is ``User-agent: * / Disallow: /``: the grab refuses this site unless ``uvoRobotsAck`` is true (``require_ack``), paces it at 2 s,
and nothing in the tests ever reaches it (recorded fixtures through httpx MockTransport).

Port of the legacy ``UvoAdapter`` (hub -> leaves, ``?page=N``, ``/extdoc/<id>`` rows, title = enclosing row text, code = anchor text, published d.M.yyyy ->
ISO, group = leaf slug) plus layout (b) of the live site: direct ``/fileadmin/dokumenty/**/*.pdf`` anchors (P81b-12). A leaf page of layout (c) (rows that
open ``usmernenie-detail`` records, about 8,000 of them on the two per-law leaves) yields no document and is recorded as ``layout_c_not_collected:<rows>``.
More than one layout can appear on one leaf page, so both selectors run on every page.
"""
from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from dp_sk_metodika_grab import robots
from dp_sk_metodika_grab.errors import CONFIG_ERROR, GrabError
from dp_sk_metodika_grab.model import SITE_UVO, Listing, PdfDoc, normalize, strip_pdf_suffix

if TYPE_CHECKING:
    from dp_sk_metodika_grab.http import Client

BASE = "https://www.uvo.gov.sk"
HUB = f"{BASE}/metodika-vzdelavanie/metodicke-usmernenia-a-vykladove-stanoviska"
HOST = "www.uvo.gov.sk"
HOST_DELAYS = {HOST: 2.0}
PAGE_CAP = 1000
MARKER_LAYOUT_C = "layout_c_not_collected"
MARKER_NEW_LEAF = "new_leaf"
LEAVES: tuple[str, ...] = (
    "metodicke-usmernenia-k-zakonu-c-214-2021-zz",
    "metodicke-usmernenia-k-zakonu-c-25-2006-zz",
    "metodicke-usmernenia-k-zakonu-c-343-2015-zz",
    "vseobecne-metodicke-usmernenia-k-zakonu-c-25-2006-zz",
    "vseobecne-metodicke-usmernenia-k-zakonu-c-343-2015-zz",
    "prehlad-vykladovych-stanovisk-uradu-zakon-c-25-2006-z-z",
    "prehlad-vykladovych-stanovisk-uradu-zakon-c-343-2015-z-z",
)
_DATE = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})")  # the live rows also write "06. 08. 2026"
_DETAIL = re.compile(r"/usmernenie-detail/(\d+)")


def require_ack(ack: object) -> None:
    """The robots gate: only the JSON boolean ``true`` lets the grab touch uvo.gov.sk."""
    if ack is True:
        return
    msg = (
        "uvo-metodicke is refused: uvo.gov.sk/robots.txt says for generic agents\n"
        f"{robots.UVO_RULE}\n"
        f"({robots.UVO_DECISION}). Set the Source setting uvoRobotsAck=true to accept the robots posture, or leave uvo-metodicke out of `sites`."
    )
    raise GrabError(CONFIG_ERROR, msg)


def leaf_url(slug: str) -> str:
    return f"{HUB}/{slug}"


def page_url(seed: str, n: int) -> str:
    return seed if n == 1 else f"{seed}?page={n}"


def parse_hub(html: str) -> list[str]:
    """The leaf URLs of the hub (first segment below the hub path, query dropped, duplicates removed, document order)."""
    soup = BeautifulSoup(html, "html.parser")
    leaves: list[str] = []
    prefix = urlsplit(HUB).path + "/"
    for anchor in soup.find_all("a", href=True):
        path = urlsplit(urljoin(BASE, str(anchor["href"]))).path
        if not path.startswith(prefix):
            continue
        slug = path[len(prefix) :].strip("/").split("/")[0]
        url = leaf_url(slug) if slug else ""
        if slug and url not in leaves:
            leaves.append(url)
    return leaves


def hub_warnings(html: str) -> list[str]:
    """``new_leaf:<slug>`` for every leaf of the hub that is not one of the constants."""
    return [f"{MARKER_NEW_LEAF}:{url.rsplit('/', 1)[-1]}" for url in parse_hub(html) if url.rsplit("/", 1)[-1] not in LEAVES]


def read_hub(client: Client) -> list[str]:
    """One request: the hub, cross-checked against ``LEAVES``. A hub that cannot be read is a warning, not a failure."""
    answer = client.get(HUB)
    if answer.status != 200:  # noqa: PLR2004
        return [f"hub_http_{answer.status}"]
    return hub_warnings(answer.text())


def _published(text: str) -> str | None:
    found = _DATE.search(text)
    if not found:
        return None
    try:
        return date(int(found.group(3)), int(found.group(2)), int(found.group(1))).isoformat()
    except ValueError:
        return None


def parse(html: str, url: str) -> list[PdfDoc]:
    """``/extdoc/<id>`` rows (layout a) and direct ``/fileadmin/dokumenty/...pdf`` anchors (layout b) of a leaf page, one document per distinct URL."""
    soup = BeautifulSoup(html, "html.parser")
    group = url.split("?", maxsplit=1)[0].rstrip("/").rsplit("/", 1)[-1]
    documents: list[PdfDoc] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        path = urlsplit(href).path.lower()
        is_extdoc = "/extdoc/" in href.lower()
        is_direct = "/fileadmin/dokumenty/" in path and path.endswith(".pdf")
        if not (is_extdoc or is_direct):
            continue
        full = urljoin(BASE, href)
        if full in seen:
            continue
        seen.add(full)
        code = strip_pdf_suffix(normalize(anchor.get_text())) if is_direct else normalize(anchor.get_text())
        row = anchor.find_parent(["tr", "li"])
        title = normalize(row.get_text()) if row is not None else code
        documents.append(PdfDoc(SITE_UVO, title, full, group=group, code=code or None, published=_published(title), listing_url=url))
    return documents


def count_detail_rows(html: str) -> int:
    """Rows (or anchors) that open a ``usmernenie-detail/<id>`` record: layout (c), not collected."""
    soup = BeautifulSoup(html, "html.parser")
    found: set[str] = set()
    for tag in soup.find_all(["tr", "a"]):
        for value in (tag.get("onclick"), tag.get("href")):
            match = _DETAIL.search(str(value)) if value else None
            if match:
                found.add(match.group(1))
    return len(found)


def list_leaf(client: Client, slug: str) -> Listing:
    """Pages 1.. of one leaf until a missing, empty or repeated page (cap 1000)."""
    seed = leaf_url(slug)
    listing = Listing()
    seen: set[str] = set()
    marked = False
    for n in range(1, PAGE_CAP + 1):
        answer = client.get(page_url(seed, n))
        listing.pages = n
        if answer.status != 200 or not answer.body:  # noqa: PLR2004
            if n == 1:
                listing.warnings.append(f"listing_http_{answer.status}")
            break
        html = answer.text()
        rows = count_detail_rows(html)
        if rows and not marked:
            listing.warnings.append(f"{MARKER_LAYOUT_C}:{rows}")
            marked = True
        fresh = [d for d in parse(html, page_url(seed, n)) if d.pdf_url not in seen]
        if not fresh:
            break
        for document in fresh:
            seen.add(document.pdf_url)
            listing.docs.append(document)
    return listing
