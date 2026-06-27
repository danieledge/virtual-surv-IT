"""
test_wash_trade.py - DEMO ARTIFACT (not collected by the repo suite; testpaths = ["tests"]).

The actual pytest produced by `rules-developer` (Mateo) during the build demo. Fully synthetic,
fabricated data - no real accounts or trades. Demonstrates that off-market price is a NECESSARY
condition (true-positive alerts; competitive-price pair does NOT).

To run this demo example in isolation:  pytest docs/demos/build-artifacts/test_wash_trade.py
"""
from datetime import datetime, date

import pytest

from wash_trade import detect_wash_trades  # noqa: needs this dir on sys.path when run standalone

# Thresholds are PLACEHOLDER values for test purposes only - NOT SME-approved production values.
TEST_PARAMS = {
    "price_tolerance_pct": 2.0,     # PLACEHOLDER - awaiting calibration
    "ubo_staleness_days": 90,       # PLACEHOLDER - awaiting calibration
    "min_notional": 1_000,          # PLACEHOLDER - awaiting calibration
    "lookback_seconds": 300,        # PLACEHOLDER - awaiting calibration
    "market_mid": {"ACME": 100.0},
    "as_of_date": date(2026, 1, 15),  # reference "today" - deterministic, not wall-clock
}

_NOW = datetime(2026, 1, 15, 10, 0, 0)
_FRESH_UBO_DATE = date(2026, 1, 1)    # 14 days before as_of_date - well within the staleness window


def _trade(trade_id, account_id, side, price, notional=50_000, ts=None):
    return {
        "trade_id": trade_id,
        "account_id": account_id,
        "instrument": "ACME",
        "side": side,
        "price": price,
        "quantity": int(notional / price),
        "notional": notional,
        "timestamp": ts or _NOW,
    }


def test_true_positive_wash_trade():
    """UBO-linked accounts, sell price 6% off mid (>2% tolerance) -> exactly one alert."""
    buy = _trade("T001", "ACC-001", "B", price=106.0)
    sell = _trade("T002", "ACC-002", "S", price=106.0)

    def ubo_link(a, b):
        return {"linked": True, "as_of": _FRESH_UBO_DATE} if {a, b} == {"ACC-001", "ACC-002"} else None

    alerts = detect_wash_trades([buy, sell], TEST_PARAMS, ubo_link, exemptions=set())
    assert len(alerts) == 1
    assert alerts[0].buy_trade_id == "T001"
    assert alerts[0].sell_trade_id == "T002"
    assert alerts[0].price_deviation_pct == pytest.approx(6.0, abs=0.01)


def test_false_positive_competitive_price_suppressed():
    """Same UBO-linked pair but price only 0.5% from mid -> must NOT alert (price is necessary)."""
    buy = _trade("T003", "ACC-001", "B", price=100.5)
    sell = _trade("T004", "ACC-002", "S", price=100.5)

    def ubo_link(a, b):
        return {"linked": True, "as_of": _FRESH_UBO_DATE} if {a, b} == {"ACC-001", "ACC-002"} else None

    alerts = detect_wash_trades([buy, sell], TEST_PARAMS, ubo_link, exemptions=set())
    assert alerts == [], "Competitive-price pair should not alert - off-market price is necessary."
