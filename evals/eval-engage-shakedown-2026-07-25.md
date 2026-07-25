# Live-/engage harness shakedown - 2026-07-25

Scope: first live runs of `scripts.eval_engage` (the orchestration slice - headless `/engage`
sessions with an LLM user-sim answering the gates). Purpose: prove the harness mechanics and
adjudicate what the scores actually mean, per the 0.27.0 baseline precedent. Run outputs are
under `evals/runs/` (git-ignored); this file is the durable record.

## Harness defects found live and fixed (all in `scripts/eval_engage.py`)

1. **SDK streaming input** - `can_use_tool` requires the prompt as an async iterable, not a
   string; crash before any session.
2. **Workspace trust** - untrusted sandbox paths silently drop project settings: no skills
   (`/engage` unknown) and, critically, no guard hooks. Runner now pre-registers
   `hasTrustDialogAccepted` for the sandbox and reverts it after.
3. **Auth precedence** - an `ANTHROPIC_API_KEY` present in the host environment outranked the
   intended login inside the spawned CLI, so sessions authenticated (and failed) under the
   wrong auth source. Runner blanks the key for spawned sessions.
4. **stdin close policy** - stdin carries the permission control channel, and the CLI emits
   ResultMessages mid-run (subagents in flight). Close-on-first-result killed all writes
   mid-engagement ("AbortError: Stream closed", 42-48 failures/run); never-closing hung to
   timeout; close-after-45s-silence tripped during a subagent's quiet build. Final policy:
   close only when result seen AND no Task in flight AND conversation not resumed.
5. **venv leak** - the runner's `.venv` (needed for the SDK) led the session's PATH, so
   `python3` in-session lacked user-site Markdown/bleach and `render_html` "couldn't" run.
   Env sanitized; dual-artifact behaviour became testable at all.
6. **Severity floor vs behaviour findings** - the blind normalizer filed correct behaviour
   observations as `medium`/`style`; process manifests floor at `warning`, so a run that named
   every planted behaviour scored recall 0.0. Convention now enforced deterministically
   (behaviour findings floor to `warning`).

## Adjudicated results

| Run | Case | Deterministic | Judge | Adjudication |
|---|---|---|---|---|
| 073329Z | process-right-sizing | FAIL raw; **PASS re-scored** after fix 6 (recall 1.0, 0 traps) | 0.56 FAIL | **Harness artifact.** Writes died mid-run (defect 4); the team's behaviour to that point was correct, incl. an exemplary right-sizing statement and honest degraded-environment reporting. |
| 075302Z | process-right-sizing | recall 0.0 raw → PASS with fix 6 | 0.78 PASS | **PASS.** Full mini-cycle ran to a clean close (stub build, QA'd, `CODE-NO-QA` self-corrected, email written). "Timeout" was defect 4's hang, after the close. |
| 085734Z | process-full-lifecycle | PASS (recall 1.0, 0 traps, 11 gates) | 0.65 FAIL | **Truncation, not regression.** $15 budget cap exhausted mid-cycle after deep delivery (32 dev + 49 QA tests, FSD/RTM/review/handovers all dual-rendered); team parked with a truthful ⛔ START-HERE and outstanding list. Close artifacts (delivery report, summary email) never reached. |
| 093815Z | process-full-lifecycle | **PASS** (recall 1.0, 0 traps, 11 gates) | **0.96 PASS** (right-sizing 1.0, dual-artifact 1.0, no auto-fail) | **BASELINE - clean end-to-end close.** $25 budget, 71 turns, 59 min, $20.88. Full cycle verified on disk: 7 artifacts dual-rendered, delivery report + summary email (.txt, "Hi,", signed) written at close only, START-HERE ✅ CLOSED, zero interim banners remain. |

## What the runs say about the team (the actual eval signal)

- Right-sizing, banner/version, gate discipline, evidence tagging and blocked-not-closed
  honesty all held under a simulated user - including challenging a scenario premise against
  repo docs, and self-correcting a DoD `CODE-NO-QA` finding instead of handing it to the user.
- The known scorer weakness recurred in mirror image: EMAIL-1 keyword-matched a finding about
  the summary email being *outstanding* (mention-as-missing ≠ present). The judge caught it.
  Keep both layers; never read deterministic recall alone on process cases.

## Validation sweep (2026-07-25, post-remediation, run 132240Z)

Full unit suite (306) green, then all three live /engage cases:

| Case | Deterministic | Judge | Adjudication |
|---|---|---|---|
| process-right-sizing | recall 1.0, 0 traps after completing the mention-guard on its manifest (a live run reproduced the 0.27.0 trap artifact: "two agents, not the full team" tripped FP-1; exclude_keywords added) | 0.97 PASS | **PASS** |
| process-close-reconciliation | recall 0.8, 0 traps | 0.885 PASS (rescore - first judge call flaked) | **PASS** |
| process-full-lifecycle | recall 0.875, 0 traps | 0.69 FAIL (never closed) | **Truncation again, not regression**: $22.83/$25 in 58 min after an added compliance-review pass; parked truthfully at ⛔ "budget exhausted" mid-QA-2. Depth varies run to run - budget guidance moved to $35/75min. |

Sweep also surfaced two one-shot helper flakes (empty normalizer once, judge max-turns once);
the runner now retries once and an errored judge fails closed instead of defaulting to pass.
`--rescore` recovered both without re-running the sessions.

A final lifecycle attempt at the new $35/75min calibration (run 150240Z) was cut by the WALL
CLOCK mid-QA-cycle-4 ($25.57, 13 gates, truthful "Not closed yet") - each run of this
open-ended scenario voluntarily goes deeper (this one ran four QA cycles and preserved the
QA suite in-workspace per the new evidence-retention rule, visibly binding). Adjudication:
truncation; process discipline held throughout. Decision: STOP re-running - the clean-close
baseline (093815Z) stands as the banked proof of the full cycle. Recorded calibration lesson:
the scenario needs a bounded evidence scope (e.g. "one review pass + one QA cycle is
sufficient") before a close can be expected inside any fixed budget; unbounded depth is a
property of the case, not a harness or team defect.

## Resume test (run 170016Z over 150240Z's kept sandbox)

New `--resume-run` mode: a fresh session cold-dropped into the timed-out workspace with only
"resume where it left off and close it out" (uncoached - finding START-HERE IS the test), no
wall clock, $15 cap. **Adjudicated PASS**: all must-finds, 0 traps, judge 0.81; on disk the
engagement is ✅ CLOSED with zero interim banners, delivery report + summary email + the
codebase map written, QA cycle 4 completed, prior decisions and evidence honoured (7 gates).
The runner's raw FAIL is only the budget cap firing during post-close narration ($15.09).
The normalizer retry logic recovered a prose-not-JSON first attempt live. Resume discipline
is now a covered, repeatable surface; candidate future golden case wraps this mode.

## Calibration follow-ups (recorded, not yet applied)

- `process-full-lifecycle` needs `--max-budget` ≥ ~25 USD and `--timeout` ≥ 3600s (confirmed:
  the clean-close run used $20.88 and 59 min). Gate cases run $3-5.
- Consider scorer support for a mention-as-missing exclusion (same class as the 0.27.0
  baseline's mention-as-fix note).
- `dod_stop_gate.py` / `persona_anchor.py` treat kept sandboxes under `evals/runs/` as a live
  engagement when the cwd drifts there - candidate additive exclusion, human-applied per the
  hook-hardening rule.
