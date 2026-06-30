# Wash-trade scenario - learnings (build demo, TS-001)

Scenario-specific knowledge surfaced by the build demo (TS-001, wash trade / self-match). This is
**project/scenario memory** - it lives *with the demo*, not in the plugin's general
[`house-rules.md`](../../house-rules.md). (Per CLAUDE.md §6: the plugin accrues no project memory;
project-specific learnings belong to the project they came from.) The *general* engineering/audit
patterns this demo also surfaced - necessary-condition-as-early-continue, obligation-as-a-field,
provisional-mapping status, re-sync-after-rework - are the general ones in `house-rules.md`.

## Typology
- The **beneficial-owner (UBO) link - not legal entity -** is the entry point (accounts under
  common control). **Off-market price must be a *necessary* condition**, validated against the
  **prevailing spread** (spread-normalised, **mid-referenced**, **time-weighted** denominator),
  implemented as an early-continue. Obligation: MAR Art 12(1)(a) (register-verified).
- **Known, accepted detection gap:** *at-market* wash trading (offsetting fills at the prevailing
  mid that inflate volume / open interest with no price distortion) does **not** alert under the
  off-market necessary condition. This is a deliberate scope choice, not an oversight - candidate
  future scenario **TS-003 (volume / false-volume manipulation)**.

## False-positive drivers
- **Affiliated funds under one manager** - the **single biggest pitfall** and highest-volume FP
  source. It is **structural, not tunable**: if the UBO graph is drawn at management-company level,
  every cross between sibling funds flags. Resolve by drawing the UBO boundary at **fund level**
  (the connected-party-width decision, SME Q4) - threshold tuning cannot fix it.
- **Market-maker / riskless-principal** - exempt, but the taxonomy matters: MM is a
  **designated-status register** entry (per venue/jurisdiction, RTS 3 / FINRA 5320), **not** a
  per-order `strategy_tag`; only riskless-principal/agency is a per-order capacity (SME Q2).
- **Coincident independent orders at a liquid price** - mitigated by the off-market necessary
  condition (at-market coincident fills don't alert).

## Tuning
- Threshold's natural unit is **deviation ÷ prevailing spread** (spread-normalised), referenced to
  **mid**. Measured on a seeded synthetic labelled set, the knee is **~0.75× the spread** (precision
  ~0.84 / recall ~0.84); 0.5× (the touch) over-alerts, 1.0× misses ~28%. **Synthetic number -
  validates the method, not a production figure;** re-confirm on masked/real data before go-live.
- A **`min_notional` floor** is required (an immaterial-notional pair can't give a false/misleading
  signal under MAR Art 12(1)(a)) - a compliance risk-appetite decision, not pure statistics.

## Data quality
- **UBO-graph freshness is the keystone.** Stale/incomplete beneficial-owner linkage causes both
  false negatives and false positives. Handle it as **per-account exclusion + a data-quality
  warning - never a global abort**; when a feed delivers multiple edges for one account, keep the
  **freshest** edge (order-independent). Require a refresh cadence + a DQ gate, and include the BO
  source + as-of date in the investigator evidence pack.
- **Bad market data must leave an audit trail.** A non-positive mid or spread must raise a
  data-quality warning and continue - never a silent discard (a silent drop is an invisible missed
  alert). Treat every market-data fault (missing snapshot, non-positive mid, non-positive spread)
  symmetrically.

## Performance
- The pairing is **O(B×S)** across all trades and **will not scale** at surveillance volume. Bucket
  trades by **`(instrument, ubo_group_id, side)`** before pairing, and dedupe data-quality warnings
  by `(instrument, date)`. A production deploy-gate, not a demo blocker.
