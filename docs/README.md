# Documentation index

Every document under `docs/`, by purpose. The team's prompts cite these by path; the reference
validator (`scripts/validate_references.py --orphans --strict-orphans`, run in CI) fails on any
tracked document nothing links to, so a new page is added here or to its folder's own index.

## Start here

- [`docs/OVERVIEW.md`](OVERVIEW.md) - a plain-English tour for people new to AI agents
- [`docs/quick-start.md`](quick-start.md) - the one-page reference (rendered as `.html` and `.pdf`)
- [`docs/FAQ.md`](FAQ.md) - the questions a bank user asks first
- [`docs/glossary.md`](glossary.md) - the domain and specification shorthand

## How the team works

- [`docs/team-operating-guide.md`](team-operating-guide.md) - roster, routing and the standing rules; the
  deferred topic files live in [`docs/operating-guide.d/command-index.md`](operating-guide.d/command-index.md)
- [`docs/team-operating-guide-orchestration.md`](team-operating-guide-orchestration.md) - dispatch and right-sizing
- [`docs/team.md`](team.md) - the roster, who does what, the portrait
- [`docs/worked-example.md`](worked-example.md) - a captured review engagement, start to close
- [`docs/agent-design.md`](agent-design.md) - why each agent has its tier and tool grants
- [`docs/WAYS-OF-WORKING.md`](WAYS-OF-WORKING.md) - the frameworks (BABOK, 29148, ADRs, ASVS) and when each applies
- [`docs/DEFINITION-OF-DONE.md`](DEFINITION-OF-DONE.md) - the evidenced gate an engagement must pass
- [`docs/code-review-method.md`](code-review-method.md) and [`docs/review/tooling.md`](review/tooling.md) - the review method, lenses, router and tooling
- [`docs/coding-standards.md`](coding-standards.md) and [`docs/house-rules.md`](house-rules.md)
- [`docs/scope-and-stack.md`](scope-and-stack.md) - the example regulatory scope and stack; replace with yours
- [`docs/sme/README.md`](sme/README.md) - the three domain knowledge packs
- [`docs/scenarios/spoofing.md`](scenarios/spoofing.md) - the worked spoofing scenario and its [calibration](scenarios/spoofing-calibration.md)
- [`docs/detection-health.md`](detection-health.md) - coverage, tuning and validation, together

## Safety, packaging and operations

- [`docs/safety-model.md`](safety-model.md) - what each control guarantees, per channel
- [`docs/INTEGRATIONS.md`](INTEGRATIONS.md) - Jira, pull requests, and the Claude Code features and config the team relies on
- [`docs/EXTENDING.md`](EXTENDING.md) - adapting the team to your organisation
- [`docs/scripts-reference.md`](scripts-reference.md) - every script and when the team runs it
- [`docs/token-usage.md`](token-usage.md) - what an engagement costs and how the load is kept down
- [`docs/roadmap.md`](roadmap.md)
- [`examples/README.md`](../examples/README.md) - the shipped sample engagement, a real run on synthetic data, opened by `virt-surv try --replay`
- [`docs/releases/0.38.0.md`](releases/0.38.0.md) and
  [`docs/releases/archive-0.36-and-earlier.md`](releases/archive-0.36-and-earlier.md) - the 0.38.0 working notes and the changelog's archive
- [`docs/releases/0.33.md`](releases/0.33.md) - the 0.33 cycle overview, with the point releases
  [0.33.0](docs/releases/0.33.0.md) (`docs/releases/0.33.0.md`) and [0.33.1](docs/releases/0.33.1.md) (`docs/releases/0.33.1.md`)
- [`docs/demos/review-demo.md`](demos/review-demo.md) - a captured review engagement

## Plans (tracked)

- [`docs/plan-codebase-memory-2026-08-27.md`](plan-codebase-memory-2026-08-27.md)
- [`docs/plan-org-extensions-2026-08-27.md`](plan-org-extensions-2026-08-27.md)
- [`docs/plan-project-footprint-2026-08-27.md`](plan-project-footprint-2026-08-27.md)

## Templates

Every artifact the team produces starts from one of these (`docs/templates/`):

