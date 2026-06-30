"""
TS-001 - Wash Trade / Self-Match detection (DEMO build - synthetic data only, CLAUDE.md §5).

Purpose
    Detect wash trading / self-matching: opposing buy and sell legs in the same instrument,
    submitted by accounts that share a common ultimate beneficial owner (UBO), executed
    off-market so as to give a false or misleading price signal while no genuine change in
    beneficial ownership occurs.

Regulatory obligation (carried on every alert as typed FIELDS, not free text)
    EU MAR (Reg. (EU) No 596/2014) Art.12(1)(a) - transactions/orders giving, or likely to
    give, false or misleading signals as to supply, demand or price. The no-change-in-
    beneficial-ownership indicator (MAR Art.12(2)(c)) is conceptually the typology core but is
    TO-VERIFY against the primary source and absent from the register, so the mapping is NOT
    finalised. Every alert therefore carries `obligation_status = "PROVISIONAL"`; this flag must
    not be removed without sign-off on SME open questions Q1/Q3/Q4 and register verification.

Design (per the SME validation, SMV-001, and the validated spec SCN-001 v0.1)
    - Phase-1 connected-party scope is UBO-only (SME Q4). Accounts are grouped by `ubo_group_id`;
      cross-account and single-account ("both sides") wash are both in scope (SCN-001 §3). Wider
      acting-in-concert grouping is Phase 2 / TS-002 and out of scope here.
    - Off-market price is a NECESSARY condition implemented as an early-continue (DR-002), never a
      weighted score. The test is SPREAD-NORMALISED: the average leg price must deviate from the
      prevailing mid by more than a configured multiple of the prevailing spread. Per the SME the
      spread denominator is the TIME-WEIGHTED average spread over the execution window (an upstream
      contract; carried on `MarketSnapshot.time_weighted_spread_bps`).
    - Safe-harbour suppression (DR-003): designated market-maker accounts (static register) and
      riskless-principal / agency / MM-tagged orders (per-order `strategy_tag`) are suppressed with
      a logged reason rather than silently dropped.
    - Materiality floor (DR-004): the matched notional must meet a minimum.
    - UBO-graph freshness (DR-005): a stale graph for an account EXCLUDES that account's pairs and
      raises a data-quality warning (a coverage/false-negative control, per SME) - it does NOT
      abort the whole run.
    - Implied-match lower-confidence tier (DR-006) is OFF at launch (SME Q5).

Inputs/outputs
    detect_wash_trades(...) -> DetectionResult with .alerts, .data_quality_warnings and
    .suppressions. Deterministic for given inputs (no wall-clock; `as_of_date` is injected).

Assumptions
    - Confirmed fills only (implied-match tier disabled). Date-granular timing for this demo.
    - The UBO graph, safe-harbour register and market-data snapshots are governed upstream feeds.
    - This module is self-contained by design (it is a demo artefact) and imports no repo `rules/`.
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import date
from typing import Sequence

logger = logging.getLogger("ts001")

# --- Obligation mapping (FIELDS on the alert; mapping is PROVISIONAL - see module docstring) ---
OBLIGATION_REFERENCE = "EU MAR Art.12(1)(a)"
OBLIGATION_STATUS = "PROVISIONAL"  # locked until SME Q1/Q3/Q4 resolved + register verified (SMV-001 §5)

# --- Named detection thresholds (CLAUDE.md §4: every threshold has a rationale + tuning date) ---
# Each default is a placeholder pending tuning-analyst (Theo) calibration. `tuning_date` is the
# date a value was last calibrated against evidence; "TBD" means it has never been tuned and the
# default is a reasoned starting point only, not a calibrated production value.

# Opposing legs must execute within this many days of each other to be a candidate pair.
# Date-granular for the demo; a real deployment uses sub-second/intraday windows per asset class.
# Rationale: wash legs are near-contemporaneous; a tight window limits coincidental pairing.
DEFAULT_LOOKBACK_DAYS = 1  # tuning_date: TBD

# Off-market necessary condition, SPREAD-NORMALISED. The average leg price must deviate from the
# prevailing mid by MORE than this multiple of the prevailing (time-weighted) spread. A multiple of
# 1.0 means "beyond a full spread from mid". Spread-normalised (not absolute bps) so the same
# threshold is meaningful in both tight and wide-spread instruments (SME §1.2).
# DEFERRED (M2, tuning-analyst call): the reference frame here is MID, so 1.0 = a full spread from
# mid, i.e. ~2x the touch (the half-spread to best bid/offer). Theo to calibrate this knowingly.
DEFAULT_OFF_MARKET_SPREAD_MULTIPLE = 1.0  # tuning_date: TBD

# Materiality floor on the MATCHED notional of a pair (smaller of the two legs), in instrument
# currency. Below this, a pair is immaterial and not worth an alert. Risk-appetite / tuning call.
DEFAULT_MIN_PAIR_NOTIONAL = 10_000.0  # tuning_date: TBD

# UBO-graph freshness limit. A graph older than this for an account cannot be relied upon to
# establish connection, so that account's pairs are excluded and a DQ warning is raised (DR-005).
# Stale data drives false NEGATIVES (missed links), so this is a coverage control (SME §1.1).
DEFAULT_UBO_GRAPH_MAX_AGE_DAYS = 90  # tuning_date: TBD

# Implied-match lower-confidence tier (DR-006). OFF at launch per SME Q5 - evidentially weak
# without a confirmed fill; Phase-2 enablement only, with its own queue/SLA and tighter window.
ENABLE_IMPLIED_MATCH_TIER = False  # tuning_date: TBD (Phase 2)

_BPS = 10_000.0
BUY = "BUY"
SELL = "SELL"


@dataclasses.dataclass(frozen=True)
class Trade:
    """A confirmed fill. Synthetic/masked data only (CLAUDE.md §5).

    `side` is "BUY"/"SELL"; `strategy_tag` carries per-order capacity (e.g. a riskless-principal
    or MM tag) used by the DR-003 safe-harbour test; None means no special capacity.
    """

    trade_id: str
    account_id: str
    instrument: str
    side: str
    price: float
    quantity: float
    trade_date: date
    strategy_tag: str | None = None


@dataclasses.dataclass(frozen=True)
class UBOLink:
    """Ownership-graph edge: an account's UBO group and the graph's as-of date for freshness."""

    account_id: str
    ubo_group_id: str
    graph_as_of_date: date


@dataclasses.dataclass(frozen=True)
class MarketSnapshot:
    """Prevailing market reference for an instrument on a date.

    `time_weighted_spread_bps` is the TIME-WEIGHTED average spread over the execution window
    (SME §1.2) - an upstream contract, not the instantaneous spread at fill time.
    """

    instrument: str
    snapshot_date: date
    mid_price: float
    time_weighted_spread_bps: float


@dataclasses.dataclass(frozen=True)
class DetectionParams:
    """Injectable thresholds (default to the named module constants so tuning needs no code edit).

    `exempt_account_ids` is the static market-maker / designated-status register (DR-003);
    `exempt_strategy_tags` are per-order capacities that attract safe-harbour suppression.
    """

    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    off_market_spread_multiple: float = DEFAULT_OFF_MARKET_SPREAD_MULTIPLE
    min_pair_notional: float = DEFAULT_MIN_PAIR_NOTIONAL
    ubo_graph_max_age_days: int = DEFAULT_UBO_GRAPH_MAX_AGE_DAYS
    exempt_account_ids: frozenset[str] = frozenset()
    exempt_strategy_tags: frozenset[str] = frozenset({"MARKET_MAKER", "RISKLESS_PRINCIPAL", "AGENCY"})
    enable_implied_match_tier: bool = ENABLE_IMPLIED_MATCH_TIER


@dataclasses.dataclass(frozen=True)
class WashTradeAlert:
    """An explainable wash-trade alert.

    Every keystone element is a typed FIELD so the record alone carries the alert->logic->
    obligation trace: the UBO group id (keystone linkage), the obligation reference and its
    PROVISIONAL status, both trade ids, and the spread-normalised deviation that fired it.
    `reason` supplements but never replaces the typed fields.
    """

    alert_id: str
    obligation_reference: str
    obligation_status: str
    ubo_group_id: str
    instrument: str
    buy_trade_id: str
    sell_trade_id: str
    buy_account_id: str
    sell_account_id: str
    snapshot_date: date
    avg_leg_price: float
    mid_price: float
    price_deviation_bps: float
    time_weighted_spread_bps: float
    spread_normalised_deviation: float  # price_deviation_bps / spread (multiples of the spread)
    off_market_spread_multiple: float  # the threshold breached
    matched_notional: float
    reason: str


@dataclasses.dataclass
class DetectionResult:
    """Detector output: alerts plus the audit trail of what was suppressed or could not be assessed."""

    alerts: list[WashTradeAlert] = dataclasses.field(default_factory=list)
    data_quality_warnings: list[str] = dataclasses.field(default_factory=list)
    suppressions: list[str] = dataclasses.field(default_factory=list)


def _price_deviation_bps(avg_price: float, mid: float) -> float:
    """Absolute deviation of the average leg price from mid, in bps of price. mid<=0 -> 0.0."""
    if mid <= 0:
        return 0.0
    return abs(avg_price - mid) / mid * _BPS


def detect_wash_trades(
    trades: Sequence[Trade],
    ubo_links: Sequence[UBOLink],
    market_snapshots: Sequence[MarketSnapshot],
    as_of_date: date,
    params: DetectionParams | None = None,
) -> DetectionResult:
    """Detect TS-001 wash-trade / self-match pairs (EU MAR Art.12(1)(a), PROVISIONAL mapping).

    Pairs opposing buy/sell legs in the same instrument within the same UBO group and lookback
    window (DR-001), applies the spread-normalised off-market necessary condition as an
    early-continue (DR-002), suppresses safe-harboured pairs (DR-003) and immaterial pairs (DR-004),
    and excludes accounts whose UBO graph is stale (DR-005, raising a data-quality warning).

    Returns a DetectionResult. Deterministic: candidates are evaluated in a stable trade order and
    `as_of_date` is injected, never read from the wall clock. Raises NotImplementedError if the
    implied-match tier is requested (DR-006 is OFF at launch per SME Q5).
    """
    p = params or DetectionParams()
    if p.enable_implied_match_tier:
        raise NotImplementedError(
            "DR-006 implied-match tier is OFF at launch (SME Q5). Phase-2 enablement requires a "
            "separate queue/SLA and a tuning-analyst-set tighter lookback per asset class."
        )

    result = DetectionResult()

    # DR-005: build the UBO index from FRESH graph edges only; exclude stale accounts and warn.
    # A feed may deliver several edges for one account (e.g. a fresh and a stale row, in any
    # order). Resolve to the FRESHEST edge per account FIRST so freshness is order-independent,
    # then an account is excluded (with a DQ warning) only if it has NO edge within the limit -
    # a single stale row must not shadow a fresh one and trigger a spurious staleness warning.
    freshest_link: dict[str, UBOLink] = {}
    for link in ubo_links:
        held = freshest_link.get(link.account_id)
        if held is None or link.graph_as_of_date > held.graph_as_of_date:
            freshest_link[link.account_id] = link

    ubo_index: dict[str, str] = {}
    for account_id, link in freshest_link.items():
        age_days = (as_of_date - link.graph_as_of_date).days
        if age_days > p.ubo_graph_max_age_days:
            result.data_quality_warnings.append(
                f"UBO graph for account {account_id} is {age_days} days old "
                f"(limit {p.ubo_graph_max_age_days}); account excluded from TS-001 pairing (DR-005)."
            )
            continue
        ubo_index[account_id] = link.ubo_group_id

    market_index = {(s.instrument, s.snapshot_date): s for s in market_snapshots}

    # Stable ordering so pairing and alert ids are deterministic regardless of input order.
    ordered = sorted(trades, key=lambda t: (t.trade_date, t.trade_id))
    buys = [t for t in ordered if t.side == BUY and t.account_id in ubo_index]
    sells = [t for t in ordered if t.side == SELL and t.account_id in ubo_index]

    alert_counter = 0
    for buy in buys:
        buy_group = ubo_index[buy.account_id]
        for sell in sells:
            # DR-001: same instrument, same UBO group, within lookback. Same-account ("both sides")
            # is in scope (SCN-001 §3) and pairs naturally because an account shares its own group.
            if sell.instrument != buy.instrument:
                continue
            if ubo_index[sell.account_id] != buy_group:
                continue
            if abs((sell.trade_date - buy.trade_date).days) > p.lookback_days:
                continue

            # Reference snapshot: the buy leg's date governs (documented, deterministic); fall back
            # to the sell-leg date so a one-sided snapshot gap still allows assessment.
            snapshot = market_index.get((buy.instrument, buy.trade_date)) or market_index.get(
                (sell.instrument, sell.trade_date)
            )
            if snapshot is None:
                result.data_quality_warnings.append(
                    f"No market snapshot for {buy.instrument} on {buy.trade_date}/{sell.trade_date}; "
                    f"pair ({buy.trade_id},{sell.trade_id}) not evaluated."
                )
                continue
            if snapshot.mid_price <= 0:
                # Mirror the non-positive-spread guard below: a non-positive mid makes the
                # off-market deviation meaningless (and _price_deviation_bps would return 0,
                # silently discarding the pair). Surface it as a DQ warning, never a silent drop.
                result.data_quality_warnings.append(
                    f"Non-positive mid price for {snapshot.instrument} on {snapshot.snapshot_date}; "
                    f"cannot assess off-market deviation for pair ({buy.trade_id},{sell.trade_id})."
                )
                continue
            if snapshot.time_weighted_spread_bps <= 0:
                result.data_quality_warnings.append(
                    f"Non-positive spread for {snapshot.instrument} on {snapshot.snapshot_date}; "
                    f"cannot spread-normalise pair ({buy.trade_id},{sell.trade_id})."
                )
                continue

            # DR-002: off-market necessary condition, SPREAD-NORMALISED, as an early-continue.
            avg_price = (buy.price + sell.price) / 2.0
            deviation_bps = _price_deviation_bps(avg_price, snapshot.mid_price)
            normalised = deviation_bps / snapshot.time_weighted_spread_bps
            if normalised <= p.off_market_spread_multiple:
                continue  # at/near market - no false price signal; discard with no score compensation

            # DR-003: safe-harbour suppression (logged, not silently dropped).
            exempt_reason = _safe_harbour_reason(buy, sell, p)
            if exempt_reason is not None:
                result.suppressions.append(
                    f"Pair ({buy.trade_id},{sell.trade_id}) suppressed - safe-harbour: {exempt_reason} (DR-003)."
                )
                continue

            # DR-004: materiality floor on the matched (smaller-leg) notional.
            matched_notional = min(buy.price * buy.quantity, sell.price * sell.quantity)
            if matched_notional < p.min_pair_notional:
                continue

            alert_counter += 1
            result.alerts.append(
                WashTradeAlert(
                    alert_id=f"TS001-{as_of_date.isoformat()}-{alert_counter:04d}",
                    obligation_reference=OBLIGATION_REFERENCE,
                    obligation_status=OBLIGATION_STATUS,
                    ubo_group_id=buy_group,
                    instrument=buy.instrument,
                    buy_trade_id=buy.trade_id,
                    sell_trade_id=sell.trade_id,
                    buy_account_id=buy.account_id,
                    sell_account_id=sell.account_id,
                    snapshot_date=snapshot.snapshot_date,
                    avg_leg_price=round(avg_price, 6),
                    mid_price=snapshot.mid_price,
                    price_deviation_bps=round(deviation_bps, 2),
                    time_weighted_spread_bps=snapshot.time_weighted_spread_bps,
                    spread_normalised_deviation=round(normalised, 2),
                    off_market_spread_multiple=p.off_market_spread_multiple,
                    matched_notional=round(matched_notional, 2),
                    reason=(
                        f"UBO '{buy_group}' opposing {buy.instrument} legs at avg {avg_price:g} are "
                        f"{deviation_bps:.1f}bps off mid {snapshot.mid_price:g} "
                        f"= {normalised:.1f}x the time-weighted spread "
                        f"({snapshot.time_weighted_spread_bps:g}bps), exceeding the "
                        f"{p.off_market_spread_multiple:g}x threshold; matched notional "
                        f"{matched_notional:g}. Obligation {OBLIGATION_REFERENCE} ({OBLIGATION_STATUS})."
                    ),
                )
            )

    return result


def _safe_harbour_reason(buy: Trade, sell: Trade, p: DetectionParams) -> str | None:
    """Return a DR-003 suppression reason if either leg is safe-harboured, else None.

    Designated status is checked against the static MM register (`exempt_account_ids`); per-order
    capacity (riskless principal / agency / MM) is checked via `strategy_tag` (SME Q2).
    """
    for leg in (buy, sell):
        if leg.account_id in p.exempt_account_ids:
            return f"account {leg.account_id} on the designated-MM register"
        if leg.strategy_tag in p.exempt_strategy_tags:
            return f"order {leg.trade_id} tagged {leg.strategy_tag}"
    return None
