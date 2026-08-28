---
description: Build an end-to-end solution from a set of requirements (orchestrator-workers)
argument-hint: <path to requirements pack / BRD+FSD, or describe it>
disable-model-invocation: true
---

Under the PM (CLAUDE.md §6), deliver end to end from the requirements: **$ARGUMENTS**

**Scope note:** `/build-solution` is the full orchestrator-workers fan-out for a *multi-unit*
deliverable built from a requirements pack. For a *single* detection scenario (one rule,
spec → SME → build → review), use `/new-scenario` - the lean path - instead.

**The standard open applies before any unit is dispatched, even when this skill is invoked
directly.** Read `.claude/skills/.shared/engagement-bookends.md` and follow it - the Engagement
Brief and `engagement_state init` (unless `/engage` already wrote them) before step 1, the closing
bookend at the end.

Run the **orchestrator-workers** pattern, agile and iterative:

1. **Fill gaps flexibly - and right-size the spec chain first (2026-08-17 build review).**
   A **single-unit, non-detection, non-regulated** build DERIVES the light shape by default:
   an EARS-lite spec block inside the Engagement Brief replaces the BRD+FSD documents, and
   the crew is builder + `code-reviewer` + QA (the `/engage-light` scale) - state the derived
   shape at the gate for correction, don't ask. The full document chain (`/write-brd` then
   `/brd-to-fsd`) runs for multi-unit, detection-logic or regulated work, or when the user
   asks for the documents; skip whatever the user already provided. **Chained skills are
   dormant** - read `.claude/skills/<name>/SKILL.md` and follow it in this session, never the
   Skill tool (`.claude/skills/.shared/run-mode.md`). Same for `/handover` at step 7.
2. **Decompose** the FSD into discrete, independently buildable units. **Route each unit to
   the right builder by type** (CLAUDE.md §6): detection logic → `rules-developer`; data
   pipeline / ETL / transformation or utility script / infra → `platform-engineer`; analytics
   / data-quality / reconciliation / reporting → `data-analyst`; ML → `ml-engineer` +
   independent `model-validator`. **Give each unit an explicit, non-overlapping brief**
   (objective · scope boundaries / what other units own · inputs/artifacts to read · expected
   output **· the unit's in-scope FILE LIST and, when the project has one, the codebase map's
   PATH with "read it for context - do not enumerate the repo"** - point, never paste the map
   body; the same brief rule reviews use, and the enumeration guard denies a bare `find`
   mid-build) so units don't duplicate or leave gaps. Then chain each through `code-reviewer`; add
   `compliance-reviewer` when the unit is detection logic, touches regulated data, or documents
   thresholds (§4) - **not a default for every unit** (CLAUDE.md §4; operating guide routing
   table: "not every code review"). Independent units can run in parallel.
   **Price the plan at the go-ahead gate (2026-08-17):** beside the agent count and dispatch
   mechanism (operating guide §Orchestration discipline), state one order-of-magnitude money
   line derived from the unit list - roughly (builder pass + review pass) per unit at list
   price, QA on top, and **assume at least one fix→re-review cycle per unit** in the figure;
   add the budget-status line when a budget is recorded. **State execution-consent status and
   its consequence in the same gate line** - "consent declined → QA evidence will be 🧠
   inferred (written, not run), static-only DoD path" - so the plan's evidence level is agreed
   up front, never discovered at step 3.
3. **Test independently** - `qa-engineer` (not the builder) designs and runs tests
   appropriate to the deliverable: true-positive and false-positive cases for detection
   logic; input/output, schema and edge-case tests for pipelines/transforms; idempotency/
   error-path tests for scripts. Synthetic data only (§5); thresholds documented (§4).
   **Every QA pass gets a test-cycles row at the time it runs** (qa-handover §1, append-only);
   a Fail routes defects to the builder and the re-test is a **new pass row** - failed
   verdicts are never rewritten (operating guide, Outcome discipline 5).
4. **Review** - `code-reviewer` (deep) and, where it processes data at volume,
   `performance-reviewer`; add `compliance-reviewer` where the deliverable is detection logic,
   touches regulated data, or documents thresholds (§4) - **not a default for every build**.
   Loop fixes until no Critical remains - **brief the builder with EVERY currently-open finding
   from a review pass in one fix call, not a severity-filtered subset with a follow-up call for
   the rest.** Splitting one pass's findings into sequential same-severity-tier fix calls (fix
   Criticals, then a separate call for the Mediums, with no re-review in between and no stated
   reason for the gap) is pure overhead - each call re-spins a subagent and reloads context for
   findings the builder could have fixed together (2026-08-04 eval trace: `process-full-lifecycle`
   did exactly this). A NEW fix call is warranted when a **re-review** surfaces genuinely new
   findings, not to stagger one review's own findings by severity. **A fix that changes
   externally visible behaviour (a new failure mode, changed output, changed permissions)
   includes updating the FSD/README/docstrings in the SAME fix call** - docs currency is a
   standing coding-standards requirement, and a compliance reviewer will correctly bounce a
   behaviour change whose docs still describe the old behaviour, costing a second builder spawn
   just for the documentation half (2026-08-04 eval trace: `process-full-lifecycle`'s CMP-03
   fix shipped undocumented and needed a follow-up call once compliance caught it). **A user
   ruling that dispositions a finding is written into the findings pack BEFORE the next
   downstream review reads that pack** - do not persist the decision to engagement state and
   then hand a knowingly stale pack to the next reviewer, who must then flag the contradiction
   as a finding of its own (same trace: a ratified file-permissions decision left one finding's
   disposition stale, and compliance flagged the pack contradicting itself). If someone else
   must make the pack update, brief them with the decision text verbatim, the pack path, and
   the exact target value, so the call is a write, not a re-investigation.
   **Record each pass/fix/re-review hand-off in the Delivery Report's iteration log (§1a)
   as it happens**, journey strip included.
5. **Maintain the RTM** (`docs/templates/rtm.md`): every requirement → code → test →
   obligation. A gap is a blocker - surface it to the user. Record significant design decisions
   as **ADRs** (`docs/templates/adr.md`).
6. **Keep a status log**; return to the user at each gate with decisions and blockers.
7. **Meet the Definition of Done** (`docs/DEFINITION-OF-DONE.md`) and run `/handover`.
   **By default deliver one consolidated Delivery Report** (`docs/templates/delivery-report.md`
   - RTM, review, performance, compliance, QA, handover, change/ops as sections); split into
   separate artifacts only if asked. Save under `VSIT/engagements/`, as `.md` and rendered `.html`.
   Confirm the **project's test suite** passes (use the target's framework - `pytest`, Pester,
   JUnit/ScalaTest, Jest, etc. - not an assumed one) and record the exact command. Running tests
   needs the execution-consent gate (CLAUDE.md §7); if the guard blocks, ask the user to grant it
   (consent is human-only).

Stop for human approval before anything that touches live systems.
