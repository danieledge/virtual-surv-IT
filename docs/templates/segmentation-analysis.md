# Segmentation Analysis — <SCENARIO / POPULATION>

> Produced by `data-analyst`. A risk-based segmentation of a surveillance population so detection
> is calibrated per segment rather than one global threshold. Statistical analysis on
> **synthetic/masked data only — no real PII/MNPI** (§5). Authored in `.md`, rendered to `.html`.
> Feeds the **Threshold Tuning Pack** (`docs/templates/threshold-tuning-pack.md`) — segments here
> become its per-segment rows. Every figure carries its basis: 📊 measured vs 🧠 inferred.

| | |
|---|---|
| **Scenario / population** | <what is being segmented; obligation served (§2)> |
| **Data window** | <period; synthetic/masked> |
| **Dimensions** | <product / instrument / customer-type / channel / liquidity> |
| **Date / author** | <YYYY-MM-DD · data-analyst> |

## 1. Rationale & dimensions
Why one global threshold is wrong here, and the dimensions chosen to segment on (and why each is
risk-relevant). A single behaviour can be normal in one segment and abusive in another.

| Dimension | Why it matters | Source field |
|---|---|---|

## 2. Segment definitions & population
The segments, their precise membership rule (so a record lands in exactly one), and population.

| Segment | Definition (membership rule) | Population | % of total | Basis |
|---|---|---|---|---|
| <S1> | <e.g. liquid large-cap equities> | <n> | <%> | 📊 |
| <S2> | <e.g. illiquid / small-cap> | <n> | <%> | 📊 |

## 3. Per-segment behaviour profile
The distribution of the signal metric per segment — this is what makes a per-segment threshold
defensible. Use robust stats (median/IQR), not just the mean.

| Segment | Metric | Median | IQR / spread | P90 | P95 | P99 | Basis |
|---|---|---|---|---|---|---|---|

## 4. How segments drive thresholds
For each segment, the statistical basis a per-segment threshold would use (percentile / μ+kσ /
tail), and why it differs from neighbours. These rows hand directly to the tuning pack §2–§3.

| Segment | Suggested basis | Indicative threshold | Why it differs |
|---|---|---|---|

## 5. Validation — segments are stable & meaningful
Evidence the segmentation is sound, not arbitrary: segments are **distinct** (behaviour profiles
differ materially), **stable** (hold over time / sub-periods), and **populated** (no thin
segments that can't be calibrated; respects `k_anonymity` in `config/masking-schema.yaml`).

| Check | Method | Result | Basis |
|---|---|---|---|
| Distinctness | <profiles differ; effect size> | <...> | 📊 |
| Stability | <split window; re-derive> | <...> | 📊 |
| Coverage / min size | <no segment < k> | <...> | 📊 |

## 6. Next steps
Hand segments to the **Threshold Tuning Pack** for ATL/BTL per segment; independent sign-off →
`model-validator`; re-segmentation cadence (segments drift as the book changes).
