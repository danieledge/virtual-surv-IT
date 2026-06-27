# Delivery Report - Wash Trade / Self-Match Detection (DEMO)

> The consolidated delivery artifact for the [build demo](../build-demo.md) - the full DoD chain on
> one page. Synthetic only (§5). This is what a *complete* build stage produces, not just the build
> core. Demo artifact: not production detection logic.

| | |
|---|---|
| **Deliverable** | Wash-trade / self-match detection (sketch) |
| **Spec** | [SS-TS-001 Rev B](wash-trade-scenario-spec.md) |
| **Obligation** | MAR Art. 12(1)(a) (+ UK MAR, SEC/FINRA, CFTC, SFA, SFO) |
| **Date** | 2026-06-27 |
| **Verdict** | ✅ **Demo-complete** (fix→re-review loop closed; not for production until the DoD "deploy" gates close) |

## 1. What was produced (the full chain)
business-analyst (spec) → trade-surveillance-sme (validation) → rules-developer (code + tests) →
**code-reviewer + qa-engineer + compliance-reviewer** (independent) → PM (this report, RTM, handover).

## 2. Requirements Traceability Matrix (RTM)
The audit golden thread - obligation → spec → code → test.

| Obligation | Spec (SS-TS-001) | Code (`wash_trade.py`) | Test |
|---|---|---|---|
| MAR Art 12(1)(a) - detect self-match | §1 behaviour, §2 | `detect_wash_trades()` + `OBLIGATION` on the alert | `test_true_positive_wash_trade` |
| Off-market price is *necessary* | §4 step 3 (Rev B) | Condition 2 (max-of-both-legs early-continue) | `test_false_positive_competitive_price_suppressed` |
| UBO link required + fresh | §3, §4 step 1 | Condition 1 (UBO gate + staleness) | QA: `TestUBOStaleness` (×N) |
| Exemptions (market-makers) | §4 step 5 | Condition 3 (exemption set) | QA: `TestExemptions` |
| No invented thresholds | §5 | `KeyError` on missing param | QA: missing-param test |
| Alert carries the obligation | §7 AC3 | `obligation` + `ubo_id` fields on `WashTradeAlert` | QA: alert-field test |

## 3. Review findings & disposition (fix→re-review loop)
Independent review found **real defects the build missed**; all routed back and fixed, then re-tested.

| # | Finding | Raised by | Disposition |
|---|---|---|---|
| 1 | Deviation checked the **sell leg only** - a buy-side-only wash is missed | code-reviewer | ✅ Fixed (max of both legs) |
| 2 | **DEF-001:** UBO staleness off-by-one (`<` accepts a link AT the limit) | qa-engineer | ✅ Fixed (`<=`) |
| 3 | Alert record **lacked the obligation citation** - violated its own AC3 | compliance-reviewer | ✅ Fixed (`obligation` + `ubo_id` fields) |
| 4 | Loop assumed **buy-before-sell** ordering (silent FN on unsorted feed) | code-reviewer / QA | ✅ Fixed (full-list scan) |
| 5 | No `mid == 0` guard (ZeroDivisionError) | code-reviewer | ✅ Fixed (`if not mid`) |
| 6 | `callable` is not a valid type hint | code-reviewer | ✅ Fixed (`Callable[...]`) |
| 7 | Spec said "convergence"; code does "off-market" (divergence) | compliance-reviewer | ✅ Fixed (spec Rev B) |
| 8 | Missing-`market_mid` silently drops pairs - no observability | qa-engineer | ⏭️ Deferred (add a metric/log before production) |
| 9 | O(n²) pairwise scan - unbenchmarked at volume | qa/compliance | ⏭️ Deferred (performance review at productionisation) |
| 10 | Thresholds *flagged* but not yet *calibrated with rationale + date* | compliance | ⏭️ Deferred (tuning-analyst, pre-deploy gate) |

