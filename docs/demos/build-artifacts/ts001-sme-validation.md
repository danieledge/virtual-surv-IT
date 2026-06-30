# SME Validation - TS-001 Wash Trade / Self-Match (DEMO)

> **Document control** · ID `SMV-001` · Version `0.1` · Status `In review` · Classification `Internal` · Owner `trade-surveillance-sme (Camila)` · As-of `2026-06-30`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-06-30 | Camila (trade-surveillance-sme) | Initial SME validation against SCN-001 v0.1 |

---

## Basis of Validation

This document validates the typology design and dispositions the open questions in Scenario Spec SCN-001 v0.1 (`docs/demos/build-artifacts/ts001-scenario-spec.md`). The regulatory register reviewed is at `config/regulatory-register.yaml` as-of the validation date. Claims are tagged 📊 (observed in the spec or a verified cited source) or 🧠 (industry practice / reasoned beyond the cited sources). Pinpoint citations absent from the register are flagged explicitly and must not appear in live alert records or regulatory reports until verified and added.

---

## 1. Typology Confirmation

### 1.1 UBO / Connected-Party as Entry Point (Not Legal Entity)

The spec's use of UBO/connected-party grouping as the entry point for pairing opposing legs is confirmed correct. 📊

Operating at the legal-entity level is insufficient. A wash-trading scheme is routinely structured across multiple legal entities that share the same beneficial owner precisely to evade entity-level detection. The detection must traverse the ownership and control graph to the natural or legal person who ultimately controls both sides. This is the operationalisation of the no-change-in-beneficial-ownership concept that is the typology's definitional core across all in-scope regimes. 🧠

Two caveats apply: (a) the width of the connected-party definition (Q4, unresolved) determines which relationships are included and therefore drives alert volume materially; (b) the UBO graph freshness gate in DR-005 is correctly specified - stale graph data generates false negatives (missed connections), not false positives, so the freshness limit is a detection-coverage control, not a precision control.

### 1.2 Off-Market Price as Necessary Condition

The treatment of off-market price as a necessary condition (early-continue, DR-002) and not a scored factor is confirmed correct and architecturally defensible. 📊

An at-market fill between connected parties does not create a false price signal; it contributes only to volume. Volume-only wash trading is a genuinely prohibited typology under MAR Art.12(1)(a) (which covers false signals as to supply and demand, not only price), but it cannot be addressed within TS-001's data model, which does not reconstruct the full order book or distinguish orders that would have cleared at the same price regardless of which party submitted them. Treating at-market fills as out of scope for TS-001 is a known detection gap: at-market wash trading to inflate volume or open interest will not alert. This gap must be documented in the project's CLAUDE.md and should be scoped as a separate future scenario (suggested: TS-003 volume manipulation / false volume signal).

Using spread-normalised deviation (bps of spread, not bps of price) is the correct normalisation. A 10 bps absolute deviation is immaterial in a 200 bps spread market and highly significant in a 2 bps spread market. 🧠

One implementation point for the PM to route to Mateo: the spec's `prevailing_spread_bps` field (data requirements, §4) should be clarified as the time-weighted average spread over the execution window, not the instantaneous spread at fill time. Time-weighted is more defensible under regulatory scrutiny.

### 1.3 No-Change-in-Beneficial-Ownership Indicator (MAR Art.12(2)(c))

The spec cites EU MAR Art.12(2)(c) as the no-change-in-beneficial-ownership indicator. The conceptual grounding is confirmed: absence of change in beneficial ownership is the definitional hallmark of wash trading and is recognised across all in-scope regimes. 📊

However, the specific sub-article citation MAR Art.12(2)(c) is marked `TO-VERIFY (🧠)` in the spec and is not present in `config/regulatory-register.yaml`. 📊 The no-change indicator in the MAR framework is referenced in both Art.12 and its associated Annex I (which sets out non-exhaustive lists of indicators of manipulation); the exact sub-article numbering of "(2)(c)" requires verification by a human reader against the primary source (EUR-Lex: Regulation (EU) No 596/2014) before this citation is used in alert records, regulatory reports or STORs. Until then the indicator mapping carries `obligation_status = PROVISIONAL` and must not be upgraded.

