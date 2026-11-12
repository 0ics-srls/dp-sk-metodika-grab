# Pinned certificates

Every `*.pem` in this directory is added to the TLS trust of the grab on top of the certifi roots (`http.ssl_context`).

The directory is empty on purpose: on 2026-11-12 all four hosts (`www.financnasprava.sk`, `www.mfsr.sk`, `nbs.sk`, `www.uvo.gov.sk`) sent complete
chains, so nothing needs pinning (P81b-14). The loader exists, and is unit-tested (`tests/unit/test_certs.py`), because phase 79b met a host that sent only its
leaf certificate. If a container chain check ever shows an incomplete chain, add the intermediate here as `<name>.pem` and document in this file its source
URL (the `CA Issuers` URI of the leaf), subject, issuer, validity and SHA-256 fingerprint, then release a new tag.
