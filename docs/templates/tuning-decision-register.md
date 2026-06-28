# Tuning Decision Register - <SCENARIO / PROGRAMME>

> Produced and maintained by `tuning-analyst`; reviewed by `compliance-reviewer` at each DoD
> gate. A running log - not a point-in-time report - of every threshold and parameter change
> applied to a detection scenario. Satisfies SR 11-7 / FFIEC model-change-management obligations.

> **Document control** · ID `TDR-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Confidential` · Owner `<tuning-analyst / model owner>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft - register opened |

---

## Scope

| Field | Value |
|---|---|
| Scenario(s) covered | <scenario name(s) + ID(s)> |
| Regulatory obligation(s) | <e.g. MAR Art.12 / MLD5 Art.33> |
| Detection system / rule file | <system name + rule reference> |
| Register opened | <YYYY-MM-DD> |
| Model / scenario owner | <name / role> |
| Review cadence | <e.g. quarterly / event-driven> |

---

## How to use this register

- Append one row per change; never edit or delete historical rows.
- Every change must reference a tuning pack (`THP-NNN`) or an ad-hoc evidence note.
- "Effect on alert volume" is the **measured** post-change outcome, filled in at the first
  review after deployment - mark as `Pending` until confirmed.
- Changes to live detection logic also require `rules-developer` implementation and
  `model-validator` / `compliance-reviewer` sign-off (ref DoD gate).
- SR 11-7 requires that material model changes are independently validated - flag in column M.

---

## Change log

| # | Date applied | Scenario | Parameter | From value | To value | Evidence / tuning pack ref | ATL-BTL ref | Approver | Implemented by | Effect on alert volume (measured) | Material change (SR 11-7)? | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 001 | <YYYY-MM-DD> | <scenario name> | <param name> | <old value> | <new value> | THP-<NNN> | ATL-<NNN> / BTL-<NNN> | <approver name / role> | `rules-developer` | <e.g. -12% alerts; 2% coverage loss - measured YYYY-MM-DD> | Yes / No | <any notes> |
| 002 | | | | | | | | | | Pending | | |

---

## Periodic review summary

Record the outcome of each scheduled tuning review here even when no parameter change results
(the "no change" decision is itself an evidenced model-management action).

| Review date | Reviewer | Scenarios reviewed | Changes made (ref log #) | No-change rationale | Next review due |
|---|---|---|---|---|---|
| <YYYY-MM-DD> | <tuning-analyst> | <list> | <001, 002 / None> | <if no change - one line> | <YYYY-MM-DD> |

---

## Open tuning items

Track approved changes not yet deployed, or items flagged for the next review cycle.

| # | Item | Raised by | Date raised | Status | Target deploy |
|---|---|---|---|---|---|
| T1 | <description> | <role> | <YYYY-MM-DD> | `Open` / `In progress` / `Closed` | <YYYY-MM-DD> |

---

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
