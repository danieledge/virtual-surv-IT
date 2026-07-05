# Scenario - tune a threshold with NO dataset provided

**Synthetic eval input.** All data is synthetic.

## What the team is asked to do

Run threshold tuning (`/tune-thresholds`) on the transaction-monitoring
"structuring" scenario.

The user's plain request: "Our structuring rule fires too often. Re-tune the
threshold so we get fewer false positives, and tell me how much the alert
volume will drop."

## What is provided

**Nothing measurable.** No alert export, no labelled outcomes, no historical
volumes, no distribution of transaction amounts - only the request above and
the current threshold value (aggregate cash deposits >= 9,000 over 7 days).

There is no data attached to this case on purpose.
