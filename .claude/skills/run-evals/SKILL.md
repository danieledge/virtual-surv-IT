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

**1. Select cases.** List `evals/cases/*/`; filter by the arg (rubric or case id) if given. As the
orchestrator you may read `expected.yaml` (the ground truth) and `evals/rubrics/<rubric>.md` - **you
use them only to score, after the workflow has run.** The ground truth must never enter the
context of the team-under-test (see step 2).

**2. Per case - run blind, then score. Blindness must be structural, not willpower:** the golden
input files no longer contain the answer, but this orchestrator's context does (you just read
`expected.yaml`), so you cannot run the workflow yourself and call it blind. A subagent also
cannot invoke the (dormant) slash-command workflow or answer AskUserQuestion menus - so inline
the workflow into the brief instead of asking the subagent to invoke it:
   a. **Brief a clean subagent.** Read the case's `workflow:` SKILL.md
      (`.claude/skills/<workflow>/SKILL.md`) and inline its instructions into the subagent brief,
      with the intake axes **pre-answered from the case** (state in the brief that the menus are
      pre-answered because a subagent has no user channel for AskUserQuestion). The brief contains
      **ONLY** the inlined workflow and the case `input:` file - never `expected.yaml`, never the
      rubric, never the case's `notes.md` (grading notes, if present), never any scenario answer
      sections (seeded-issue / ground-truth content). Inputs are synthetic - the execution gate /
      data attestation still apply.
   b. **Normalize via a SECOND uncontaminated subagent** (one that has not seen `expected.yaml` -
      not you): give it the first subagent's raw output only, and have it emit findings JSON:
      `{"findings": [{"severity","location","title","kind"}, ...]}`
      (severity ∈ critical|warning|medium|style). For behaviour cases (data-safety), it captures
      what the team *did* as findings (e.g. `{"title":"refused to read data/raw","kind":"behaviour"}`),
      keeping the wording close to the output's own vocabulary so keyword matching is fair. It must
      never see `expected.yaml`'s keywords - that would leak the grade back in.
   c. **Deterministic score (you, the orchestrator):** write the findings JSON to a temp file and run
      `<python> -m scripts.eval_score --expected evals/cases/<case>/expected.yaml --findings <tmp>.json`
      (`<python>`: resolve your interpreter - try python3, then python, then py - and in an
      installed-plugin session invoke the bundled `scripts/` copy by path; see the operating guide,
      "Run mode & the bundled scripts"). That returns recall, must-find-missed, and
      false-positive-traps-triggered.
   d. **Qualitative judge** *(delegate to `compliance-reviewer`, acting as an
      independent LLM-judge - NOT the agent that produced the output):* score the rubric's qualitative
      dimensions 0.0-1.0 (evidence-basis, actionability, clarity, etc.) and apply its auto-fail rules.
      Combine with the deterministic result for the case verdict (pass/fail + score).

**3. Scoreboard (console, clean).** One line per case: ✅/❌ · case · recall · score · any
must-find-missed or traps. Then the headline: **N/total passed, mean recall, mean score**. Put the
per-case detail in an artifact (`artifacts/EVAL-<date>.md`, rendered to `.html`), not a console wall.

**4. Close - flag regressions, don't dead-end.** Call out any case that **fails or dropped vs a prior
run** as a likely regression from a recent prompt change, with the specific miss (e.g. "review missed
the SQL-injection critical"). Recommend the next step (investigate the prompt, add a case, or
accept). A failing eval is a finding, not a pass.

> The LLM-judge is calibrated, not infallible (Anthropic guidance: keep a human in the loop).
> Treat a borderline qualitative score as a prompt to look, not a verdict. The deterministic
> recall/trap numbers are the hard signal.
