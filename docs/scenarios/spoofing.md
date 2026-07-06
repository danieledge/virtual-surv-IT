# Scenario: Spoofing (order-book manipulation)

> Worked reference scenario for this repo. It demonstrates the team's conventions end to
> end: a deterministic, explainable rule with a traceable line from **alert → logic →
> regulatory obligation**, tested against synthetic true-positive and false-positive cases.

| | |
|---|---|
| **Domain** | Trade surveillance |
| **Status** | Reference example (synthetic) |
| **Owner / SME** | `trade-surveillance-sme` |
| **Implementation** | `rules/spoofing.py` |
| **Tests** | `tests/test_spoofing.py` |
| **Data** | `scripts/gen_synthetic.py` (synthetic only - §5) |
| **Last tuned** | 2026-06-18 (thresholds); 2026-06-29 (genuine-baseline definition) |

## 1. Regulatory obligation

- **MAR (EU) No 596/2014, Art.12(1)(a) and Annex I** - market manipulation through
  placing orders with no intention to execute ("non-bona-fide" orders) that give, or are
  likely to give, false or misleading signals as to supply, demand or price.
- **UK:** FCA MAR / Art.15 prohibition on market manipulation.

Each alert carries this obligation string in `SpoofingAlert.obligation`.

## 2. Typology

A trader places a large order on one side of the book (e.g. a large **BUY**) to create a
false impression of demand, executes a genuine order on the **opposite** side (a SELL) at
the more favourable price the illusion created, then **cancels** the large order shortly
after, having allowed it to barely (or never) execute.

## 3. Detection logic

For each `(trader, instrument)` with enough orders to form a baseline, flag a **spoof
order** that is:

1. **Outsized** - qty >= `large_qty_multiple` x the **genuine** median order size (see the
   genuine-baseline note below);
2. **Cancelled** and **short-lived** - lifetime <= `max_spoof_lifetime_ms`;
3. **Near-unfilled** - fill ratio <= `max_fill_ratio`;

**and** coincides with a **benefiting genuine execution on the opposite side** within
`opposite_exec_window_ms` of the spoof order being live.

**Genuine-baseline definition (2026-06-29).** The "median order size" the outsized test
compares against is computed over **genuine** orders only - those that do *not* have the
place-and-cancel / near-unfilled shape (the same predicate, `_is_place_and_cancel`, used to
identify candidate spoofs). This stops a prolific spoofer from inflating their own median with
their spoofs and masking the outsized test (a one-off spoof was caught, a campaign self-masked).
**Independence:** the *shape* (lifetime + fill ratio) decides what is excluded from the baseline;
**size** is then judged separately - so the baseline is not circular. When a trader has fewer than
`min_orders_for_baseline` genuine orders, sizing **falls back to the instrument's genuine median
across all traders**, so a book that is entirely spoof-shaped is still measured rather than
skipped. If there is no genuine order anywhere for the instrument, "outsized" cannot be defined
and nothing is raised (see Limitations).

See `detect_spoofing()` in `rules/spoofing.py`.

## 4. Thresholds (rationale + tuning date)

All thresholds live in `SpoofingThresholds`; none are hard-coded inline (§4).

| Threshold | Default | Rationale | Tuned |
|---|---|---|---|
| `large_qty_multiple` | 5.0 | Spoof orders are outsized to move the perceived book | 2026-06-18 |
| `max_spoof_lifetime_ms` | 2000 | Genuine resting liquidity persists; spoofs are pulled fast | 2026-06-18 |
| `max_fill_ratio` | 0.10 | Non-bona-fide orders are not meant to trade | 2026-06-18 |
| `opposite_exec_window_ms` | 3000 | Benefiting execution must be close in time to the spoof | 2026-06-18 |
| `min_orders_for_baseline` | 4 | Minimum **genuine** orders for a robust trader-level median; below this, sizing falls back to the instrument's genuine median | 2026-06-18 (gate); 2026-06-29 (now applied to the genuine subset) |

Thresholds are injectable so `data-analyst` can recalibrate and evidence the
volume/coverage trade-off without touching detection logic.

> **Enforcement-statistics context (evidence pass 2026-07-06, `docs/evidence-base.md` C41).** These
> defaults are deliberately **conservative catch-alls, not case-derived constants**. The spoofing
> mechanics and signature are verified against the Coscia and Sarao records (MAR Art 12), but the
> published case statistics are *tighter* than these thresholds: in *US v Coscia* the large
> (spoof) orders filled at ~0.08% (vs the 0.10 default here) and were generally open for under
> 500ms (vs 2000ms here); Sarao's layering used 4-6 orders stacked one price level apart. So a rule
> at these defaults comfortably catches the known cases with headroom - but the numbers are
> illustrative starting points that **must be calibrated on production data** (see the calibration
> note below), never treated as empirically-derived values.

