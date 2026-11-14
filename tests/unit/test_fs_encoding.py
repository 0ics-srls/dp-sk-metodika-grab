"""P84 (carry-over C16): the document URL of a Financna sprava href is percent-encoded (spaces -> %20, no double encoding).

Critical invariant (D151/D156): ``source_id`` and the legacy ``doc_id`` stay what they were, otherwise a re-run creates duplicate documents. The goldens below
were recorded from the 0.1.1 code on the two phase-81b documents whose href had a raw space (parity.md item 15).
"""
from __future__ import annotations

import hashlib

import pytest

from conftest import fixture_text
from dp_sk_metodika_grab import fs, ids, mfsr, nbs

BASE = "https://www.financnasprava.sk//_img/pfsedit/Dokumenty_PFS/Zverejnovanie_dok/Dane/Metodicke_usmernenia/Priame_dane"
RAW_A = f"{BASE}/2024/2024.04.22_017_DZPaU_2024_I_ Info_uct_kompenz_energ.pdf"
RAW_B = f"{BASE}/2022/2022.04.08_ 8_DZPaU_2022_MU.pdf"
ENC_A = f"{BASE}/2024/2024.04.22_017_DZPaU_2024_I_%20Info_uct_kompenz_energ.pdf"
ENC_B = f"{BASE}/2022/2022.04.08_%208_DZPaU_2022_MU.pdf"
SOURCE_ID_A = "Zverejnovanie_dok_Dane_Metodicke_usmernenia_Priame_dane_2024_2024.04.22_017_DZPaU_2024_I__Info_uct_kompenz_energ"
SOURCE_ID_B = "Zverejnovanie_dok_Dane_Metodicke_usmernenia_Priame_dane_2022_2022.04.08__8_DZPaU_2022_MU"
DOC_ID_A = "2024.04.22_017_DZPaU_2024_I__Info_uct_kompenz_energ"
DOC_ID_B = "2022.04.08__8_DZPaU_2022_MU"


def listing(*hrefs: str) -> str:
    anchors = "".join(f"<a href='{href}' title='x'>Usmernenie {n}</a>" for n, href in enumerate(hrefs, start=1))
    return f"<html><body>{anchors}</body></html>"


@pytest.mark.unit
def test_should_percent_encode_spaces_in_source_url_when_href_has_a_space() -> None:
    docs = fs.parse_listing(listing(RAW_A, RAW_B), "https://www.financnasprava.sk/sk/x", "metodicke-usmernenia")

    assert [d.pdf_url for d in docs] == [ENC_A, ENC_B]


@pytest.mark.unit
def test_should_not_double_encode_when_href_already_encoded() -> None:
    already = f"{BASE}/2020/2020.01.02_%C3%A1_%20x.pdf"

    docs = fs.parse_listing(listing(ENC_A, already), "https://www.financnasprava.sk/sk/x", "metodicke-usmernenia")

    assert [d.pdf_url for d in docs] == [ENC_A, already]
    assert "%25" not in docs[0].pdf_url + docs[1].pdf_url


@pytest.mark.unit
def test_should_keep_source_id_unchanged_when_url_is_encoded() -> None:
    docs = fs.parse_listing(listing(RAW_A, RAW_B), "https://www.financnasprava.sk/sk/x", "metodicke-usmernenia")

    assert [ids.source_id(d.pdf_url) for d in docs] == [SOURCE_ID_A, SOURCE_ID_B]
    assert [ids.source_id(u) for u in (RAW_A, RAW_B)] == [SOURCE_ID_A, SOURCE_ID_B]
    assert [d.doc_id for d in docs] == [DOC_ID_A, DOC_ID_B], "the legacy doc_id (legacy_doc_id in the sidecar) is unchanged too"


@pytest.mark.unit
def test_should_keep_the_recorded_fs_page_unchanged_when_it_has_no_space_besides_the_known_one() -> None:
    docs = fs.parse_listing(fixture_text("fs-usmernenia-1.html"), "https://www.financnasprava.sk/sk/x", "metodicke-usmernenia")

    assert all(" " not in d.pdf_url for d in docs), "no raw space survives in a document URL"
    assert any(d.pdf_url.endswith("2024_I_%20Info_uct_kompenz_energ.pdf") for d in docs)


def _digest(docs: list) -> str:
    return hashlib.sha256("\n".join(f"{d.pdf_url}|{ids.source_id(d.pdf_url)}" for d in docs).encode()).hexdigest()


@pytest.mark.unit
def test_should_keep_non_fs_adapters_untouched() -> None:
    nbs_docs = nbs.parse(fixture_text("nbs.html"), "https://nbs.sk/page/")
    mfsr_docs = mfsr.parse(fixture_text("mfsr-2025.html"), mfsr.year_url(2025))

    assert (len(nbs_docs), _digest(nbs_docs)) == (12, "b21c91d19615918144867b29afedd6c4b4c8e9054400165d9b5b37c82c96bce9")
    assert (len(mfsr_docs), _digest(mfsr_docs)) == (36, "2ccc18df0fa3e2ca490750602719ac6de8c75432bcaa479e4447e796a64861ea")
