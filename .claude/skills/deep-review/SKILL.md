---
description: Detailed multi-dimension code review (bugs, security, architecture, impact) with confidence scoring
argument-hint: <path/glob, commit range, or nothing for the working diff>
disable-model-invocation: true
---

Run a **deep (detailed) code review** of: **$ARGUMENTS**.

**1. Confirm the target.** If none was given (no path/glob/commit range and no uncommitted
`git diff`), ask where the code is - a path/glob, repo/branch, commit range, or to paste it -
and wait. Don't review an assumed target.

**2. Put scope on a menu - ask, don't assume.** Ask the axes below **in ONE `AskUserQuestion`
call** (one screen, not separate round-trips); they stay distinct questions with the stated
`multiSelect` and header. **Hard tool limits: max 4 questions per call, max 4 options per
question** ("Other" is added automatically) - the constructions below are sized to fit; don't
un-bundle them back into a 7-option list:
- **Dimensions** (header `Dimensions`, **`multiSelect: false`** - four locked bundles; a bespoke
  mix goes through "Other", e.g. *"bugs + docs only"*):
  - **Full review** - all seven dimensions: bugs & logic · security · architecture ·
    language-specific · docs/comments · style & form · compliance/audit.
  - **Core** - 🐛 bugs & logic + 🔐 security + 🧰 language-specific. *For a plain utility script.*
  - **Core + quality** - Core plus 📐 architecture + 📝 docs/comments + 🔵 style & form.
  - **Core + compliance** - Core plus 📋 compliance/audit (§4/§5 trail).
  Run only what was picked - don't force a dimension the user didn't choose. (A *dimension* is one
  of these seven scope axes; a *lens* is one of the files in `docs/review/lenses/`. The mapping is
  not 1:1 - the router owns it.)
  - **Which to recommend is conditional, never a fixed default.** `compliance-reviewer` and
    regulatory-citation retrieval cost real tokens for a check that only matters when there is a
    §4/§5 trail to assess - don't spend them on general-purpose code by habit. **Recommend "Core +
    quality"** unless the target plausibly touches detection logic, regulated data, or the
    engagement is otherwise compliance-sensitive (ask if genuinely unclear from the target alone) -
    **then recommend "Full review"** instead. Right-sizing applies to dimensions the same way it
    applies to agent headcount.
- **Breadth** (header `Breadth`, **`multiSelect: false`**, exactly one): the working diff ·
  named files/glob · whole module · whole repo.
- **Mode** (header `Mode`, **`multiSelect: false`**): change review (filter pre-existing) **or**
  audit (keep pre-existing in scope).
- **Origin** (header `Origin`, **`multiSelect: false`**): was this **AI-assisted /
  "vibe-coded"**? (yes · mixed · no, hand-written). If **yes/mixed**, the report adds a
  **🧑‍💻 Prompting guidance** section (see `docs/review/output-format.md`): how a better prompt
  would have prevented the top findings, plus example prompts to reuse. (The reviewer also adds
  it if the findings clearly show vibe-coding.)

> **Do NOT re-ask the fix-cycle (report / fix / loop) here** - `engage` already captured it
> (its Q3) and it is the single source of truth; inherit that answer. If this skill was invoked
> **directly** (not via `engage`), ask it once (header `Fix-cycle`) - but the call is already at
> the 4-question cap, so in direct mode **swap Origin out of the first call** and ask it in the
> follow-up screen (with jurisdiction, if 📋 compliance is in scope; otherwise on its own or
> defaulted to "unknown - infer from the findings").

**If 📋 compliance/audit is among the dimensions**, ask **jurisdiction(s)** as a follow-up -
**`multiSelect: true`** (may operate in several) - or use the configured scope (CLAUDE.md §2 /
`docs/scope-and-stack.md`), so `compliance-reviewer` assesses only the **applicable** regime(s)
and states what's applicable vs not.

**3. Run the tiered review** (CLAUDE.md §6; method `docs/code-review-method.md`; lenses
`docs/review/lenses/`; router `docs/review/agent-router.md`):

> ⚠️ **Pip (`review-scorer`) is two of these steps, and both are delegations, not options.**
> Before dispatching anyone, state the pipeline roll-call in one line - *"Pip context → Ravi
> (×N, concurrent) → Pip score/filter → my challenge"* - the same out-loud discipline as the
> agent count (operating guide §Orchestration discipline). A fan-out plan that names the
> reviewers but not `review-scorer` is wrong; Found/Reported/Filtered counts self-scored by the
> reviewer are a defect to redo via Pip, not accept. Skipping the haiku helper saves nothing -
> it moves rote work onto the most expensive tier. (Live failure 2026-08-07: a full audit-depth
> review ran with zero `review-scorer` calls - the stated plan never named Pip, and the
> reviewers self-scored, noting it in their own packs.)

1. **Context** *(delegate to `review-scorer`, haiku)* - detect languages, list changed
   files/lines, check for CLAUDE.md, and select the minimal lens set per the router. This is
   rote work - run it on the cheap tier, not opus.
2. **Load lenses** progressively via the router - only those `review-scorer` selected.
3. **Analyse** - drive `code-reviewer` to run the loaded lenses in the topology the router defines
   (`docs/review/agent-router.md`, canonical for pipeline shape: today that is sequential focused
   passes inside `code-reviewer`, one lens at a time, with the trade-off stated there),
   **analysers first**: the available analysers run once, up front, before any lens pass, and
   their output grounds every pass - never an after-check on a review already written
   (`code-reviewer.md`'s tool table is the single source of truth for which tools and their
   caveats; **Semgrep** stays deliberately excluded, see there for why). Deep adds
   the **architecture** lens, **impact analysis**, and test/doc coverage. If the target is
   split into multiple independent component passes (operating guide §Orchestration
   discipline, `large_context_review_split`), dispatch them as **concurrent Task calls in one
   message** - never one per turn; a `performance-reviewer` pass on the same target joins the
   same message.
