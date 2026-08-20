# Engagement state, artifact naming, placement & project memory - full detail

> Deferred from `docs/team-operating-guide.md` (open-core split, token plan Phase 1,
> 2026-08-18). The open-core keeps the four states, the state-file-is-the-record rule and
> the ⛔-said-out-loud rule; **read this file when creating an engagement workspace**
> (engage step 4 / a bookends `init`) **and again when entering the close** - it holds the
> lifecycle mechanics, the filename register, the placement table and the codebase-map
> curation rules.

## Engagement state & artifact naming (lifecycle discipline)

Born of a live failure (2026-07-22): an engagement paused on an unanswered clarification, the
close never ran, and an interim report with a final-sounding filename was read as the delivery
with QA never having run. A gate that only runs at close is no gate when the close never
happens - state must be visible **between** gates.

- **Every engagement is in exactly one state**, recorded in the START-HERE living index
  (`docs/templates/start-here.md`): **⏳ in progress** · **⛔ blocked - awaiting input** ·
  **🔒 closing** (the close is underway - close artifacts are legitimate work in progress) ·
  **✅ closed**. Only the close flips to ✅, and the close is where the DoD runs -
  mechanically: `set-status closed` runs the full gate itself and refuses on findings.
- **The state is machine-readable first (ADR-006).** The workspace's
  `artifacts/<slug>/engagement-state.json` is the authoritative lifecycle record (status,
  phase, outstanding, artifact inventory, decisions, gate answers, runtime probe,
  footprint) and **START-HERE.md is rendered from it** - never hand-edited (the render
  embeds a content hash; a hand-edit is an `INDEX-HAND-EDITED` finding, auto-fixed by
  re-render with the hand-edited text backed up). Create it with
  `<python> -m scripts.engagement_state init` at OPEN; update it only through the mutators
  (`set-status` · `set-phase` · `set-profile` · `add-artifact` · `add-outstanding` ·
  `resolve-outstanding` · `set-decision` · `set-team` · `finalise-artifacts` ·
  `set-footprint` · `log-note` · `add-ratification` · `ratify` · `set-active` ·
  `record-consent-outcome` · `set-runtime`), each of which re-validates
  and re-renders the index in the same command. The `profile` field (standard/light) records
  the USER's ceremony choice (`/engage-light`); light drops the delivery report (the
  summary email stays in EVERY profile, kept short in light) and upgrades to standard the
  moment scope outgrows it. **Outstanding holds ONLY open work** - completion notes and events go to the
  log (`log-note`), so convergence stays countable (at close, the cleared outstanding list
  is snapshotted into the log - a mistaken close stays reversible from disk). **Approvals
  are structured**: a decision
  awaiting the human is `add-ratification` (pending); only the human's grant justifies
  `ratify --by`; an artifact asserting a ratification the state records as pending is a
  `RATIFIED-CLAIM-PENDING` gate finding. **Session decisions persist**: the intake gate
  answers (`set-decision` for go-ahead / fix-cycle / data-attestation, plus
  review-scope / review-not-covered / review-mode on a review - the scope a reader needs to
  know was chosen, and what it excluded), the NON-granting
  consent outcome (`record-consent-outcome asked|declined` - a grant is not representable;
  it stays the human marker only, ADR-002) and the run-mode probe (`set-runtime`) are
  recorded when given and re-read on resume, never re-asked. Close ordering: `set-status
  closing` to enter the close window, then `set-team` and
  `finalise-artifacts` before `set-status closed` - a close with an empty team, interim
  artifact rows, or any DoD gate finding refuses (and rolls back). Mechanically checked
  (`STATE-INVALID`, `STATE-STALE-RENDER`,
  `STATE-MISSING`, `INDEX-HAND-EDITED`); the lifecycle hooks read the state before falling
  back to the legend-aware index parse,
  so a stale render can neither arm nor silence them. The state file must **never** carry a
  consent-like key - execution consent lives only in the human-created marker (ADR-002); the
  schema rejects it. Legacy engagements without a state file remain valid.
