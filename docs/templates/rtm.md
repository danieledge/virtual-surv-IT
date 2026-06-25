# Requirements Traceability Matrix - <TITLE>

> The audit "golden thread": every business need traces forward to design, code, a test and
> the regulatory obligation it serves - and back again. This is the artifact that lets a
> solution stand up to audit and regulatory scrutiny. Authored in `.md`, rendered to `.html`.

| BRD | FSD | Design / ADR | Code (module / fn) | Test | Regulatory obligation | Status |
|-----|-----|--------------|--------------------|------|-----------------------|--------|
| BRD-001 | FSD-001 | ADR-001 | `rules/spoofing.py::detect_spoofing` | `test_spoofing.py::test_known_spoof_is_flagged` | MAR Art.12(1)(a) | ✅ done |
| BRD-002 | FSD-002 | - | - | - | … | ⏳ in progress |

**How to read it**
- Every row must end-to-end connect a requirement to a passing test and a cited obligation.
- A gap in any column is an audit finding waiting to happen - track it to closure.
- Update the RTM as part of every change; it is reviewed by `compliance-reviewer`.
