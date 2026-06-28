# Model Validation Report - <MODEL NAME / VERSION>

> Produced by `model-validator`, **independent** of `ml-engineer` (CLAUDE.md §7).
> Aligned to model-risk governance: US SR 11-7, UK PRA SS1/23.

> **Document control** · ID `MVR-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Confidential` · Owner `<name / role>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

| | |
|---|---|
| **Model ID** | `<unique stable identifier, e.g. MDL-042>` |
| **Model name / version** | <name / version> |
| **Purpose** | <what detection decision it supports> |
| **Risk tier / materiality** | High / Medium / Low - per your model-risk policy (`<policy ref>`) |
| **Developer** | `ml-engineer` |
| **Validator** | `model-validator` (independent - no involvement in model development) |
| **Date** | <YYYY-MM-DD> |
| **Outcome** | Approved / Approved with conditions / Rejected |

## 1. Model assumptions - stated and challenged
List every material assumption the model makes (data distribution, stationarity, feature
availability, label quality, population scope). For each, state whether it was validated or
challenged, the evidence, and the residual risk if the assumption fails.

| Assumption | Source | Validated / Challenged | Evidence | Residual risk if assumption fails |
|---|---|---|---|---|
| | | | | |

## 2. Conceptual soundness
Is the method appropriate for the problem and the obligation it serves? Alignment between the
detection typology (per the relevant SME) and the modelling approach.

## 3. Data
Provenance, representativeness, quality, leakage checks. Synthetic/governed only (§5).

## 4. Performance
Precision/recall (or proxies), calibration, comparison to the existing rule/benchmark,
performance by segment.

## 5. Stability & robustness
Sensitivity to inputs and thresholds; behaviour under drift; stress/edge cases.

## 6. Bias & fairness
Disparate impact across relevant segments; mitigations.

## 7. Explainability & auditability
Can each score/alert be explained and traced (§4)? Documentation completeness.

## 8. Findings & conditions

**Severity taxonomy:**
- **S1 - Critical:** blocks approval; model must not be deployed until resolved.
- **S2 - Major:** approval with mandatory condition; must be resolved before next revalidation.
- **S3 - Minor:** advisory; tracked but does not block approval.
- **S4 - Observation:** informational; no required action.

**Disposition tally:**
| Severity | Open | Resolved | Accepted (with rationale) | Total |
|---|---|---|---|---|
| S1 - Critical | | | | |
| S2 - Major | | | | |
| S3 - Minor | | | | |
| S4 - Observation | | | | |

| Sev | ID | Finding | Required action | Owner | Due | Status |
|---|---|---|---|---|---|---|
| | | | | | | |

## 9. Limitations & compensating controls
Explicit statement of what this model does **not** do well, the boundaries of its applicability,
and the compensating controls in place (rule-based backstops, human review thresholds, alert
suppression, etc.) that mitigate each limitation.

| Limitation | Scope / boundary | Compensating control | Control owner |
|---|---|---|---|
| | | | |

## 10. Ongoing monitoring & outcome analysis (backtesting)
Requirements for keeping the model safe after approval.

- **Performance monitoring:** metrics to track in production, frequency, alert thresholds for
  degradation (who is notified, who decides to suspend).
- **Outcome / backtesting cadence:** how often model outputs are compared to confirmed outcomes
  (SARs filed, regulatory findings, enforcement actions) and by whom.
- **Drift detection:** feature and label drift checks; retraining trigger criteria.
- **Revalidation trigger:** conditions that mandate a full revalidation ahead of schedule
  (e.g. regulatory change, data-feed change, performance breach, >X% alert-volume shift).
- **Scheduled revalidation date:** `<YYYY-MM-DD>`

## 11. Conclusion
Overall opinion, residual risk summary (cross-reference §9), and formal outcome with any
binding conditions.

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
