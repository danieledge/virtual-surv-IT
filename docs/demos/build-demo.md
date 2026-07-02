# 🏗️ Build demo

*A real `/demo` transcript: Morgan builds a new detection from scratch and takes it through the full
Definition-of-Done chain - 8 specialists, the blackboard, the fix→re-review loop. [Back to demos](README.md).*

> 📖 **Reading key:** blockquotes that begin with **🎩** are **Morgan, the AI PM, speaking live in
> the session** (his words, generated at the moment - not the repo author's). Plain text is editorial
> framing; ` ``` ` blocks are real commands/output and verbatim agent findings.
> [Full key](README.md#how-to-read-a-transcript-whos-speaking).

> 📂 **The actual deliverables are downloadable** - every artifact below is committed in
> [`build-artifacts/`](build-artifacts/). Synthetic only (§5); a demo artifact, not production logic.

---

> 🎩 **Build demo - let's make something.** I'll spec, build and fully review a new **wash-trade /
> self-match** detection (TS-001), on synthetic data. The intake gates first - I answer them; on a
> real job *you* would:
> - ⚠️ **Execution?** → **Yes**, but only this trusted demo repo on synthetic data (so I can *run*
>   the tests - that's how review earns its keep).
> - 🛡️ **Data?** → **Synthetic, no real data.**
>
> **Right-sizing, out loud:** this is the *heavy* demo - a full DoD delivery is **8 specialists**
> (build + 3 independent reviews + tuning + performance). It is **not** cheap (see the token
> note at the end); a lighter ask would use far fewer.

### → Step 1: Amara (`business-analyst`, sonnet) writes the spec

> 🎩 Why her, why sonnet: turning a regulatory need into a testable spec is structured BA work, not
> novel judgement. She cites the obligation and **flags every threshold as a tuning decision** rather
> than inventing numbers.

Amara produced [**`ts001-scenario-spec.md`**](build-artifacts/ts001-scenario-spec.md): the behaviour,
**MAR Art 12(1)(a)** (the only pinpoint *verified* in the register - the rest flagged `[TO-VERIFY]` 🧠
per ADR-001), 6 EARS requirements, Gherkin acceptance criteria, the data schema, and **5 open
questions** - carrying `obligation_status = PROVISIONAL` until the SME confirms the mapping.

### → Step 2: Camila (`trade-surveillance-sme`, sonnet) validates + dispositions

> 🎩 Camila advises only - she never touches code. She confirms the typology, names the
> false-positive drivers, and **formally closes the open questions** so nothing dangles.

She validated the typology (UBO linkage is the right entry point; **off-market price must be a
*necessary* condition**, not a score - spread-normalised, mid-referenced), named the FP drivers
(**affiliated funds under one manager = the single biggest pitfall**, structural not tunable;
market-making; coincident liquid orders), and **dispositioned all 5 questions**
([validation](build-artifacts/ts001-sme-validation.md)): **1 ✅, 3 🔴 go-live blockers, 1 ⏭️** → the
obligation mapping is **not** safe to finalise. She also flagged a known scope gap: *at-market* wash
(volume-only) won't alert under the necessary condition - a candidate future scenario.

### → Step 3: Mateo (`rules-developer`, sonnet) builds it

> 🎩 Mateo builds from the *validated* spec - UBO keystone, off-market as an early-continue, obligation
> **and** UBO id as alert fields, an injected `as_of_date` (deterministic, no wall clock).

Mateo produced [**`ts001_wash_trade.py`**](build-artifacts/ts001_wash_trade.py) + tests: Phase-1
UBO-only pairing, the spread-normalised off-market **necessary condition**, safe-harbour + materiality
suppression, **per-account** stale-graph exclusion with a data-quality warning, the implied-match tier
off at launch, and thresholds as **named constants each with a rationale + `tuning_date`**.

```console
$ cd docs/demos/build-artifacts && python3 -m pytest test_ts001_wash_trade.py -q
..........                                                               [100%]
10 passed
```

### → Step 4: the independent reviews (Ravi + Linh + Layla, in parallel)

> 🎩 The adversarial pass - three independents, no chatter, findings onto the blackboard. Did review
> earn its keep? **Yes - and the standout is that two of them found the *same* real defect independently.**

- **Ravi (`code-reviewer`, opus):** ⚠️ conditional pass. **W1 - a non-positive market price was
  *silently dropped* with no audit record** (a silent false-negative). Plus items for the SME/tuning
  (MM-as-tag vs designated register; the mid-vs-touch threshold frame) and order-dependent UBO edges.
  Caveat: the Python analysers aren't installed here, so his logic findings are **🧠 inferred**.
- **Linh (`qa-engineer`, sonnet):** wrote a **31-test** independent suite (boundaries, the exemption
  register, observability) - and independently hit the **same bad-mid silent drop** (NOTE-001). She
  also found the *previous* run's QA file was stale (tested an API that no longer exists) and
  **regenerated it** against the delivered detector.
- **Layla (`compliance-reviewer`, opus):** **FAIL - return to build**, and rightly: the rework had
  left the old delivery report + RTM describing a **non-existent API** and stale claims. The code
  itself she found **sound** - typed obligation/UBO fields, `PROVISIONAL` correctly held, citations
  **grounded** (`check_citations`: Art 12(1)(a) `[VERIFIED]`, the rest `[TO-VERIFY]` - no
  confabulation), data-safe. Her durable lesson: *a post-review rewrite silently invalidates the prior
  QA/RTM/handover - re-sync and re-run before the gate.*

> 🎩 **That's the chain working.** Two independents caught the same silent false-negative - that's the
> signal it's real. I routed it back to Mateo (mirror the data-quality guard so a bad price leaves a
> trail, never a silent drop), plus the order-dependent UBO edges. Re-ran **both** suites:

```console
$ python3 -m pytest test_ts001_wash_trade.py test_ts001_qa.py -q
...........................................                              [100%]
43 passed
```

### → Step 5: Theo (tuning) + Thabo (performance)

> 🎩 Two more, in parallel, before I sign anything off.

- **Theo (`tuning-analyst`):** thresholds stay un-invented, but now **measured**. He built a seeded
  synthetic labelled set and swept the off-market threshold ([tuning pack](build-artifacts/threshold-tuning-pack.md)):
  recommend **0.75× the spread from mid** - precision **0.84** / recall **0.84** (F1 0.84). 0.5× (the
  touch) over-alerts; 1.0× misses 28%. **Caveat:** synthetic distribution - it validates the
  *method*, not a production number; re-confirm on real data before go-live.
- **Thabo (`performance-reviewer`):** [won't scale as-is](build-artifacts/performance-review.md) -
  the O(buys×sells) pairing; fix is to pre-bucket by `(instrument, ubo_group_id)`. A **deploy-gate**,
  deferred to productionisation (a demo has no volume).

### → The delivery

The consolidated [**delivery report**](build-artifacts/delivery-report.md) ties it together: the RTM
(against the *delivered* API), every finding dispositioned, the DoD gate, the developer handover, the
measured token table - and it closes with the **[engagement-summary email](build-artifacts/engagement-summary-email.txt)**.

> 🎩 **The verdict.** This is **demo-complete** - every stage ran on synthetic data. But it is
> **NOT deployable**, and I'll say exactly why: the obligation mapping is PROVISIONAL (SME blockers),
> the 0.75× threshold is a synthetic number that needs real-data confirmation, the O(B×S) pairing
> needs bucketing before volume, and a **human still has to sign off** - which a demo cannot do. A
> report that hid those to look "all green" would be the failure. Saying them is the job.

---

## What this demo showed
- **Orchestrator-workers, end to end** - 8 specialists, each output feeding the next via the blackboard.
- **Independent review is not a rubber stamp** - two reviewers independently caught the same silent
  false-negative, and compliance caught that a post-rework rewrite had desynced the evidence docs.
- **Citations retrieved, not recalled** - only the register-verified pinpoint is asserted; the rest
  are flagged `[TO-VERIFY]`, and the obligation mapping is held `PROVISIONAL`.
- **No invented thresholds; measured, not guessed** - flagged in the spec, then calibrated with a real
  labelled harness (with the synthetic-data caveat stated).
- **Gates** - demo-complete, but plainly **not deployable** until the mapping is finalised,
  the threshold is re-confirmed on real data, the O(B×S) pairing is bucketed, and a human signs off.
