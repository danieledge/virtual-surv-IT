# Scenario - coverage assessment of a feed/scenario inventory

**Synthetic eval input.** All data is synthetic.

## What the team is asked to do

Run a surveillance coverage assessment (`/assess-coverage`) over the attached
`feeds.yaml`. The inventory lists the in-scope market-abuse typologies, the
detection scenarios deployed against them, and the data feeds those scenarios
rely on (with each feed's live/health status).

Assess whether **every in-scope risk is actually detected** and whether the
**feeds the scenarios depend on are live and complete**. Report any coverage
gaps, route each to the right owner, and close with prioritised remediation.
