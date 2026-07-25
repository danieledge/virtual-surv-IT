# Grading notes - review-main-guard-py

Never shown to the team-under-test.

## Seeded issues

1. **MAIN-1 (line 52)** - `if __name__ == "__main__": unittest.main()` sits mid-file:
   `ChainAnchoringTests` (line 56 onward) is defined after it, so `python
   input_test_alert_window.py` runs 6 of 8 tests, prints OK, and never executes the two
   regression tests. Direct provenance: the 2026-07-25 independent code review found exactly
   this in the process-full-lifecycle baseline delivery (44 of 48 silently run). A correct
   review flags the guard placement and that the trailing tests are silently skipped under
   direct invocation.
2. **TAUT-1 (line 47)** - `test_boundary_semantics_are_inclusive` computes
   `expected = within_window(BASE, boundary)` and then asserts
   `within_window(BASE, boundary) == expected`: the oracle is the function under test, so the
   test can never fail. Same review, AC-12 fixture-decay class.

## The trap

`SUPPRESSION_WINDOW_SECONDS = 600` carries the required rationale + agreement date comment
(repo convention: no bare thresholds), and `test_window_matches_configured_value` is a
legitimate config-guard. Flagging either as a magic number / undocumented threshold is a false
positive. `exclude_keywords` on the trap covers remediation phrasing that merely quotes it.

## Running

Subagent slice (`/run-evals`) - static review, no live /engage needed.
