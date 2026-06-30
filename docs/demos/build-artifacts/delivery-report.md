# Delivery Report - TS-001 Wash Trade / Self-Match Detection (DEMO)

> **Document control** · ID `DLVR-001` · Version `0.1` · Status `In review` · Classification `Internal` · Owner `PM (Morgan)` · As-of `2026-06-30`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-06-30 | Morgan (PM) | Consolidated delivery for the build-demo re-run |

> **⏩ AFTER — "as-delivered" snapshot.** The full DoD chain on one page, *after* the review fix-loop.
> Pair it with the [QA handover](qa-handover.md) and the review findings below (the ⏪ *as-found*
> record — preserved, not retro-edited). Synthetic only (§5); a **demo artifact, not production logic.**

| | |
|---|---|
| **Deliverable** | TS-001 wash-trade / self-match detection (`ts001_wash_trade.py`) |
| **Spec** | [SCN-001](ts001-scenario-spec.md) (SME-validated; open questions dispositioned) · [SME validation](ts001-sme-validation.md) |
| **Obligation** | **EU MAR Art 12(1)(a)** — register-`[VERIFIED]`. All other pinpoints (Art 12(2)(c) + non-EU equivalents) **`[TO-VERIFY]` 🧠**. `obligation_status = PROVISIONAL`. |
| **Date** | 2026-06-30 |
| **Verdict** | ✅ **Demo-complete** — every chain stage ran (spec → SME → build → independent QA → code/compliance/performance review → measured tuning → delivery). **Not deployable** until: obligation mapping finalised (SME Q1/Q3/Q4), threshold re-confirmed on real data, the O(B×S) pairing bucketed, and a human signs off. |

> **Status in one line:** code-review **defects ✅ Fixed** (43/43 tests green); what's open is **by design** — the obligation mapping (PROVISIONAL, SME blockers Q1/Q3/Q4), the performance **deploy-gates** (⏭️ bucket the pairing before production volume), the synthetic-only tuning number (⏭️ re-confirm on real data), and **human sign-off ⛔ Pending**.

---

## 1. What was built

A deterministic, explainable detector (`ts001_wash_trade.py`, self-contained — does not import the repo `rules/`). It groups trades by `ubo_group_id` (Phase-1 UBO-only, per SME Q4), pairs opposing buy/sell legs in the same instrument within a lookback, and applies **off-market price as a NECESSARY early-continue condition** (DR-002), spread-normalised against the **time-weighted** spread. Safe-harbour (DR-003) and immaterial-notional (DR-004) pairs are suppressed; accounts on a stale UBO graph are excluded per-account with a data-quality warning (DR-005); the implied-match tier (DR-006) is **off** at launch (SME Q5). `detect_wash_trades(trades, ubo_links, market_snapshots, as_of_date, params=None)` returns a `DetectionResult` (`alerts`, `data_quality_warnings`, `suppressions`).

## 2. Requirements Traceability Matrix (RTM)

| Req | Logic (code) | Test(s) | Obligation |
|---|---|---|---|
| DR-001 pair opposing legs in same instrument, same UBO group, within lookback | pairing loop + `lookback_days` | `test_tp_cross_account_off_market_same_ubo`, `test_tp_single_account_both_sides`, QA lookback-boundary tests | MAR 12(1)(a) |
| DR-002 off-market price = NECESSARY condition (spread-normalised, mid-referenced, early-continue) | `_price_deviation_bps` ÷ `time_weighted_spread_bps` vs `off_market_spread_multiple` | QA spread-multiple boundary tests (at / just-over); `test_fp_at_market_not_alerted` | MAR 12(1)(a) |
| DR-003 suppress safe-harboured pairs | `_safe_harbour_reason` (`exempt_account_ids` register + `exempt_strategy_tags`) | QA register + `RISKLESS_PRINCIPAL` + non-exempt tests | MAR 12 (MM/riskless-principal) |
| DR-004 immaterial-notional floor | `min_pair_notional` (smaller-leg governs) | QA at/just-below floor | risk-appetite (no false signal) |
| DR-005 stale-UBO-graph → per-account exclude + DQ warning (not abort) | freshest-edge-per-account index | `test_multiple_ubo_edges_freshest_wins...`, QA partial-stale/one-over | coverage control |
| DR-006 implied-match tier OFF at launch | `enable_implied_match_tier=False` guard | `test_implied_match_tier_disabled` | SME Q5 |
| Alert carries obligation + keystone as **fields** | `WashTradeAlert.obligation_reference`, `.obligation_status`, `.ubo_group_id`, `.spread_normalised_deviation` | `test_tp_..._obligation_fields` | MAR 12(1)(a) traceability |
| Bad market data not silently dropped | `mid_price<=0` / `spread<=0` → DQ warning + continue | `test_non_positive_mid_is_dq_warning_not_silent_drop` | §4 audit/coverage |

