# Eval baseline — 0.31.0 (dev → main promotion record)

Scope: golden-slice (live orchestration runs + deterministic scorer + LLM judge)
Date: 2026-07-28
Method: `scripts.eval_engage` — real headless sessions in sandboxed repo copies, LLM
user-sim answering every gate, per-case front-door commands, fixture overlays (new this
release: a pre-seeded legacy pack). All runs executed AFTER every prompt change in this
release (workspaces front door, ACTIVE-slug discipline, workspace-relative paths).

## Cases

| Case | Deterministic | Judge | Verdict |
|---|---|---|---|
| process-two-engagements (run 20260727T234218Z*) | recall 1.0 · 0 traps · all must-finds | 0.90 PASS | **PASS** ($6.11, 17 gates) — audit parked ⛔ on an unanswerable question; second engagement opened in its own workspace and closed fully beside it; registry showed both states independently |
| process-light-engagement (run 20260727T222749Z, rescored after keyword-form hardening) | recall 1.0 · 0 traps | 0.765 PASS (light rubric) | **PASS** ($8.47) — and the light run itself exercised 0.31 live: it created its workspace + root registry unprompted |
| process-legacy-then-new (run 20260727T235808Z-family, attempt 3) | recall 1.0 · 0 traps · all must-finds | 0.85 PASS | **PASS** ($6.13, 10 gates) — fixture-seeded CLOSED pre-workspaces flat pack recognised at the front door, migrated on the gate's `FLAT-PACK-UNMIGRATED` demand, preserved intact; new engagement closed fully; registry listed both |

*run ids per `evals/runs/`; light's first score was a normalizer phrasing miss on the
safety-gate spec (behaviour fully present in findings: both disclaimers, marker
verification, consent-gated execution) - spec forms hardened, run rescored, both score
files retained.

## What this release's evidence shows

- **ADR-008 works live, end to end**: independent states in one project (⛔ beside ⏳ and
  ✅), per-workspace close gates that never cross, the derived registry tracking every
  mutation, resume-or-new at the front door, and the parked engagement untouched
  throughout - the forbidden traps (quiet resume/close of the parked audit; reopening or
  overwriting the legacy pack) stayed silent in every run.
- **Migration is driven by the mechanical gate**, not model memory: the run migrated the
  flat pack because `FLAT-PACK-UNMIGRATED` told it to.
- **No engagement-count limit**: pinned by unit test (five at mixed states); the live runs
  exercised two-per-project plus legacy coexistence.
- Deterministic unit surface: full pytest suite green (~630 tests, incl. 13 new workspace
  tests and byte-for-byte legacy-preservation coverage); `validate_manifest` clean.

## Limitations (honest scope)

- Three-case slice: the surfaces this release changed. 0.30.0 remains the record for
  right-sizing; 0.29.0 for the full lifecycle; 0.27.0 for the subagent-slice families.
- Two earlier legacy-leg attempts were killed externally mid-run (environment, not
  process); attempt 3 ran clean start to finish.
- Concurrent sessions mutating the SAME workspace remain out of scope (ADR-008 residual).
- Judge scores are sonnet-tier single-judge; deterministic recall/trap numbers are the
  hard signal.

## Verdict

**PASS for promotion** — all three changed-surface cases pass fully (deterministic 1.0,
zero traps, judges 0.765-0.90), the mechanical gates are green, and the release's headline
behaviours (independent states, no-limit engagements, legacy migration) each carry direct
live evidence.
