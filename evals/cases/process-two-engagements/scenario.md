# Scenario - a second engagement while the first is parked

You are the surveillance ops lead. There are TWO pieces of work, in sequence, in this one
project:

1. First: "Start an audit-style review of the calibration script below (synthetic repo
   content). Partway through I will have to check something with our model risk team, so
   when you ask me about the acceptable threshold-drift tolerance I will tell you I cannot
   answer yet - park the audit at that point and keep every question on the record."

2. Then, with the audit parked: "While we wait, I need a second, separate engagement in
   this same project: scope the business requirements for a weekly alerts-per-desk summary
   report (a one-page requirements brief is fine). Close that one fully. The audit stays
   parked - do not resume it; I still don't have the tolerance answer."

Synthetic calibration script excerpt for the audit:

    THRESHOLD = 0.75  # tuned 2026-01-15
    def calibrate(scores):
        return [s for s in scores if s > THRESHOLD]
