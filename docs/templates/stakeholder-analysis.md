# Stakeholder Analysis - <TITLE>

> Produced by `business-analyst` as part of elicitation (BABOK *Stakeholder Analysis*).
> Maps who is affected, who decides, and how we keep each party engaged. Authored in `.md`,
> rendered to `.html`. Names are illustrative - synthetic illustrations only, no real data (§5).

| | |
|---|---|
| **Document ID** | STK-<slug> |
| **Author / owner** | business-analyst / <user> |
| **Version / date** | 0.1 / <YYYY-MM-DD> |
| **Status** | draft / approved |
| **Related** | BRD-<slug> · RTM-<slug> |

## 1. Purpose & scope
One line on the engagement these stakeholders relate to, and the decision(s) they inform.

## 2. Stakeholder register
Each row is a role (not necessarily a named person). Influence and interest drive how much
attention they get; classify with the power/interest grid in §4.

| ID | Stakeholder / role | Area | Interest in outcome | Influence (H/M/L) | Needs & concerns |
|----|--------------------|------|---------------------|-------------------|------------------|
| STK-001 | Head of Surveillance | Compliance | <why they care> | H | <e.g. defensible coverage, audit trail> |
| STK-002 | MLRO / Financial Crime | AML | … | H | SAR/STR quality, FATF alignment |
| STK-003 | Surveillance analysts | Operations | … | M | alert quality, low false positives |
| STK-004 | Data engineering / IT | Platform | … | M | feed stability, retention, residency |
| STK-005 | Internal Audit / Model Risk | Assurance | … | M | traceability, SR 11-7 / SS1/23 evidence |
| STK-006 | Regulator (indirect) | External | … | H | demonstrable obligation coverage (§2) |

## 3. RACI
For each key activity/deliverable, mark exactly **one A**; R does the work, C is consulted
before, I is informed after.

| Activity / deliverable | R | A | C | I |
|------------------------|---|---|---|---|
| Requirements sign-off | business-analyst | Head of Surveillance | SMEs | Audit |
| Detection logic build | rules-developer | … | tm-sme / trade-sme | … |
| Threshold tuning | data-analyst | … | … | … |
| UAT & sign-off | qa-engineer | … | … | … |
| Deploy & operate | IT team | IT team | business-analyst | … |

## 4. Power / interest grid
Place each STK-ID in a quadrant - it sets the engagement posture.

| | **Low interest** | **High interest** |
|---|---|---|
| **High influence** | Keep satisfied - <IDs> | Manage closely - <IDs> |
| **Low influence** | Monitor - <IDs> | Keep informed - <IDs> |

## 5. Communication & engagement plan
| Stakeholder | What they need | Format | Cadence | Owner |
|-------------|----------------|--------|---------|-------|
| STK-001 | decisions & risks | brief + gate review | per gate | business-analyst |
| STK-003 | change impact | walkthrough | at UAT | business-analyst |

## 6. Open questions & assumptions
- <unknown stakeholder, undecided approver, assumed authority…> - the PM is clarifying.

> Traceability: stakeholder needs become BRD-### requirements; approvers here appear in the
> BRD §11 approvals and the RTM sign-off.
