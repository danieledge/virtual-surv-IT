# Definition of Done

A delivery is "done" only when it carries the evidence a real developer, QA reviewer and
auditor can rely on. The PM checks this gate before handover; `compliance-reviewer` verifies
it. Apply the items relevant to the deliverable type - not every item fits every task.

> **The gate is a FIX-LIST, not a report.** These checks are on the **team's own output**, so a
> defect in that output that has a deterministic remedy is the team's to **fix**, not the user's
> to be told about. Sort every gate/critique finding into two tiers:
>
> - **AUTO-FIX (correct it and re-run - never surface as a delivered failure):** a missing
>   `.md`/`.html` sibling (render it) · an off-roster or wrong-role persona name (correct to the
>   canonical roster - `ROSTER-UNKNOWN`/`ROSTER-ROLE-MISMATCH`) · a missing interim banner or a
>   "final/v1.0" asserted while the engagement is still open (set the correct state) · a
>   non-portable absolute path cited as a source (relativise or mark it external) · an incomplete
>   or miscounted source index (recount) · a missing per-finding evidence tag where the legend is
>   defined (add it). Fix, note the correction in one line, move on.
> - **ESCALATE / ASK (the team cannot resolve it alone - pause and ask via the question tool):**
>   a rationale contradicted by the evidence ("the email says X but the artifact says Y") · a
>   closure or sign-off resting on authority the team cannot verify (verbal only, no written
>   authority on file) · any scope or acceptance judgement. These need a human decision - surface
>   them clearly; do **not** guess.
>
> Handing the user a self-correctable defect (a missing render, a wrong reviewer name) as a
> "documentation-standards failure" is itself a process failure - it is exactly the kind of thing
> the team is here to fix silently. (Live lesson 2026-07-23: a delivery report's self-audit listed
> six auto-fixable defects - a missing `.md` sibling, fabricated reviewer names, a missing interim
> banner - as failures for the user, instead of correcting them and re-checking.)

> **How these gates are enforced (note).** Most items below are **prompt-enforced and
> eval-sampled**, not CI-enforced: the PM and `compliance-reviewer` attest them, and the eval
> harness (`/run-evals`) samples for drift - CI cannot see engagement deliverables because
> `artifacts/` is deliberately git-ignored. The mechanical exceptions: the repo's own code is
> CI-tested (pytest, lint, secret-scan, no-raw-data), and the **Distributable**,
> **Engagement-summary email**, **Indexed** and **Stateful** items have a one-command check
> the PM runs at this gate - and can run at ANY point mid-engagement, since the living index
> makes the gate meaningful before close: `python -m scripts.check_artifacts` (every
> `artifacts/*.md` has a rendered `.html` sibling; the START-HERE index exists, has a status,
> and lists everything; close-only artifacts don't exist early; a summary `.txt` exists at
> close). Treat the rest as evidenced claims to spot-check, not guarantees.
>
> **Changes to the team itself** (prompts, skills, agent definitions) gate on the eval harness:
> full pytest (contract + docs-consistency tests) plus a live golden-slice spot check for prompt
> changes. A change that drops a previously passing golden case does not land.

## Every delivery

- [ ] **Briefed** - the engagement **opens** with an **Engagement Brief**
      (`docs/templates/engagement-brief.md`, `.md` + `.html`) capturing the target/scope, the
      decisions and assumptions taken, and the plan - **right-sized** to the work (a few lines for a
      small review, a fuller brief for a build). Present for **every** engagement and every entry
      point: written by `/engage`, or by the invoked skill's *standard open* when it is called
      directly. It is the opening bookend to the engagement-summary email below.
- [ ] **Traceable** - each requirement links requirement → design → code → test → obligation
      in the RTM (requirements traceability matrix, `docs/templates/rtm.md`).
- [ ] **Open questions dispositioned** - every open question raised upstream (spec/BRD/review, e.g.
      a BA's questions for an SME) is **formally closed** by its owner (✅ answered / ⏭️ needs
      deployment input / 🔴 open-decision-required) in a tracked decision log - not left dangling or
      "touched in passing". Any 🔴 / blocking item is reflected in the verdict. The
      **clarification-rounds register** (elicitation template §10) shows each round's who /
      when / what-changed trail, append-only.
- [ ] **Tested** - tests appropriate to the deliverable exist and **pass**:
  - detection logic → true-positive **and** false-positive cases;
  - pipeline/transform → input/output, schema and edge-case tests, **including a completeness
    reconciliation** (source vs output record counts / control totals) for anything that
    extracts or converts data;
  - script → idempotency and error-path tests.
