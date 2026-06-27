# Changelog

All notable changes to the compliance-surveillance-team plugin. Dates are absolute.
This is a proof-of-concept; see `docs/house-rules.md` for the evidence state of domain content.

## [0.6.0] - 2026-06-27

### Added
- **`/demo` guided demo** - Morgan runs a full engagement end-to-end on safe synthetic data,
  narrating every decision (which specialist + why, model tier + why, the patterns: right-sizing,
  blackboard, challenge pass, safety gates). Three flavours: review / build / data-safety. The
  fastest way to see the team work; surfaced as the new-user entry point.

### Changed - data-masking honesty (claims-vs-reality audit)
- **`validate_masking --in <file>`** - new mode that scans **your actual masked output** for
  residual free-text PII (string fields) + k-anonymity, rather than only the built-in synthetic
  fixture (which the default mode is now clearly labelled as). +2 tests (34 → 36).
- Fixed the PII-scan label ("all output fields" → "free-text-capable fields") to match the code,
  and tightened the README masking claims: validator-checks-a-fixture vs `--in` real-file scan,
  k-anonymity is off until `quasi_identifiers` are declared, and `redact` is regex-only (not safe
  for real comms without NER). Full audit in `artifacts/DATA-MASKING-CLAIMS-REVIEW`.

## [0.5.1] - 2026-06-27

### Changed - token optimisation
- **`CLAUDE.md` slimmed ~44%** (~5.2k → ~2.9k tokens) by moving the PM's detailed operating rules
  (question-construction, voice/console, outcome discipline, orchestration detail) to
  `docs/team-operating-guide.md`, read **on-engage**. CLAUDE.md keeps the always-on core (dormancy,
  data-safety §5, the routing table + names, the execution gate §7). It loads into every session and
  is inherited by every subagent, so this saves ~2.3k tokens per session - multiplied across a fan-out.
- Measured real token usage and documented it: new README **Token usage & optimisation** and
  **Self-test (eval harness)** sections.

## [0.5.0] - 2026-06-27

### Added - team-quality eval harness (`evals/`)
- A regression net that scores the team's **own output** against golden cases - so a prompt change
  that silently degrades rigour is caught. Closes the highest-value roadmap item and the last open
  Anthropic-conformance gap (LLM-as-judge).
- **5 rubrics** (code-review, coverage-assessment, spec-traceability, threshold-tuning, data-safety)
  and **17 golden cases** with seeded issues + false-positive traps, all synthetic.
- **`scripts/eval_score.py`** - deterministic scorer (recall / must-find criticals / FP-traps),
  with **7 unit tests** (`tests/test_eval_score.py`) so the harness backbone runs free in CI.
  Test suite: 27 → **34 passing**.
- **`/run-evals`** skill - runs the live team per case, scores deterministically, adds an LLM-judge
  for qualitative dimensions, prints a scoreboard, and flags regressions. (Spends tokens; run at
  milestones.)

## [0.4.2] - 2026-06-27

### Changed
- **Handover-doc quality is now a Definition-of-Done gate** - docs must be *clear & usable by a
  developer who has never seen the code* (build/run/change from the doc alone), not merely present;
  `compliance-reviewer` checks usability. Closes the documentation seam without adding an agent.
- **audit-review intake** aligned with the other review flows: inherits the fix-cycle and
  jurisdiction from `engage`, and no longer blurs the handover deliverable into the action question.
- **Em-dashes removed repo-wide** (markdown *and* code comments/docstrings/config) for consistent prose.
- README: Meet-the-team headcount corrected (15 specialists + PM + intern = 16 agents).

## [0.4.1] - 2026-06-27

### Changed
- **Streamlined engagement intake.** The review intake had grown to ~11 separate prompts; cut to
  ~5 with no decisions lost: removed a genuine **duplicate** (the fix-cycle question was asked by
  both `engage` and the review skills - `engage` now owns it, the review skills inherit it);
  **batched** multi-axis menus onto single `AskUserQuestion` screens (review menu = depth+perf+
  findings; scope = dimensions+breadth+mode); **gated** the execution-safety question to code
  engagements; dropped the standalone "any other clarifications?" step.
- **README:** Mei ↔ Viktor profile cross-links; "What's new" refreshed.

