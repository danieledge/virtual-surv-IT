# Changelog

All notable changes to the compliance-surveillance-team plugin. Dates are absolute.
This is a proof-of-concept; see `docs/house-rules.md` for the evidence state of domain content.

## [0.3.0] — 2026-06-25

### Added — Data-analyst & business-analyst expansion (research-grounded)
- **`tuning-analyst`** agent — surveillance threshold calibration / alert tuning: risk-based
  segmentation, Above-The-Line / Below-The-Line testing, dry-run alerts, FP-rate & alert-to-SAR MI.
  Extended to trade (peer-group/benchmark, RTS 25 timestamp prerequisite) and comms (lexicon/NLP)
  tuning, with the FCA MW79 "four-component, not calibration-only" rule.
- **Workflows** — `/tune-thresholds`, `/validate-tm-model`, `/assess-coverage`,
  `/elicit-requirements`, `/reg-change-impact`, `/analyse-data`, and `/meet-the-team`.
- **Templates (16)** — threshold-tuning-pack, tm-model-validation, surveillance-coverage-assessment,
  trade-scenario-design, lexicon-spec, comms-surveillance-policy; stakeholder-analysis,
  elicitation-requirements, process-map (BPMN), user-stories, uat-plan, reg-change-impact,
  data-dictionary, mi-spec, segmentation-analysis, exploratory-analysis.

### Changed
- **`requirements-analyst` → `business-analyst`** — rebranded and broadened from spec-writer to the
  full BABOK lifecycle (elicitation, stakeholder/process analysis, UAT, traceability, reg-change
  impact, obligation→detection). All references updated repo-wide.
- **Performance review is static-only** for now — profilers/benchmarks removed; findings are
  inference-only (📊 only for explicit coded costs read in source). Re-enable via the consent flow.

### Added — Safety
- **Code-execution gate** (`guard-code-execution.py`) — reviews are static by default; running
  tests/profilers is blocked unless authorised by the `.claude/.exec-consent` marker (written on
  user consent) or `CST_ALLOW_EXEC=1`, behind a prominent intake disclaimer (CLAUDE.md §7).

### Evidence
- AML/TM tuning, FCA Market Watch 79, and the **trade/market-abuse regulatory spine**
  (MAR Art 16(2) / CDR 2016/957 / RTS 24 (2017/580) / RTS 22 (2017/590) / RTS 25) are **verified
  against primary sources** (EUR-Lex, legislation.gov.uk, ESMA).
- **Unverified (flagged):** comms specifics (MiFID II Art 16(7), SEC 17a-4 / FINRA 4511, the
  off-channel sweep), per-scenario tuning practice, and the DA/BA boundary — see `docs/house-rules.md`.

## [0.2.0]

- Modular code-review subsystem (review lenses + scoreboard + evidence-basis tagging + style lane +
  Morgan-challenges-findings + opt-in AI-review pre-commit gate), integrating
  [turingmind-code-review](https://github.com/turingmindai/turingmind-code-review) (MIT).

## [0.1.1]

- Initial plugin packaging and input-gathering fixes.
