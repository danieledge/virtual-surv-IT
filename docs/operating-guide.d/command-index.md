# Command index (canonical - 13 front doors, 32 skills on disk)

> Deferred from `docs/team-operating-guide.md` (open-core split, token plan Phase 1,
> 2026-08-18). **Read when** composing workflow options for the user beyond the routing
> table, or when unsure whether a command exists. The routing table in the operating guide
> answers "who does this work"; this file answers "which command runs it". Since 2026-09-13
> (framework review, step 4.5) the team has **13 front doors**; the older names are engines
> behind them and still work for one release.

## Command index

- `/engage` - front door: intake + orchestration for any request (problem, review or build);
  `--light` is the low-ceremony profile (same safety gates + code chain, 2-3 agents, refuses
  detection logic, upgrades to standard)
- `/demo` - guided end-to-end demo on synthetic data, every decision narrated; `/demo replay`
  opens the shipped sample engagement (`examples/engagements/`) with no tokens
- `/review` - every code review: `--depth quick|deep|audit`, `--focus security|performance|quantexa`,
  `--fix` for the assess-fix-re-review loop on legacy code
- `/build` - end-to-end build from a requirements pack; `--scenario` for a single detection
  scenario (spec, SME-pack review, build, compliance review)
- `/requirements` - `--elicit` (BABOK elicitation), `--brd` (idea to BRD), `--fsd` (BRD to FSD),
  `--impact` (regulatory change to affected scenarios, controls, data, specs)
- `/detection-health` - `--coverage` (is everything in scope monitored, are feeds live),
  `--tune` (ATL/BTL threshold calibration), `--validate` (periodic TM model validation pack)
- `/why-no-alert` - detection-gap triage: why a case-level miss, silent scenario or volume
  drop happened - fixed lineage walk, evidence per stage
- `/analyse-data` - exploratory analysis to an evidenced insight report
- `/prepare-data` - safe data onboarding (synthetic or masked) before any agent sees it
- `/handover` - handover pack: dev docs + independent QA evidence + change/ops artifacts
- `/map-codebase` - deterministic first-contact skeleton pass + a small synthesis team,
  producing/refreshing the curated codebase map (`--refresh` re-verifies drifted areas)
- `/team` - `--meet` (Morgan introduces the roster), `--preferences` (project settings),
  `--dashboard` (the local cross-project dashboard); quick utilities, no engagement opened
- `/run-evals` - the team-quality eval harness against the golden cases (spends tokens; kept
  separate so its narrow Bash grant stays narrow)

### Engines and aliases (type the front door instead; kept for one release)

- `/engage-light` - engine for `/engage --light`
- `/deep-review` - engine for `/review` (default depth)
- `/audit-review` - engine for `/review --depth audit`
- `/security-audit` - engine for `/review --focus security`
- `/performance-review` - engine for `/review --focus performance`
- `/beta-assess-quantexa` - engine for `/review --focus quantexa` (beta)
- `/remediate` - engine for `/review --fix`
- `/build-solution` - engine for `/build`
- `/new-scenario` - engine for `/build --scenario`
- `/elicit-requirements` - engine for `/requirements --elicit`
- `/write-brd` - engine for `/requirements --brd`
- `/brd-to-fsd` - engine for `/requirements --fsd`
- `/reg-change-impact` - engine for `/requirements --impact`
- `/assess-coverage` - engine for `/detection-health --coverage`
- `/tune-thresholds` - engine for `/detection-health --tune`
- `/validate-tm-model` - engine for `/detection-health --validate`
- `/meet-the-team` - engine for `/team`
- `/preferences` - engine for `/team --preferences`
- `/dashboard` - engine for `/team --dashboard`
