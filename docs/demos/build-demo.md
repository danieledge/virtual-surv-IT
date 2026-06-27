# 🏗️ Build demo

*A real `/demo` transcript: Morgan builds a new detection from scratch, chaining specialists
(orchestrator-workers). [Back to demos](README.md).*

> 📂 **The actual documents produced are downloadable** in
> [**`build-artifacts/`**](build-artifacts/): the full [scenario spec](build-artifacts/wash-trade-scenario-spec.md),
> the [SME validation](build-artifacts/wash-trade-sme-validation.md), and Mateo's
> [`wash_trade.py`](build-artifacts/wash_trade.py) + [`test_wash_trade.py`](build-artifacts/test_wash_trade.py).
> Not summaries - the real deliverables.

---

> 🎩 **Build demo - the orchestrator-workers pattern.** A build *chains* specialists, each one's
> output feeding the next (the blackboard).
>
> **The intake (I answer):** A build from scratch. **Execution? No** - I'll produce a spec and a rule
> *sketch* + test statically. **Data? Synthetic only.** Output goes to a **demo artifact**, not your
> live `rules/`.
>
> **Right-sizing, out loud - and notice it's *different* from the review:** a 1-file review was 1
> agent. A *build* genuinely needs a chain - so I'll use **three**: **Amara** (spec) → **Camila** (SME
> validation) → **Mateo** (build). Still not all 16. The idea: a small **wash-trade / self-match**
> detector (a trader on both sides of the same instrument in a short window - classic market abuse).

### → Step 1: Amara (`business-analyst`, sonnet) writes the spec

> Why her, why sonnet: turning an obligation into a precise, testable spec is structured BA work that
> gets re-checked downstream - it doesn't need opus.

Amara produced a concise scenario spec (`SS-TS-001`) -
[**read the full document**](build-artifacts/wash-trade-scenario-spec.md). Highlights:
- **Behaviour:** a party buys and sells the same instrument in offsetting trades attributable to the
  same beneficial owner, with no genuine change in economic exposure.
- **Obligation:** **EU MAR Article 12(1)(a)** (false/misleading signals as to supply/demand/price);
  jurisdiction equivalents noted (UK MAR, SEC Exchange Act s.9(a)(1), SFA s.197, SFO s.274). *Flagged
  for SME to confirm in-scope jurisdictions + safe-harbour carve-outs.*
- **Data required:** trade/order ID, instrument, direction, price, qty, timestamp, account ID,
  **beneficial-owner (UBO) ID**, venue, counterparty. (UBO linkage marked the critical field.)
- **Detection outline:** link accounts → find opposite-direction pairs in the same instrument within
  a lookback window → offset test → exemption filter → score → alert.
- **Parameters:** lookback, price/qty tolerance, repetition threshold - **all flagged as SME/tuning
  decisions; no values invented** (CLAUDE.md §4).
- One synthetic **true-positive** + one **false-positive** example, and **Gherkin acceptance
  criteria** (incl. the obligation-trace AC), plus 5 open questions for the SME.

> 🎩 **Amara delivered a real spec** - and did exactly right: cited the article, **flagged every
> threshold as an SME/tuning decision instead of inventing numbers**, and surfaced the open questions.
> The **blackboard handoff:** her spec is now the *input* to the next agent.

### → Step 2: Camila (`trade-surveillance-sme`, sonnet, READ-ONLY) validates the typology

> Why her: the market-abuse expert who validates the *typology*. Read-only by design - she advises,
> can't edit.

Camila's advisory ([**full document**](build-artifacts/wash-trade-sme-validation.md); condensed here):
- **Typology sound?** Yes - beneficial-owner linkage is the right entry point, opposite-direction
  pairs in a window is the standard signature, MAR Art 12(1)(a) is correct and jurisdiction-portable.
- **Top false-positive drivers:** (1) **legitimate two-way business between affiliated funds** under
  one manager - the highest-volume FP source; (2) **market-making / riskless-principal** activity;
  (3) **coincident independent orders** at a liquid price level.
- **Single biggest pitfall:** **beneficial-owner graph completeness & freshness** - stale linkage
  causes both false negatives *and* false positives; it's the most common reason a wash-trade
  scenario fails audit. Require a refresh cadence + a data-quality gate.
