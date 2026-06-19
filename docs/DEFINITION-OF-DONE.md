# Definition of Done

A delivery is "done" only when it carries the evidence a real developer, QA reviewer and
auditor can rely on. The PM checks this gate before handover; `compliance-reviewer` verifies
it. Apply the items relevant to the deliverable type — not every item fits every task.

## Every delivery

- [ ] **Traceable** — each requirement links requirement → design → code → test → obligation
      in the RTM (`docs/templates/rtm.md`).
- [ ] **Tested** — tests appropriate to the deliverable exist and **pass**:
  - detection logic → true-positive **and** false-positive cases;
  - pipeline/transform → input/output, schema and edge-case tests;
  - script → idempotency and error-path tests.
- [ ] **Independently QA'd** — `qa-engineer` (not the builder) has produced a **QA handover**
      (`qa-handover.md`) evidencing what ran, results, coverage, gaps and residual risk.
- [ ] **Code-reviewed (deep)** — `code-reviewer` ran; **no Critical findings open**;
      filtered/ reported counts recorded.
- [ ] **Performance-reviewed** — where it processes data at volume, `performance-reviewer`
      assessed it against expected volumes with profiling evidence.
- [ ] **Compliance-reviewed** — auditability, data safety (no secrets/PII/raw data, §5),
      documented thresholds (§4).
- [ ] **Documented for handover** — a **developer handover** (`developer-handover.md`): how
      to build/run/test, design decisions (ADRs), known limitations and tech debt.
- [ ] **Distributable** — all artifacts produced in `.md` **and** `.html`
      (`python -m scripts.render_html`).
- [ ] **Signed off** — human approval recorded at the gate; nothing touching live systems
      proceeds without it.

## Why this exists

Real people review these outputs and real delivery will be handed to the team. A consistent,
evidenced gate is what turns "the AI says it's done" into something a developer can maintain,
a QA team can accept, and an auditor can defend.
