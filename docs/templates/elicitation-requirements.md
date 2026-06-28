# Elicitation & Requirements - <TITLE>

> Produced by `business-analyst` (BABOK *Elicitation* + *Requirements Analysis*). Business
> requirements in **EARS**, acceptance criteria in **Gherkin**. The bridge from a need to the
> FSD. Authored in `.md`, rendered to `.html`. Synthetic illustrations only - no real data (§5).

> **Document control** · ID `ELR-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Internal | Confidential` · Owner `<name / role>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

**Related:** BRD-`<slug>` · STK-`<slug>` · RTM-`<slug>`

## 1. Context & regulatory driver
The business situation and the obligation(s) it serves (§2) - e.g. MAR Art.12 (market
manipulation), 6AMLD / BSA (AML), FCA SYSC record-keeping. Cite the specific obligation.

## 2. Scope
- **In scope:** <instruments / venues / accounts / comms channels / behaviours covered>
- **Out of scope:** <explicitly excluded - note the residual risk owner>

## 3. Elicitation method & sources
| Technique | Source / participant | Date | Output |
|-----------|----------------------|------|--------|
| Interview | tm-sme / trade-sme | <YYYY-MM-DD> | typology notes |
| Document analysis | regulation / policy | … | obligation map |
| Workshop | analysts | … | as-is process |

## 4. Confirm elicitation results
Before requirements are baselined, elicitation outputs must be reviewed and countersigned by
the relevant SME(s) and the business sponsor. This step closes the loop on any
misinterpretation and is a gate before the FSD is authored.

| Elicitation output | Reviewed by (SME) | Reviewed by (sponsor) | Date | Any corrections? |
|--------------------|-------------------|-----------------------|------|-----------------|
| <typology notes> | <sme name / role> | <sponsor name / role> | <YYYY-MM-DD> | <yes - see Q# / no> |

## 5. Business requirements (EARS)
Stable IDs; "When `<trigger>`, the system shall `<response>`" (or ubiquitous form). Cite driver.

| ID | Requirement (EARS) | Driver / obligation (§2) | Priority |
|----|--------------------|--------------------------|----------|
| REQ-B-001 | When … the system shall … | MAR Art.12 / … | Must |
| REQ-B-002 | The system shall … | … | Should |

## 6. Functional / detection requirements
What the solution must do - detection logic, scenario behaviour, alerting, workflow outputs.

| ID | Functional requirement | Traces to | Priority |
|----|------------------------|-----------|----------|
| REQ-F-001 | Detect <typology> when <conditions> | REQ-B-001 | Must |
| REQ-F-002 | Generate alert with <fields> for triage | REQ-B-001 | Must |

## 7. Data requirements
Feeds, fields, granularity, quality and lineage the logic depends on. Flag any feed not yet
captured - a missing feed is undetected abuse.

| Data element | Source feed | Granularity | Quality / completeness need |
|--------------|-------------|-------------|-----------------------------|
| Orders & cancels | OMS | per-event, ms | full lifecycle, no gaps |
| Trades | exec venue | per-fill | reconciled to ledger |

## 8. Acceptance criteria (Gherkin)
Each functional requirement needs at least one **true-positive** (should alert) and one
**false-positive** (should *not* alert) case.
```gherkin
Scenario: <true positive - abuse is detected>
  Given <synthetic market/account state>
  When <the behaviour occurs>
  Then an alert of type <X> is raised with <evidence fields>

Scenario: <false positive - benign activity is not flagged>
  Given <legitimate but superficially similar activity>
  When <it occurs>
  Then no alert is raised
```

## 9. Non-functional requirements
EARS phrasing required; use the REQ-NF-### series for stable IDs.

| ID | NFR (EARS) | Category | Driver / obligation | Priority |
|----|------------|----------|---------------------|----------|
| REQ-NF-001 | The system shall retain alert records for <n> years without modification | Retention / immutability | SEC 17a-4 / FCA SYSC | Must |
| REQ-NF-002 | When an alert is generated, the system shall produce a traceable audit record linking alert to logic to obligation within <n> seconds | Auditability | MAR / SR 11-7 | Must |
| REQ-NF-003 | The system shall process <n> events per day with end-to-end latency not exceeding <t> minutes | Performance | <internal SLA> | Must |
| REQ-NF-004 | The system shall operate without storing PII or MNPI outside the approved data classification boundary | Data safety | GDPR / CLAUDE.md §5 | Must |

## 10. Open questions
Material unknowns the PM is clarifying with the user (never guessed).

> Traceability: REQ-B/F-### flow into the FSD and the RTM (`docs/templates/rtm.md`):
> BRD → FSD → code → test → obligation. Keep the RTM updated as these firm up.

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
