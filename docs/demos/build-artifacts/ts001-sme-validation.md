# Typology Validation - TS-001 Wash Trade (DEMO, Run 2)

> The advisory produced by `trade-surveillance-sme` (Camila), reviewing Amara's TS-001 spec.
> Read-only - the SME does not edit code. Obligation: MAR Art 12(1)(a). Synthetic only.

### 1. Is the typology sound?
Yes. The spec correctly targets the MAR Art 12(1)(a) manipulative-transaction typology: opposing
orders from the same beneficial controller creating artificial volume without genuine transfer of
risk. The sequence (pair → fill confirmation → volume/price enrichment → safe-harbour exclusion →
explainable alert) is the standard architecture. **Reinforce:** off-market price must be a
*necessary* condition (hard early-exit), not a weighted score (house-rule) - if scored, a strong
UBO-match compensates for a benign price, a prolific FP source and audit finding.

### 2. Top false-positive drivers
1. **Affiliated-fund two-way flow under one manager** - the highest-volume FP source; the UBO
   perimeter must be scoped carefully ("same UBO" set too wide floods on legitimate rebalancing).
2. **Market-making / riskless-principal** - designated MMs legitimately fill both sides; exempt via
   formal MM designation (EU RTS 3 Art 2, FINRA 5320), applied **before** scoring.
3. **Coincident independent orders at a liquid price** - mitigated precisely by the off-market
   necessary condition; tolerance must be **spread-normalised**, not a fixed bps figure.

### 3. Single biggest pitfall
**Stale / incomplete UBO linkage.** The scenario's whole discriminatory power rests on the
connected-party graph; a stale graph causes both false negatives and false positives, and is the most
common reason a wash-trade scenario fails audit. Mandate a refresh cadence + a data-quality gate that
halts the run if the BO source is stale, and put the BO source's as-of date in the evidence pack.

### 4. One thing the spec got right
Flagging **all** thresholds as open SME/tuning decisions with no invented values. Honest open-flagging
is auditable; invented defaults are not.

### 5. Open-questions disposition
See the spec's [§9 decision log](ts001-scenario-spec.md). Q5/Q6 answered (Q6 → separate TS-002);
Q2 needs deployment input; **Q1 (jurisdiction) + Q3/Q4 (intra-group + connected-party width) are
go-live blockers** → the obligation mapping is **not** safe to finalise.

### Recommendations for `docs/house-rules.md`
(a) spread-normalised off-market threshold; (b) `min_notional` floor is required; (c) UBO refresh
cadence + as-of date in the evidence pack. *(All actioned - see house-rules 2026-06-27.)*
