# Surveillance Coverage Assessment - <SCOPE / DESK / BUSINESS LINE>

> Produced by `data-quality-reviewer` with `business-analyst`. Maps in-scope risks → scenarios
> → the **data feeds** each needs → coverage status, and surfaces the **undetected-abuse blind
> spots**. Assessment uses **synthetic/masked data and feed metadata only** (§5). Authored in
> `.md`, rendered to `.html`. Read-only assessment - feed/coverage fixes are built by
> `platform-engineer` / `data-analyst`; this pack is the finding, not the remediation.

> **Document control** · ID `COV-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Internal | Confidential` · Owner `<name / role>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

| | |
|---|---|
| **Scope** | <desk / asset class / venues / comms population> |
| **Jurisdiction(s)** | <applicable regime(s) (CLAUDE.md §2)> |
| **Date / assessor** | <YYYY-MM-DD> |
| **Headline** | <N blind spots - M critical, in one line> |
| **Next re-assessment date** | <YYYY-MM-DD> |
| **Re-assessment triggers** | <new channel/venue onboarded; new product/desk; regulatory change; feed incident; zero-alert period exceeding X days on any scenario> |

## 1. Why this matters - the MW79 lesson
The FCA's surveillance model-testing expectation has **four** components - parameter
calibration, model **logic**, model **code**, and **data** (comprehensiveness & accuracy)
(FCA Market Watch 79). Failures most often come from **data-ingestion gaps, not thresholds**:
MW79 records a news feed left un-activated, so an insider-dealing scenario fired **zero alerts
for 3+ years**. A perfectly-tuned scenario on a dead feed detects nothing. This assessment
tests the data substrate, not just the logic.

## 2. In-scope risks / typologies
The conduct universe this scope must cover, each tied to its obligation.

| Typology | Domain (TM / trade / comms) | Obligation (CLAUDE.md §2) |
|---|---|---|

## 3. Risk → scenario → feed map
For every typology: the scenario(s) that cover it and the data feed(s) each scenario consumes.
A typology with **no scenario**, or a scenario with **no feed**, is a blind spot (§5).

| Typology | Detection scenario | Required data feed(s) | Owner |
|---|---|---|---|

## 4. Feed health check
Each feed a scenario depends on - is it **live, complete, and timely**? A feed can be
configured yet un-activated (the MW79 trap), so check that alerts actually fire from it.

| Feed | Live? (alerts firing) | Complete? (all instruments/venues/accounts) | Timely? (latency vs SLA) | Last verified |
|---|---|---|---|---|

## 5. Coverage gaps & blind spots
The output that matters: where abuse could occur undetected.

Severity scale (undetected-abuse exposure, not remediation effort):
- 🔴 Critical - a typology is entirely undetected or a required feed is confirmed dead; immediate escalation required.
- 🟠 High - partial coverage gap; a typology is detectable but material activity could pass through undetected.
- 🟡 Medium - minor coverage gap or quality degradation; detection works but with reduced precision/recall.
- 🔵 Low - informational; no material detection impact.

| Gap | Type (no-scenario / missing-feed / dead-feed / partial-feed) | Typology exposed | Severity | Route to |
|---|---|---|---|---|

Missing/dead feeds → `platform-engineer`; partial/quality issues → `data-analyst`; missing
scenarios → `business-analyst` / `rules-developer`.

**Dead-feed detection** - "no alerts" is ambiguous: it can mean the population is genuinely quiet
OR a feed has silently failed (the MW79 trap). Distinguish these using at least one of:
- **Synthetic canary alert** - inject a synthetic record that must always trigger an alert; confirm
  receipt per scheduled run. Absence of the canary alert = feed or scenario failure.
- **Reconciliation count** - compare the record count received from the upstream system to the
  expected baseline (based on historical volume). A zero or near-zero count on a normally busy feed
  is a dead-feed signal, not a quiet-market signal.
- **Heartbeat / last-seen timestamp** - monitor the latest event timestamp in the feed; alert if it
  has not advanced within X minutes/hours of the expected delivery window.

| Feed | Dead-feed detection method | Canary / reconciliation ref | Last verified |
|---|---|---|---|

## 6. Recommendation & next steps
Prioritised remediation with owners. Close with concrete options and a recommendation - never
end at the gap list. Re-assessment cadence and triggers are recorded in the header above.

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
