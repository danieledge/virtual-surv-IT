# Detection Scenario Specification - <NAME>

> Produced by `business-analyst` before development. Keep it implementable and testable.

> **Document control** · ID `SCN-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Internal | Confidential` · Owner `<name / role>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

## 1. Need / trigger
What business or regulatory need prompts this? (one paragraph)

## 2. Regulatory obligation
The specific obligation(s) this detection serves (cite the article/rule, per CLAUDE.md §2).

**Control mapping:** record which internal control(s) this scenario satisfies alongside the
regulatory obligation. Use the format: Obligation ref - Control ID - Control name.

| Obligation | Control ID | Control name | Control type |
|------------|------------|--------------|--------------|
| <e.g. MAR Art.12> | <CTRL-001> | <e.g. Spoofing detection> | Detective |

## 3. Typology / behaviour
The conduct to detect, in plain terms.

## 4. Data requirements
- Inputs (events/fields), source systems, frequency.
- Data classification (PII / MNPI). Synthetic/masked only in this repo (§5).

## 5. Detection requirements
State each requirement in EARS form: "When `<condition>`, the system shall `<response>`."
Signals and the proposed logic at a conceptual level (thresholds are the SME/tuning-analyst's
call and must not be invented here - surface them as open questions in §7).

| ID | Detection requirement (EARS) | Rationale / source |
|----|------------------------------|--------------------|
| DR-001 | When <condition>, the system shall <response> | <obligation / typology ref> |

## 6. Acceptance criteria
- [ ] Known true-positive cases that MUST alert.
- [ ] Known false-positive controls that MUST NOT alert.
- [ ] Explainability: every alert traces alert → logic → obligation.

## 7. Out of scope / assumptions / open questions
List explicitly. Flag anything needing SME input. **Each open question must be formally
dispositioned by its owner before sign-off** (§9) - don't leave them dangling (DoD gate).

## 8. Hand-off
SME for review: `<trade-surveillance-sme | tm-sme | comms-surveillance-sme>`
Implementer: `rules-developer` (or `ml-engineer` if model-based → `model-validator`).

## 9. Open-questions disposition (decision log)
The §7 open questions, formally closed by their owner (the SME). Don't finalise the obligation
mapping / sign off while a blocker is open.

| # | Question | Owner | Disposition |
|---|---|---|---|
| Q1 | <…> | <sme> | answered / needs deployment input / open-decision-required - <one line> |

**Bottom line:** is the obligation mapping safe to finalise? If not, the minimum still required.

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
