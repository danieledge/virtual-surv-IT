# Decision & Open-Questions Log - <TITLE>

> The tracked record that satisfies the **"Open questions dispositioned"** Definition-of-Done gate
> (`docs/DEFINITION-OF-DONE.md`): every open question raised upstream (a spec/BRD/review - e.g. a BA's
> questions for an SME) is **formally closed by its owner**, never left dangling or "touched in
> passing". Authored in `.md`, rendered to `.html`.

> **Document control** · ID `DLOG-<slug>` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Internal` · Owner `<name / role>` · As-of `<YYYY-MM-DD>`

## How to use
- One row per question. The **owner** dispositions it with a tag and a one-line rationale.
- A `🔴 Open-decision-required` or any blocker **must** be reflected in the parent artifact's verdict
  (the delivery report / spec cannot read "ready" while a blocker is open).
- `compliance-reviewer` checks this log as part of the DoD gate before sign-off.

**Disposition tags:** ✅ Answered · ⏭️ Needs deployment input (firm-specific fact) · 🔴 Open-decision-required
(needs a named human decision / sign-off) · ⚖️ Accepted (with rationale).

## Log
| # | Question | Raised by | Owner | Disposition | Rationale / answer | Blocker? | Date closed |
|---|----------|-----------|-------|-------------|--------------------|----------|-------------|
| Q1 | <…> | `business-analyst` | `trade-surveillance-sme` | 🔴 Open-decision-required | <one line> | **Yes** | - |
| Q2 | <…> | … | … | ✅ Answered | <one line> | No | <YYYY-MM-DD> |

## Disposition summary
✅ _N_ answered · ⏭️ _N_ deployment-input · 🔴 _N_ open-decision · ⚖️ _N_ accepted.
**Bottom line:** is the parent artifact safe to finalise / sign off? If not, list the minimum still
required (the open blockers) and who owns each.

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver | | | |
