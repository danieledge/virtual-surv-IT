# QA Handover - TS-001 Wash Trade / Self-Match Detection (DEMO)

> Produced by `qa-engineer` (Linh) - independent of the builder (Mateo / rules-developer).
> Evidences what was tested, exact results, what is NOT covered, and items for the human QA team.
>
> **This is the "as-found" record. Do NOT retro-edit once defects are fixed.**

> **Document control** · ID `QAH-TS001-001` · Version `0.1` · Status `In review`
> · Classification `Internal` · Owner `qa-engineer (Linh)` · As-of `2026-06-30`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-06-30 | Linh (qa-engineer) | Independent QA pass against commit 8dc8044 |

| | |
|---|---|
| **Deliverable** | TS-001 Wash Trade / Self-Match detector (`ts001_wash_trade.py`) |
| **Version / commit** | `8dc8044` (main, 2026-06-30) |
| **Traces to** | SCN-001 v0.1 (DR-001 through DR-006), SMV-001 v0.1 |
| **Tested by** | Linh (qa-engineer) - did NOT write the detector |
| **Date** | 2026-06-30 |
| **Overall** | Ready with notes - detector logic passes all 41 tests; one pre-existing QA file defect resolved (DEF-QA-001); obligation mapping remains PROVISIONAL pending SME open questions (not a code defect) |

---

## 1. Test execution summary

| Suite | File | Tests | Passed | Failed | Skipped |
|-------|------|-------|--------|--------|---------|
| Developer (Mateo) | `test_ts001_wash_trade.py` | 10 | 10 | 0 | 0 |
| Independent QA (Linh) | `test_ts001_qa.py` | 31 | 31 | 0 | 0 |
| **Combined** | both | **41** | **41** | **0** | **0** |

All results are 📊 measured (executed on the actual code, not inferred).

**Acceptance threshold:** zero failed tests; all true-positive and false-positive acceptance
criteria cases covered. Threshold: **met**.

### How to reproduce (exact commands)

```bash
# Environment: Python 3.12.3, pytest 9.0.1, platform linux
# From repo root - detector and tests both live in docs/demos/build-artifacts/

cd docs/demos/build-artifacts

# Developer suite only
python3 -m pytest test_ts001_wash_trade.py -v

# Independent QA suite only
python3 -m pytest test_ts001_qa.py -v

# Both suites together (recommended for CI)
python3 -m pytest test_ts001_wash_trade.py test_ts001_qa.py -v
```

No additional dependencies beyond the repo standard environment.
All fixtures are fully synthetic (CLAUDE.md §5); no real data is required.

---

## 2. Environment and test data

**Environment:**
- Python 3.12.3
- pytest 9.0.1, pluggy 1.6.0
- Platform: linux
- Commit: `8dc8044`

**Test data provenance:**
All trade IDs, account IDs, UBO group IDs, instrument identifiers and notionals are wholly
synthetic (naming convention: `SYNTH-EQ-QA-*`, `ACCT-A/B/C/D`, `UBO-QA-X/Y`,
`MM-ACCT-QA-001`). Market snapshot parameters (mid=100.0, spread=5.0 bps) are illustrative
round numbers chosen for clear boundary arithmetic, not derived from real market data. Exact
float values for boundary tests (e.g., `price=100.05` yields `normalised=0.9999...` in IEEE 754)
were verified by a pre-write Python 3.12 arithmetic check before the tests were authored.

---

## 3. Coverage

### 3a. What is covered (📊 measured - combined 41 tests)

| Detection requirement | Mateo's tests | Linh's tests | Notes |
|---|---|---|---|
| DR-001: cross-account off-market same-UBO pair -> alert | test_tp_cross_account_off_market_same_ubo | TestAlertFields::test_alert_carries_all_mandatory_obligation_fields | Obligation fields asserted independently |
| DR-001: single-account both-sides wash | test_tp_single_account_both_sides | - | SCN-001 §3 in-scope variant; Mateo's coverage sufficient |
| DR-001: multi-day pair within lookback | test_tp_off_market_within_lookback_not_same_day | TestLookbackWindowBoundary (2 tests) | Mateo tests interior; Linh adds at-boundary and over-boundary |
| DR-001: cross-instrument isolation | - | TestMultiplePairs::test_cross_instrument_pairs_are_not_formed | NEW |
| DR-001: cross-UBO-group isolation | test_fp_coincident_independent_orders_liquid_price | TestMultiplePairs::test_cross_ubo_group_does_not_pair | NEW independent assertion |
| DR-001: full cross-product 2x2 pairing | - | TestMultiplePairs::test_two_buys_two_sells_same_ubo_full_cross_product | NEW |
| DR-002: at-market fails necessary condition | test_fp_affiliated_funds_at_market | TestSpreadMultipleBoundary (5 tests) | NEW: at-threshold, above, below, dynamic boundary, asymmetric avg |
| DR-003: MM strategy tag suppressed + logged | test_fp_designated_mm_strategy_tagged_cross | TestSafeHarbour (3 tests) | NEW: account register, RISKLESS_PRINCIPAL tag, non-exempt tag does not suppress |
| DR-004: immaterial notional no alert | test_fp_immaterial_notional | TestNotionalBoundary (3 tests) | NEW: exact-at-floor, just-below, smaller-leg governs |
| DR-005: stale UBO -> DQ warning no alert | test_fp_stale_ubo_graph_warns_no_alert | TestUboFreshnessBoundary (3 tests) | NEW: at-limit (not stale), over-limit, partial-stale (one excluded, rest intact) |
| DR-006: implied-match disabled raises | test_implied_match_tier_disabled_raises | - | Mateo's coverage sufficient |
| Missing snapshot -> DQ warning | test_no_snapshot_is_dq_warning_not_alert | TestSnapshotFallback (2 tests) | NEW: also tests buy-date-absent fallback path |
| Zero / negative spread -> DQ warning | - | TestZeroAndNegativeSpread (2 tests) | NEW |
| Empty/edge inputs no crash | - | TestEdgeInputs (5 tests) | NEW: empty trades, empty UBO, fully empty, unknown side, orphan account |
| Alert ID sequential + date-embedded | - | TestAlertFields::test_alert_ids_are_sequential_and_embed_as_of_date | NEW |
| Alert field arithmetic consistency | - | TestAlertFields::test_alert_spread_deviation_arithmetic_consistency | NEW |

