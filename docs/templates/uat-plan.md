# UAT Plan & Results - <TITLE>

> Produced by `business-analyst` with `qa-engineer`. User-acceptance test plan and evidence,
> derived from the acceptance criteria. Authored in `.md`, rendered to `.html`.
> **Synthetic or masked data only - no real PII/MNPI/secrets (§5).**

> **Document control** · ID `UAT-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Internal | Confidential` · Owner `<name / role>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

**Related:** US-`<slug>` · REQ-`<slug>` · RTM-`<slug>`

## 1. Scope & objectives
What is being accepted, by whom, against which requirements/stories. Note what is out of scope.

## 2. Entry / exit criteria
- **Entry:** build deployed to UAT; synthetic/masked test data loaded; acceptance criteria
  agreed; defect process in place.
- **Exit:** all Must scenarios pass; no open Critical/High defects; results & sign-off recorded;
  RTM updated.

## 3. Test data & environment

### 3a. Environment representativeness
Confirm that the UAT environment is sufficiently representative of production before testing
begins. The sign-off line below is a gate - do not start execution without it.

| Dimension | UAT environment | Production equivalent | Acceptable? |
|-----------|----------------|----------------------|-------------|
| Data volume / profile | <e.g. 60 days synthetic data, volume-scaled to prod> | <prod volume> | Y / N |
| Feed completeness | <feeds connected: OMS, exec venue, …> | <prod feeds> | Y / N |
| Detection engine version | <version / commit> | <target deploy version> | Y / N |
| Infrastructure / latency | <cloud size / batch window> | <prod spec> | Y / N |

**Environment sign-off:** `<QA lead / IT owner>` confirms UAT environment is representative - __________ Date: __________

### 3b. Test data
Dataset used (synthetic/masked, §5), how to reset, masking config reference if applicable.

## 4. Regression scope
List the existing scenarios and functionality that must still pass after this change, in
addition to the new test scenarios below. Run these before sign-off to confirm no regressions.

| Regression area | Scope | Rationale |
|-----------------|-------|-----------|
| <e.g. existing spoofing scenario> | <UAT-R-001 to UAT-R-005> | <change touches shared alert-engine logic> |
| <e.g. alert-export pipeline> | <UAT-R-010> | <downstream feed unchanged> |

## 5. Test scenarios
One row per acceptance scenario; include true-positive (should alert) and false-positive
(should not alert) cases. Fill **Actual** and **Result** at execution.

| ID | Traces to | Scenario | Steps | Expected | Actual | Result (P/F) |
|----|-----------|----------|-------|----------|--------|--------------|
| UAT-001 | US-001 (TP) | abuse detected | <given/when> | alert type X raised | | |
| UAT-002 | US-001 (FP) | benign not flagged | … | no alert | | |
| UAT-003 | US-002 | <…> | … | … | | |

## 6. Defects log
| ID | Scenario | Severity (Crit/High/Med/Low) | Description | Status | Owner |
|----|----------|------------------------------|-------------|--------|-------|
| DEF-001 | UAT-00x | | | open / fixed / accepted | rules-developer |

## 7. Results summary
| Total | Passed | Failed | Blocked | Pass rate |
|-------|--------|--------|---------|-----------|
| | | | | % |

Plain-language outcome, residual risk, and **next-step options with a recommendation** (never a
dead end) - e.g. fix the failures, re-test, then proceed to handover.

## 8. Accepted with conditions
If sign-off is granted subject to conditions (e.g. a known defect accepted as low risk, or a
deferred regression fix), record it here. Each condition must have a named owner and a
resolution date.

| Condition | Rationale for acceptance | Owner | Resolution date | Tracking ref |
|-----------|--------------------------|-------|-----------------|--------------|
| <e.g. DEF-002 - low-severity edge case deferred> | <agreed risk is low; fix in next sprint> | <rules-developer> | <YYYY-MM-DD> | <Jira/ticket ref> |

## 9. Sign-off
| Role | Name | Decision (accept / accept w/ conditions / reject) | Date |
|------|------|---------------------------------------------------|------|
| Business owner | | | |
| qa-engineer (AI) | | | |
| Compliance | | | |

> Traceability: each UAT-### links back to a US-###/REQ-### and forward into the RTM test
> column; UAT sign-off is part of the Definition of Done (`docs/DEFINITION-OF-DONE.md`).