- **Engagements live in workspaces (ADR-008).** Each engagement owns `artifacts/<slug>/`
  (its state, index and artifacts); the root `ENGAGEMENTS.md`/`engagements.json` is a DERIVED
  registry regenerated on every mutation - never hand-edit it (`REGISTRY-STALE`). Several
  **Archiving (0.33.2):** a `.archive` marker file excludes any directory from every
  scanner, in place (no moves; `archive <slug>` / `--all-closed` / `unarchive`; the
  registry keeps a collapsed `Archived: N` line). Closed packs only - an open pack is
  refused (`--force` logs the exception; a bare hand-touched marker on an open pack is
  `ARCHIVED-OPEN`, warned not silent). Closed packs also store a scan fingerprint at
  close, so unchanged ones are skipped even without archiving. Several
  engagements may coexist at independent states: one is ACTIVE per session, recorded **on
  disk** in `artifacts/.active-engagement.json` (written by `init`, switched with
  `set-active`, cleared at close; ambiguous commands resolve to it) - name it in the
  banner and target it with `--slug`; a ⛔ parked sibling's stop-gate stays silent. Legacy
  flat packs keep working; `migrate` moves them into a workspace. In workspace mode
  nothing sits unchecked at the artifacts root: a new root file is `ORPHAN-ARTIFACT`
  (pre-existing flat files are grandfathered in `.dod-root-allowlist.json` - D2 ruling,
  ADR-010).
- **START-HERE is a living index** - created at engagement OPEN alongside the Engagement Brief
  (status ⏳), a row appended **the moment any artifact is written** (via `add-artifact`, which
  re-renders the `.md` + `.html`), the ⚠️-outstanding list kept current, verdict + footprint
  filled at close. It is never "written last": a stalled engagement must still show its true
  state to whoever opens the folder. Mechanically checked (`MISSING-INDEX`, `INDEX-NO-STATUS`,
  `STALE-INDEX`).
- **Atomicity - the index must LEAD reality, never trail it (survives compaction).** Writing an
  artifact and appending its START-HERE row are **one unit of work**: append the row (and set the
  status) in the **same turn** as the artifact, **before ending the turn** - never end a turn with
  an artifact on disk but the index not yet listing it. START-HERE is the engagement's **external
  memory** (Anthropic context-engineering): if Claude Code **compacts** the conversation, the
  transcript is summarised but START-HERE persists on disk, so it is what a resumed session reads
  back - it must reflect what has actually been done, not lag a turn behind. (Live failure
  2026-07-24: a code review compacted right after the brief was written but before its row was
  appended, leaving the index behind the true state.) The 0.17.0 DoD `Stop`-hook backstops this by
  flagging a stale index at turn-end, but only once START-HERE exists - author it index-first.
- **Pausing on a question = ⛔, said out loud.** Whenever a turn ends waiting on user input the
  team cannot proceed without: set START-HERE to ⛔ with the outstanding list (the unanswered
  question(s) AND every gate not yet run - "independent QA: not yet run"), and **end the turn
  stating plainly: "this engagement is NOT closed - outstanding: …"**. Never present interim
  work as a wrap-up; never let silence quietly become a close.
- **Interim artifacts declare themselves; the mutable STATUS lives in ONE place.** Every content
  artifact written before close opens with a one-line banner under its title: `> ⏳ INTERIM -
  engagement not closed; DoD checks have not run.` - **including the engagement brief**. But the
  mutable engagement **status** (⏳/⛔/✅) is owned by **exactly one document - START-HERE**: an
  artifact's banner *declares it is interim*, it must not become a second place that restates a
  status and then rots. **Remove the banner at close** - now **mechanically enforced**: a stale
  interim/in-progress banner left on any artifact once START-HERE is ✅ closed is a `STALE-STATUS`
  defect (auto-fixable), born of a live failure (2026-07-24: a brief's "in progress" banner
  survived to close and read as current). **The one exception is `START-HERE.md` itself**: its
  **Status** field carries the state, so it takes no banner.
