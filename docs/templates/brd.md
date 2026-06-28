# Business Requirements Document - <TITLE>

> Drafted by `business-analyst`, overseen by the PM. Structure follows BABOK v3;
> requirements are written in **EARS** syntax. Authored in `.md`, rendered to `.html`.

> **Document control** · ID `BRD-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Internal | Confidential` · Owner `<name / role>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

## 1. Executive summary
One paragraph: what's being asked for and why it matters.

## 2. Business context & problem
The current situation, the gap, and the impact of not acting.

## 3. Business case (cost / benefit)
Quantify where possible: estimated cost of non-compliance (regulatory fine, reputational
exposure), cost of the change (build + run), and the expected benefit (coverage improvement,
audit-finding closure, headcount reduction). Even a qualitative comparison is required -
leave a stub if numbers are not yet available and flag as an open question.

| Item | Estimate | Notes |
|------|----------|-------|
| Cost of non-compliance | <£/$/€ or qualitative> | <regulatory exposure, enforcement history> |
| Build cost | <days / spend> | <team, tooling> |
| Annual run cost | <days / spend> | <ops, infra> |
| Expected benefit | <quantified or qualitative> | <coverage, fine avoidance, efficiency> |
| Break-even / payback | <period> | |

## 4. Goals & success metrics
Measurable outcomes that define success.

## 5. Stakeholders
Who is affected / consulted / signs off.

## 6. Scope
- **In scope:**
- **Out of scope:**

## 7. Business requirements (EARS)
Each requirement has a stable ID and uses EARS - "When `<trigger>`, the system shall
`<response>`" (or "The system shall `<response>`" for ubiquitous ones). Cite the driver.

| ID | Requirement (EARS) | Regulatory / business driver | Priority |
|----|--------------------|------------------------------|----------|
| BRD-001 | When … the system shall … | MAR Art.12 / … | Must |
| BRD-002 | The system shall … | … | Should |

## 8. Assumptions, constraints & dependencies

## 9. Risks

## 10. Acceptance criteria
Criteria must be measurable and testable. Use Gherkin scenarios for behavioural outcomes;
use numeric success metrics for non-behavioural outcomes.

```gherkin
Scenario: <true-positive - system detects the target behaviour>
  Given <the relevant context / data state>
  When <the trigger condition occurs>
  Then <the expected system response, including obligation cited>

Scenario: <false-positive control - benign activity is not flagged>
  Given <a superficially similar but legitimate context>
  When <the similar trigger occurs>
  Then no alert is raised
```

**Numeric success metrics (where applicable):**
| Metric | Target | Measurement method |
|--------|--------|--------------------|
| <e.g. false-positive rate> | <e.g. < 5 %> | <e.g. 30-day parallel run vs. baseline> |
| <e.g. alert latency> | <e.g. < 15 min> | <e.g. end-to-end timing in UAT> |

## 11. Open questions
Items the PM is clarifying with the user.

## 12. Approvals
| Role | Name | Decision | Date |
|------|------|----------|------|

> Traceability: each BRD-### flows to one or more FSD-### in the FSD, then to code, tests
> and the regulatory obligation in the RTM.

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
