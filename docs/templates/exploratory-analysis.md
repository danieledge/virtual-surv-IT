# Exploratory Analysis - <QUESTION>

> Produced by `data-analyst`. An evidenced answer to a specific question - the exploratory loop of
> question → analysis → insight, with every finding traceable to figures. Analysis on
> **synthetic/masked data only - no real PII/MNPI** (§5). Authored in `.md`, rendered to `.html`.
> Every finding states its basis: **📊 measured** (a number computed from the data) vs **🧠
> inferred** (a judgement/projection beyond what the data directly shows). Never present 🧠 as 📊.

> **Document control** · ID `EDA-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Internal | Confidential` · Owner `<name / role>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

| | |
|---|---|
| **Question** | <the one question this answers> |
| **Question agreed by** | <name / role> on <YYYY-MM-DD> |
| **Requested by** | <who needs it and the decision it informs> |
| **Data window** | <period / dataset; synthetic/masked> |
| **Date / author** | <YYYY-MM-DD · data-analyst> |
| **Headline finding** | <one-line answer> |

**Reproducibility**

| Item | Value |
|---|---|
| Script / notebook | <path/to/script.py or notebook.ipynb> |
| Commit hash | <git SHA at run time> |
| Tool versions | <Python X.Y / pandas X / scipy X / etc.> |
| Seed / random state | <n/a or seed value used> |

## 1. Question & motivation
The precise question and why it matters now - the decision or risk it bears on (§2 where
regulatory).

## 2. Approach & data used
The datasets (with dictionary pointers), the masking applied (`config/masking-schema.yaml`), the
method (aggregation / distribution / correlation / cohort), and the tools. State scope boundaries
- what this analysis does **not** cover.

| Dataset | Dictionary | Grain | Records | Masking |
|---|---|---|---|---|

## 3. Findings
One row per finding. **Basis** is mandatory: 📊 measured vs 🧠 inferred. **Limitations** records
what would change the conclusion (small n, synthetic artefacts, confounders). For quantitative
findings, include a **confidence interval or significance note** (e.g. 95% CI, p-value, or a
plain-language note that n is too small for inference) so the reader can judge weight of evidence.

| # | Finding | Figures / evidence | CI / significance | Basis | Limitations |
|---|---|---|---|---|---|
| 1 | <e.g. cancels cluster pre-fill for segment X> | <rate, n, %> | <95% CI [a, b]; p=...> | 📊 | <synthetic; n=...> |
| 2 | <e.g. likely indicates layering pattern> | <reasoned from #1> | <n/a - inferred> | 🧠 | <not yet confirmed; needs labelled cases> |

## 4. Interpretation
What the findings mean together - the story behind the numbers. Be explicit where you cross from
📊 measured into 🧠 inferred interpretation.

## 5. Recommendation & next action
Close with a concrete recommendation, not just analysis: the **action** it supports, the **owner**
to carry it out, and your confidence. Offer the route forward (e.g. tune → `tune-thresholds`;
build → `platform-engineer`; new scenario → `new-scenario`).

| Recommendation | Action it supports | Owner | Confidence (basis) |
|---|---|---|---|
| <...> | <e.g. tighten threshold for segment X> | <data-analyst / rules-developer> | <📊/🧠> |

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
