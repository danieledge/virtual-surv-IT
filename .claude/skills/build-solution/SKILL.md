---
description: Build an end-to-end solution from a set of requirements (orchestrator-workers)
argument-hint: <path to requirements pack / BRD+FSD, or describe it>
disable-model-invocation: true
---

Under the PM (CLAUDE.md §6), deliver end to end from the requirements: **$ARGUMENTS**

Run the **orchestrator-workers** pattern, agile and iterative:

1. **Fill gaps flexibly.** If there's no BRD/FSD yet, run `/write-brd` then `/brd-to-fsd`
   first; skip whatever the user already provided.
2. **Decompose** the FSD into discrete, independently buildable units. **Route each unit to
   the right builder by type** (CLAUDE.md §6): detection logic → `rules-developer`; data
   pipeline / ETL / transformation or utility script / infra → `platform-engineer`; analytics
   / data-quality / reconciliation / reporting → `data-analyst`; ML → `ml-engineer` +
   independent `model-validator`. **Give each unit an explicit, non-overlapping brief**
   (objective · scope boundaries / what other units own · inputs/artifacts to read · expected
   output) so units don't duplicate or leave gaps. Then chain each through `code-reviewer` →
   `compliance-reviewer`. Independent units can run in parallel.
3. **Test independently** - `qa-engineer` (not the builder) designs and runs tests
   appropriate to the deliverable: true-positive and false-positive cases for detection
   logic; input/output, schema and edge-case tests for pipelines/transforms; idempotency/
   error-path tests for scripts. Synthetic data only (§5); thresholds documented (§4).
4. **Review** - `code-reviewer` (deep) and, where it processes data at volume,
   `performance-reviewer`; then `compliance-reviewer`. Loop fixes until no Critical remains.
5. **Maintain the RTM** (`docs/templates/rtm.md`): every requirement → code → test →
   obligation. A gap is a blocker - surface it to the user. Record significant design decisions
   as **ADRs** (`docs/templates/adr.md`).
6. **Keep a status log**; return to the user at each gate with decisions and blockers.
7. **Meet the Definition of Done** (`docs/DEFINITION-OF-DONE.md`) and run `/handover`.
   **By default deliver one consolidated Delivery Report** (`docs/templates/delivery-report.md`
   - RTM, review, performance, compliance, QA, handover, change/ops as sections); split into
   separate artifacts only if asked. Save under `artifacts/`, as `.md` and rendered `.html`.
   Confirm the **project's test suite** passes (use the target's framework - `pytest`, Pester,
   JUnit/ScalaTest, Jest, etc. - not an assumed one) and record the exact command. Running tests
   needs the execution-consent gate (CLAUDE.md §7); if the guard blocks, ask the user to grant it
   (consent is human-only).

Stop for human approval before anything that touches live systems.
