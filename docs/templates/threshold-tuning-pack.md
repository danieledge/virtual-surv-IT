# Threshold Tuning Pack - <SCENARIO / RULE>

> Produced by `tuning-analyst`. Evidence for a threshold/parameter change, defensible to a
> regulator. Statistical analysis on **synthetic/masked data only** (§5). Authored in `.md`,
> rendered to `.html`. Threshold changes to live logic are implemented by `rules-developer` and
> signed off by `model-validator` - this pack is the recommendation, not the production change.

> **Document control** · ID `TUNE-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Internal | Confidential` · Owner `<name / role>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

| | |
|---|---|
| **Scenario / rule** | <name + the obligation it serves (CLAUDE.md §2)> |
| **Jurisdiction(s)** | <applicable regime(s)> |
| **Data window** | <period; synthetic/masked> |
| **Date / tuner** | <YYYY-MM-DD> |
| **Recommendation** | <proposed change in one line> |
| **Next review date** | <YYYY-MM-DD> |
| **Re-tune triggers** | <volume spike >X%; FP rate >Y%; alert-to-SAR/STR falls below Z%; book composition change; new product/segment; regulatory change> |

## 1. Objective & current state
What we're tuning and why (FP too high? coverage gap? volume budget?). Current threshold(s) and
current alert volume / FP rate / alert-to-SAR.

## 2. Segmentation (risk-based)
Calibrate per segment, not one global threshold. State the segments and why.

| Segment | Definition | Population | Behaviour profile (median / spread) |
|---|---|---|---|

## 3. Candidate thresholds & statistical rationale
Derived from the genuine population's distribution - percentile / **std-dev multiple** / tail
(EVT for rare large events). Record the rationale + date (§4); no round numbers without it.

| Segment | Current | Candidate | Basis (e.g. P95 / μ+3σ) | Rationale |
|---|---|---|---|---|

## 4. Above-The-Line (ATL) test - precision among flagged
Sample flagged activity at the candidate threshold; label true vs false positive.

| Segment | Sampled | True positives | False positives | Precision |
|---|---|---|---|---|

## 5. Below-The-Line (BTL) test - what's missed just under the line
Sample activity just below the candidate; estimate false negatives / coverage gaps. **This is
what stops tuning creating blind spots.**

| Segment | Sampled (sub-threshold) | Looks suspicious (missed) | Coverage risk |
|---|---|---|---|

## 6. Dry-run - projected volume & population change
Candidate parameters over the historical (masked/synthetic) window.

| Segment | Alerts now | Alerts (candidate) | Δ volume | Population added / dropped |
|---|---|---|---|---|

## 7. Volume ↔ coverage trade-off & recommendation
The headline a regulator wants: at the recommended threshold, **X% fewer alerts** for **what
coverage cost** (from BTL). State the recommendation per segment, the **expected effect at the
firm's volumes**, and residual risk. Never assert a number without the ATL/BTL + dry-run evidence.

## 8. Performance MI - ongoing monitoring
Track after deployment to detect decay and confirm the tuning held.

| Metric | Definition | Calculation | Current | Target | Basis |
|---|---|---|---|---|---|
| Alert volume | Count of alerts raised per period | `count(alert_id) by segment, period` | | | 📊 |
| False-positive rate | FP alerts / total alerts | `count(FP) / count(alert)` | | | 📊 |
| Precision | TP / (TP + FP) at threshold | `count(TP) / count(TP + FP)` | | | 📊 |
| Alert-to-SAR/STR conversion | SARs/STRs filed / alerts raised | `count(SAR_or_STR) / count(alert)` | | | 📊 |
| Analyst productivity | Alerts reviewed per analyst per day | `count(reviewed) / (analysts x days)` | | | 📊 |
| Stability | Month-on-month alert volume variance | std-dev of monthly alert counts | | | 📊 |

## 9. Next steps
Implementation → `rules-developer`; independent sign-off → `model-validator`. Re-tune cadence
and triggers are recorded in the header fields above.

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
