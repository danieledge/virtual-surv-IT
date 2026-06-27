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
| **Verdict** | ✅ **Demo-complete** - every chain stage ran (build + code/QA/compliance review + tuning + performance); only **human sign-off** is outstanding. Not for production until re-calibrated on real data + the O(n²) fix. |

## 1. What was produced (the full chain)
business-analyst (spec) → trade-surveillance-sme (validation) → rules-developer (code + tests) →
**code-reviewer + qa-engineer + compliance-reviewer** (independent) → **tuning-analyst** (measured
calibration on synthetic data) + **performance-reviewer** (static, scalability) → PM (this report,
RTM, handover). The only gate not closed is **human sign-off** (a demo can't produce one).

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
| 9 | O(n²) pairwise scan - unbenchmarked at volume | qa/compliance | ✅ Reviewed ([perf review](performance-review.md)): won't scale; fix = group by instrument+window. 🔴 Open for productionisation. |
| 10 | Thresholds *flagged* but not yet *calibrated* | compliance | ✅ Calibrated ([tuning pack](threshold-tuning-pack.md)): measured ATL/BTL on synthetic data → `price_tolerance_pct` 0.10-0.50%. Real labelled set still needed pre-deploy. |

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
| Performance-reviewed | ✅ Met | [Perf review](performance-review.md): won't scale as-is (O(n²)); fix identified. 🔴 Open for production. |
| Thresholds calibrated | ✅ Met (demo) | [Tuning pack](threshold-tuning-pack.md): measured ATL/BTL on synthetic → 0.10-0.50%. Real labelled set needed pre-deploy. |
| Documented for handover | ✅ Met | §6 below |
| Distributable (.md + .html) | ✅ Met | rendered to `.html` |
| **Signed off (human)** | ⛔ **Pending** | demo - no human gate; a real delivery stops here for sign-off |
| Re-calibrate on real labelled data (deploy gate) | ⏭️ Deferred | demo calibrated on synthetic; real labelled set needed before production |

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

## 7. 💰 Token usage, runtime & a (quirky) rate card
Real `subagent_tokens` and `duration_ms` reported by the Agent tool. The full build + DoD delivery
used **8 agents**:

| Stage | Agent | Tier | Tokens | Runtime | ~API cost |
|---|---|---|---|---|---|
| Spec | business-analyst (Amara) | sonnet | ~16,580 | ~55s | ~$0.15 |
| SME validation | trade-surveillance-sme (Camila) | sonnet | ~16,274 | ~35s | ~$0.15 |
| Build | rules-developer (Mateo) | sonnet | ~19,859 | ~63s | ~$0.18 |
| Code review | code-reviewer (Ravi) | **opus** | ~23,199 | ~34s | **~$1.04** |
| QA | qa-engineer (Linh) | sonnet | ~32,924 | ~244s | ~$0.30 |
| Compliance | compliance-reviewer (Layla) | **opus** | ~31,077 | ~65s | **~$1.40** |
| Calibration | tuning-analyst (Theo) | sonnet | ~24,197 | ~105s | ~$0.22 |
| Performance | performance-reviewer (Thabo) | sonnet | ~18,290 | ~42s | ~$0.16 |
| **Total** | **8 agents** | | **~182,400** | **~643s agent-time** (~9 min wall-clock, reviews ran parallel) | **~$3.60** |

**Cost basis (rough, ±2×):** list prices opus ~$15/$75, sonnet ~$3/$15 per M in/out; tokens are
totals so a ~50/50 split is assumed. Note the **2 opus agents = ~68% of the cost** for ~30% of the
tokens - which is *exactly why* the model tiering reserves opus for the final-judgement roles only.

### The rate card (tongue-in-cheek, illustrative - not a quote)
What would a **human** team invoice for the same work - a spec, an SME sign-off, a build, three
independent reviews, a calibration, a performance review and a delivery pack for a new scenario?

| | The human team | This AI team |
|---|---|---|
| Effort | ~**3-5 person-days** (realistic for a new reviewed scenario) | ~**11 person-minutes** of agent-time |
| Blended rate | ~£750/day contractor (BA/dev ~£600, SME/compliance ~£900-950) | - |
| Wall-clock | days-to-weeks (calendars, handoffs, meetings) | ~**9 minutes** |
| **Invoice** | ~**£2,250 - £3,750** | ~**$3.60** in API |

So the team delivered roughly **£2-4k of consulting effort for about the price of a coffee** - in
minutes, not days. *Caveat (the honest bit):* this is a **proof-of-concept demo on synthetic data**;
the output is a *starting point for real engineers and reviewers*, not a replacement (and the human
"invoice" is illustrative). The point isn't "fire the humans" - it's *"the boring 80% gets done in
minutes so the humans spend their day on the judgement that matters."*

## 8. Responsibility notes
- **Code execution:** the tests were *run* (📊 measured) on this trusted demo repo with synthetic
  data. Ensuring handed-over code is safe to run remains the user's responsibility (§7).
- **Data:** synthetic only; no raw data reached any agent (§5).
