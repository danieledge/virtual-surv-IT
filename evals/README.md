# Team-quality eval harness

The repo's unit tests check the **code** (masking, the spoofing rule, rendering, the guards).
This harness
checks the **quality of what the team produces** - reviews, coverage assessments, specs, tuning
packs - so a prompt change that silently degrades rigour gets **caught**, not shipped.

> Why it exists: the team is mostly *prompts*, and prompts get edited often. Without an eval,
> there's no signal that `/deep-review` still catches the bugs it caught 30 commits ago. This is
> the regression net (an Anthropic multi-agent standard - see `docs/agent-design.md`).

## How it works (two layers)

1. **Deterministic** (`scripts/eval_score.py`, unit-tested, no tokens) - matches the team's
   normalized **findings** against a golden **ground-truth manifest** (`expected.yaml`): recall on
   planted issues, must-find criticals, and false-positive traps. This is the backbone. What runs
   in CI token-free is the harness **contract**, not the team: the scorer's unit tests
   (`tests/test_eval_score.py`) plus per-case contract tests (`tests/test_eval_cases.py`) that
   check every manifest parses, a synthetic perfect run passes and an empty run fails per case.
   Scoring the *live team's* output still requires running `/run-evals` (spends tokens).
2. **Qualitative** (the `/run-evals` skill + an LLM judge) - scores the dimensions the
   deterministic layer can't: clarity, traceability, evidence-basis, usability. 0-1 + pass/fail
   per the rubric.

```
evals/
  rubrics/        what "good" looks like per deliverable (judge scores against these)
  cases/<case>/   a golden case: input file (synthetic) + expected.yaml (ground truth)
                  + notes.md (grading notes - optional but preferred)
  results.jsonl   tracked, append-only numeric record of every scored run (below)
  eval-baseline-<version>.md   the per-release record, carrying the verdict block (below)
```

**What the judge actually sees** (fixed 2026-08-01 after an audit found it did not):
the artifact listing handed to the normalizer and judge carries the **bodies** of the
`.md`/`.txt` deliverables, not just their paths (6k chars per file, 60k total, truncation
stated in-band), and the transcript retains **subagent output** tagged `[subagent]` and
capped at 3k chars per block (`--exclude-subagent-output` restores the old PM-only view).
Before that, "evidence basis", "traceability" and "clarity" were scored from filenames plus
the PM's own narration of the work - a well-narrated empty deliverable scored like a real
one.

All eval inputs are **synthetic** (CLAUDE.md §5) - seeded with known issues on purpose.

## What lives where in a case

- **The `input:` file** (named by the manifest's `input:` key, e.g. `scenario.md` or a code
  file) is the ONLY thing the team-under-test sees. `/run-evals` briefs the blind subagent
  with it alone, so it must read as a real request/artifact: no answer keys, no seeded-issue
  lists, no "this is an eval" banners, nothing that states or instructs the graded behaviour.
- **`expected.yaml`** is the ground-truth manifest the deterministic scorer reads.
- **`notes.md`** is the grading sidecar: seeded-issue detail, what a correct response
  does / must not do, trap-keyword rationale (and a change log when traps are reworked).
  It is never shown to the team-under-test - `/run-evals` excludes it from the blind brief.

## Running it

`/run-evals` (the skill) drives it: for each case it runs the named workflow, normalizes the
output to findings JSON, scores it deterministically (`python -m scripts.eval_score`), adds the
LLM-judge dimensions, and prints an aggregate scoreboard (cases passed, recall, traps triggered).
**Running the full set spends tokens** (each case spawns the team) - run it at milestones / before
a release, not every commit. The deterministic scorer's own tests and the per-case contract tests
(`tests/test_eval_cases.py`) run free in CI.

## The orchestration slice - `scripts.eval_engage` (live /engage runs)

`/run-evals` covers the *subagent* surface only: it cannot exercise Morgan's orchestration
(banner, intake gates, right-sizing, lifecycle discipline, close artifacts) because a subagent
has no user channel and cannot run slash commands - the gap the 0.27.0 baseline recorded. The
driver closes it:

    . .venv/bin/activate          # dev venv with claude-agent-sdk (requirements-dev.txt)
    python -m scripts.eval_engage --list
    python -m scripts.eval_engage --case process-full-lifecycle --max-budget 10
    python -m scripts.eval_engage --all-engage

