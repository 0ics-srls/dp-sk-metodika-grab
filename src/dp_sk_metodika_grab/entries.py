"""One document of any source in the shape the sidecar needs (the contract of the Python classes): ``Entry`` plus the sidecar writer."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from dp_sk_metodika_grab import ids
from dp_sk_metodika_grab.model import SITE_UVO

if TYPE_CHECKING:
    from dp_sk_metodika_grab.fs import FsDocument
    from dp_sk_metodika_grab.model import PdfDoc

FONTE_FS = "financnasprava"
_YEAR_DIGITS = 4


@dataclass(frozen=True)
class Entry:
    """A listed document. Unknown values are None (never "" and never 0)."""

    fonte: str
    source_id: str
    legacy_doc_id: str
    section: str
    group: str | None
    title: str | None
    pdf_url: str
    listing_url: str | None
    code: str | None = None
    number: int | None = None
    dept: str | None = None
    year: int | None = None
    doc_type: str | None = None
    category: str | None = None
    published: str | None = None


def from_fs(doc: FsDocument) -> Entry:
    return Entry(
        fonte=FONTE_FS, source_id=ids.source_id(doc.pdf_url), legacy_doc_id=doc.doc_id, section=doc.section, group=None, title=doc.title or None,
        pdf_url=doc.pdf_url, listing_url=doc.listing_url, code=doc.code, number=doc.number, dept=doc.dept, year=doc.year, doc_type=doc.doc_type,
        category=doc.category, published=doc.published,
    )  # fmt: skip


def from_pdf(doc: PdfDoc) -> Entry:
    year: int | None = None
    if doc.group is not None and len(doc.group) == _YEAR_DIGITS and doc.group.isdigit():
        year = int(doc.group)  # MF SR: the group is the year page
    elif doc.site == SITE_UVO and doc.published is not None:
        year = int(doc.published[:_YEAR_DIGITS])
    return Entry(
        fonte=doc.site, source_id=ids.source_id(doc.pdf_url), legacy_doc_id=doc.doc_id, section=doc.site, group=doc.group, title=doc.title or None,
        pdf_url=doc.pdf_url, listing_url=doc.listing_url, code=doc.code, year=year, published=doc.published,
    )  # fmt: skip


def sidecar(  # noqa: PLR0913
    entry: Entry, version: str, fetched: str, *, pdf_bytes: int | None, source_filename: str | None = None, skip_reason: str | None = None
) -> dict[str, Any]:
    """The ``<source_id>.meta.json`` content, keys in the order of the contract plus ``source_filename`` (Content-Disposition) and ``skip_reason``."""
    return {
        "fonte": entry.fonte,
        "source_id": entry.source_id,
        "legacy_doc_id": entry.legacy_doc_id,
        "section": entry.section,
        "group": entry.group,
        "title": entry.title,
        "pdf_url": entry.pdf_url,
        "listing_url": entry.listing_url,
        "code": entry.code,
        "number": entry.number,
        "dept": entry.dept,
        "year": entry.year,
        "doc_type": entry.doc_type,
        "category": entry.category,
        "published": entry.published,
        "pdf_file": f"{entry.source_id}.pdf" if pdf_bytes is not None else None,
        "pdf_bytes": pdf_bytes,
        "fetched": fetched,
        "version": version,
        "source_filename": source_filename,
        "skip_reason": skip_reason,
    }
