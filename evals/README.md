# Team-quality eval harness

The repo's 58 unit tests check the **code** (masking, the spoofing rule, rendering, the guards).
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
  cases/<case>/   a golden case: input (synthetic) + expected.yaml (ground truth)
```

All eval inputs are **synthetic** (CLAUDE.md §5) - seeded with known issues on purpose.

## Running it

`/run-evals` (the skill) drives it: for each case it runs the named workflow, normalizes the
output to findings JSON, scores it deterministically (`python -m scripts.eval_score`), adds the
LLM-judge dimensions, and prints an aggregate scoreboard (cases passed, recall, traps triggered).
**Running the full set spends tokens** (each case spawns the team) - run it at milestones / before
a release, not every commit. The deterministic scorer's own tests and the per-case contract tests
(`tests/test_eval_cases.py`) run free in CI.

## A case (`expected.yaml`)

```yaml
case: review-seeded-bugs-py
workflow: /deep-review
rubric: code-review
planted:                       # issues the team MUST surface
  - id: SEC-1
    keywords: [hardcoded, secret, credential, api key]
    location: app.py:12
    min_severity: critical
    must_find: true
forbidden:                     # false-positive traps - must NOT be flagged
  - id: FP-1
    keywords: [documented threshold]
pass:
  require_all_must_find: true
  forbid_all: true
```

## Adding a case

1. `mkdir evals/cases/<id>/`, add a **synthetic** input with deliberately seeded issues.
2. Write `expected.yaml` (planted + forbidden + pass rules) - the ground truth.
3. Point `rubric:` at the relevant `evals/rubrics/*.md`.
4. Sanity-check the scorer against a hand-written findings JSON before relying on it. CI's
   contract tests (`tests/test_eval_cases.py`) pick the new case up automatically and verify the
   manifest parses, a perfect run passes and an empty run fails (or passes, for zero-finding
   cases - add those to `ZERO_FINDING_CASES`).