> **Calibration note (2026-06-29).** The genuine-baseline change re-bases the effective
> outsized threshold for every trader (excluding spoof-shaped orders lowers the median for a
> spoofer, but can raise it for a legitimate fast-cancel/market-making profile). A **measured
> method-validation** FP/FN run on the labelled synthetic set is recorded in
> [`spoofing-calibration.md`](spoofing-calibration.md) (precision/recall 1.00, FP-rate 0.00;
> reproduce with `python -m scripts.calibrate_spoofing`). **Real-world calibration** on masked
> production data, and `trade-surveillance-sme` confirmation, remain owned by `tuning-analyst`
> before the change is treated as production-calibrated; the thresholds themselves are unchanged.

## 5. Test coverage

| Case | Fixture | Expectation |
|---|---|---|
| Known spoof (TP) | `spoofing_session()` | exactly one alert, BUY spoof + SELL benefit |
| Normal trading (TN) | `benign_session()` | no alert |
| Outsized but genuine (FP control) | `large_genuine_session()` | no alert (fully filled / long-resting) |
| Threshold sensitivity | `spoofing_session()` + tightened lifetime | alert suppressed |
| Repeat spoofer (FN regression) | 4 genuine + 4 large spoofs | all spoofs flagged (own spoofs don't mask the baseline) |
| Pure spoofer (W1 regression) | all spoof-shaped + another trader's genuine flow | flagged via the instrument-median fallback |
| No genuine baseline (limitation) | all spoof-shaped, none genuine market-wide | no alert (cannot size "outsized") |
| Same-ms lifecycle | FILL listed before its NEW at the same ms | fill applied, not dropped |

## 6. Running this scenario

Prerequisite: `pip install -r requirements-dev.txt` (standard library + pytest; no extra deps for
the rule itself).

```bash
# 1. Generate synthetic order flow (no real data - §5).
python -m scripts.gen_synthetic --kind spoofing --out data/synthetic/spoofing.jsonl
#    other fixtures: --kind benign | large_genuine

# 2. Run the rule's tests (true-positive, false-positive, and regression cases).
pytest tests/test_spoofing.py -v

# 3. Prove masking preserves the signal (the rule fires identically masked vs original).
python -m scripts.validate_masking
```

Use the rule directly in code:

```python
from rules.spoofing import detect_spoofing, SpoofingThresholds
from scripts.gen_synthetic import spoofing_session

alerts = detect_spoofing(spoofing_session(seed=1))
for a in alerts:
    print(a.spoof_order_id, "-", a.reason)
    print("  obligation:", a.obligation)

# Thresholds are injectable - recalibrate without touching detection logic:
detect_spoofing(spoofing_session(seed=1), SpoofingThresholds(large_qty_multiple=6.0))
```

> `pytest` executes code, so inside the team it needs execution consent - granted by the human
> only, via the `.claude/.exec-consent` marker or `CST_ALLOW_EXEC=1` (the `/engage` intake answer
> records intent, it grants nothing) - see
> [the safety hooks](../../README.md#-the-safety-hooks-plain-english).
> The `scripts.*` helpers (`gen_synthetic`, `validate_masking`) are always allowed.

## 7. Limitations & open items

- Single-account heuristic; does not yet detect **layering** (multiple orders at
  successive price levels) or **cross-account** coordination.
- Median baseline is per-session; production should use a rolling per-trader baseline.
- No price-context check (distance from the touch, i.e. the best bid or offer) - a candidate enhancement.
- **No genuine baseline anywhere (2026-06-29):** if neither the trader nor any other trader has
  a genuine order in the instrument, "outsized" cannot be defined and **no alert is raised**.
  This is a deliberate, documented choice (don't guess a baseline); it is a rare degenerate case
  (zero genuine flow market-wide in the window) and is pinned by a test.
- **Genuine-baseline FP risk:** excluding fast-cancel/near-unfilled orders from the baseline
  could, for a legitimate high-cancel profile (e.g. market-making, fleeting IOC quotes), raise
  the median and suppress borderline alerts, or lower it and over-alert. The FP/FN impact needs
  measured calibration evidence (see the calibration note in §4) and `trade-surveillance-sme`
  confirmation.

## 8. Review trail

- [ ] `trade-surveillance-sme` reviewed detection logic
- [x] `code-reviewer` reviewed the 2026-06-29 genuine-baseline change (findings W1/W2/M1 applied:
      instrument-median fallback, gate on the genuine subset, shared shape predicate)
- [x] `compliance-reviewer` reviewed auditability/§4/§5 for the 2026-06-29 change; this doc + the
      RTM updated in response (C1/W3). **Outstanding for sign-off:** measured FP/FN calibration
      evidence (§4 note), `trade-surveillance-sme` confirmation, and human sign-off in the RTM.
- Tuning history:
  - 2026-06-18 - initial calibration on synthetic set.
  - 2026-06-29 - genuine-only size baseline + instrument-median fallback; same-ms event ordering
    fix in `reconstruct_orders`. Thresholds unchanged. Regression tests added.
