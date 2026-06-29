"""
scripts/calibrate_spoofing.py - measured FP/FN evidence for the spoofing rule on synthetic data.

The compliance review of the 2026-06-29 genuine-baseline change asked for a *measured* FP/FN delta
rather than only a logical argument. This builds a LABELLED synthetic corpus (each session is known
to be a spoof or not), runs `detect_spoofing`, and reports precision / recall / false-positive rate
per segment plus a confusion matrix.

Honest scope (the same caveat the scenario doc carries): this validates the *method* on a synthetic
distribution - it does NOT calibrate the real-world thresholds. Real calibration needs masked
production data and `data-analyst` / `tuning-analyst` (CLAUDE.md). All data here is synthetic (§5).

Reproduce:
    python -m scripts.calibrate_spoofing
"""

from __future__ import annotations

from dataclasses import dataclass

from rules.spoofing import detect_spoofing
from scripts.gen_synthetic import benign_session, large_genuine_session, spoofing_session

# Labelled segments: (name, generator, should_alert, n_sessions). Distinct seed ranges keep the
# sessions varied while staying deterministic/reproducible.
_SEGMENTS = [
    ("spoof (true positive)", spoofing_session, True, 50),
    ("benign two-way (true negative)", benign_session, False, 50),
    ("outsized-but-genuine (FP control)", large_genuine_session, False, 50),
]


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0


def _evaluate() -> tuple[dict[str, Counts], Counts]:
    per_segment: dict[str, Counts] = {}
    total = Counts()
    for name, gen, should_alert, n in _SEGMENTS:
        c = Counts()
        for seed in range(1, n + 1):
            fired = bool(detect_spoofing(gen(seed=seed)))
            if should_alert and fired:
                c.tp += 1
            elif should_alert and not fired:
                c.fn += 1
            elif not should_alert and fired:
                c.fp += 1
            else:
                c.tn += 1
        per_segment[name] = c
        total.tp += c.tp
        total.fp += c.fp
        total.tn += c.tn
        total.fn += c.fn
    return per_segment, total


def _metrics(c: Counts) -> tuple[float, float, float]:
    precision = c.tp / (c.tp + c.fp) if (c.tp + c.fp) else 1.0
    recall = c.tp / (c.tp + c.fn) if (c.tp + c.fn) else 1.0
    fp_rate = c.fp / (c.fp + c.tn) if (c.fp + c.tn) else 0.0
    return precision, recall, fp_rate


def main() -> int:
    per_segment, total = _evaluate()
    print("Spoofing rule - measured performance on a labelled SYNTHETIC corpus (method validation,")
    print(
        "not real-world calibration). Deterministic; reproduce with `python -m scripts.calibrate_spoofing`.\n"
    )
    print(f"{'Segment':36s} {'TP':>4} {'FN':>4} {'FP':>4} {'TN':>4}")
    for name, c in per_segment.items():
        print(f"{name:36s} {c.tp:>4} {c.fn:>4} {c.fp:>4} {c.tn:>4}")
    p, r, fpr = _metrics(total)
    print(
        f"\nOverall: precision={p:.2f}  recall={r:.2f}  false-positive-rate={fpr:.2f}  "
        f"(TP={total.tp} FN={total.fn} FP={total.fp} TN={total.tn})"
    )
    # On the shipped synthetic fixtures the rule is expected to be perfect: every spoof fires,
    # no control does. A non-perfect result here is a regression worth investigating.
    ok = total.fn == 0 and total.fp == 0
    print("RESULT:", "PASS (recall=1.0, FP=0 on the synthetic set)" if ok else "REGRESSION")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