- [ ] **Independently QA'd** - `qa-engineer` (not the builder) has produced a **QA handover**
      (`qa-handover.md`) evidencing what ran, results, coverage, gaps and residual risk -
      **with the full cycle history**: one test-cycles row per pass (append-only, failed
      verdicts preserved) and defect lifecycle (raised in pass → routed to → fix evidence →
      verified fixed in pass). A multi-pass engagement whose docs read first-pass-clean fails
      this gate.
- [ ] **Code-reviewed (deep)** - `code-reviewer` ran; **no Critical findings open**;
      filtered/ reported counts recorded; every finding has a **disposition** (fixed / open /
      accepted / deferred) and the review carries a **🔵 Developer guidance - improving future
      code** section (always present, even on a clean pass).
- [ ] **Critiqued against the named standard** - before handover, a critic **who is not the
      author** checked each major deliverable against its profession's named criteria
      (findings → the 5 C's shape in `docs/review/output-format.md`; requirements → BABOK
      quality criteria; QA evidence → ISO/IEC 29119-shaped completeness; validation reports →
      SR 11-7-style documentation expectations), and the deliverable records which standard
      it was checked against (operating guide, Outcome discipline 6). Ungrounded
      "second-look" passes do not satisfy this gate.
- [ ] **Audit-compatible skeleton (default, every review depth)** - the review output carries
      document control, scope at a stated commit, reviewer independence, methodology + tooling
      coverage, the findings register with dispositions, filtered transparency and a
      **limitations & residual risk** section (operating guide §Outcome discipline 4;
      `docs/review/output-format.md`). Governance extras (control mappings, validation
      opinions, ops/change artifacts) are **opt-in** via the artifact menu - and outputs are
      framed as consumable by audit/model-governance reviewers, never as compliance claims.
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
- [ ] **Indexed - a LIVING START-HERE entry point** - `artifacts/START-HERE.md` (template
      `docs/templates/start-here.md`) is **created at engagement open** alongside the brief,
      gains a row **the moment each artifact is written**, and is finalised at close: verdict,
      reading order, every artifact listed with one line of purpose, and the open items a
      reader should know about. Never "written last" - a stalled engagement must still show
      its state. Mechanically checked (`MISSING-INDEX`, `STALE-INDEX`).
- [ ] **Stateful - never silently dangling** - the engagement's state (⏳ in progress ·
      ⛔ blocked - awaiting input · ✅ closed) is recorded in START-HERE and kept truthful. A
      pause on unanswered input sets ⛔ with the outstanding list (questions + gates not yet
      run) and the turn says plainly "NOT closed - outstanding: …". Interim artifacts carry
      the interim banner and **pass-scoped names** (`review-pass-N`, `qa-cycle-N`,
      `interim-*`); `delivery-report.md` / `final-*` and the summary email exist **only at ✅
      close**. Mechanically checked (`INDEX-NO-STATUS`, `FINAL-BEFORE-CLOSE`,
      `SUMMARY-BEFORE-CLOSE`). (Lesson, 2026-07-22: a blocked engagement's interim report was
      read as the delivery and QA never ran - the close-time gates never fired.)
- [ ] **Distributable** - evidence produced in `.md` **and** `.html`
      (`python -m scripts.render_html`). **By default one consolidated Delivery Report**
      (`docs/templates/delivery-report.md`) holds all sections; split into separate artifacts
      only if a control requires it.
- [ ] **Engagement-summary email** - the PM (**Morgan**) has written a short email-format cover
      note summarising what was done and where it stands, saved as a **`.txt` in `artifacts/`**
      (`docs/templates/engagement-summary-email.md`). **Written at ✅ close only** - its existence
      is the signal the engagement closed, so a blocked/in-progress engagement must not have one
      (`SUMMARY-BEFORE-CLOSE`). Address it to the requester **only if the name is known** -
      otherwise open with "Hi,"; sign off as Morgan. (It's an email, so it stays `.txt` and is
      the one artifact not rendered to HTML.)
- [ ] **Codebase map updated** - the working project's codebase map (`docs/codebase-map.md`,
      template `docs/templates/codebase-map.md`, decision ADR-003) was **read at open and
      updated at close**: entries added with 📊/🧠 tags, dates and SHA anchors; stale or wrong
      entries corrected or moved to Deprecated (never silently dropped); engagement-history
      row appended. PM-written only; advisory-only; no PII/MNPI/secrets/raw-data content (§5).
      Mechanical hygiene is part of the `python -m scripts.check_artifacts` gate.
- [ ] **Signed off** - human approval recorded at the gate; nothing touching live systems
      proceeds without it.

## Why this exists

Real people review these outputs and real delivery will be handed to the team. A consistent,
evidenced gate is what turns "the AI says it's done" into something a developer can maintain,
a QA team can accept, and an auditor can defend.
