"""Independent QA suite for TS-001 (qa-engineer / Linh). Synthetic only (CLAUDE.md §5).
Covers the branches the developer suite does not: boundaries, exemptions, multi-instrument,
missing-snapshot observability, same-account, cross-UBO. Run:
  cd docs/demos/build-artifacts && python3 -m pytest test_ts001_qa.py"""
import logging
from datetime import date

import pytest

from ts001_wash_trade import (
    DetectionParams, MarketSnapshot, Trade, UBOGraphStaleError, UBOLink,
    detect_wash_trades,
)

AS_OF = date(2026, 6, 27)
P = DetectionParams(lookback_days=5, off_market_threshold_bps=50.0,
                    ubo_graph_max_age_days=7, exempt_account_ids=frozenset({"MM-ACCT-001"}))
LINKS = [UBOLink("ACCT-A", "UBO-X"), UBOLink("ACCT-B", "UBO-X"),
         UBOLink("ACCT-C", "UBO-Y"), UBOLink("MM-ACCT-001", "UBO-X")]
SNAP = MarketSnapshot("SYNTH-EQ-001", date(2026, 6, 27), 100.00, 20.0)


def _pair(buy_acct, sell_acct, price=100.60, d=date(2026, 6, 27), instr="SYNTH-EQ-001"):
    return [Trade("B", buy_acct, instr, "BUY", price, 500.0, d),
            Trade("S", sell_acct, instr, "SELL", price, 500.0, d)]


def test_staleness_boundary_exactly_at_limit_ok():
    # age == max_age_days (7) must NOT raise (boundary is "older than", strict >)
    detect_wash_trades([], LINKS, date(2026, 6, 20), [], P, AS_OF)


def test_staleness_one_over_limit_raises():
    with pytest.raises(UBOGraphStaleError):
        detect_wash_trades([], LINKS, date(2026, 6, 19), [], P, AS_OF)


def test_lookback_boundary_inclusive():
    t = _pair("ACCT-A", "ACCT-B", d=date(2026, 6, 27))
    t[1] = Trade("S", "ACCT-B", "SYNTH-EQ-001", "SELL", 100.60, 500.0, date(2026, 6, 22))  # 5d
    assert len(detect_wash_trades(t, LINKS, date(2026, 6, 26), [SNAP], P, AS_OF)) == 1


def test_lookback_one_over_suppressed():
    t = _pair("ACCT-A", "ACCT-B")
    t[1] = Trade("S", "ACCT-B", "SYNTH-EQ-001", "SELL", 100.60, 500.0, date(2026, 6, 21))  # 6d
    assert detect_wash_trades(t, LINKS, date(2026, 6, 26), [SNAP], P, AS_OF) == []


def test_deviation_exactly_at_threshold_alerts():
    # 50 bps on a 100 mid = price 100.50 ; >= threshold fires
    t = _pair("ACCT-A", "ACCT-B", price=100.50)
    assert len(detect_wash_trades(t, LINKS, date(2026, 6, 26), [SNAP], P, AS_OF)) == 1


def test_deviation_just_under_threshold_suppressed():
    t = _pair("ACCT-A", "ACCT-B", price=100.49)  # 49 bps
    assert detect_wash_trades(t, LINKS, date(2026, 6, 26), [SNAP], P, AS_OF) == []


def test_exempt_account_suppressed():
    assert detect_wash_trades(_pair("MM-ACCT-001", "ACCT-B"), LINKS, date(2026, 6, 26), [SNAP], P, AS_OF) == []


def test_same_account_not_matched():
    assert detect_wash_trades(_pair("ACCT-A", "ACCT-A"), LINKS, date(2026, 6, 26), [SNAP], P, AS_OF) == []


def test_cross_ubo_not_matched():
    assert detect_wash_trades(_pair("ACCT-A", "ACCT-C"), LINKS, date(2026, 6, 26), [SNAP], P, AS_OF) == []


def test_cross_instrument_not_matched():
    t = [Trade("B", "ACCT-A", "SYNTH-EQ-001", "BUY", 100.60, 500.0, date(2026, 6, 27)),
         Trade("S", "ACCT-B", "SYNTH-EQ-002", "SELL", 100.60, 500.0, date(2026, 6, 27))]
    assert detect_wash_trades(t, LINKS, date(2026, 6, 26), [SNAP], P, AS_OF) == []


def test_missing_snapshot_is_logged_not_silent(caplog):
    # QA DEF-001 fix: a missing snapshot must surface as a data-quality warning, not vanish.
    with caplog.at_level(logging.WARNING, logger="ts001"):
        out = detect_wash_trades(_pair("ACCT-A", "ACCT-B"), LINKS, date(2026, 6, 26), [], P, AS_OF)
    assert out == []
    assert any("no market snapshot" in r.message for r in caplog.records)


def test_unmapped_account_skipped_no_crash():
    links = [UBOLink("ACCT-A", "UBO-X")]  # ACCT-B absent from graph
    assert detect_wash_trades(_pair("ACCT-A", "ACCT-B"), links, date(2026, 6, 26), [SNAP], P, AS_OF) == []


def test_empty_input_no_crash():
    assert detect_wash_trades([], LINKS, date(2026, 6, 26), [SNAP], P, AS_OF) == []
