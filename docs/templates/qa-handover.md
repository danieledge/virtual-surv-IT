# QA Handover - Test Evidence - <TITLE>

> Produced by `qa-engineer` (independent of the builder). Evidences what was tested, the
> results, what is **not** covered, and what the QA team should note or re-verify. Authored
> in `.md`, rendered to `.html`.
>
> **Critique standard for this document** (operating guide, Outcome discipline 6):
> ISO/IEC 29119-shaped completeness - a reader can determine **what was tested** (scope +
> cycles), **against what** (environment, data provenance), **with what result** (per-pass
> verdicts, defect lifecycle), **what was NOT tested and why**, and **what risk remains**.
> A handover missing any of the five goes back, not forward.
>
> **This is the "as-found" record - do NOT retro-edit it once defects are fixed.** QA evidence is
> an audit trail of *what was caught*; rewriting it to "look passed" destroys that. If a re-review
> loop fixes the findings, **preserve this doc as-found** and record the **resolved** state in the
> Delivery Report's findings disposition (the "after"). Tag the status line "(as-found)" and link
> the Delivery Report for the current state.

> **QA level for this pass:** `auto | quick | deep | audit` - state it here AND record it
> on the engagement (`engagement_state set-qa-depth <level>`), because the DoD gate reads
> it from state, not from this document (`QA-LEVEL-UNDECLARED`). A reader who cannot tell
> which breadth of QA produced a handover cannot tell what was skipped. **`quick` also
> closes the engagement PARTIAL** - a reduced pass must never read as a full one.

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

## 1. Test cycles *(append-only - one row per pass, failed verdicts stay forever)*
Every QA pass gets a row **at the time it runs**; later passes append, never overwrite. A
two-cycle engagement whose only visible verdict is "Pass" is a defect in this document.

| Pass | Date | Scope | Verdict | Defects raised | Routed to |
|------|------|-------|---------|----------------|-----------|
| 1 | <YYYY-MM-DD> | full suite | ❌ Fail | D-1, D-2 | `rules-developer` |
| 2 | <YYYY-MM-DD> | re-test D-1, D-2 + regression | ✅ Pass | - | - |

## 2. Test execution summary *(latest pass; earlier passes stay in §1 and §5)*
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

## 3. Environment & test data
- Environment / versions:
- Test data: **synthetic / masked only** (§5) - provenance and how it was generated.

## 4. Coverage
- **Covered:** scenarios, true-positive and false-positive cases, edge cases, error paths.
- **NOT covered (and why):** be explicit - unstated gaps are the dangerous ones.
- **Residual risk:** what could still go wrong in production.

## 5. Defects & known issues *(lifecycle - never delete a row once raised)*
| ID | Severity | Description | Raised in pass | Routed to | Fix evidence | Verified fixed in pass | Status |
|----|----------|-------------|----------------|-----------|--------------|------------------------|--------|

## 6. Items for the QA team to note / re-verify
Things a human reviewer should manually confirm (e.g. regulatory mapping, alert wording,
threshold rationale, anything not fully automatable).

**Disposition tally:** ✅ _N_ Fixed/Answered · 🔴 _N_ Open · ⏭️ _N_ Deferred/Needs-input · ⚖️ _N_ Accepted - reconcile with the QA verdict; a Fail must make the Open defects explicit.

> **Run provenance & non-determinism** *(standing statement - keep it in the rendered artifact)*
> · Model `<model id>` · Framework `compliance-surveillance-team <version>` · Run `<YYYY-MM-DD>`
>
> The findings and conclusions in this document are **one sample from a non-deterministic
> process**. The same inputs, run again by the same model, can yield a different set of findings,
> in a different order, with different confidence scores. **Absence of a finding is not evidence
> of absence:** this document evidences what *was* found on this run, never that nothing further
> exists. Anything load-bearing for a control decision needs human verification; repeat runs
> raise confidence but never make the result exhaustive.

## Sign-off
> 🤖 = AI agent (Virtual Surveillance IT), not a human. Agent rows and human-approver rows stay separate - never combine an agent and a human on one line.

| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
