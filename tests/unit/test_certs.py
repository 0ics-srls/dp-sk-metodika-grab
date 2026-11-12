"""TLS trust (P79b lesson): certifi plus every ``certs/*.pem``. All four hosts send full chains today, so the directory ships empty; the loader is tested."""
from __future__ import annotations

import re
import ssl
from pathlib import Path

import certifi
import pytest

from dp_sk_metodika_grab import http
from dp_sk_metodika_grab.errors import CONFIG_ERROR, GrabError


def _a_pem_from_the_certifi_bundle() -> str:
    bundle = Path(certifi.where()).read_text(encoding="ascii")
    block = re.search(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", bundle, re.DOTALL)
    assert block is not None
    return block.group(0) + "\n"


@pytest.mark.unit
def test_should_build_a_verifying_context_when_the_certs_directory_is_empty(tmp_path: Path) -> None:
    context = http.ssl_context(verify=True, certs_dir=tmp_path)

    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert len(context.get_ca_certs()) > 50, "the certifi roots are loaded"


@pytest.mark.unit
def test_should_ship_an_empty_pinned_certs_directory() -> None:
    assert list(http.CERTS_DIR.glob("*.pem")) == []
    assert (http.CERTS_DIR / "README.md").is_file()
    context = http.ssl_context(verify=True)
    assert context.verify_mode == ssl.CERT_REQUIRED


@pytest.mark.unit
def test_should_load_a_pem_added_to_the_directory(tmp_path: Path) -> None:
    (tmp_path / "pinned-b.pem").write_text(_a_pem_from_the_certifi_bundle(), encoding="ascii")
    (tmp_path / "pinned-a.pem").write_text(_a_pem_from_the_certifi_bundle(), encoding="ascii")
    (tmp_path / "notes.txt").write_text("not a certificate", encoding="ascii")

    context = ssl.create_default_context(cafile=certifi.where())
    loaded = http.load_pinned(context, tmp_path)

    assert loaded == ["pinned-a.pem", "pinned-b.pem"]


@pytest.mark.unit
def test_should_load_nothing_from_a_missing_directory(tmp_path: Path) -> None:
    assert http.load_pinned(ssl.create_default_context(), tmp_path / "absent") == []


@pytest.mark.unit
def test_should_report_a_broken_pem_as_a_config_error(tmp_path: Path) -> None:
    (tmp_path / "broken.pem").write_text("-----BEGIN CERTIFICATE-----\nnot base64 at all\n-----END CERTIFICATE-----\n", encoding="ascii")

    with pytest.raises(GrabError) as caught:
        http.ssl_context(verify=True, certs_dir=tmp_path)

    assert caught.value.code == CONFIG_ERROR
    assert "broken.pem" in str(caught.value)


@pytest.mark.unit
def test_should_keep_the_documented_escape_when_verify_is_false(tmp_path: Path) -> None:
    context = http.ssl_context(verify=False, certs_dir=tmp_path)

    assert context.verify_mode == ssl.CERT_NONE
    assert context.check_hostname is False
