---
description: Produce the handover pack - dev + QA evidence, and the change/ops artifacts that feed your IT team's controls
argument-hint: <the delivered component / path>
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
6. Save under `artifacts/` and render to `.html` (`python -m scripts.render_html`).

Stop for human sign-off - real reviewers will read these, and approval/execution is theirs.
