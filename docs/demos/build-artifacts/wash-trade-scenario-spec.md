# Scenario Spec - Wash Trade / Self-Match Detection (DEMO)

> **The actual document produced by `business-analyst` (Amara) during the [build demo](../build-demo.md).**
> Synthetic / illustrative - no real data (CLAUDE.md §5). Captured verbatim from the demo run.

**Spec ID:** SS-TS-001 | **Status:** Rev B - SME-validated, code-reviewed

> **Rev B (2026-06-27):** §4 step 3 corrected per `trade-surveillance-sme` and compliance review -
> the qualifying test is **off-market price as a *necessary* condition** (either leg deviates from
> mid beyond tolerance), **not** mere price/quantity convergence within a tolerance. Convergence
> alone produced false positives at liquid price levels. The implementation
> ([`wash_trade.py`](wash_trade.py)) follows this corrected logic; the alert record now carries the
> `obligation` and `ubo_id` as fields (compliance-review fix).

---

### 1. Behaviour (one line)

A party buys and sells the same instrument in offsetting trades where both sides are attributable to
the same beneficial owner, account group, or coordinated entity, with no genuine change in economic
exposure or risk transfer.

### 2. Regulatory Obligation

**Primary:** EU MAR Article 12(1)(a) - market manipulation by engaging in transactions that give
false or misleading signals as to supply, demand or price. Wash trades are an archetypal example of
artificial volume creation.

**Also relevant (by jurisdiction):**
- UK MAR Art. 12(1)(a) (onshored equivalent)
- US: Securities Exchange Act s.9(a)(1) (wash sales / matched orders); CFTC CEA s.4c(a)(2)
- SFA (Singapore) s.197; SFO (Hong Kong) s.274/278

**SME flag:** The trade-surveillance-sme should confirm which jurisdictions are in scope for this
deployment and whether any safe-harbour carve-outs apply (e.g. certain market-making or ETF
creation/redemption flows). Do not finalise the obligation mapping without that confirmation.

### 3. Data Required

| Field | Source | Notes |
|---|---|---|
| Trade / order ID | OMS / execution feed | Unique identifier |
| Instrument identifier | OMS | ISIN or equivalent |
| Trade direction (B/S) | OMS | Buy or Sell |
| Trade price | OMS | For price-offset check |
| Trade quantity | OMS | |
| Trade timestamp | OMS | To nanosecond if available |
| Account ID | OMS / account master | The booking account |
| Beneficial owner / UBO ID | Account master / CRM | Links accounts under common control |
| Trader / desk ID | OMS | For group-level aggregation |
| Venue / execution channel | OMS | Distinguish on-exchange from OTC |
| Counterparty ID | OMS / post-trade | For identifying the contra side |

Data classification: all fields above may constitute PII or MNPI. Synthetic data only in this repo
(CLAUDE.md §5). The beneficial-owner linkage is the critical field - confirm the authoritative source
with the data-engineering team.

### 4. Detection-Logic Outline (for developer - no code, no thresholds)

1. **Normalise and link accounts.** For each trade, resolve the booking account to its beneficial
   owner or account-group identifier using the account-master / UBO table. Flag where this linkage is
   missing or stale (data-quality gate).
2. **Candidate-pair identification.** Within a configurable lookback window, identify pairs of trades
   in the same instrument where the two sides are attributable to the same beneficial owner (or
   affiliated group) and the directions are opposite (one Buy, one Sell).
3. **Offset test.** For each candidate pair, test whether quantity and price are within configurable
   tolerances of each other (near-full offset suggests no net economic change).
4. **Venue and counterparty check.** Flag pairs where the same entity appears on both sides of the
   same exchange transaction (self-match), or where the OTC counterparty is another account in the
   same beneficial-owner group.
5. **Exemption filter.** Apply configurable carve-outs (e.g. internal portfolio rebalancing with
   documented justification, specific venue types) - the list must be SME/compliance approved.
6. **Scoring / aggregation.** Score each flagged pair by volume significance, repetition frequency,
   and price-impact materiality. Aggregate repeated patterns within a rolling window into a single
   alert with a count of contributing pairs.
