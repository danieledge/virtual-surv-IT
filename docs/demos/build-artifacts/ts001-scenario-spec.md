# Scenario Spec - TS-001 Wash Trade / Self-Match (DEMO, Run 2)

> Produced by `business-analyst` (Amara). Obligation: **MAR Art 12(1)(a)**. Synthetic only (§5).
> Status: **SME-validated; open questions dispositioned (§9); obligation mapping PROVISIONAL.**

## 1. Behaviour
A trader or connected group submits offsetting buy/sell orders in the same instrument that match
against each other, creating artificial volume or a false price signal with no genuine change in
economic exposure.

## 2. Regulatory obligation
Primary: **EU MAR Art 12(1)(a)** (false/misleading signals as to supply, demand or price), with
Art 12(2)(c) "no change in beneficial ownership" indicator. Equivalents: UK MAR Art 12; US SEC 10b-5 /
FINRA 6140; CFTC CEA s.4c(a); SG SFA s.197; HK SFO s.274; JP FIEA Art 159.

> **FLAG (resolved in §9):** the obligation mapping above is illustrative - the SME must confirm
> which desks/venues fall under which regime and which safe-harbours apply **before** the mapping is
> finalised. Until then the detector carries `obligation_status = PROVISIONAL`.

## 3. Data required
Trade/order id, instrument id, side, price, quantity/notional, timestamps, trader/desk id, account &
legal-entity id, counterparty id, venue, strategy/algo tag. Plus: UBO/connected-party graph (with
as-of date) and a market snapshot (mid + prevailing spread) per instrument/date. *Contains PII/MNPI -
fixtures are synthetic only (§5).*

## 4. Detection-logic outline (no thresholds)
1. Pair opposing buy/sell legs in the same instrument where accounts share a **UBO / connected-party
   group**, within a lookback window.
2. **Off-market price is a NECESSARY condition** (SME-confirmed) - the average leg price must deviate
   from the prevailing mid beyond a (spread-normalised) threshold; implement as an early-continue.
3. Apply a **safe-harbour exemption** set (designated market-makers) *before* pairing.
4. Raise an explainable alert carrying the matched pair, UBO id, deviation, and the obligation (+status).

## 5. Parameters (SME / tuning decisions - no invented values)
`lookback_days` · `off_market_threshold_bps` (spread-normalised) · `min_notional` (required - see tuning
pack) · `ubo_graph_max_age_days` (data-quality gate) · connected-party definition · safe-harbour list.

## 6. Examples (synthetic)
- **True-positive:** ACCT-A buys, ACCT-B sells SYNTH-EQ-001 (same UBO-X) at 100.60 vs mid 100.00 (60bps
  off-market), same day → alert.
- **False-positive:** designated MM (MM-ACCT-001) two-sided quote fills at mid → suppressed (off-market
  necessary condition + exemption).

## 7. Acceptance criteria (Gherkin)
```gherkin
Scenario: Cross-account self-match, off-market, same UBO -> alert
  Given opposing legs in one instrument from two accounts sharing a UBO group
  And the price is off-market beyond the threshold within the lookback window
  And neither account is exempt
  Then an alert is raised carrying both trade ids, the UBO id, the deviation and the obligation

Scenario: At-market price -> no alert (necessary condition)
  Given the same UBO-linked opposing legs priced at mid
  Then no alert is raised
```

## 8. Open questions for the SME
Q1 jurisdiction scope + safe-harbours · Q2 safe-harbour operationalisation · Q3 intra-group/treasury
treatment · Q4 connected-party definition · Q5 implied-match where no fill confirmation · Q6 cover the
pre-arranged-via-connected-counterparty variant?

## 9. Open-questions disposition (decision log) - `trade-surveillance-sme` (Camila), 2026-06-27
| # | Disposition |
|---|---|
| Q1 | ⏭️ **Needs deployment input** - depends on venues/domicile; safe-harbours are venue-specific. **Blocks the mapping.** |
| Q2 | ⏭️ Needs deployment input - MM-designation feed + buyback register, applied as a pre-filter. |
| Q3 | 🔴 **Open-decision-required** - intra-group/treasury is a firm-policy call (exclude vs separate queue); Legal/Compliance sign-off. |
| Q4 | 🔴 **Open-decision-required** - UBO is the right anchor, but the *width* (entity / group / acting-in-concert) must be chosen; drives BO-graph + alert volume. |
| Q5 | ✅ Answered - implied match is a valid *lower-confidence tier*: tighter window, distinct confidence label, higher review threshold. |
| Q6 | ✅ Answered - real typology but materially harder (needs comms/network analysis); scope as a **separate TS-002**, do not fold in. |

**Bottom line:** obligation mapping **not safe to finalise** - Q1 + Q3/Q4 are go-live blockers.
