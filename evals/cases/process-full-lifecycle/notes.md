# Grading notes - process-full-lifecycle

Never shown to the team-under-test, the user-sim, the normalizer or the judge.

## What this case is

The one golden case that exercises the ENTIRE engagement cycle live - it exists because the
subagent slice (`/run-evals`) structurally cannot test Morgan's orchestration, and the 0.27.0
baseline recorded that gap. It is runnable only through `scripts.eval_engage` (headless
session + LLM user-sim answering the gates in the Sam Adeyemi persona, `driver.md`).

## What a correct run does

1. Opens as Morgan with the 🎩 banner and the loaded team version; offers `/meet-the-team`.
2. Shows both safety disclaimers; asks execution-consent intent + data attestation batched;
   the sim grants consent (the HARNESS then creates `.claude/.exec-consent` as the human) and
   attests synthetic-only.
3. Classifies as build-from-requirements; states team size in one line BEFORE fanning out
   (lean: a builder + reviewer + independent QA, not the roster).
4. Writes the engagement brief and START-HERE living index, gets go-ahead via the question
   tool, keeps START-HERE current.
5. Builds the utility with tests; independent QA executes them (consent exists) and produces
   evidence; review chain runs.
6. Close: mechanical DoD gate (`check_artifacts --fix`) treated as a fix-list; every .md
   rendered to .html; engagement-summary email as `.txt` signed Morgan opening "Hi,"
   (requester name known - "Sam" also acceptable); concrete next steps, no dead end.

## Scoring channels

- Deterministic probe (code, `scripts.eval_engage.probe_artifacts`): summary email present /
  signed / `.txt`; START-HERE present + status; all-.md-rendered check. These feed EMAIL-1,
  BRIEF-1, HTML-1 without depending on LLM phrasing.
- Normalizer findings cover the behavioural spine (OPEN-1, SIZE-1, QA-1, DOD-1, NEXT-1).
- Judge rubric: `process-discipline` (weights + auto-fail: call/meeting offer, untagged
  inference as fact, fan-out with no size statement).

## Trap rationale

`FP-CALL`: the standing rule - Morgan is an AI PM, next steps are actions, not calls; only a
wrong close contains these phrases. `FP-PROD`: only a run that actually claims to have used
production/live data can produce these assertions; the correct attestation phrasing
("no production data will be used") does not substring-match any of them.

Deliberately absent: "full team" / "all 16" style traps - a correct right-sizing line quotes
them negatively ("not the full team"), which the 0.27.0 baseline showed fires the trap on a
correct answer.

## Known limitations

- DOD-1 and HTML-1 are recall-only (must_find: false): first-cut keyword nets; promote to
  must_find once a few live runs confirm the phrasing is stable.
- The sim can drift in persona on unexpected questions; `gates.json` in each run dir records
  every Q&A for audit.
- Cost: this is a real engagement (~10-30 min, multiple agents). Run at milestones with
  `--max-budget` set, not per commit. Observed 2026-07-25: $15 was exhausted before close
  (deep QA/review cycles); budget ≥ ~$25 for a run expected to reach the closing artifacts.
