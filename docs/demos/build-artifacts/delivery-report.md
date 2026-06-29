# Delivery Report - TS-001 Wash Trade / Self-Match Detection (DEMO, Run 2)

> # ⏩ AFTER - "as-delivered" current state
> The consolidated delivery for the [build demo](../build-demo.md) - the full DoD chain on one page,
> after the review fixes. Pair it with the [QA handover](qa-handover.md) (the ⏪ *as-found* snapshot).
> This is the **canonical run** (Run 2); see how it compares to Run 1 in the
> [run comparison](../build-run-comparison.md). Synthetic only (§5); demo artifact, not production logic.

| | |
|---|---|
| **Deliverable** | TS-001 wash-trade / self-match detection |
| **Spec** | [TS-001](ts001-scenario-spec.md) (SME-validated; open questions dispositioned §9) |
| **Obligation** | MAR Art 12(1)(a) - **PROVISIONAL** (mapping pending SME Q1/Q3/Q4) |
| **Date** | 2026-06-27 |
| **Verdict** | ✅ **Demo-complete** - every chain stage ran (build + code/QA/compliance review + tuning + performance). Not deployable until the obligation mapping is finalised, calibrated on real data, the O(n²) fixed, and a human signs off. |

> **Status in one line:** review **defects ✅ Fixed** (suites green); what's open is by design -
> the **obligation mapping** (SME blockers Q1/Q3/Q4, carried as `obligation_status=PROVISIONAL`),
> **deploy-gates ⏭️ Deferred** (real-data calibration, `min_notional`, O(n²), intraday alert-id), and
> **human sign-off ⛔ Pending**.

## 1. The chain (8 agents)
business-analyst (Amara) → trade-surveillance-sme (Camila, +disposition) → rules-developer (Mateo) →
code-reviewer (Ravi) + qa-engineer (Linh) + compliance-reviewer (Layla) → tuning-analyst (Theo) +
performance-reviewer (Thabo) → PM compile.

