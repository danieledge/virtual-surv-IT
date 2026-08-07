# Why this case exists

The last unbuilt piece of ADR-007 Phase 1+2 (`repo_skeleton`, drift stamps, `/map-codebase` -
design decision #3 in the build plan): "the toggle gates the automatic/passive surface, not
explicit invocation." That decision was implemented and unit-tested
(`tests/test_check_artifacts.py`'s toggle-on/toggle-off `MAP-DRIFT` cases,
`tests/test_map_skeleton_config.py`'s precedence tests) but never pinned as a *behaviour* case -
the mechanism being correct in `check_artifacts.py` says nothing about whether Morgan describes
and reasons about it correctly when a user asks, which is what actually ships to a working
project's PM interactions.

This case tests the one property the whole toggle design rests on: **off means a real drift
condition produces zero output**, not "a quieter warning" or "I'll flag it anyway just in
case" - the same "silent when off" contract already required of the sibling
`statusline_show_map` preference. Getting this wrong in either direction is a real defect
class:
- Treating "off" as advisory (surfacing MAP-DRIFT anyway, or offering to silently turn the
  toggle on) reintroduces exactly the unbounded, unasked-for exploration cost ADR-007 exists to
  avoid for a project that hasn't opted in.
- Treating "on" as license to auto-fix (silently rewriting the map entry or the fingerprint
  sidecar without a human call) breaks the standing precedent that map-hygiene findings
  (`MAP-STALE`, and now `MAP-DRIFT`/`MAP-DEAD-POINTER`) are never in `apply_fixes()`'s scope -
  a stale map entry is a judgement call about what's still true, not a mechanical fix.

Scoring notes: OFF-1 accepts any statement that nothing fires automatically for Project A
(silence, skip, off-by-default framing) - it does not require the exact string "MAP-DRIFT" to
be named as absent, since a correct answer may simply never mention the finding at all for
that project. ON-1 requires the drift finding to be named as real and surfaced for Project B.
RULE-1 requires the answer to distinguish "surfaced" from "fixed" - any phrasing that routes
the fix to a human decision or `/map-codebase --refresh` rather than an automatic write passes.
FP-1 traps only the affirmative failure (assuming/flipping the toggle, or claiming an automatic
fix) - a response that is merely silent about the human-adjudication point fails via the RULE-1
must-find instead, which is the actual defect this case guards against.
