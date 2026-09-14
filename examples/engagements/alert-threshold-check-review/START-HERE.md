# START HERE - Code review: alert_threshold_check.py

> **Generated view - do not hand-edit.** The machine-readable source of truth is
> [`engagement-state.json`](engagement-state.json) (schema v1, ADR-006). Update the
> state through any state command and this file re-renders; a stale
> render is a DoD finding (`STATE-STALE-RENDER`).

| | |
|---|---|
| **Engagement** | Code review: alert_threshold_check.py |
| **Status** | ✅ CLOSED 2026-09-14 |
| **Opened** | 2026-09-14 |
| **Requested by** | unknown |
| **Profile** | standard |
| **Phase** | close |
| **Verdict** | Not yet fit for a production alerting job (static review, execution declined) |
| **Team** | Morgan (PM), Pip (review-scorer), Ravi (code-reviewer), Layla (compliance-reviewer), Kenji (platform-engineer), Linh (qa-engineer) |
| **Footprint** | ~9 agents · roughly 600000 tokens |
| **Exec consent** | declined 2026-09-14 - a grant is only ever the human-created marker (ADR-002) |

## ⚠️ Outstanding before this is done

Nothing - closed 2026-09-14.

## Read in this order

1. [`engagement-summary-alert-threshold-check-review.txt`](engagement-summary-alert-threshold-check-review.txt) - the two-minute cover note.
2. [`delivery-report.md`](delivery-report.md) - the consolidated report: iteration log, findings with dispositions, QA evidence, limitations.
3. *Then by interest:* the artifacts below.

## Everything in this delivery

| Artifact | What it is | Status |
|----------|------------|--------|
| [`engagement-brief.md`](engagement-brief.md) | Engagement Brief - code review of alert_threshold_check.py | final |
| [`data/findings-alert-threshold-check-review.jsonl`](data/findings-alert-threshold-check-review.jsonl) | Findings pack - code review (Ravi), 12 findings | final |
| [`data/findings-compliance-alert-threshold-check-review.jsonl`](data/findings-compliance-alert-threshold-check-review.jsonl) | Findings pack - compliance review (Layla), 11 findings | final |
| [`qa-handover.md`](qa-handover.md) | QA handover (Linh) - static-only, 15 tests assessed, verdict inferred | final |
| [`data/findings-alert-threshold-check-review-rereview.jsonl`](data/findings-alert-threshold-check-review-rereview.jsonl) | Findings pack - re-review after fixes (Ravi), 10 new findings + dispositions | final |
| [`delivery-report.md`](delivery-report.md) | Delivery Report - consolidated review, fixes, QA and verdict | final |
| [`engagement-summary-alert-threshold-check-review.txt`](engagement-summary-alert-threshold-check-review.txt) | Engagement summary email | final |

## Decisions of record

- **data-attestation**: No data involved - code only; nothing shared (user, 2026-09-14)
- **fix-cycle**: Fix then re-review loop (user, 2026-09-14)
- **fix-scope**: Safe fixes only plus tests - no changes to the names or parameter lists of the two public functions (user, 2026-09-14). Consequence: CR-01, CR-02, CMP-03, CMP-04 and CMP-09 cannot be fixed in this pass and close as Open, needs human developer decision.
- **go-ahead**: Proceed as briefed (user, 2026-09-14)
- **jurisdiction**: US (BSA / FinCEN) (user, 2026-09-14)
- **module-purpose**: Both a CTR filing determination and an investigation alert, from one bool (user, 2026-09-14). Splitting them needs a signature change, so it stays open.
- **nydfs-part-504**: Not a New York regulated entity - Part 504 out of scope (user, 2026-09-14)
- **review-mode**: audit (whole-target breadth, pre-existing issues in scope)
- **review-not-covered**: Nothing excluded - the file is the only source file in the project
- **review-scope**: Deep depth, Full dimensions (core + quality + compliance/audit), alert_threshold_check.py whole file, 19 lines, origin mixed, no performance pass (user, 2026-09-14)
- **upstream-scoping**: Unknown - the user cannot see whether the caller scopes to one person, one business day, currency only (user, 2026-09-14). Aggregation findings stay a live reporting gap.

## Engagement log

