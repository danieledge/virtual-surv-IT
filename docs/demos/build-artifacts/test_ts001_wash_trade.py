"""
TS-001 wash-trade detector tests (DEMO - fully synthetic data only, CLAUDE.md §5).

Covers the validated acceptance criteria (SCN-001 §6): true-positive wash shapes that MUST alert
and false-positive controls that MUST NOT. All identifiers, prices and notionals are synthetic.

Run: python -m pytest docs/demos/build-artifacts/test_ts001_wash_trade.py -q
"""

from datetime import date, timedelta

import pytest

from ts001_wash_trade import (
    DEFAULT_UBO_GRAPH_MAX_AGE_DAYS,
    DetectionParams,
    MarketSnapshot,
    Trade,
    UBOLink,
    detect_wash_trades,
)

AS_OF = date(2026, 6, 30)
FRESH = AS_OF - timedelta(days=1)  # graph well within the freshness limit
INSTR = "SYNTH-EQ-001"

# A liquid reference: mid 100.00, 5 bps time-weighted spread. A 100.60 fill is ~60 bps off mid
# = ~12x the spread, comfortably off-market; a 100.00 fill is at-market.
SNAP = MarketSnapshot(INSTR, AS_OF, mid_price=100.00, time_weighted_spread_bps=5.0)


def _ubo(*accounts: str, group: str = "UBO-SYNTH-X", as_of: date = FRESH) -> list[UBOLink]:
    return [UBOLink(a, group, as_of) for a in accounts]


def _run(trades, ubo, snapshots=(SNAP,), params=None):
    return detect_wash_trades(trades, ubo, snapshots, AS_OF, params)


# --------------------------------------------------------------------------------------------
# True positives - MUST alert
# --------------------------------------------------------------------------------------------

def test_tp_cross_account_off_market_same_ubo():
    """Two accounts in one UBO group, opposing legs, off-market -> one alert with keystone fields."""
    trades = [
        Trade("T-BUY", "ACCT-A", INSTR, "BUY", 100.60, 1000, AS_OF),
        Trade("T-SELL", "ACCT-B", INSTR, "SELL", 100.60, 1000, AS_OF),
    ]
    result = _run(trades, _ubo("ACCT-A", "ACCT-B"))

    assert len(result.alerts) == 1
    a = result.alerts[0]
    assert a.ubo_group_id == "UBO-SYNTH-X"          # keystone linkage is a field
    assert a.obligation_reference == "EU MAR Art.12(1)(a)"
    assert a.obligation_status == "PROVISIONAL"       # mapping not finalised
    assert {a.buy_trade_id, a.sell_trade_id} == {"T-BUY", "T-SELL"}
    assert a.spread_normalised_deviation > a.off_market_spread_multiple


def test_tp_single_account_both_sides():
    """Single account on both sides (SCN-001 §3 in-scope) off-market -> alert."""
    trades = [
        Trade("T-B", "ACCT-C", "SYNTH-EQ-002", "BUY", 100.60, 1000, AS_OF),
        Trade("T-S", "ACCT-C", "SYNTH-EQ-002", "SELL", 100.60, 1000, AS_OF),
    ]
    snap = MarketSnapshot("SYNTH-EQ-002", AS_OF, 100.00, 5.0)
    result = _run(trades, _ubo("ACCT-C"), snapshots=(snap,))

    assert len(result.alerts) == 1
    assert result.alerts[0].buy_account_id == result.alerts[0].sell_account_id == "ACCT-C"


def test_tp_off_market_within_lookback_not_same_day():
    """Legs a day apart (inside the lookback) still pair and alert."""
    trades = [
        Trade("T-B2", "ACCT-A", INSTR, "BUY", 100.70, 2000, AS_OF - timedelta(days=1)),
        Trade("T-S2", "ACCT-B", INSTR, "SELL", 100.70, 2000, AS_OF),
    ]
    snap_prev = MarketSnapshot(INSTR, AS_OF - timedelta(days=1), 100.00, 5.0)
    result = _run(trades, _ubo("ACCT-A", "ACCT-B"), snapshots=(SNAP, snap_prev))

    assert len(result.alerts) == 1
    assert result.alerts[0].spread_normalised_deviation > 1.0


# --------------------------------------------------------------------------------------------
# False-positive controls - MUST NOT alert
# --------------------------------------------------------------------------------------------

def test_fp_affiliated_funds_at_market():
    """Affiliated funds (same UBO) trading AT market fail the necessary condition (DR-002)."""
    trades = [
        Trade("T-B", "FUND-1", INSTR, "BUY", 100.00, 5000, AS_OF),
        Trade("T-S", "FUND-2", INSTR, "SELL", 100.01, 5000, AS_OF),  # within the spread
    ]
    result = _run(trades, _ubo("FUND-1", "FUND-2"))
    assert result.alerts == []


def test_fp_coincident_independent_orders_liquid_price():
    """Coincident orders at the liquid mid by UNRELATED accounts -> no UBO link and at-market."""
    trades = [
        Trade("T-B", "INDEP-1", INSTR, "BUY", 100.00, 3000, AS_OF),
        Trade("T-S", "INDEP-2", INSTR, "SELL", 100.00, 3000, AS_OF),
    ]
    ubo = _ubo("INDEP-1", group="UBO-1") + _ubo("INDEP-2", group="UBO-2")  # different owners
    result = _run(trades, ubo)
    assert result.alerts == []


