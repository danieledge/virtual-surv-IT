# Why this case exists

Live-reported (2026-08-07), in two parts, on the same working project, same command
(`/engage` → deep review + performance review), same target:

1. First run: `review-scorer` (Pip) was delegated to for the context scan, hit an unrelated
   API/gateway error (`tools.0.custom.eager_input_streaming: Extra inputs are not
   permitted` - a gateway rejecting a beta tool-schema field, unrelated to the plugin's own
   code), and Morgan self-corrected: "Model override incompatible with the agent type. I'll
   handle the context scan myself - it's a file listing, PM-level rote work." A reasonable
   one-off recovery from a genuine infrastructure failure.
2. A later run of the *identical* scenario: `review-scorer` was never invoked at all - no
   context-scan delegation, no scoring delegation, no lens-loading narration anywhere in
   the transcript.

`docs/code-review-method.md` states the delegation rule unconditionally: "the review skills
delegate [scoring and context/language detection] to the review-scorer (haiku) agent, for
code-reviewer AND performance-reviewer findings alike." `deep-review/SKILL.md` states it as
two explicit numbered pipeline steps (1: context, delegated; 4: score & filter, delegated).
Neither is a just-in-time reference doc consulted only on failure (unlike the earlier
PROBE_FAILED probe-contract.md gap this session already fixed) - both are always-loaded,
core instructions. A same-command, same-scenario run skipping the delegation entirely is
therefore a genuine instruction-following inconsistency, not a documented alternate path.

This case cannot fix that by adding more prose (the prose is already unconditional and
already always in context) - what it CAN do is make the failure rate measurable. Run
repeatedly via `/run-evals`, a persistently low pass rate here is the evidence needed to
justify a stronger (more mechanical) intervention later; a rare, isolated failure is a
different, lower-priority problem than a systemic one.

## Scoring notes

CONTEXT-1 and SCORE-1 are deliberately two SEPARATE specs (not one "was review-scorer
mentioned anywhere" check) because both delegation moments were missing in the live
failure - a run that delegates only one of the two should still fail this case. SCORE-1
deliberately excludes "review-scorer" from its own keyword list (CONTEXT-1 already covers
the agent name) so a transcript that mentions review-scorer exactly once, only during the
context scan, cannot also satisfy SCORE-1 by accident - it needs its own scoring-stage
evidence (`docs/review/output-format.md`'s Found/Reported/Filtered scoreboard language,
`docs/code-review-method.md`'s "scoring rubric").

Known limitation, shared with every other keyword-scored case in this repo: the normalizer
paraphrases (kept close to the transcript's own wording per its own prompt, but not a
verbatim quote), so this is a reasonable signal, not a perfect mechanical check of "was the
Task/Agent tool literally invoked with subagent_type=review-scorer". PERF-2 is a sanity
floor (performance review happened at all), not the focus of this case.

FP-1 traps the exact self-correction phrasing from the first live report ("I'll handle the
context scan myself") - a legitimate one-off recovery from a genuine tool/API failure, but
also the exact shape a run that skips delegation as a HABIT would produce if it ever
explained itself. A run that delegates correctly from the start has no reason to say this.
