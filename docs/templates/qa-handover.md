# QA Handover - Test Evidence - <TITLE>

> Produced by `qa-engineer` (independent of the builder). Evidences what was tested, the
> results, what is **not** covered, and what the QA team should note or re-verify. Authored
> in `.md`, rendered to `.html`.
>
> **This is the "as-found" record - do NOT retro-edit it once defects are fixed.** QA evidence is
> an audit trail of *what was caught*; rewriting it to "look passed" destroys that. If a re-review
> loop fixes the findings, **preserve this doc as-found** and record the **resolved** state in the
> Delivery Report's findings disposition (the "after"). Tag the status line "(as-found)" and link
> the Delivery Report for the current state.

> **Document control** · ID `QAH-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Internal | Confidential` · Owner `<name / role>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

| | |
|---|---|
| **Deliverable** | <name> |
| **Version / commit** | <...> |
| **Traces to** | BRD-`<...>` / FSD-`<...>` / RTM-`<...>` |
| **Tested by** | qa-engineer |
| **Date** | <YYYY-MM-DD> |
| **Overall** | ready for QA / ready with notes / not ready |

## 1. Test execution summary
| Suite | Tests | Passed | Failed | Skipped |
|-------|-------|--------|--------|---------|
| unit | | | | |
| integration | | | | |
| performance | | | | |

**Acceptance threshold:** zero failed tests; line coverage >= `<floor - e.g. 80%>`; all
true-positive and false-positive scenario cases must pass. Any result below this threshold
constitutes a QA hold.

How to reproduce (exact commands - use the project's test framework, not an assumed one):
```bash
# Replace with the TARGET project's commands - do not assume pytest.
# e.g. Python: pytest · PowerShell: Invoke-Pester · JVM: mvn test / ./gradlew test · JS: npm test
<install deps for the target stack>
<run the target stack's test suite>

```

## 2. Environment & test data
- Environment / versions:
- Test data: **synthetic / masked only** (§5) - provenance and how it was generated.

## 3. Coverage
- **Covered:** scenarios, true-positive and false-positive cases, edge cases, error paths.
- **NOT covered (and why):** be explicit - unstated gaps are the dangerous ones.
- **Residual risk:** what could still go wrong in production.

## 4. Defects & known issues
| ID | Severity | Description | Status |
|----|----------|-------------|--------|

## 5. Items for the QA team to note / re-verify
Things a human reviewer should manually confirm (e.g. regulatory mapping, alert wording,
threshold rationale, anything not fully automatable).

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
