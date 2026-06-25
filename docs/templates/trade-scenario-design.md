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
The specific obligation (cite the MAR article / MiFID rule, CLAUDE.md §2). E.g. market
manipulation under **MAR Article 12**; suspicious orders reportable via **STOR (MAR Article 16)**.

## 3. Data substrate required
The behaviour is only detectable if the data supports it — name the feeds and why.
- **Order lifecycle** (new / amend / cancel / fill) — **MiFID II RTS 24** order record-keeping is
  the substrate for spoofing/layering sequencing.
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
How a confirmed alert feeds a **Suspicious Transaction and Order Report (STOR, MAR Art 16)**:
escalation path, evidence pack, decision record. Map the scenario to the control(s) it satisfies
in the surveillance control framework (RTM reference).

## 8. Out of scope / assumptions / open questions
List explicitly; flag SME input needed.

## 9. Hand-off
SME review: `trade-surveillance-sme`. Implementer: `rules-developer`. Tuning: `tuning-analyst`.
Coverage feeds into the Surveillance Coverage Assessment.
