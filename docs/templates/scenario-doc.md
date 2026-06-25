# Scenario: <NAME>

> Audit-trail document for a deployed (or candidate) detection. Mirrors
> `docs/scenarios/spoofing.md`. Every detection must have one.

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

## 5. Test coverage
| Case | Fixture | Expectation |
|---|---|---|
| | | |

## 6. Limitations & open items
Known gaps and candidate enhancements.

## 7. Review trail
- [ ] SME reviewed detection logic
- [ ] `compliance-reviewer` confirmed auditability, thresholds, no secrets/PII, tests
- Tuning history: <date - change - rationale>
