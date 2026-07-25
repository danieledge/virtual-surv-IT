# Eval baseline — 0.28.0 (dev → main promotion record)

Scope: golden-slice (live /engage orchestration runs + deterministic scorer + LLM judge)
Date: 2026-07-25
Method: `scripts.eval_engage` — real headless `/engage` sessions in sandboxed repo copies,
LLM user-sim answering every AskUserQuestion gate in persona, scored deterministically
(`scripts.eval_score`) plus the `process-discipline` rubric judge. All runs below executed
AFTER this release's prompt changes (the close-time reconciliation batch) and are therefore
the live evidence for the changed surfaces. Full narrative + adjudications:
`eval-engage-shakedown-2026-07-25.md`; independent 3-lens artifact review:
`artifact-review-2026-07-25.md`.

## Cases (orchestration slice — the surface 0.27.0 could not test)

| Case | Deterministic | Judge | Verdict |
|---|---|---|---|
| process-right-sizing | recall 1.0 · 0 traps · all must-finds | 0.97 PASS | **PASS** (mention-guard verified against a live reproduction of the 0.27.0 trap artifact) |
| process-close-reconciliation | recall 0.8 · 0 traps · all must-finds | 0.885 PASS | **PASS** (reconciliation sweep performed on real seeded drifted files, verified on disk) |
| process-full-lifecycle | recall 1.0 · 0 traps (baseline 093815Z) | 0.96 PASS | **PASS** — clean end-to-end close: 7 dual-rendered artifacts, email at close only, banners stripped |
| process-full-lifecycle (cold resume, 170016Z) | all must-finds · 0 traps | 0.81 PASS | **PASS** — interrupted engagement resumed from START-HERE alone, QA cycle 4 completed, closed clean |

## Headline

- **All four live orchestration verdicts PASS**; zero false-positive traps across every run.
- The unit surface: 306 tests green (scorer, mechanical gate incl. new STALE-DOCSTATUS,
  guards, staged hooks, per-case contracts for all 36 golden cases).
- Two lifecycle attempts at lower caps were truncated by budget/wall-clock and adjudicated
  as truncation with process discipline intact (truthful ⛔/⏳ parking) — recorded in the
  shakedown, not counted as failures of the surface under test.

## Limitations (honest scope)

- Orchestration slice only; the 0.27.0 subagent-slice baseline remains the record for the
  review/coverage/citation case families (those prompts changed only via the shared
  close-checklist references).
- The lifecycle scenario is open-ended and can outgrow any fixed budget (depth varies run to
  run); bounded-evidence-scope wording is a recorded follow-up, not yet applied.
- Judge scores are sonnet-tier single-judge; deterministic recall/trap numbers are the hard
  signal (0.27.0 precedent).

## Verdict

**PASS for promotion** — the surfaces this release changed (close discipline, scorer,
harness, hooks) are all covered by fresh live evidence.
