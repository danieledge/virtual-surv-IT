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


# --- working-project overlay (plugin-mode commit path) ------------------------------------


def test_overlay_extends_and_overrides(tmp_path, monkeypatch):
    """Entries in the working project's config/regulatory-register.yaml merge with the
    bundled register: new ids extend, matching ids override (verified locally)."""
    from scripts.check_citations import _load_register

    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "regulatory-register.yaml").write_text(
        "obligations:\n"
        "  - id: LOCAL-1\n"
        "    pinpoint: Rule 99-1\n"
        "    status: verified\n"
        "  - id: MAR-ART12-1A\n"
        "    pinpoint: MAR Art.12(1)(a)\n"
        "    status: verified\n"
        "    verified_on: '2026-07-21'\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    reg = _load_register()
    by_id = {o["id"]: o for o in reg["obligations"]}
    assert "LOCAL-1" in by_id  # extended
    assert by_id["MAR-ART12-1A"]["verified_on"] == "2026-07-21"  # overridden
    assert len(by_id) > 2  # bundled entries still present


# --- handbook-style detection + status-aware verification (demo-found gaps) ---------------


def test_handbook_style_citations_detected():
    from scripts.check_citations import find_citations

    found = find_citations("Prohibited under FCA MAR 1.6; see SYSC 6.1.1R and MAR Art.12(1)(a).")
    assert "MAR 1.6" in found and "SYSC 6.1.1R" in found
    # prose numbers and undotted codes stay out
    assert not any(
        "chapter" in f.lower() for f in find_citations("in chapter 6 we discuss ISO 29119")
    )


def test_unverified_register_entries_flag_to_verify():
    """status: example (or missing verified_on) is in the ledger but NOT human-verified -
    citing it must flag, not pass. The FCA seeds are exactly this state."""
    from scripts.check_citations import check_text

    reg = {
        "obligations": [
            {"id": "A", "pinpoint": "MAR 1.6", "status": "example", "verified_on": "-"},
            {
                "id": "B",
                "pinpoint": "SYSC 6.1.1R",
                "status": "verified",
                "verified_on": "2026-07-21",
            },
        ]
    }
    out = check_text("cites MAR 1.6 and SYSC 6.1.1R", register=reg)
    assert out["unverified"] == ["MAR 1.6"]
    assert out["verified"] == ["SYSC 6.1.1R"]
