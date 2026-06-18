---
description: Drive a new detection scenario end to end — spec → SME review → implement → compliance review
argument-hint: <scenario name or regulatory requirement>
---

Stand up a new detection scenario for: **$ARGUMENTS**

You are the orchestrator (CLAUDE.md §6). Do **not** write detection logic yourself — route
each step to the right agent and chain them in this session:

1. **requirements-analyst** — turn "$ARGUMENTS" into a spec using
   `docs/templates/scenario-spec.md` (obligation, data, detection requirements,
   true-positive / false-positive acceptance criteria).
2. **Domain SME** — pick by domain: `trade-surveillance-sme`, `tm-sme`, or
   `comms-surveillance-sme`. Have them review the proposed detection logic and thresholds.
   (Advisory/read-only — they recommend, they do not edit.)
3. **rules-developer** — implement under `rules/` with synthetic tests under `tests/`
   (synthetic data only — §5), thresholds documented with rationale + tuning date (§4).
   If the detection is model-based, route to **ml-engineer** instead, then **model-validator**
   for independent validation before sign-off.
4. **compliance-reviewer** — check auditability, the alert→logic→obligation trace,
   thresholds rationale, secrets/PII, and test coverage.
5. Produce the scenario doc from `docs/templates/scenario-doc.md`.

Confirm `pytest` passes. Stop for human approval before anything that touches live systems.
