# Change Request / RFC - <TITLE>

> **Drafted by the virtual team to feed your existing change control.** Items marked
> **[IT team]** are for your team to complete, approve or execute - the team does **not**
> self-certify or approve changes. Authored in `.md`, rendered to `.html`.

> **Document control** · ID `CR-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Internal | Confidential` · Owner `<name / role>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

| | |
|---|---|
| **Change ID** | [IT team] |
| **Title** | <...> |
| **Raised by** | <...> · drafted by the virtual team |
| **Date drafted** | <YYYY-MM-DD> |
| **Change type** | standard / normal / emergency - [IT team to confirm] |
| **Target environment** | [IT team] |

## 1. Summary
What is changing, in one paragraph.

## 2. Reason / business driver
Why - link the BRD/FSD and the regulatory driver.

## 3. Scope
- **In scope:**
- **Out of scope / not affected:**

## 4. Risk & impact assessment
- **Impact if deployed:** systems/users/data affected.
- **Risk if NOT deployed:**
- **Risk rating:** [IT team to confirm against your matrix]
- **Affected components / blast radius:** (from the deep review / impact analysis)

## 5. Test evidence
Link the **QA handover** (test execution + coverage) and the **review reports** (code,
performance, compliance). Summary: tests run, pass rate, residual risk.

## 6. Rollback / backout plan
How to revert if the change misbehaves; data considerations; time to roll back.

**Rollback trigger / go-no-go criteria:** define the observable conditions that would cause the
deployment to be halted or reversed (e.g. error-rate threshold, alert-liveness failure, data
reconciliation breach). State who holds the go/no-go decision authority and the time-box within
which the call must be made post-deployment.

| Trigger condition | Threshold | Decision authority | Time-box |
|---|---|---|---|
| | | [IT team] | |

## 7. Implementation
- **Steps:** link the deployment runbook (if produced).
- **Window / schedule:** [IT team]
- **Dependencies / prerequisites:**

## 8. Post-implementation verification
Steps to confirm the change is operating correctly after deployment (distinct from pre-deploy
testing). Link the ops runbook monitoring section and state the verification window.

| Check | Expected result | Owner | Verification window |
|---|---|---|---|
| Alert-liveness check | Alerts generated within SLA | [IT team] | <e.g. 24h post-deploy> |
| Reconciliation / data-feed check | Row counts match upstream | [IT team] | <e.g. next batch run> |
| Performance baseline | Latency within target | [IT team] | <e.g. 48h post-deploy> |

## 9. Approvals - [IT team / CAB]
| Role | Name | Decision | Date |
|------|------|----------|------|
| Change owner | | | |
| Technical approver | | | |
| CAB / release authority | | | |

> The virtual team supplies the evidence above; **approval and the implementation decision
> remain with your IT team and change-control process.**

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