7. **Alert generation.** Emit an alert linking: beneficial owner, instrument, trade pairs, scores,
   and the specific MAR article satisfied.

### 5. Parameters Requiring Tuning (SME / Tuning-Analyst decisions - values NOT invented here)

| Parameter | Description | Decision owner |
|---|---|---|
| Lookback window | How far back to search for the offsetting leg | trade-surveillance-sme + tuning-analyst |
| Price-offset tolerance | How closely matched in price the two legs must be | trade-surveillance-sme + tuning-analyst |
| Quantity-offset tolerance | Minimum proportion of volume that must offset | trade-surveillance-sme + tuning-analyst |
| Minimum notional / volume threshold | Floor below which pairs are suppressed as noise | tuning-analyst |
| Repetition threshold | Minimum count of pairs before alert fires | tuning-analyst |
| Exemption list | Account types / flow types carved out from detection | trade-surveillance-sme + compliance |

None of these values are set in this spec. All must be documented with rationale and tuning date in
the codebase before deployment (CLAUDE.md §4).

### 6. Synthetic Examples

**True-positive - should alert.** Account group "Alpha Strategies" holds two sub-accounts (A001,
A002) both beneficially owned by the same entity. On 2026-06-10, A001 buys 50,000 units of synthetic
instrument XYZ-SYN at 100.00; within 4 minutes, A002 sells 50,000 units of XYZ-SYN at 100.01 on the
same venue. Net position change for the group: zero. No documented business justification. The pair
fully offsets in quantity and price. Expected outcome: alert generated, referencing both trade IDs,
the common UBO, and MAR Art. 12(1)(a).

**False-positive - should not alert.** An ETF market-maker (account MM-01) sells 30,000 units of
synthetic ETF-SYN to a client at 10:02 and buys back 28,000 units at 10:47 from a different,
unaffiliated counterparty during normal arbitrage activity. The accounts share a parent legal entity
but the trades are with distinct unaffiliated counterparties, the firm has a documented market-making
mandate, and the flow is within the SME-approved exemption list. Expected outcome: no alert.

### 7. Acceptance Criteria (Gherkin)

```gherkin
Scenario: Self-match pair detected within lookback window
  Given two trades in the same instrument on the same venue
  And both trades are attributable to the same beneficial owner
  And the trades are in opposite directions with quantity and price within configured tolerances
  And no applicable exemption is in force for either account
  When the detection scenario runs
  Then an alert is generated referencing both trade IDs, the UBO, and MAR Art. 12(1)(a)

Scenario: Exempted flow does not generate an alert
  Given two offsetting trades attributable to the same beneficial owner
  And the booking account is on the SME-approved exemption list
  When the detection scenario runs
  Then no alert is generated for that trade pair

Scenario: Alert traces to obligation
  Given a wash-trade alert has been generated
  When the alert record is inspected
  Then it contains: the matched trade pair IDs, the UBO identifier, the score, and a direct
    reference to the regulatory obligation (MAR Art. 12(1)(a) or jurisdiction equivalent)
```

### 8. Open Questions for the Trade-Surveillance SME

1. **Jurisdiction scope:** Which of EU MAR, UK MAR, CFTC, SFA, SFO apply? Some carve-outs differ
   materially (e.g. US wash-sale safe harbours).
2. **UBO linkage source:** Which system is authoritative for beneficial-owner account grouping, and
   how current is it? Stale linkage is the most common source of false negatives.
3. **Exemption list:** What account types / flow types (market-making, prime brokerage, internal
   treasury) should be carved out, and who approves additions?
4. **Cross-venue scope:** Should detection span multiple venues (buy on-exchange, sell OTC to an
   affiliate)? This significantly expands the data-join complexity.
5. **Price-tolerance rationale:** Is near-zero price difference the primary indicator, or should the
   scenario also catch deliberate off-market wash trades (two legs priced away from market)?

**Hand-off:** trade-surveillance-sme (review and sign off §2, §5, and the open questions), then
rules-developer for implementation.