- **Sharp correction:** *"price must be **off-market** as a **necessary** condition, not just
  convergence with a tolerance."*
- **One thing the spec got right:** deferring all thresholds to SME/tuning with placeholders.

> 🎩 **That's why the SME isn't optional.** Camila - pure advice - caught the thing that sinks real
> wash-trade scenarios *before a line of code was written.* She can recommend house-rules entries;
> committing them is mine.

### → Step 3: Mateo (`rules-developer`, sonnet) builds the sketch + tests

> Why him, why sonnet: he implements the validated spec into deterministic, tested logic; it's then
> independently reviewed, so it doesn't need opus. He inherits Amara's spec **and** Camila's caveats.

Mateo produced a real `detect_wash_trades()` sketch + tests
([**`wash_trade.py`**](build-artifacts/wash_trade.py) ·
[**`test_wash_trade.py`**](build-artifacts/test_wash_trade.py)) honouring every caveat - core (abridged):

```python
def detect_wash_trades(trades, params, ubo_link, exemptions) -> list[WashTradeAlert]:
    """Flag a pair only when ALL three conditions hold:
       1. Both accounts share a confirmed, NON-STALE UBO link (data-quality gate).
       2. At least one leg is priced OFF-MARKET (necessary condition).
       3. Neither account is in the active exemption set."""
    # Fail loudly if a threshold is missing - no silent defaults (coding-standards §4).
    required = {"price_tolerance_pct","ubo_staleness_days","min_notional","lookback_seconds","market_mid"}
    if required - params.keys():
        raise KeyError(f"Missing required params: {required - params.keys()}")
    ...
    for buy in buys:
        if buy["account_id"] in exemptions: continue          # condition 3
        for sell in candidate_sells(buy):
            link = ubo_link(buy["account_id"], sell["account_id"])
            if not link or not link["linked"]: continue        # condition 1: UBO gate
            if link["as_of"] < staleness_cutoff: continue       # 1: skip STALE UBO data
            deviation = abs(sell["price"] - mid) / mid * 100
            if deviation <= params["price_tolerance_pct"]: continue   # condition 2: necessary
            alerts.append(WashTradeAlert(...))                  # off-market + UBO-linked + not exempt
    return alerts
```

…plus a pytest with **one true-positive** (UBO-linked, 6%-off-market → alerts) and **one
false-positive guard** (same pair but competitive 0.5% price → must NOT alert), proving price is a
*necessary* condition. All thresholds are `PLACEHOLDER` values left for `tuning-analyst`.

> 🎩 **Mateo nailed it.** He implemented Camila's "off-market price as a *necessary* condition" as an
> **early-continue, not a weighted score** (exactly as she demanded), gated on a fresh UBO link, and
> made missing thresholds **fail loud** (`KeyError`) so nobody can ship undocumented numbers.
>
> **What happens next:** Mateo's code → **Ravi** (`code-reviewer`) for quality/security, **Layla**
> (`compliance-reviewer`) to verify the obligation trace + gate the Definition of Done, and **Theo**
> (`tuning-analyst`) to calibrate those placeholders with ATL/BTL. Nothing ships until that signs off.

> 🎩 **And the review stage immediately earned its keep.** When I actually *ran* Mateo's test, the
> true-positive **failed** - the original sketch checked UBO staleness against the wall clock
> (`datetime.utcnow()`) while the fixtures used a fixed date, so once "today" drifted past the window
> the real alert was silently dropped. **A non-deterministic time bug** - exactly what review/QA exists
> to catch. The fix (inject the reference date, make it deterministic) is in the committed artifact,
> and the test now passes. The chain is **not a rubber stamp**: code doesn't ship until it's run *and*
> reviewed. (Details in [`build-artifacts/`](build-artifacts/).)

---

## What this demo showed
- **Orchestrator-workers** end-to-end: Amara → Camila → Mateo → reviewers, three agents not sixteen.
- **The blackboard** - each output is the next step's input; no agent-to-agent chatter.
- **The SME caught a real flaw** (the UBO graph; off-market-as-necessary) *before* code existed.
- **No invented thresholds** - flagged in the spec, `KeyError`-enforced in the code, left for tuning.
- **Built to be reviewed** - the chain doesn't end at "code written"; it ends at signed-off.
