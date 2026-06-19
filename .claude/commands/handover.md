---
description: Produce the handover pack — dev + QA evidence, and the change/ops artifacts that feed your IT team's controls
argument-hint: <the delivered component / path>
---

Produce the **handover pack** for: **$ARGUMENTS** — so a real developer can maintain it, a
real QA team can accept it, and your IT team's existing controls have the evidence they need
(CLAUDE.md §6; gate: `docs/DEFINITION-OF-DONE.md`).

**Ownership boundary:** the team **drafts** these artifacts; **your IT team reviews, approves
and executes** (change approval, deployment, sign-off). Leave every approval/owner/contact
field blank and marked `[IT team]` — never self-certify a human control.

Ask the user which artifacts they need, then produce the relevant ones:

1. **QA handover (independent).** Route to **qa-engineer**: run the tests, capture exact
   commands, results and counts; assess coverage and **what is NOT covered**; list residual
   risk, defects, and items the QA team should re-verify. → `docs/templates/qa-handover.md`.
2. **Developer handover.** Route to the relevant builder (and `cloud-architect` for
   pipelines/infra): build/run/test, configuration, key design decisions (link ADRs), known
   limitations and tech debt, how to extend. → `docs/templates/developer-handover.md`.
3. **Change request / RFC package** (feeds your change control / CAB): summary, risk &
   impact, rollback, links to the test/review evidence; approvals left for `[IT team]`. →
   `docs/templates/change-request.md`.
4. **Operational runbook + release notes** (feed ops/support and your release process):
   monitoring/alerting (incl. alert-liveness), failure modes & recovery, escalation
   `[IT team]`; plus what changed. → `docs/templates/ops-runbook.md`, `release-notes.md`.
5. **Check the Definition of Done** and note any unmet items explicitly.
6. Save under `artifacts/` and render each to `.html` (`python -m scripts.render_html`).
   Cross-link the review, performance and RTM artifacts so the pack is self-contained.

Stop for human sign-off — real reviewers will read these, and approval/execution is theirs.
