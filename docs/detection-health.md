# Detection health - keeping absence visible

> Advisory doctrine the team APPLIES when asked to design, assess or remediate a
> surveillance estate (`/assess-coverage`, `/tune-thresholds`, `/why-no-alert` route
> here). Building the monitoring infrastructure itself is the client platform's job; the
> team specifies and reviews it. Rationale and sources: the alert-absence enhancement
> plan (docs/internal/) - FCA Market Watch 79's three fact patterns, the FINRA
> vendor-change fine, and detection-engineering practice are the evidence base.

The organising rule: **presence elsewhere masks absence somewhere.** Aggregate alert
volume is not scenario health; every control below exists to make absence visible at the
granularity where it hides.

## The four standing controls

1. **Silent-scenario heartbeats.** Zero alerts over a scenario's expected cadence is a
   STATE to alert on, not a comfort. Every scenario carries an expected-alert cadence per
   segment (from its own history or calibration); a breach opens an ops ticket whose
   first move is the `/why-no-alert` lineage walk. "No data" and "nothing to detect" must
   be distinguishable - a scenario with no eligible input in the window reports that,
   never a bare zero.

2. **Per-scenario, per-SEGMENT volume baselines with change-point review.** Alert counts
   tracked at scenario × segment (instrument class, venue, customer segment, channel,
   language) granularity - the level where MW79's Firm B failure hid (liquid-name flow
   masking illiquid-name silence). A detected change-point is correlated against co-timed
   candidates BEFORE any single cause is asserted: deploys/config/threshold changes, feed
   volume change-points, reference-data changes, population changes.

3. **Synthetic canaries.** Periodically inject a known-abusive synthetic pattern (the
   worked example ships generators: `gen_synthetic`'s spoofing session is a ready canary)
   through the FULL path - feed, ingestion, eligibility, evaluation, case creation - and
   assert an alert emerges. A missed canary is unambiguous breakage evidence and
   localises to the first absent stage. Canary events are synthetic and flagged as such
   in the case tool (§5: never real data).

4. **Shadow-diff on every rule/threshold change.** No logic or threshold change ships
   without a before/after alert-count diff on historical data (per segment, not
   aggregate) - the control that catches the "vendor change silently stopped alerts for
   three years" class before production does. The worked example's
   `calibrate_spoofing` + `explain_rule --near-miss` pair is the miniature: population
   metrics plus per-miss narration for anything the change suppresses.

## Where each control is applied

| Control | Applied via |
|---|---|
| Heartbeats + segment baselines | `/assess-coverage` (coverage verdicts are segment-granular, never aggregate-only) and reporting/MI design (`data-analyst`) |
| Change-point correlation | `/why-no-alert` volume-drop form, step 0 |
| Synthetic canaries | `/assess-coverage` recommendations; `qa-engineer` test design for detection deliverables |
| Shadow-diff | `/tune-thresholds` (BTL before any cut, diff before any ship) and `/build-solution` review chain for logic changes |

## What the team does NOT do

Stand up schedulers, dashboards or alerting infrastructure on client estates, or claim a
heartbeat exists because it was recommended. A recommended control is 🧠 advisory until
the client evidences it running; the team's own artifacts state which.
