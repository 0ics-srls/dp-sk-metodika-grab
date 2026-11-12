"""Financna sprava listing parsers: the legacy FsParseTests 1:1 plus recorded real pages (single-quoted hrefs, the title attribute is noise)."""
from __future__ import annotations

import pytest

from conftest import fixture_text
from dp_sk_metodika_grab import fs

PREHLADY = (
    "https://www.financnasprava.sk/sk/danovi-a-colni-specialisti/dane/prehlady-zmluv-zdz/_1/D%c3%a1tum%20publikovania/Mw==/MjQ=/MA==/MA==/MTA=/bnVsbA==/opb"
)


@pytest.mark.unit
def test_should_extract_code_and_doc_id_when_the_title_is_coded() -> None:
    doc = fs.make_document(
        "metodicke-pokyny",
        "10/DZPaU/2026/MP \N{EN DASH} Metodický pokyn k \N{HORIZONTAL ELLIPSIS}",
        "https://www.financnasprava.sk/_img/Zverejnovanie_dok/dane/2026/mp/subor_2026.05.13.pdf",
    )

    assert doc.number == 10
    assert doc.dept == "DZPaU"
    assert doc.year == 2026
    assert doc.doc_type == "MP"
    assert doc.code == "10/DZPaU/2026/MP"
    assert doc.doc_id == "10_DZPaU_2026_MP"
    assert doc.category == "dane"  # folder just above the {year} segment
    assert doc.published == "2026-05-13"  # from YYYY.MM.DD in the filename


@pytest.mark.unit
def test_should_slug_the_file_stem_when_the_title_has_no_code() -> None:
    doc = fs.make_document("zavery-komisii", "Zápis zo zasadnutia", "https://www.financnasprava.sk/_img/Zverejnovanie_dok/zavery/zapis-final.pdf")

    assert doc.code is None
    assert doc.doc_id == "zapis-final"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("10/DZPaU", "10_DZPaU"),
        ("a b?c", "a_b_c"),
        ("výnos-č.5", "výnos-č.5"),  # R5: Unicode letters KEPT, dot + dash preserved
        ("///", "dokument"),
        ("", "dokument"),
    ],
)
def test_should_match_the_python_unicode_slug_rule(value: str, expected: str) -> None:
    assert fs.slug(value) == expected


@pytest.mark.unit
def test_should_keep_only_zverejnovanie_dok_pdfs_with_titles() -> None:
    page = """
        <html><body>
          <a href="https://x.sk/_img/Zverejnovanie_dok/dane/2026/mp/a_2026.01.02.pdf">Dok A</a>
          <a href="https://x.sk/_img/Zverejnovanie_dok/dane/2026/mp/b_2026.03.04.pdf">Dok B</a>
          <a href="https://x.sk/_img/Zverejnovanie_dok/dane/logo.png">image not pdf</a>
          <a href="https://x.sk/other/nope.pdf">pdf but not in the doc store</a>
          <a href="https://x.sk/_img/Zverejnovanie_dok/dane/2026/mp/c.pdf"><img src="i.png"></a>
        </body></html>
        """

    docs = fs.parse_listing(page, "https://x.sk/base", "metodicke-pokyny")

    assert [d.title for d in docs] == ["Dok A", "Dok B"]  # image-only link (empty title) dropped
    assert docs[0].category == "dane"
    assert docs[0].published == "2026-01-02"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("base", "n", "expected"),
    [
        ("https://x.sk/base", 1, "https://x.sk/base"),
        ("https://x.sk/base", 2, "https://x.sk/base/_2"),
        ("https://x.sk/p/_1/Datum/opb", 2, "https://x.sk/p/_2/Datum/opb"),  # embedded marker rewrite
    ],
)
def test_should_build_the_page_url_like_the_python_scraper(base: str, n: int, expected: str) -> None:
    assert fs.page_url(base, n) == expected


@pytest.mark.unit
def test_should_resolve_a_relative_href_against_the_page_url() -> None:
    page = "<a href='/_img/Zverejnovanie_dok/dane/2026/a_2026.01.02.pdf'>Dok A</a>"

    docs = fs.parse_listing(page, "https://www.financnasprava.sk/sk/x/metodicke-pokyny", "metodicke-pokyny")

    assert [d.pdf_url for d in docs] == ["https://www.financnasprava.sk/_img/Zverejnovanie_dok/dane/2026/a_2026.01.02.pdf"]


