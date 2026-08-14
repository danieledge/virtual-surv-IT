---
description: Review existing code for robustness and audit/regulatory defensibility (evaluator-optimizer loop)
argument-hint: <path/glob of code to review, or a commit range>
disable-model-invocation: true
---

Under the PM (CLAUDE.md §6), review for robustness and whether it would **stand up to audit
and regulatory scrutiny**: **$ARGUMENTS**

**If no target was given, first ask the user where the code is** (path/glob, repo/branch,
commit range, or paste it) and wait - don't review an assumed target.

**Fix-cycle (report / fix / loop):** if invoked **via `engage`**, inherit its answer (Q3) -
**don't re-ask**. If invoked **directly**, ask it once via the **question tool** (`multiSelect:
false`): report only · apply fixes · fix→re-review loop (the default here). **Confirm before
changing the user's code.** Don't blur in the handover pack - that's a **deliverable**, offered
from the artifact menu / at close, not mixed into this action question.

**Chained skills are dormant** - where a step routes to another workflow (`/deep-review`), read
`.claude/skills/<name>/SKILL.md` and follow it in this session, never the Skill tool
(`.claude/skills/.shared/run-mode.md`).

Run an **evaluator-optimizer loop**:

1. **code-reviewer** in **deep** mode (i.e. run `/deep-review`, telling it to inherit
   **Mode = audit** and the **compliance** dimension and not to re-ask those) - comprehensive review
   across the languages present, driving the standard analysers first - run once, up front,
   before the lens passes, their output grounding each pass (`code-reviewer.md`'s tool table is
   the single source of truth for which tools; **Semgrep** stays deliberately excluded, see
   there for why),
   citing OWASP ASVS / CWE / SEI CERT, with confidence scoring and filter transparency
   (`docs/code-review-method.md`). Audit mode: pre-existing issues stay in scope. The embedded
   `/deep-review` asks whether the code was **AI-assisted / vibe-coded**; if so, carry its
   **🧑‍💻 Prompting guidance** through into the audit report (see `docs/review/output-format.md`).
2. **compliance-reviewer** - use the **jurisdiction(s)** already established at step 1's
   `/deep-review` **intake** (asked and answered before any reviewer is dispatched; or CLAUDE.md
   §2 / `docs/scope-and-stack.md`); **only ask if still unknown** - don't re-ask what intake
   captured, and don't wait for `code-reviewer`'s output: jurisdiction is an intake answer, not a
   review result. It assesses against the **applicable** regime(s) and states
   what's applicable vs not. Then: auditability, the alert→logic→obligation trace, threshold
   rationale, secrets/PII, test coverage, and change control.

   **Steps 1 and 2 are one concurrent dispatch, not step-after-step.** The two reviews are
   independent - separate packs (`findings-<slug>.jsonl`, `findings-compliance-<slug>.jsonl`),
   merged only in the consolidation step below - so once intake is answered, dispatch
   `compliance-reviewer` together with step 1's `code-reviewer` pass(es) per the operating
   guide's dispatch rule. **No `review-scorer` context to forward here** (unlike
   `deep-review/SKILL.md`'s step 5, a sequential hand-off): step 1's embedded `/deep-review` runs
   its own Pip context call internally, concurrently with this dispatch, so nothing is available
   yet to forward when `compliance-reviewer` goes out - it derives its own file list via
   `git diff` this way, which is correct here, not a gap. **Default path**: when `PARALLEL_DISPATCH_VIA_WORKFLOW=on` (the probe
   line; on by default) and the `Workflow` tool is available this session, its
   `{label, prompt, agentType: "compliance-reviewer"}` spec joins the same `args` array as the
   `agentType: "code-reviewer"` spec(s), through the fixed script in
   `.claude/skills/.shared/workflow-dispatch.md` verbatim - the passes run concurrently in the
   background and the results arrive as a later task notification (say so plainly; two-turn flow
   in that shared file). **Fallback** (preference off, tool absent, or the Workflow call failed):
   all of them as Task tool-uses in **one message** - never one per turn - per the operating
   guide's literal procedure ("Dispatch independent calls concurrently").
3. If any **Critical/Warning** findings (and fixes are in scope), route fixes to the right
   builder, then **re-review** - and **fix everything you safely can in this pass, don't defer
   fixable work to a later sprint**. **The re-review pass needs fresh context, not the first
   pass's** (2026-08-12): the fixes just applied changed the files, so any file list/language
   breakdown forwarded into the first pass is now stale - re-run `review-scorer`'s context step
   (or let `code-reviewer` derive it itself) rather than re-forwarding what step 1/2 used. **Record every pass as it happens** in the Delivery
   Report's iteration log (§1a: journey strip + append-only hand-off row per review pass, fix
   routing and re-review - operating guide, Outcome discipline 5); earlier pass verdicts are
   never rewritten. Loop until everything fixable is fixed; the only items left
   are those needing a **human decision** (mark 🔴 Open / needs human review, not "deferred").
4. **Morgan's challenge pass** - same step, same scope and rationale as `deep-review/SKILL.md`
   step 6 (spot-check not re-score; every 🔴 Critical, §4/§5-regulated, thin-evidence and a
   sample of the rest; documented/intentional bounds aren't defects) - not repeated here.
5. Present in the shared `docs/review/output-format.md`: a clean traffic-light **scoreboard to
   the console**, with the full findings in the **clean artifact**. Give an explicit verdict
   (✅ audit-ready / ⚠️ conditional / ❌ not yet), standards cited, audit/regulatory checks, the
   🔵 style & form lane, a tooling-coverage section, **and - MANDATORY - a `## 🔵 Developer
   guidance - improving future code` section** (2-4 points, even on a clean pass;
   `check_artifacts` mechanically flags it missing/empty as `FINDINGS-NO-DEV-GUIDANCE`, but
   verify it's genuinely there before presenting, don't rely on the gate). Use the standalone
   clean review artifact by default; fold into the consolidated `delivery-report.md` only when
   audit is part of a larger handover.

6. **Independent read of the consolidated pack (Audit depth - the check on Morgan).** Before close,
   hand the finished audit artifact / `delivery-report` **itself** to **compliance-reviewer**
   (structurally independent of the PM - no Write/Edit) for a final read of the *synthesis*, not the
   code: does the **verdict follow from the findings register**? is any claim in the summary
   **unsupported by an artifact**? are dispositions, counts and evidence tags (📊/📄/🧠) internally
   consistent? This is the one pass Morgan cannot reliably do on its **own** output (ungrounded
   self-review is unreliable - `docs/internal/research-virtual-team.md`); fix or escalate what it flags before
   ✅. Right-sized: it reads the pack, it does not re-run the review.

**The report is rendered from a findings pack, not hand-authored** (`docs/review/output-format.md`).
Step 1's `/deep-review` already had `code-reviewer` write its own pack directly to
`artifacts/<slug>/data/findings-<slug>.jsonl`, and step 2's `compliance-reviewer` writes its own
alongside it (`findings-compliance-<slug>.jsonl`, both agents hold a Write grant scoped to exactly
their own path, mechanically enforced) - **read both back and consolidate**: merge
`compliance-reviewer`'s `findings[]` into the code-review pack (append; use its narrative fields
for the audit skeleton), then run **`<python> -m scripts.check_artifacts --fix`** - it validates the
pack (`FINDINGS-INVALID` → fix and re-run) and renders the workspace's `artifacts/<slug>/REVIEW-<slug>.md`
+ `.html` (render is CLOSE-only, ADR-010: `set-status closing` first). Don't hand-author or
hand-edit the rendered report.
(`<python>`: the `INTERPRETER=` word the step-0 probe printed, verbatim, never re-probed; direct invocation and plugin-mode paths: `.claude/skills/.shared/run-mode.md`)

**Close with a clear disposition - never leave it ambiguous.** State the verdict **and the
disposition of every finding**: ✅ fixed (what changed) · 🔴 open · ⚖️ accepted (rationale) ·
⏭️ deferred. A ❌/conditional verdict must **list the Open items explicitly** - don't just say
"failed". For anything with no straightforward fix, mark it **🔴 Open (needs human developer
review)** with the reason and options rather than guessing. Then offer concrete follow-ups with
a recommendation - e.g. *"Verdict: conditional - 2 fixed, 1 open (needs your call on the
threshold). I can fix the 2 remaining warnings, escalate the open one, or produce the handover
pack. Which next?"* **Among the follow-ups, offer a dedicated deep security audit
(`/security-audit`)** - and recommend it when the code touches a security-sensitive surface or the
audit surfaced any security finding; it goes deeper on security (OWASP ASVS / CWE + a threat model)
than this audit's security lens.

**The standard open and close apply (Definition of Done), even when this skill is invoked
directly.** Read `.claude/skills/.shared/engagement-bookends.md` and follow it: before delivering
the review above, the proportionate **Engagement Brief** (`.md` + `.html`, right-sized) written
together with its index row via `<python> -m scripts.engagement_state init` + `add-artifact`
(unless `/engage` already wrote them); at the end, the **engagement-summary email** as a `.txt`
signed off as Morgan, then `<python> -m scripts.check_artifacts --fix` and act on whatever it
still flags. A pause on unanswered user input is ⛔ BLOCKED said out loud, interim output takes
pass-scoped names, and `delivery-report.md` + the summary email are written at ✅ close only.
