# Scenario Spec - TS-001 Wash Trade / Self-Match (DEMO)

> Produced by `business-analyst` (Amara). Synthetic data only (§5). DEMO artefact.

> **Document control** · ID `SCN-001` · Version `0.1` · Status `Draft`
> · Classification `Internal` · Owner `business-analyst (Amara)` · As-of `2026-06-30`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-06-30 | Amara | Initial draft |

---

## 1. Need / trigger

Regulators and internal compliance require that the firm detect wash trading and self-matching
conduct: the submission of offsetting buy and sell orders by a trader or economically connected
group that match against each other, generating artificial volume or a false price signal while
producing no genuine change in beneficial ownership or economic risk. Left undetected, this
conduct exposes the firm to regulatory censure, reputational damage and potential civil or
criminal liability. A detective control is required to identify matched pairs and generate an
explainable, obligation-traceable alert for review.

---

## 2. Regulatory obligation

**Primary obligation:** EU MAR Art.12(1)(a) - transactions, orders to trade or other behaviour
that give, or are likely to give, false or misleading signals as to the supply of, demand for,
or price of a financial instrument. (`obligation_status = PROVISIONAL` - see flag below.)

**Indicator:** EU MAR Art.12(2)(c) - transactions or orders where there is no change in
beneficial ownership. `TO-VERIFY (🧠)` - Art.12(2)(c) is not yet in `config/regulatory-register.yaml`;
add and verify against the primary source before obligation mapping is finalised.

**Jurisdiction equivalents (all `TO-VERIFY (🧠)` - not in the register; confirm pinpoints
against primary sources before going live in those regimes):**

| Regime | Pinpoint | Status |
|---|---|---|
| UK MAR | UK MAR Art.12(1)(a) | TO-VERIFY (🧠) |
| US (SEC) | SEC Rule 10b-5 (Exchange Act s.10(b)) | TO-VERIFY (🧠) |
| US (FINRA) | FINRA Rule 6140 | TO-VERIFY (🧠) |
| US (CFTC) | CEA s.4c(a) | TO-VERIFY (🧠) |
| SG | SFA s.197 | TO-VERIFY (🧠) |
| HK | SFO s.274 | TO-VERIFY (🧠) |
| JP | FIEA Art.159 | TO-VERIFY (🧠) |

> **PROVISIONAL flag (ADR-001):** the obligation mapping above is illustrative. The
> `trade-surveillance-sme` (Camila) must confirm which desks, venues and domiciles fall under
> which regime and which safe-harbours apply before this mapping is finalised. Until then the
> detector carries `obligation_status = PROVISIONAL` in every alert. The citation `MAR Art.12(1)(a)`
> is `status: verified` in the register; all others must be added and verified.

**Control mapping:**

| Obligation | Control ID | Control name | Control type |
|---|---|---|---|
| EU MAR Art.12(1)(a) | CTRL-TS-001 | Wash trade / self-match detection | Detective |
| EU MAR Art.12(2)(c) (TO-VERIFY) | CTRL-TS-001 | Same as above (indicator) | Detective |

---

## 3. Typology / behaviour

A trader or economically connected group (sharing a UBO or connected-party relationship)
submits opposing buy and sell orders in the same instrument. The orders match against each
other - either on the same venue (direct self-match) or arranged across accounts - creating the
appearance of genuine market activity: inflated volume and/or a price signal. Because the same
beneficial owner is on both sides, no real transfer of economic risk occurs.

Key behavioural indicators:
- Opposing legs in the same instrument within a short lookback window.
- Counterparty accounts linked by a common UBO or connected-party relationship.
- Execution price that deviates from the prevailing market mid beyond the spread (off-market
  price is a **necessary condition**, not a scored factor - see DR-002).
- No legitimate economic rationale (e.g., not a designated market-maker, not a riskless-principal).

Variant in scope: single-account wash (one account takes both sides if the venue permits).
Variant out of scope (separate scenario): pre-arranged trade via an unconnected counterparty
(requires comms/network analysis - defer to TS-002; see §7).

---

## 4. Data requirements

All fields containing personal or firm identifiers, account numbers or trade details are
classified **PII / potentially MNPI**. No real records may appear in this repository; all
fixtures must be fully synthetic (§5).

