"""
scripts/synthesise.py - learn the *shape* of (masked) order flow and emit fully synthetic
sessions that match it, while sharing no real rows, entities or timestamps.

Why this exists: masked data is still personal data (pseudonymised != anonymous), and the
preserved behaviour can itself be mildly re-identifying. For anything that leaves the
governed environment - or goes in front of an LLM agent - synthetic data is the safer
choice: it reproduces the statistical and structural properties detection depends on
without containing any real record.

This is a deliberately lightweight, dependency-free statistical synthesiser: it fits the
marginal distributions (order sizes, timing gaps) and reproduces the spoofing motif at its
observed rate. A production system might use a learned generative model (e.g. CTGAN or a
sequence model); the `fit -> sample` interface here is the same idea, just simpler.

Operates on synthetic/masked data only (CLAUDE.md §5).
"""

from __future__ import annotations

import random
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

# Portability: make the repo root importable so this runs standalone by absolute path
# from any cwd (not only via `python -m scripts.synthesise` from the repo root).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rules.spoofing import EventKind, OrderEvent, Side, detect_spoofing, reconstruct_orders


@dataclass
class FlowProfile:
    """The learned 'shape' of a corpus of order flow. Contains no real records."""

    qty_values: list[float]  # observed genuine order sizes (sampled from)
    gap_values: list[int]  # observed inter-event gaps in ms (sampled from)
    spoof_rate: float  # fraction of sessions that exhibited a spoof
    spoof_multiple: float  # spoof order size / median genuine size
    spoof_lifetime_ms: int  # typical place -> cancel lifetime
    opp_gap_ms: int  # typical gap to the benefiting opposite-side fill


def fit(sessions: list[list[OrderEvent]]) -> FlowProfile:
    """Learn a FlowProfile from a corpus of sessions (each a list of order events)."""
    qty_values: list[float] = []
    gap_values: list[int] = []
    spoof_sessions = 0
    multiples: list[float] = []
    lifetimes: list[int] = []
    gaps: list[int] = []

    for session in sessions:
        orders = reconstruct_orders(session)
        alerts = detect_spoofing(session)
        spoof_ids = {a.spoof_order_id for a in alerts}

        genuine = [o.qty for o in orders.values() if o.order_id not in spoof_ids]
        median_genuine = statistics.median(genuine) if genuine else 0.0
        qty_values.extend(genuine)

        ts_sorted = sorted(e.ts_ms for e in session)
        gap_values.extend(max(1, b - a) for a, b in zip(ts_sorted, ts_sorted[1:]))

        if alerts:
            spoof_sessions += 1
            a = alerts[0]
            if median_genuine:
                multiples.append(a.spoof_qty / median_genuine)
            lifetimes.append(a.spoof_lifetime_ms)
            gaps.append(a.time_gap_ms)

    n = len(sessions) or 1
    return FlowProfile(
        qty_values=qty_values or [100.0],
        gap_values=gap_values or [600],
        spoof_rate=spoof_sessions / n,
        spoof_multiple=statistics.mean(multiples) if multiples else 8.0,
        spoof_lifetime_ms=int(statistics.mean(lifetimes)) if lifetimes else 1500,
        opp_gap_ms=int(statistics.mean(gaps)) if gaps else 500,
    )


def sample(profile: FlowProfile, n_sessions: int = 10, seed: int = 0) -> list[list[OrderEvent]]:
    """Generate `n_sessions` fully synthetic sessions matching the profile.

    Every session uses fresh, made-up identifiers and a fresh timeline - nothing here
    maps back to any input record.
    """
    rng = random.Random(seed)  # nosec B311 - synthetic data generation, not security-sensitive
    median_genuine = statistics.median(profile.qty_values)
    sessions: list[list[OrderEvent]] = []

    for i in range(n_sessions):
        trader = f"SYNTH_T{i:03d}"
        instrument = f"SYNTH_INSTR_{i % 3}"
        events: list[OrderEvent] = []
        ts = rng.randint(0, 1000)

        for j in range(6):  # genuine two-way flow, enough to form a baseline
            ts += rng.choice(profile.gap_values)
            side = Side.BUY if j % 2 == 0 else Side.SELL
            qty = rng.choice(profile.qty_values)
            oid = f"{trader}_O{j:02d}"
            events.append(OrderEvent(ts, trader, instrument, oid, side, 100.0, qty, EventKind.NEW))
            events.append(
                OrderEvent(
                    ts + rng.randint(150, 500),
                    trader,
                    instrument,
                    oid,
                    side,
                    100.0,
                    qty,
                    EventKind.FILL,
                )
            )

        if rng.random() < profile.spoof_rate:  # reproduce the spoof motif at the learned rate
            ts += 1000
            spoof_qty = median_genuine * profile.spoof_multiple
            soid, boid = f"{trader}_SPOOF", f"{trader}_BEN"
            # benefiting genuine SELL on the opposite side
            events.append(
                OrderEvent(
                    ts, trader, instrument, boid, Side.SELL, 100.0, median_genuine, EventKind.NEW
                )
            )
            events.append(
                OrderEvent(
                    ts + profile.opp_gap_ms,
                    trader,
                    instrument,
                    boid,
                    Side.SELL,
                    100.0,
                    median_genuine,
                    EventKind.FILL,
                )
            )
            # outsized non-bona-fide BUY, placed then cancelled unfilled
            events.append(
                OrderEvent(
                    ts - 50, trader, instrument, soid, Side.BUY, 100.0, spoof_qty, EventKind.NEW
                )
            )
            events.append(
                OrderEvent(
                    ts - 50 + profile.spoof_lifetime_ms,
                    trader,
                    instrument,
                    soid,
                    Side.BUY,
                    100.0,
                    spoof_qty,
                    EventKind.CANCEL,
                )
            )

        sessions.append(events)
    return sessions


def detection_rate(sessions: list[list[OrderEvent]]) -> float:
    """Fraction of sessions in which the spoofing rule raises at least one alert."""
    if not sessions:
        return 0.0
    return sum(1 for s in sessions if detect_spoofing(s)) / len(sessions)


def main() -> None:
    # Demo over synthetic data: build a corpus, learn its shape, sample fresh data, and
    # confirm the synthetic data carries the same detectable behaviour.
    from scripts.gen_synthetic import benign_session, spoofing_session

    corpus = [spoofing_session(seed=s) if s % 2 == 0 else benign_session(seed=s) for s in range(6)]
    profile = fit(corpus)
    synthetic = sample(profile, n_sessions=50, seed=1)

    print(f"Learned spoof rate (from corpus): {profile.spoof_rate:.2f}")
    print(f"Spoof rate in 50 synthetic sessions: {detection_rate(synthetic):.2f}")
    print(f"Median genuine size learned: {statistics.median(profile.qty_values):.0f}")
    print("Synthetic data shares no real entities, timestamps or rows with the corpus.")


if __name__ == "__main__":
    main()
