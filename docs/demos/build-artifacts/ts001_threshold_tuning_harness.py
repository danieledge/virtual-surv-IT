"""
TS-001 threshold-tuning harness (DEMO - SYNTHETIC data only, CLAUDE.md §5).

Produces the MEASURED evidence behind the off-market spread-multiple calibration
(threshold-tuning-pack.md, TUNE-001). Deterministic: seeded RNG, no wall clock.

Method
    Generate a LABELLED population of candidate wash-trade pairs with known ground
    truth (WASH vs LEGIT), across three liquidity segments (tight / mid / wide
    spread). Each "case" is one UBO group with one buy + one sell on the same
    instrument and day, so each forms exactly ONE candidate pair in the detector.
    Notional is set above the materiality floor and no safe-harbour tags are used,
    so DR-002 (the off-market spread-normalised test) is the SOLE discriminator -
    isolating the parameter under calibration.

    The discriminating feature is the spread-normalised price deviation from mid
    (multiples of the time-weighted spread). We draw it from two distributions:
      - WASH  (true positives): genuinely off-market prints. Centred above a full
        spread from mid with a tail reaching down toward the touch.
      - LEGIT (negatives): at/near-market coincident fills (independent orders at a
        liquid price; ETF c/r; index rebal) - centred at mid with noise, occasionally
        drifting up toward the touch.
    The deliberate overlap in the 0.5x-1.0x band is exactly where the M2 decision
    (touch vs full-spread reference frame) bites.

    We then run the REAL detector at a range of thresholds and compute precision,
    recall and alert volume vs ground truth (ATL/BTL), overall and per segment.

Run
    python -m docs.demos.build-artifacts.ts001_threshold_tuning_harness   # (path has dashes; run by file)
    python docs/demos/build-artifacts/ts001_threshold_tuning_harness.py
"""

from __future__ import annotations

import importlib.util
import random
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

# --- import the detector (sibling file; dashed dir defeats normal import) ---
_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("ts001_wash_trade", _HERE / "ts001_wash_trade.py")
ts001 = importlib.util.module_from_spec(_spec)
sys.modules["ts001_wash_trade"] = ts001  # let dataclass resolve string annotations
_spec.loader.exec_module(ts001)  # type: ignore[union-attr]

Trade = ts001.Trade
UBOLink = ts001.UBOLink
MarketSnapshot = ts001.MarketSnapshot
DetectionParams = ts001.DetectionParams
detect_wash_trades = ts001.detect_wash_trades

SEED = 20260630
AS_OF = date(2026, 6, 30)
TRADE_DAY = date(2026, 6, 15)        # well within UBO freshness; single day so lookback is non-binding
GRAPH_DATE = date(2026, 6, 1)        # 29 days old < 90-day freshness limit

# Segments: (name, mid_price, time_weighted_spread_bps). Spread-normalisation should make the
# SAME normalised threshold behave consistently across all three - that is the thing we validate.
SEGMENTS = [
    ("LIQUID  (tight ~3bps)", 100.00, 3.0),
    ("MID     (~20bps)",      50.00, 20.0),
    ("ILLIQUID(~200bps)",     25.00, 200.0),
]

# Population per segment. Wash is RARE - low base rate, as in real surveillance.
N_WASH_PER_SEG = 100
N_LEGIT_PER_SEG = 700

THRESHOLDS = [0.5, 0.75, 1.0, 1.5, 2.0]   # multiples of the spread, measured from mid


def _draw_normalised_deviation(rng: random.Random, label: str) -> float:
    """Spread-normalised deviation from mid (in multiples of the spread) for a case."""
    if label == "WASH":
        # genuinely off-market: centre ~1.3 spreads, sd 0.55, with a thin tail toward the touch.
        d = rng.gauss(1.30, 0.55)
        return max(0.10, d)
    # LEGIT: at/near market. Half-normal-ish around mid; rarely drifts toward/just past the touch.
    d = abs(rng.gauss(0.0, 0.32))
    return min(d, 1.40)


