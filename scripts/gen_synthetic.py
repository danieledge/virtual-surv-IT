"""
Synthetic order-flow generator for the MAR spoofing scenario.

CLAUDE.md §5: examples and tests use SYNTHETIC data only. Nothing here represents real
orders, traders, instruments or persons. Output is deterministic for a given seed so
tests and tuning runs are reproducible.

Use as a library (preferred for tests):
    from scripts.gen_synthetic import spoofing_session, benign_session
    events = spoofing_session(seed=1)

Or from the command line (writes JSONL under data/, which is git-ignored):
    python -m scripts.gen_synthetic --kind spoofing --out data/synthetic/spoofing.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

# Portability: make the repo root importable so this runs standalone by absolute path
# from any cwd (not only via `python -m scripts.gen_synthetic` from the repo root).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rules.spoofing import EventKind, OrderEvent, Side

# Synthetic, non-identifying labels.
TRADER = "TRADER_SYNTH_01"
INSTRUMENT = "SYNTH-EQ-0001"
BASE_PRICE = 100.0
TYPICAL_QTY = 100.0


def _new(ts, oid, side, qty, price=BASE_PRICE):
    return OrderEvent(ts, TRADER, INSTRUMENT, oid, side, price, qty, EventKind.NEW)


def _fill(ts, oid, side, qty, price=BASE_PRICE):
    return OrderEvent(ts, TRADER, INSTRUMENT, oid, side, price, qty, EventKind.FILL)


def _cancel(ts, oid, side, price=BASE_PRICE):
    return OrderEvent(ts, TRADER, INSTRUMENT, oid, side, price, 0.0, EventKind.CANCEL)


def benign_session(seed: int = 1) -> list[OrderEvent]:
    """Normal two-way trading: typical-sized orders that fill or rest and cancel slowly.

    True-negative control - must not produce a spoofing alert.
    """
    rng = random.Random(seed)
    events: list[OrderEvent] = []
    ts = 0
    for i in range(12):
        ts += rng.randint(500, 1500)
        side = Side.BUY if i % 2 == 0 else Side.SELL
        qty = TYPICAL_QTY + rng.randint(-20, 20)
        oid = f"B{i:02d}"
        events.append(_new(ts, oid, side, qty))
        if rng.random() < 0.7:
            # genuine fill shortly after
            events.append(_fill(ts + rng.randint(200, 800), oid, side, qty))
        else:
            # cancelled, but only after resting a long time (bona-fide working order)
            events.append(_cancel(ts + rng.randint(6000, 12000), oid, side))
    return events


def spoofing_session(seed: int = 1) -> list[OrderEvent]:
    """A clear spoof: an outsized BUY placed to inflate apparent demand, a genuine SELL
    executed into it, then the BUY cancelled within ~1.5s having barely filled.

    True-positive control - must produce a spoofing alert.
    """
    rng = random.Random(seed)
    events: list[OrderEvent] = []
    # Baseline of typical genuine orders to establish the median.
    ts = 0
    for i in range(4):
        ts += rng.randint(400, 900)
        side = Side.BUY if i % 2 == 0 else Side.SELL
        oid = f"G{i:02d}"
        events.append(_new(ts, oid, side, TYPICAL_QTY))
        events.append(_fill(ts + rng.randint(200, 500), oid, side, TYPICAL_QTY))

    # The manipulation: outsized BUY (8x typical) faking demand.
    spoof_place = ts + 1000
    events.append(_new(spoof_place, "SPOOF1", Side.BUY, TYPICAL_QTY * 8))
    # Genuine SELL executes on the opposite side while the spoof is live.
    events.append(_fill(spoof_place + 500, "SELL1_pre", Side.SELL, TYPICAL_QTY))
    events.insert(0, _new(spoof_place - 100, "SELL1_pre", Side.SELL, TYPICAL_QTY))
    # Spoof BUY pulled ~1.5s after placement, essentially unfilled.
    events.append(_cancel(spoof_place + 1500, "SPOOF1", Side.BUY))
    return events


def large_genuine_session(seed: int = 1) -> list[OrderEvent]:
    """Outsized orders that are genuine: one fills in full, one rests then cancels with
    no opposite-side benefit.

    False-positive control - must NOT produce a spoofing alert despite large size.
    """
    rng = random.Random(seed)
    events: list[OrderEvent] = []
    ts = 0
    for i in range(4):
        ts += rng.randint(400, 900)
        side = Side.BUY if i % 2 == 0 else Side.SELL
        oid = f"G{i:02d}"
        events.append(_new(ts, oid, side, TYPICAL_QTY))
        events.append(_fill(ts + rng.randint(200, 500), oid, side, TYPICAL_QTY))

    # Outsized order that genuinely executes in full (fill_ratio = 1.0).
    ts += 1000
    events.append(_new(ts, "BIG_FILLED", Side.BUY, TYPICAL_QTY * 8))
    events.append(_fill(ts + 600, "BIG_FILLED", Side.BUY, TYPICAL_QTY * 8))

    # Outsized order that rests a long time then cancels, with no opposite-side trade.
    ts += 2000
    events.append(_new(ts, "BIG_RESTING", Side.SELL, TYPICAL_QTY * 8))
    events.append(_cancel(ts + 9000, "BIG_RESTING", Side.SELL))
    return events


_KINDS = {
    "benign": benign_session,
    "spoofing": spoofing_session,
    "large_genuine": large_genuine_session,
}


def event_to_record(e: OrderEvent) -> dict:
    """Serialise an event to a plain dict (the on-the-wire / file schema)."""
    return {
        "ts_ms": e.ts_ms,
        "trader": e.trader,
        "instrument": e.instrument,
        "order_id": e.order_id,
        "side": e.side.value,
        "price": e.price,
        "qty": e.qty,
        "kind": e.kind.value,
    }


def record_to_event(d: dict) -> OrderEvent:
    """Parse a record dict back into an OrderEvent (side/kind kept as strings by masking)."""
    return OrderEvent(
        ts_ms=int(d["ts_ms"]),
        trader=d["trader"],
        instrument=d["instrument"],
        order_id=d["order_id"],
        side=Side(d["side"]),
        price=float(d["price"]),
        qty=float(d["qty"]),
        kind=EventKind(d["kind"]),
    )


def _to_jsonl(events: list[OrderEvent]) -> str:
    rows = [event_to_record(e) for e in sorted(events, key=lambda x: x.ts_ms)]
    return "\n".join(json.dumps(r) for r in rows) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate synthetic order flow.")
    ap.add_argument("--kind", choices=sorted(_KINDS), default="spoofing")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", type=Path, default=Path("data/synthetic/orders.jsonl"))
    args = ap.parse_args()

    events = _KINDS[args.kind](seed=args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(_to_jsonl(events))
    print(f"Wrote {len(events)} synthetic events ({args.kind}) -> {args.out}")


if __name__ == "__main__":
    main()
