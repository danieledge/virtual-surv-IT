"""
MAR spoofing / layering detection.

Regulatory basis: Market Abuse Regulation (EU) No 596/2014 - Article 12(1)(a) and
Annex I - placing orders with no intention to execute ("non-bona-fide" orders) to
create a false or misleading impression of supply or demand, while benefiting from a
genuine execution on the opposite side of the book. In the UK the equivalent
prohibition on market manipulation is FCA MAR (MAR 1 / Art.15).

Design principles (CLAUDE.md §4):
- Deterministic and explainable: every alert records the spoof order(s), the
  benefiting execution, the timings, and the threshold(s) the behaviour breached.
- No undocumented thresholds: all live in `SpoofingThresholds` with a rationale and
  tuning date; they are injectable so `data-analyst` can recalibrate without editing
  logic.
- Synthetic/governed data only (CLAUDE.md §5): this module never logs raw record
  contents beyond the identifiers needed for the audit trail.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY


class EventKind(str, Enum):
    NEW = "NEW"        # order placed on the book
    CANCEL = "CANCEL"  # order cancelled (remaining qty removed)
    FILL = "FILL"      # a (partial) execution against an order


@dataclass(frozen=True)
class OrderEvent:
    """A single order-lifecycle event. Synthetic/masked data only."""

    ts_ms: int            # event time, ms since session start
    trader: str
    instrument: str
    order_id: str
    side: Side
    price: float
    qty: float            # order qty for NEW; executed qty for FILL; ignored for CANCEL
    kind: EventKind


@dataclass
class Order:
    """Reconstructed lifecycle of a single order."""

    order_id: str
    trader: str
    instrument: str
    side: Side
    price: float
    qty: float
    placed_ms: int
    cancelled_ms: int | None = None
    filled_qty: float = 0.0
    last_fill_ms: int | None = None

    @property
    def lifetime_ms(self) -> int | None:
        if self.cancelled_ms is None:
            return None
        return self.cancelled_ms - self.placed_ms

    @property
    def fill_ratio(self) -> float:
        return self.filled_qty / self.qty if self.qty else 0.0


@dataclass(frozen=True)
class SpoofingThresholds:
    """
    Tunable detection thresholds.

    Defaults calibrated 2026-06-18 against the synthetic calibration set in
    scripts/gen_synthetic.py. Re-tune with `data-analyst`, record the change and the
    volume/coverage trade-off in docs/scenarios/spoofing.md, and route the diff through
    `rules-developer` + `compliance-reviewer` before deployment.
    """

    # An order >= this multiple of the trader's median order size in the instrument is
    # "outsized" - spoof orders are large to move the perceived book. (tuned 2026-06-18)
    large_qty_multiple: float = 5.0
    # Genuine resting liquidity persists; non-bona-fide orders are pulled quickly.
    # Placement->cancel within this window is a place-and-cancel indicator. (2026-06-18)
    max_spoof_lifetime_ms: int = 2000
    # Spoof orders are not intended to trade; flag only near-unfilled orders. (2026-06-18)
    max_fill_ratio: float = 0.10
    # The benefiting (genuine) execution on the opposite side must occur close in time
    # to the spoof order being live. (tuned 2026-06-18)
    opposite_exec_window_ms: int = 3000
    # Need a minimum number of the trader's orders to establish a median baseline;
    # avoids flagging on trivially small samples. (tuned 2026-06-18)
    min_orders_for_baseline: int = 4


@dataclass
class SpoofingAlert:
    """An explainable alert: what fired, why, and the obligation it serves."""

    trader: str
    instrument: str
    spoof_order_id: str
    spoof_side: Side
    spoof_qty: float
    spoof_lifetime_ms: int
    spoof_fill_ratio: float
    benefiting_fill_order_id: str
    benefiting_side: Side
    benefiting_qty: float
    time_gap_ms: int
    reason: str
    obligation: str = (
        "MAR (EU) 596/2014 Art.12(1)(a) / Annex I - non-bona-fide orders creating a "
        "false or misleading impression of supply/demand"
    )


def reconstruct_orders(events: list[OrderEvent]) -> dict[str, Order]:
    """Fold a stream of events into per-order lifecycles, time-ordered."""
    orders: dict[str, Order] = {}
    for e in sorted(events, key=lambda x: x.ts_ms):
        if e.kind is EventKind.NEW:
            orders[e.order_id] = Order(
                order_id=e.order_id,
                trader=e.trader,
                instrument=e.instrument,
                side=e.side,
                price=e.price,
                qty=e.qty,
                placed_ms=e.ts_ms,
            )
        elif e.kind is EventKind.CANCEL:
            o = orders.get(e.order_id)
            if o is not None:
                o.cancelled_ms = e.ts_ms
        elif e.kind is EventKind.FILL:
            o = orders.get(e.order_id)
            if o is not None:
                o.filled_qty += e.qty
                o.last_fill_ms = e.ts_ms
    return orders


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def detect_spoofing(
    events: list[OrderEvent],
    thresholds: SpoofingThresholds | None = None,
) -> list[SpoofingAlert]:
    """
    Flag potential spoofing: an outsized, short-lived, near-unfilled order that is
    cancelled, coinciding with a genuine execution on the opposite side of the book.

    Returns one alert per qualifying spoof order. Deterministic for given inputs.
    """
    th = thresholds or SpoofingThresholds()
    orders = reconstruct_orders(events)

    by_key: dict[tuple[str, str], list[Order]] = defaultdict(list)
    for o in orders.values():
        by_key[(o.trader, o.instrument)].append(o)

    alerts: list[SpoofingAlert] = []
    for (trader, instrument), olist in by_key.items():
        if len(olist) < th.min_orders_for_baseline:
            continue
        median_qty = _median([o.qty for o in olist])
        if median_qty <= 0:
            continue

        for spoof in olist:
            # Non-bona-fide signature: outsized, cancelled, short-lived, near-unfilled.
            if spoof.cancelled_ms is None or spoof.lifetime_ms is None:
                continue
            if spoof.qty < th.large_qty_multiple * median_qty:
                continue
            if spoof.lifetime_ms > th.max_spoof_lifetime_ms:
                continue
            if spoof.fill_ratio > th.max_fill_ratio:
                continue

            # Benefiting genuine execution on the opposite side, close in time to the
            # spoof order's live window.
            window_start = spoof.placed_ms - th.opposite_exec_window_ms
            window_end = spoof.cancelled_ms + th.opposite_exec_window_ms
            best: tuple[Order, int] | None = None
            for other in olist:
                if other.side is not spoof.side.opposite:
                    continue
                if other.filled_qty <= 0 or other.last_fill_ms is None:
                    continue
                if window_start <= other.last_fill_ms <= window_end:
                    gap = abs(other.last_fill_ms - spoof.placed_ms)
                    if best is None or gap < best[1]:
                        best = (other, gap)
            if best is None:
                continue

            benef, gap = best
            alerts.append(
                SpoofingAlert(
                    trader=trader,
                    instrument=instrument,
                    spoof_order_id=spoof.order_id,
                    spoof_side=spoof.side,
                    spoof_qty=spoof.qty,
                    spoof_lifetime_ms=spoof.lifetime_ms,
                    spoof_fill_ratio=round(spoof.fill_ratio, 4),
                    benefiting_fill_order_id=benef.order_id,
                    benefiting_side=benef.side,
                    benefiting_qty=benef.filled_qty,
                    time_gap_ms=gap,
                    reason=(
                        f"Outsized {spoof.side.value} order {spoof.order_id} "
                        f"({spoof.qty:g} ≈ {spoof.qty / median_qty:.1f}× median) placed and "
                        f"cancelled within {spoof.lifetime_ms}ms, {spoof.fill_ratio:.0%} filled, "
                        f"while {benef.side.value} order {benef.order_id} executed "
                        f"{benef.filled_qty:g} on the opposite side {gap}ms away."
                    ),
                )
            )
    return alerts
