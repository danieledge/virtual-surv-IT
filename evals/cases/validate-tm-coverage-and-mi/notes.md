# Grading notes (NOT shown to the team - do not pass this file to the workflow)

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

## Trap change log

- FP-FULLY-FIT reworked (2026-07-05): the old keywords ("fit for purpose",
  "sign off", "no gaps", ...) were negation-blind - a correct opinion saying
  "cannot sign off" or "not fit for purpose" substring-matched the trap.
  Replaced with endorsement-only phrasings a hedged or negative opinion would
  not contain. The must-find gaps remain the primary signal: a sign-off answer
  fails by missing GAP-COVERAGE / GAP-MISSING-MI.
