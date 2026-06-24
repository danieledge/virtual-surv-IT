# Performance Review Report — <TITLE>

> Produced by `performance-reviewer`. **STATIC-ONLY for now** (CLAUDE.md §7): the team does not
> execute the reviewed code, so findings are **🧠 inferred** from structure/complexity (or 📊 only
> for an explicit value *read* in the code) — **not** profiled/benchmarked. The measured columns
> below apply only if/when execution is re-enabled via the consent flow. Authored in `.md`,
> rendered to `.html`.

| | |
|---|---|
| **Scope** | <code / pipeline reviewed> |
| **Date** | <YYYY-MM-DD> |
| **Verdict** | ✅ scales to target / ⚠️ scales with changes / ❌ will not scale |

## 1. Workload & targets
- **Data volume:** <current and expected, e.g. 5M orders/day, peak X/s>
- **Latency / throughput target:** <the detection SLA>
- **Mode:** batch / streaming / both

## 2. Method
Tools and how measurements were taken (`cProfile` / `py-spy` / `scalene` / `JMH` /
`async-profiler` / `Measure-Command` / `hyperfine` / `EXPLAIN` …), on synthetic data (§5).

## 3. Findings (evidence-backed)

**Basis** column is mandatory: **📊 measured** (profiler/benchmark number you ran, or an
explicit value in the code — cite it) vs **🧠 inferred** (reasoned from structure, not executed
— name the benchmark that would confirm it). Never present 🧠 as 📊.

| # | Location | Issue | Basis | Evidence (timing / Big-O / profile) | Impact at target volume | Severity | Fix |
|---|----------|-------|-------|--------------------------------------|-------------------------|----------|-----|
| 1 | `path:fn` | O(n²) join in hot path | 📊 measured | `cProfile`: 4.2s @ 100k rows; quadratic | ~hours @ 5M | 🔴 | hash-join / index |
| 2 | `worker.py:88` | fixed 5s sleep per call | 📊 measured | explicit `time.sleep(5)` in code | 5s × N calls | 🟠 | event/backoff |
| 3 | `match.py:40` | nested scan, not benchmarked | 🧠 inferred | O(n²) from structure — confirm with the stack's benchmark harness @ 100k | likely hours @ 5M | 🟡 | measure, then hash-join |

## 4. Potential gains summary (the headline a developer wants)

For **each** issue: the current cost, the projected cost after the fix, the **gain**, and —
crucially — **how that number was derived** (so it's defensible, not a guess). State the basis:
📊 **measured** (a real before/after benchmark, or an explicit coded value like `sleep(5)`) vs
🧠 **inferred** (a projection from complexity — give the model, e.g. "O(n²)→O(n): ~Nx at N rows").

| # | Issue | Current (basis) | Projected after fix | Gain | How derived |
|---|-------|-----------------|---------------------|------|-------------|
| 1 | O(n²) join | 📊 4.2s @ 100k (cProfile) | ~0.1s @ 100k | **~40×** @ 100k; hours→minutes @ 5M | measured baseline + hash-join is O(n); 5M figure extrapolated from the quadratic curve (🧠) |
| 2 | fixed 5s sleep | 📊 5s × N calls (explicit `sleep(5)`) | ~0s (event-driven) | **5s per call** removed | the delay is literal in code — exact, not modelled (📊) |
| 3 | nested scan | 🧠 not benchmarked | — | **unknown until measured** | inferred O(n²); **run the stack's benchmark harness @ 100k before claiming a number** |

**Total execution time saved (the headline number):** sum the per-issue savings into an
aggregate at the **target volume** — e.g. *"~Xs → ~Ys per run at 5M rows: **~Z saved (≈N%)**"* —
and split it **📊 measured vs 🧠 projected** so the total is honest (don't blend a benchmarked
saving with an un-benchmarked guess as if both are measured). Note any 🔴 not-yet-measured items
excluded from the total.

**Headline:** *"Fixes 1–2 (measured) remove ~Xs/run; fix 3 (projected, pending benchmark) a
further ~Ys. Total at 5M ≈ Z faster."*
Never present an inferred projection as a measured result; if a gain isn't yet measured, say so.

## 5. Before / after (where a fix was actually profiled)
| Metric | Before | After | Δ |
|--------|--------|-------|---|
| Wall-clock @ <vol> | | | |
| Peak memory | | | |

## 6. Recommendation
What to change, in priority order, with the expected effect at target volume (from §4). Fixes
route to `rules-developer` / `platform-engineer` / `ml-engineer`, then **re-profile to confirm the
projected gain became a measured one**.
