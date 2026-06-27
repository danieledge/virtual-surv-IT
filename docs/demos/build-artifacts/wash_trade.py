"""
wash_trade.py - DEMO ARTIFACT (not production; not collected by the repo test suite).

The actual detection sketch produced by `rules-developer` (Mateo) during the build demo
(see ../build-demo.md). Synthetic only (CLAUDE.md §5). It honours the SME's caveats: a
beneficial-owner (UBO) data-quality gate, off-market price as a NECESSARY condition, and an
exemption set. All thresholds are named parameters with NO invented values - tuning-analyst owns them.

Obligation: MAR Art. 12(1)(a) (EU); UK MAR Art. 12; SEC Rule 10b-5 / FINRA Rule 6140(b) (US).
Cite the applicable regime per desk before deploying.

Assumptions:
- `trades` is an iterable of dicts with keys:
      trade_id, account_id, instrument, side ('B'/'S'), price, quantity, notional, timestamp (datetime)
- `ubo_link(account_a, account_b)` returns {'linked': bool, 'as_of': date} or None if unknown.
- `exemptions` is a set of account_ids exempt from this scenario (e.g. designated market-makers;
  list maintained by Compliance).
- `params` must supply all threshold keys (no defaults - see the tuning note).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable


@dataclass
class WashTradeAlert:
    buy_trade_id: str
    sell_trade_id: str
    account_buy: str
    account_sell: str
    instrument: str
    price_deviation_pct: float
    reason: str


def detect_wash_trades(
    trades: Iterable[dict],
    params: dict,
    ubo_link: callable,
    exemptions: set[str],
) -> list[WashTradeAlert]:
    """
    Identify wash-trade / self-match pairs across accounts sharing a UBO.

    A pair is flagged only when ALL three conditions are satisfied:
      1. Both accounts share a confirmed, non-stale UBO link.
      2. At least one leg is priced off-market (|deviation| > price_tolerance_pct).
      3. Neither account appears in the active exemption set.

    params (ALL must be present - no defaults):
        price_tolerance_pct  - minimum % deviation from mid to be "off-market".
                               [TUNING REQUIRED - must exceed normal bid/ask spread. Date: pending.]
        ubo_staleness_days   - reject UBO links older than this.
                               [TUNING REQUIRED - regulatory expectation + data-refresh SLA. pending.]
        min_notional         - ignore pairs below this notional (noise filter). [TUNING REQUIRED.]
        lookback_seconds     - window within which a matching contra-leg is sought. [TUNING REQUIRED.]
        market_mid           - {instrument: mid_price}; injected so the function stays testable.
        as_of_date           - reference "today" for the UBO staleness check (a `date`). Injected
                               rather than read from the wall clock so the function is DETERMINISTIC
                               and testable - added at the code-review stage (the original sketch used
                               datetime.utcnow(), which is non-deterministic and broke the test).

    Raises KeyError if any required param is absent (fail-loud - no silent defaults).
    """
    required_keys = {
        "price_tolerance_pct", "ubo_staleness_days",
        "min_notional", "lookback_seconds", "market_mid", "as_of_date",
    }
    missing = required_keys - params.keys()
    if missing:
        raise KeyError(f"Missing required params: {missing}")

    alerts: list[WashTradeAlert] = []
    trade_list = list(trades)

    for i, buy in enumerate(trade_list):
        if buy["side"] != "B":
            continue
        if buy["account_id"] in exemptions:
            continue  # Exemption gate (condition 3, buy side)

        for sell in trade_list[i + 1:]:
            if sell["side"] != "S":
                continue
            if sell["instrument"] != buy["instrument"]:
                continue
            if sell["account_id"] in exemptions:
                continue  # Exemption gate (condition 3, sell side)
            if sell["account_id"] == buy["account_id"]:
                continue  # Same account - different scenario (intra-account wash)

            delta_secs = abs((sell["timestamp"] - buy["timestamp"]).total_seconds())
            if delta_secs > params["lookback_seconds"]:
                continue
            if min(buy["notional"], sell["notional"]) < params["min_notional"]:
                continue

            # --- Condition 1: UBO link (data-quality gate) ---
            link = ubo_link(buy["account_id"], sell["account_id"])
            if not link or not link["linked"]:
                continue  # No UBO connection - not in scope
            staleness_cutoff = params["as_of_date"] - timedelta(days=params["ubo_staleness_days"])
            if link["as_of"] < staleness_cutoff:
                continue  # Stale UBO data - skip; escalate to data-quality, do not false-positive

            # --- Condition 2: Off-market price (NECESSARY condition, per the SME) ---
            mid = params["market_mid"].get(buy["instrument"])
            if mid is None:
                continue  # No reference price - data-quality gap, not a detection gap
            deviation_pct = abs(sell["price"] - mid) / mid * 100
            if deviation_pct <= params["price_tolerance_pct"]:
                continue  # Price is competitive - necessary condition NOT met

            alerts.append(
                WashTradeAlert(
                    buy_trade_id=buy["trade_id"],
                    sell_trade_id=sell["trade_id"],
                    account_buy=buy["account_id"],
                    account_sell=sell["account_id"],
                    instrument=buy["instrument"],
                    price_deviation_pct=round(deviation_pct, 4),
                    reason=f"UBO-linked accounts, off-market price ({deviation_pct:.2f}% from mid)",
                )
            )

    return alerts