Jurisdiction equivalents cited in the spec are all `TO-VERIFY (🧠)` and absent from the register:

| Regime | Pinpoint in Spec | SME note | Tag |
|---|---|---|---|
| UK MAR | Art.12(1)(a) | Post-Brexit retained law; substantively equivalent. Verify UK MAR text against FCA Policy Statement and FCA Handbook MAR. | 🧠 |
| US SEC | Rule 10b-5 | General anti-fraud provision. Exchange Act s.9(a)(1) is the more precise wash-sale prohibition for securities; 10b-5 is broader. Verify applicable provision with Legal per asset class. | 🧠 |
| US FINRA | Rule 6140 | Specifically addresses wash sales. Verify pinpoint and confirm applicability to each relevant market. | 🧠 |
| US CFTC | CEA s.4c(a) | Explicitly prohibits wash sales and prearranged trades in commodities and futures. Applies only to CFTC-jurisdiction instruments. Verify pinpoint. | 🧠 |
| SG | SFA s.197 | False trading provision. Conceptually equivalent but the statutory framing differs from EU MAR; no connected-party element required. Verify pinpoint against MAS SFA text. | 🧠 |
| HK | SFO s.274 | False trading provision. Under HK law any person creating a false appearance of active trading may be liable; no beneficial-ownership link is a prerequisite. Verify pinpoint against SFO text. | 🧠 |
| JP | FIEA Art.159 | Market manipulation provision covering wash trading. Verify pinpoint against FIEA text with local Legal. | 🧠 |

Note on US asset-class split: the applicable US regime (SEC/FINRA for securities vs. CFTC/CEA for commodities, futures and swaps) depends on the instrument's regulatory classification. Q1 must resolve this per desk and per instrument type before the US obligation mapping can be finalised.

**Investigator evidence requirements.** To evidence intent in a wash-trade case the investigator needs: (a) the UBO graph printout showing the ownership chain linking both accounts at the time of the trade; (b) the spread-normalised price deviation calculation showing the mid, the spread, and the configured threshold at execution time; (c) order-level timestamps for both legs showing near-simultaneous or sequenced submission; (d) the absence of a legitimate economic rationale (no MM designation, no hedging strategy tag); and (e) pattern evidence where available (repeated instances strengthen intent inference; a single isolated pair is harder to sustain without communications intelligence). Communications records, if accessible via TS-002 in a later phase, significantly strengthen a case built on trading patterns alone.

---

## 2. Disposition of Open Questions

### Q1 - Regime / Venue / Safe-Harbour Scope

**Status: 🔴 open-decision-required (go-live blocker)**

**Recommendation.** A Legal/Compliance-led desk-by-desk and venue-by-venue regime-mapping exercise is required. The SME cannot make this determination without the firm's actual authorisation footprint. The exercise should produce a signed mapping table assigning each desk to its primary regime(s) using the following logic:

- Regime applicability by authorisation and venue: EU-authorised entity trading on EU venues falls under EU MAR; UK-authorised entity on UK venues falls under UK MAR; FINRA-member entity on US equity venues falls under FINRA 6140; futures desk falls under CFTC/CEA; dual-jurisdiction desks carry both.
- US asset-class split: per instrument type, not per desk, because the same desk may trade both securities and futures.
- Safe-harbours per regime: EU/UK: market-maker exemption requires an accepted-market-practices determination under MAR Art.13 and a notification to the relevant NCA under MiFID II/RTS 3. This must be operationalised in the DR-003 exemption register before go-live. US: bona-fide hedging (CFTC) and riskless-principal exemption (FINRA). SG/HK/JP: equivalent safe-harbour provisions apply; verify with local Legal.

Until the signed mapping table exists, all alerts carry `obligation_status = PROVISIONAL`. This status must not be removed by the implementation team without sign-off on this question.

