# Typology Validation - Wash Trade / Self-Match (DEMO)

> **The actual advisory produced by `trade-surveillance-sme` (Camila) during the
> [build demo](../build-demo.md)**, reviewing Amara's spec ([SS-TS-001](wash-trade-scenario-spec.md)).
> Read-only advice - the SME does not edit code. Captured verbatim from the demo run.

**Obligation under review:** MAR Art 12(1)(a)

---

### (1) Is the typology sound?

Yes, substantially. The core logic is correct: beneficial-owner linkage is the right entry point
(legal entity is not enough - related accounts under common control is the test regulators use),
opposite-direction pairs in the same instrument within a window is the standard wash-trade signature,
and the offset test (price and quantity convergence) is the right qualifying criterion. MAR Art
12(1)(a) is the correct citation for transactions that give false/misleading signals as to
supply/demand. CFTC CEA s.4c(a), FINRA Rule 6140, SFA s.197 and SFO s.274 all reach the same conduct,
so the spec is jurisdiction-portable. Flagging lookback, tolerances and repetition as tuning
decisions rather than inventing values is exactly right.

### (2) Top false-positive drivers

- **Legitimate two-way business with a related entity.** Affiliated funds (e.g. a long-only fund and
  a hedge fund under the same asset manager) will routinely trade opposite directions in the same
  name for entirely legitimate portfolio reasons. The beneficial-owner graph must be scoped correctly
  - "same UBO" is not the same as "same surveillance perimeter." A firm that draws the graph too wide
  will flood alerts; too narrow misses the abuse. This is the highest-volume FP source in practice.
- **Market-making and riskless principal activity.** A desk quoting two-way prices, or filling a
  client order from inventory and then hedging the residual, will generate paired trades that
  superficially match the wash pattern. The exemption filter must key off the registered/designated
  market-making status per venue and jurisdiction (RTS 3 under MAR Art 17, FINRA Rule 5320 etc.) and
  must verify the hedging leg is directionally consistent with inventory management, not a mirror.
- **Coincident independent orders at a liquid price level.** In a tight, liquid market, two unrelated
  accounts under the same UBO may independently arrive at the same best price and cross without any
  coordinating intent. A price-tolerance set too wide makes this indistinguishable from a deliberate
  wash. The fix is to require the price to be off-market (or at a stale/non-competitive level) as a
  necessary condition, not just convergence with a tolerance.

### (3) Single biggest pitfall

**Beneficial-owner graph completeness and freshness.** The entire scenario depends on the accuracy of
the BO linkage: stale CRM data, undisclosed nominees, trust structures, or recently acquired
subsidiaries will either produce false negatives (missing the abuse) or false positives (linking
accounts that are no longer under common control). This is a data-quality dependency, not a
detection-logic dependency, and it is the most common reason a wash-trade scenario fails audit
challenge. The spec must require a defined refresh cadence and a data-quality gate before the scenario
runs - and the investigator evidence pack must include the BO source and its as-of date.

### (4) One thing the spec got right

Deferring all threshold values to SME and tuning sign-off with explicit placeholders, rather than
embedding numbers without rationale. Hard-coded tolerances invented in a spec room are the most common
route to a scenario that either never fires or fires constantly, and they create an audit liability
when a regulator asks why that number was chosen.

---

### Recommendations for `docs/house-rules.md`

The team should record: (a) the BO-graph refresh cadence decision once agreed; (b) the chosen scope
rule for affiliated-fund exemptions (UBO vs. legal entity vs. investment-mandate); and (c) the
requirement that price tolerance must be validated against prevailing spread at time of trade, not a
fixed basis-point figure.