- 2026-09-14: Pip context pass returned: 1 Python file, 19 lines, no CLAUDE.md, 4 lenses, opengrep+ast-grep unavailable. Ravi and Layla dispatched concurrently via Workflow (run wf_f75eac3c-8ad).
- 2026-09-14: dod-gate-block:f9fb9a8cd1d34d3c (block 1)
- 2026-09-14: DoD gate: 3 MISSING-HTML / REGISTRY-HTML-STALE findings. Not auto-fixable here - the Markdown render library is absent in this environment and render_html raises 'The Markdown package is required'. Escalated to the user; installing libraries is a human action, not the team's. Markdown artifacts are complete and authoritative.
- 2026-09-14: Task-panel nudge noted: TodoWrite is not available as a tool in this session, so planned gates are tracked in this state file and the outstanding list instead. Not seeding a panel that does not exist.
- 2026-09-14 [review-loop]: Pip scoring pass: 23 found, 23 reported, 0 filtered, no basis corrections, 6 cross-pack overlaps identified. Morgan challenge pass: corrected Ravi's envelope severity split (was 5 warning/4 medium, actual 6/3), recorded Pip's scoring in both envelopes, flagged CMP-05's proposed 9000 near-threshold band as an invented ungoverned value that must not be implemented as-is, and flagged CR-05's proposed comment text asserting eCFR verification that has not happened.
- 2026-09-14: dod-gate-block:f9fb9a8cd1d34d3c (block 2)
- 2026-09-14: dod-gate-block:e0b40f75d8ebc71b (block 3)
- 2026-09-14 [review-loop]: Round 1 fixes (Kenji) -> QA (Linh, static, inferred) + re-review (Ravi). Ravi dispositions: 5 fixed, 4 open by design, 3 partially fixed, 10 new RR- findings, no new critical. RR-01 is a data-safety regression introduced by our own fix (customer records interpolated into error messages). RR-04: DAILY_LIMIT retype ruled scope creep, revert recommended. Round 2 dispatched for RR-01 and RR-04 only.
- 2026-09-14: DoD gate run at close: 11 findings. 7 auto-fixed by Morgan (4 EMAIL-AGENT-UNMARKED, 2 STALE-STATUS banners, 1 STALE-DOCSTATUS). 4 remain: MISSING-HTML on START-HERE, delivery-report, engagement-brief and qa-handover. These are NOT auto-fixable in this environment - the Markdown render library is absent and installing it is a human action. The close is REFUSED and the engagement stays at 'closing'. Not worked around. All deliverables exist and are complete in Markdown.
- 2026-09-14: PM error, corrected: the project-level codebase map (VSIT/shared/map.md, ADR-003) was wrongly registered as a workspace artifact, leaving an added_before_file_existed row. The row was removed from engagement-state.json by hand and the index re-rendered. The map itself exists and is correct at the project level, where it belongs.
- 2026-09-14: DOD-GATE-EXHAUSTED:93cd22b58fc849ed - the DoD backstop blocked 3 times on this engagement without its findings clearing, and has degraded to a warning so turns can end. The findings are still open; they are printed at every stop from here on, but nothing blocks on them.
- 2026-09-14: close: cleared 5 outstanding item(s): HTML siblings cannot be rendered - the Markdown render library is absent. Needs a human to install the dev requirements, then re-render. Blocks the MISSING-HTML DoD findings, not the review itself.; Threshold owner, effective date, tuning date and review cycle are still <to be completed> placeholders in the code - the user's to fill.; Aggregation defects CR-01, CR-02, CMP-03, CMP-10 accepted and documented, not fixed - need the full fix with a caller inventory.; Compliance pass assessed the code as found and was not re-run after the fixes - a fresh Layla pass is needed before the compliance limb is treated as current.; CLOSE BLOCKED: 4 MISSING-HTML DoD findings. Needs a human to install the dev requirements so the .html siblings can render, then re-run set-status closed. Every deliverable is complete in Markdown meanwhile.

## Provenance

🤖 Produced by the virtual compliance-surveillance engineering team (0.37.0) - AI agents, Virtual Surveillance IT. Evidence basis tags: 📊 measured · 🧠 inferred.

<!-- rendered-from: engagement-state.json state-hash: 58a37701901a29c4 content-hash: 9dd0155aa9b738b6 -->
