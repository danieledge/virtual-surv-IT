# Requirements Traceability Matrix - <TITLE>

> The audit "golden thread": every business need traces forward to design, code, a test and
> the regulatory obligation it serves - and back again. This is the artifact that lets a
> solution stand up to audit and regulatory scrutiny. Authored in `.md`, rendered to `.html`.

> **Document control** · ID `RTM-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Internal | Confidential` · Owner `<name / role>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

**Allowed Status values:** `done` · `in progress` · `not started` · `deferred` · `blocked` · `N/A`

| BRD | FSD | Design / ADR | Code (module / fn) | Test | Regulatory obligation | Status | Gap / exception disposition |
|-----|-----|--------------|--------------------|------|-----------------------|--------|-----------------------------|
| BRD-001 | FSD-001 | ADR-001 | `rules/spoofing.py::detect_spoofing` | `test_spoofing.py::test_known_spoof_is_flagged` | MAR Art.12(1)(a) | done | - |
| BRD-002 | FSD-002 | - | - | - | ... | in progress | Gap owner: `<role>` · Target close: `<YYYY-MM-DD>` |

**How to read it**
- Every row must end-to-end connect a requirement to a passing test and a cited obligation.
- A gap in any column is an audit finding waiting to happen - track it to closure in the
  "Gap / exception disposition" column: record the owner and target-close date for every "-" cell.
- Update the RTM as part of every change; it is reviewed by `compliance-reviewer`.

**Bidirectional-coverage check (run at each review gate)**
- **Orphan tests** - tests that exist in the suite but do not appear in any RTM row are a
  coverage gap: they may be testing undocumented behaviour or untraceable scope. List them here
  and resolve before sign-off.
- **Requirements with no obligation** - any BRD/FSD row that lacks a cited regulatory or business
  obligation must be justified or removed; it cannot satisfy the audit trail.
- **Orphan obligations** - obligations in the regulatory scope (`docs/scope-and-stack.md`) that
  have no corresponding BRD row indicate a potential surveillance gap.

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
