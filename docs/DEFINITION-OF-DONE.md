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
>   canonical roster - `ROSTER-UNKNOWN`/`ROSTER-ROLE-MISMATCH`) · a roster name readable as a real
>   person or an agent sharing a sign-off line with a human (add the 🤖 / Virtual Surveillance IT
>   attribution, split the line - `AGENT-UNMARKED`/`AGENT-HUMAN-COMBINED`) · a missing interim banner or a
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
> `VSIT/engagements/` is deliberately git-ignored. The mechanical exceptions: the repo's own code is
> CI-tested (pytest, lint, secret-scan, no-raw-data), and the **Distributable**,
> **Engagement-summary email**, **Indexed** and **Stateful** items have a one-command check
> the PM runs at this gate - and can run at ANY point mid-engagement, since the living index
> makes the gate meaningful before close: `python -m scripts.check_artifacts --fix`, run per
> engagement workspace `VSIT/engagements/<slug>/` (ADR-008/ADR-010; a legacy flat pack is checked the
> same way). **`--fix`** mechanically resolves the auto-fixable defects (render missing HTML;
> rename a mis-typed email and sync the state; re-render a stale or hand-edited index from the
> state, backing the hand-edited text up; render the close-only `REVIEW-<slug>.md` from its
> findings pack during 🔒/✅) so the close doesn't depend on the model remembering. Output is
> forced to UTF-8 so it can't crash a Windows console. Treat the rest as evidenced claims to
> spot-check, not guarantees.
>
> **The machine-readable state is the record (ADR-006).** Each workspace's
> `engagement-state.json` is authoritative - status (⏳ in_progress · ⛔ blocked · 🔒 closing ·
> ✅ closed), phase, outstanding, artifact inventory, decisions and gate answers, the
> non-granting consent outcome, the runtime probe, footprint - and `START-HERE.md` is its
> GENERATED view (never hand-edit; the render embeds state- and content-hashes). The root
> registry (`ENGAGEMENTS.md`/`engagements.json`) is derived; the session's ACTIVE engagement is
> recorded on disk (`.active-engagement.json`). **The close is an evidenced state, not a
> claim**: `set-status closing` marks the close window (close artifacts become legitimate work
> in progress), and `set-status closed` runs this full mechanical gate itself and REFUSES,
> rolling back, on any finding - the cleared outstanding list is snapshotted into the log first.
>
> **Finding codes (the full mechanical register):** `MISSING-HTML` · `MISSING-INDEX` ·
> `INDEX-NO-STATUS` · `STALE-INDEX` · `INDEX-HAND-EDITED` · `FINAL-BEFORE-CLOSE` (incl. the
> close-only `REVIEW-*.md`) · `SUMMARY-BEFORE-CLOSE` · `MISSING-SUMMARY-EMAIL` ·
> `SUMMARY-WRONG-EXT` · `STALE-STATUS` · `STALE-DOCSTATUS` · `CODE-NO-QA` / `CODE-NO-TESTS`
> (scoped per folder - a sibling engagement's QA never vouches) · `FINDING-NO-IMPACT` ·
> `FINDINGS-CWORD-LABELS` · `FINDINGS-INVALID` · `FINDINGS-NO-DEV-GUIDANCE` (a review-shaped
> artifact - has `## Findings` - missing or leaving empty the mandatory `## 🔵 Developer
> guidance` section; audit finding #2, 2026-07-30) ·
> `ROSTER-UNKNOWN` / `ROSTER-ROLE-MISMATCH` ·
> `AGENT-UNMARKED` / `AGENT-HUMAN-COMBINED` · `EMAIL-NOT-MORGAN` / `EMAIL-AGENT-UNMARKED`
> (the summary email is always FROM Morgan; every roster name in it carries a 🤖-marked
> mention) · `RATIFIED-CLAIM-PENDING` ·
> `REVIEW-FINGERPRINT-GAP` · `RTM-UNRESOLVED` / `RTM-INCOMPLETE` (a pack that HAS an
> `rtm.md`: a Code/Test cell pointing at a file that does not exist on disk, or a
> requirement with neither a cited obligation nor a gap disposition, or a table that does
> not parse - the traceability spine checked by `python -m scripts.validate_rtm`, which
> also reports the scope-dependent `RTM-ORPHAN-OBLIGATION` / `RTM-ORPHAN-TEST` sweeps this
> gate deliberately leaves to the review gate; no RTM at all is never a finding) ·
> `STATE-MISSING` / `STATE-INVALID` / `STATE-STALE-RENDER` ·
> `REGISTRY-STALE` / `REGISTRY-HTML-STALE` (the registry's HTML mirror is written
> best-effort, so its freshness is checked explicitly) · `STALE-FINDINGS-RENDER` /
> `COUNT-MISMATCH` (the rendered `REVIEW-<slug>.md`'s finding IDs and disposition tally no
> longer match the current `data/findings-<slug>.jsonl` pack - "one authoritative number
> everywhere," mechanised where a marker exists to check it; audit finding #3, 2026-07-30) ·
> `NESTED-PACK` (a pack
> initialised inside another workspace; init now refuses the shape) · `ARCHIVED-OPEN`
> (a `.archive` marker on a pack that never passed the close gate - warned, never a
> silent skip; 0.33.2) · `FLAT-PACK-UNMIGRATED` · `ORPHAN-ARTIFACT` (workspace-mode root files;
> pre-existing ones grandfathered per the D2 ruling) · map hygiene: `MAP-TOO-LONG` ·
> `MAP-NO-ASOF` / `MAP-NO-ANCHOR` · `MAP-STALE-ANCHOR` / `MAP-STALE` (staleness budget) ·
> `MAP-ENTRY-NO-ASOF` / `MAP-ENTRY-NO-ANCHOR` / `MAP-STALE-ENTRY-ANCHOR` · `MAP-NO-BASIS` ·
> `MAP-SECRET`.
>
> **Scan scope (0.33.2).** Directories carrying a `.archive` marker are excluded from
> every scan (archive-in-place; `engagement_state archive <slug>` / `--all-closed`,
> `unarchive` to reverse). A ✅ closed pack whose stat-only `scan_fingerprint`
> (stored at its gate-passing close) still matches is skipped without content reads -
> the verification it passed at close stands until a deliverable changes.
>
> That same mechanical check also ships as a **warn-first `Stop` hook** (`scripts/dod_stop_gate.py`),
> wired into **both** tracked hook files - `.claude/settings.json` (repo-as-project) and
> `hooks/hooks.json` (installed-plugin) - so it is active for every user with no per-user setup. It
> runs the check **automatically** whenever a turn ends with an engagement still gated (a
> workspace ⏳/🔒; the flat pack also on ⛔), plus the registry and root-orphan scans - so "the
> close never ran, so the gate never ran" (the 2026-07-22 failure) can
> no longer happen silently. It **nudges once** and does not hard-block (it is a backstop, not a
> trap); this implements `docs/internal/research-virtual-team.md` refinement #4 ("verification as hooks, not
> prompts"). The three always-on **safety** guard hooks are separate and unchanged.
>
> **Changes to the team itself** (prompts, skills, agent definitions) gate on the eval harness:
> full pytest (contract + docs-consistency tests) plus a live golden-slice spot check for prompt
> changes. A change that drops a previously passing golden case does not land. **This gate is now
> mechanical at the release boundary**: `dev` → `main` promotion requires a committed
> `evals/eval-baseline-<version>.md` record that is *fresher than the last prompt commit*, verified
> by `python -m scripts.release_gate` (see CONTRIBUTING.md "Promotion") - a documented gate nobody
> runs is decoration (2026-07-24 review: nine prompt-touching releases had shipped with no eval run).

## Every delivery

- [ ] **Briefed** - the engagement **opens** with an **Engagement Brief**
      (`docs/templates/engagement-brief.md`, `.md` + `.html`) capturing the target/scope, the
      decisions and assumptions taken, and the plan - **right-sized** to the work (a few lines for a
      small review, a fuller brief for a build). Present for **every** engagement and every entry
      point: written by `/engage`, or by the invoked skill's *standard open* when it is called
      directly. It is the opening bookend to the engagement-summary email below.
- [ ] **Traceable** - each requirement links requirement → design → code → test → obligation
      in the RTM (requirements traceability matrix, `docs/templates/rtm.md`). Regulatory
      citations are ON by default project-wide; when a project's `team-preferences.json`
      sets `regulatory_citations: false`, the obligation link is stated as declined rather
      than omitted - the RTM still traces requirement → design → code → test.
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
      **at a declared LEVEL** (2026-08-20; `engagement_state set-qa-depth quick|deep|audit`).
      The level tiers **breadth only**: existence, independence of the builder, evidence
      preservation and the per-deliverable-type test minima hold at every level, there is no
      `none`, and "run the COMPLETE suite" stays literal. **`quick` closes `DoD: PARTIAL - QA
      scope reduced`** with the uncovered classes named in residual risk and the close
      offering the upgrade ("run the deep pass → verdict upgrades") - mechanically enforced by
      `QA-QUICK-NOT-PARTIAL`, so a cheap pass can never read as a full one, and
      `QA-LEVEL-UNDECLARED` when a handover exists with no level recorded. Absence of a level
      is never "quick" -
      **with the full cycle history**: one test-cycles row per pass (append-only, failed
      verdicts preserved) and defect lifecycle (raised in pass → routed to → fix evidence →
      verified fixed in pass). A multi-pass engagement whose docs read first-pass-clean fails
      this gate. **QA evidence is preserved, not deleted**: independent test suites and run
      evidence survive under `VSIT/engagements/` (file or content hash) - an independence claim whose
      evidence was deleted is unfalsifiable and fails this gate. A **📊 measured** tag needs a
      surviving artifact (output, log, tool cache); where nothing survives, the claim is
      retagged **🧠 inferred** before close (2026-07-25 independent review: "600 randomised
      runs" and three of five analysers were measured-tagged with no artifact on disk).
- [ ] **Code-reviewed (deep)** - `code-reviewer` ran; **no Critical findings open**;
      filtered/ reported counts recorded; every finding has a **disposition** (fixed / open /
      accepted / deferred) and the review carries a **🔵 Developer guidance - improving future
      code** section (the heading is always present, even on a clean pass). **Where the
      deliverable contains no code** - an analysis, an investigation, a policy or threshold
      review - that section states in one line that it does not apply and why; it is never
      filled with invented coding advice (`docs/review/output-format.md`).
- [ ] **Unattended runs close PARTIAL** - an engagement the human authorised as unattended
      (`--auto`) reaches every line on this list **except human sign-off**, and must never
      record itself as signed off. It closes **PARTIAL with "human sign-off" outstanding**,
      and carries the **assumption ledger** - every question it answered on its own
      judgement, with its reasoning - in the delivery report and one ticket comment.
      Mechanically checked (`AUTO-NOT-PARTIAL`, `AUTO-LEDGER-MISSING`); the flag itself is
      recorded by the launcher, not by the run. Detail: `.claude/skills/engage/references/auto-mode.md`.
- [ ] **Critiqued against the named standard** - **opt-in, off by default**
      (`VSIT/config/preferences.json` `standards_critique`, project-wide, configurable via
      `/preferences` or the installer - same mechanism as `regulatory_citations`, opposite
      default: this is a full second review pass over an already-finished deliverable, not a
      universal expectation). **When on:** before handover, a critic **who is not the
      author** checked each major deliverable against its profession's named criteria
      (findings → the 5 C's shape in `docs/review/output-format.md`; requirements → BABOK
      quality criteria; QA evidence → ISO/IEC 29119-shaped completeness; validation reports →
      SR 11-7-style documentation expectations), and the deliverable records which standard
      it was checked against (operating guide, Outcome discipline 6). Ungrounded
      "second-look" passes do not satisfy this gate. **When off,** this item is **N/A, not a
      failure** - say so plainly rather than silently omitting it.
- [ ] **Audit-compatible skeleton (default, every review depth)** - the review output carries
      document control, scope at a stated commit, reviewer independence, methodology + tooling
      coverage, the findings register with dispositions, filtered transparency and a
      **limitations & residual risk** section (operating guide §Outcome discipline 4;
      `docs/review/output-format.md`). Governance extras (control mappings, validation
      opinions, ops/change artifacts) are **opt-in** via the artifact menu - and outputs are
      framed as consumable by audit/model-governance reviewers, never as compliance claims.
- [ ] **Independent synthesis read (Audit depth)** - for an **Audit-depth** engagement, the
      consolidated pack (`delivery-report` / audit artifact) was read by an **independent** reviewer
      (`compliance-reviewer`, *not* the PM who authored the synthesis) for internal consistency,
      unsupported claims, evidence-tag coherence and whether the verdict follows from the findings
      register - the one check the author cannot reliably run on its own output (`/audit-review`
      step 6). Fix or escalate before ✅.
- [ ] **Performance-reviewed** - where it processes data at volume, `performance-reviewer`
      assessed it against expected volumes. **Static by default** (🧠 inferred from code structure);
      📊 measured profiling evidence only when execution was consented (§7) - the verdict must state
      which basis it carries.
- [ ] **Compliance-reviewed** - **where the deliverable is detection logic, touches regulated
      data, or documents thresholds (§4)**, `compliance-reviewer` ran the full auditability/§4/§5
      pass (CLAUDE.md §4; not a default for every build - operating guide routing table says so
      explicitly: "not every code review"). Every deliverable, regardless of type, still carries
      the universal self-check: no secrets/PII/raw data in the repo (§5).
- [ ] **Documented for handover** - **where the deliverable ships new or changed code**, a
      **developer handover** (`developer-handover.md`): how to build/run/test, design
      decisions (ADRs - architecture decision records), known limitations and tech debt. When
      handing to an IT team with its own controls, also draft the artifacts those controls
      consume (**change request**, **ops runbook + release notes**) with approval/owner
      fields left for the IT team - the team drafts, it does not approve or deploy.
      **A review-only deliverable (existing code, nothing built or changed by the team) does
      not produce a developer handover** - the review's own findings register and the
      mandatory 🔵 Developer guidance section are the handover. Applies identically under
      `/engage` and `/engage-light` - this is a deliverable-type condition, not a profile one.
- [ ] **Handover docs are clear & usable, not just present** - *where a developer handover was
      produced*, a developer who has never seen the code could build, run and safely change it
      from the doc **alone** (no tribal knowledge, no unexplained jargon, commands
      copy-pastable). `compliance-reviewer` checks usability at this gate, not merely
      existence.
- [ ] **Indexed - a LIVING, GENERATED START-HERE entry point** - the workspace's
      `VSIT/engagements/<slug>/START-HERE.md` (render shape: `docs/templates/start-here.md`) is
      **rendered from `engagement-state.json` at engagement open** (`engagement_state init`)
      alongside the brief, gains a row **the moment each artifact is written**
      (`add-artifact`, in the same turn), and is finalised at close: verdict,
      reading order, every artifact listed with one line of purpose, and the open items a
      reader should know about. Never "written last" - a stalled engagement must still show
      its state - and **never hand-edited** (ADR-006: mutate the state; the render is
      hash-verified). Mechanically checked (`MISSING-INDEX`, `STALE-INDEX`,
      `STATE-STALE-RENDER`, `INDEX-HAND-EDITED`, `REGISTRY-STALE`).
- [ ] **Stateful - never silently dangling** - the engagement's state (⏳ in progress ·
      ⛔ blocked - awaiting input · 🔒 closing · ✅ closed) lives in `engagement-state.json`
      and is kept truthful. A
      pause on unanswered input sets ⛔ with the outstanding list (questions + gates not yet
      run) and the turn says plainly "NOT closed - outstanding: …". Interim artifacts carry
      the interim banner and **pass-scoped names** (`review-pass-N`, `qa-cycle-N`,
      `interim-*`); `delivery-report.md` / `final-*` / `REVIEW-<slug>.md` and the summary
      email exist **only from 🔒 closing on** - and the flip to ✅ is gate-verified:
      `set-status closed` runs the full mechanical check and refuses on findings. Session
      decisions persist on disk (the gate answers as `decisions`, the NON-granting consent
      outcome, the `runtime` probe, the ACTIVE marker), so a resumed session re-reads rather
      than re-asks. Mechanically checked (`INDEX-NO-STATUS`, `FINAL-BEFORE-CLOSE`,
      `SUMMARY-BEFORE-CLOSE`, `STATE-INVALID`). (Lesson, 2026-07-22: a blocked engagement's
      interim report was
      read as the delivery and QA never ran - the close-time gates never fired.)
- [ ] **Distributable** - evidence produced in `.md` **and** `.html`
      (`python -m scripts.render_html`). **By default one consolidated Delivery Report**
      (`docs/templates/delivery-report.md`) holds all sections; split into separate artifacts
      **Single-deliverable carve-out (2026-08-18):** when one artifact already carries the engagement's substance, it IS the delivery - closing block appended to it, no separate wrapper report, no invented executive summary; the summary email still closes the engagement (bookends §Single-deliverable close).
      only if a control requires it.
- [ ] **Reconciled at close** - before START-HERE flips to ✅, every document the engagement
      produced or touched (including code-adjacent ones: deliverable README, module
      docstrings) is re-opened and reconciled to the FINAL state: one authoritative set of
      counts/ranges/finding enumerations, late-cycle changes propagated, struck citations
      swept from every file, no prose referencing removed interim state, and document-control
      Status fields closed out (or explicitly "pending human sign-off"). Procedure: the close
      checklist's "Close-time reconciliation sweep"; Status fields under a CLOSED index are
      mechanically checked (`STALE-DOCSTATUS`). (Lesson, 2026-07-25: a fix-cycle-1 handover
      and README shipped "final" in a fix-cycle-2 pack, with a struck citation still live.)
- [ ] **Engagement-summary email** - the PM (**Morgan**) has written a short email-format cover
      note summarising what was done and where it stands, saved as a **`.txt` in the
      workspace `VSIT/engagements/<slug>/`**
      (`docs/templates/engagement-summary-email.md`). **Written in the close window only**
      (🔒 closing → ✅) - its existence
      is the signal the engagement is closing/closed, so a blocked/in-progress engagement must
      not have one
      (`SUMMARY-BEFORE-CLOSE`). Address it to the requester **only if the name is known** -
      otherwise open with "Hi,"; sign off as Morgan. (It's an email, so it stays `.txt` and is
      the one artifact not rendered to HTML.)
- [ ] **Codebase map updated** - the working project's codebase map (`VSIT/shared/map.md`,
      template `docs/templates/codebase-map.md`, decision ADR-003) was **consulted at open**
      (header + §3 history loaded at turn 0; full §2 sections read just-in-time when relied on -
      not pre-loaded, per ADR-003) **and updated at close**: entries added with 📊/🧠 tags, dates
      and SHA anchors; stale or wrong
      entries corrected or moved to Deprecated (never silently dropped); engagement-history
      row appended - in EVERY profile (light keeps new entries minimal, never skips the row
      or corrections). PM-written only; advisory-only; no PII/MNPI/secrets/raw-data content
      (§5). Mechanical hygiene (size, header + per-entry provenance, anchor resolution and
      the staleness budget, basis tags, secrets) is part of the
      `python -m scripts.check_artifacts` gate.
- [ ] **Signed off** - human approval recorded at the gate; nothing touching live systems
      proceeds without it.

## When execution consent is withheld (static-only mode)

The **Tested** and **Independently QA'd** items require *running* code, but execution is **off by
default** (§7) and only a **human** can grant it (creating `.claude/.exec-consent` or setting
`CST_ALLOW_EXEC=1` - the model is blocked from writing either, so the intake "yes" is *intent, not
the grant*). If consent is not granted for an engagement that ships code, those two items **cannot
be met** - and the gate must say so honestly rather than deadlock or overstate "done":

- `qa-engineer` still **authors** the full test plan and test code, but the run is blocked - the QA
  verdict is **🧠 inferred (tests written, not executed)**, never a pass.
- The delivery is marked **DoD: PARTIAL - not independently verified by execution**, with
  **untested code** named as the top item in **limitations & residual risk**.
- The engagement may close (✅) as a *static* delivery **only if** this partial state is stated
  plainly in the START-HERE verdict and the summary email - it may **not** claim "Tested" or
  "independently QA'd". Close every such engagement by offering the one action that lifts it: the
  user grants consent, the team runs the complete suite, and the verdict upgrades.

This is the honest way out of the static-only default; it is **not** a licence to skip QA when
consent **is** available (operating guide §4a - deliverable code ships with tests and an
independent QA pass, no workflow exempt).

## Why this exists

Real people review these outputs and real delivery will be handed to the team. A consistent,
evidenced gate is what turns "the AI says it's done" into something a developer can maintain,
a QA team can accept, and an auditor can defend.
