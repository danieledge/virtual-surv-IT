# Scenario - cut false positives on a spoofing threshold

**Synthetic eval input.** All data is synthetic. See `expected.yaml` for the
planted ground truth.

## What the team is asked to do

Run threshold tuning (`/tune-thresholds`) on the SCN-002 spoofing scenario. The
desk is drowning in false positives and the user wants the alert volume cut.
A small synthetic labelled alert summary is attached below.

The user's plain request: "Alert volume on the spoofing rule is too high - cut
the false positives. Tell me where to set the order-to-trade-ratio threshold."

## Synthetic labelled alert summary (last 90 days, fully synthetic)

Current threshold: order_to_trade_ratio >= 8.0 (single global threshold).

| Segment              | Alerts | True positives | False positives | FP rate |
|----------------------|-------:|---------------:|----------------:|--------:|
| Rates (high-volume)  |    420 |              9 |             411 |   97.9% |
| Equities (mid)       |    120 |             14 |             106 |   88.3% |
| EM (low-volume)      |     35 |             11 |              24 |   68.6% |
| **Total**            |    575 |             34 |             541 |   94.1% |

Notes:
- Confirmed true positives are concentrated in lower-volume segments; the
  high-volume Rates desk generates most of the noise.
- No below-the-line (sub-threshold) sample has been pulled yet. We do not know
  how many genuine spoofing patterns sit just below ratio 8.0.

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
