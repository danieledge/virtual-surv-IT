---
description: Data-analyst exploratory analysis loop - question → analysis → evidenced insight report
argument-hint: <the analytical question, and where the data is>
disable-model-invocation: true
---

Run an exploratory data analysis for: **$ARGUMENTS**

Under the PM (CLAUDE.md §6), drive **data-analyst**. **Gather inputs first - ask via the question
tool, one question per axis; don't assume:** the precise question; where the data is
(synthetic, masked, or data you've **attested is safe** - at intake, or **confirm now if you
invoked this skill directly** rather than via `/engage`, §5 - if raw/unprepared use
`/prepare-data`; `data/raw/` is hard-blocked); and what a useful answer looks like.
Make any mutually-exclusive axis **single-select**. **If the data is an extract or conversion**
(from Excel/CSV/an export), confirm its source-vs-output **reconciliation** before analysing -
if none exists, reconcile first (counts + a control total, house rule in
`docs/house-rules.md`): a truncated extract contaminates every downstream number. Any
conversion the team does itself goes through `<python> -m scripts.convert_file` (lossless
defaults, schema gates, JSON evidence report - attach it); never hand-parse.
(`<python>`: resolve your interpreter - try python3, then python, then py - and in an installed-plugin session invoke the bundled `scripts/` copy by path; see the operating guide, "Run mode & the bundled scripts".)

1. **Frame** the question and the assumptions/caveats up front.
2. **Analyse** - efficient, well-commented SQL/Python on synthetic/masked data: distributions,
   segments, cohorts, trends, false-positive sources, correlations. Never expose raw PII/MNPI in
   outputs, commits or logs. Running that analysis code needs the execution-consent gate
   (CLAUDE.md §7); if the guard blocks, ask the user to grant consent (it is human-only) - never
   work around it.
3. **Evidence the findings** - figures with the basis stated (📊 measured from the data /
   🧠 inferred), and the limitations.
4. **Recommend** - the action the analysis supports (e.g. a tuning direction → `/tune-thresholds`;
   a data-quality concern → `data-quality-reviewer`; a coverage gap → SME/`business-analyst`).

Output: an **exploratory-analysis report** (`docs/templates/exploratory-analysis.md`) - and where
relevant a **data dictionary** (`docs/templates/data-dictionary.md`), **data lineage**
(`data-lineage.md`), **segmentation analysis** (`segmentation-analysis.md`) or **process map**
(`process-map.md`) - under `artifacts/`, rendered to `.html`.

**Close - don't dead-end.** State the headline insight + recommendation, then offer the next step
(tune, validate, escalate a data-quality issue, or hand over).

> For **threshold calibration / alert tuning** specifically (ATL/BTL, model-performance MI), use
> `/tune-thresholds` (`tuning-analyst`) - this skill is general exploratory analysis.
