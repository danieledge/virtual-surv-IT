# Control Mapping - <PROGRAMME / SCOPE>

> Produced by `business-analyst`; reviewed by `compliance-reviewer`. Maps each detection scenario
> to the regulatory obligation it satisfies and the internal control it implements. The RTM's
> control view - the artifact that lets a regulator or auditor trace from obligation to control
> to evidence of effectiveness.

> **Document control** · ID `CTRL-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Internal` · Owner `<business-analyst / control owner>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

---

## Scope

| Field | Value |
|---|---|
| Programme | <e.g. Trade Surveillance / AML TM / Comms Surveillance> |
| Jurisdictions | <applicable regime(s)> |
| As-of date | <YYYY-MM-DD> |
| RTM reference | <RTM-NNN> |

---

## Control type key

- **Preventive** - designed to stop a breach occurring (pre-trade / pre-send limit / block).
- **Detective** - designed to identify a breach after the fact (surveillance alert / monitoring).
- **Directive** - policy or procedure that directs behaviour (training / policy / approval gate).
- **Corrective** - designed to remediate once a breach is detected (escalation / SAR / claw-back).

---

## Control mapping table

| Control ID | Detection scenario | Scenario ref | Regulatory obligation (article) | Control type | Control description | Control owner | Effectiveness rating | Last tested | Evidence ref | Gaps / open items |
|---|---|---|---|---|---|---|---|---|---|---|
| CTRL-001 | <scenario name> | FSD-<NNN> | <e.g. MAR Art.12(1)(a)> | Detective | <one-line description of what the control does> | <team / role> | `Effective` / `Partially effective` / `Ineffective` / `Not yet tested` | <YYYY-MM-DD> | <test evidence ref> | <gap or N/A> |
| CTRL-002 | | | | | | | | | | |

---

## Obligation coverage summary

List each in-scope regulatory obligation and confirm at least one control addresses it.
A gap (obligation with no mapped control) is an audit finding.

| Obligation | Article | Controls mapped | Coverage status |
|---|---|---|---|
| <e.g. Market Abuse Regulation - layering> | MAR Art.12(1)(a) | CTRL-001 | Covered |
| <e.g. 5MLD - unusual transaction reporting> | MLD5 Art.33 | CTRL-002, CTRL-003 | Covered |
| <obligation with no control yet> | <article> | None | **GAP - action required** |

---

## Effectiveness testing schedule

| Control ID | Test method | Responsible | Frequency | Next due | Last outcome |
|---|---|---|---|---|---|
| CTRL-001 | <e.g. scenario walkthrough / sample review / red-team> | <role> | <quarterly / annual> | <YYYY-MM-DD> | <pass / fail / partial> |

---

## Open gaps and remediation

| # | Gap description | Obligation at risk | Owner | Target remediation date | Status |
|---|---|---|---|---|---|
| G1 | <description> | <obligation> | <owner> | <YYYY-MM-DD> | `Open` / `In progress` / `Closed` |

---

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
