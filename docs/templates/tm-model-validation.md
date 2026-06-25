# TM Model Validation Pack - <TM SYSTEM / SCENARIO SET>

> Produced by `/validate-tm-model` (`tuning-analyst` data work + independent `model-validator`
> verdict). Periodic "is the detection still fit for purpose" review - SR 11-7 + FFIEC BSA/AML.
> Synthetic/masked data only (§5). Authored in `.md`, rendered to `.html`.

| | |
|---|---|
| **Scope** | <scenarios / system> |
| **Jurisdiction(s)** | <applicable regime(s)> |
| **Period** | <validation window> |
| **Date** | <YYYY-MM-DD> |
| **Verdict** | ✅ fit for purpose / ⚠️ conditional / ❌ revalidate |
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

## 4. Performance MI
| Metric | This period | Trend | Note |
|---|---|---|---|
| Alert volume | | | |
| False-positive rate | | | |
| Alert-to-SAR/STR conversion | | | |
| Precision / recall proxy | | | |
| Stability over time (decay?) | | | |

## 5. Segmentation validity
Is the risk-based segmentation still right for the current book / customer base?

## 6. Findings & disposition
| # | Sev | Finding | Evidence | Obligation | Disposition |
|---|-----|---------|----------|------------|-------------|

Anything with no straightforward fix → **🔴 Open (needs human review)** with the reason.

## 7. Verdict & next steps
The verdict must match the disposition. Offer: `/tune-thresholds` on weak scenarios, fixes →
`rules-developer`, or handover. Independent model-risk sign-off stays with `model-validator`.
