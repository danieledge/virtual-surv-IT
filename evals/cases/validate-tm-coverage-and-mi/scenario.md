# Scenario - periodic TM model validation

**Synthetic eval input.** All data is synthetic. See `expected.yaml` for the
planted ground truth.

## What the team is asked to do

Run a periodic transaction-monitoring model validation (`/validate-tm-model`)
over the attached `model.yaml`. The submission lists the in-scope AML
typologies, the deployed scenarios and their thresholds, and the
model-performance management information (MI).

Assess whether the model is fit for purpose: typology coverage, thresholds,
data integrity, and false-positive / alert-to-SAR performance MI. Report any
findings and give an overall validation opinion.

## Seeded issues (for the harness - not shown to the team)

1. **Coverage gap.** TYP-TBML (trade-based money laundering) is in scope but
   has no scenario mapped to it - an uncovered typology.
2. **Missing performance MI.** `alert_to_sar`, `false_positive_rate` and
   `threshold_tuning_history` are all null. Alert volume is captured, but
   conversion (alert-to-SAR) and FP-rate performance MI are not measured, so
   model effectiveness cannot be evidenced.

## Failure to catch (forbidden)

Concluding the model is "fully fit for purpose" / passes validation despite the
uncovered typology and the missing performance MI. Glossing over both gaps and
signing the model off is the headline failure mode this case exists to catch.
