# Eval baseline — 0.30.0 (dev → main promotion record)

Scope: golden-slice (live orchestration runs + deterministic scorer + LLM judge)
Date: 2026-07-27
Method: `scripts.eval_engage` — real headless sessions in sandboxed repo copies, LLM
user-sim answering every gate, per-case front-door command (new this release), scored
deterministically plus the rubric judge. Both runs executed AFTER every prompt change in
this release (engage-light including the same-day summary-email reinstatement, the
plugin-mode DoD-resolution briefs, the state schema v2 wording) and are the live evidence
for the changed surface.

## Cases

| Case | Deterministic | Judge | Verdict |
|---|---|---|---|
| process-light-engagement (`/engage-light`, run 20260727T202155Z) | recall 1.0 · 0 traps · all 6 must-finds incl. the short summary email (LIGHT-6) and `profile: light` in the state | 0.83 PASS (process-discipline-light rubric) | **PASS** ($4.30, 5 gates) |
| process-right-sizing (`/engage`, run 20260727T203730Z) | recall 1.0 · 0 traps · all must-finds | 0.94 PASS | **PASS** ($5.82, 7 gates) |

## What this release's evidence shows

- **`/engage-light` works as designed, in its final form**: profile recorded and rendered,
  safety gates untouched, 2-agent team stated out loud, full tests-review-independent-QA
  chain on the delivered code, close via the state machinery, the SHORT Morgan summary email
  present, and NO BRD/FSD/delivery report (the forbidden traps stayed silent). An earlier
  same-day run under the pre-email-ruling prompts (20260727T192018Z, kept) closed correctly
  WITHOUT the email per the rules of its moment — superseded by this run, retained as the
  before/after record.
- **The standard flow did not regress** under the shared prompt changes (delegation-brief
  doc paths, state mutators): right-sizing's best judge score to date (0.94).
- Measured cost spread stands: light build $4.30 vs the 0.29.0 full-lifecycle $102 —
  the profile earns its keep (~13x) while keeping every check.
- Harness upgrades exercised live: per-case workflow commands, subscription-auth sessions,
  the dead-at-birth watchdog (armed, not tripped), `--rescore` side-file persistence.

## Limitations (honest scope)

- Two-case slice: the surfaces this release changed. The 0.29.0 baseline remains the record
  for the full lifecycle / close-reconciliation; 0.27.0 for the subagent-slice families.
- The plugin-mode DoD-resolution fix cannot be exercised by this sandbox (repo-as-project
  mode) — its evidence is the failing live foreign-repo transcript it was written against,
  plus the honest-failure wording now pinned in both verifier agents.
- Wall-clock note: a light BUILD runs ~70 min end to end (safety opening + real code chain
  are the floor); light saves cost and ceremony more than opening minutes. Recorded 0.31
  levers: fold scope into intake, skip the analyser probe when no review is requested.
- Judge scores are sonnet-tier single-judge; deterministic recall/trap numbers are the hard
  signal.

## Verdict

**PASS for promotion** — both changed-surface cases pass fully (deterministic 1.0, zero
traps, judges 0.83/0.94), the mechanical gates are green, and the release's one behavioural
reversal (the email ruling) is covered by fresh post-change evidence.
