"""The UVO robots gate (decision D141): uvo.gov.sk answers ``User-agent: * / Disallow: /``, so the adapter is off unless ``uvoRobotsAck`` is true.

The first tests cover the gate function; the run-level tests (zero requests to uvo.gov.sk through ``run_grab``) are in this file as well.
"""
from __future__ import annotations

import pytest

from dp_sk_metodika_grab import uvo
from dp_sk_metodika_grab.errors import CONFIG_ERROR, GrabError


@pytest.mark.unit
@pytest.mark.parametrize("ack", [None, False, "true", 1, 0, "", "yes"])
def test_should_refuse_uvo_unless_the_acknowledgement_is_exactly_true(ack: object) -> None:
    with pytest.raises(GrabError) as caught:
        uvo.require_ack(ack)

    error = caught.value
    assert error.code == CONFIG_ERROR
    assert "robots" in str(error)
    assert "User-agent: *" in str(error)
    assert "Disallow: /" in str(error)
    assert "D141" in str(error)
    assert "uvoRobotsAck" in str(error)


@pytest.mark.unit
def test_should_let_uvo_pass_when_the_acknowledgement_is_true() -> None:
    uvo.require_ack(True)  # noqa: FBT003


@pytest.mark.unit
def test_should_pace_uvo_at_two_seconds() -> None:
    assert uvo.HOST_DELAYS == {"www.uvo.gov.sk": 2.0}