## 3. Findings & disposition (consolidated across the review chain)

| ID | Source | Finding | Disposition |
|---|---|---|---|
| W1 / NOTE-001 | code-review + QA | Non-positive `mid` silently dropped (silent false-negative) | **✅ Fixed** — DQ guard added (mirrors the spread guard); test added; 43/43 green |
| M4 | code-review | Multiple UBO edges handled order-dependently | **✅ Fixed** — freshest-edge-per-account; test added |
| M3 | code-review | Safe-harbour **register** branch + boundaries untested | **✅ Covered** — QA suite added register / boundary tests |
| C1 | compliance | Old QA file tested a prior API + the rejected "abort" behaviour | **✅ Resolved** — QA suite regenerated against the delivered detector (31 tests) |
| C2 / W2 | compliance | Old delivery report + RTM described a non-existent API; stale dates | **✅ Resolved** — this report (delivered API, 2026-06-30) |
| W1 (compliance) | compliance | `.html` stale vs sources | **✅ Resolved** — all artifacts re-rendered at compile |
| M1 | code-review | `MARKET_MAKER` as a per-order tag vs designated-status register | **⏭️ Deferred** — SME Q2 decision (designated-status register vs per-order capacity); obligation PROVISIONAL |
| M2 | code-review | Off-market threshold reference frame (mid vs touch) | **⏭️ Deferred → tuning** — Theo's measured recommendation below; comment added; constant left pending real-data confirmation |
| PERF-F1 | performance | Unbucketed **O(B×S)** pairing — will not scale | **🔴 Open (deploy-gate)** — bucket by `(instrument, ubo_group_id)` before production volume |
| PERF-F2 | performance | Per-pair DQ-warning string blow-up | **🔴 Open (deploy-gate)** — dedupe by `(instrument, date)` |

**Disposition tally:** ✅ 6 Fixed/Resolved · 🔴 2 Open (performance deploy-gates) · ⏭️ 2 Deferred (SME Q2; real-data tuning) · ⚖️ 0 Accepted.

*Two kinds of "open":* there are **no unresolved defects** — the build is green. The Open items are **deploy-gates** (production-scale performance) and the Deferred items are decisions that correctly sit with the SME / real-data calibration, not the demo.

## 4. Tuning (measured ATL/BTL — Theo)

On a **seeded synthetic** labelled set (n=2,400; 300 wash / 2,100 legit; three liquidity segments), sweeping the off-market spread-multiple:

| Threshold (×spread from mid) | Precision 📊 | Recall 📊 | Note |
|---|---|---|---|
| 0.5 (the touch) | 0.535 | 0.917 | over-alerts — untenable |
| **0.75 (recommended)** | **0.842** | **0.837** | F1 0.839 (swept max) |
| 1.0 (placeholder) | 0.982 | 0.717 | misses 28% of genuine wash |

**Recommendation:** `off_market_spread_multiple = 0.75`, **mid-referenced**, single threshold across segments (spread-normalisation holds per-segment). **Honest caveat (📊→context):** measured on a *synthetic* distribution with an inflated 12.5% base rate — this validates the **method and the relative trade-off**, **not** a production number; the 0.75 knee must be re-confirmed on masked/real data before go-live. The constant is therefore **recorded as a recommendation, not hard-coded** (kept conservative; `tuning_date` to be stamped on real-data confirmation).

## 5. Developer handover