## [0.4.0] - 2026-06-26

### Changed - data-handling contract (the reason for the minor bump)
- **Data posture shifted** from "real data must never reach an agent" to: the raw-data folder is
  **hard-blocked** (unchanged keystone), and **other data the user provides may be analysed on the
  user's attestation** that it is masked/synthetic/anonymised with no prohibited PII. Responsibility
  is the user's. Committed examples/tests/artifacts stay synthetic/masked only (unchanged).
- **Startup data-safety disclaimer** - a punchy, emoji callout shown at intake alongside the
  code-execution disclaimer, with a one-question attestation. Mirrored into CLAUDE.md §5 and the
  Delivery Report.
- **Language follow-through** - removed every absolute "real data never reaches the AI" claim across
  the README, OVERVIEW, the skills (analyse-data, tune-thresholds, validate-tm-model, meet-the-team)
  and the delivery-report.

### Added
- **README Roadmap: "Automatic data-masking workflow" TODO** - the capability that *replaces* the
  disclaimer (schema-inference profiler · NER/Presidio · format adapters · real synthetic · an
  auto-validation gate that blocks on residual PII).

### Changed - presentation & behaviour
- **PM uses the team's names** in user-facing narration (standing behaviour, not optional); fixed a
  stale name (performance-reviewer is Thabo).
- **README restructure** - "Meet the team" moved up (after the intro, before Quick start) for
  prominence; jump-nav leads with it. Removed the traffic-light status circles from the profiles.

## [0.3.3] - 2026-06-25

### Added
- **Anthropic multi-agent conformance audit** (`docs/agent-design.md` §6) - the team mapped
  honestly against Anthropic's published multi-agent standards, with the **source links** (§7 +
  a README "Built on" section): Building Effective Agents, the multi-agent research system,
  context engineering, and the Subagents docs.
- **README Roadmap** - the outstanding enhancements with the rationale for each (LLM-judge eval
  harness; `/prepare-data` universality; evidence gaps to verify; a larger spoofing calibration set).

### Changed
- **Subagent self-assessment** is now a team convention (CLAUDE.md §6): every agent self-verifies
  against its brief and flags gaps before returning, rather than implying false completeness.
- **Delegation rule made explicit**: a subagent inherits none of the conversation - put every
  needed input in the brief (the documented cause of duplicated work / gaps).
- **Style:** removed all em-dashes across the README and every markdown file (docs, agents,
  skills, CLAUDE.md, CHANGELOG) for consistency.

## [0.3.2] - 2026-06-25

### Added
- **`docs/agent-design.md`** - the team as a worked example of a well-built Claude Code agent
  set-up: design principles, per-agent model-tiering rationale, deliberate deviations, the
  16-agent justification, and a best-practice **conformance matrix**.
- **`docs/prepare-data-roadmap.md`** - the credible "throw anything at it" path for `/prepare-data`
  (schema-inference profiler, NER/Presidio redaction, format adapters, real synthetic), with the
  assisted-not-blind framing and non-negotiable safety gates.

### Changed
- **Model tiering scrutinised + rebalanced → 4 opus / 11 sonnet / 1 haiku.** opus reserved for
  final/unchecked judgement or novel design (`model-validator`, `compliance-reviewer`,
  `code-reviewer`, `ml-engineer`); SMEs + `performance-reviewer` (now static-only) downgraded to
  sonnet; `compliance-reviewer` upgraded to opus. Rationale centralised in `docs/agent-design.md`.
- **Every agent has a human name** (Morgan PM + 16 specialists), **globally + gender-diverse**;
  README "Meet the team" rewritten as playful, compliance/IT-flavoured staff profiles with
  Slack-status one-liners. `review-scorer` retitled **Review Coordinator**.
- **README navigation overhaul** - badges, a jump-nav, emoji section headers.

### Verified
- **Comms-surveillance regulatory citations VERIFIED** against primary sources (MiFID II Art 16(7)
  / CDR 2017/565 Art 76, SEC 17a-4(b)(4) / FINRA 4511, the off-channel enforcement sweep) - folded
  into the comms templates; comms *practice* detail remains foundational (flagged).

## [0.3.1] - 2026-06-25

