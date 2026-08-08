---
description: Static performance & scalability review against target data volumes (findings inferred; profiling is a future opt-in)
argument-hint: <path/glob or component to review> [at <volume/SLA> if known]
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
> **statically** and mark findings **🧠 inferred** (or **📄 coded** for an explicit value *read* in
> the code - never 📊 measured: nothing ran). Measured profiling is a future opt-in that needs
> execution re-enabled via the consent
> flow; until then, **do not run anything** (the `guard-code-execution.py` hook enforces this).

Drive **performance-reviewer** (CLAUDE.md §6). When this review runs alongside independent
code-review passes in the same engagement (non-overlapping concern, no shared output), dispatch
the whole independent set per the operating guide's dispatch rule (no token cost, wall-clock
only). **Default path**: when `PARALLEL_DISPATCH_VIA_WORKFLOW=on` (the probe line; on by
default) and the `Workflow` tool is available this session, this pass is one
`{label, prompt, agentType: "performance-reviewer"}` spec in the same `args` array as the
code-review specs, run through the fixed script in
`.claude/skills/.shared/workflow-dispatch.md` verbatim - results arrive as a later background
task notification (say so plainly; two-turn flow in that shared file). **Fallback** (preference
off, tool absent, or the Workflow call failed): dispatch
the `performance-reviewer` call **in the same message as those passes** so they run
concurrently. **Live-tested
failure mode (2026-08-07/08, three attempts): stating this was not enough - the calls still
went out one per
turn, even once while narrating "dispatching... concurrently" in the same breath** - which is
why the Workflow path is the default. On the fallback, follow the
literal procedure: enumerate every independent call first, then emit all of them as Task
tool-uses in this ONE response, before reading any of their results:

1. Establish the **workload** - current and expected data volumes and the latency/throughput
   target. Ask the user if not stated (surveillance volumes are large; this changes the
   verdict). Batch or streaming?
2. **Assess statically - run nothing.** Two kinds of finding:
   - **📄 Explicit coded costs (hunt these first)** - a literal `sleep`/fixed wait, polling
     interval, oversized timeout/retry back-off, blocking `WaitForExit`/`join`, hard-coded
     `LIMIT`/batch. The cost is *in the source* - a hard fact, **📄 coded, not 📊 measured**
     (nothing ran; quantify it: "sleep(5) →
     5s × N calls"); flag any that are unnecessary - usually the easiest, most certain win.
   - **🧠 Inferred** - complexity / data structures / `EXPLAIN` plan-only / concurrency / memory
     at target volume. Reasoned from structure; name the benchmark that would confirm each.
   Never present an inference as measured, and never claim 📊 for a delay you read in the code -
   that is **📄 coded** (`docs/code-review-method.md` §Evidence basis).
3. Assess **complexity, scaling, I/O/queries, concurrency, memory** and resource hygiene.
4. **State the basis of every claim** (this is what survives a developer's challenge):
   distinguish **📄 coded** - an explicit value read in the code (a literal `sleep`, a fixed
   batch size, a declared timeout, `LIMIT n`) - and **📊 measured** - a profiler/benchmark
   number you ran (cite it; off in static mode)
   - from **🧠 inferred** - reasoned from structure (e.g. "O(n²) nested scan") but not executed.
   Never present an inference as a measurement; for an inference, give the reasoning **and the
   benchmark that would confirm it**. If you couldn't measure, say so in tooling coverage rather
   than upgrading a guess to a fact.
5. **Score & filter** *(delegate to `review-scorer`, haiku - after `performance-reviewer`'s pack
   exists: the scorer pass is the one genuinely sequential step, same as `/deep-review`)* - apply
   `docs/code-review-method.md`'s confidence rubric to the pack's candidate findings and produce
   the `Found N · Reported R · Filtered F` counts. Performance findings are not in the never-filter
   regulated list, so this is genuine filtering (unlike compliance/model-validation packs) - trim
   the pack to what scores above threshold (your edit, the same post-scoring edit `/deep-review`
   step 4 describes), and record the pass in the pack's envelope `scoring` field ("scored by
   review-scorer: Found N · Reported R · Filtered F") - `check_artifacts` flags a scored-kind
   pack without that record (`PACK-UNSCORED`). This is a delegation, not an option: name Pip in the
   fan-out plan before dispatching anyone, and counts self-scored by `performance-reviewer` are
   a defect to redo via `review-scorer`, not accept (live failure 2026-08-07 - see
   `/deep-review` step 3's roll-call rule, which applies here identically).
6. **Morgan's challenge pass (the orchestrator's own tier - sonnet by default, opus if
   configured for this engagement).** Independently re-test each performance claim - is it
   measured or inferred? is the number real? - and downgrade unsupported assertions before
   presenting.
7. Produce the **performance report** (`docs/templates/performance-report.md`, shared
   `docs/review/output-format.md` conventions): a **scoreboard to the console**, full
   evidence-backed findings (with 📊/📄/🧠 basis) in the **clean artifact**, impact at target
   volume, and a scale verdict.

Fixes route to `rules-developer` / `platform-engineer` / `ml-engineer`; any **before/after
profiling** requires the **execution-consent gate** (CLAUDE.md §7) - the default posture stays
static / 🧠 inferred, so don't promise measured before/after unless execution has been consented.
**The report is rendered from a findings pack, not hand-authored** (`docs/review/output-format.md`,
schema `docs/review/findings-schema.json`). `performance-reviewer` writes the findings itself,
directly, to `artifacts/<slug>/data/findings-performance-<slug>.jsonl` with **`"kind":
"performance"`** (the `performance-` prefix so it cannot collide with a code-review pack of the
same engagement; it holds a Write grant scoped to exactly this path, mechanically enforced): each finding the five named
fields (`basis` = 📊 measured / 📄 coded / 🧠 inferred as per the static-only rules above) **plus the
optional `current_cost` / `projected_cost` / `gain`** fields; workload/targets and the total saved
in `executive_summary`. Read it back rather than re-authoring it, then run
**`<python> -m scripts.check_artifacts --fix`** (allow-listed): it validates the pack and renders
the workspace's `artifacts/<slug>/PERF-<slug>.md` + `.html` (render is CLOSE-only, ADR-010: `set-status closing` first; the `kind` drives the `PERF-`
prefix and the per-finding cost/gain line). Don't hand-author or hand-edit the report.
(`<python>`: the `INTERPRETER=` word the step-0 probe printed, verbatim, never re-probed; direct invocation and plugin-mode paths: `.claude/skills/.shared/run-mode.md`).

**Close - don't dead-end (CLAUDE.md §6).** Give the scale verdict (does it hold at target
volume?), then offer next steps with a recommendation - apply the fixes (any before/after
profiling only via the execution-consent gate, CLAUDE.md §7), run a full `/remediate` loop if the
findings are deep, or produce a `/handover` pack - and wait for the user's choice.

**The standard open and close apply (Definition of Done), even when this skill is invoked
directly.** Read `.claude/skills/.shared/engagement-bookends.md` and follow it: before delivering
the review above, the proportionate **Engagement Brief** (`.md` + `.html`, right-sized) written
together with its index row via `<python> -m scripts.engagement_state init` + `add-artifact`
(unless `/engage` already wrote them); at the end, the **engagement-summary email** as a `.txt`
signed off as Morgan, then `<python> -m scripts.check_artifacts --fix` and act on whatever it
still flags. A pause on unanswered user input is ⛔ BLOCKED said out loud, interim output takes
pass-scoped names, and `delivery-report.md` + the summary email are written at ✅ close only.
