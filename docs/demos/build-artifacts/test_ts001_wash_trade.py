"""Developer tests for TS-001 wash-trade detection. Synthetic only (CLAUDE.md §5).
Run in isolation:  cd docs/demos/build-artifacts && python3 -m pytest test_ts001_wash_trade.py"""
from datetime import date

import pytest

from ts001_wash_trade import (
    DetectionParams, MarketSnapshot, Trade, UBOGraphStaleError, UBOLink,
    detect_wash_trades,
)

AS_OF = date(2026, 6, 27)
UBO_AS_OF = date(2026, 6, 26)
PARAMS = DetectionParams(
    lookback_days=5, off_market_threshold_bps=50.0,
    ubo_graph_max_age_days=7, exempt_account_ids=frozenset({"MM-ACCT-001"}),
)
UBO_LINKS = [UBOLink("ACCT-A", "UBO-X"), UBOLink("ACCT-B", "UBO-X"), UBOLink("ACCT-C", "UBO-Y")]
OFF_MKT = MarketSnapshot("SYNTH-EQ-001", date(2026, 6, 27), 100.00, 20.0)
AT_MKT = MarketSnapshot("SYNTH-EQ-001", date(2026, 6, 25), 100.00, 20.0)


def test_true_positive_wash_trade():
    trades = [
        Trade("TRD-001", "ACCT-A", "SYNTH-EQ-001", "BUY", 100.60, 500.0, date(2026, 6, 27)),
        Trade("TRD-002", "ACCT-B", "SYNTH-EQ-001", "SELL", 100.60, 500.0, date(2026, 6, 27)),
    ]
    alerts = detect_wash_trades(trades, UBO_LINKS, UBO_AS_OF, [OFF_MKT], PARAMS, AS_OF)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.obligation == "MAR Art 12(1)(a)"          # carried as a field
    assert "PROVISIONAL" in a.obligation_status        # mapping not finalised (compliance fix)
    assert a.ubo_group_id == "UBO-X"                    # keystone id as a field
    assert a.snapshot_date == date(2026, 6, 27)         # which mid was used (audit fix W3)
    assert a.price_deviation_bps >= 50.0


def test_false_positive_at_market_suppressed():
    trades = [
        Trade("TRD-003", "ACCT-A", "SYNTH-EQ-001", "BUY", 100.00, 1000.0, date(2026, 6, 25)),
        Trade("TRD-004", "ACCT-B", "SYNTH-EQ-001", "SELL", 100.00, 1000.0, date(2026, 6, 25)),
    ]
    alerts = detect_wash_trades(trades, UBO_LINKS, UBO_AS_OF, [AT_MKT], PARAMS, AS_OF)
    assert alerts == []  # off-market is a necessary condition


def test_stale_ubo_graph_raises():
    with pytest.raises(UBOGraphStaleError):
        detect_wash_trades([], UBO_LINKS, date(2026, 6, 1), [], PARAMS, AS_OF)