### Q2 - Safe-Harbour Exemption Operationalisation

**Status: ⏭️ needs deployment/Legal input (pre-implementation, not an obligation-mapping blocker)**

**Recommendation.** DR-003 requires a maintained exemption register as input. The SME recommends the following operationalisation approach, subject to deployment confirming which feeds are available:

- Market-maker designations: source from the exchange or venue's official MM designation list (updated at least monthly) and from the firm's MiFID II/RTS 3 notifications to the NCA. Reference Data/Compliance must own this feed and maintain a dated version log.
- Riskless principal and agency trades: flag at order level via the OMS `strategy_tag` field rather than relying on a static register for this class; the static register is appropriate only for designated status, not for per-order capacity classification.
- Buyback programmes: if the firm acts as a buyback agent, the relevant share class and date range must be in the register; source from the issuer's public buyback disclosure.
- Review cycle: the register must be reviewed at minimum quarterly and on any regulatory change. A lapsed MM designation that remains in the register creates a false-negative risk.

The deployment team must confirm which operational systems can supply these feeds, at what latency, and whether the register will be managed manually or via a reference-data API. This is a data-availability question the SME cannot resolve without infrastructure knowledge.

### Q3 - Intra-Group / Treasury Treatment

**Status: 🔴 open-decision-required (go-live blocker, firm-policy call requiring Legal/Compliance sign-off)**

**Recommendation.** The SME's view is as follows:

- OTC intragroup transactions not executed on a public venue cannot generate a false price or volume signal in the public market and should generally be excluded from alert scope. However, if they are reported to a trade repository under a post-trade transparency regime (e.g., MiFID II APA/ARM reporting) and therefore become de facto public, this exclusion must be re-examined with Legal before applying it.
- On-venue intragroup transactions, regardless of internal treasury intent, appear in the public order book and can distort public price and volume signals. These must remain in scope. Treasury rationale does not extinguish the market impact.
- Recommended treatment: route on-venue intragroup matches to a separate lower-priority review queue tagged `INTRAGROUP_REVIEW`, rather than suppressing them entirely. This preserves the audit trail and avoids a blanket suppression that regulators would challenge. Off-venue transactions should be excluded via a venue-type filter applied upstream of DR-001.
- What Legal must determine: whether any of the firm's OTC intragroup transactions are captured by trade-reporting rules that make them effectively public; and whether the group structure creates acting-in-concert exposure that prevents blanket OTC exclusion.
- Until Legal delivers a signed decision, all intragroup trades remain in scope and alert as normal. No exclusion filter is to be implemented without that sign-off.

### Q4 - Connected-Party Definition Width

**Status: 🔴 open-decision-required (go-live blocker)**

**Recommendation.** The SME recommends a phased approach:

- Phase 1 (launch): UBO-only definition. Connect accounts where the same natural or legal person holds above the threshold ownership or control interest in both accounts' legal entities. Use a threshold consistent with the firm's AML/beneficial-ownership framework (typically greater than 25% direct or indirect ownership or equivalent control), verified by Legal against the definition applicable under each in-scope regime. This is the most operationalizable definition and aligns with the UBO graph assumed to exist in SCN-001 §4. Alert volume will be material but scoped.
- Phase 2 (post-calibration): extend to acting-in-concert groups identified via network analysis or communications intelligence. This requires TS-002 and is explicitly out of scope for TS-001.
- What Legal must confirm: the minimum ownership/control threshold to adopt; whether fund-of-funds or manager-level relationships are to be treated as connected (the highest-alert-volume decision; see §3); and whether acting-in-concert can be inferred from trading patterns alone or requires communications evidence before a legal threshold is crossed.
- Schema note for the PM to route to Mateo: the `UBO_group_id` and graph schema must be designed to the Phase 1 definition. If Phase 2 is anticipated, the schema should carry a relationship-type annotation field so that UBO relationships and acting-in-concert relationships can be distinguished at alert time.

### Q5 - Implied-Match Tier Enablement

