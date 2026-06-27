"""
Tests for the MAR spoofing detection rule (CLAUDE.md §4: known true-positive and
false-positive cases are mandatory). All fixtures are synthetic (§5).
"""
from __future__ import annotations

from rules.spoofing import (
    Side,
    SpoofingThresholds,
    detect_spoofing,
    reconstruct_orders,
)
from scripts.gen_synthetic import (
    benign_session,
    large_genuine_session,
    spoofing_session,
)


def test_known_spoof_is_flagged():
    """True positive: the staged place-and-cancel + opposite fill must alert."""
    alerts = detect_spoofing(spoofing_session(seed=1))
    assert len(alerts) == 1
    a = alerts[0]
    assert a.spoof_order_id == "SPOOF1"
    assert a.spoof_side is Side.BUY
    assert a.benefiting_side is a.spoof_side.opposite
    assert a.spoof_fill_ratio <= 0.10
    assert a.spoof_lifetime_ms <= 2000
    assert "MAR" in a.obligation


def test_benign_session_produces_no_alert():
    """True negative: normal two-way trading must not alert."""
    assert detect_spoofing(benign_session(seed=2)) == []


def test_large_but_genuine_orders_not_flagged():
    """False-positive control: outsized orders that genuinely fill or rest must not alert."""
    assert detect_spoofing(large_genuine_session(seed=3)) == []


def test_thresholds_are_injectable_and_change_outcome():
    """Requiring a shorter place-and-cancel lifetime than the staged 1500ms suppresses the
    alert - proves the documented thresholds actually drive the decision (auditability)."""
    events = spoofing_session(seed=1)
    assert detect_spoofing(events)  # fires with defaults (max_spoof_lifetime_ms=2000)
    tight = SpoofingThresholds(max_spoof_lifetime_ms=1000)
    assert detect_spoofing(events, tight) == []


def test_reconstruct_orders_tracks_lifecycle():
    """Order folding computes lifetime and fill ratio used by the rule."""
    orders = reconstruct_orders(spoofing_session(seed=1))
    spoof = orders["SPOOF1"]
    assert spoof.cancelled_ms is not None
    assert spoof.fill_ratio == 0.0
    assert spoof.lifetime_ms == 1500
