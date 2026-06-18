# Model Validation Report — <MODEL NAME / VERSION>

> Produced by `model-validator`, **independent** of `ml-engineer` (CLAUDE.md §7).
> Aligned to model-risk governance: US SR 11-7, UK PRA SS1/23.

| | |
|---|---|
| **Model** | <name / version> |
| **Purpose** | <what detection decision it supports> |
| **Developer** | `ml-engineer` |
| **Validator** | `model-validator` (independent) |
| **Date** | <YYYY-MM-DD> |
| **Outcome** | <Approved / Approved with conditions / Rejected> |

## 1. Conceptual soundness
Is the method appropriate for the problem and the obligation it serves? Assumptions and
their limitations.

## 2. Data
Provenance, representativeness, quality, leakage checks. Synthetic/governed only (§5).

## 3. Performance
Precision/recall (or proxies), calibration, comparison to the existing rule/benchmark,
performance by segment.

## 4. Stability & robustness
Sensitivity to inputs and thresholds; behaviour under drift; stress/edge cases.

## 5. Bias & fairness
Disparate impact across relevant segments; mitigations.

## 6. Explainability & auditability
Can each score/alert be explained and traced (§4)? Documentation completeness.

## 7. Findings & conditions
| Severity | Finding | Required action | Owner |
|---|---|---|---|
| | | | |

## 8. Conclusion
Overall opinion, residual risk, monitoring requirements, and revalidation trigger/date.
