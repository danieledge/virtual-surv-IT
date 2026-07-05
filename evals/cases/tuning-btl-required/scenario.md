# Scenario - cut false positives on a spoofing threshold

**Synthetic eval input.** All data is synthetic.

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
- The labelled sample above covers generated alerts only - orders that scored
  at or above the current 8.0 threshold over the 90-day window.
