# Scenario - coverage assessment with a dead feed

**Synthetic eval input.** All data is synthetic. See `expected.yaml` for the
planted ground truth.

## What the team is asked to do

Run a surveillance coverage assessment (`/assess-coverage`) over the attached
`feeds.yaml`. The inventory lists the in-scope market-abuse typologies, the
detection scenarios deployed against them, and the data feeds those scenarios
rely on (with each feed's live/health status).

Assess whether **every in-scope risk is actually detected** and whether the
**feeds the scenarios depend on are live and complete**. Report any coverage
gaps, route each to the right owner, and close with prioritised remediation.

## Seeded issues (for the harness - not shown to the team)

1. **Dead feed.** `news_reference` is `inactive`, last updated ~7 months ago,
   0% completeness. SCN-001 (insider dealing) depends on it, so that scenario
   fires no alerts despite showing as deployed - a silent blind spot.
2. **Unmapped typology.** TYP-WASH (wash trades) is in scope but has no
   scenario mapped to it - an uncovered typology.

## False-positive trap

The `orders`, `executions` and `market_data` feeds are all live, current and
near-100% complete. A thorough assessment must NOT invent a gap against a
healthy live feed to look diligent.
