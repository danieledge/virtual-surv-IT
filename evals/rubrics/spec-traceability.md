# Rubric: spec & traceability (`/write-brd`, `/brd-to-fsd`, `/elicit-requirements`, `/new-scenario`)

Scores a requirements/spec deliverable 0.0-1.0 + pass/fail.

| Dimension | What "good" looks like | Weight |
|---|---|---|
| **Obligation traced** | The traceability spine is intact: obligation → BRD → FSD → code/test. Each requirement cites its driver. *(deterministic: must-trace items present)* | 0.30 |
| **EARS / testable** | Requirements in EARS ("When `<trigger>`, the system shall `<response>`"), each unambiguous and testable. | 0.20 |
| **Acceptance criteria** | Gherkin Given/When/Then, including **true-positive AND false-positive** handling. | 0.20 |
| **No invented thresholds** | Thresholds flagged as SME/tuning decisions, never fabricated. | 0.15 |
| **Scope clarity** | In-scope / out-of-scope explicit; open questions surfaced, not hidden. | 0.10 |
| **No real data** | Examples are synthetic (§5). | 0.05 |

**Pass:** the traceability spine complete, weighted score >= 0.75.
**Auto-fail:** an invented threshold presented as decided; a requirement with no driver; real PII in an example.
