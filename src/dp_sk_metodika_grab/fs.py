"""Financna sprava SR listings (``fonte`` financnasprava): the section catalogue, pure parsers and the page walk.

Port of the legacy ``FsSections`` + ``FsParse`` (C#, itself a port of ``financnasprava.documents`` / ``scraper._page_url``). The live pages use single-quoted
hrefs and repeat the first page after the last one (page 6 of usmernenia = page 1), so the walk stops at an empty page or a page without a fresh PDF.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

if TYPE_CHECKING:
    from dp_sk_metodika_grab.http import Client

DEFAULT_BASE = "https://www.financnasprava.sk/sk/danovi-a-colni-specialisti/dane"
SECTION_NAMES = ("metodicke-pokyny", "metodicke-usmernenia", "zavery-komisii", "prehlady-zmluv-zdz")
PAGE_CAP = 500
DOC_STORE = "Zverejnovanie_dok"
_CODE = re.compile(r"(\d+)\s*/\s*([^/\s]+)\s*/\s*(\d{4})\s*/\s*([A-Za-z]+)")
_DATE = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})")
_YEAR = re.compile(r"\d{4}")
_SLUG = re.compile(r"[^\w.-]+")
_EMBEDDED_PAGE = re.compile(r"/_\d+/")


def sections(base_url: str | None = None) -> dict[str, str]:
    """Section key -> listing URL, built from ``base_url`` (blank = the site). The prehlady URL is a stateless filtered-results GET (base64 filter parameters,
    the page marker is the ``/_1/`` segment inside the path); the plain section URL lists no documents."""
    base = (base_url or DEFAULT_BASE).rstrip("/")
    return {
        "metodicke-pokyny": f"{base}/metodicke-pokyny",
        "metodicke-usmernenia": f"{base}/metodicke-usmernenia",
        "zavery-komisii": f"{base}/zavery-zo-zasadnuti-MFSR",
        "prehlady-zmluv-zdz": f"{base}/prehlady-zmluv-zdz/_1/D%c3%a1tum%20publikovania/Mw==/MjQ=/MA==/MA==/MTA=/bnVsbA==/opb",
    }


def slug(value: str) -> str:
    """Runs of non-word/dot/dash characters -> ``_``, trimmed, fallback ``dokument``. Unicode letters (Slovak diacritics) are kept."""
    return _SLUG.sub("_", value).strip("_") or "dokument"


def _path_of(url: str) -> str:
    return urlsplit(url).path if urlsplit(url).scheme else url


def url_path_stem(pdf_url: str) -> str:
    """The file name of the URL path without its last extension, percent-encoding kept."""
    path = _path_of(pdf_url)
    name = path[path.rfind("/") + 1 :]
    dot = name.rfind(".")
    return name[:dot] if dot > 0 else name


@dataclass(frozen=True)
class FsDocument:
    """One document of a listing. ``doc_id`` is the legacy stable folder name (kept as ``legacy_doc_id``)."""

    section: str
    title: str
    pdf_url: str
    code: str | None = None
    number: int | None = None
    dept: str | None = None
    year: int | None = None
    doc_type: str | None = None
    category: str | None = None
    published: str | None = None
    listing_url: str | None = None
    raw_url: str | None = None  # the href as the page wrote it: the legacy doc_id is derived from it, so it does not change with the encoding (P84, C16)

    @property
    def doc_id(self) -> str:
        if self.code is not None:
            return f"{self.number}_{self.dept}_{self.year}_{self.doc_type}"
        return slug(url_path_stem(self.raw_url or self.pdf_url))


_PATH_SAFE = "/%:@!$&'()*+,;=~"  # RFC 3986 path characters stay, a space and non-ASCII characters are encoded, existing %XX stay (no double encoding)


def encode_url(url: str) -> str:
    """The URL with its path percent-encoded (``a b.pdf`` -> ``a%20b.pdf``). Already encoded input is returned unchanged. ``source_id`` is not affected: it decodes the path first."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, quote(parts.path, safe=_PATH_SAFE), parts.query, parts.fragment))


def make_document(section: str, title: str, pdf_url: str) -> FsDocument:
    """Code from the title (``10/DZPaU/2026/MP``), category/year/date from the PDF path."""
    code = number = dept = year = doc_type = None
    found = _CODE.search(title)
    if found:
        number, dept, year, doc_type = int(found.group(1)), found.group(2), int(found.group(3)), found.group(4)
        code = f"{number}/{dept}/{year}/{doc_type}"
    parts = _path_of(pdf_url).split("/")
    category: str | None = None
    for index, part in enumerate(parts):
        if _YEAR.fullmatch(part):
            if year is None:
                year = int(part)
            if index > 0:
                category = parts[index - 1]
            break
    published: str | None = None
    matched = _DATE.search(parts[-1] if parts else "")
    if matched:
        published = f"{matched.group(1)}-{matched.group(2)}-{matched.group(3)}"
    return FsDocument(section, title, encode_url(pdf_url), code, number, dept, year, doc_type, category, published, raw_url=pdf_url)


def parse_listing(html: str, base_url: str, section: str) -> list[FsDocument]:
    """Every ``.pdf`` link under ``Zverejnovanie_dok`` that has a title (single- and double-quoted hrefs alike)."""
    soup = BeautifulSoup(html, "html.parser")
    documents: list[FsDocument] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        if ".pdf" not in href.lower() or DOC_STORE not in href:
            continue
        title = " ".join(anchor.get_text().split())
        if not title:
            continue
        documents.append(make_document(section, title, urljoin(base_url, href)))
    return documents


def page_url(base_url: str, n: int) -> str:
    """Page ``n`` of a listing: ``<base>/_N``, or the page marker ``/_1/`` rewritten inside a filtered-results URL."""
    if n == 1:
        return base_url
    found = _EMBEDDED_PAGE.search(base_url)
    if found:
        return f"{base_url[: found.start()]}/_{n}/{base_url[found.end() :]}"
    return f"{base_url}/_{n}"


@dataclass
class Walk:
    """What a listing walk found: the documents (first sight wins), the pages requested and coverage warnings."""

    docs: list[FsDocument] = field(default_factory=list)
    pages: int = 0
    warnings: list[str] = field(default_factory=list)


def walk_section(client: Client, section: str, listing_url: str) -> Walk:
    """Pages 1.. until an empty page or a page without a fresh PDF (cap 500); the site wraps around after the last page."""
    walk = Walk()
    seen: set[str] = set()
    for n in range(1, PAGE_CAP + 1):
        url = page_url(listing_url, n)
        answer = client.get(url)
        walk.pages = n
        if answer.status != 200 or not answer.body:  # noqa: PLR2004
            if n == 1:
                walk.warnings.append(f"listing_http_{answer.status}")
            break
        fresh = [d for d in parse_listing(answer.text(), url, section) if d.pdf_url not in seen]
        if not fresh:
            break
        for document in fresh:
            if document.pdf_url not in seen:  # the same link twice on one page counts once
                seen.add(document.pdf_url)
                walk.docs.append(replace(document, listing_url=url))
    return walk
