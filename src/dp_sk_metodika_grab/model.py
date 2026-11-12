"""The document model of the three PDF sites (port of the legacy ``PdfDoc``) and the result of one listing walk."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from dp_sk_metodika_grab import fs

SITE_MFSR = "mfsr-spravodajca"
SITE_NBS = "nbs-metodicke"
SITE_UVO = "uvo-metodicke"
SITES = (SITE_MFSR, SITE_NBS, SITE_UVO)


def normalize(text: str) -> str:
    """Runs of whitespace (including U+00A0) become one space."""
    return " ".join(text.split())


def strip_pdf_suffix(text: str) -> str:
    return re.sub(r"\.pdf$", "", text, flags=re.IGNORECASE)


@dataclass(frozen=True)
class PdfDoc:
    """One PDF found on a static-PDF site. ``doc_id`` is the legacy id (kept as ``legacy_doc_id``): the slug of the uuid override or of the file stem."""

    site: str
    title: str
    pdf_url: str
    group: str | None = None
    code: str | None = None
    published: str | None = None
    id_override: str | None = None
    listing_url: str | None = None

    @property
    def doc_id(self) -> str:
        return fs.slug(self.id_override) if self.id_override is not None else fs.slug(fs.url_path_stem(self.pdf_url))


@dataclass
class Listing:
    """What the walk of one item found: the documents (first sight of a URL wins), coverage warnings and the pages requested."""

    docs: list[PdfDoc] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    pages: int = 0
