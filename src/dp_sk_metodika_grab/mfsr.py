"""MF SR - Financny spravodajca (``fonte`` mfsr-spravodajca): one page per year, ``<base>/sk/financie/financny-spravodajca/<yyyy>/``.

Port of the legacy ``MfsrAdapter``. The years come from the Source range ``annoFrom..annoTo`` (P81b-04), never from the index, which now answers 301 and is
never requested. Each link appears up to three times on a page (icon, title, "Aktualny dokument"), so hrefs are deduplicated per page (2025: 108 hrefs = 36
documents). Years 1999-2009 offer only ``FS_nn_yy.zip`` archives: such a year is an empty item with the coverage marker ``zip_archives_only`` (F1).
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from dp_sk_metodika_grab import fs
from dp_sk_metodika_grab.model import SITE_MFSR, Listing, PdfDoc, normalize

if TYPE_CHECKING:
    from dp_sk_metodika_grab.http import Client

DEFAULT_ORIGIN = "https://www.mfsr.sk"
MARKER_ZIP_ONLY = "zip_archives_only"
_YEAR = re.compile(r"/financny-spravodajca/(\d{4})/")
_CODE = re.compile(r"MF/\d+/\d{4}-\d+")
_SIZE = re.compile(r"\(\s*\d+[.,]?\d*\s*[kKmM]B\s*\)")
_LABEL = re.compile(r"\b(Aktuálny dokument|Aktualny dokument|Archívny dokument|Archivny dokument|Archív|Stiahnuť|Stiahnut|Otvoriť|Otvorit)\b")


def year_url(year: int, origin: str | None = None) -> str:
    """The single page of one year."""
    return f"{(origin or DEFAULT_ORIGIN).rstrip('/')}/sk/financie/financny-spravodajca/{year}/"


def clean_title(text: str) -> str:
    return normalize(_LABEL.sub("", _SIZE.sub("", text)))


def parse(html: str, url: str) -> list[PdfDoc]:
    """Every ``a[href$=".pdf"]`` (case-insensitive) of a year page, one document per distinct href."""
    soup = BeautifulSoup(html, "html.parser")
    year = _YEAR.search(url)
    group = year.group(1) if year else None
    documents: list[PdfDoc] = []
    seen: set[str] = set()
    for anchor in soup.select('a[href$=".pdf" i]'):
        href = str(anchor["href"])
        if href in seen:
            continue
        seen.add(href)
        header = anchor.find_parent(class_="card-header") or anchor.find_parent(["h3", "h4", "li"])
        pdf_url = urljoin(url, href)
        title = clean_title((header or anchor).get_text()) or clean_title(anchor.get_text()) or fs.slug(fs.url_path_stem(pdf_url))
        code = _CODE.search(title)
        documents.append(PdfDoc(SITE_MFSR, title, pdf_url, group=group, code=code.group(0) if code else None, listing_url=url))
    return documents


def has_zip_archives(html: str) -> bool:
    return bool(BeautifulSoup(html, "html.parser").select('a[href$=".zip" i]'))


def list_year(client: Client, year: int) -> Listing:
    """One request: the page of ``year``. Never the index."""
    url = year_url(year)
    answer = client.get(url)
    listing = Listing(pages=1)
    if answer.status != 200:  # noqa: PLR2004
        listing.warnings.append(f"listing_http_{answer.status}")
        return listing
    html = answer.text()
    listing.docs = parse(html, url)
    if not listing.docs and has_zip_archives(html):
        listing.warnings.append(MARKER_ZIP_ONLY)
    return listing
