"""The documented robots rules: mfsr.sk disallows /components and /thumb (the grab refuses them), nbs.sk allows all, financnasprava.sk has no robots.txt (404)."""
from __future__ import annotations

import pytest

from dp_sk_metodika_grab import robots


@pytest.mark.unit
def test_should_carry_the_mfsr_rule_text() -> None:
    text = robots.rule_text("www.mfsr.sk")

    assert text is not None
    assert "Disallow: /components" in text
    assert "Disallow: /thumb" in text


@pytest.mark.unit
@pytest.mark.parametrize(
    ("url", "blocked"),
    [
        ("https://www.mfsr.sk/components/mfsrweb/file_archiv/file_list.jsp?file_bean_id=1", True),
        ("https://www.mfsr.sk/components/x/y.pdf", True),
        ("https://www.mfsr.sk/thumb/img.pdf", True),
        ("https://www.mfsr.sk/files/archiv/3/Usmernenie.pdf", False),
        ("https://www.mfsr.sk/sk/financie/financny-spravodajca/2025/", False),
        ("https://mfsr.sk/components/x.pdf", True),
        ("https://nbs.sk/_img/Documents/x.pdf", False),
        ("https://nbs.sk/components/x.pdf", False),
        ("https://www.financnasprava.sk//_img/pfsedit/Zverejnovanie_dok/x.pdf", False),
    ],
)
def test_should_refuse_the_disallowed_mfsr_paths_only(url: str, blocked: bool) -> None:
    assert robots.is_disallowed(url) is blocked


@pytest.mark.unit
def test_should_document_nbs_as_allow_all_and_financnasprava_as_without_robots() -> None:
    assert "Disallow:" in (robots.rule_text("nbs.sk") or "")
    assert robots.rule_text("nbs.sk") is not None
    assert robots.rule_text("www.financnasprava.sk") is None


@pytest.mark.unit
def test_should_quote_the_uvo_rule_and_the_decision() -> None:
    text = robots.UVO_RULE

    assert "User-agent: *" in text
    assert "Disallow: /" in text
    assert "D141" in robots.UVO_DECISION
