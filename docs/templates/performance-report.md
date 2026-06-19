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
| # | Location | Issue | Evidence (timing / Big-O / profile) | Impact at target volume | Severity | Fix |
|---|----------|-------|--------------------------------------|-------------------------|----------|-----|
| 1 | `path:fn` | O(n²) join in hot path | 4.2s @ 100k rows; quadratic | ~hours @ 5M | 🔴 | hash-join / index |

## 4. Before / after (if a fix was profiled)
| Metric | Before | After |
|--------|--------|-------|
| Wall-clock @ <vol> | | |
| Peak memory | | |

## 5. Recommendation
What to change, in priority order, and the expected effect at target volume. Fixes route to
`rules-developer` / `cloud-architect` / `ml-engineer`, then re-profile.
