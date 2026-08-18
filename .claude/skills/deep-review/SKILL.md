---
description: Detailed multi-dimension code review (bugs, security, architecture, impact) with confidence scoring
argument-hint: <path/glob, commit range, or nothing for the working diff>
disable-model-invocation: true
---

Run a **deep (detailed) code review** of: **$ARGUMENTS**.

**1. Confirm the target.** If none was given (no path/glob/commit range and no uncommitted
`git diff`), ask where the code is - a path/glob, repo/branch, commit range, or to paste it -
and wait. Don't review an assumed target.

**2. Derive the fine scope - state it, don't re-ask it.** The go-ahead gate must be FINAL:
the brief carries the derived scope and the gate approves it - post-gate scope questions are
a defect (live 2026-08-17; incident-log #33). Derive:
- **Dimensions** from depth + target: Deep → **Core + quality** (bugs & logic · security ·
  language-specific · architecture · docs/comments · style & form) unless the target plausibly
  touches detection logic, regulated data or the engagement is compliance-sensitive → **Full
  review** (adds 📋 compliance/audit, §4/§5 trail). Audit depth always Full. A user-named
  bespoke mix always wins. (`compliance-reviewer` and citation retrieval cost real tokens -
  never spend them on general-purpose code by habit.)
- **Target** the same way (no standalone "what should I review?" turn - user request
  2026-08-17): an uncommitted/branch diff → the diff; a path/module named in the request → that.
  Only when NEITHER exists is the target a real question - LOCKED construction in
  `engage`'s `references/target-menu.md` (guard-enforced; "Whole working directory" is
  the review-everything option) - riding `engage`'s 0a intake batch (the Work-type slot),
  or direct-mode's one batched call below; never its own screen.
- **Breadth** from the briefed scope (the diff · named files · module · repo - whatever the
  brief already says; never widen it here).
