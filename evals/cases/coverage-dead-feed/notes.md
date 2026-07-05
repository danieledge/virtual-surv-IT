# Grading notes (NOT shown to the team - do not pass this file to the workflow)

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
