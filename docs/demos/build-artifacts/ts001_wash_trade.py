"""
TS-001 - Wash Trade / Self-Match Detection  (DEMO, Run 2 - synthetic only, CLAUDE.md §5)

Obligation : MAR Art 12(1)(a) - transactions giving false/misleading signals as to supply,
             demand or price. Carried on the alert as a field (see WashTradeAlert).
Spec ref   : TS-001 (SME-validated + open-questions dispositioned, 2026-06-27).
Scope note : TS-001 covers CROSS-account self-match within a UBO group. Intra-account opposing
             trades are a sibling scenario, out of scope here (code-review W1 disposition).

Obligation mapping is PROVISIONAL: the SME flagged Q1 (jurisdiction) and Q3/Q4 (intra-group /
connected-party scope) as go-live blockers, so `obligation` here is a single illustrative EU-MAR
citation, not a finalised multi-jurisdiction mapping. The alert carries `obligation_status` to make
that explicit (house-rule 2026-06-27: an unresolved mapping must not masquerade as finalised).

Built against docs/house-rules.md: UBO keystone + freshness gate; off-market price as an
early-continue NECESSARY condition; obligation + keystone id as alert FIELDS; injected as_of_date.
"""
from __future__ import annotations

import dataclasses
import logging
from datetime import date
from typing import Sequence

logger = logging.getLogger("ts001")

OBLIGATION = "MAR Art 12(1)(a)"
OBLIGATION_STATUS = "PROVISIONAL - mapping pending SME open-questions Q1/Q3/Q4"


@dataclasses.dataclass(frozen=True)
class Trade:
    trade_id: str
    account_id: str
    instrument: str
    side: str          # "BUY" or "SELL"
    price: float
    quantity: float
    trade_date: date


@dataclasses.dataclass(frozen=True)
class UBOLink:
    account_id: str
    ubo_group_id: str


@dataclasses.dataclass(frozen=True)
class MarketSnapshot:
    instrument: str
    snapshot_date: date
    mid_price: float
    spread_bps: float


@dataclasses.dataclass(frozen=True)
class WashTradeAlert:
    """Every field is first-class so the alert record alone satisfies the alert->obligation
    trace (house-rule 2026-06-27). `reason` supplements but never replaces the typed fields."""
    alert_id: str
    obligation: str            # the regulatory citation, as a field
    obligation_status: str     # PROVISIONAL until the mapping is finalised (compliance fix)
    ubo_group_id: str          # keystone linkage id, as a field
    buy_trade_id: str
    sell_trade_id: str
    buy_account_id: str
    sell_account_id: str
    instrument: str
    snapshot_date: date        # WHICH mid the deviation was measured against (audit fix W3)
    buy_price: float
    sell_price: float
    price_deviation_bps: float
    threshold_bps: float
    reason: str


@dataclasses.dataclass
class DetectionParams:
    """All thresholds REQUIRED - no defaults (fail loud; no hidden magic numbers, §4)."""
    lookback_days: int
    off_market_threshold_bps: float   # spread-normalisation is the tuning target (tuning pack)
    ubo_graph_max_age_days: int
    exempt_account_ids: frozenset[str]


class UBOGraphStaleError(RuntimeError):
    """Raised when the UBO graph predates the staleness gate - abort the run (house-rule 2026-06-27)."""


def _validate_ubo_freshness(ubo_as_of: date, as_of_date: date, max_age_days: int) -> None:
    """Gate the run on UBO-graph freshness. Deterministic: injected as_of_date, never wall-clock."""
    age = (as_of_date - ubo_as_of).days
    if age > max_age_days:
        raise UBOGraphStaleError(
            f"UBO graph is {age} days old (max permitted: {max_age_days}). Refresh before running TS-001."
        )


def _deviation_bps(buy_price: float, sell_price: float, mid: float) -> float:
    """Single source of truth for the off-market deviation (code-review W2 fix)."""
    if mid <= 0:
        return 0.0
    wash_price = (buy_price + sell_price) / 2
    return abs(wash_price - mid) / mid * 10_000


def detect_wash_trades(
    trades: Sequence[Trade],
    ubo_links: Sequence[UBOLink],
    ubo_as_of: date,
    market_snapshots: Sequence[MarketSnapshot],
    params: DetectionParams,
    as_of_date: date,
) -> list[WashTradeAlert]:
    """Detect cross-account wash-trade pairs under TS-001 (MAR Art 12(1)(a)).

    Off-market price is a NECESSARY condition (early-continue), not a scored input. Raises
    UBOGraphStaleError if the UBO graph is too stale. Missing market snapshots are logged as a
    data-quality coverage gap, not silently dropped (QA DEF-001 fix).
    """
    _validate_ubo_freshness(ubo_as_of, as_of_date, params.ubo_graph_max_age_days)

    ubo_index = {l.account_id: l.ubo_group_id for l in ubo_links}
    market_index = {(s.instrument, s.snapshot_date): s for s in market_snapshots}

    eligible = [t for t in trades if t.account_id not in params.exempt_account_ids]
    buys = [t for t in eligible if t.side == "BUY"]
    sells = [t for t in eligible if t.side == "SELL"]

    alerts: list[WashTradeAlert] = []
    alert_counter = 0

    for buy in buys:
        buy_ubo = ubo_index.get(buy.account_id)
        if buy_ubo is None:
            continue
        for sell in sells:
            if sell.account_id == buy.account_id:
                continue  # cross-account only (W1 scope decision); intra-account is a sibling scenario
            if sell.instrument != buy.instrument:
                continue
            if ubo_index.get(sell.account_id) != buy_ubo:
                continue
            if abs((sell.trade_date - buy.trade_date).days) > params.lookback_days:
                continue

            # The buy-leg date governs the reference snapshot (QA DEF-002: deterministic, documented).
            snapshot = market_index.get((buy.instrument, buy.trade_date))
            if snapshot is None:
                snapshot = market_index.get((sell.instrument, sell.trade_date))
            if snapshot is None:
                # Data-quality coverage gap - surface it, don't drop silently (QA DEF-001).
                logger.warning(
                    "TS-001 no market snapshot for %s on %s/%s - pair (%s,%s) not evaluated",
                    buy.instrument, buy.trade_date, sell.trade_date, buy.trade_id, sell.trade_id,
                )
                continue

            dev_bps = _deviation_bps(buy.price, sell.price, snapshot.mid_price)
            if dev_bps < params.off_market_threshold_bps:
                continue  # necessary condition not met - terminate this pair (no compensation)

            alert_counter += 1
            alerts.append(
                WashTradeAlert(
                    alert_id=f"TS001-{as_of_date.isoformat()}-{alert_counter:04d}",
                    obligation=OBLIGATION,
                    obligation_status=OBLIGATION_STATUS,
                    ubo_group_id=buy_ubo,
                    buy_trade_id=buy.trade_id,
                    sell_trade_id=sell.trade_id,
                    buy_account_id=buy.account_id,
                    sell_account_id=sell.account_id,
                    instrument=buy.instrument,
                    snapshot_date=snapshot.snapshot_date,
                    buy_price=buy.price,
                    sell_price=sell.price,
                    price_deviation_bps=round(dev_bps, 2),
                    threshold_bps=params.off_market_threshold_bps,
                    reason=(
                        f"UBO '{buy_ubo}' opposing {buy.instrument} legs {dev_bps:.1f}bps off-market "
                        f"(threshold {params.off_market_threshold_bps}bps) vs mid on {snapshot.snapshot_date}. "
                        f"Obligation: {OBLIGATION} ({OBLIGATION_STATUS})."
                    ),
                )
            )

    return alerts