### Fixed
- **`tuning-analyst` was missing from `plugin.json` `agents`** - the flagship 0.3.0 agent would
  silently fail to load on a plugin install (project-mode dir-discovery masked it). Now registered.

### Changed - best-practice review remediation
- **Roster:** resolved the `data-analyst`⇄`tuning-analyst` overlap (data-analyst cedes threshold
  calibration/ATL-BTL/segmentation to tuning-analyst); added §5 data-safety lines to
  `model-validator` + `platform-engineer`; fixed `compliance-reviewer`'s Bash line that implied it
  runs tests (now static-only, §7); dropped "performance" from `code-reviewer`'s description;
  added opus-tier rationale to the SMEs; standardised the "When the team is engaged" prefix.
- **Skills:** disambiguated the surveillance-analytics trio (`/tune-thresholds`, `/assess-coverage`,
  `/validate-tm-model`); brought 7 skills' input-gathering up to the structured-AskUserQuestion
  standard; cross-referenced `/elicit-requirements` and `/write-brd`.
- **Safety/config:** `guard-code-execution.py` java regex now allows `-version`/`-help`; added
  `tests/test_hooks_in_sync.py` to prevent plugin/project hook-config drift.
- **Docs:** fixed stale counts; rewrote the README "Meet the team" section to be more engaging
  (and corrected stale performance-reviewer/code-reviewer detail).

## [0.3.0] - 2026-06-25

### Added - Data-analyst & business-analyst expansion (research-grounded)
- **`tuning-analyst`** agent - surveillance threshold calibration / alert tuning: risk-based
  segmentation, Above-The-Line / Below-The-Line testing, dry-run alerts, FP-rate & alert-to-SAR MI.
  Extended to trade (peer-group/benchmark, RTS 25 timestamp prerequisite) and comms (lexicon/NLP)
  tuning, with the FCA MW79 "four-component, not calibration-only" rule.
- **Workflows** - `/tune-thresholds`, `/validate-tm-model`, `/assess-coverage`,
  `/elicit-requirements`, `/reg-change-impact`, `/analyse-data`, and `/meet-the-team`.
- **Templates (16)** - threshold-tuning-pack, tm-model-validation, surveillance-coverage-assessment,
  trade-scenario-design, lexicon-spec, comms-surveillance-policy; stakeholder-analysis,
  elicitation-requirements, process-map (BPMN), user-stories, uat-plan, reg-change-impact,
  data-dictionary, mi-spec, segmentation-analysis, exploratory-analysis.

### Changed
- **`requirements-analyst` → `business-analyst`** - rebranded and broadened from spec-writer to the
  full BABOK lifecycle (elicitation, stakeholder/process analysis, UAT, traceability, reg-change
  impact, obligation→detection). All references updated repo-wide.
- **Performance review is static-only** for now - profilers/benchmarks removed; findings are
  inference-only (📊 only for explicit coded costs read in source). Re-enable via the consent flow.

### Added - Safety
- **Code-execution gate** (`guard-code-execution.py`) - reviews are static by default; running
  tests/profilers is blocked unless authorised by the `.claude/.exec-consent` marker (written on
  user consent) or `CST_ALLOW_EXEC=1`, behind a prominent intake disclaimer (CLAUDE.md §7).

### Evidence
- AML/TM tuning, FCA Market Watch 79, and the **trade/market-abuse regulatory spine**
  (MAR Art 16(2) / CDR 2016/957 / RTS 24 (2017/580) / RTS 22 (2017/590) / RTS 25) are **verified
  against primary sources** (EUR-Lex, legislation.gov.uk, ESMA).
- **Unverified (flagged):** comms specifics (MiFID II Art 16(7), SEC 17a-4 / FINRA 4511, the
  off-channel sweep), per-scenario tuning practice, and the DA/BA boundary - see `docs/house-rules.md`.

## [0.2.0]

- Modular code-review subsystem (review lenses + scoreboard + evidence-basis tagging + style lane +
  Morgan-challenges-findings + opt-in AI-review pre-commit gate), integrating
  [turingmind-code-review](https://github.com/turingmindai/turingmind-code-review) (MIT).

## [0.1.1]

- Initial plugin packaging and input-gathering fixes.
