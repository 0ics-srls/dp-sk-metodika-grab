"""The robots.txt posture of the four hosts as read on 2026-11-12 (notes section 2.1). Nothing is fetched at run time; the rules are data.

mfsr.sk disallows ``/components`` and ``/thumb`` (the grab refuses such paths with the skip reason ``robots``), nbs.sk allows everything, financnasprava.sk
answers 404 (no policy), uvo.gov.sk disallows every path for generic agents (the grab refuses ``uvo-metodicke`` unless ``uvoRobotsAck``, decision D141).
"""
from __future__ import annotations

from urllib.parse import urlsplit

SKIP_REASON = "robots"
MFSR_DISALLOW = ("/components", "/thumb")
UVO_RULE = "User-agent: *\nDisallow: /"
UVO_DECISION = (
    "decision D141: the UVO adapter is OFF by default; it may run only after the project owner accepted the robots posture and set uvoRobotsAck=true"
)
_RULES: dict[str, str] = {
    "mfsr.sk": "User-agent: *\nDisallow: /components\nDisallow: /thumb",
    "nbs.sk": "User-agent: *\nDisallow:",
}


def _site(host: str) -> str:
    host = host.lower()
    return host.removeprefix("www.")


def rule_text(host: str) -> str | None:
    """The robots rules documented for ``host`` (``www.`` ignored); None when the host publishes none (financnasprava.sk)."""
    return _RULES.get(_site(host))


def is_disallowed(url: str) -> bool:
    """True for a path that the documented rules of the URL's host disallow for generic agents (mfsr.sk only; UVO is handled by the gate)."""
    parts = urlsplit(url)
    if _site(parts.hostname or "") != "mfsr.sk":
        return False
    return parts.path.startswith(MFSR_DISALLOW)
