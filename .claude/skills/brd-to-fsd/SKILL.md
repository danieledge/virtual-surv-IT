---
description: Turn a BRD into a Functional Specification (ISO/IEC/IEEE 29148 + Gherkin)
argument-hint: <path to the BRD, or paste it>
---

Under the PM (CLAUDE.md §6), turn the BRD into an FSD: **$ARGUMENTS**

1. Route to **requirements-analyst** to draft using `docs/templates/fsd.md`; have the
   relevant **SME** (`trade-surveillance-sme` / `tm-sme` / `comms-surveillance-sme`) review
   the detection logic and thresholds.
2. Each functional requirement (FSD-001, …) must **trace to a BRD id**. Write acceptance
   criteria in **Gherkin** (Given/When/Then), including true-positive and false-positive
   cases. Note data handling (synthetic/masked only — §5).
3. Update the **Requirements Traceability Matrix** (`docs/templates/rtm.md`) linking
   BRD → FSD.
4. Save `artifacts/FSD-<slug>.md` and render to `.html` (`python -m scripts.render_html`).

Hand off: the FSD feeds `/build-solution`.
