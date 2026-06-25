---
description: Calibrate surveillance thresholds / tune scenarios with ATL-BTL evidence and the volume↔coverage trade-off
argument-hint: <the scenario/rule to tune, and where the alert/behavioural data is>
---

Tune detection thresholds for: **$ARGUMENTS**

> **When to use this vs the others.** Use this to **CALIBRATE a scenario's thresholds**
> (ATL/BTL, segmentation) — one scenario's numbers. To check whether all in-scope risks are
> monitored and feeds are live (typology→scenario→feed gaps), use `/assess-coverage`. For the
> periodic umbrella review that invokes both plus data-quality and adds an independent
> model-validator verdict, use `/validate-tm-model`.

**1. Gather inputs first — ask via the question tool, one question per axis; don't assume.**
Ask as discrete, structured questions:
- **Scenario/rule** to tune (single-select if a known set; else free text).
- **Target** — **single-select, mutually exclusive**: reduce FP without losing coverage / hit
  an alert-volume budget / close a coverage gap. The user picks exactly one.
- **Data location** — where the **alert + behavioural data** is (**synthetic or masked only**,
  §5 — if it's real, route through `/prepare-data` first). Separate question.
- **Segmentation** that applies (product/instrument/customer/channel). Separate question.

**2. Get the typology context from the SME** — `tm-sme` (or `trade-surveillance-sme` /
`comms-surveillance-sme`): the red flags, the obligation the scenario serves, what "true
positive" means here. Don't invent it.

**3. Drive `tuning-analyst`** (CLAUDE.md §6 — static statistical analysis on masked/synthetic
data only):
1. **Segment** the population (risk-based) — calibrate per segment, not one global threshold.
2. **Set candidate thresholds statistically** (percentile / std-dev / tail), with rationale + date.
3. **Above-The-Line** test — precision among flagged (true vs false positives).
4. **Below-The-Line** test — what's missed just under the threshold (coverage gaps / false negs).
5. **Dry-run** the candidates over a historical (masked/synthetic) window — project alert volume
   and the added/dropped population.
6. Quantify the **volume ↔ coverage trade-off** at each candidate.

**4. Produce the threshold-tuning pack** (`docs/templates/threshold-tuning-pack.md`) — segments,
proposed thresholds + statistical rationale, ATL/BTL evidence, dry-run volumes, recommendation
with expected effect at the firm's volumes, and the obligation cited. Save under `artifacts/`,
render to `.html`.

**5. Close — don't dead-end.** State the recommendation and the evidenced trade-off, then offer:
implement the change (**`rules-developer`** applies it, **`model-validator`** signs it off),
run a `/validate-tm-model` pass, or produce a handover. Threshold changes to live logic are
**never** applied here — they go to `rules-developer`, reviewed before deployment.
