# QA Handover - Test Evidence - TS-002 Layering Detection *(worked example)*

> **Worked example** of the test-cycles capability. Fictional engagement, synthetic data
> throughout. Note how **pass 1's Fail verdict stays in the document forever** - the
> resolved state lives in the Delivery Report, never by rewriting this record.

> **Document control** · ID `QAH-002` · Version `0.2` · Status `Approved (as-found)`
> · Classification `Internal` · Owner `qa-engineer` · As-of `2026-07-19`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-07-19 | qa-engineer | Pass 1 executed and recorded (Fail: D-1, D-2) |
> | 0.2 | 2026-07-19 | qa-engineer | Pass 2 appended (Pass); defect lifecycle closed out |

| | |
|---|---|
| **Deliverable** | `ts002_layering.py` + config `ts002-thresholds.conf` |
| **Version / commit** | `3f9c2a1` (pass 1) → `8d417be` (pass 2) |
| **Traces to** | ELC-002 / RTM-002 |
| **Tested by** | qa-engineer (independent of rules-developer) |
| **Date** | 2026-07-19 |
| **Overall** | ✅ ready for QA *(as-found across 2 cycles - see §1)* |

## 1. Test cycles *(append-only - one row per pass, failed verdicts stay forever)*

| Pass | Date | Scope | Verdict | Defects raised | Routed to |
|------|------|-------|---------|----------------|-----------|
| 1 | 2026-07-19 | full suite (22 cases) | ❌ **Fail** | D-1, D-2 | `rules-developer` |
| 2 | 2026-07-19 | re-test D-1, D-2 + full regression | ✅ **Pass** | - | - |

## 2. Test execution summary *(latest pass; earlier passes stay in §1 and §5)*
| Suite | Tests | Passed | Failed | Skipped |
|-------|-------|--------|--------|---------|
| unit | 14 | 14 | 0 | 0 |
| scenario (TP/FP) | 8 | 8 | 0 | 0 |

**Acceptance threshold:** zero failed tests; all true-positive and false-positive scenario
cases pass. *(Pass 1 result for the record: 20/22 - two scenario failures → QA hold.)*

## 3. Environment & test data
- Python 3.12, pytest; synthetic order-book data via `gen_synthetic` (§5) - no real data.

## 4. Coverage
- **Covered:** layering TP patterns (5), FP look-alikes (3: genuine repricing, iceberg
  refresh, partial-fill chase), window boundaries, cancel-ratio edge exactly at 0.8.
- **NOT covered:** live-volume calibration (deferred - clarification round 3, ELC-002 §10).
- **Residual risk:** thresholds are demo-calibrated on synthetic distributions.

## 5. Defects & known issues *(lifecycle - never delete a row once raised)*
| ID | Severity | Description | Raised in pass | Routed to | Fix evidence | Verified fixed in pass | Status |
|----|----------|-------------|----------------|-----------|--------------|------------------------|--------|
| D-1 | High | FP case "partial-fill chase" wrongly alerts: genuine order amended after partial fill counted as a cancel | 1 | `rules-developer` | `8d417be` - amend-after-fill excluded from cancel ratio | 2 | ✅ Fixed |
| D-2 | Medium | Cancel-ratio boundary: exactly 0.8 not alerting (spec says ≥) | 1 | `rules-developer` | `8d417be` - `>` corrected to `>=`, boundary test added | 2 | ✅ Fixed |

**Disposition tally:** ✅ 2 Fixed · 🔴 0 Open · ⏭️ 0 Deferred · ⚖️ 0 Accepted - reconciles
with the pass-2 verdict.

## 6. Items for the QA team to note / re-verify
- Threshold rationale (§4 obligation): documented in the tuning pack; re-verify against real
  volumes at deployment (round 3).

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | qa-engineer | Pass (2 cycles, as-found) | 2026-07-19 |
| `compliance-reviewer` (DoD gate) | compliance-reviewer | Cycle history complete | 2026-07-19 |
| Human approver | *(example - unsigned)* | | |