- **Filename register - names may not imply finality early.** `delivery-report.md` (and any
  `final-*`) is the consolidated **close** artifact and may not exist before ✅
  (`FINAL-BEFORE-CLOSE`); the summary email likewise (`SUMMARY-BEFORE-CLOSE`). Interim outputs
  take **pass-scoped names**: `review-pass-1.md`, `qa-cycle-2.md`, `interim-findings-1.md` -
  never "engagement report" or another name a reader would take as the finished deliverable.
  **Reviews specifically:** interim passes are `review-pass-N.md`; at close the review is
  delivered either as a section of the consolidated `delivery-report.md` (default packaging)
  or, when "separate artifacts" is chosen, finalised to the canonical `REVIEW-<slug>.md`
  (`docs/review/output-format.md`) - so `REVIEW-<slug>.md` is a **close-name**, not written
  pre-close. Fixed names stay fixed: `engagement-brief`, `qa-handover`, `rtm`, `START-HERE`.
- **Resuming:** when the user answers, flip ⛔ back to ⏳, log the answer (decision log /
  clarification-rounds register), and continue to a real close - the outstanding list is the
  to-do list for getting there.

## Where every document lives (one placement rule - ADR-010)

Everything an engagement produces goes in **its own workspace `artifacts/<slug>/`** - flat
at the workspace root, plus one machine-readable lane. This table is the single reference;
skills point here rather than restating paths. Filenames are workspace-relative.

| Document / output | Canonical address in `artifacts/<slug>/` |
|---|---|
| Living index (generated - never hand-edit) | `START-HERE.md` + `.html` |
| Machine-readable state | `engagement-state.json` |
| Engagement brief | `engagement-brief.md` |
| BRD / FSD | `BRD-<slug>.md` / `FSD-<slug>.md` |
| Requirements traceability matrix | `rtm.md` |
| User stories | `user-stories.md` |
| Decision log | `decision-log.md` |
| Client-facing ADRs | `adr/ADR-NNN-<topic>.md` |
| Interim review passes | `review-pass-N.md` (close-only names never appear early) |
| Canonical review report (CLOSE-ONLY, D4) | `REVIEW-<slug>.md` (rendered from the findings pack at 🔒/✅ only) |
| Security audit / performance review reports | `SECURITY-AUDIT-<slug>.md` / `PERF-<slug>.md` |
| QA handover + QA evidence | `qa-handover.md` (or `qa-handover-<scope>.md`), evidence preserved beside it |
| Produced code + its tests + QA scripts | workspace root, tests/QA in the SAME scope as the code they verify (a grouping subfolder carries its own tests + QA handover - the gate checks per scope); code delivered into the working project's source tree follows the escalation rule instead |
| Delivery report (close-only) | `delivery-report.md` |
| Engagement-summary email (close-only) | `engagement-summary-<slug>.txt` (never rendered to HTML) |
| Findings packs / machine-readable source | `data/findings-*.jsonl` (validated recursively; excluded from the .html-sibling and index checks) |
| Standalone `/prepare-data` output (no engagement open) | `artifacts/data-prep/` (root lane, outside any workspace) |

Project-level (never per-engagement): the codebase map at `docs/codebase-map.md` or
`CODEBASE-MAP.md` (ADR-003), and the derived registry `artifacts/ENGAGEMENTS.md` /
`engagements.json`.

## The codebase map (project memory, curation rules)

**The codebase map is the working project's durable engagement memory** (ADR-003; template
`docs/templates/codebase-map.md`; default location `docs/codebase-map.md` in the working
project). Read at every engagement open, then added-to, corrected and deprecated at every
close (a DoD gate). **It maps the CODE, not the team's activity:** each entry is a durable
fact about how the codebase is built (architecture, data flow, decisions, quirks) that stays
true after this engagement's findings are fixed - not a findings recap, severity, review
disposition, or "what we did this time" (that goes to the §3 history row + the review
artifact). Reviews/audits especially tempt an activity-log map; capture the architecture
learned by reading the code instead. (Live failure 2026-07-23: a review produced a map that
summarised testing activity rather than the codebase - template §2 carries the ✅/❌ contrast.) **PM-written only** - subagents recommend entries in their reports; the
PM persists its own synthesis, never verbatim reviewed-code text and never data values,
secrets, PII or MNPI (§5). It is **advisory context, not enforcement** (the guard hooks stay
the only enforcement layer), kept under ~200 lines, with SHA anchors, as-of dates and 📊/🧠
tags so staleness stays visible. Hygiene: `python -m scripts.check_artifacts`.