**Re-review result:** dev tests 2/2 pass; QA suite **33/33 pass** (DEF-001 resolved).

## 4. QA handover
Independent QA by `qa-engineer` (not the builder). Full evidence: [`qa-handover.md`](qa-handover.md)
(authored pre-fix - it is the record that *found* DEF-001; defects 1-7 are now ✅ Fixed above, QA
suite green). Coverage added: UBO staleness path, exemptions, lookback/notional boundaries, multi-pair,
missing-mid. Residual (deferred): real UBO-provider integration, volume performance, calibration.

## 5. Definition of Done - status (honest)
| DoD item | Status | Note |
|---|---|---|
| Traceable (RTM) | ✅ Met | §2 above; alert now carries obligation + UBO ID |
| Tested (TP + FP) | ✅ Met | dev 2/2 + QA 33/33 pass (re-run, 📊 measured) |
| Independently QA'd | ✅ Met | `qa-engineer`, separate from builder; [handover](qa-handover.md) |
| Code-reviewed (deep) | ✅ Met | code-reviewer; 6 findings fixed, 0 critical open |
| Compliance-reviewed | ✅ Met | obligation trace holds; §5 clean; thresholds flagged |
| Performance-reviewed | ⏭️ Deferred | O(n²) - required at productionisation, not for a demo |
| Documented for handover | ✅ Met | §6 below |
| Distributable (.md + .html) | ✅ Met | rendered to `.html` |
| **Signed off (human)** | ⛔ **Pending** | demo - no human gate; a real delivery stops here for sign-off |
| Thresholds calibrated (deploy gate) | ⏭️ Deferred | tuning-analyst, before any real use |

**Honest verdict:** complete and audit-ready *as a demo build*; **not deployable** until the three
deferred "deploy" gates (calibration, performance, human sign-off) close.

## 6. Developer handover
- **Build/run:** pure Python, no deps. `cd docs/demos/build-artifacts && python3 -m pytest` runs both
  suites (35 tests, green).
- **Entry point:** `detect_wash_trades(trades, params, ubo_link, exemptions)`; returns
  `list[WashTradeAlert]`. All 6 `params` are required (fail-loud `KeyError`) - no defaults.
- **Key design decisions:** off-market price is a *necessary* condition (early-continue, not a score);
  `as_of_date` is injected (deterministic time); UBO staleness uses `<=`; obligation + UBO ID are
  carried on the alert record.
- **Known limitations / tech debt:** O(n²) scan (benchmark before volume); no missing-mid metric;
  thresholds are `PLACEHOLDER` pending tuning; `ubo_link` is mocked (real provider integration untested).
- **How to extend:** add a quantity-offset test (spec §5) and per-instrument mid sourcing.

## 7. 💰 Token usage (this engagement)
Real `subagent_tokens` reported by the Agent tool. The full build + DoD delivery used **6 agents**:

| Stage | Agent | Tier | Tokens |
|---|---|---|---|
| Spec | business-analyst (Amara) | sonnet | ~16,580 |
| SME validation | trade-surveillance-sme (Camila) | sonnet | ~16,274 |
| Build | rules-developer (Mateo) | sonnet | ~19,859 |
| Code review | code-reviewer (Ravi) | opus | ~23,199 |
| QA | qa-engineer (Linh) | sonnet | ~32,924 |
| Compliance | compliance-reviewer (Layla) | opus | ~31,077 |
| **Total** | **6 agents** | | **~139,900** |

A full build-to-signed-off delivery cost **~140k tokens** - the price of the *complete* chain
(build + 3 independent reviews). Right-sizing kept it to 6 agents, not 16; a lighter touch (spec +
build + one review) would be roughly half.

## 8. Responsibility notes
- **Code execution:** the tests were *run* (📊 measured) on this trusted demo repo with synthetic
  data. Ensuring handed-over code is safe to run remains the user's responsibility (§7).
- **Data:** synthetic only; no raw data reached any agent (§5).