4. **Score & filter** *(delegate to `review-scorer`, haiku)* - apply the scoring rubric and
   produce the Found/Reported/Filtered counts (`docs/code-review-method.md`). This is the one
   genuinely sequential step in the fan-out (it depends on the packs existing), and it runs
   **even if a pass returned self-scored counts** - the reviewer applying the rubric to its own
   findings is not a substitute. Tag each finding's
   **evidence basis** (📊 measured / 🧠 inferred). **Never** filter regulated findings (secrets,
   PII/raw data §5, undocumented thresholds / broken traceability §4) - those stay with
   `code-reviewer`/`compliance-reviewer`, not the scorer.
5. For anything touching detection logic, hand to **compliance-reviewer** for the §4/§5 trail.
6. **Morgan's challenge pass** *(the orchestrator's own tier - sonnet by default, opus if
   configured for this engagement)* - a **spot-check, not a re-score**: the scorer already
   applied the rubric (step 4), and re-scoring everything on opus pays twice for the same
   judgement. Challenge the findings that *matter*: every 🔴 Critical, anything §4/§5-regulated,
   any finding whose evidence basis looks thin (🧠 presented as 📊), and a sample of the rest.
   Downgrade or drop what fails the challenge. You are a sceptic, not a relay - and not a second
   scorer.
   - **A documented, intentional bound is not a defect.** Before flagging a cap, bound, limit or
     threshold as a bug (e.g. "silently drops rows beyond N", "truncates to M"), check whether the
     code documents its rationale or the value is a by-design contract (a column cap set to the
     expected schema width, a threshold carrying a rationale + tuning date per §4). If it's
     intentional, don't raise it - drop the finding unless the rationale itself is wrong or the
     bound is genuinely silent/undocumented. Distinguish a *silent-truncation bug* (no rationale, no
     reconciliation, unbounded loss) from an *intended limit* (documented, expected).

**4. Present - findings pack → rendered report → scoreboard** (`docs/review/output-format.md`):
   1. `code-reviewer` already **wrote** the structured pack itself, directly, to
      `artifacts/<slug>/data/findings-<slug>.jsonl` (schema `docs/review/findings-schema.json`,
      exemplar `docs/review/gold-findings.jsonl` - it holds a Write grant scoped to exactly this
      path, mechanically enforced) - read it back for your challenge pass (step 6) rather than
      re-authoring it. **In a component-split review** (step 3.3) the passes returned findings
      as text instead and **you** wrote the merged pack yourself (operating guide §Orchestration
      discipline, the >8-finding Write-then-Edit rule) - challenge from that file the same way. **Only if your challenge pass downgrades or drops something** do you edit
      that same file to reflect the final (post-challenge) findings; otherwise leave it exactly as
      written.
   2. Run **`<python> -m scripts.check_artifacts --fix`** (allow-listed - no consent needed): it
      **validates** the pack (a missing field is `FINDINGS-INVALID` → fix the pack and re-run) and
      **renders** the canonical `artifacts/<slug>/REVIEW-<slug>.md` + `.html` (render is CLOSE-only, ADR-010: `set-status closing` first). The renderer owns the layout,
      so the report can't drift (no "5C"/C-word/inline). *(`<python>`: the `INTERPRETER=` word the step-0 probe printed, verbatim, never re-probed; direct invocation and plugin-mode paths: `.claude/skills/.shared/run-mode.md`)*
   3. Present a glanceable traffic-light **scoreboard to the console** from the rendered report; 🔵
      style & form is a non-blocking "consider in future" lane. (Fold into the consolidated
      `delivery-report.md` only if this review is part of a larger build/handover.)

   ⚠️ **MANDATORY - `developer_guidance` is not optional.** The pack's `developer_guidance` field
   must always be populated (2-4 constructive points on the author's coding style and what to
   improve next time; if the code is strong, say what's done well), **even on a clean pass** - the
   renderer emits it as the `## 🔵 Developer guidance` section. `check_artifacts` mechanically
   flags a missing or empty section as `FINDINGS-NO-DEV-GUIDANCE` (audit finding #2, 2026-07-30 -
   this used to be a prose-only reminder with no backstop), but don't rely on the gate to catch it.

**5. Close - don't dead-end.** Summarise from the scoreboard, then offer concrete next steps
with a recommendation - *"3 🔴, 5 🟠. I can fix the criticals, run `/remediate`, or produce a
handover pack. Which?"* - and offer to carry them out. **Always include a deep security audit
(`/security-audit`) among the options**, and **recommend** it when the review touched a
security-sensitive surface (auth, input parsing, DB access, external I/O, crypto, secrets, or
PII/data handling) or surfaced any security finding - it runs a dedicated OWASP ASVS / CWE +
threat-model pass beyond this review's inline security lens.

**The standard open and close apply (Definition of Done), even when this skill is invoked
directly.** Read `.claude/skills/.shared/engagement-bookends.md` and follow it: before delivering
the review above, the proportionate **Engagement Brief** (`.md` + `.html`, right-sized) written
together with its index row via `<python> -m scripts.engagement_state init` + `add-artifact`
(unless `/engage` already wrote them); at the end, the **engagement-summary email** as a `.txt`
signed off as Morgan, then `<python> -m scripts.check_artifacts --fix` and act on whatever it
still flags. A pause on unanswered user input is ⛔ BLOCKED said out loud, interim output takes
pass-scoped names, and `delivery-report.md` + the summary email are written at ✅ close only.

> For audit/regulatory sign-off with a fix→re-review loop, use `/audit-review` (which runs this
> deep review as its first step).
