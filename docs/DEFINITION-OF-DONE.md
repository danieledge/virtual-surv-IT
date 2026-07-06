# Definition of Done

A delivery is "done" only when it carries the evidence a real developer, QA reviewer and
auditor can rely on. The PM checks this gate before handover; `compliance-reviewer` verifies
it. Apply the items relevant to the deliverable type - not every item fits every task.

> **How these gates are enforced (note).** Most items below are **prompt-enforced and
> eval-sampled**, not CI-enforced: the PM and `compliance-reviewer` attest them, and the eval
> harness (`/run-evals`) samples for drift - CI cannot see engagement deliverables because
> `artifacts/` is deliberately git-ignored. The mechanical exceptions: the repo's own code is
> CI-tested (pytest, lint, secret-scan, no-raw-data), and the **Distributable** +
> **Engagement-summary email** items have a one-command check the PM runs at this gate:
> `python -m scripts.check_artifacts` (every `artifacts/*.md` has a rendered `.html` sibling;
> a summary `.txt` exists). Treat the rest as evidenced claims to spot-check, not guarantees.
>
> **Changes to the team itself** (prompts, skills, agent definitions) gate on the eval harness:
> full pytest (contract + docs-consistency tests) plus a live golden-slice spot check for prompt
> changes. A change that drops a previously passing golden case does not land.

## Every delivery

- [ ] **Traceable** - each requirement links requirement → design → code → test → obligation
      in the RTM (requirements traceability matrix, `docs/templates/rtm.md`).
- [ ] **Open questions dispositioned** - every open question raised upstream (spec/BRD/review, e.g.
      a BA's questions for an SME) is **formally closed** by its owner (✅ answered / ⏭️ needs
      deployment input / 🔴 open-decision-required) in a tracked decision log - not left dangling or
      "touched in passing". Any 🔴 / blocking item is reflected in the verdict.
- [ ] **Tested** - tests appropriate to the deliverable exist and **pass**:
  - detection logic → true-positive **and** false-positive cases;
  - pipeline/transform → input/output, schema and edge-case tests, **including a completeness
    reconciliation** (source vs output record counts / control totals) for anything that
    extracts or converts data;
  - script → idempotency and error-path tests.
- [ ] **Independently QA'd** - `qa-engineer` (not the builder) has produced a **QA handover**
      (`qa-handover.md`) evidencing what ran, results, coverage, gaps and residual risk.
- [ ] **Code-reviewed (deep)** - `code-reviewer` ran; **no Critical findings open**;
      filtered/ reported counts recorded; every finding has a **disposition** (fixed / open /
      accepted / deferred) and the review carries a **🔵 Developer guidance - improving future
      code** section (always present, even on a clean pass).
- [ ] **Performance-reviewed** - where it processes data at volume, `performance-reviewer`
      assessed it against expected volumes. **Static by default** (🧠 inferred from code structure);
      📊 measured profiling evidence only when execution was consented (§7) - the verdict must state
      which basis it carries.
- [ ] **Compliance-reviewed** - auditability, data safety (no secrets/PII/raw data, §5),
      documented thresholds (§4).
- [ ] **Documented for handover** - a **developer handover** (`developer-handover.md`): how
      to build/run/test, design decisions (ADRs - architecture decision records), known
      limitations and tech debt. When
      handing to an IT team with its own controls, also draft the artifacts those controls
      consume (**change request**, **ops runbook + release notes**) with approval/owner
      fields left for the IT team - the team drafts, it does not approve or deploy.
- [ ] **Handover docs are clear & usable, not just present** - a developer who has never seen
      the code could build, run and safely change it from the doc **alone** (no tribal knowledge,
      no unexplained jargon, commands copy-pastable). `compliance-reviewer` checks usability at
      this gate, not merely existence.
- [ ] **Distributable** - evidence produced in `.md` **and** `.html`
      (`python -m scripts.render_html`). **By default one consolidated Delivery Report**
      (`docs/templates/delivery-report.md`) holds all sections; split into separate artifacts
      only if a control requires it.
- [ ] **Engagement-summary email** - the PM (**Morgan**) has written a short email-format cover
      note summarising what was done and where it stands, saved as a **`.txt` in `artifacts/`**
      (`docs/templates/engagement-summary-email.md`). Address it to the requester **only if the name
      is known** - otherwise open with "Hi,"; sign off as Morgan. (It's an email, so it stays `.txt`
      and is the one artifact not rendered to HTML.)
- [ ] **Signed off** - human approval recorded at the gate; nothing touching live systems
      proceeds without it.

## Why this exists

Real people review these outputs and real delivery will be handed to the team. A consistent,
evidenced gate is what turns "the AI says it's done" into something a developer can maintain,
a QA team can accept, and an auditor can defend.
