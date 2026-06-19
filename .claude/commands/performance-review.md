---
description: Performance & scalability review with profiling evidence, against target data volumes
argument-hint: <path/glob or component to review> [at <volume/SLA> if known]
---

Run a **performance & scalability review** of: **$ARGUMENTS**

Drive **performance-reviewer** (CLAUDE.md §6):

1. Establish the **workload** — current and expected data volumes and the latency/throughput
   target. Ask the user if not stated (surveillance volumes are large; this changes the
   verdict). Batch or streaming?
2. **Profile/benchmark** the hot paths with the established tools for the stack (`cProfile`/
   `py-spy`/`scalene`, `JMH`/`async-profiler`, `Measure-Command`, `hyperfine`, `EXPLAIN`),
   on **synthetic data only** (§5). Measure — don't guess.
3. Assess **complexity, scaling, I/O/queries, concurrency, memory** and resource hygiene.
4. Produce a **performance report** (`docs/templates/performance-report.md`) with
   evidence-backed findings by severity, impact at target volume, and a scale verdict.

Fixes route to `rules-developer` / `cloud-architect` / `ml-engineer`, then **re-profile** to
show the before/after. Save `artifacts/PERF-<slug>.md` and render to `.html`
(`python -m scripts.render_html`).
