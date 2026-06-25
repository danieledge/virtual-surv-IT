# User Stories - <TITLE>

> Produced by `business-analyst`. Agile-format stories with Gherkin acceptance criteria and
> MoSCoW priority, feeding the FSD and build. Authored in `.md`, rendered to `.html`.
> Synthetic illustrations only - no real data (§5).

| | |
|---|---|
| **Document ID** | US-<slug> |
| **Author / owner** | business-analyst / <user> |
| **Version / date** | 0.1 / <YYYY-MM-DD> |
| **Status** | draft / refined / ready |
| **Related** | REQ-<slug> · RTM-<slug> |

## 1. Story map / epic
One line on the epic these stories deliver and the obligation it serves (§2).

## 2. Stories
Each story has a stable ID, the canonical "As a … I want … so that …" form, MoSCoW priority,
and Gherkin acceptance criteria. Surveillance stories must include a **true-positive** and a
**false-positive** criterion.

### US-001 - <short title>  ·  Priority: **Must**
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

### US-002 - <short title>  ·  Priority: **Should**
**As a** <role> **I want** <capability> **so that** <outcome>.
```gherkin
Scenario: <…>
  Given <…>
  When <…>
  Then <…>
```
*Traces to:* REQ-F-00x

## 3. Priority summary (MoSCoW)
| Priority | Stories |
|----------|---------|
| Must | US-001, … |
| Should | US-002, … |
| Could | … |
| Won't (this release) | … |

## 4. Definition of Ready / Done
- **Ready:** story is independent, valued, estimable, small, testable (INVEST); acceptance
  criteria written incl. TP & FP cases; data source identified; driver cited; no blocking
  open questions.
- **Done:** see `docs/DEFINITION-OF-DONE.md` - implemented, tested (TP & FP pass),
  independently QA'd, reviewed (code/compliance), documented, RTM updated, human sign-off.

> Traceability: each US-### maps to REQ-F-###/FSD-### and an RTM row through to a passing test
> and the cited obligation.
