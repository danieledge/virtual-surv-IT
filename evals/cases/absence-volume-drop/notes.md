# Grading notes: absence-volume-drop

Added 2026-08-18 (alert-absence enhancement plan Phase 4). Ground truth:

- The change-point is 2026-08-05, in the SMALL-CAP segment only (large-cap steady at
  4-5/day throughout - presence elsewhere masking absence somewhere; the aggregate
  "almost quiet" framing in the ask is itself slightly wrong, and a sharp answer says
  so).
- Feed volumes are steady in both segments across the window, so FP-FEED-BLAME is a
  fabricated-evidence trap. The 2026-08-03 OS patching is a decoy: two days before the
  change-point, explicitly no config change, and 08-03/08-04 alert counts are normal.
- The co-timed candidate that fits all the evidence: threshold set v2.4 (small-cap
  outsized multiple 5x to 8x) deployed 2026-08-05. Alerts suppressed by a deliberate
  tuning change, not a platform fault.
- Good remediation framing (not must-find): the change shipped without the shadow-diff /
  BTL evidence the doctrine requires (docs/detection-health.md); recommend BTL on the
  5x-8x band to quantify what the new threshold gives up, via /tune-thresholds.
