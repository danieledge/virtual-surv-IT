---
description: Static performance & scalability review against target data volumes (findings inferred; profiling is a future opt-in)
argument-hint: <path/glob or component to review> [at <volume/SLA> if known]
allowed-tools: Read, Grep, Glob, Bash(git diff:*), Bash(git status:*)
disable-model-invocation: true
---

Run a **performance & scalability review** of: **$ARGUMENTS**

**If no target was given, first ask the user where the code/component is** (path/glob, repo,
or paste it) and wait - don't assume a target.

**Put scope on a menu - ask the axes below in ONE `AskUserQuestion` call** (one screen), each a
distinct question with the stated header and `multiSelect` (tool limits: ≤4 questions per call,
≤4 options per question - "Other" is automatic):
- **Concerns** (header `Concerns`, **`multiSelect: true`**, default all): algorithmic
  complexity · memory & data-shape · I/O & queries · concurrency.
- **Mode** (header `Mode`, **`multiSelect: false`**): batch · streaming · both.
- **Target volume** (header `Volume`, **`multiSelect: false`** - the number changes the verdict;
  an exact figure goes through "Other"): < 1M events/day · 1-100M events/day · > 100M or
  streaming/real-time · not sure - assess at multiple scales.

> **Do NOT re-ask the fix-cycle (report / fix / loop) here** - `engage` already captured it (Q3);
> inherit that answer. Only ask it (batched in the same call) if this skill was invoked **directly**,
> not via `engage`. Deliverables like a handover pack are chosen separately. Legacy end-to-end
> overhaul is `/remediate`.
- **No execution-permission question here** - this review is static-only (see the STATIC-ONLY note
  below), so it never runs the code and nothing is asked about it. Measured profiling is a future
  opt-in that would need execution re-enabled via the consent flow.

> ⚙️ **STATIC-ONLY mode (CLAUDE.md §7).** This review does **not execute** the code - profilers
> and benchmarks *run* it, and the team is configured not to. So assess performance
> **statically** and mark findings **🧠 inferred** (or 📊 only for an explicit value *read* in the
> code). Measured profiling is a future opt-in that needs execution re-enabled via the consent
> flow; until then, **do not run anything** (the `guard-code-execution.py` hook enforces this).

Drive **performance-reviewer** (CLAUDE.md §6):

1. Establish the **workload** - current and expected data volumes and the latency/throughput
   target. Ask the user if not stated (surveillance volumes are large; this changes the
   verdict). Batch or streaming?
2. **Assess statically - run nothing.** Two kinds of finding:
   - **📊 Explicit coded costs (hunt these first)** - a literal `sleep`/fixed wait, polling
     interval, oversized timeout/retry back-off, blocking `WaitForExit`/`join`, hard-coded
     `LIMIT`/batch. The cost is *in the source*, so it's **measured** (quantify it: "sleep(5) →
     5s × N calls"); flag any that are unnecessary - usually the easiest, most certain win.
   - **🧠 Inferred** - complexity / data structures / `EXPLAIN` plan-only / concurrency / memory
     at target volume. Reasoned from structure; name the benchmark that would confirm each.
   Never present an inference as measured, but **do** claim 📊 for a delay you read in the code.
3. Assess **complexity, scaling, I/O/queries, concurrency, memory** and resource hygiene.
4. **State the basis of every claim** (this is what survives a developer's challenge):
   distinguish **📊 measured** - an explicit value in the code (a literal `sleep`, a fixed
   batch size, a declared timeout, `LIMIT n`) or a profiler/benchmark number you ran (cite it)
   - from **🧠 inferred** - reasoned from structure (e.g. "O(n²) nested scan") but not executed.
   Never present an inference as a measurement; for an inference, give the reasoning **and the
   benchmark that would confirm it**. If you couldn't measure, say so in tooling coverage rather
   than upgrading a guess to a fact.
5. **Morgan's challenge pass (opus).** Independently re-test each performance claim - is it
   measured or inferred? is the number real? - and downgrade unsupported assertions before
   presenting.
6. Produce the **performance report** (`docs/templates/performance-report.md`, shared
   `docs/review/output-format.md` conventions): a **scoreboard to the console**, full
   evidence-backed findings (with 📊/🧠 basis) in the **clean artifact**, impact at target
   volume, and a scale verdict.

Fixes route to `rules-developer` / `platform-engineer` / `ml-engineer`, then **re-profile** to
show the before/after. Save `artifacts/PERF-<slug>.md` and render to `.html`
(`python -m scripts.render_html`).

**Close - don't dead-end (CLAUDE.md §6).** Give the scale verdict (does it hold at target
volume?), then offer next steps with a recommendation - apply the fixes and re-profile, run a
full `/remediate` loop if the findings are deep, or produce a `/handover` pack - and wait for
the user's choice.
