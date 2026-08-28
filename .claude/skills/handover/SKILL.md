---
description: Produce the handover pack - dev + QA evidence, and the change/ops artifacts that feed your IT team's controls
argument-hint: <the delivered component / path>
disable-model-invocation: true
---

Produce the **handover pack** for: **$ARGUMENTS** - so a real developer can maintain it, a
real QA team can accept it, and your IT team's existing controls have the evidence they need
(CLAUDE.md §6; gate: `docs/DEFINITION-OF-DONE.md`).

**Ownership boundary:** the team **drafts** these artifacts; **your IT team reviews, approves
and executes** (change approval, deployment, sign-off). Leave every approval/owner/contact
field blank and marked `[IT team]` - never self-certify a human control.

**By default, produce ONE consolidated `docs/templates/delivery-report.md`** with the
sections below as headings - not separate files. Ask if the user instead wants standalone
artifacts (e.g. a separate change request to attach to a ticket); the standalone templates
named below are the building blocks.

**Both bookends apply, even when this skill is invoked directly.** Read
`.claude/skills/.shared/engagement-bookends.md`: follow its opening bookend (unless `/engage`
already wrote it) before step 1, and its **close sequence** (the state-machine commands -
`set-status closing` first, through `set-status closed` last) around steps 6-8 below - this
skill produces its own closing ARTIFACTS (the consolidated delivery report + summary email are
this engagement's version of the bookend's "delivery report + summary email"), but the
machine-readable state transitions are identical to every other closing skill and are not
restated here; follow the shared sequence exactly, slotting steps 6-7 in as the artifacts
written during the 🔒 closing window.

1. **QA evidence (independent).** Route to **qa-engineer**: run the tests, capture exact
   commands, results and counts; assess coverage and **what is NOT covered**; list residual
   risk, defects, and items the QA team should re-verify. → *QA* section (or `qa-handover.md`).
   Running the tests needs the execution-consent gate (CLAUDE.md §7); if the guard blocks, ask
   the user to grant consent (it is human-only) - never work around it.
2. **Developer handover.** Route to the relevant builder (and `platform-engineer` for
   pipelines/infra): build/run/test, configuration, key design decisions (link ADRs), known
   limitations and tech debt, how to extend. → *Developer handover* section (or `developer-handover.md`).
   **Quality bar - write it for a real developer who has never seen this code:** could they build,
   run and safely change it from this doc *alone*, with no tribal knowledge? No unexplained jargon,
   no "obvious" steps left out, every command copy-pastable. The PM (and `code-reviewer` /
   `compliance-reviewer` at the DoD gate) checks it clears that bar - **clear & usable, not just
   present.** Send it back to the builder if it wouldn't survive a cold read.
3. **Change request / RFC** (feeds your change control / CAB): summary, risk & impact,
   rollback, links to evidence; approvals left for `[IT team]`. → *Change & ops* section (or
   `change-request.md`).
4. **Ops runbook + release notes** (feed ops/support and release): monitoring/alerting (incl.
   alert-liveness), failure modes & recovery, escalation `[IT team]`; what changed. → *Change
   & ops* section (or `ops-runbook.md`, `release-notes.md`).
5. **Check the Definition of Done** and note any unmet items explicitly. **Include the findings
   disposition** (✅ fixed · 🔴 open · ⚖️ accepted · ⏭️ deferred) and reconcile it with the verdict -
   a pack that mentions blocking findings must make clear whether the rework addressed them or
   they're still open (🔴 Open / needs human developer review), never ambiguous.
6. **Enter the closing window**: `<python> -m scripts.engagement_state set-status closing
   --slug <slug>` - before writing the artifacts below, so they're legitimate close work in
   progress rather than appearing with no matching state transition. Then save under
   `VSIT/engagements/` and render to `.html` (`<python> -m scripts.render_html`). If the
   receiving team runs its own acceptance testing, include a **UAT plan**
   (`docs/templates/uat-plan.md`).
   (`<python>`: the `INTERPRETER=` word the step-0 probe printed, verbatim, never re-probed; direct invocation and plugin-mode paths: `.claude/skills/.shared/run-mode.md`)
7. **Engagement-summary email** (required closing artifact - Definition of Done): a short
   email-format cover note (`docs/templates/engagement-summary-email.md`) saved as a **`.txt` in
   `VSIT/engagements/`**, **signed off as Morgan** ("Hi," if you don't know the recipient's name). It's an
   email, so it stays `.txt` - not rendered to HTML.
8. **Run the mechanical DoD gate with auto-fix** - `<python> -m scripts.check_artifacts --fix`
   (auto-renders missing `.html` siblings and renames a mis-typed summary email to `.txt`), then act on anything it
   flags (missing `.html` siblings or a missing summary email). Then finish the state machine
   exactly as the bookends' close sequence describes: `resolve-outstanding`, `set-team`,
   `finalise-artifacts`, `set-footprint`, then `<python> -m scripts.engagement_state
   set-status closed --slug <slug>` - the actual gate that flips the engagement to ✅ and
   refuses on anything still wrong. **Without this, the engagement-state.json never leaves
   whatever status it was already in** - a delivered-looking pack with no matching state
   transition. Present the pack only after `set-status closed` succeeds.

Stop for human sign-off - real reviewers will read these, and approval/execution is theirs.