> 🔁 **Knowledge compounded:** Mateo built against `house-rules.md`, so **none of Run 1's 7 defects
> recurred** - the build passed its tests first time (Run 1's failed on a wall-clock bug). The review
> still earned its keep by finding *new, subtler* issues. Full story: [run comparison](../build-run-comparison.md).

## 2. RTM (traceability spine)
| Obligation | Spec | Code (`ts001_wash_trade.py`) | Test |
|---|---|---|---|
| MAR Art 12(1)(a) - self-match | §1-2 | `detect_wash_trades` + `OBLIGATION` field | `test_true_positive_wash_trade` |
| Off-market = necessary | §4.2 | early-continue on `dev_bps < threshold` | `test_false_positive_at_market_suppressed` |
| UBO link + fresh | §4.1 | UBO gate + `_validate_ubo_freshness` | QA staleness boundary tests |
| Safe-harbour exemption | §4.3 | `exempt_account_ids` pre-filter | `test_exempt_account_suppressed` |
| Mapping not finalised | §9 | `obligation_status=PROVISIONAL` | `test_true_positive` asserts PROVISIONAL |
| No invented thresholds | §5 | `DetectionParams` no defaults | (fail-loud) |

## 3. Review findings & disposition (fix→re-review loop)
| # | Finding | By | Disposition |
|---|---|---|---|
| 1 | Off-market test & reported deviation computed from two sources | code-review | ✅ Fixed (`_deviation_bps` single source) |
| 2 | Snapshot date not recorded on the alert (auditability) | code-review | ✅ Fixed (`snapshot_date` field) |
| 3 | Falsy-snapshot `or` idiom fragile | code-review | ✅ Fixed (explicit `is None`) |
| 4 | Obligation literal *looks finalised* while mapping is blocked | compliance | ✅ Fixed (`obligation_status=PROVISIONAL`) + new house-rule |
| 5 | DEF-001 missing snapshot silently drops pairs | QA | ✅ Fixed (logged as data-quality warning) |
| 6 | DEF-002 snapshot date tie-break undocumented | QA | ✅ Fixed (buy-date governs, documented + tested) |
| 7 | Same-account self-match excluded | code-review | ✅ Dispositioned (scope: TS-001 = cross-account; intra-account = sibling scenario) |
| 8 | DEF-003 quantity/notional not matched | QA/tuning | ⏭️ Deferred (`min_notional` required - tuning pack) |
| 9 | O(B×S) won't scale | performance | ⏭️ Deferred (pre-group by instrument+UBO; productionisation) |
| 10 | Obligation mapping not finalised | compliance/SME | ⏭️ Deferred (Q1/Q3/Q4 go-live blockers - [spec §9](ts001-scenario-spec.md)) |

**Re-review result:** dev 3/3 + QA suite green.

## 4. Definition of Done
| Item | Status |
|---|---|
| Traceable (RTM) | ⚠️ Partial - spine + fields present; obligation *mapping* not finalised (PROVISIONAL) |
| Open questions dispositioned | ✅ Met ([spec §9](ts001-scenario-spec.md)) |
| Tested (TP + FP) | ✅ Met (dev 3/3 + QA suite, 📊 measured) |
| Independently QA'd | ✅ Met ([qa-handover](qa-handover.md)) |
| Code-reviewed | ✅ Met (findings fixed/dispositioned) |
| Compliance-reviewed | ✅ Met (data-safety clean; mapping flagged) |
| Performance-reviewed | ✅ Met ([perf review](performance-review.md); O(n²) Open for prod) |
| Thresholds calibrated | ⏭️ Deferred ([tuning pack](threshold-tuning-pack.md); real labelled set needed) |
| Documented for handover | ✅ Met (§5) |
| Distributable (.md + .html) | ✅ Met |
| Signed off (human) | ⛔ Pending (a demo can't produce one) |

## 5. Developer handover
- **Run tests:** `cd docs/demos/build-artifacts && python3 -m pytest test_ts001_wash_trade.py test_ts001_qa.py`.
- **Entry point:** `detect_wash_trades(trades, ubo_links, ubo_as_of, market_snapshots, params, as_of_date)`.
  All `DetectionParams` required (fail-loud). `as_of_date` injected (deterministic).
- **Design:** off-market = necessary (early-continue); UBO staleness gate aborts; obligation +
  `obligation_status` + `ubo_group_id` + `snapshot_date` on the alert; missing snapshot logged.
- **Known limitations / tech debt:** O(B×S) (pre-group before volume); `min_notional` absent (tuning);
  intraday alert-id collision; obligation mapping PROVISIONAL until Q1/Q3/Q4.

## 6. 💰 Token usage, runtime & a (quirky) rate card
Real `subagent_tokens` / `duration_ms`. Full comparison vs Run 1: [run comparison](../build-run-comparison.md).

| Stage | Agent | Tier | Tokens | Runtime |
|---|---|---|---|---|
| Spec | business-analyst (Amara) | sonnet | ~17,329 | ~65s |
| SME + disposition | trade-surveillance-sme (Camila) | sonnet | ~16,570 | ~64s |
| Build | rules-developer (Mateo) | sonnet | ~22,745 | ~94s |
| Code review | code-reviewer (Ravi) | opus | ~21,036 | ~48s |
| QA | qa-engineer (Linh) | sonnet | ~25,808 | ~151s |
| Compliance | compliance-reviewer (Layla) | opus | ~21,932 | ~62s |
| Calibration | tuning-analyst (Theo) | sonnet | ~29,973 | ~115s |
| Performance | performance-reviewer (Thabo) | sonnet | ~16,009 | ~42s |
| **Total** | **8 agents** | | **~171,400** | **~641s** (~9 min wall-clock) |

~**$3-6** API at list prices (±2×); the 2 opus agents are ~25% of tokens but the bulk of the cost -
which is why opus is reserved for the final-judgement roles.

### The rate card (tongue-in-cheek, illustrative - not a quote)
What would a **human** team invoice for the same work - a spec, an SME sign-off, a build, three
independent reviews, a calibration, a performance review and a delivery pack for a new scenario?

| | The human team | This AI team |
|---|---|---|
| Effort | ~**3-5 person-days** (realistic for a new reviewed scenario) | ~**11 person-minutes** of agent-time |
| Blended rate | ~£750/day contractor (BA/dev ~£600, SME/compliance ~£900-950) | - |
| Wall-clock | days-to-weeks (calendars, handoffs, meetings) | ~**9 minutes** |
| **Invoice** | ~**£2,250 - £3,750** | ~**$3-6** in API |

So the team delivered roughly **£2-4k of consulting effort for about the price of a coffee** - in
minutes, not days. *Caveat (the honest bit):* this is a **proof-of-concept demo on synthetic data**;
the output is a *starting point for real engineers and reviewers*, not a replacement (and the human
"invoice" is illustrative). The point isn't "fire the humans" - it's *"the boring 80% gets done in
minutes, so the humans spend their day on the judgement that matters."*

## 7. Responsibility notes
Code executed (📊) on this trusted demo repo with synthetic data; ensuring handed-over code is safe to
run remains the user's responsibility (§7). No raw data reached any agent (§5).