Per case it: copies the repo to a throwaway sandbox (with `evals/` excluded, so ground truth
is structurally unreachable; guard hooks stay live - they are under test too), launches a real
headless session via the Agent SDK **using the case's declared `workflow:` as the front-door
command** (`/engage` or `/engage-light`; anything else falls back to `/engage`), and has an
**LLM user-sim** answer every AskUserQuestion gate in persona (the case's `driver.md`,
falling back to `evals/driver-default.md`).

Robustness (0.30): sessions authenticate like interactive Claude Code (the API key is blanked
in the child env - runs bill to the subscription and share its usage window); a
**dead-at-birth watchdog** aborts fast with the reason if a session emits nothing within 120s
(instead of burning the whole `--timeout`); `RateLimitEvent` frames are printed as they
arrive. `--rescore <run-dir>` re-runs probe + normalizer + judge over a KEPT run without a
live session, persisting to `score-rescore.json` alongside the untouched original. When the sim grants execution-consent intent, the harness process -
standing in for the human, per ADR-002 - creates the sandbox's `.claude/.exec-consent` marker;
the session itself remains blocked from writing it. Scoring then combines a deterministic
artifact probe of the sandbox, an uncontaminated normalizer pass over the transcript
(`eval_score` against `expected.yaml`), and the rubric LLM-judge. Outputs land under
**Retention rule (2026-07-30 audit):** under `evals/runs/`, keep IN FULL (a) any run id
named in a committed `evals/eval-baseline-*.md` or `evals/artifact-review-*.md` (those
sandboxes are cited evidence and `--rescore`/`--resume-run` operate on kept runs), and
(b) all runs from the last 7 days. For anything else, delete the `*/sandbox/` subdirs and
keep the scoring outputs (`transcript.md`, `events.jsonl`, `score.json`, `report.md`);
whole run dirs older than 30 days may be purged unless referenced. Rationale: kept
sandboxes are full repo copies (~80% of bytes) and the lifecycle hooks treat stale kept
sandboxes as live engagement state.

`evals/runs/<timestamp>/<case>/` (git-ignored): `transcript.md`, `gates.json` (every simulated
Q&A), `findings.json`, `score.json`, `report.md`.

`process-full-lifecycle` is the flagship case: the only one that runs intake -> build ->
independent QA -> DoD gate -> close end-to-end. **Each case is a real engagement** - cap spend
with `--max-budget`, run at milestones. As with `/run-evals`, treat raw keyword scores as the
starting point: adjudicate misses/traps against the transcript before calling a regression
(baseline precedent: `evals/eval-baseline-0.27.0.md`).

## The baseline verdict block (the release gate parses this)

`scripts/release_gate.py` blocks a dev → main promotion unless the version's
`evals/eval-baseline-<version>.md` **declares a verdict in machine-readable form**. Until
2026-08-01 the gate only checked the file existed, so a baseline whose own prose said "No
clean-pass claim is made for this baseline" satisfied it, and four versions shipped
unevaluated. Every baseline now carries a fenced block:

````
```eval-verdict
verdict: pass-with-adjudication
cases_total: 7
cases_passed_raw: 2
cases_adjudicated_pass: 5
unadjudicated_failures: 0
runs: 20260729T225110Z, 20260730T010541Z
```
````

- `verdict:` - `pass` | `pass-with-adjudication` | `fail`. `fail` blocks promotion, and
  `pass` may only be claimed when **every** case passed RAW, so an adjudicated release
  cannot be misread as a clean run.
- The counts must satisfy `cases_passed_raw + cases_adjudicated_pass +
  unadjudicated_failures == cases_total` - every case is accounted for or the gate says so.
- **`unadjudicated_failures` > 0 blocks promotion.** Adjudication is a human act (read the
  transcript, evidence why the raw FAIL is not a real failure, write it up in the record's
  table). A budget-killed or timed-out case is **unevidenced, not passed** - it stays an
  unadjudicated failure until it is re-run or adjudicated on evidence.
- Blank lines and `#` comments inside the block are ignored; only the FIRST block counts.