- **Mode** from depth: Audit → keep pre-existing in scope; otherwise change-focused (or
  whole-target when there is no diff, per the Quick rule's scope logic).
- **Origin** is inherited from `engage`'s review menu (its Q4) - if it says AI-assisted/mixed,
  the report adds the **🧑‍💻 Prompting guidance** section (`docs/review/output-format.md`);
  the reviewer also adds it unprompted when the findings clearly show vibe-coding.

Write one scope line into the brief ("Deep · Core + quality · whole repo · change-focused ·
origin: mixed") - the go-ahead gate is where the user adjusts it. **Ask a scope question ONLY
when genuinely ambiguous** (conflicting signals about compliance-sensitivity, an unclear
target) - one question, not a screen of axes. Invoked **directly** (not via `engage`): the
review menu never ran, so ask ONE batched call first - Fix-cycle + Origin (+ jurisdiction if
📋 is in scope) - then derive the rest exactly as above.

**If 📋 compliance/audit is among the dimensions**, ask **jurisdiction(s)** as a follow-up -
**`multiSelect: true`** (may operate in several) - or use the configured scope (CLAUDE.md §2 /
`docs/scope-and-stack.md`), so `compliance-reviewer` assesses only the **applicable** regime(s)
and states what's applicable vs not.

**Quick runs in-session - no fan-out (2026-08-17 cost decision).** When the chosen depth is
**Quick**, read `references/quick.md` (this skill's folder; plugin mode under `$PLUGIN_ROOT`)
and follow it INSTEAD of everything below - it is the complete Quick recipe (in-session,
diff-scoped, analysers + inline lenses, self-scored with the honest label). None of the
pipeline below applies at Quick depth.

**3. Run the tiered review** (CLAUDE.md §6; method `docs/code-review-method.md`; lenses
`docs/review/lenses/`; router `docs/review/agent-router.md`):

**Consolidate by default - splitting is the exception (2026-08-17 cost review).** One
`code-reviewer` dispatch per component runs ALL selected lenses sequentially inside it (the
router's canonical topology: the code is read into context once and every lens reuses it).
**Security is a lens, never its own pass, whenever a code review is already running** -
a chained `/security-audit` folds its focus into the same pass's lens set instead of
dispatching more agents (6 passes went out where the topology prices 3, roughly doubling the
cost - live 2026-08-16/17; incident-log #17).
Split into per-component passes ONLY when `LARGE_CONTEXT_REVIEW_SPLIT=on`, the target
genuinely exceeds one context, or corporate-proxy timeouts have already bitten this session
(the split's original purpose, and it demonstrably helps there) - name which reason applies
in the sizing line, and state the resulting pass count before dispatching.

**Tier by evidence need (2026-08-17 decision):** **Deep defaults to `model: sonnet`** on the
dispatch (its findings are independently scored and PM-challenged, and the pack is not the
final audit word), with an **opus opt-in stated in the priced menu line** for
high-stakes-but-not-audit work; **Audit always dispatches opus** - there the pack IS the
evidence and the final specialist word (agent-design §2's rationale). If the dispatch path in
use cannot override the agent's frontmatter model, say so and proceed on the frontmatter tier
rather than silently absorbing the cost difference.

**Deep reads a MAP, not the repo:** widen scope beyond the diff only via a targeted
related-file map built once up front - importers of the changed files, their imports, and
their test files - and read only what the map names (turingmind's Phase-1C pattern). Never
browse the codebase breadth-first from inside a review pass. **When `docs/codebase-map.md`
exists, it is that map already** (dispatched reviewers have re-crawled a mapped repo - live
2026-08-17; incident-log #16): the dispatch brief carries the in-scope FILE LIST plus the
map's PATH with "read it for wider context - do not enumerate the repo" - **point, never paste**
(the map body in N briefs is N times orchestrator output tokens; an agent-side Read is
cheap input, and a diff-scoped pass needs no map read at all). Search discipline applies throughout (operating guide, orchestration §Exploration discipline): 2-3 miss budget, small files whole, batched lookups, grep for symbols only. Trust it only after a cheap
staleness look (map's stated date vs `git log -1 --format=%ci`); if drifted, refresh just
the target directories with `git ls-files <dir>` - never a whole-repo walk.

> ⚠️ **Pip (`review-scorer`) is two of these steps, and both are delegations, not options -**
> **including doing the step yourself "to save a turn."** Before dispatching anyone, state the
> pipeline roll-call in one line - *"Pip context → Ravi (×N, concurrent) → Pip score/filter →
> my challenge"* - the same out-loud discipline as the agent count (operating guide
> §Orchestration discipline). A fan-out plan that names the reviewers but not `review-scorer`
> is wrong; Found/Reported/Filtered counts self-scored by the reviewer are a defect to redo via
> Pip, not accept. Skipping the haiku helper saves nothing - it moves rote work onto the most
> expensive tier. This rule failed live twice in different shapes despite being documented -
> once wholesale (no Pip at all, reviewers self-scored) and once one step at a time (scoring
> delegated, context done inline) - so it holds per STEP, not per plan (2026-08-07 and
> 2026-08-10; incident-log #8).

1. **Context** - a real `Task` tool call, `subagent_type: review-scorer` (haiku), not the
   orchestrator doing the equivalent work itself - detect languages, list changed files/lines,
   check for CLAUDE.md, and select the minimal lens set per the router. This is rote work - run
   it on the cheap tier, not opus, and not inline on whatever tier the orchestrator is already
   running.
2. **Load lenses** progressively via the router - only those `review-scorer` selected. **Forward
   Pip's context, not just the lens list** - include the file list and language breakdown Pip
   already detected verbatim in `code-reviewer`'s dispatch prompt, **labeled `Context from
   review-scorer:` right before it** (so it reads as a fixed, recognizable marker rather than
   something the reviewer has to infer from unlabeled brief text), instead of re-running
   `git diff`/re-deriving language grouping for context that already exists (2026-08-12:
   `code-reviewer.md`'s own step 1 is written to look for that exact label, and to fall back to
   deriving it itself only when the label isn't there - e.g. a lightweight path with no
   `review-scorer` call). **Not `performance-reviewer`** - it never derived a file list via
   `git diff` in the first place (its own step 1 establishes workload characteristics, not file/
   language detection), so there's nothing there for it to reuse.
3. **Analyse** - drive `code-reviewer` to run the loaded lenses in the topology the router defines
   (`docs/review/agent-router.md`, canonical for pipeline shape: today that is sequential focused
   passes inside `code-reviewer`, one lens at a time, with the trade-off stated there),
   **analysers first**: the available analysers run once, up front, before any lens pass, and
   their output grounds every pass - never an after-check on a review already written
   (`code-reviewer.md`'s tool table is the single source of truth for which tools and their
   caveats; **Semgrep** stays deliberately excluded, see there for why). Deep adds
   the **architecture** lens, **impact analysis**, and test/doc coverage. If the target is
   split into multiple independent component passes (operating guide §Orchestration
   discipline, `large_context_review_split`), dispatch the set per the dispatch rule's
   **default path**: when `PARALLEL_DISPATCH_VIA_WORKFLOW=on` (the probe line; on by default)
   and the `Workflow` tool is available this session, use the fixed script in
   `.claude/skills/.shared/workflow-dispatch.md` verbatim - one `{label, prompt, agentType}`
   spec per pass, `agentType: "code-reviewer"`, a `performance-reviewer` pass on the same
   target joins the same `args` array; the passes run concurrently in the background and the
   results arrive as a later task notification (say so plainly - the two-turn flow is in that
   shared file). **Each pass's prompt must instruct it to write its own findings pack directly**
   to its own component-qualified path (operating guide §Orchestration discipline -
   `findings-<slug>-<component>.jsonl`, never the shared canonical name) and return only a short
   confirmation, not its findings as text - see `.claude/skills/.shared/workflow-dispatch.md`
   for the exact convention.
   **Fallback** (preference off, tool absent, or the Workflow call failed):
   dispatch them as **concurrent Task calls in one message** - never one per turn; the
   `performance-reviewer` pass joins the same message. **Prose alone failed this rule three
   times running - the calls still went out one per turn every time - which is why the
   Workflow path is the default** (2026-08-07/08; incident-log #7). On the fallback, follow
   the operating guide's literal procedure: list every independent call first, then emit all
   of them as Task tool-uses in this ONE response before reading any of their results. N
   independent passes = N Task tool-uses in this turn, not N turns.
4. **Score & filter** *(delegate to `review-scorer`, haiku)* - apply the scoring rubric and
   produce the Found/Reported/Filtered counts (`docs/code-review-method.md`). This is the one
   genuinely sequential step in the fan-out (it depends on the packs existing), and it runs
   **even if a pass returned self-scored counts** - the reviewer applying the rubric to its own
   findings is not a substitute. Once the scorer's numbers are applied, **you (Morgan) record
   the pass in each pack's envelope `scoring` field** ("scored by review-scorer: Found N ·
   Reported R · Filtered F") **right here, as part of this step - before the challenge pass,
   not as part of it.** Pip has no Write/Edit of its own (advisory, judgement stays with the
   reviewers and you), and the reviewer that wrote the pack has already returned by now, so
   this bookkeeping edit is yours to make regardless of whether your later challenge pass
   changes anything - `check_artifacts` mechanically flags a scored-kind pack without that
   record (`PACK-UNSCORED`), and a self-scoring note there does not clear it. Tag each finding's
   **evidence basis** (📊 measured / 🧠 inferred). **Never** filter regulated findings (secrets,
   PII/raw data §5, undocumented thresholds / broken traceability §4) - those stay with
   `code-reviewer`/`compliance-reviewer`, not the scorer.
5. For anything touching detection logic, hand to **compliance-reviewer** for the §4/§5 trail -
   **forward Pip's file list here too, same `Context from review-scorer:` label as step 2**
   (this dispatch is sequential, after step 1's Pip call has returned;
   `compliance-reviewer.md`'s own step 2 is written to look for that label), **and state the
   intake jurisdiction(s) in the same brief** ("Jurisdiction(s): ...") - its step 1 consumes a
   brief-stated jurisdiction without re-deriving it from `docs/scope-and-stack.md`.
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
      re-authoring it. **In a component-split review** (step 3.3) each pass instead wrote its own
      pack directly to its own component-qualified path - read those small packs back (`Read`
      each one, no reconstruction from prose needed) and **you** merge them into the canonical
      `findings-<slug>.jsonl` yourself (operating guide §Orchestration discipline, the
      >8-finding Write-then-Edit rule) - challenge from that merged file the same way. The
      `scoring` envelope edit (step 4) already happened before you get here, regardless of
      what the challenge pass does - what's carved out below is FINDING CONTENT specifically.
      **Only if your challenge pass downgrades or drops something** do you edit
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
   flags a missing or empty section as `FINDINGS-NO-DEV-GUIDANCE`, but don't rely on the gate to
   catch it.

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