def build_population():
    """Return (trades, ubo_links, snapshots, truth) where truth maps ubo_group_id -> 'WASH'|'LEGIT'."""
    rng = random.Random(SEED)
    trades: list = []
    ubo_links: list = []
    snapshots: list = []
    truth: dict[str, str] = {}
    case_meta: dict[str, tuple[str, float]] = {}  # ubo -> (segment_name, normalised_dev)

    case_no = 0
    for seg_idx, (seg_name, mid, spread_bps) in enumerate(SEGMENTS):
        instrument = f"SYNTH-EQ-{seg_idx:02d}"
        snapshots.append(MarketSnapshot(instrument, TRADE_DAY, mid, spread_bps))
        plan = [("WASH", N_WASH_PER_SEG), ("LEGIT", N_LEGIT_PER_SEG)]
        for label, n in plan:
            for _ in range(n):
                case_no += 1
                ubo = f"UBO-{seg_idx}-{case_no:05d}"
                acct_b = f"ACCT-{case_no:05d}-B"
                acct_s = f"ACCT-{case_no:05d}-S"
                d = _draw_normalised_deviation(rng, label)
                # price so that |avg - mid|/mid * 1e4 / spread_bps == d  (both legs at avg)
                dev_bps = d * spread_bps
                price = mid * (1.0 + dev_bps / 10_000.0)  # push up; sign is immaterial (abs deviation)
                qty = 1000.0  # notional ~ price*1000 >> 10k floor for all segments
                trades.append(Trade(f"T{case_no:05d}B", acct_b, instrument, ts001.BUY, price, qty, TRADE_DAY))
                trades.append(Trade(f"T{case_no:05d}S", acct_s, instrument, ts001.SELL, price, qty, TRADE_DAY))
                ubo_links.append(UBOLink(acct_b, ubo, GRAPH_DATE))
                ubo_links.append(UBOLink(acct_s, ubo, GRAPH_DATE))
                truth[ubo] = label
                case_meta[ubo] = (seg_name, d)
    return trades, ubo_links, snapshots, truth, case_meta


def evaluate(threshold: float, trades, ubo_links, snapshots, truth, case_meta):
    """Run the detector at `threshold` and return overall + per-segment confusion stats."""
    params = DetectionParams(off_market_spread_multiple=threshold)
    result = detect_wash_trades(trades, ubo_links, snapshots, AS_OF, params)
    alerted_ubos = {a.ubo_group_id for a in result.alerts}

    # confusion, overall and per segment
    overall = defaultdict(int)
    per_seg: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for ubo, label in truth.items():
        seg = case_meta[ubo][0]
        alerted = ubo in alerted_ubos
        if label == "WASH" and alerted:
            key = "TP"
        elif label == "WASH" and not alerted:
            key = "FN"
        elif label == "LEGIT" and alerted:
            key = "FP"
        else:
            key = "TN"
        overall[key] += 1
        per_seg[seg][key] += 1
    return overall, per_seg, len(result.alerts)


def _pr(c) -> tuple[float, float]:
    tp, fp, fn = c["TP"], c["FP"], c["FN"]
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    return precision, recall


def main() -> None:
    trades, ubo_links, snapshots, truth, case_meta = build_population()
    n_wash = sum(1 for v in truth.values() if v == "WASH")
    n_legit = sum(1 for v in truth.values() if v == "LEGIT")
    print(f"seed={SEED}  pairs={len(truth)}  WASH={n_wash}  LEGIT={n_legit}  "
          f"base_rate={n_wash/len(truth):.3%}  trades={len(trades)}")
    print(f"segments: {[s[0] for s in SEGMENTS]}  (each {N_WASH_PER_SEG} wash / {N_LEGIT_PER_SEG} legit)\n")

    print("=== ATL/BTL sweep (overall) ===")
    print(f"{'thr':>5} {'alerts':>7} {'TP':>5} {'FP':>5} {'FN':>5} {'TN':>6} "
          f"{'precision':>10} {'recall':>8} {'F1':>7}")
    for thr in THRESHOLDS:
        overall, per_seg, n_alerts = evaluate(thr, trades, ubo_links, snapshots, truth, case_meta)
        p, r = _pr(overall)
        f1 = (2 * p * r / (p + r)) if (p + r) else float("nan")
        print(f"{thr:>5.2f} {n_alerts:>7} {overall['TP']:>5} {overall['FP']:>5} "
              f"{overall['FN']:>5} {overall['TN']:>6} {p:>10.3f} {r:>8.3f} {f1:>7.3f}")

    print("\n=== per-segment precision/recall (validates spread-normalisation) ===")
    for thr in THRESHOLDS:
        overall, per_seg, n_alerts = evaluate(thr, trades, ubo_links, snapshots, truth, case_meta)
        print(f"\n threshold = {thr:.2f}x spread")
        for seg, _, _ in SEGMENTS:
            c = per_seg[seg]
            p, r = _pr(c)
            print(f"   {seg:<22} TP={c['TP']:>3} FP={c['FP']:>3} FN={c['FN']:>3} "
                  f"precision={p:.3f} recall={r:.3f}")

    # M2 focus: the touch (0.5) vs full-spread-from-mid (1.0) reference-frame choice
    print("\n=== M2 reference-frame decision: 0.5x (touch) vs 1.0x (full spread from mid) ===")
    for thr in (0.5, 1.0):
        overall, _, n_alerts = evaluate(thr, trades, ubo_links, snapshots, truth, case_meta)
        p, r = _pr(overall)
        print(f" {thr:.2f}x  alerts={n_alerts:>4}  TP={overall['TP']:>3} FP={overall['FP']:>3} "
              f"FN={overall['FN']:>3}  precision={p:.3f} recall={r:.3f}")


if __name__ == "__main__":
    main()
