---
description: Produce the handover pack — developer handover + QA test-evidence — for a delivery
argument-hint: <the delivered component / path>
---

Produce the **handover pack** for: **$ARGUMENTS** — so a real developer can maintain it and a
real QA team can accept it (CLAUDE.md §6; gate: `docs/DEFINITION-OF-DONE.md`).

1. **QA handover (independent).** Route to **qa-engineer**: run the tests, capture exact
   commands, results and counts; assess coverage and **what is NOT covered**; list residual
   risk, defects, and items the QA team should re-verify. Produce
   `docs/templates/qa-handover.md`.
2. **Developer handover.** Route to the relevant builder (and `cloud-architect` for
   pipelines/infra): how to build/run/test, configuration, key design decisions (link ADRs),
   known limitations and technical debt, and how to extend. Produce
   `docs/templates/developer-handover.md`.
3. **Check the Definition of Done** and note any unmet items explicitly.
4. Save both under `artifacts/` and render each to `.html`
   (`python -m scripts.render_html`). Include links to the review, performance and RTM
   artifacts so the pack is self-contained.

Stop for human sign-off — real reviewers will read these.
