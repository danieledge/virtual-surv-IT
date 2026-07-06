# Spoofing rule - calibration evidence (method validation)

> Measured FP/FN evidence for the 2026-06-29 genuine-baseline change to `rules/spoofing.py`,
> produced in response to the compliance review (which asked for a *measured* delta, not only a
> logical argument). Companion to `docs/scenarios/spoofing.md`. Authored in `.md`.

> **Document control** · Owner `data-analyst` / `tuning-analyst` · As-of `2026-06-29`
> · Classification `Internal` · Status `Method-validated (synthetic); real-world calibration outstanding`

## Scope

This validates the **method** on a synthetic distribution. It does **not** calibrate the
real-world thresholds. Real calibration needs masked production data and `data-analyst` /
`tuning-analyst`; the thresholds in `SpoofingThresholds` are unchanged by the 2026-06-29 change.
All data here is synthetic (CLAUDE.md §5).

## Method

A labelled corpus of 150 synthetic sessions (deterministic seeds) from `scripts/gen_synthetic.py`:

| Segment | Generator | Label | Sessions |
|---|---|---|---|
| Spoof (true positive) | `spoofing_session` | should alert | 50 |
| Benign two-way (true negative) | `benign_session` | should not alert | 50 |
| Outsized-but-genuine (FP control) | `large_genuine_session` | should not alert | 50 |

A session is predicted positive if `detect_spoofing` raises at least one alert.

**Reproduce:** `python -m scripts.calibrate_spoofing` (and `pytest -k calibration` pins it as a
regression test).

## Results (2026-06-29)

| Segment | TP | FN | FP | TN |
|---|---|---|---|---|
| Spoof (true positive) | 50 | 0 | 0 | 0 |
| Benign two-way | 0 | 0 | 0 | 50 |
| Outsized-but-genuine | 0 | 0 | 0 | 50 |

**Overall: precision = 1.00, recall = 1.00, false-positive-rate = 0.00** (TP=50, FN=0, FP=0, TN=100).

## Interpretation

- The genuine-baseline change **does not introduce false positives** on the controls (the
  outsized-but-genuine segment, which exists specifically to tempt a size-only rule, stays clean)
  and **retains full recall** on the spoof segment.
- The **delta vs the old all-orders-median logic** is shown qualitatively by
  `test_repeat_spoofer_not_masked_by_own_orders`: on a repeat-spoofer the old logic raised **0**
  alerts (the spoofs inflated the trader's own median) and the new logic raises **4**. The pure-
  spoofer case (`test_pure_spoofer_caught_via_instrument_baseline`) is caught via the
  instrument-median fallback.

## Outstanding for production calibration

- Replay against **masked production data** (or a higher-fidelity synthesised distribution from
  `scripts/synthesise.py`) to estimate real precision/recall and the volume↔coverage trade-off.
- `tuning-analyst` ATL/BTL (above-the-line / below-the-line) testing with the thresholds, and `trade-surveillance-sme` confirmation of the
  genuine-baseline exclusion against legitimate high-cancel / market-making profiles.
