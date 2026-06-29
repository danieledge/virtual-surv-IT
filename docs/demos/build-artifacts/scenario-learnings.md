# Wash-trade scenario - learnings (build demo, TS-001)

Scenario-specific knowledge surfaced by the build demo (TS-001, wash trade / self-match). This is
**project/scenario memory** - it lives *with the demo*, not in the plugin's general
[`house-rules.md`](../../house-rules.md). (Per CLAUDE.md §6: the plugin accrues no project memory;
project-specific learnings belong to the project they came from.) The *general* engineering/audit
patterns this demo also surfaced - necessary-condition-as-early-continue, obligation-as-a-field,
provisional-mapping status - are the general ones in `house-rules.md`.

## Typology
- The **beneficial-owner (UBO) link - not legal entity -** is the entry point (accounts under
  common control). **Off-market price must be a *necessary* condition**, validated against the
  **prevailing spread at time of trade**, not a fixed basis-point figure. Obligation: MAR Art
  12(1)(a) (jurisdiction-portable).

## False-positive drivers
- **Affiliated funds under one manager** (legitimate two-way business) - the highest-volume FP
  source; scope the UBO graph as a *surveillance perimeter*, not just "same UBO" (too wide floods
  alerts, too narrow misses abuse).
- **Market-making / riskless-principal** activity - exempt via designated-MM status per
  venue/jurisdiction (RTS 3 / FINRA 5320).
- **Coincident independent orders at a liquid price** - mitigated by the off-market-price necessary
  condition above.

## Tuning
- The off-market threshold's natural unit is **deviation ÷ prevailing spread** (spread-normalised),
  not a flat bps figure; and a **`min_notional` floor is required** (an immaterial-notional pair
  can't give a "false or misleading signal" under MAR Art 12(1)(a)) - a compliance risk-appetite
  decision, not pure statistics.

## Data quality
- **UBO-graph freshness is the keystone.** Stale/incomplete beneficial-owner linkage causes both
  false negatives (missed abuse) and false positives (linking accounts no longer under common
  control), and is the most common reason a wash-trade scenario fails audit. Require a defined
  refresh cadence + a data-quality gate before the scenario runs, and include the BO source + its
  as-of date in the investigator evidence pack.
