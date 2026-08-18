# Enhancement plan: alert-absence investigation ("why did this not alert?")

Status: PROPOSED 2026-08-18. Sources: a framework capability audit (agent-run, full report
summarised in section 1) and external deep research (industry practice, regulator fact
patterns, RCA-agent design, rule-engine explain techniques - key citations inline).
Nothing below is implemented.

## Why this query family matters

"Why did this alert not generate?" / "why am I seeing no alerts?" is a standing
surveillance-ops query, and the enforcement record is a catalogue of exactly these misses:
FCA Market Watch 79's three fact patterns (a news feed never activated - zero insider
alerts for 3+ years; a coding error silently excluding illiquid instruments while liquid
names masked the silence; DMA data never ingested despite years of assumed coverage), the
FINRA fine for a vendor change that silently stopped alert generation for three years, and
the UBS $125M case (a partial feed wired in, 5%+ of wires never alerting). The meta-lesson
everywhere: **presence elsewhere masks absence somewhere** - aggregate alert volume is not
scenario/segment health.

## 1. Where the framework stands today (audit verdict)

Strong on SYSTEMIC absence, nearly unarmed on CASE-LEVEL absence. Per diagnostic-chain link:

| Link | Rating | Evidence |
|---|---|---|
| (a) Did the data arrive (feed completeness/latency) | Strong | DQ reviewer checklist, /assess-coverage, coverage-dead-feed eval |
| (b) Did it pass ingestion filters (eligibility, exclusion lists) | Weak | one DQ clause; "exclusion list"/"eligibility" appear nowhere |
| (c) Did the logic evaluate (per-condition trace) | Weak | static code-reading only; the spoofing rule's five non-fire paths are silent `continue`s; running anything hits the §7 gate |
| (d) Threshold suppression (BTL, near-miss) | Partial | population BTL is doctrine and eval-enforced; case-level near-miss ("missed by 3.6% on condition C") absent |
| (e) Post-generation dedup/suppression | Absent | the alert post-processing layer does not exist as a concept anywhere |
| (f) Scenario in scope (typology/instrument/channel) | Strong | /assess-coverage map, coverage-uncaptured-channel eval |

Routing is judgement-dependent: the deliverable table has an FP-analysis row and no
FN/absence row, and `data-analyst`'s one canonical example is the exact mirror query
("too many alerts"). No eval hands the team an activity trace and asks "why no alert on
this?"; the SME packs are design-time only.

## 2. What the research says to steal

Techniques that repeatedly appear across industry, regulators and the RCA-agent
literature, each mapped to the link it fixes:

1. **Pipeline-stage lineage walk as a FIXED fault tree** (links a-f): feed → ingestion →
   eligibility → evaluation → threshold → suppression → case; first absent stage
   localises the fault. The RCA-agent literature is unanimous that a fixed causal
   skeleton plus LLM evidence-gathering beats free-form hypothesising (VerifyOps,
   arXiv 2607.22385; why-not provenance, PUG arXiv 1808.05752).