### 3b. What is NOT covered (and why) - 📊 gap register

| Gap | Risk level | Why not covered |
|---|---|---|
| **At-market wash trading (volume inflation without price signal)** | High (accepted design gap) | DR-002 discards at-market pairs by design (SMV-001 §1.2). Not a code defect. Candidate future scenario TS-003. |
| **`mid_price <= 0` silent discard** | Medium | No DQ warning in this code path (see NOTE-001). The case produces 0-deviation -> pair silently dropped. Untested because there is nothing to assert on from the outside. |
| **Performance / volume stress** | Medium for production | No test with >100 trades. O(B*S) complexity within a large UBO group is untested. 🧠 Inferred acceptable for demo scale. |
| **Sub-second / intraday timing** | Medium for production | Detector uses date granularity (demo assumption). Production asset-class-specific intraday windows are not implemented or tested. |
| **Obligation string correct against EUR-Lex primary source** | Regulatory risk | Automated tests assert the string IS present as `"EU MAR Art.12(1)(a)"`. Whether this matches the current EUR-Lex text is a human-only verification. |
| **PROVISIONAL status process control** | Regulatory risk | Tests assert status IS "PROVISIONAL". Cannot automate the control that it must NOT be upgraded without sign-off. This is a process/governance control. |
| **Safe-harbour register lapse (false-negative risk)** | Operational | Register is a static frozenset in tests. Lapsed MM designation in a live feed is a data/process risk, not code. |
| **Affiliated-fund FP volume (Q4 open)** | High structural risk | Cannot be tested until Q4 (connected-party width) is resolved. Structural, not testable with current schema. |
| **DR-006 implied-match tier logic** | Deferred (off at launch) | Tier disabled per SME Q5. Guard tested (Mateo). Logic unimplemented; cannot be tested. |
| **Integration with live upstream feeds** | Out of scope (demo) | All tests are unit-level with synthetic data. |

### 3c. Residual risk

1. **Silent suppression when `mid_price <= 0`** - A data-quality fault producing mid=0 will cause
   all pairs on that instrument to be silently discarded with no DQ warning. The `spread <= 0`
   case is guarded; `mid <= 0` is not. Recommend hardening before connecting to a live market data
   feed (see NOTE-001).

2. **O(n^2) pairing complexity** - In a large deployment with many UBO-linked accounts, the
   cross-product of buys and sells could produce very large alert volumes. 🧠 Inferred as acceptable
   for demo; must be benchmarked before production deployment.

3. **Obligation mapping is PROVISIONAL** - A standing regulatory risk (not a code risk). All alerts
   carry `obligation_status = "PROVISIONAL"`. Correct per spec. Must not be changed without
   SME Q1/Q3/Q4 resolution and register verification.

---

## 4. Defects and known issues (as-found)

| ID | Severity | Description | Status |
|----|----------|-------------|--------|
| DEF-QA-001 | Medium | **Pre-existing `test_ts001_qa.py` entirely non-functional.** The file imported `UBOGraphStaleError` (does not exist in the detector), used wrong argument order, and used wrong `DetectionParams` field name (`off_market_threshold_bps` vs `off_market_spread_multiple`). Failure mode: `ImportError` at pytest collection - surfaces as a collection error, not a test failure, making it easy to overlook in CI. Zero coverage was provided. | ✅ Resolved - overwritten with this 31-test independent suite. |
| NOTE-001 | Informational | **`mid_price <= 0` produces no DQ warning.** When a market snapshot has `mid_price=0` or negative, `_price_deviation_bps` returns `0.0`, `normalised=0`, and the pair is silently discarded via the DR-002 early-continue. No DQ warning is raised, unlike the analogous `spread <= 0` guard. This is not a defect against the current spec (which does not require a mid-price guard) but is a hardening gap for production. | Open - recommend raising with builder as a pre-production hardening item. Not a demo blocker. |