@pytest.mark.unit
def test_should_parse_the_recorded_metodicke_pokyny_page_with_single_quoted_hrefs() -> None:
    assert "<a href='https://www.financnasprava.sk//_img/pfsedit/Dokumenty_PFS/Zverejnovanie_dok" in fixture_text("fs-pokyny-1.html")

    docs = fs.parse_listing(fixture_text("fs-pokyny-1.html"), "https://www.financnasprava.sk/sk/danovi-a-colni-specialisti/dane/metodicke-pokyny", "metodicke-pokyny")

    assert len(docs) == 10
    first = docs[0]
    assert first.code == "12/DZPaU/2026/MP"
    assert (first.number, first.dept, first.year, first.doc_type) == (12, "DZPaU", 2026, "MP")
    assert first.category == "Priame_dane_uct"
    assert first.published == "2026-08-18"
    assert first.doc_id == "12_DZPaU_2026_MP"
    assert first.title.startswith("12/DZPaU/2026/MP - Metodický pokyn k minimálnej dani právnickej osoby")
    assert first.pdf_url.endswith("/Zverejnovanie_dok/Dane/Metodicke_pokyny/Priame_dane_uct/2026/2026.08.18_012_DZPaU_2026_MP_Minim_dan_PO.pdf")
    assert len({d.pdf_url for d in docs}) == 10


@pytest.mark.unit
def test_should_ignore_the_title_attribute_with_the_size_and_new_window_note() -> None:
    docs = fs.parse_listing(fixture_text("fs-pokyny-1.html"), "https://www.financnasprava.sk/x", "metodicke-pokyny")

    for doc in docs:
        assert ".pdf;" not in doc.title
        assert "nové okno" not in doc.title
        assert " KB" not in doc.title


@pytest.mark.unit
def test_should_parse_the_other_recorded_listings() -> None:
    base = "https://www.financnasprava.sk/x"

    assert len(fs.parse_listing(fixture_text("fs-usmernenia-1.html"), base, "metodicke-usmernenia")) == 10
    zavery = fs.parse_listing(fixture_text("fs-zavery.html"), base, "zavery-komisii")
    assert len(zavery) == 3
    assert all(d.code is None for d in zavery)  # minutes carry no code: the doc id is the slugged stem
    assert all(d.doc_id == fs.slug(fs.url_path_stem(d.pdf_url)) for d in zavery)
    assert len(fs.parse_listing(fixture_text("fs-prehlady-1.html"), base, "prehlady-zmluv-zdz")) == 7
    assert fs.parse_listing(fixture_text("fs-pokyny-3-empty.html"), base, "metodicke-pokyny") == []


@pytest.mark.unit
def test_should_take_the_url_path_stem_without_decoding() -> None:
    assert fs.url_path_stem("https://x.sk/a/b%20c.d.pdf?x=1") == "b%20c.d"
    assert fs.url_path_stem("https://x.sk/a/noext") == "noext"


@pytest.mark.unit
def test_should_list_the_four_sections_with_the_exact_prehlady_url() -> None:
    sections = fs.sections()

    assert list(sections) == ["metodicke-pokyny", "metodicke-usmernenia", "zavery-komisii", "prehlady-zmluv-zdz"]
    assert sections["metodicke-pokyny"] == "https://www.financnasprava.sk/sk/danovi-a-colni-specialisti/dane/metodicke-pokyny"
    assert sections["metodicke-usmernenia"] == "https://www.financnasprava.sk/sk/danovi-a-colni-specialisti/dane/metodicke-usmernenia"
    assert sections["zavery-komisii"] == "https://www.financnasprava.sk/sk/danovi-a-colni-specialisti/dane/zavery-zo-zasadnuti-MFSR"
    assert sections["prehlady-zmluv-zdz"] == PREHLADY
    assert fs.sections("https://replay.test/dane/")["metodicke-pokyny"] == "https://replay.test/dane/metodicke-pokyny"
