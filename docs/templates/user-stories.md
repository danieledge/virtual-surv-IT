# User Stories - <TITLE>

> Produced by `business-analyst`. Agile-format stories with Gherkin acceptance criteria and
> MoSCoW priority, feeding the FSD and build. Authored in `.md`, rendered to `.html`.
> Synthetic illustrations only - no real data (§5).

> **Document control** · ID `US-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Internal | Confidential` · Owner `<name / role>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

**Related:** REQ-`<slug>` · RTM-`<slug>`

## 1. Personas
Define the roles that appear in stories. Add or remove personas to match the engagement.

| Persona | Role description | Typical goal | Surveillance-specific context |
|---------|-----------------|--------------|-------------------------------|
| Surveillance analyst | Front-line reviewer who triages alerts in the case-management system | Quickly determine whether an alert represents genuine misconduct or a false positive | Works to regulatory timelines (e.g. STR/SAR filing window); needs traceable, explainable alerts |
| MLRO / financial crime officer | Senior decision-maker for regulatory filings | Receive high-quality escalations with clear evidence packs | Accountable for SAR quality; relies on alert narrative and obligation citation |
| Surveillance manager | Oversees the analyst team and alert KPIs | Manage throughput, false-positive rate, and audit readiness | Requires MI/reporting on scenario performance and coverage gaps |
| IT / platform engineer | Operates feeds, infrastructure, and deployment | Stable, well-defined interfaces and data contracts | Needs clear data requirements and SLAs per spec |

## 2. Story map / epic
One line on the epic these stories deliver and the obligation it serves (§2).

## 3. Stories
Each story has a stable ID, the canonical "As a … I want … so that …" form, MoSCoW priority,
size/estimate, and Gherkin acceptance criteria. Surveillance stories must include a
**true-positive** and a **false-positive** criterion.

### US-001 - <short title> · Priority: **Must** · Size: `<S / M / L / XL or story points>`
**As a** surveillance analyst
**I want** <capability>
**so that** <outcome / obligation served>.

*Acceptance criteria:*
```gherkin
Scenario: True positive - abuse is detected
  Given <synthetic account/market state>
  When <the suspicious behaviour occurs>
  Then an alert of type <X> is raised with <evidence>

Scenario: False positive - benign activity is not flagged
  Given <legitimate look-alike activity>
  When <it occurs>
  Then no alert is raised
```
*Traces to:* REQ-F-001 · *Driver:* MAR Art.12 / … (§2)

### US-002 - <short title> · Priority: **Should** · Size: `<S / M / L / XL or story points>`
**As a** <role> **I want** <capability> **so that** <outcome>.
```gherkin
Scenario: <…>
  Given <…>
  When <…>
  Then <…>
```
*Traces to:* REQ-F-00x

## 4. Priority summary (MoSCoW)
| Priority | Stories | Total size |
|----------|---------|------------|
| Must | US-001, … | <points / effort> |
| Should | US-002, … | |
| Could | … | |
| Won't (this release) | … | |

## 5. Definition of Ready / Done
- **Ready:** story is independent, valued, estimable, small, testable (INVEST); acceptance
  criteria written incl. TP & FP cases; data source identified; driver cited; no blocking
  open questions.
- **Done:** see `docs/DEFINITION-OF-DONE.md` - implemented, tested (TP & FP pass),
  independently QA'd, reviewed (code/compliance), documented, RTM updated, human sign-off.

> Traceability: each US-### maps to REQ-F-###/FSD-### and an RTM row through to a passing test
> and the cited obligation.

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
