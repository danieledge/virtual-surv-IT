"""Tests for the regulatory-citation grounding (scripts/check_citations.py + the register)."""

from __future__ import annotations

from rules.spoofing import SpoofingAlert
from scripts.check_citations import check_text, find_citations, lookup


def test_known_pinpoint_is_verified():
    res = check_text("This detection serves MAR Art.12(1)(a), and comms uses Art.16(7).")
    assert res["unverified"] == []
    assert any("12(1)(a)" in c for c in res["verified"])


def test_fabricated_pinpoint_is_flagged():
    # A confident, invented citation (the citation-flag-unverified eval draft) must be caught.
    res = check_text("This control fully satisfies MAR Article 48, and Rule 10b-5(c)(2).")
    cores = " ".join(res["unverified"]).lower()
    assert "48" in cores
    assert "10b-5" in cores
    assert res["verified"] == []


def test_lookup_retrieves_grounded_obligation():
    hits = lookup("spoofing")
    assert any(h["id"] == "MAR-ART12-1A" for h in hits)
    assert all("pinpoint" in h for h in hits)


def test_find_citations_detects_multiple_shapes():
    cites = find_citations("See Article 12, Rule 4511, Section 76 and 17a-4(b)(4).")
    joined = " ".join(cites).lower()
    assert "article 12" in joined
    assert "rule 4511" in joined
    assert "17a-4(b)(4)" in joined


def test_rule_obligation_string_is_register_grounded():
    # The spoofing rule's own obligation citation must not be flagged as unverified - i.e. the
    # register actually covers what the repo ships, so the gate is self-consistent.
    obligation = SpoofingAlert.__dataclass_fields__["obligation"].default
    res = check_text(obligation)
    assert res["unverified"] == []