| Field group | Fields required | Source system (indicative) |
|---|---|---|
| Trade / order identity | trade_id, order_id | OMS / execution system |
| Instrument | instrument_id, asset_class, venue | Reference data |
| Economics | side (buy/sell), price, quantity, notional, currency | OMS / trade blotter |
| Timing | order_timestamp, execution_timestamp | OMS |
| Parties | trader_id, desk_id, account_id, legal_entity_id, counterparty_id | CRM / entity master |
| Classification | strategy_tag, algo_tag | OMS / algo system |
| Ownership graph | UBO_group_id, connected_party_flag, graph_as_of_date | Ownership / BO registry |
| Market snapshot | mid_price, prevailing_spread_bps, snapshot_timestamp | Market data feed |

---

## 5. Detection requirements (EARS)

Thresholds (`lookback_days`, `off_market_threshold_bps`, `min_notional`,
`ubo_graph_max_age_days`) are SME / tuning-analyst decisions and must not be invented here;
each is flagged as a tuning decision below.

| ID | Detection requirement (EARS) | Rationale / source |
|---|---|---|
| DR-001 | When two or more trade or order records in the same instrument are identified within the configured lookback window, the system shall group them by UBO/connected-party group (using the ownership graph, filtered to records where `graph_as_of_date` is within the freshness limit) and pair opposing buy/sell legs within each group. | Typology §3; UBO graph requirement - Q3/Q4 open (§7). `lookback_days` = tuning decision. |
| DR-002 | When a candidate pair is identified under DR-001, the system shall apply the off-market price test as an **early-continue**: if the average execution price of the pair does not deviate from the prevailing mid by more than the configured spread-normalised threshold, the system shall immediately discard the pair and generate no alert. | Off-market price is a necessary condition (not a score); prevents at-market fills from alerting. `off_market_threshold_bps` = tuning decision (spread-normalised). |
| DR-003 | When a candidate pair passes DR-002, the system shall check each account against the current safe-harbour exemption register; if either account is exempt (e.g., designated market-maker, riskless-principal), the system shall suppress the alert for that pair and log the suppression reason. | Safe-harbour pre-filter; Q1/Q2 open (§7). Exemption list = deployment/SME decision. |
| DR-004 | When a candidate pair passes DR-002 and DR-003, and the notional value of the pair meets or exceeds the configured minimum notional floor, the system shall raise an alert containing: both trade/order identifiers, instrument identifier, UBO/connected-party group identifier, spread-normalised price deviation, `obligation_status`, and the applicable obligation reference(s). | Alert content must be explainable and obligation-traceable (CLAUDE.md §4). `min_notional` = risk-appetite / tuning decision. |
| DR-005 | When the `graph_as_of_date` of the ownership graph for an account exceeds the configured freshness limit, the system shall exclude that account's pairs from alert generation and raise a data-quality warning. | Stale UBO data creates false negatives; data-quality gate. `ubo_graph_max_age_days` = tuning decision. |
| DR-006 | When an opposing-leg pair is identified by UBO/connected-party grouping but no confirmed fill record exists for one leg (implied match), the system shall, if the implied-match tier is enabled, raise a lower-confidence alert with a distinct `confidence_tier` label and apply a tighter lookback window for that tier. | Implied match is a valid lower-confidence variant; see Q5 (§7). Tier enablement and tighter window = SME/tuning decision. |

---

## 6. Acceptance criteria (Gherkin)

All identifiers and prices below are **synthetic** (§5).

```gherkin
Feature: TS-001 Wash trade / self-match detection

  # --- True-positive scenarios (MUST alert) ---

  Scenario: Off-market cross-account self-match, same UBO group -> alert
    Given account ACCT-SYNTH-A and ACCT-SYNTH-B share UBO group UBO-SYNTH-X (graph current)
    And ACCT-SYNTH-A places a buy order on SYNTH-EQ-001 at price 100.60
    And ACCT-SYNTH-B places a sell order on SYNTH-EQ-001 at price 100.60
    And the prevailing mid is 100.00 and the spread is 5 bps
    And the orders execute within the configured lookback window
    And neither account appears on the safe-harbour exemption register
    And the paired notional meets the minimum notional floor
    Then the system raises an alert for the pair
    And the alert carries both trade identifiers, UBO-SYNTH-X, the spread-normalised deviation,
        the applicable obligation reference, and obligation_status = PROVISIONAL

  Scenario: Same-account wash trade (single account, both sides) -> alert
    Given account ACCT-SYNTH-C is on both sides of a matched trade in SYNTH-EQ-002
    And the execution price is off-market beyond the configured threshold
    And the account is not exempt
    Then the system raises an alert

  # --- False-positive controls (MUST NOT alert) ---

  Scenario: At-market price - necessary condition fails -> no alert
    Given account ACCT-SYNTH-A and ACCT-SYNTH-B share UBO group UBO-SYNTH-X
    And the opposing legs execute at the prevailing mid (within spread)
    Then the system discards the pair via the early-continue (DR-002) and raises no alert

  Scenario: Designated market-maker exemption -> no alert
    Given account MM-ACCT-SYNTH-001 is listed on the safe-harbour exemption register
    And MM-ACCT-SYNTH-001 provides a two-sided quote that fills at an off-market price
    Then the system suppresses the alert and logs the suppression reason (DR-003)

  Scenario: Stale UBO graph -> data-quality warning, no alert
    Given the ownership graph for ACCT-SYNTH-D has a graph_as_of_date beyond the freshness limit
    Then the system raises a data-quality warning and excludes ACCT-SYNTH-D's pairs from alerts (DR-005)

  Scenario: Implied match, lower-confidence tier enabled -> lower-confidence alert
    Given ACCT-SYNTH-A and ACCT-SYNTH-B are UBO-linked
    And no confirmed fill exists for ACCT-SYNTH-B's leg (implied match)
    And the implied-match tier is enabled
    Then the system raises an alert with confidence_tier = LOWER_CONFIDENCE and a distinct label
```