**Status: ✅ answered**

**Recommendation: do not enable the implied-match tier (DR-006) at launch.**

An implied match (opposing orders from connected parties with no confirmed fill on one leg) is evidentially weak. The absence of a confirmed fill means the match is inferred from order proximity; this inference is routinely contested in regulatory proceedings and is difficult to evidence as intentional without corroborating communications. Enabling this tier before the confirmed-match baseline is established risks flooding the queue with low-quality alerts that consume investigator capacity and erode alert credibility.

Conditions for Phase 2 enablement: (a) confirmed-match alert rate is calibrated and stable; (b) a separate review queue, SLA and escalation path for lower-confidence alerts are defined operationally; (c) the tuning-analyst (Theo) has determined the tighter lookback window for each asset class based on observed order-to-fill latency distributions. For liquid equities this lookback may be seconds to low minutes; for OTC bonds it may extend to hours. Theo must determine this per asset class at the time of enablement, not in advance.

DR-006 as specified (distinct `confidence_tier` label) is the correct design for when this tier is eventually activated.

---

## 3. False-Positive Drivers and Exemptions

| FP source | Volume impact | Mitigation | Current status |
|---|---|---|---|
| Affiliated funds under one manager (same management-company UBO, independent investment mandates) | Highest - can dominate and operationally disable alert throughput | Q4 decision: if UBO drawn at manager level, every cross between sibling funds flags. Resolution requires fund-level boundary or mandate-independence flag in the UBO graph. | 🔴 Q4 unresolved |
| Designated market-maker activity | High | DR-003 exemption register; requires current MM designation feed (Q2). | ⏭️ Q2 |
| Riskless principal / agency crosses | Medium | DR-003 register plus OMS `strategy_tag` filter. | ⏭️ Q2 |
| Coincident independent orders at a liquid price | Medium | Largely mitigated by DR-002: at-market coincident fills do not alert. Residual risk near the threshold boundary is a tuning-analyst calibration task. | Mitigated |
| ETF creation/redemption and index rebalancing | Medium | At-market condition (DR-002) excludes the majority; residual captured by `strategy_tag`. | Partially mitigated |
| Intragroup treasury transactions (on-venue) | Medium | Q3 decision: separate lower-priority queue recommended. | 🔴 Q3 unresolved |
| Stale UBO graph producing false connections or missed connections | Variable | DR-005 data-quality gate with freshness limit. | Specified |

**Single biggest pitfall.** Affiliated funds managed by the same investment manager where the UBO graph is constructed at the management-company level rather than the fund level. In a large fund house this configuration can generate false-positive alert volumes that make TS-001 operationally unusable and creates a regulatory-credibility problem if alerts are dismissed in bulk without individual justification. This is not a calibration problem and cannot be solved by threshold adjustment; it is a structural question about the connected-party definition that must be resolved in Q4 before go-live. If the answer is "draw the UBO boundary at fund level," the ownership-graph schema must support fund-level entity nodes and not only management-company-level nodes.

---

## 4. Evidence Basis