2. **Rule explain mode - per-condition truth table with first-failing-condition** (link c):
   LaunchDarkly's "evaluation reasons" pattern; Drools' documented weakness ("no good way
   to tell which condition failed") is the cautionary tale - emission must be built in,
   not bolted on by log archaeology.
3. **Counterfactual replay with distance-to-threshold** (link d): relax each failing
   threshold until fire; report the minimal perturbation. Generalises BTL from
   populations to one event.
4. **Per-scenario, per-segment volume baselines + change-point detection correlated with
   deploys and feed volumes** (volume-drop form): what would have caught MW79 Firm B.
5. **Silent-scenario heartbeats + synthetic canaries** (systemic form): zero alerts over
   expected cadence is itself alertable; inject a known-abusive synthetic pattern
   end-to-end and assert an alert emerges (detection-engineering/BAS practice).
6. **Shadow/dry-run diff on rule changes**: before/after alert-count diff for every
   threshold/logic change (the FINRA vendor-change class of failure).
7. **Evidence-verified hypothesis table in the agent loop**: supporting AND contradicting
   evidence per hypothesis, sufficiency gate before concluding - guards the two
   documented LLM-RCA failure modes (fabricated evidence, insufficient evidence) and is
   native to the team's 📊/🧠 discipline.

Vendor vocabulary for naming: scenario calibration, simulation/replay, rule
experimentation, threshold analyzer, evaluation reasons, detection assurance.

## 3. The plan

### Phase 1 - make the query routable and the investigation structured (docs/prose, ~a day)

1. **Routing row**: add "Alert-absence / detection-gap triage ('why no alert?', 'volumes
   dropped')" to the deliverable → owner table: `data-analyst` leads case-level,
   `data-quality-reviewer` owns links a/b, `tuning-analyst` owns link d, orchestrated -
   with the systemic form routed to `/assess-coverage`.
2. **New skill `/why-no-alert`** encoding the method:
   - classify the FORM first: case-level (this activity), scenario-level (this scenario
     is silent), or volume-drop (fewer than before) - each gets a different opening move;
   - the fixed a-f lineage walk as the skeleton, first-absent-stage search, one stage at
     a time with evidence recorded per stage (📊 where checkable, 🧠 where not);
   - an evidence-verified hypothesis table (hypothesis, supporting, contradicting,
     verdict) - never a single-cause conclusion without exclusion reasoning;
   - the §7 reality stated up front: without execution consent the diagnosis is capped at
     🧠 inferred from static reads; shipped trace tooling (Phase 2) is the consent-free
     route to 📊;
   - MW79/SR 11-7 citations for the report's obligation line.
3. **SME packs**: an "under-alerting diagnosis" section per pack - typology-specific
   absence causes (TM: eligibility/exclusion lists, segmentation misassignment; trade:
   instrument/venue scope, liquidity masking; comms: channel capture, lexicon language
   gaps) so the in-line consult has something to say when the question is a miss.
4. **Roster touch-ups**: `data-analyst` gains the FN direction as a named example;
   `data-quality-reviewer` checklist gains links b and e explicitly (ingestion
   eligibility/exclusion lists; alert-lifecycle dedup/suppression as distinct from data
   dedup).

### Phase 2 - mechanical explain capability on the worked example (code, ~a day)

5. **a new `explain_rule` script under scripts/** (worked-example scope: spoofing): given a session id and
   a sessions file, re-evaluate `detect_spoofing`'s conditions WITHOUT short-circuit and
   emit the truth table - condition, observed value, required value, pass/fail, first
   failing condition in normal order - plus counterfactual distance-to-threshold per
   failing numeric condition, using the already-injectable `SpoofingThresholds`. The rule
   itself stays untouched (its silent non-fire paths are fine once the explainer exists).
6. **Near-miss surface in `calibrate_spoofing`**: per-session distance vector instead of
   the current boolean, so population BTL and case-level near-miss share one mechanism.
7. **Allow-list**: both names into `_TEAM_ALLOW` via the staged-guard + human-apply
   process (standing rule) so the explain path is consent-free - that is the point:
   a 📊-observed absence diagnosis with no execution-gate friction.

### Phase 3 - detection-health doctrine (docs + small script, ~half a day)

8. **Scenario-health section** (operating guide or a new detection-health doc under docs/,
   referenced by `/assess-coverage` and `/tune-thresholds`): silent-scenario heartbeats
   (zero alerts is a state, with expected cadence per scenario/segment), per-segment
   volume baselines with change-point correlation against deploy/config/feed-volume
   changes, synthetic canaries (a `gen_synthetic --canary` mode feeding an end-to-end
   assertion), and the shadow-diff rule: no threshold/logic change ships without a
   before/after alert-count diff on historical data.
9. **/assess-coverage** gains the "presence masks absence" rule: coverage verdicts at
   segment granularity, never aggregate-only.

### Phase 4 - eval closure (the regression net, ~half a day + one live run)

10. **New golden case `absence-case-level`**: a synthetic session that SHOULD have
    alerted but misses on one condition + the rule + the question "why did this not
    alert?". Graded on: walking the chain, identifying the first failing condition with
    observed-vs-required values, distance-to-threshold, and a false-positive trap for
    inventing a feed outage that is not in evidence (the fabricated-evidence failure
    mode).
11. **New golden case `absence-volume-drop`**: alert-count series + a co-timed config
    change + a feed-volume series; graded on change-point reasoning and the correlation,
    with a trap for blaming the feed when the config change is the fit.
12. Both cases join the golden slice for the next release baseline.

### Sequencing and cost

Phases are independent enough to ship 1 → 2 → 3 → 4 in order, roughly three days of
sessions; Phase 4's live eval adds ~$3-6 at the sonnet tier. Phase 1 alone already
converts the query from judgement-routed to method-routed; Phase 2 is the highest-leverage
single item (the audit's gap #2) because it upgrades the team's best possible answer from
🧠 inferred to 📊 observed without touching the consent model.

### Explicitly out of scope

Building real change-point/heartbeat MONITORING infrastructure (that is the client
platform's job; the team advises on and specifies it - the doctrine in Phase 3 is what
the team itself applies when asked). No new agent: the audit shows the roster covers the
chain; what is missing is the method, the mechanical trace, and the routing.
