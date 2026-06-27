# 🔁 Build demo: Run 1 vs Run 2 - reproducibility & knowledge-compounding

*We re-ran the **entire** build chain a second time, from scratch, on the same wash-trade scenario,
and compared. The result is the most important thing this demo can show: **the team learns** - the
lessons codified after Run 1 stopped Run 2 reintroducing the same defects, while the review chain
still earned its keep by finding new, subtler issues. [Back to demos](README.md).*

> 📖 Both runs are real: 8 agents each, synthetic data only, every metric below is the actual
> `subagent_tokens` / `duration_ms` reported by the Agent tool.

## The numbers (apples-to-apples - same scenario, same 8-stage chain)

| | Run 1 | Run 2 |
|---|---|---|
| Agents | 8 | 8 |
| Total tokens | ~182,400 | **~171,400** |
| Total agent-time | ~643s (~9 min wall-clock) | **~641s** |
| Build's own tests, first run | ❌ **true-positive FAILED** (non-deterministic wall-clock bug) | ✅ **3/3 passed first time** |
| Defects independent review found | **7** (incl. basic bugs) | **5 + 3 QA defects** - all *new / subtler* |
| Est. API cost (±2×) | ~$3.60 | **~$3.40** |

### Per-agent (tokens · runtime)

| Stage | Agent | Run 1 | Run 2 |
|---|---|---|---|
| Spec | business-analyst (Amara) | 16,580 · 55s | 17,329 · 65s |
| SME validation | trade-surveillance-sme (Camila) | 16,274 · 35s | 16,570 · 64s |
| Build | rules-developer (Mateo) | 19,859 · 63s | 22,745 · 94s |
| Code review | code-reviewer (Ravi) | 23,199 · 34s | 21,036 · 48s |
| QA | qa-engineer (Linh) | 32,924 · 244s | 25,808 · 151s |
| Compliance | compliance-reviewer (Layla) | 31,077 · 65s | 21,932 · 62s |
| Calibration | tuning-analyst (Theo) | 24,197 · 105s | 29,973 · 115s |
| Performance | performance-reviewer (Thabo) | 18,290 · 42s | 16,009 · 42s |
| **Total** | **8 agents** | **~182,400 · 643s** | **~171,400 · 641s** |

Reproducible: the totals land within ~6% on tokens and ~0.3% on time. The chain is stable.

## What changed - and why it matters

### 1. The codified house-rules prevented regression (the big one)
After Run 1, the 7 defects review caught were turned into **house-rules** and **templates**. In Run 2,
Mateo **read `house-rules.md`** and pre-applied them. The result: **not one of Run 1's defects recurred.**

| Run 1 defect (found by review, then fixed + codified) | Run 2 outcome |
|---|---|
| Wall-clock time-bug → true-positive test failed | ✅ Injected `as_of_date` from the start; tests passed first run |
| Off-market checked the **sell leg only** (false-negative) | ✅ Uses both legs' average vs mid |
| UBO staleness **off-by-one** (`<` vs `<=`) | ✅ Freshness gate correct; QA tested the boundary - no off-by-one |
| Alert **lacked the obligation citation** (broke its own AC) | ✅ `obligation` + `ubo_group_id` as typed fields from the start |
| Build→spec divergence ("convergence" vs "off-market") | ✅ Off-market-as-necessary implemented directly |

The build that needed **7 fixes** in Run 1 came out **clean** in Run 2. That is the knowledge-compounds
loop ([`docs/house-rules.md`](../house-rules.md)) working - not narrated, measured.

### 2. The review chain is *not* a rubber stamp - it found new value
With the old bugs gone, the reviewers found **different, subtler** issues - exactly what an adversarial
chain should do:
- **Ravi (code):** same-account self-match silently excluded (a coverage gap); off-market test and the
  reported deviation computed from two sources of truth; snapshot-date not recorded (auditability).
- **Linh (QA):** wrote 14 extra tests (17/17 pass); **DEF-001** missing-market-snapshot silently drops
  pairs (no observability) - the same *theme* as Run 1's missing-mid, caught again; quantity never matched.
- **Layla (compliance):** the standout - the obligation is a **hard-coded literal that looks finalised**,
  yet the SME flagged jurisdiction (Q1) and connected-party scope (Q3/Q4) as go-live blockers, so the
  alert **asserts a regulatory trace that does not yet exist.** The most dangerous failure mode for a
  surveillance control - and *only surfaced because the basic bugs were already gone.*
- **Theo (tuning):** spread-normalised off-market threshold (not flat bps); a **required `min_notional`**.

### 3. Knowledge kept compounding
Camila, Mateo **and** Theo each **cited house-rules** in Run 2. Three *new* lessons emerged for the next
round: (a) reference the obligation via an **RTM/decision-log ID, not an inline literal**; (b)
**spread-normalised** off-market threshold; (c) **`min_notional` is a required parameter**. Run 2's review
becomes Run 3's house-rules - the same loop, one turn further on.

## The honest read
Neither run is "better" - they show different things, and that's the point:
- **Run 1** is the more dramatic *teaching* transcript: you watch the chain **catch a real bug** (a test
  failing live) and fix it. The fix→re-review loop in full.
- **Run 2** is the *maturity* proof: the same team, now carrying its lessons, **doesn't make those
  mistakes again** - and the reviewers still find new, harder issues.

Together they demonstrate the thing that actually matters: **a team that gets better each time it runs.**
