---
description: Investigate why an alert did NOT generate - a case-level miss, a silent scenario, or an alert-volume drop (detection-gap triage)
argument-hint: <the miss - "why didn't scenario X alert on this?", "no alerts from Y", "volumes dropped" - or describe it>
disable-model-invocation: true
---

Under the PM (CLAUDE.md §6), investigate the reported alert ABSENCE: **$ARGUMENTS**

**The standard open applies before any investigation, even when this skill is invoked
directly.** Read `.claude/skills/.shared/engagement-bookends.md` and follow it. **Chained
skills are dormant** - when a step routes to another workflow, read
`.claude/skills/<name>/SKILL.md` and follow it in this session (`.claude/skills/.shared/run-mode.md`).

**0. Classify the FORM first** - three shapes, three different opening moves; say which
one this is before touching anything:
- **Case-level** ("why didn't it alert on THIS activity"): the lineage walk in step 1,
  over that activity.
- **Scenario-level** ("this scenario is silent"): systemic - route through
  `/assess-coverage`'s typology→scenario→feed machinery scoped to that scenario. The
  front-running causes are FCA Market Watch 79's three fact patterns: a feed never
  activated, a silent logic defect masked by alerts elsewhere, data never ingested.
- **Volume-drop** ("fewer alerts than before"): time-series - locate the change-point in
  per-scenario, per-SEGMENT alert counts first, then correlate with co-timed changes
  (deploy/config/threshold edits, feed volumes) before blaming any single cause.

**1. Walk the fixed lineage chain - the first ABSENT stage localises the fault.** Never
free-form hypothesise; this chain IS the hypothesis space, and evidence is recorded per
stage (📊 where mechanically checked, 🧠 where inferred - CLAUDE.md §6):

| Stage | Question | Lead |
|---|---|---|
| (a) Feed | Did the data arrive - complete, on time? | `data-quality-reviewer` |
| (b) Ingestion | Did it pass eligibility/segmentation - or die on an exclusion list or filter? | `data-quality-reviewer` |
| (c) Logic | Did the rule evaluate - which condition failed first, observed vs required? | `data-analyst` (trace tooling where shipped; static read otherwise) |
| (d) Threshold | Suppressed just under the line? Distance-to-threshold, near-miss, BTL | `tuning-analyst` |
| (e) Post-generation | Deduplicated, suppressed, or filtered after generation, before a case? | `data-analyst` |
| (f) Scope | Is the scenario even in scope for this typology/instrument/venue/channel? | `/assess-coverage` machinery |

Consult the matching `docs/sme/` pack's under-alerting section in-line for
typology-specific causes at each stage - cite the pack, never a persona.

**2. Conclude through an evidence-verified hypothesis table** - hypothesis · supporting
evidence · CONTRADICTING evidence · verdict - and give exclusion reasoning for every
rejected candidate. Never a single-cause conclusion without it: fabricated evidence and
concluding on insufficient evidence are the two documented failure modes of LLM
diagnosis, and both are findings against this report if a reviewer catches them.

**3. State the execution boundary up front (§7).** Static by default: without the human
consent marker, nothing under investigation is executed, and stage (c)/(d) answers from
reading code are 🧠 inferred - say so in the report rather than dressing them up.
Allow-listed team tooling (the converters, calibrators, and any shipped rule-explain
trace tools) runs consent-free and is the preferred route to a 📊 observed answer.

**4. Right-size.** A single case-level miss with tooling available is often a
classify-and-answer quick look (state it, offer to formalise); a scenario-level or
volume-drop investigation with remediation is a real engagement. State the agent count
and the form (step 0) in the same breath at the gate.

**5. Report.** The deliverable is the diagnosis: the first failing stage with its
evidence chain, the hypothesis table, remediation routed by stage - (c) logic defect →
`/build-solution` or `/new-scenario` fix path with regression tests; (d) threshold →
`/tune-thresholds` (BTL before any cut); (a)/(b)/(f) → `/assess-coverage` +
`data-quality-reviewer` remediation - and the obligation line citing the register
(`config/regulatory-register.yaml` via `check_citations`; MW79 is the trade-surveillance
model-testing expectation, SR 11-7/OCC 2011-12 where TM scenarios are models). Verdicts
are SEGMENT-granular, never aggregate-only: presence elsewhere masks absence somewhere.

**Close - don't dead-end (CLAUDE.md §6).** Offer the natural next step with a
recommendation: fix-and-retest via the routed skill, a standing detection-health check,
or stop here with the diagnosis recorded.
