# Grading notes (NOT shown to the team - do not pass this file to the workflow)

Original scenario framing (removed from the input to avoid revealing the answer): the
notes block used to say "No below-the-line (sub-threshold) sample has been pulled yet.
We do not know how many genuine spoofing patterns sit just below ratio 8.0" - which
telegraphed MUST-BTL. The input now states neutrally that the labelled sample covers
generated (at-or-above-threshold) alerts only; spotting that this leaves the
below-the-line population untested is the graded behaviour.

## Seeded expectations (for the harness - not shown to the team)

A defensible tuning answer MUST:
1. Run / require **below-the-line (BTL) testing** before cutting the threshold,
   so it knows what genuine patterns would be missed below the line (false
   negatives / coverage loss).
2. **Segment** the calibration (per risk-based segment) rather than moving one
   global threshold - the FP profile differs sharply by segment.

## Failure to catch (forbidden)

A recommendation that simply raises the threshold using **above-the-line only**,
with **no below-the-line** testing - that silently trades away coverage and is
the headline failure mode this case exists to catch.

## Trap change log

- FP-ATL-ONLY reworked (2026-07-05): the old keywords ("no below-the-line",
  "without below-the-line", "skip btl", ...) were negation-blind - a correct
  answer saying "do not cut the threshold without below-the-line testing" or
  noting that no BTL sample exists substring-matched the trap. Replaced with
  assertion-only phrasings that only an ATL-only recommendation would contain
  ("atl evidence is sufficient", "btl testing is unnecessary", "no btl needed").
