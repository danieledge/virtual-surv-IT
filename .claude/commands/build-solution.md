---
description: Build an end-to-end solution from a set of requirements (orchestrator-workers)
argument-hint: <path to requirements pack / BRD+FSD, or describe it>
---

Under the PM (CLAUDE.md §6), deliver end to end from the requirements: **$ARGUMENTS**

Run the **orchestrator–workers** pattern, agile and iterative:

1. **Fill gaps flexibly.** If there's no BRD/FSD yet, run `/write-brd` then `/brd-to-fsd`
   first; skip whatever the user already provided.
2. **Decompose** the FSD into discrete, independently buildable units. For each unit chain:
   `rules-developer` (or `ml-engineer` + independent `model-validator` for models) →
   `code-reviewer` → `compliance-reviewer`. Independent units can run in parallel.
3. **Tests mandatory** for every unit — true-positive and false-positive cases, synthetic
   data only (§5), thresholds documented with rationale + date (§4).
4. **Maintain the RTM** (`docs/templates/rtm.md`): every requirement → code → test →
   obligation. A gap is a blocker — surface it to the user.
5. **Keep a status log**; return to the user at each gate with decisions and blockers.
6. **Deliver an audit pack** (RTM, review reports, scenario docs) under `artifacts/`, each as
   `.md` and rendered `.html` (`python -m scripts.render_html`). Confirm `pytest` passes.

Stop for human approval before anything that touches live systems.