---

## 7. Out of scope / assumptions / open questions

**Out of scope:**
- Pre-arranged wash via an unconnected counterparty (requires comms/network analysis) - scope
  as TS-002.
- Cross-asset wash (different instrument classes) - not in scope for this iteration.
- Historical back-fill of alerts prior to go-live.

**Assumptions:**
- The UBO/connected-party ownership graph is maintained by an upstream system and delivered to
  the detection layer with a reliable `graph_as_of_date` field.
- A safe-harbour exemption register (market-maker designations, riskless-principal flags) is
  maintained and accessible as a reference feed.
- A market data feed providing mid price and prevailing spread per instrument per date is
  available.

**Open questions for `trade-surveillance-sme` (Camila) to disposition before sign-off:**

| # | Question | Owner |
|---|---|---|
| Q1 | Which desks, venues and client domiciles are in scope under each regime listed in §2? Which safe-harbours apply per venue/regime (e.g., MiFID II market-maker exemption)? **Blocks obligation mapping.** | trade-surveillance-sme |
| Q2 | How is the safe-harbour exemption operationalised? Is there a maintained MM-designation feed or buyback register that can serve as the pre-filter in DR-003? | trade-surveillance-sme |
| Q3 | How should intra-group and treasury transactions be treated? Exclude from detection entirely, or route to a separate review queue with lower priority? This is a firm-policy call requiring Legal/Compliance sign-off. | trade-surveillance-sme / Legal |
| Q4 | What is the required width of the connected-party definition (entity-level UBO only, or full acting-in-concert group)? This drives the ownership-graph schema and alert volume. | trade-surveillance-sme |
| Q5 | Should the implied-match lower-confidence tier (DR-006) be enabled at launch? If so, what tighter lookback window applies? | trade-surveillance-sme / tuning-analyst |

---

## 8. Hand-off

SME for review and open-question disposition: `trade-surveillance-sme` (Camila).
Implementer: `rules-developer` (Mateo).
Threshold calibration (once SME questions are dispositioned): `tuning-analyst` (Theo).
Independent QA: `qa-engineer` (Linh).

---

## 9. Open-questions disposition (decision log)

To be completed by `trade-surveillance-sme` (Camila) before the obligation mapping is
finalised and sign-off is given.

| # | Question | Owner | Disposition |
|---|---|---|---|
| Q1 | Regime / venue / safe-harbour scope | trade-surveillance-sme | **Open** |
| Q2 | Safe-harbour exemption operationalisation | trade-surveillance-sme | **Open** |
| Q3 | Intra-group / treasury treatment | trade-surveillance-sme / Legal | **Open** |
| Q4 | Connected-party definition width | trade-surveillance-sme | **Open** |
| Q5 | Implied-match tier enablement | trade-surveillance-sme / tuning-analyst | **Open** |

**Bottom line:** obligation mapping is **not safe to finalise**. Q1 (regime/venue/safe-harbour
scope) is a go-live blocker. Q3 (intra-group treatment) and Q4 (connected-party width) are
go-live blockers. Q2 and Q5 are required before implementation but do not block the obligation
mapping itself.

---

## Sign-off

| Role | Name | Decision | Date |
|---|---|---|---|
| Author / owner | Amara (business-analyst) | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver | | | |
