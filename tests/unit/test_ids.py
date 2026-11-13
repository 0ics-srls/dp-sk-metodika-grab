"""source_id (P81b-05): slug of the PDF URL path, the only rule (convert trusts the sidecar, P81b-34); the 715 recorded MF SR URLs give 715 distinct ids (legacy: 645)."""
from __future__ import annotations

import json

import pytest

from conftest import fixture_text
from dp_sk_metodika_grab import ids

UUID = "8a55d8a5-dea0-43a3-a164-96201563e0f5"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.mfsr.sk/files/archiv/35/Priloha_c_1.pdf", "files_archiv_35_Priloha_c_1"),
        ("/files/archiv/35/Priloha_c_1.PDF", "files_archiv_35_Priloha_c_1"),
        ("https://www.uvo.gov.sk/extdoc/53262", "extdoc_53262"),
        (f"https://nbs.sk/dokument/{UUID}/stiahnut", f"dokument_{UUID}"),
        (f"https://nbs.sk/dokument/{UUID}/stiahnut?force=false?force=false", f"dokument_{UUID}"),
        (f"https://nbs.sk/dokument/{UUID}/stiahnut/?force=true", f"dokument_{UUID}"),
        (
            "https://www.uvo.gov.sk/fileadmin/dokumenty/vykladove_stanoviska_2015/vykladove_stanovisko_1-2021.pdf",
            "fileadmin_dokumenty_vykladove_stanoviska_2015_vykladove_stanovisko_1-2021",
        ),
        (
            "https://www.financnasprava.sk//_img/pfsedit/Dokumenty_PFS/Zverejnovanie_dok/Dane/Metodicke_pokyny/Priame_dane_uct/2026/2026.06.01_010_DZPaU_2026_MP.pdf",
            "Zverejnovanie_dok_Dane_Metodicke_pokyny_Priame_dane_uct_2026_2026.06.01_010_DZPaU_2026_MP",
        ),
        ("https://nbs.sk/_img/Documents/_Dohlad/Ochrana_spotrebitela/Stanovisko_OFS_22_12_2020.pdf", "img_Documents__Dohlad_Ochrana_spotrebitela_Stanovisko_OFS_22_12_2020"),
        ("https://x.sk/files/archiv/1/Metodick%C3%BD%20pokyn%20%C4%8D.5.pdf?x=1#f", "files_archiv_1_Metodický_pokyn_č.5"),
        ("https://x.sk/", "dokument"),
    ],
)
def test_should_slug_the_url_path_when_the_url_is_known(url: str, expected: str) -> None:
    assert ids.source_id(url) == expected


@pytest.mark.unit
def test_should_keep_every_id_inside_the_allowed_alphabet_and_length() -> None:
    hostile = [
        "https://x.sk/a/..%2f..%2fx.pdf",
        "https://x.sk/a/../../b.pdf",
        "https://x.sk/a b/c\\d/e:f*g?.pdf",
        "https://x.sk/" + "very-long-segment-" * 30 + ".pdf",
        "https://x.sk/.pdf",
        "https://x.sk/%2e%2e/%2e%2e/etc/passwd",
    ]
    for url in hostile:
        value = ids.source_id(url)
        assert ids.is_safe_id(value), (url, value)
        assert len(value) <= ids.MAX_ID_LENGTH


@pytest.mark.unit
def test_should_truncate_with_a_hash_when_the_path_is_too_long() -> None:
    first = ids.source_id("https://x.sk/" + "a" * 300 + "/1.pdf")
    second = ids.source_id("https://x.sk/" + "a" * 300 + "/2.pdf")
    assert len(first) == len(second) == ids.MAX_ID_LENGTH
    assert first != second
    assert first == ids.source_id("https://x.sk/" + "a" * 300 + "/1.pdf")


@pytest.mark.unit
def test_should_refuse_unsafe_ids() -> None:
    for bad in ["", ".", "..", "../x", "a/b", "a\\b", ".hidden", "a b", "x" * 201, "a:b"]:
        assert not ids.is_safe_id(bad), bad
    for good in ["files_archiv_1", "a.b-c_d", "Metodický_pokyn", "dokument_" + UUID]:
        assert ids.is_safe_id(good), good


@pytest.mark.unit
def test_should_give_715_distinct_ids_when_the_recorded_mfsr_urls_are_slugged() -> None:
    by_year: dict[str, list[str]] = json.loads(fixture_text("mfsr-urls-715.json"))
    urls = [f"https://www.mfsr.sk{href}" for hrefs in by_year.values() for href in hrefs]
    assert len(urls) == 715
    values = [ids.source_id(url) for url in urls]
    assert len(set(values)) == 715
    assert len({value.lower() for value in values}) == 715, "ids must also differ on a case-insensitive file system"
    assert all(ids.is_safe_id(value) for value in values)


@pytest.mark.unit
def test_should_make_a_directory_name_of_an_item_id() -> None:
    assert ids.safe_name("fs:metodicke-pokyny") == "fs_metodicke-pokyny"
    assert ids.safe_name("pdf:mfsr-spravodajca:2025") == "pdf_mfsr-spravodajca_2025"
    assert ids.safe_name("..") == "item"
    assert ids.safe_name("../../outside") == "_.._outside"
    assert ids.safe_name("a/../b") == "a_.._b"
    assert ids.safe_name("pdf:uvo-metodicke:vseobecne-metodicke-usmernenia-k-zakonu-c-343-2015-zz").startswith("pdf_uvo-metodicke_")
