# Eval baseline — 0.29.0 (dev → main promotion record)

Scope: golden-slice (live /engage orchestration runs + deterministic scorer + LLM judge)
Date: 2026-07-26
Method: `scripts.eval_engage` — real headless `/engage` sessions in sandboxed repo copies,
LLM user-sim answering every AskUserQuestion gate in persona, scored deterministically
(`scripts.eval_score`) plus the `process-discipline` rubric judge. All runs executed AFTER
this release's prompt changes (the machine-readable engagement state batch, ADR-006) and are
the live evidence for the changed surface. Independent 3-lens artifact review:
`artifact-review-2026-07-26.md`.

## Cases (orchestration slice)

| Case | Deterministic | Judge | Verdict |
|---|---|---|---|
| process-right-sizing | recall 1.0 · 0 traps · all must-finds | 0.96 PASS | **PASS** ($2.34) |
| process-close-reconciliation | recall 0.6 · 0 traps · all must-finds | 0.94 PASS | **PASS** ($2.23; recall vs 0.8 at 0.28.0 — optional planted items lapsed, no must-find missed; watch item) |
| process-full-lifecycle (3 legs: 170621Z → 181437Z → 193818Z) | final leg recall 1.0 · 0 traps · all must-finds incl. the new STATE-1 | 0.71 FAIL (evidence-tagging 0.15; other dims 0.85–0.95) | **PASS with adjudication** (below) |

## The full-lifecycle adjudication (recorded, not hand-waved)

The engagement closed properly on its third leg (~$102 total: $15 budget truncation, $39
wall-clock truncation, $47.58 close). Deterministic surface: perfect — every must-find
including the new `STATE-1` (valid `engagement-state.json`, fresh render hash), zero traps.
The judge failed the final-leg transcript solely on evidence-tagging. The independent
claims-vs-evidence audit adjudicates that dimension with artifact-level evidence: the
specialist artifacts apply the 📊/🧠 convention rigorously (49 tags in qa-handover, 60 in
review-pass-5) while the PM's summary layer largely does not (~7 in the delivery report, 0
in the email). Per the harness's own rule (deterministic numbers are the hard signal; a
borderline judge score is a prompt to look), the verdict is **pass on substance with a real,
named PM-layer finding** — remediated in-release by a close-checklist/skill restatement of
the PM tag duty, and left on record here for the 0.30 evals to re-measure.

## What the truncations proved (the changed surface, live)

- The state discipline held in a session that had never seen it: state file opened at OPEN,
  mutated throughout, render hash fresh at every probe, truthful ⛔ parking at both
  truncations.
- **Cold resume worked twice, uncoached**: fresh sessions inherited the full outstanding
  list (including subtle carry-items: DST residual risk, named-approver governance actions,
  a QA coverage gap) from `engagement-state.json` + START-HERE alone and continued without
  re-litigating.
- The artifact review caught the feature's own gaps (close reached with `team: []` and all
  rows interim — no mutator existed for either): fixed in-release (`set-team`,
  `finalise-artifacts`, closed-state validation), with tests.

## Headline

- All three orchestration cases pass (one by recorded adjudication); zero false-positive
  traps across every run.
- Unit surface: full pytest suite green including 28 new state tests and the per-case
  contracts; `validate_manifest` clean.
- No fabrication found by the 3-lens artifact review; every load-bearing number verifies on
  disk; QA evidence preserved (the 0.28.0 review's worst finding does not recur).

## Limitations (honest scope)

- Orchestration slice only; the 0.27.0 subagent-slice baseline remains the record for the
  review/coverage/citation families (their prompts changed only via shared references).
- The lifecycle scenario remains open-ended and outgrew two fixed budgets before closing
  (known 0.28.0 limitation, now observed twice more) — the cost spread across cases
  ($2.3 vs $102) is recorded as the standing argument for engagement profiles in 0.30.
- The PM-summary evidence-tagging decay and the outstanding-list-as-ledger habit are named
  team-behaviour findings carried to the 0.30 backlog (details in the artifact review).
- Judge scores are sonnet-tier single-judge; deterministic recall/trap numbers are the hard
  signal.

## Verdict

**PASS for promotion** — the surface this release changed (machine-readable state, render
discipline, state-first hooks, close completeness) is covered by fresh live evidence, the
one judge fail is adjudicated on artifact-level grounds with its remediation shipped, and
the mechanical gates are green.
