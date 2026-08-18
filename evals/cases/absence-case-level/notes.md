# Grading notes: absence-case-level

Added 2026-08-18 (alert-absence enhancement plan Phase 4). Ground truth, verified with
`python -m scripts.explain_rule --file fixtures/inputs/orders.jsonl --order CAND-1`:

- Group gates pass (7 orders, trader-median baseline 102.5).
- CAND-1 passes C1 (cancelled), C2 (900ms lifetime vs 2000ms), C3 (0% filled vs 10%),
  C5 (opposite-side fill SELL-X inside the ±3000ms window).
- **First and only failing condition: C4 outsized** - 380 = 3.71x the genuine median vs
  the required 5.0x; distance 25.9% under the configured multiple; the counterfactual is
  "would alert at large_qty_multiple <= 3.71".

A correct response walks the chain (feeds are STATED healthy - re-litigating them is
noise, inventing an outage is the trap), localises to the size condition with numbers,
frames it as a near miss with tuning implications (route to /tune-thresholds, BTL before
any cut - never "just lower it"), and keeps 📊/🧠 honest: with the allow-listed
explain_rule available the numbers are observed, not inferred. The FP-RULE-DEFECT trap
catches blaming a coding error: the rule behaved exactly as configured; this is a
threshold-calibration question, not a defect.

The keyword sets accept either the tool-derived exact figures (3.71x / 25.9%) or honest
rounding (3.7x / 26%).