| Claim | Tag | Basis |
|---|---|---|
| UBO/connected-party grouping as entry point | 📊 | Grounded in MAR Art.12(1)(a) (register: verified) and the no-change-in-beneficial-ownership concept per SCN-001 §3 |
| Off-market price as necessary condition (DR-002) | 📊 | Specified in SCN-001 DR-002; confirmed correct by this SME review |
| MAR Art.12(1)(a) obligation citation | 📊 | `config/regulatory-register.yaml`, status: verified, verified_on: 2026-06-29 |
| MAR Art.12(2)(c) no-change indicator sub-article | 🧠 | Not in register; TO-VERIFY in spec; conceptually correct but sub-article pinpoint unconfirmed against primary source EUR-Lex |
| All non-EU-MAR jurisdiction equivalents (UK, US, SG, HK, JP) | 🧠 | Not in register; standard industry knowledge; must be verified by a human reader against each primary source before use in live alerts or STORs |
| At-market wash trading as a known detection gap in TS-001 | 🧠 | Inferred from DR-002 design; the gap is real, material, and must be documented |
| Affiliated-fund FP as highest-volume source | 🧠 | Industry practice observation from surveillance programme design; no direct citation in the spec |
| Phase 1 UBO-only / Phase 2 acting-in-concert approach for Q4 | 🧠 | Industry practice for phased connected-party rollout; not in the spec |
| Implied-match evidential weakness | 🧠 | Observed pattern from investigations and regulatory proceedings; no direct citation in the spec |
| On-venue vs. OTC intragroup scope distinction for Q3 | 🧠 | Reasoned from MAR Art.12(1)(a) market-impact logic; Legal must confirm applicability to the firm's specific reporting obligations |
| US SEC/FINRA vs. CFTC/CEA asset-class split | 🧠 | Standard US regulatory framework; not addressed in the spec; flagged for Legal confirmation at Q1 |
| Time-weighted spread preferred over instantaneous spread | 🧠 | Industry surveillance practice; not specified in SCN-001 |

---

## 5. Disposition Tally

| # | Question | Status | Go-live blocker |
|---|---|---|---|
| Q1 | Regime / venue / safe-harbour scope | 🔴 open-decision-required | Yes |
| Q2 | Safe-harbour exemption operationalisation | ⏭️ needs deployment/Legal input | No (pre-implementation) |
| Q3 | Intra-group / treasury treatment | 🔴 open-decision-required | Yes |
| Q4 | Connected-party definition width | 🔴 open-decision-required | Yes |
| Q5 | Implied-match tier enablement | ✅ answered | No |

**Disposition tally:** ✅ 1 Answered · 🔴 3 Open · ⏭️ 1 Needs-input · ⚖️ 0 Accepted.

**Obligation mapping status: NOT SAFE TO FINALISE.** `obligation_status = PROVISIONAL` must remain on all alerts pending: (a) resolution of Q1, Q3 and Q4 with signed Legal/Compliance decisions; and (b) human verification of MAR Art.12(2)(c) and all non-EU-MAR jurisdiction equivalents against their primary sources, followed by addition to `config/regulatory-register.yaml` with `status: verified`. No implementation team action may remove the PROVISIONAL status flag without these prerequisites being met and recorded.

---

## 6. Recommendations for Project Memory

The following insights are project-specific and should be added to this project's `CLAUDE.md` by the PM once agreed, so they travel with the project rather than being lost between sessions:

- TS-001 has a documented detection gap: at-market wash trading to inflate volume or open interest does not alert under DR-002. This is an accepted design choice, not an oversight. Candidate future scenario: TS-003 (volume manipulation / false volume signal).
- The single largest structural false-positive risk is affiliated funds under a common investment manager where the UBO graph is drawn at management-company level. Q4 must resolve the fund/manager boundary before go-live; no threshold tuning can substitute for this structural decision.
- Spread-normalised bps deviation is the correct metric for the off-market test across asset classes. Absolute bps is not appropriate.
- Time-weighted average spread over the execution window is the preferred denominator for the deviation test; instantaneous spread is not.
- Implied-match tier (DR-006) is not to be enabled at Phase 1.
- MAR Art.12(2)(c) and all non-EU jurisdiction equivalents are absent from the regulatory register as-of 2026-06-30; they must be verified and added before the obligation mapping is upgraded from PROVISIONAL.

---

## Sign-off

| Role | Name | Decision | Date |
|---|---|---|---|
| SME validation author | Camila (trade-surveillance-sme) | Validation complete. Typology and DR-002 design confirmed correct. Obligation mapping must remain PROVISIONAL pending Q1/Q3/Q4 resolution and register verification of all TO-VERIFY citations. | 2026-06-30 |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver | | | |

---

**Relevant source files read during this validation:**
- `docs/demos/build-artifacts/ts001-scenario-spec.md`
- `config/regulatory-register.yaml`
- `docs/scope-and-stack.md`
