# Performance Review - TS-001 Wash Trade / Self-Match Detector (DEMO)

> **Document control** · ID `PERF-001` · Version `0.1` · Status `In review` · Classification `Internal` · Owner `performance-reviewer (Thabo)` · As-of `2026-06-30`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-06-30 | Thabo (performance-reviewer) | Static scalability review of the as-delivered detector |

**Review basis:** **Static only** (CLAUDE.md §7 - the detector was **not executed**, no profiler run). Every complexity/scaling finding is **🧠 inferred** from code structure; an explicitly coded value read from source is **📄 coded** (a fact, but not a run - never 📊 measured in static mode). Legend: severity 🔴 Critical · 🟠 High · 🟡 Medium · 🔵 Low/Info; evidence 📄 coded · 📊 measured · 🧠 inferred.

---

## 1. Workload & targets

- **Volume:** 1M+ confirmed fills/day (target); thousands of instruments; UBO groups of 10-100+ accounts.
- **Mode:** daily batch (`as_of_date` injected; date-granular).
- **SLA:** not stated; typical T+1 surveillance batch is sub-hour for alert generation.
- **Key driver:** all of the day's fills are loaded into flat `buys` / `sells` lists before the cross-product loop.

## 2. Tooling coverage

No profiler was run (static mode, §7), so there are **no 📊 measured time costs** - all timings below are **🧠 projected**. The benchmark that would confirm them: `pytest-benchmark` measuring `detect_wash_trades()` wall-clock + peak memory (`tracemalloc`) on synthetic sets of 10K / 100K / 1M trades, sweeping instrument count and UBO-group size.

## 3. Findings

### 🔴 Finding 1 - Unbucketed O(B×S) cross-product pairing (CRITICAL · 🧠 inferred)
`ts001_wash_trade.py` (pairing loop): the `for buy in buys: for sell in sells:` evaluates the full `B_total × S_total` cross-product. The instrument / UBO / lookback guards are `continue`s - they cut per-iteration work, **not** the iteration count. At 1M trades (≈500k buys × 500k sells) that is ~2.5×10¹¹ iterations; even with a 1,000-instrument universe pruning 99.9% of pairs, ~250M still reach the UBO check, and a single high-volume instrument gets no instrument-guard pruning at all. Large UBO groups compound it.
**Fix:** pre-bucket trades by `(instrument, ubo_group_id, side)` after the UBO-freshness phase, then pair *within* buckets → complexity drops to `Σ over buckets (B_k × S_k)`; structurally eliminates cross-instrument / cross-group pairs without visiting them. **Route:** `rules-developer`.

### 🟠 Finding 2 - Per-pair DQ-warning generation (HIGH · 🧠 inferred)
The three snapshot-quality checks `append` a formatted string **per pair**, not per `(instrument, date)`. One instrument with a missing snapshot and 500×500 pairs → ~250k warning strings (~30 MB) from a single gap; unbounded across instruments. Also a control-flow miss: on a missing snapshot the loop `continue`s to the next sell rather than breaking (no sell can resolve a snapshot keyed on the *buy*).
**Fix:** dedupe warnings by `(instrument, date)` via a `set`; break the inner loop on snapshot-miss; ideally hoist snapshot validation above the pairing loop. **Route:** `rules-developer`.

### 🟡 Finding 3 - Dual O(N) partition scan (LOW · 🧠 inferred)
Two separate comprehensions over `ordered` build `buys`/`sells` with 2N `account_id in ubo_index` lookups. A single conditional pass halves it. Sub-dominant while Finding 1 stands; **fold into the bucketing refactor**.

### 🔵 Finding 4 - Six-variable alert `reason` f-string per alert (INFO · 🧠 inferred)
Negligible at expected alert volumes (hundreds-low thousands/day). Note only if alert counts grow unexpectedly. No action.

## 4. Potential gains (🧠 projected - no profiler run)

| # | Issue | Current (🧠) | After fix (🧠) | Gain |
|---|---|---|---|---|
| 1 | Unbucketed O(B×S) | ~2.5×10¹¹ worst-case; ~250M in a 1,000-instrument case | `Σ (B_k×S_k)` per bucket (~25M in the worked example) | ~10× conservative; 1,000×+ in skewed distributions |
| 2 | Per-pair DQ warnings | up to ~250k string allocs per affected instrument | O(1) per `(instrument, date)` defect | up to ~250,000×; removes unbounded memory growth |
| 3 | Dual O(N) scan | 2N lookups | N lookups | constant factor (sub-dominant) |

**Headline (🧠 projected, static-only):** Finding 1 dominates by orders of magnitude; as written the unbucketed form will exhaust a realistic batch window before alerts complete. After Fixes 1-2 the rule is benchmarkable - run `pytest-benchmark` at 100K and 1M to convert these to 📊 measured numbers.

## 5. Before / after

Not available - static-only review, no profiler run (§7). Populate after the benchmark harness runs against the fixed code.

## 6. Recommendation

1. **[CRITICAL]** Bucket trades by `(instrument, ubo_group_id, side)` before pairing → `rules-developer`.
2. **[HIGH]** Dedupe DQ warnings by `(instrument, date)` + break on snapshot-miss (or hoist the check) → `rules-developer`.
3. **[LOW]** Fold the buy/sell partition into the bucketing refactor.
Then run `pytest-benchmark` at 100K / 1M to confirm the projected gains and establish the production baseline.

**Disposition tally:** ✅ 0 Fixed/Answered · 🔴 2 Open (F1 Critical, F2 High - production-scale deploy-gates) · ⏭️ 2 Deferred (F3 fold-in, F4 info) · ⚖️ 0 Accepted.

**Verdict: will not scale at target volume (🧠 inferred)** - a **deferred deploy-gate**, not a demo blocker. The detector is correct at demo scale; bucketing by `(instrument, ubo_group_id)` is the concrete, necessary fix before production volume.