- [`docs/templates/adr.md`](templates/adr.md)
- [`docs/templates/alert-investigation.md`](templates/alert-investigation.md)
- [`docs/templates/brd.md`](templates/brd.md)
- [`docs/templates/change-request.md`](templates/change-request.md)
- [`docs/templates/codebase-map-area.md`](templates/codebase-map-area.md)
- [`docs/templates/codebase-map.md`](templates/codebase-map.md)
- [`docs/templates/comms-surveillance-policy.md`](templates/comms-surveillance-policy.md)
- [`docs/templates/control-mapping.md`](templates/control-mapping.md)
- [`docs/templates/data-dictionary.md`](templates/data-dictionary.md)
- [`docs/templates/data-lineage.md`](templates/data-lineage.md)
- [`docs/templates/decision-log.md`](templates/decision-log.md)
- [`docs/templates/delivery-report.md`](templates/delivery-report.md)
- [`docs/templates/developer-handover.md`](templates/developer-handover.md)
- [`docs/templates/elicitation-requirements.md`](templates/elicitation-requirements.md)
- [`docs/templates/engagement-brief.md`](templates/engagement-brief.md)
- [`docs/templates/engagement-summary-email.md`](templates/engagement-summary-email.md)
- [`docs/templates/exploratory-analysis.md`](templates/exploratory-analysis.md)
- [`docs/templates/fsd.md`](templates/fsd.md)
- [`docs/templates/lexicon-spec.md`](templates/lexicon-spec.md)
- [`docs/templates/mi-spec.md`](templates/mi-spec.md)
- [`docs/templates/model-validation-report.md`](templates/model-validation-report.md)
- [`docs/templates/ops-runbook.md`](templates/ops-runbook.md)
- [`docs/templates/performance-report.md`](templates/performance-report.md)
- [`docs/templates/process-map.md`](templates/process-map.md)
- [`docs/templates/qa-handover.md`](templates/qa-handover.md)
- [`docs/templates/reg-change-impact.md`](templates/reg-change-impact.md)
- [`docs/templates/release-notes.md`](templates/release-notes.md)
- [`docs/templates/review-report.md`](templates/review-report.md)
- [`docs/templates/rtm.md`](templates/rtm.md)
- [`docs/templates/sar-str-referral.md`](templates/sar-str-referral.md)
- [`docs/templates/scenario-doc.md`](templates/scenario-doc.md)
- [`docs/templates/scenario-spec.md`](templates/scenario-spec.md)
- [`docs/templates/segmentation-analysis.md`](templates/segmentation-analysis.md)
- [`docs/templates/stakeholder-analysis.md`](templates/stakeholder-analysis.md)
- [`docs/templates/start-here.md`](templates/start-here.md)
- [`docs/templates/surveillance-coverage-assessment.md`](templates/surveillance-coverage-assessment.md)
- [`docs/templates/team-extensions.md`](templates/team-extensions.md)
- [`docs/templates/threshold-tuning-pack.md`](templates/threshold-tuning-pack.md)
- [`docs/templates/tm-model-validation.md`](templates/tm-model-validation.md)
- [`docs/templates/trade-scenario-design.md`](templates/trade-scenario-design.md)
- [`docs/templates/tuning-decision-register.md`](templates/tuning-decision-register.md)
- [`docs/templates/uat-plan.md`](templates/uat-plan.md)
- [`docs/templates/user-stories.md`](templates/user-stories.md)

Local-only, not tracked: `docs/adr/` (decision records, indexed in its own README) and
`docs/internal/` (reviews, audits and working plans).

## Repository layout

> Moved out of README.md on 2026-09-14 (framework review, step 6.8).


In one line: `.claude/agents/` (13 subagents) · `docs/sme/` (3 SME knowledge packs) · `.claude/skills/` (32 workflows) · `.claude/hooks/` + `settings.json` (safety guards) · `rules/` + `tests/` (the spoofing worked example) · `scripts/` (tooling) · `vendor/` (pip-less deps) · `config/` (masking schema, regulatory register) · `docs/` · `evals/` · `.claude-plugin/` (manifests).

<details>
<summary>📁 <b>One consolidated map of the repo</b></summary>

```
.claude-plugin/                 # plugin + marketplace manifests (installable via /plugin)
CLAUDE.md                       # shared team handbook (example defaults - customise as needed)
.claude/agents/                 # 13 subagents:
   builders                       business-analyst · rules-developer · platform-engineer ·
                                  data-analyst · tuning-analyst · ml-engineer · qa-engineer
   advisors (read-only)           model-validator · code-reviewer · performance-reviewer ·
                                  compliance-reviewer · data-quality-reviewer
   (SME typology advice lives in docs/sme/ knowledge packs - in-line, no agent)
   helper                         review-scorer (haiku - review prep, scoring, filter tallies)
.claude/skills/                 # 32 workflows: /engage, /deep-review, /audit-review, /security-audit, /handover,
                                #   /new-scenario, /tune-thresholds, … (see "Using them")
.claude/hooks/ + settings.json  # data-safety (always-on) + session-scoped execution guards
rules/ · tests/                 # the bundled example (spoofing) + its true/false-positive tests
scripts/                        # masking (ingest), synthesise, render_html, eval_score,
                                #   calibrate_spoofing, check_citations, validate_* helpers,
                                #   convert_file (the file-conversion front door)
vendor/                         # bundled pure-Python deps (no pip): convert_file's readers +
                                #   rich/prompt_toolkit for the virt-surv go TUI; licences in
                                #   THIRD-PARTY-LICENSES.md
config/                         # masking schema + regulatory register + feed-schema example
docs/                           # OVERVIEW · WAYS-OF-WORKING · agent-design · scope-and-stack ·
                                #   scenarios/ · demos/ · templates/ · adr/
evals/                          # team-quality eval harness: 9 rubrics + 52 golden cases
.github/workflows/ci.yml        # tests + lint + manifest validation + gitleaks + no-raw-data check
.pre-commit-config.yaml         # local secret / raw-data guardrails
```

</details>

<sub>[↑ Back to top](../README.md#readme-top)</sub>