---

## 5. Items for the QA team to note and re-verify

The following require human review and cannot be fully verified by automated test.

### 5a. Regulatory and obligation mapping

1. **Verify obligation reference string against EUR-Lex primary source.** The alert carries
   `obligation_reference = "EU MAR Art.12(1)(a)"`. Tests assert the string is present.
   A human reviewer must verify this against the current EUR-Lex text of Regulation (EU) No 596/2014
   before any alert enters a regulatory report or STOR. The citation is in
   `config/regulatory-register.yaml` with `status: verified`; confirm the register entry is current.

2. **PROVISIONAL status must remain until SME blockers resolved.** Tests assert alerts carry
   `obligation_status = "PROVISIONAL"`. Per SMV-001 §5, this must not be upgraded without signed
   Legal/Compliance decisions on Q1 (regime/venue scope), Q3 (intragroup treatment) and Q4
   (connected-party width), plus human verification and register addition of all TO-VERIFY citations.
   This is a process control for the QA team, not an automated gate.

3. **MAR Art.12(2)(c) indicator not in register.** Cited conceptually in the spec (TO-VERIFY, 🧠).
   Must not appear in alert fields, STORs or regulatory reports until verified and added to the
   register. The detector does not reference it in alert fields; confirm no downstream processing
   promotes it.

4. **All non-EU-MAR jurisdiction equivalents are TO-VERIFY (🧠).** UK MAR, FINRA 6140, CFTC CEA,
   SG SFA, HK SFO, JP FIEA - all absent from the register. The detector does not reference them.
   Confirm this remains the case in any downstream alert management system.

### 5b. Threshold calibration

5. **All thresholds carry `tuning_date: TBD`.** `DEFAULT_LOOKBACK_DAYS=1`,
   `DEFAULT_OFF_MARKET_SPREAD_MULTIPLE=1.0`, `DEFAULT_MIN_PAIR_NOTIONAL=10000.0`,
   `DEFAULT_UBO_GRAPH_MAX_AGE_DAYS=90` are all uncalibrated starting points. Tests verify the
   detector respects these values; they do not validate the values are appropriate. Tuning-analyst
   (Theo) must calibrate against evidence before go-live.

6. **Boundary semantics of the off-market threshold.** At exactly `normalised == threshold`, the
   condition `normalised <= threshold` fires (no alert - a false negative at the boundary). The spec
   says "more than the configured threshold" (implying strict `>`), which is consistent with the
   current `<=` early-continue. Confirm with Camila this boundary interpretation is intended.

### 5c. Operational hardening

7. **mid_price <= 0 silent discard (NOTE-001).** A data-feed fault producing mid=0 suppresses pairs
   without a DQ warning. Before live market data connection, add a mid-price guard with DQ warning
   analogous to the existing spread guard.

8. **DQ warnings must feed an operational dashboard.** DR-005 stale-graph warnings and missing-
   snapshot warnings are returned in `result.data_quality_warnings`. In production, these must flow
   to a data-quality monitoring tool so persistent gaps surface to a data owner, not just into
   application logs.

9. **Safe-harbour register update process.** The static `exempt_account_ids` register must in
   production be sourced from a maintained feed with a defined review cycle (SMV-001 Q2). A lapsed
   MM designation creates a false-negative. Confirm the operational process is defined before go-live.

10. **Q4 affiliated-fund structural risk.** If Q4 resolves the UBO boundary at management-company
    level rather than fund level, affiliated-fund FP volume could be operationally disabling. This
    structural risk must be resolved in Q4 before any production deployment sign-off; it cannot be
    mitigated by threshold tuning.

---

## Disposition tally

| Category | Count | Items |
|---|---|---|
| ✅ Resolved | 1 | DEF-QA-001 (broken prior QA file, overwritten) |
| 🔴 Open defect / blocker | 0 | None |
| ⏭️ Deferred / needs-input | 1 | NOTE-001 (mid<=0 silent discard - pre-production hardening) |
| ⚖️ Accepted / by-design | 3 | At-market wash trading gap (DR-002 design), O(n^2) complexity, PROVISIONAL obligation status |

**Disposition tally:** ✅ 1 Resolved · 🔴 0 Open · ⏭️ 1 Deferred · ⚖️ 3 Accepted.

**QA verdict: Ready with notes.** All 41 automated tests pass. No open defects in the detector
implementation. DEF-QA-001 resolved. All residual items are accepted-by-design, deferred
pre-production hardening, or regulatory-mapping items requiring human review - none block the demo
deliverable.

---

## Sign-off

| Role | Name | Decision | Date |
|---|---|---|---|
| Author / owner | Linh (qa-engineer) | QA pass complete. Evidence above is as-found. | 2026-06-30 |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver | | | |
