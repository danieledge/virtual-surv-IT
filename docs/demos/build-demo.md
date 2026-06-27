# 🏗️ Build demo

*A real `/demo` transcript: Morgan builds a new detection from scratch and takes it through the full
Definition-of-Done chain - 8 specialists, the blackboard, the fix→re-review loop. [Back to demos](README.md).*

> 📖 **Reading key:** blockquotes that begin with **🎩** are **Morgan, the AI PM, speaking live in
> the session** (his words, generated at the moment - not the repo author's). Plain text is editorial
> framing; ` ``` ` blocks are real commands/output and verbatim agent findings.
> [Full key](README.md#how-to-read-a-transcript-whos-speaking).

> 📂 **The actual deliverables are downloadable** - every artifact below is committed in
> [`build-artifacts/`](build-artifacts/). And this run is compared head-to-head with an earlier run in
> the [🔁 run comparison](build-run-comparison.md) - which shows the team *getting better each time*.

---

> 🎩 **Build demo - let's make something.** I'll spec, build and fully review a new **wash-trade /
> self-match** detection (TS-001), on synthetic data. The intake gates first - I answer them, on a
> real job *you* would:
> - ⚠️ **Execution?** → **Yes**, but only this trusted demo repo on synthetic data (so I can *run*
>   the tests - that's how review earns its keep).
> - 🛡️ **Data?** → **Synthetic, no real data.**
>
> **Right-sizing, out loud:** this is the *heavy* demo - a full DoD delivery is **8 agents** (build +
> 3 reviews + tuning + performance), ~170k tokens. A lighter ask would be far less.

### → Step 1: Amara (`business-analyst`, sonnet) writes the spec

> 🎩 Why her, why sonnet: turning a regulatory need into a testable spec is structured BA work, not
> novel judgement. She cites the obligation and **flags every threshold as a tuning decision** rather
> than inventing numbers.

Amara produced [**`ts001-scenario-spec.md`**](build-artifacts/ts001-scenario-spec.md): behaviour,
**MAR Art 12(1)(a)**, the data fields, a detection outline, parameters-to-tune, Gherkin ACs, and **6
open questions** - with an explicit *"don't finalise the obligation mapping until Q1-Q3 are
dispositioned."*

### → Step 2: Camila (`trade-surveillance-sme`, sonnet) validates + dispositions

> 🎩 Camila advises only - she never touches code. She confirms the typology, names the
> false-positive drivers, and **formally closes the open questions** so nothing dangles.

She validated the typology (UBO linkage is the right entry point; **off-market price must be a
*necessary* condition**, not a score), named the FP drivers (affiliated-fund flow, market-making,
coincident liquid orders), and **dispositioned all 6 questions** ([validation](build-artifacts/ts001-sme-validation.md)):
Q5/Q6 answered (Q6 → a separate TS-002), Q2 needs deployment input, and **Q1 + Q3/Q4 are go-live
blockers** → the obligation mapping is **not** safe to finalise.

### → Step 3: Mateo (`rules-developer`, sonnet) builds it - and the team's memory pays off

> 🎩 Here's the bit I'm proud of. Mateo **read `house-rules.md` first** - the lessons the team
> recorded from earlier builds - and applied them *up front*.

Mateo produced [**`ts001_wash_trade.py`**](build-artifacts/ts001_wash_trade.py) + tests, applying:
UBO keystone + **staleness gate**, off-market as an **early-continue necessary condition**, obligation
**and** UBO id as **alert fields**, and an **injected `as_of_date`** (deterministic - no wall clock).

```console
$ cd docs/demos/build-artifacts && python3 -m pytest test_ts001_wash_trade.py -q
...                                                                      [100%]
3 passed
```

> 🎩 **Three for three, first run.** That matters more than it looks: in an earlier run of this same
> demo, the equivalent test **failed** the first time - the code had used the wall clock for UBO
> staleness, a non-deterministic bug. That lesson became a house-rule, and this time Mateo never made
> it. The team's memory is **measured, not decorative** - see the [run comparison](build-run-comparison.md).

### → Step 4: the independent reviews (Ravi + Linh + Layla, in parallel)

> 🎩 Now the adversarial pass - three independents, no chatter, findings onto the blackboard. With the
> old bugs already designed-out, did review still earn its keep? **Yes - it found newer, subtler things.**

- **Ravi (`code-reviewer`, opus):** the off-market test and the *reported* deviation came from two
  separate computations (drift risk); the alert didn't record *which* snapshot date it judged against
  (auditability); same-account self-match silently excluded (a scope call).
- **Linh (`qa-engineer`, sonnet):** wrote an independent QA suite and caught **DEF-001** - a missing
  market snapshot **silently dropped** pairs (an invisible surveillance gap); quantity never matched.
- **Layla (`compliance-reviewer`, opus):** the standout. The code hard-coded `obligation="MAR Art
  12(1)(a)"` as if **finalised** - while the SME had flagged the mapping as **blocked**. The alert
  *asserted a regulatory trace that didn't yet exist* - the most dangerous failure mode for a control.

> 🎩 **That's the chain working.** None of these are the old bugs - they're harder, and they only
> surfaced *because* the basics were already right. I routed them back: single-source the deviation,
> record the snapshot date, log the missing-snapshot gap, and carry an explicit
> **`obligation_status = PROVISIONAL`** so a blocked mapping can't masquerade as done. Re-tested - green.

```console
$ python3 -m pytest test_ts001_wash_trade.py test_ts001_qa.py -q
................                                                         [100%]
16 passed
```

### → Step 5: Theo (tuning) + Thabo (performance)

> 🎩 Two more, in parallel, before I sign anything off.

- **Theo (`tuning-analyst`):** thresholds stay un-invented; the [tuning pack](build-artifacts/threshold-tuning-pack.md)
  gives the **method** + illustrative values, and two new rules - **spread-normalise** the off-market
  threshold, and **`min_notional` is required** (an immaterial pair can't give a false signal).
- **Thabo (`performance-reviewer`):** [won't scale as-is](build-artifacts/performance-review.md) -
  O(buys×sells); fix is to pre-group by instrument+UBO. Deferred to productionisation (a demo has no volume).

### → The delivery

The consolidated [**delivery report**](build-artifacts/delivery-report.md) ties it together: RTM,
every finding dispositioned, the DoD gate, developer handover, and the token/runtime/cost capture
(**8 agents, ~171k tokens, ~9 min, ~$3-6**).

> 🎩 **And here's the honest verdict.** This is **demo-complete** - every stage ran. But it is **NOT
> deployable**, and I'll say exactly why: the obligation mapping is provisional (SME blockers), the
> thresholds need real-data calibration, the O(n²) needs fixing, and a **human still has to sign off**
> - which a demo cannot do. A report that hid those to look "all green" would be the failure. Saying
> them is the job.

---

## What this demo showed
- **Orchestrator-workers, end to end** - 8 specialists, each output feeding the next via the blackboard.
- **The team learns** - codified house-rules stopped this build reintroducing the prior run's defects
  (measured in the [run comparison](build-run-comparison.md)), and Run 2's review *added* new rules.
- **Review is not a rubber stamp** - it found new, subtler issues, including a compliance trap (an
  obligation literal masquerading as a finalised mapping).
- **No invented thresholds; measured, not guessed** - flagged in the spec, calibrated by method.
- **Honest gates** - demo-complete, but plainly **not deployable** until the mapping is finalised,
  calibration is done on real data, the O(n²) is fixed, and a human signs off.
