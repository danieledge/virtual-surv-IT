---
description: Performance & scalability review with profiling evidence, against target data volumes
argument-hint: <path/glob or component to review> [at <volume/SLA> if known]
allowed-tools: Read, Grep, Glob, Bash(git diff:*), Bash(git status:*)
---

Run a **performance & scalability review** of: **$ARGUMENTS**

**If no target was given, first ask the user where the code/component is** (path/glob, repo,
or paste it) and wait — don't assume a target.

**Put scope on a menu — ask via the question tool, each axis its own question with the stated
`multiSelect`:**
- **Concerns** — **`multiSelect: true`** (default all): algorithmic complexity · memory ·
  I/O & queries · concurrency · data-shape.
- **Mode** — **`multiSelect: false`**: batch · streaming · both.
- **After findings (fix-cycle)** — **`multiSelect: false`** (one): report only · apply fixes +
  re-profile · **fix → re-profile loop** until it scales. (Deliverables like a handover pack are
  chosen separately, not here. Legacy end-to-end overhaul is `/remediate`.)
- **Target data volume / SLA** — free-text ask (the number changes the verdict); offer it as a
  question with an "Other" path rather than burying it in prose.
- **Execution permission** — see the execution gate below; profiling **runs the code**, so this
  is required. Wait for answers.

> ⚙️ **STATIC-ONLY mode (CLAUDE.md §7).** This review does **not execute** the code — profilers
> and benchmarks *run* it, and the team is configured not to. So assess performance
> **statically** and mark findings **🧠 inferred** (or 📊 only for an explicit value *read* in the
> code). Measured profiling is a future opt-in that needs execution re-enabled via the consent
> flow; until then, **do not run anything** (the `guard-code-execution.py` hook enforces this).

Drive **performance-reviewer** (CLAUDE.md §6):

1. Establish the **workload** — current and expected data volumes and the latency/throughput
   target. Ask the user if not stated (surveillance volumes are large; this changes the
   verdict). Batch or streaming?
2. **Assess statically** — complexity / data structures / `EXPLAIN` plan-only / concurrency /
   memory at the target volume, plus explicit coded costs you can read. **Run nothing.** Findings
   are 🧠 inferred (name the benchmark that would confirm each), never presented as measured.
3. Assess **complexity, scaling, I/O/queries, concurrency, memory** and resource hygiene.
4. **State the basis of every claim** (this is what survives a developer's challenge):
   distinguish **📊 measured** — an explicit value in the code (a literal `sleep`, a fixed
   batch size, a declared timeout, `LIMIT n`) or a profiler/benchmark number you ran (cite it)
   — from **🧠 inferred** — reasoned from structure (e.g. "O(n²) nested scan") but not executed.
   Never present an inference as a measurement; for an inference, give the reasoning **and the
   benchmark that would confirm it**. If you couldn't measure, say so in tooling coverage rather
   than upgrading a guess to a fact.
5. **Morgan's challenge pass (opus).** Independently re-test each performance claim — is it
   measured or inferred? is the number real? — and downgrade unsupported assertions before
   presenting.
6. Produce the **performance report** (`docs/templates/performance-report.md`, shared
   `docs/review/output-format.md` conventions): a **scoreboard to the console**, full
   evidence-backed findings (with 📊/🧠 basis) in the **clean artifact**, impact at target
   volume, and a scale verdict.

Fixes route to `rules-developer` / `platform-engineer` / `ml-engineer`, then **re-profile** to
show the before/after. Save `artifacts/PERF-<slug>.md` and render to `.html`
(`python -m scripts.render_html`).

**Close — don't dead-end (CLAUDE.md §6).** Give the scale verdict (does it hold at target
volume?), then offer next steps with a recommendation — apply the fixes and re-profile, run a
full `/remediate` loop if the findings are deep, or produce a `/handover` pack — and wait for
the user's choice.
