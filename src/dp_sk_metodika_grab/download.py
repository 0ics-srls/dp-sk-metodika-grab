"""One PDF download: the body is a PDF when it starts with ``%PDF-`` (UVO serves ``application/octet-stream``); every other outcome is a named skip reason."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import unquote

from dp_sk_metodika_grab.errors import TRANSIENT_ERROR, GrabError
from dp_sk_metodika_grab.http import TooLargeError

if TYPE_CHECKING:
    from dp_sk_metodika_grab.http import Client

PDF_MAGIC = b"%PDF-"
DEFAULT_MAX_PDF_BYTES = 40 * 1024 * 1024
_FILENAME_STAR = re.compile(r"filename\*\s*=\s*([A-Za-z0-9-]+)'[^']*'([^;]+)", re.IGNORECASE)
_FILENAME = re.compile(r"""filename\s*=\s*(?:"([^"]*)"|([^;]+))""", re.IGNORECASE)


@dataclass(frozen=True)
class Downloaded:
    """``body`` is set for a PDF; otherwise ``reason`` names why not (``http_404``, ``not_a_pdf``, ``too_large``, ``fetch_failed``)."""

    body: bytes | None
    reason: str | None
    filename: str | None = None
    content_type: str | None = None


def content_disposition_filename(header: str) -> str | None:
    """The file name of a Content-Disposition header (RFC 6266: ``filename*`` wins, quotes removed), None when there is none."""
    starred = _FILENAME_STAR.search(header)
    if starred:
        return unquote(starred.group(2).strip(), encoding=starred.group(1)).strip() or None
    plain = _FILENAME.search(header)
    if plain:
        return (plain.group(1) if plain.group(1) is not None else plain.group(2)).strip() or None
    return None


def download_pdf(client: Client, url: str, max_bytes: int) -> Downloaded:
    """403/429 and a host outside the allow-list raise (config_error); everything else about this one document is a skip reason."""
    try:
        answer = client.get(url, max_bytes=max_bytes)
    except TooLargeError:
        return Downloaded(None, "too_large")
    except GrabError as error:
        if error.code == TRANSIENT_ERROR:
            return Downloaded(None, "fetch_failed")
        raise
    if answer.status != 200:  # noqa: PLR2004
        return Downloaded(None, f"http_{answer.status}")
    filename = content_disposition_filename(str(answer.headers.get("content-disposition", "")))
    if not answer.body.startswith(PDF_MAGIC):
        return Downloaded(None, "not_a_pdf", filename, answer.content_type or None)
    return Downloaded(answer.body, None, filename, answer.content_type or None)
