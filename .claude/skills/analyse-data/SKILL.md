---
description: Data-analyst exploratory analysis loop - question → analysis → evidenced insight report
argument-hint: <the analytical question, and where the data is>
---

Run an exploratory data analysis for: **$ARGUMENTS**

Under the PM (CLAUDE.md §6), drive **data-analyst**. **Gather inputs first - ask via the question
tool, one question per axis; don't assume:** the precise question; where the data is
(synthetic, masked, or data you've **attested is safe** - at intake, or **confirm now if you
invoked this skill directly** rather than via `/engage`, §5 - if raw/unprepared use
`/prepare-data`; `data/raw/` is hard-blocked); and what a useful answer looks like.
Make any mutually-exclusive axis **single-select**.

1. **Frame** the question and the assumptions/caveats up front.
2. **Analyse** - efficient, well-commented SQL/Python on synthetic/masked data: distributions,
   segments, cohorts, trends, false-positive sources, correlations. Never expose raw PII/MNPI in
   outputs, commits or logs.
3. **Evidence the findings** - figures with the basis stated (📊 measured from the data /
   🧠 inferred), and the limitations.
4. **Recommend** - the action the analysis supports (e.g. a tuning direction → `/tune-thresholds`;
   a data-quality concern → `data-quality-reviewer`; a coverage gap → SME/`business-analyst`).

Output: an **exploratory-analysis report** (`docs/templates/exploratory-analysis.md`) (and a
**data dictionary** / **segmentation analysis** where relevant), under `artifacts/`, rendered to
`.html`.

**Close - don't dead-end.** State the headline insight + recommendation, then offer the next step
(tune, validate, escalate a data-quality issue, or hand over).

> For **threshold calibration / alert tuning** specifically (ATL/BTL, model-performance MI), use
> `/tune-thresholds` (`tuning-analyst`) - this skill is general exploratory analysis.
