"""NBS - metodicke usmernenia, stanoviska a odporucania (``fonte`` nbs-metodicke): one page with ``/_img/...pdf`` links and ``/dokument/<uuid>/stiahnut`` links.

Port of the legacy ``NbsAdapter``. The page writes the download links in several forms (``?force=false?force=false``, an absolute URL with ``/?force=true``);
they are normalised to the canonical ``https://nbs.sk/dokument/<uuid>/stiahnut`` so that one document has one URL and one id (``id_override`` = the uuid).
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from dp_sk_metodika_grab.model import SITE_NBS, Listing, PdfDoc, normalize

if TYPE_CHECKING:
    from dp_sk_metodika_grab.http import Client

PAGE_URL = "https://nbs.sk/dohlad-nad-financnym-trhom/ofs/informacie-pre-odbornu-verejnost/metodicke-usmernenia-stanoviska-a-odporucania/"
_DOKUMENT = re.compile(r"^/dokument/([0-9A-Fa-f-]+)/stiahnut/?$")
_TITLE_TRIM = " .\N{EN DASH}-"


def _canonical(page_url: str, href: str) -> tuple[str, str | None] | None:
    """(canonical URL, uuid) of a document link, or None when the link is neither a ``/_img`` PDF nor a ``/dokument/.../stiahnut`` download."""
    parts = urlsplit(urljoin(page_url, href))
    origin = f"{parts.scheme}://{parts.netloc}"
    dokument = _DOKUMENT.match(parts.path)
    if dokument:
        return f"{origin}/dokument/{dokument.group(1)}/stiahnut", dokument.group(1)
    if parts.path.lower().endswith(".pdf") and "/_img/" in parts.path.lower():
        return f"{origin}{parts.path}", None
    return None


def parse(html: str, url: str) -> list[PdfDoc]:
    soup = BeautifulSoup(html, "html.parser")
    documents: list[PdfDoc] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        link = _canonical(url, str(anchor["href"]))
        if link is None or link[0] in seen:
            continue
        pdf_url, uuid = link
        seen.add(pdf_url)
        label = normalize(anchor.get_text())
        host = anchor.find_parent(["p", "li", "td"])
        title = normalize(host.get_text()) if host is not None else label
        if label and title.endswith(label):
            title = title[: -len(label)].strip(_TITLE_TRIM)
        documents.append(PdfDoc(SITE_NBS, title or label, pdf_url, id_override=uuid, listing_url=url))
    return documents


def list_all(client: Client) -> Listing:
    """One request: the single page."""
    answer = client.get(PAGE_URL)
    listing = Listing(pages=1)
    if answer.status != 200:  # noqa: PLR2004
        listing.warnings.append(f"listing_http_{answer.status}")
        return listing
    listing.docs = parse(answer.text(), PAGE_URL)
    return listing
