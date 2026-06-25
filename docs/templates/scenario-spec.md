# Detection Scenario Specification - <NAME>

> Produced by `business-analyst` before development. Keep it implementable and testable.

## 1. Need / trigger
What business or regulatory need prompts this? (one paragraph)

## 2. Regulatory obligation
The specific obligation(s) this detection serves (cite the article/rule, per CLAUDE.md §2).

## 3. Typology / behaviour
The conduct to detect, in plain terms.

## 4. Data requirements
- Inputs (events/fields), source systems, frequency.
- Data classification (PII / MNPI). Synthetic/masked only in this repo (§5).

## 5. Detection requirements
- Signals and the proposed logic at a conceptual level.
- Candidate thresholds and the rationale for each (no undocumented thresholds - §4).

## 6. Acceptance criteria
- [ ] Known true-positive cases that MUST alert.
- [ ] Known false-positive controls that MUST NOT alert.
- [ ] Explainability: every alert traces alert → logic → obligation.

## 7. Out of scope / assumptions / open questions
List explicitly. Flag anything needing SME input.

## 8. Hand-off
SME for review: `<trade-surveillance-sme | tm-sme | comms-surveillance-sme>`
Implementer: `rules-developer` (or `ml-engineer` if model-based → `model-validator`).
