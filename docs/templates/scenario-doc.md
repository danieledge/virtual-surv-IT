# Scenario: <NAME>

> Audit-trail document for a deployed (or candidate) detection. Mirrors
> `docs/scenarios/spoofing.md`. Every detection must have one.

> **Document control** · ID `SCN-DOC-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Internal | Confidential` · Owner `<name / role>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

| | |
|---|---|
| **Domain** | <transaction monitoring / trade surveillance / comms surveillance> |
| **Status** | <candidate / live> |
| **Owner / SME** | `<agent>` |
| **Implementation** | `rules/<file>.py` |
| **Tests** | `tests/test_<file>.py` |
| **Data** | synthetic only (§5) |
| **Last tuned** | <YYYY-MM-DD> |

## 1. Regulatory obligation
Cite the specific obligation(s). This string should appear on the alert.

## 2. Typology
The behaviour being detected.

## 3. Detection logic
Summary of the rule/model. Link to the implementation function.

## 4. Thresholds (rationale + tuning date)
| Threshold | Value | Rationale | Tuned |
|---|---|---|---|
| | | | |

## 5. Data lineage
Document the path from source feed through to the fields consumed by the detection logic.
Any transformation (aggregation, join, normalisation) must be named. Gaps here are undetected
abuse risk - flag any feed not yet reconciled.

| Feed / source | Field(s) consumed | Transformation | Produces | Owner |
|---------------|-------------------|----------------|----------|-------|
| <e.g. OMS feed> | <order_id, qty, price> | <deduplicate + aggregate> | <order_book snapshot> | <platform-engineer> |

## 6. Test coverage
| Case | Fixture | Expectation | Result (P/F) |
|---|---|---|---|
| | | | |

## 7. Limitations & open items
Known gaps and candidate enhancements.

## 8. Review trail
- [ ] SME reviewed detection logic
- [ ] `compliance-reviewer` confirmed auditability, thresholds, no secrets/PII, tests
- Tuning history: <date - change - rationale>

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
