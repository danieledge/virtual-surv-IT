# Trade Surveillance Scenario Design - <SCENARIO NAME>

> Produced by `business-analyst` with `trade-surveillance-sme`, before development. Translates a
> market-abuse behaviour into an implementable, testable design for `rules-developer` (logic) and
> `tuning-analyst` (parameters). Examples use **synthetic/masked data only** (§5). Authored in
> `.md`, rendered to `.html`. This is the design, not the production rule.

> **Document control** · ID `TSD-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Internal | Confidential` · Owner `<name / role>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

| | |
|---|---|
| **Scenario** | <name> |
| **Abuse type** | <spoofing / layering / marking-the-close / ramping / front-running / insider dealing / momentum ignition> |
| **Jurisdiction(s)** | <applicable regime(s)> |
| **Date / author** | <YYYY-MM-DD> |

## 1. Behaviour
The market-abuse conduct in plain terms - the manipulative pattern, the intent it proxies, and
the market harm it causes.

## 2. Regulatory obligation
The specific obligation (cite the MAR article / MiFID rule, CLAUDE.md §2):
- **Behaviour definition** - market manipulation **MAR Article 12** / insider dealing **MAR
  Article 8** (incl. *attempted* abuse).
- **Detect-and-report obligation** - **MAR Article 16(2)** on persons professionally arranging or
  executing transactions (PPAETs): maintain arrangements to **detect and report** suspicious
  orders & transactions and **notify the competent authority without delay**. *(The statute says
  "notify"; the term "STOR" comes from the implementing RTS - see §7.)* Art 16(1) is the parallel
  duty on trading-venue operators. *[Verified: MAR Reg 596/2014, EUR-Lex/legislation.gov.uk.]*

## 3. Data substrate required
The behaviour is only detectable if the data supports it - name the feeds and why.
- **Order lifecycle** - **RTS 24 (CDR (EU) 2017/580**, under MiFIR Art 25) order-book record-
  keeping is the substrate for spoofing/layering sequencing. Its Field 21 codifies the lifecycle
  events you sequence on - **NEWO** (new), **CHME/CHMO** (amend), **CAME/CAMO** (cancel), **REMO**
  (reject), **PARF/FILL** (part/full fill), etc. *(RTS 24 ≠ transaction reporting: RTS 22 (CDR
  2017/590, MiFIR Art 26) is the separate post-execution report to the NCA, T+1.)* *[Verified.]*
- **Accurate, granular timestamps** - **MiFID II RTS 25** clock-sync / timestamp granularity
  (microsecond for HFT / <1ms latency) is the time-spine that makes event ordering auditable.
- Reference/market data, venue, account/trader linkage, benchmark/fixing windows as needed.

## 3a. Time-spine validation check
Before finalising the design, confirm the data substrate meets the granularity the logic requires.
A scenario designed around sub-second sequencing is undetectable if the feed delivers only
second-level timestamps.

| Requirement | Feed granularity available | RTS 25 compliant? | Gap / action |
|---|---|---|---|
| <e.g. order-event sequencing requires microsecond> | <e.g. millisecond (gateway)> | <Partial - gateway clock; HFT venues require microsecond> | <confirm with `data-quality-reviewer`> |
| <e.g. cancel-to-fill ratio window = 100ms> | <...> | <...> | <...> |

If the feed cannot meet the design's time-spine requirement, escalate to `data-quality-reviewer`
and `platform-engineer` before development begins. A correctly coded rule on a coarse timestamp
feed will produce false alerts or miss the pattern entirely.

## 4. Detection logic outline (for `rules-developer`)
The signals and the conceptual logic - sequence, time windows, ratios, price/volume context.
Keep it implementable and explainable (alert → logic → obligation).

**Peer-group / benchmark comparator:** for each signal metric, define how the entity's behaviour
is compared to a peer group or market benchmark (not just an absolute threshold). State the peer
group definition (e.g. same desk / same instrument class / same liquidity band over the same
window) and the comparator method (e.g. z-score relative to peer median, percentile rank within
cohort). Absolute thresholds alone miss relative manipulation; peer-relative signals are more
robust and more defensible.

| Signal metric | Absolute threshold | Peer group definition | Comparator method | Alert condition |
|---|---|---|---|---|
| <e.g. cancel ratio> | <e.g. > 80%> | <e.g. same instrument, same session> | <e.g. z-score > 3 vs peer median> | <absolute OR peer-relative, whichever fires first> |

## 5. Parameters (for `tuning-analyst`)
Every tunable, with a rationale placeholder - no undocumented thresholds (§4).

| Parameter | Purpose | Initial value | Rationale / tuning note |
|---|---|---|---|

## 6. Worked examples
- **True positive(s)** - synthetic case(s) that MUST alert, with the manipulative pattern shown.
- **False positive control(s)** - legitimate activity (genuine liquidity provision, normal
  cancellations) that MUST NOT alert.

## 7. STOR linkage & control mapping
How a confirmed alert feeds a **Suspicious Transaction and Order Report (STOR)** - the report
prescribed by the RTS supplementing MAR Art 16, **CDR (EU) 2016/957**:
- **Trigger** - **"reasonable suspicion"** of *actual or attempted* abuse - a **lower bar than
  certainty**; file even on incomplete information; covers **non-executed, cancelled and modified
  orders** (i.e. the spoofing/layering pattern). File **without delay** (Art 6).
- **Content** - the **Annex template** (Art 7): submitter + capacity · order/transaction
  description · **reasons for the suspicion** · persons involved · supporting documents.
- **Retention** - keep the analysis and the **reasons for submitting *or not* submitting** for
  **5 years** (Art 3(8)). Avoid low-substance defensive STORs (regulators expect *quality over
  quantity*). *[Verified: CDR (EU) 2016/957, EUR-Lex/legislation.gov.uk; MFSA/FCA SUP 15.10.]*

**Reasonable-suspicion calibration note** - "reasonable suspicion" is a qualitative threshold,
not a score. Define the signal level that should prompt a referral for human review and onward
STOR consideration:
- At what combination of signals (e.g. cancel ratio AND peer-relative z-score AND proximity to
  fixing window) does an alert cross from "review and close" to "escalate for STOR assessment"?
- Record this calibration in the parameters table (§5) so `tuning-analyst` can ATL/BTL test it.
- The referral decision and the reasons for filing or not filing must be documented per Art 3(8).

Map the scenario to the control(s) it satisfies in the surveillance control framework (RTM ref).

## 8. Out of scope / assumptions / open questions
List explicitly; flag SME input needed.

## 9. Hand-off
SME review: `trade-surveillance-sme`. Implementer: `rules-developer`. Tuning: `tuning-analyst`.
Coverage feeds into the Surveillance Coverage Assessment.

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
