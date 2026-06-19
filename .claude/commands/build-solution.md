---
description: Build an end-to-end solution from a set of requirements (orchestrator-workers)
argument-hint: <path to requirements pack / BRD+FSD, or describe it>
---

Under the PM (CLAUDE.md §6), deliver end to end from the requirements: **$ARGUMENTS**

Run the **orchestrator–workers** pattern, agile and iterative:

1. **Fill gaps flexibly.** If there's no BRD/FSD yet, run `/write-brd` then `/brd-to-fsd`
   first; skip whatever the user already provided.
2. **Decompose** the FSD into discrete, independently buildable units. **Route each unit to
   the right builder by type** (CLAUDE.md §6): detection logic → `rules-developer`; data
   pipeline / ETL / transformation or utility script / infra → `cloud-architect`; analytics
   / data-quality / reconciliation / reporting → `data-analyst`; ML → `ml-engineer` +
   independent `model-validator`. Then chain each unit through `code-reviewer` →
   `compliance-reviewer`. Independent units can run in parallel.
3. **Tests mandatory** for every unit, appropriate to the deliverable — true-positive and
   false-positive cases for detection logic; input/output, schema and edge-case tests for
   pipelines/transforms; idempotency/error-path tests for scripts. Synthetic data only (§5);
   any thresholds documented with rationale + date (§4).
4. **Maintain the RTM** (`docs/templates/rtm.md`): every requirement → code → test →
   obligation. A gap is a blocker — surface it to the user.
5. **Keep a status log**; return to the user at each gate with decisions and blockers.
6. **Deliver an audit pack** (RTM, review reports, scenario docs) under `artifacts/`, each as
   `.md` and rendered `.html` (`python -m scripts.render_html`). Confirm `pytest` passes.

Stop for human approval before anything that touches live systems.
