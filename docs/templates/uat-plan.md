# UAT Plan & Results — <TITLE>

> Produced by `business-analyst` with `qa-engineer`. User-acceptance test plan and evidence,
> derived from the acceptance criteria. Authored in `.md`, rendered to `.html`.
> **Synthetic or masked data only — no real PII/MNPI/secrets (§5).**

| | |
|---|---|
| **Document ID** | UAT-<slug> |
| **Author / owner** | business-analyst / <user> |
| **Version / date** | 0.1 / <YYYY-MM-DD> |
| **Status** | planned / in progress / signed off |
| **Related** | US-<slug> · REQ-<slug> · RTM-<slug> |

## 1. Scope & objectives
What is being accepted, by whom, against which requirements/stories. Note what is out of scope.

## 2. Entry / exit criteria
- **Entry:** build deployed to UAT; synthetic/masked test data loaded; acceptance criteria
  agreed; defect process in place.
- **Exit:** all Must scenarios pass; no open Critical/High defects; results & sign-off recorded;
  RTM updated.

## 3. Test data & environment
Environment, data set (synthetic/masked, §5), how to reset, any masking config used.

## 4. Test scenarios
One row per acceptance scenario; include true-positive (should alert) and false-positive
(should not alert) cases. Fill **Actual** and **Result** at execution.

| ID | Traces to | Scenario | Steps | Expected | Actual | Result (P/F) |
|----|-----------|----------|-------|----------|--------|--------------|
| UAT-001 | US-001 (TP) | abuse detected | <given/when> | alert type X raised | | |
| UAT-002 | US-001 (FP) | benign not flagged | … | no alert | | |
| UAT-003 | US-002 | <…> | … | … | | |

## 5. Defects log
| ID | Scenario | Severity (Crit/High/Med/Low) | Description | Status | Owner |
|----|----------|------------------------------|-------------|--------|-------|
| DEF-001 | UAT-00x | | | open / fixed / accepted | rules-developer |

## 6. Results summary
| Total | Passed | Failed | Blocked | Pass rate |
|-------|--------|--------|---------|-----------|
| | | | | % |

Plain-language outcome, residual risk, and **next-step options with a recommendation** (never a
dead end) — e.g. fix the failures, re-test, then proceed to handover.

## 7. Sign-off
| Role | Name | Decision (accept / accept w/ conditions / reject) | Date |
|------|------|---------------------------------------------------|------|
| Business owner | | | |
| qa-engineer (AI) | | | |
| Compliance | | | |

> Traceability: each UAT-### links back to a US-###/REQ-### and forward into the RTM test
> column; UAT sign-off is part of the Definition of Done (`docs/DEFINITION-OF-DONE.md`).