def test_fp_designated_mm_strategy_tagged_cross():
    """An off-market cross is suppressed (not alerted) when a leg is MM/strategy-tagged (DR-003)."""
    trades = [
        Trade("T-B", "MM-ACCT", INSTR, "BUY", 100.60, 1000, AS_OF, strategy_tag="MARKET_MAKER"),
        Trade("T-S", "ACCT-B", INSTR, "SELL", 100.60, 1000, AS_OF),
    ]
    result = _run(trades, _ubo("MM-ACCT", "ACCT-B"))
    assert result.alerts == []
    assert any("safe-harbour" in s for s in result.suppressions)


def test_fp_immaterial_notional():
    """Off-market, UBO-linked, but below the materiality floor -> no alert (DR-004)."""
    trades = [
        Trade("T-B", "ACCT-A", INSTR, "BUY", 100.60, 5, AS_OF),   # ~503 notional
        Trade("T-S", "ACCT-B", INSTR, "SELL", 100.60, 5, AS_OF),
    ]
    result = _run(trades, _ubo("ACCT-A", "ACCT-B"))
    assert result.alerts == []


def test_fp_stale_ubo_graph_warns_no_alert():
    """A stale UBO graph excludes the account and raises a DQ warning instead of alerting (DR-005)."""
    stale = AS_OF - timedelta(days=DEFAULT_UBO_GRAPH_MAX_AGE_DAYS + 5)
    trades = [
        Trade("T-B", "ACCT-D", INSTR, "BUY", 100.60, 1000, AS_OF),
        Trade("T-S", "ACCT-E", INSTR, "SELL", 100.60, 1000, AS_OF),
    ]
    ubo = _ubo("ACCT-D", "ACCT-E", as_of=stale)
    result = _run(trades, ubo)
    assert result.alerts == []
    assert any("old" in w.lower() for w in result.data_quality_warnings)


# --------------------------------------------------------------------------------------------
# Guards / governance
# --------------------------------------------------------------------------------------------

def test_implied_match_tier_disabled_raises():
    """DR-006 is OFF at launch (SME Q5): requesting it fails loudly rather than silently scoring."""
    params = DetectionParams(enable_implied_match_tier=True)
    with pytest.raises(NotImplementedError):
        _run([], [], params=params)


def test_no_snapshot_is_dq_warning_not_alert():
    """A missing market snapshot is surfaced as a coverage gap, not silently dropped."""
    trades = [
        Trade("T-B", "ACCT-A", INSTR, "BUY", 100.60, 1000, AS_OF),
        Trade("T-S", "ACCT-B", INSTR, "SELL", 100.60, 1000, AS_OF),
    ]
    result = _run(trades, _ubo("ACCT-A", "ACCT-B"), snapshots=())
    assert result.alerts == []
    assert any("snapshot" in w.lower() for w in result.data_quality_warnings)


def test_non_positive_mid_is_dq_warning_not_silent_drop():
    """A non-positive mid must not be silently discarded (W1/NOTE-001): no alert AND a DQ warning.

    A bad mid makes the off-market deviation meaningless; the detector must mirror the
    non-positive-SPREAD guard and surface a data-quality warning rather than dropping the pair
    with no audit record (which would be a silent false negative).
    """
    bad_mid = MarketSnapshot(INSTR, AS_OF, mid_price=0.0, time_weighted_spread_bps=5.0)
    trades = [
        Trade("T-B", "ACCT-A", INSTR, "BUY", 100.60, 1000, AS_OF),
        Trade("T-S", "ACCT-B", INSTR, "SELL", 100.60, 1000, AS_OF),
    ]
    result = _run(trades, _ubo("ACCT-A", "ACCT-B"), snapshots=(bad_mid,))
    assert result.alerts == []
    assert any("mid" in w.lower() for w in result.data_quality_warnings)


def test_multiple_ubo_edges_freshest_wins_no_spurious_staleness():
    """M4: a fresh + a stale edge for one account -> keep the freshest, include it, no DQ warning.

    Order-independence: a stale row delivered alongside a fresh one must not shadow it and raise a
    spurious 'stale graph -> excluded' warning. Both legs' accounts carry a stale edge listed before
    the fresh edge, so a naive order-dependent loop would exclude them.
    """
    stale = AS_OF - timedelta(days=DEFAULT_UBO_GRAPH_MAX_AGE_DAYS + 5)
    ubo = [
        UBOLink("ACCT-A", "UBO-SYNTH-X", stale),   # stale edge first ...
        UBOLink("ACCT-A", "UBO-SYNTH-X", FRESH),   # ... fresh edge after
        UBOLink("ACCT-B", "UBO-SYNTH-X", stale),
        UBOLink("ACCT-B", "UBO-SYNTH-X", FRESH),
    ]
    trades = [
        Trade("T-BUY", "ACCT-A", INSTR, "BUY", 100.60, 1000, AS_OF),
        Trade("T-SELL", "ACCT-B", INSTR, "SELL", 100.60, 1000, AS_OF),
    ]
    result = _run(trades, ubo)
    assert len(result.alerts) == 1               # freshest edge keeps the accounts in scope
    assert result.data_quality_warnings == []    # no spurious staleness warning