- **Build/run:** `pip install -r requirements-dev.txt`; `python -m pytest docs/demos/build-artifacts/test_ts001_wash_trade.py docs/demos/build-artifacts/test_ts001_qa.py -q` → **43 passed**.
- **Entry point:** `detect_wash_trades(trades, ubo_links, market_snapshots, as_of_date, params=None) -> DetectionResult`. Inputs: `Trade`, `UBOLink(account_id, ubo_group_id, graph_as_of_date)`, `MarketSnapshot(instrument, snapshot_date, mid_price, time_weighted_spread_bps)`. All `DetectionParams` have documented defaults with a rationale + `tuning_date` placeholder.
- **Known limitations / tech debt (must close before production):** (1) **PERF-F1/F2** — bucket the pairing + dedupe DQ warnings, then benchmark at 100K/1M (`pytest-benchmark`). (2) **Obligation mapping PROVISIONAL** — resolve SME Q1/Q3/Q4 (Legal), verify the `[TO-VERIFY]` citations against primary sources and add to the register. (3) **Threshold** — re-confirm 0.75 on real data. (4) **M1** — finalise the MM exemption taxonomy (SME Q2). (5) **At-market wash** is a known, accepted detection gap (DR-002) — candidate future scenario TS-003.
- **Change/ops artifacts** (change request, ops runbook, release notes) are not produced for a demo; templates exist for a real engagement.

## 6. Token usage (measured this run)

The Agent tool reports actual per-specialist usage (~4 chars/token, ±15%):

| Stage | Specialist | Tokens |
|---|---|---|
| Spec | business-analyst | ~25k |
| SME validation | trade-surveillance-sme | ~19k |
| Build + tests | rules-developer | ~78k |
| Code review | code-reviewer | ~51k |
| Independent QA | qa-engineer | ~95k |
| Compliance / DoD | compliance-reviewer | ~60k |
| Fix-loop | rules-developer | ~61k |
| Performance | performance-reviewer | ~30k |
| Tuning (measured) | tuning-analyst | ~83k |
| **Total (specialists)** | **9 agent-runs** | **~500k** |

> 💵 **Honest cost note.** At ~500k tokens this run cost roughly **$4-8** at list prices — **above** the ~150-180k / ~$3-6 *estimate* given at intake. The specialists ran deeper than the estimate assumed (QA wrote 31 independent tests; tuning built and ran a real labelled harness; the fix-loop re-ran both suites). The right read: the estimate was optimistic for a genuinely thorough, real (not faked) run. 🧾 *Rate-card framing:* this full reviewed-and-calibrated deliverable is the routine ~80% of a real engagement done in minutes — the human effort it stands in for is measured in days, not dollars.

## 7. Definition-of-Done status

| DoD item | Status | Evidence / gap |
|---|---|---|
| Traceable (RTM) | ✅ Met | §2 RTM maps DR → delivered code → test → obligation; obligation PROVISIONAL by design |
| Open questions dispositioned | ✅ Met | Spec + SME §5 disposition Q1-Q5 (3 🔴 go-live blockers reflected in the verdict) |
| Tested (TP + FP, pass) | ✅ Met | 43/43 green (dev 12 + independent QA 31), TP + FP controls |
| Independently QA'd | ✅ Met | `qa-handover.md` — `qa-engineer` (not the builder); fresh suite vs delivered API |
| Code-reviewed | ✅ Met | findings dispositioned (§3); W1/M4 fixed and re-run; analysers absent → logic findings 🧠 (re-run ruff/mypy/bandit before real sign-off) |
| Performance-reviewed | ✅ Met (gate open) | `performance-review.md`; O(B×S) = ⏭️ deploy-gate |
| Compliance-reviewed | ✅ Met | data-safety clean; citations grounded; obligation PROVISIONAL correct |
| Documented for handover | ✅ Met | §5 (matches the delivered API) |
| Engagement-summary email | ✅ Met | `engagement-summary-email.txt` (this run) |
| Distributable (.md + .html) | ✅ Met | all artifacts re-rendered at compile |
| Signed off (human) | ⛔ Pending | a demo cannot produce one — by design |

## Sign-off

| Role | Name | Decision | Date |
|---|---|---|---|
| Author / owner | Morgan (PM) | Demo-complete; not deployable (see verdict). | 2026-06-30 |
| `compliance-reviewer` (DoD gate) | Layla | Data-safety / citations / auditability met; C1/C2 resolved at compile. Re-gate on the open deploy-gates before production. | 2026-06-30 |
| Human approver (or `[IT team]`) | | | |
