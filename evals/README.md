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
```

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
