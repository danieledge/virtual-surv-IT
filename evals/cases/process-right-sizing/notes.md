# Grading notes (NOT shown to the team - do not pass this file to the workflow)

## What a correct response does

- States in one line how many agents will be engaged and why (the right-sizing gate).
- Keeps the set lean for a one-file fix: a builder (rules-developer / Mateo) plus a
  reviewer (code-reviewer / Ravi) - not the roster.

## What a correct response must NOT do

- Reflex full-team fan-out for a trivial, crisply-specified change.

## Trap change log

- FP-2 dropped (2026-07-05): its keywords were bare agent names (tm-sme, ml-engineer,
  tuning-analyst, ...), so a correct answer that names the agents it will NOT engage
  ("no need for tm-sme or ml-engineer here") substring-matched the trap. Engagement-implying
  rephrasings ("engaging tm-sme", "engaged ml-engineer") are still contained in plausible
  correct exclusions ("not engaging tm-sme"), so the trap was dropped rather than reworded.
  Over-engagement short of a full fan-out is now caught qualitatively by the
  process-discipline rubric; the deterministic net keeps FP-1 (full fan-out) and the two
  must-finds (lean statement + builder/reviewer named).
- Known residual: FP-1's "the full team" / "whole team" keywords are still negation-prone
  (a correct "just a builder and a reviewer, not the whole team" would trip them). Left
  unchanged in this pass; a rework should use engagement-asserting phrasings.
