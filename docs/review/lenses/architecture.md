---
name: Architecture & Design
model: sonnet
---

> Adapted from **turingmind-code-review** (MIT, © 2026 TuringMind). See THIRD-PARTY-LICENSES.md.

*Deep / audit reviews only.* Analyse architectural implications. Needs related-file context
(importers + imports of the changed files).

## Checks

- **Pattern consistency** - does this follow existing patterns, or solve a solved problem a new way?
- **Abstraction** - reaching into private internals; inappropriate coupling between modules.
- **Duplication** - logic that should be a shared utility; near-duplicates to consolidate.
- **Dependencies** - are new deps justified? Any circular dependency introduced?
- **Separation of concerns** - business/detection logic mixed with infrastructure; layering violations.
- **Auditability (this domain)** - is the alert→logic→obligation trace still clear after the
  change, or has the restructure obscured it? (Flag for `compliance-reviewer` to confirm.)

## Output

Feeds the **📐 Architectural notes** and **💥 Impact analysis** sections of
`docs/review/output-format.md`. Report observations as note / suggestion / issue with a
recommendation; most architecture findings are 🔵 style/form or 🟡 Medium, not blockers, unless
they break correctness or the audit trail. State evidence basis (📊 / 🧠).
