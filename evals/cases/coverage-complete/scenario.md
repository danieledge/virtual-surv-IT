# Scenario - coverage assessment of a fully covered inventory

**Synthetic eval input.** All data is synthetic. See `expected.yaml` for the
planted ground truth.

## What the team is asked to do

Run a surveillance coverage assessment (`/assess-coverage`) over the attached
`feeds.yaml`. The inventory lists the in-scope market-abuse typologies, the
detection scenarios deployed against them, the data feeds those scenarios rely
on, and the in-scope comms population and its channels.

Assess whether every in-scope risk is detected and whether the feeds and
channels are live, complete and monitored. Report any genuine coverage gaps and
close with a recommendation.

## Seeded issues (for the harness - not shown to the team)

None. This inventory is fully covered:
- every in-scope typology (insider, spoofing, wash trades) has a scenario;
- every feed is `active`, current and near-100% complete;
- every comms channel is captured and monitored.

## False-positive trap (the whole case)

This case tests false-alarm restraint: the assessment must NOT invent a gap to
look thorough. The correct answer is "no coverage gaps found - coverage is
complete", with a recommendation to keep monitoring feed health. Any fabricated
gap is a failure.
