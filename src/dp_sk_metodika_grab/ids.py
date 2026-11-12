"""Document identity (P81b-05): ``source_id`` is the slug of the PDF URL path, the same rule in grab and convert (identical copy, never imported).

Rule: percent-decode the path, drop the query and the fragment, drop a trailing ``.pdf``, join the non-empty segments with ``_``, replace every run of
characters outside ``[A-Za-z0-9_.-]`` and the Latin-1/Extended letters by ``_``, strip leading/trailing ``_`` and ``.``. Short forms: everything before
``Zverejnovanie_dok`` is dropped (Financna sprava), ``/dokument/<uuid>/stiahnut`` becomes ``dokument_<uuid>`` (NBS), ``_img`` loses its underscore.
At most 200 characters (longer: the first 191 + ``_`` + 8 hex of the sha256). No separator and no leading dot can survive, so the id is a safe file name.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import unquote, urlsplit

MAX_ID_LENGTH = 200
_HASH_LENGTH = 8
_ALLOWED = r"A-Za-z0-9_.\-À-ÖØ-öø-ɏ"
_UNSAFE_RUN = re.compile(rf"[^{_ALLOWED}]+")
_SAFE_ID = re.compile(rf"[{_ALLOWED}]+")
_NBS_DOKUMENT = re.compile(r"^/*dokument/([0-9A-Fa-f-]+)/stiahnut/?$")
_STORE = "Zverejnovanie_dok"
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def source_id(url: str) -> str:
    """The identity of the PDF behind ``url`` (absolute or a bare path)."""
    path = unquote(urlsplit(url).path)
    dokument = _NBS_DOKUMENT.match(path)
    if dokument:
        return _fit(f"dokument_{dokument.group(1)}")
    path = re.sub(r"\.pdf$", "", path, flags=re.IGNORECASE)
    segments = [s for s in path.split("/") if s]
    if _STORE in segments:
        segments = segments[segments.index(_STORE) :]
    joined = "_".join(_UNSAFE_RUN.sub("_", segment) for segment in segments)
    return _fit(joined)


def _fit(value: str) -> str:
    cleaned = value.strip("_.") or "dokument"
    if len(cleaned) <= MAX_ID_LENGTH:
        return cleaned
    digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:_HASH_LENGTH]
    return f"{cleaned[: MAX_ID_LENGTH - _HASH_LENGTH - 1].rstrip('_.')}_{digest}"


def is_safe_id(value: str) -> bool:
    """True when ``value`` can be used as a file stem inside the item directory: allowed alphabet only, no leading dot, at most 200 characters."""
    return bool(_SAFE_ID.fullmatch(value)) and len(value) <= MAX_ID_LENGTH and not value.startswith(".")


def safe_name(item_id: str) -> str:
    """Directory name of an item id (convert and ingest derive the same name): ``fs:metodicke-pokyny`` -> ``fs_metodicke-pokyny``.

    Runs outside ``[A-Za-z0-9._-]`` become ``_``; leading and trailing dots are dropped so that a hostile id cannot name ``..``.
    """
    return _UNSAFE_NAME.sub("_", item_id.replace(" ", "-")).strip(".") or "item"  # never "." or "..": the directory stays below ``dir``
