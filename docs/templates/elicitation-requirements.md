# Elicitation & Requirements — <TITLE>

> Produced by `business-analyst` (BABOK *Elicitation* + *Requirements Analysis*). Business
> requirements in **EARS**, acceptance criteria in **Gherkin**. The bridge from a need to the
> FSD. Authored in `.md`, rendered to `.html`. Synthetic illustrations only — no real data (§5).

| | |
|---|---|
| **Document ID** | REQ-<slug> |
| **Author / owner** | business-analyst / <user> |
| **Version / date** | 0.1 / <YYYY-MM-DD> |
| **Status** | draft / approved |
| **Related** | BRD-<slug> · STK-<slug> · RTM-<slug> |

## 1. Context & regulatory driver
The business situation and the obligation(s) it serves (§2) — e.g. MAR Art.12 (market
manipulation), 6AMLD / BSA (AML), FCA SYSC record-keeping. Cite the specific obligation.

## 2. Scope
- **In scope:** <instruments / venues / accounts / comms channels / behaviours covered>
- **Out of scope:** <explicitly excluded — note the residual risk owner>

## 3. Elicitation method & sources
| Technique | Source / participant | Date | Output |
|-----------|----------------------|------|--------|
| Interview | tm-sme / trade-sme | <YYYY-MM-DD> | typology notes |
| Document analysis | regulation / policy | … | obligation map |
| Workshop | analysts | … | as-is process |

## 4. Business requirements (EARS)
Stable IDs; "When `<trigger>`, the system shall `<response>`" (or ubiquitous form). Cite driver.

| ID | Requirement (EARS) | Driver / obligation (§2) | Priority |
|----|--------------------|--------------------------|----------|
| REQ-B-001 | When … the system shall … | MAR Art.12 / … | Must |
| REQ-B-002 | The system shall … | … | Should |

## 5. Functional / detection requirements
What the solution must do — detection logic, scenario behaviour, alerting, workflow outputs.

| ID | Functional requirement | Traces to | Priority |
|----|------------------------|-----------|----------|
| REQ-F-001 | Detect <typology> when <conditions> | REQ-B-001 | Must |
| REQ-F-002 | Generate alert with <fields> for triage | REQ-B-001 | Must |

## 6. Data requirements
Feeds, fields, granularity, quality and lineage the logic depends on. Flag any feed not yet
captured — a missing feed is undetected abuse.

| Data element | Source feed | Granularity | Quality / completeness need |
|--------------|-------------|-------------|-----------------------------|
| Orders & cancels | OMS | per-event, ms | full lifecycle, no gaps |
| Trades | exec venue | per-fill | reconciled to ledger |

## 7. Acceptance criteria (Gherkin)
Each functional requirement needs at least one **true-positive** (should alert) and one
**false-positive** (should *not* alert) case.
```gherkin
Scenario: <true positive — abuse is detected>
  Given <synthetic market/account state>
  When <the behaviour occurs>
  Then an alert of type <X> is raised with <evidence fields>

Scenario: <false positive — benign activity is not flagged>
  Given <legitimate but superficially similar activity>
  When <it occurs>
  Then no alert is raised
```

## 8. Non-functional requirements
- **Auditability & explainability:** deterministic inputs; alert → logic → obligation traceable.
- **Thresholds:** every threshold carries rationale + tuning date (no bare constants).
- **Retention:** records held per obligation (e.g. SEC 17a-4 / FINRA 4511, FCA SYSC).
- **Performance / volume:** <target events/day, latency, batch window>.
- **Data safety:** synthetic/masked data only; no PII/MNPI/secrets (§5).

## 9. Open questions
Material unknowns the PM is clarifying with the user (never guessed).

> Traceability: REQ-B/F-### flow into the FSD and the RTM (`docs/templates/rtm.md`):
> BRD → FSD → code → test → obligation. Keep the RTM updated as these firm up.
