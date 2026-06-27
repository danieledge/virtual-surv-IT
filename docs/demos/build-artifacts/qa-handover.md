# QA Handover - TS-001 Wash Trade Detector (DEMO, Run 2)

> # ⏪ BEFORE - "as-found" QA snapshot
> The QA evidence as first produced by `qa-engineer` (Linh), independent of the builder. It records
> **what QA caught**; it is **not** retro-edited (audit trail). The defects were then routed back and
> resolved - the **current state** is in the [delivery report](delivery-report.md) §3.

| | |
|---|---|
| **Deliverable** | `ts001_wash_trade.py` (DEMO) |
| **Tested by** | qa-engineer (Linh) - independent |
| **Date** | 2026-06-27 |
| **Overall (as-found)** | PASS-WITH-GAPS - 3 defects · *(pre-fix; see delivery report for resolved state)* |

## 1. Execution
Dev suite 3/3, plus an independent QA suite (boundaries, exemptions, multi-instrument, missing
snapshot, same-account, cross-UBO) - all pass. Synthetic only.

## 2. What the dev tests cover
True-positive (off-market, same UBO), false-positive (at-market suppressed), stale-UBO raises.
Nothing else - the QA suite adds the branch coverage below.

## 3. Defects found (as-found)
- **DEF-001 (MEDIUM):** a missing market snapshot **silently drops** qualifying pairs - no log, no
  counter. In production a feed outage becomes an invisible surveillance gap. *(Fixed → now logged as
  a data-quality warning.)*
- **DEF-002 (LOW):** the buy-date-vs-sell-date snapshot tie-break (`or`) was undocumented. *(Fixed →
  buy-leg date governs, documented + tested.)*
- **DEF-003 (LOW):** `quantity` is captured but never matched - an asymmetric pair (1 share vs 1M)
  alerts identically; no notional floor. *(Deferred → `min_notional` is a required tuning param.)*

## 4. Coverage gaps / residual risk (as-found)
Exempt-account path, lookback & staleness boundaries, cross-UBO/cross-instrument negatives, alert-id
collision on intraday re-runs, and O(B×S) volume behaviour were untested by the dev suite. Residual:
real UBO-feed integration, threshold calibration, the obligation mapping (SME blockers).

## 5. Verdict (as-found): PASS-WITH-GAPS - not production-ready
Top tests to add (now in the QA suite): missing-snapshot observability, staleness/lookback boundaries,
exemption path. Deploy gates (calibration, real-data, sign-off) remain open by design.
