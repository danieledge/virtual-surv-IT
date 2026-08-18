# Command index (canonical - all 27 skills)

> Deferred from `docs/team-operating-guide.md` (open-core split, token plan Phase 1,
> 2026-08-18). **Read when** composing workflow options for the user beyond the routing
> table, or when unsure whether a command exists. The routing table in the operating guide
> answers "who does this work"; this file answers "which command runs it".

## Command index

- `/engage` - front door: intake + orchestration for any request (problem, review or build)
- `/engage-light` - explicit low-ceremony profile: same safety gates + code chain, one-page
  brief, 2-3 agents, short summary email, no delivery report; refuses detection logic, upgrades to standard
- `/map-codebase` - deterministic first-contact skeleton pass + a small synthesis team,
  producing/refreshing the curated codebase map (ADR-007 Phase 1, `--refresh` re-verifies only
  drifted areas)
- `/meet-the-team` - Morgan introduces the roster (canonical intro)
- `/prepare-data` - safe data onboarding (synthetic or masked) before any agent sees it
- `/demo` - guided end-to-end demo on synthetic data, every decision narrated
- `/write-brd` - idea → Business Requirements Document (BABOK + EARS)
- `/elicit-requirements` - stakeholder analysis + requirements gathering (BABOK)
- `/brd-to-fsd` - BRD → Functional Spec (ISO/IEC/IEEE 29148 + Gherkin)
- `/new-scenario` - new detection scenario end to end: spec → SME review → build → compliance review
- `/build-solution` - end-to-end build from a requirements pack (orchestrator-workers)
- `/analyse-data` - exploratory analysis → evidenced insight report
- `/why-no-alert` - detection-gap triage: why a case-level miss, silent scenario or volume
  drop happened - fixed lineage walk (feed → ingestion → logic → threshold → suppression →
  scope), evidence per stage
- `/tune-thresholds` - threshold calibration: ATL-BTL, segmentation, volume↔coverage trade-off
- `/validate-tm-model` - periodic TM model validation pack (coverage, thresholds, data integrity)
- `/assess-coverage` - are all in-scope risks monitored? typology→scenario→feed map + feed health
- `/reg-change-impact` - regulatory change → affected scenarios, controls, data, specs
- `/deep-review` - detailed multi-dimension code review with confidence scoring
- `/audit-review` - audit/regulatory-defensibility review (evaluator-optimizer loop)
- `/beta-assess-quantexa` - (beta) Quantexa TM estate vs BRD/TSD traceability assessment, with platform KB
- `/security-audit` - deep security audit: OWASP ASVS / CWE + threat model, security-focused evaluator-optimizer loop
- `/performance-review` - static performance & scalability review vs target volumes
- `/remediate` - legacy / poorly-built code: assess → prioritise → fix → re-review → hand over
- `/handover` - handover pack: dev docs + independent QA evidence + change/ops artifacts
- `/run-evals` - team-quality eval harness against golden cases (regression net)
- `/preferences` - view/change project-wide settings (docx export, regulatory citations);
  quick utility, no engagement opened
- `/dashboard` - regenerate the local, static, cross-project observability dashboard (every
  project + engagement this machine has evidence of, ADR-013); quick utility, read-only, no
  engagement opened.
