# Trade Surveillance Scenario Design — <SCENARIO NAME>

> Produced by `business-analyst` with `trade-surveillance-sme`, before development. Translates a
> market-abuse behaviour into an implementable, testable design for `rules-developer` (logic) and
> `tuning-analyst` (parameters). Examples use **synthetic/masked data only** (§5). Authored in
> `.md`, rendered to `.html`. This is the design, not the production rule.

| | |
|---|---|
| **Scenario** | <name> |
| **Abuse type** | <spoofing / layering / marking-the-close / ramping / front-running / insider dealing / momentum ignition> |
| **Jurisdiction(s)** | <applicable regime(s)> |
| **Date / author** | <YYYY-MM-DD> |

## 1. Behaviour
The market-abuse conduct in plain terms — the manipulative pattern, the intent it proxies, and
the market harm it causes.

## 2. Regulatory obligation
The specific obligation (cite the MAR article / MiFID rule, CLAUDE.md §2):
- **Behaviour definition** — market manipulation **MAR Article 12** / insider dealing **MAR
  Article 8** (incl. *attempted* abuse).
- **Detect-and-report obligation** — **MAR Article 16(2)** on persons professionally arranging or
  executing transactions (PPAETs): maintain arrangements to **detect and report** suspicious
  orders & transactions and **notify the competent authority without delay**. *(The statute says
  "notify"; the term "STOR" comes from the implementing RTS — see §7.)* Art 16(1) is the parallel
  duty on trading-venue operators. *[Verified: MAR Reg 596/2014, EUR-Lex/legislation.gov.uk.]*

## 3. Data substrate required
The behaviour is only detectable if the data supports it — name the feeds and why.
- **Order lifecycle** — **RTS 24 (CDR (EU) 2017/580**, under MiFIR Art 25) order-book record-
  keeping is the substrate for spoofing/layering sequencing. Its Field 21 codifies the lifecycle
  events you sequence on — **NEWO** (new), **CHME/CHMO** (amend), **CAME/CAMO** (cancel), **REMO**
  (reject), **PARF/FILL** (part/full fill), etc. *(RTS 24 ≠ transaction reporting: RTS 22 (CDR
  2017/590, MiFIR Art 26) is the separate post-execution report to the NCA, T+1.)* *[Verified.]*
- **Accurate, granular timestamps** — **MiFID II RTS 25** clock-sync / timestamp granularity
  (microsecond for HFT / <1ms latency) is the time-spine that makes event ordering auditable.
- Reference/market data, venue, account/trader linkage, benchmark/fixing windows as needed.

## 4. Detection logic outline (for `rules-developer`)
The signals and the conceptual logic — sequence, time windows, ratios, price/volume context.
Keep it implementable and explainable (alert → logic → obligation).

## 5. Parameters (for `tuning-analyst`)
Every tunable, with a rationale placeholder — no undocumented thresholds (§4).

| Parameter | Purpose | Initial value | Rationale / tuning note |
|---|---|---|---|

## 6. Worked examples
- **True positive(s)** — synthetic case(s) that MUST alert, with the manipulative pattern shown.
- **False positive control(s)** — legitimate activity (genuine liquidity provision, normal
  cancellations) that MUST NOT alert.

## 7. STOR linkage & control mapping
How a confirmed alert feeds a **Suspicious Transaction and Order Report (STOR)** — the report
prescribed by the RTS supplementing MAR Art 16, **CDR (EU) 2016/957**:
- **Trigger** — **"reasonable suspicion"** of *actual or attempted* abuse — a **lower bar than
  certainty**; file even on incomplete information; covers **non-executed, cancelled and modified
  orders** (i.e. the spoofing/layering pattern). File **without delay** (Art 6).
- **Content** — the **Annex template** (Art 7): submitter + capacity · order/transaction
  description · **reasons for the suspicion** · persons involved · supporting documents.
- **Retention** — keep the analysis and the **reasons for submitting *or not* submitting** for
  **5 years** (Art 3(8)). Avoid low-substance defensive STORs (regulators expect *quality over
  quantity*). *[Verified: CDR (EU) 2016/957, EUR-Lex/legislation.gov.uk; MFSA/FCA SUP 15.10.]*

Map the scenario to the control(s) it satisfies in the surveillance control framework (RTM ref).

## 8. Out of scope / assumptions / open questions
List explicitly; flag SME input needed.

## 9. Hand-off
SME review: `trade-surveillance-sme`. Implementer: `rules-developer`. Tuning: `tuning-analyst`.
Coverage feeds into the Surveillance Coverage Assessment.
