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
6. Save under `artifacts/` and render to `.html` (`<python> -m scripts.render_html`). If the
   receiving team runs its own acceptance testing, include a **UAT plan**
   (`docs/templates/uat-plan.md`).
   (`<python>`: resolve your interpreter - try python3, then python, then py - and in an
   installed-plugin session invoke the bundled `scripts/` copy by path; see the operating guide,
   "Run mode & the bundled scripts".)
7. **Engagement-summary email** (required closing artifact - Definition of Done): a short
   email-format cover note (`docs/templates/engagement-summary-email.md`) saved as a **`.txt` in
   `artifacts/`**, **signed off as Morgan** ("Hi," if you don't know the recipient's name). It's an
   email, so it stays `.txt` - not rendered to HTML.
8. **Run the mechanical DoD gate** - `<python> -m scripts.check_artifacts` - and fix anything it
   flags (missing `.html` siblings or a missing summary email) before presenting the pack.

Stop for human sign-off - real reviewers will read these, and approval/execution is theirs.
