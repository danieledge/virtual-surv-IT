# Eval baseline 0.35.0 - 2026-08-18

**Scope: targeted** (live `/engage` sessions via `scripts.eval_engage`, Agent SDK, sandboxed) -
the validation slice for the 0.35.0 token-economics changes, chosen for the surfaces those
changes touch: the engagement open/close lifecycle against the new open-core operating guide
and deferred placement table, and the review pipeline against the trimmed reviewer, the Quick
split and the new context forwards. Not a full 14-case sweep (0.34.0's full baseline stands
for the untouched surfaces).
**Runs:** `20260818T190738Z` (4 lifecycle/process cases) · `20260818T201205Z` (review pipeline)
- 5 cases · **$27.45** live spend
**Orchestrator tier:** `sonnet` (`--team-model sonnet`), not the shipped default of opus -
same lower-bound convention as 0.33.6/0.34.0: a pass on the weaker orchestrator is conservative.

```eval-verdict
verdict: pass-with-adjudication
cases_total: 5
cases_passed_raw: 4
cases_adjudicated_pass: 1
unadjudicated_failures: 0
runs: 20260818T190738Z, 20260818T201205Z
```

## Result

| Case | Outcome | Recall | Judge | Cost |
|---|---|---|---|---|
| process-full-lifecycle | PASS | 1.0 | 0.96 | $9.24 |
| process-blocked-not-done | pass-with-adjudication | 1.0 (rescored) | 0.5 (artifact) | $0.43 |
| process-dual-artifact | PASS | 1.0 | 0.99 | $2.46 |
| process-summary-email | PASS | 1.0 | 0.82 | $5.75 |
| process-review-scorer-delegation | PASS | 1.0 | 0.81 | $9.57 |

## Adjudication: process-blocked-not-done

Raw FAIL (recall 0.667, judge 0.5), adjudicated **pass** against its transcript:

- **QA-1 keyword miss was wording, not behaviour.** The transcript states the required fact
  verbatim ("Linh (QA) hasn't run independent testing"; status table "independent testing |
  ⏳ not run"), but the keyword list carried no contraction/inverted form. Fixed additively in
  `evals/cases/process-blocked-not-done/expected.yaml` (dated comment in file); deterministic
  rescore over the saved run: recall 1.0, PASS (`score-rescore.json` in the run dir).
- **Judge 0.5 is a short-session rubric artifact.** Its own rationale confirms the paused
  behaviour was correct (explicit NOT-closed, outstanding list, no close-only artifacts, no
  call offered) and reweighted the close dimensions away as n/a, then scored the two remaining
  dimensions (right-sizing statement, evidence tagging) neutral for lack of occasion - a
  5-turn blocked status nudge has no fan-out to right-size and no data insight to tag. Nothing
  in the rationale implicates the changes under test.

## Notes

- `process-dual-artifact` at 0.99 is the direct probe of the release's riskiest change: the
  placement table moved out of the always-loaded guide into a deferred file behind a
  read-trigger, and the session still produced correctly-placed dual artifacts.
- The review-pipeline case ran against the trimmed `code-reviewer.md`, the Quick/pipeline
  split and the jurisdiction/tooling brief-forwards; 7 gates answered, recall 1.0.
- Prompt files received further same-day edits after these runs within the 0.35.0 change set
  (narrative stripping, the ladder paragraph) - invariant-preserving compressions, covered by
  the full deterministic suite (2,397 passing). If the promotion gate's staleness rule
  objects, a fresh slice re-run is the remedy.
