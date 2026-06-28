# TM Model Validation Pack - <TM SYSTEM / SCENARIO SET>

> Produced by `/validate-tm-model` (`tuning-analyst` data work + independent `model-validator`
> verdict). Periodic "is the detection still fit for purpose" review - SR 11-7 + FFIEC BSA/AML.
> Synthetic/masked data only (§5). Authored in `.md`, rendered to `.html`.

> **Document control** · ID `TMV-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Internal | Confidential` · Owner `<name / role>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

| | |
|---|---|
| **Scope** | <scenarios / system> |
| **Jurisdiction(s)** | <applicable regime(s)> |
| **Period** | <validation window> |
| **Date** | <YYYY-MM-DD> |
| **Verdict** | Fit for purpose / Conditional / Revalidate required |
| **Disposition** | ✅ _N_ fixed · 🔴 _N_ open · ⚖️ _N_ accepted · ⏭️ _N_ deferred |

## 1. Coverage - are the firm's risks & typologies all detected?
Map in-scope typologies/obligations → scenarios. Flag gaps (a typology with no scenario = an
undetected-abuse blind spot). *(Coverage of the data feeds → `data-quality-reviewer`.)*

| Typology / obligation | Scenario(s) | Covered? | Gap / risk |
|---|---|---|---|

## 2. Threshold adequacy
Are thresholds still appropriate or have they drifted? Summarise ATL/BTL evidence (detail in the
threshold-tuning pack). Flag scenarios that need re-tuning.

## 3. Data integrity
Completeness, accuracy, timeliness and reconciliation of the feeds the model depends on (hand to
`data-quality-reviewer`). A late/partial feed silently degrades detection.

## 4. Model assumptions - stated and challenged
List every assumption the model rests on and the challenge applied. SR 11-7 requires that
assumptions are identified, documented, and independently tested.

| # | Assumption | Where it appears in logic | Challenge / test applied | Result | Basis |
|---|---|---|---|---|---|
| 1 | <e.g. customer risk scores are refreshed monthly> | <segment assignment> | <checked refresh cadence in source system> | <...> | 📊 |
| 2 | <e.g. cash transactions below USD 3k are low risk> | <de minimis exclusion> | <BTL sample of sub-threshold activity> | <...> | 📊 |

## 5. Performance MI
Metrics with explicit denominators so two validators compute the same number.

| Metric | Definition | Numerator | Denominator | This period | Prior period | Trend | Note |
|---|---|---|---|---|---|---|---|
| Alert volume | Total alerts raised in period | count(alert_id) | n/a | | | | |
| False-positive rate | Alerts reviewed and closed as FP / alerts reviewed | count(closed_FP) | count(reviewed) | | | | |
| Alert-to-SAR/STR conversion | SAR/STR filings sourced from alerts / alerts reviewed | count(SAR_or_STR where source=alert) | count(reviewed) | | | | |
| Precision proxy | TP alerts / (TP + FP) in reviewed sample | count(TP in sample) | count(TP + FP in sample) | | | | |
| Recall proxy | TP alerts / (TP + FN) from BTL + labelled set | count(TP) | count(TP + FN) | | | | |
| Stability | Month-on-month volume variance | std-dev(monthly alert counts) | mean(monthly alert counts) | | | | flag if >25% MoM swing |

## 6. Segmentation validity
Is the risk-based segmentation still right for the current book / customer base?

## 7. Backtesting / historical stress
Apply current thresholds and logic retrospectively over a historical stressed window (e.g. a
period known to contain confirmed cases, a period of elevated volume, or the last regulatory
examination window). Confirm the model would have fired on known true positives and assess
false-negative rate on the stressed sample.

| Scenario | Stressed window | Known TPs in window | TPs caught by model | Missed (FN) | FP rate in window | Basis |
|---|---|---|---|---|---|---|
| <e.g. Scenario A> | <e.g. Q1 2024 (confirmed cases from SAR log)> | <n> | <n> | <n> | <%> | 📊 |

## 8. Findings & disposition
Severity: 🔴 Critical · 🟠 High · 🟡 Medium · 🔵 Low

| # | Sev | Finding | Evidence | Obligation | Disposition |
|---|-----|---------|----------|------------|-------------|

Anything with no straightforward fix → **🔴 Open (needs human review)** with the reason.

Disposition tally: ✅ _N_ · 🔴 _N_ · ⏭️ _N_ · ⚖️ _N_

## 9. Verdict & next steps
The verdict must match the disposition. Offer: `/tune-thresholds` on weak scenarios, fixes →
`rules-developer`, or handover. Independent model-risk sign-off stays with `model-validator`.

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
