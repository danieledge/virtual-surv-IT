---
description: Run the team-quality eval harness - score the team's own output against golden cases (regression net)
argument-hint: <optional - a rubric, a single case id, or blank for all>
disable-model-invocation: true
---

Run the **team-quality eval harness** (`evals/`) - the regression net that checks the team still
produces good work after prompt changes. Scope: **$ARGUMENTS** (a rubric name, a case id, or blank
= all cases).

> ⚠️ **This spends tokens** - each case spawns the relevant workflow. Run it at **milestones / before
> a release**, not every commit. The deterministic scorer's own unit tests (`tests/test_eval_score.py`)
> run free in CI; this skill adds the live run + the qualitative judge.

**1. Select cases.** List `evals/cases/*/`; filter by the arg (rubric or case id) if given. Read each
`expected.yaml` (the ground truth) and its `evals/rubrics/<rubric>.md`.

**2. Per case - run, normalize, score (do NOT peek at `expected.yaml` while running the workflow;
run it blind, then score):**
   a. Run the case's `workflow:` on its `input:` (e.g. `/deep-review` on the seeded file). Inputs are
      synthetic - the execution gate / data attestation still apply.
   b. **Normalize** the team's output to findings JSON: `{"findings": [{"severity","location","title","kind"}, ...]}`
      (severity ∈ critical|warning|medium|style). For behaviour cases (data-safety), capture what the
      team *did* as findings (e.g. `{"title":"refused to read data/raw","kind":"behaviour"}`).
   c. **Deterministic score:** write the findings JSON to a temp file and run
      `python -m scripts.eval_score --expected evals/cases/<case>/expected.yaml --findings <tmp>.json`.
      That returns recall, must-find-missed, and false-positive-traps-triggered.
   d. **Qualitative judge** *(delegate to `compliance-reviewer`, acting as an
      independent LLM-judge - NOT the agent that produced the output):* score the rubric's qualitative
      dimensions 0.0-1.0 (evidence-basis, actionability, clarity, etc.) and apply its auto-fail rules.
      Combine with the deterministic result for the case verdict (pass/fail + score).

**3. Scoreboard (console, clean).** One line per case: ✅/❌ · case · recall · score · any
must-find-missed or traps. Then the headline: **N/total passed, mean recall, mean score**. Put the
per-case detail in an artifact (`artifacts/EVAL-<date>.md`, rendered to `.html`), not a console wall.

**4. Close - flag regressions, don't dead-end.** Call out any case that **fails or dropped vs a prior
run** as a likely regression from a recent prompt change, with the specific miss (e.g. "review missed
the SQL-injection critical - SEC-2"). Recommend the next step (investigate the prompt, add a case, or
accept). A failing eval is a finding, not a pass.

> Honesty: the LLM-judge is calibrated, not infallible (Anthropic guidance: keep a human in the loop).
> Treat a borderline qualitative score as a prompt to look, not a verdict. The deterministic
> recall/trap numbers are the hard signal.