`scripts.eval_engage` drafts the raw block into each run's `report.md` - copy it into the
baseline and move cases from `unadjudicated_failures` to `cases_adjudicated_pass` as you
adjudicate them. The gate also ages a baseline against
`docs/DEFINITION-OF-DONE.md`, `docs/house-rules.md`, `docs/WAYS-OF-WORKING.md` and
`docs/code-review-method.md` alongside the agents/skills - those docs steer the team at run
time exactly as a skill does.

## The tracked results log (`evals/results.jsonl`)

`evals/runs/` is git-ignored and pruned by the retention rule, so the numbers used to
survive only as prose in a baseline. Every scored case now also appends one JSON row to
**`evals/results.jsonl`** (tracked, append-only, deduped on `run_id` + `case` + `mode`):

    {"run_id": "20260730T010541Z", "case": "process-full-lifecycle", "mode": "run",
     "version": "0.33.1", "passed": false, "recall": 0.778, "must_find_missed": [...],
     "traps_triggered": [], "judge_score": 0.48, "judge_pass": false, "cost_usd": 14.07,
     "num_turns": 61, "duration_s": 2400.0, "timed_out": true, "session_error": false,
     "recorded_at": "..."}

Writing is automatic (live runs and `--rescore`). To backfill from saved run outputs:

    python -m scripts.eval_engage --record evals/runs    # no session, no tokens

`version` is the plugin version the run exercised - taken from the run's kept sandbox when
backfilling, and `"unknown"` where the sandbox was pruned (never today's version stamped on
an old row). Recall and judge scores are trendable from this file instead of being
re-narrated each release.

## A case (`expected.yaml`)

Abridged from the real `review-seeded-bugs-py` case (one planted issue of its four shown):

```yaml
case: review-seeded-bugs-py
workflow: /deep-review          # the skill the blind run inlines
rubric: code-review             # resolves to evals/rubrics/code-review.md
input: input_alert_export.py    # the ONLY file shown to the team-under-test
planted:                        # issues the team MUST surface
  - id: SEC-1
    keywords: [hardcoded, secret, credential, password, api key]
    location: input_alert_export.py:8
    min_severity: critical
    must_find: true
forbidden:                      # false-positive traps - must NOT be flagged
  - id: FP-1
    keywords: [magic number, undocumented threshold, LARGE_ORDER_MULTIPLE]
pass:
  require_all_must_find: true
  forbid_all: true
```

Trap keywords are substring-matched against each finding's title+kind+location, so keep them
**assertion-only**: a keyword like "no below-the-line" would also match a correct answer that
says "do not cut the threshold with no below-the-line testing". Phrase traps so that only an
actually-wrong answer contains them, and record the rationale in `notes.md`.

Both planted and forbidden specs also accept **`exclude_keywords:`** - a mention-guard that
vetoes a match when any of them appears in the finding's haystack. Use it where a keyword net
cannot tell presence from absence-talk (a planted "summary email" spec matching "summary email
never produced" - observed live 2026-07-25) or a defect-flag from a fix-recommendation (the
0.27.0 baseline's mention-as-fix trap artifact). CI checks that an exclude is never a substring
of the spec's own match keywords.

## Adding a case

1. `mkdir evals/cases/<id>/`, add a **synthetic** input file with deliberately seeded issues -
   written as the team would really receive it (no answer keys or eval banners; see "What
   lives where in a case").
2. Write `expected.yaml` (planted + forbidden + pass rules) - the ground truth. Set `input:`
   to the input file's name and `workflow:` to the driving skill; anchor each planted
   `location:` to the issue's exact line (the scorer tolerates +/- 3).
3. Point `rubric:` at the relevant `evals/rubrics/*.md`.
4. Put the grading rationale in `notes.md` (seeded-issue detail, correct/forbidden behaviour,
   trap rationale) - never in the input file.
5. Sanity-check the scorer against a hand-written findings JSON before relying on it. CI's
   contract tests (`tests/test_eval_cases.py`) pick the new case up automatically and verify the
   manifest parses, its `input:`/`rubric:`/`workflow:` pointers resolve, numeric line anchors sit
   inside the input file, `scenario.md` carries no answer-key sections, a perfect run passes and
   an empty run fails (or passes, for zero-finding cases - add those to `ZERO_FINDING_CASES`).
