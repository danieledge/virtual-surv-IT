# Performance Review Report — <TITLE>

> Produced by `performance-reviewer`. Findings are evidence-backed (profiled/benchmarked),
> not guesses. Authored in `.md`, rendered to `.html`.

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
| 3 | `match.py:40` | nested scan, not benchmarked | 🧠 inferred | O(n²) from structure — confirm with `pytest-benchmark` @ 100k | likely hours @ 5M | 🟡 | measure, then hash-join |

## 4. Before / after (if a fix was profiled)
| Metric | Before | After |
|--------|--------|-------|
| Wall-clock @ <vol> | | |
| Peak memory | | |

## 5. Recommendation
What to change, in priority order, and the expected effect at target volume. Fixes route to
`rules-developer` / `cloud-architect` / `ml-engineer`, then re-profile.
