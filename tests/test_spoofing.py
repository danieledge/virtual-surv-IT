"""
Tests for the MAR spoofing detection rule (CLAUDE.md §4: known true-positive and
false-positive cases are mandatory). All fixtures are synthetic (§5).
"""

from __future__ import annotations

from rules.spoofing import (
    EventKind,
    OrderEvent,
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


def _new(ts, oid, side, qty):
    return OrderEvent(ts, "T1", "INSTR", oid, side, 100.0, qty, EventKind.NEW)


def _fill(ts, oid, side, qty):
    return OrderEvent(ts, "T1", "INSTR", oid, side, 100.0, qty, EventKind.FILL)


def _cancel(ts, oid, side):
    return OrderEvent(ts, "T1", "INSTR", oid, side, 100.0, 0.0, EventKind.CANCEL)


def test_repeat_spoofer_not_masked_by_own_orders():
    """Regression: a trader who spoofs repeatedly must not escape because their own large
    spoofs inflate the median size baseline. Here large spoofs OUTNUMBER genuine orders, so an
    all-orders median (the old logic) is 600 -> threshold 3000 -> zero alerts. The genuine-only
    baseline is 100 -> threshold 500 -> every spoof fires."""
    events = [
        # Three genuine filled orders (qty 100) - the only legitimate size signal.
        _new(1000, "GEN_BUY_C", Side.BUY, 100),
        _fill(1100, "GEN_BUY_C", Side.BUY, 100),
        _new(4900, "GEN_SELL_A", Side.SELL, 100),
        _fill(5000, "GEN_SELL_A", Side.SELL, 100),
        _new(9900, "GEN_SELL_B", Side.SELL, 100),
        _fill(10000, "GEN_SELL_B", Side.SELL, 100),
    ]
    # Four outsized BUY spoofs (qty 600 = 6x), each placed-and-cancelled fast, ~unfilled,
    # each benefiting from a genuine opposite-side SELL fill in-window.
    for oid, place in [("SP0", 5000), ("SP1", 5200), ("SP2", 9800), ("SP3", 10100)]:
        events.append(_new(place, oid, Side.BUY, 600))
        events.append(_cancel(place + 500, oid, Side.BUY))

    alerts = detect_spoofing(events)
    assert len(alerts) == 4, f"expected all 4 repeat spoofs flagged, got {len(alerts)}"
    assert {a.spoof_order_id for a in alerts} == {"SP0", "SP1", "SP2", "SP3"}


def test_same_timestamp_fill_before_new_not_lost():
    """Regression: a FILL listed before its NEW at the same ms must still be applied (NEW is
    processed first within a timestamp), so the fill is not silently dropped."""
    events = [
        _fill(5000, "O1", Side.BUY, 100),  # listed BEFORE its NEW, same ms
        _new(5000, "O1", Side.BUY, 100),
    ]
    orders = reconstruct_orders(events)
    assert orders["O1"].filled_qty == 100.0
    assert orders["O1"].fill_ratio == 1.0
