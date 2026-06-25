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
| **Last tuned** | 2026-06-18 |

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

1. **Outsized** - qty ≥ `large_qty_multiple` × the trader's median order size;
2. **Cancelled** and **short-lived** - lifetime ≤ `max_spoof_lifetime_ms`;
3. **Near-unfilled** - fill ratio ≤ `max_fill_ratio`;

**and** coincides with a **benefiting genuine execution on the opposite side** within
`opposite_exec_window_ms` of the spoof order being live.

See `detect_spoofing()` in `rules/spoofing.py`.

## 4. Thresholds (rationale + tuning date)

All thresholds live in `SpoofingThresholds`; none are hard-coded inline (§4).

| Threshold | Default | Rationale | Tuned |
|---|---|---|---|
| `large_qty_multiple` | 5.0 | Spoof orders are outsized to move the perceived book | 2026-06-18 |
| `max_spoof_lifetime_ms` | 2000 | Genuine resting liquidity persists; spoofs are pulled fast | 2026-06-18 |
| `max_fill_ratio` | 0.10 | Non-bona-fide orders are not meant to trade | 2026-06-18 |
| `opposite_exec_window_ms` | 3000 | Benefiting execution must be close in time to the spoof | 2026-06-18 |
| `min_orders_for_baseline` | 4 | Avoid flagging on samples too small for a median | 2026-06-18 |

Thresholds are injectable so `data-analyst` can recalibrate and evidence the
volume/coverage trade-off without touching detection logic.

## 5. Test coverage

| Case | Fixture | Expectation |
|---|---|---|
| Known spoof (TP) | `spoofing_session()` | exactly one alert, BUY spoof + SELL benefit |
| Normal trading (TN) | `benign_session()` | no alert |
| Outsized but genuine (FP control) | `large_genuine_session()` | no alert (fully filled / long-resting) |
| Threshold sensitivity | `spoofing_session()` + tightened lifetime | alert suppressed |

## 6. Limitations & open items

- Single-account heuristic; does not yet detect **layering** (multiple orders at
  successive price levels) or **cross-account** coordination.
- Median baseline is per-session; production should use a rolling per-trader baseline.
- No price-context check (distance from touch) - a candidate enhancement.

## 7. Review trail

- [ ] `trade-surveillance-sme` reviewed detection logic
- [ ] `compliance-reviewer` confirmed auditability, thresholds rationale, no secrets/PII,
      test coverage
- Tuning history: 2026-06-18 - initial calibration on synthetic set.
